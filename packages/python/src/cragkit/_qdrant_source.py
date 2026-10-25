"""Pure QS-r1 nomination and canonical source verification."""
from __future__ import annotations

from hashlib import sha256
import json
import math
import re
from typing import Any, Literal

from pydantic import Field

from ._qdrant_contract import (CandidatePayload, DenseProfile, SparseProfile, FrozenModel, QdrantConfig, QdrantNomination,
                               identity_tuple, matches, parse_model, point_id, compile_filter)
from .contracts import Evidence, RetrievalRequest, TrustedScope
from .contracts._validation import input_text
from .errors import IntegrityViolation, InvalidRequest, UnauthorizedScope

MAX_SOURCE_BYTES = 16777216
MAX_EXCERPT_BYTES = 32768
SOURCE_ROW_FIELDS = ('point_id','backend_namespace','physical_collection','collection_incarnation',
    'tenant_id','collection','document_id','revision_id','generation_id','chunk_id','start_byte','end_byte',
    'source_sha256','text_sha256','dense_profile_id','sparse_profile_id','dense_profile','sparse_profile',
    'authorization_revision','mutation_epoch','principal_ids','grant_ids','language','kind','tag',
    'source_locator','parser_id','chunker_profile','source_bytes','canonical_utf8','excerpt_bytes','excerpt_utf8',
    'active_generation_id','generation_published','generation_ever_published','tombstoned')
IMMUTABLE_FIELDS = ('backend_namespace','physical_collection','collection_incarnation','tenant_id','collection',
    'document_id','revision_id','generation_id','chunk_id','start_byte','end_byte','source_sha256','text_sha256',
    'dense_profile_id','sparse_profile_id','dense_profile','sparse_profile')


class PrivateSource(FrozenModel):
    canonical_text: str = Field(repr=False)
    source_sha256: str


class SourceFetch(FrozenModel):
    state: Literal['verified', 'unavailable', 'budget_exhausted']
    evidence: Evidence | None = None
    source_bytes: int = 0
    stale: bool = False
    binding: Any = Field(default=None, exclude=True, repr=False)
    private_source: PrivateSource | None = Field(default=None, exclude=True, repr=False)


def metadata_guard(value: object) -> None:
    """Bound metadata before serializers, UTF-8 encoders or validation copy it."""
    nodes = 0
    active: set[int] = set()
    def visit(item: object, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 4096 or depth > 32:
            raise InvalidRequest()
        if item is None or type(item) in (bool, int):
            return
        if type(item) is float:
            if not math.isfinite(item):
                raise InvalidRequest()
            return
        if type(item) is str:
            if len(item) > 1024:
                raise InvalidRequest()
            try:
                if len(item.encode('utf-8')) > 1024:
                    raise InvalidRequest()
            except UnicodeError:
                raise InvalidRequest() from None
            return
        if id(item) in active:
            raise InvalidRequest()
        active.add(id(item))
        try:
            if type(item) in (QdrantNomination, CandidatePayload, DenseProfile, SparseProfile, QdrantConfig):
                values = vars(item)
            elif type(item) is dict:
                values = item
            elif type(item) in (list, tuple):
                assert isinstance(item, (list, tuple))
                if len(item) > 4096:
                    raise InvalidRequest()
                for child in item:
                    visit(child, depth + 1)
                return
            else:
                raise InvalidRequest()
            if len(values) > 4096:
                raise InvalidRequest()
            for key, child in values.items():
                if type(key) is not str or len(key) > 256:
                    raise InvalidRequest()
                try:
                    if len(key.encode('utf-8')) > 256:
                        raise InvalidRequest()
                except UnicodeError:
                    raise InvalidRequest() from None
                visit(child, depth + 1)
        finally:
            active.remove(id(item))
    visit(value, 0)


def source_limit(value: object) -> int:
    if type(value) not in (int, float):
        raise InvalidRequest()
    assert isinstance(value, (int, float))
    if not 0 <= value <= MAX_SOURCE_BYTES or not math.isfinite(value) or int(value) != value:
        raise InvalidRequest()
    return int(value)


def row_integer(value: object, minimum: int = 0, maximum: int = 9007199254740991) -> int:
    if type(value) is str:
        if len(value) > 16 or re.fullmatch(r'0|[1-9][0-9]*', value) is None:
            raise IntegrityViolation()
        value = int(value)
    if type(value) not in (int, float):
        raise IntegrityViolation()
    assert isinstance(value, (int, float))
    if not minimum <= value <= maximum or not math.isfinite(value) or int(value) != value:
        raise IntegrityViolation()
    return int(value)


def validate_nomination(value: object, request: RetrievalRequest, scope: TrustedScope,
                        config: QdrantConfig) -> QdrantNomination:
    metadata_guard(value)
    nomination: QdrantNomination = parse_model(QdrantNomination, value)
    payload = nomination.payload
    if re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', nomination.point_id) is None:
        raise InvalidRequest()
    if (nomination.branch == 'dense' and (nomination.score_kind != 'cosine_similarity' or not -1.000001 <= nomination.score <= 1.000001)
            or nomination.branch == 'sparse' and nomination.score_kind != 'dot_product'):
        raise InvalidRequest()
    if payload.tenant_id != scope.tenant_id or payload.collection != request.collection:
        raise UnauthorizedScope()
    if (payload.backend_namespace != config.backend_namespace or payload.physical_collection != config.physical_collection
            or payload.collection_incarnation != config.collection_incarnation
            or payload.dense_profile != config.dense_profile or payload.sparse_profile != config.sparse_profile
            or payload.dense_profile_id != config.dense_profile.profile_id
            or payload.sparse_profile_id != (config.sparse_profile.profile_id if config.sparse_profile else '')
            or nomination.point_id != point_id(identity_tuple(payload))
            or nomination.branch == 'sparse' and config.sparse_profile is None):
        raise IntegrityViolation()
    return nomination


def provenance(fetch: SourceFetch, row: dict[str, Any]) -> dict[str, str]:
    return {key: row[key] for key in ('parser_id', 'chunker_profile', 'source_locator')}


def verify_source(nomination: object, rows: object, request: object, scope: object, config: object, *,
                  retained: bool = False, max_source_bytes: int = MAX_SOURCE_BYTES,
                  include_source: bool = False, bound_provenance: dict[str, str] | None = None) -> SourceFetch:
    req: RetrievalRequest = parse_model(RetrievalRequest, request)
    trusted: TrustedScope = parse_model(TrustedScope, scope)
    metadata_guard(config)
    cfg: QdrantConfig = parse_model(QdrantConfig, config)
    nom = validate_nomination(nomination, req, trusted, cfg)
    compile_filter(req, trusted)
    allowance = source_limit(max_source_bytes)
    if type(include_source) is not bool or type(retained) is not bool:
        raise InvalidRequest()
    if type(rows) is not list:
        raise IntegrityViolation()
    if not rows:
        return SourceFetch(state='unavailable')
    if len(rows) != 1 or type(rows[0]) is not dict or set(rows[0]) != set(SOURCE_ROW_FIELDS):
        raise IntegrityViolation()
    row = dict(rows[0])
    try:
        metadata_guard({key: value for key, value in row.items() if key not in ('canonical_utf8', 'excerpt_utf8')})
        for key in ('start_byte', 'end_byte', 'mutation_epoch', 'source_bytes', 'excerpt_bytes'):
            row[key] = row_integer(row[key])
        for key in ('tombstoned', 'generation_published', 'generation_ever_published'):
            if type(row[key]) is not bool:
                raise IntegrityViolation()
        for key in ('parser_id', 'chunker_profile', 'source_locator'):
            if type(row[key]) is not str:
                raise IntegrityViolation()
            input_text(row[key], 256)
        if row['active_generation_id'] is not None:
            if type(row['active_generation_id']) is not str:
                raise IntegrityViolation()
            input_text(row['active_generation_id'], 256)
        payload_data = {key: row[key] for key in CandidatePayload.model_fields
                        if key not in ('language', 'kind', 'tag') or row[key] is not None}
        payload = CandidatePayload.model_validate(payload_data)
        actual = payload.model_dump(mode='json')
        expected = nom.payload.model_dump(mode='json')
        if any(actual[key] != expected[key] for key in IMMUTABLE_FIELDS) or row['point_id'] != nom.point_id:
            raise IntegrityViolation()
        if bound_provenance is not None and any(row[key] != value for key, value in bound_provenance.items()):
            raise IntegrityViolation()
        size = row_integer(row['source_bytes'], 1, MAX_SOURCE_BYTES)
        excerpt_size = row_integer(row['excerpt_bytes'], 1, MAX_EXCERPT_BYTES)
        if not 0 <= payload.start_byte < payload.end_byte <= size or payload.end_byte - payload.start_byte != excerpt_size:
            raise IntegrityViolation()
        canonical_buffer, excerpt_buffer = row['canonical_utf8'], row['excerpt_utf8']
        for buffer, declared in ((canonical_buffer, size), (excerpt_buffer, excerpt_size)):
            if buffer is not None:
                if type(buffer) not in (bytes, bytearray, memoryview):
                    raise IntegrityViolation()
                if type(buffer) is memoryview and (buffer.ndim != 1 or buffer.itemsize != 1):
                    raise IntegrityViolation()
                if len(buffer) != declared:
                    raise IntegrityViolation()
        loaded = len(canonical_buffer) if canonical_buffer is not None else 0
        if loaded > allowance:
            raise IntegrityViolation()
        if (row['tombstoned'] or payload.authorization_revision != trusted.authorization_revision
                or not (trusted.principal_id in payload.principal_ids or set(trusted.grant_ids).intersection(payload.grant_ids))
                or not matches(req.model_dump(mode='json')['required_filters'], actual)
                or not row['generation_ever_published']
                or not retained and (not row['generation_published'] or row['active_generation_id'] != payload.generation_id)):
            return SourceFetch(state='unavailable', source_bytes=loaded)
        if size > allowance:
            if row['canonical_utf8'] is not None or row['excerpt_utf8'] is not None:
                raise IntegrityViolation()
            return SourceFetch(state='budget_exhausted')
        canonical, excerpt = row['canonical_utf8'], row['excerpt_utf8']
        if type(canonical) not in (bytes, memoryview, bytearray) or type(excerpt) not in (bytes, memoryview, bytearray):
            raise IntegrityViolation()
        if (type(canonical) is memoryview and (canonical.ndim != 1 or canonical.itemsize != 1) or
                type(excerpt) is memoryview and (excerpt.ndim != 1 or excerpt.itemsize != 1)):
            raise IntegrityViolation()
        if len(canonical) != size or len(excerpt) != excerpt_size:
            raise IntegrityViolation()
        canonical, excerpt = bytes(canonical), bytes(excerpt)
        canonical_text = canonical.decode('utf-8', errors='strict')
        text = excerpt.decode('utf-8', errors='strict')
        selected = canonical[payload.start_byte:payload.end_byte]
        selected.decode('utf-8', errors='strict')
        if (selected != excerpt or sha256(canonical).hexdigest() != payload.source_sha256
                or sha256(excerpt).hexdigest() != payload.text_sha256):
            raise IntegrityViolation()
        evidence_id = sha256(json.dumps(['cragkit.evidence.v1',payload.tenant_id,payload.collection,
            payload.document_id,payload.revision_id,payload.chunk_id,str(payload.start_byte),str(payload.end_byte),
            payload.text_sha256], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        evidence = Evidence(evidence_id=evidence_id, collection=payload.collection, document_id=payload.document_id,
            revision_id=payload.revision_id, chunk_id=payload.chunk_id, source_locator=row['source_locator'],
            start_byte=payload.start_byte, end_byte=payload.end_byte, text=text,
            source_sha256=payload.source_sha256, text_sha256=payload.text_sha256)
        return SourceFetch(state='verified', evidence=evidence, source_bytes=size,
            stale=row['active_generation_id'] != payload.generation_id,
            private_source=PrivateSource(canonical_text=canonical_text, source_sha256=payload.source_sha256) if include_source else None)
    except (ValueError, TypeError, UnicodeError, OverflowError, KeyError, InvalidRequest):
        raise IntegrityViolation() from None
