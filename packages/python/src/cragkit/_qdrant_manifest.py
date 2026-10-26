"""Pure QW-r1 content identity and original-vector replay; no authority claims."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import re
import struct
from typing import Annotated, Any, Literal, TypeVar, cast

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from ._qdrant_contract import DenseProfile, SparseProfile, SPARSE_PROFILE, point_id
from ._qdrant_vectors import _DenseVector, _SparseVector, _numbers, encode_dense, encode_sparse
from .contracts._validation import integer
from .contracts.models import Collection, Identity
from .embeddings import FAKE_PROFILE, OPENAI_PROFILE
from .errors import EmbeddingProfileMismatch, IntegrityViolation, InvalidRequest, UnsupportedCapability


_SOURCE_LIMIT = 16777216
_JSON_LIMIT = 1048576
_REPLAY_DOMAIN = b'cragkit.qdrant.replay.v1\0'
_DENSE_FIELDS = ('profile_id', 'provider', 'model', 'dimensions', 'tokenizer', 'normalization')
_SPARSE_FIELDS = ('profile_id', 'encoder', 'model', 'revision', 'vocabulary', 'preprocessing',
                  'weighting', 'corpus_statistics_revision')
_HASH = re.compile(r'^[0-9a-f]{64}$')
_Safe = Annotated[int, BeforeValidator(integer), Field(ge=0, le=9007199254740991)]
_Sha = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


def _sequence(value: object) -> tuple[Any, ...]:
    if type(value) not in (list, tuple):
        raise ValueError('Invalid sequence')
    return tuple(cast(list[Any] | tuple[Any, ...], value))


def _metadata(value: object) -> object:
    if value is not None and (type(value) is not str or '\0' in value):
        raise ValueError('Invalid metadata')
    return value


_Metadata = Annotated[str | None, BeforeValidator(_metadata)]
_Acl = Annotated[tuple[Identity, ...], BeforeValidator(_sequence), Field(max_length=64)]


class _Model(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid', allow_inf_nan=False,
                              revalidate_instances='always')


class _Member(_Model):
    chunk_id: Identity
    point_id: Annotated[str, Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')]
    start_byte: _Safe
    end_byte: _Safe
    text_sha256: _Sha
    dense_input_sha256: _Sha
    sparse_input_sha256: _Sha | None


class _Manifest(_Model):
    backend_namespace: Identity
    physical_collection: Annotated[str, Field(pattern=r'^[A-Za-z][A-Za-z0-9_-]{0,63}$')]
    collection_incarnation: Identity
    tenant_id: Identity
    collection: Collection
    document_id: Identity
    revision_id: Identity
    generation_id: Identity
    source_sha256: _Sha
    source_bytes: Annotated[int, BeforeValidator(integer), Field(ge=1, le=_SOURCE_LIMIT)]
    source_locator: Identity
    parser_id: Identity
    chunker_profile: Identity
    dense_profile: DenseProfile
    sparse_profile: SparseProfile | None
    members: Annotated[tuple[_Member, ...], BeforeValidator(_sequence), Field(min_length=1, max_length=64)]


class _Authorization(_Model):
    authorization_revision: Identity
    principal_ids: _Acl
    grant_ids: _Acl
    language: _Metadata
    kind: _Metadata
    tag: _Metadata
    tombstoned: bool


class _Intent(_Model):
    intent_id: Identity
    tenant_id: Identity
    collection: Collection
    document_id: Identity
    expected_authorization_revision: Identity
    expected_mutation_epoch: _Safe


class _Stage(_Intent):
    manifest_sha256: _Sha
    expected_active_generation_id: Identity | None
    initial_authorization: _Authorization | None


class _Security(_Intent):
    action: Literal['update_authorization', 'tombstone']
    authorization: _Authorization


class _Purge(_Intent):
    tombstone_intent_payload_sha256: _Sha


@dataclass(frozen=True, slots=True)
class _JsonResult:
    value: tuple[Any, ...]
    encoded_bytes: bytes
    sha256: str


@dataclass(frozen=True, slots=True)
class _ReplayResult:
    blob: bytes
    blob_sha256: str
    input_sha256: str
    encoded: _DenseVector | _SparseVector


def _snapshot(value: object) -> object:
    """Bound metadata before copying strings or traversing arbitrary containers."""
    active: set[int] = set()
    nodes = 0

    def visit(item: object, depth: int) -> Any:
        nonlocal nodes
        nodes += 1
        if nodes > 4096 or depth > 32:
            raise InvalidRequest()
        if type(item) is str:
            if len(item) > 1024:
                raise InvalidRequest()
            try:
                if len(item.encode('utf-8')) > 1024:
                    raise InvalidRequest()
            except UnicodeError:
                raise InvalidRequest() from None
            return item
        if item is None or type(item) is bool:
            return item
        if type(item) in (int, float):
            number = cast(int | float, item)
            if not -9007199254740991 <= number <= 9007199254740991 or not math.isfinite(number):
                raise InvalidRequest()
            return number
        if type(item) not in (dict, list, tuple) or id(item) in active:
            raise InvalidRequest()
        container = cast(dict[object, object] | list[object] | tuple[object, ...], item)
        if len(container) > 4096:
            raise InvalidRequest()
        active.add(id(item))
        try:
            if type(item) is dict:
                result: dict[str, object] = {}
                for key, child in cast(dict[object, object], item).items():
                    if type(key) is not str or len(key) > 256:
                        raise InvalidRequest()
                    try:
                        if len(key.encode('utf-8')) > 256:
                            raise InvalidRequest()
                    except UnicodeError:
                        raise InvalidRequest() from None
                    result[key] = visit(child, depth + 1)
                return result
            return [visit(child, depth + 1) for child in cast(list[object] | tuple[object, ...], item)]
        finally:
            active.remove(id(item))

    return visit(value, 0)


_M = TypeVar('_M', bound=_Model)


def _parse(model: type[_M], value: object) -> _M:
    try:
        return model.model_validate(_snapshot(value))
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise InvalidRequest() from None


def _result(value: tuple[Any, ...]) -> _JsonResult:
    encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(encoded) > _JSON_LIMIT:
        raise InvalidRequest()
    return _JsonResult(value, encoded, hashlib.sha256(encoded).hexdigest())


def _source(text: object) -> bytes:
    if type(text) is not str or not 1 <= len(text) <= _SOURCE_LIMIT:
        raise InvalidRequest()
    count = 0
    try:
        for offset in range(0, len(text), 4096):
            count += len(text[offset:offset + 4096].encode('utf-8'))
            if count > _SOURCE_LIMIT:
                raise InvalidRequest()
        return text.encode('utf-8')
    except UnicodeError:
        raise InvalidRequest() from None


def _profiles(record: _Manifest) -> tuple[tuple[tuple[str, str], ...], tuple[tuple[str, str], ...] | None]:
    dense = record.dense_profile.model_dump()
    if dense not in (FAKE_PROFILE.model_dump(), OPENAI_PROFILE.model_dump()):
        raise UnsupportedCapability()
    if record.sparse_profile is not None and (
        record.sparse_profile != SPARSE_PROFILE or dense != FAKE_PROFILE.model_dump()
    ):
        raise UnsupportedCapability()
    dense_pairs = tuple((key, str(dense[key])) for key in _DENSE_FIELDS)
    sparse_pairs = None
    if record.sparse_profile is not None:
        sparse = record.sparse_profile.model_dump()
        sparse_pairs = tuple((key, str(sparse[key])) for key in _SPARSE_FIELDS)
    return dense_pairs, sparse_pairs


def encode_manifest(record: object, canonical_text: object) -> _JsonResult:
    """Verify exact source/member metadata and identify the declared vector seals."""
    parsed = _parse(_Manifest, record)
    dense_pairs, sparse_pairs = _profiles(parsed)
    source = _source(canonical_text)
    if len(source) != parsed.source_bytes or hashlib.sha256(source).hexdigest() != parsed.source_sha256:
        raise IntegrityViolation()
    chunks: set[str] = set()
    points: set[str] = set()
    members: list[tuple[Any, ...]] = []
    sparse_id = parsed.sparse_profile.profile_id if parsed.sparse_profile is not None else ''
    for member in sorted(parsed.members, key=lambda item: item.chunk_id.encode('utf-8')):
        identity = ('cragkit.qdrant.point.v1', parsed.backend_namespace, parsed.physical_collection,
                    parsed.collection_incarnation, parsed.tenant_id, parsed.collection,
                    parsed.document_id, parsed.revision_id, parsed.generation_id,
                    member.chunk_id, parsed.dense_profile.profile_id, sparse_id)
        if member.chunk_id in chunks or member.point_id in points or member.point_id != point_id(identity):
            raise IntegrityViolation()
        chunks.add(member.chunk_id)
        points.add(member.point_id)
        if not 0 <= member.start_byte < member.end_byte <= len(source):
            raise IntegrityViolation()
        if member.end_byte - member.start_byte > 32768:
            raise InvalidRequest()
        excerpt = source[member.start_byte:member.end_byte]
        try:
            excerpt.decode('utf-8')
        except UnicodeError:
            raise IntegrityViolation() from None
        if hashlib.sha256(excerpt).hexdigest() != member.text_sha256:
            raise IntegrityViolation()
        if (member.sparse_input_sha256 is None) != (parsed.sparse_profile is None):
            raise IntegrityViolation()
        members.append((identity, member.point_id, str(member.start_byte), str(member.end_byte),
                        member.text_sha256, member.dense_input_sha256, member.sparse_input_sha256))
    return _result(('cragkit.qdrant.manifest.v1', parsed.backend_namespace, parsed.physical_collection,
                    parsed.collection_incarnation, parsed.tenant_id, parsed.collection,
                    parsed.document_id, parsed.revision_id, parsed.generation_id,
                    parsed.source_sha256, str(parsed.source_bytes), parsed.source_locator,
                    parsed.parser_id, parsed.chunker_profile, dense_pairs, sparse_pairs,
                    str(len(members)), tuple(members)))


def _authorization(value: _Authorization) -> tuple[Any, ...]:
    return (value.authorization_revision,
            tuple(sorted(set(value.principal_ids), key=lambda item: item.encode('utf-8'))),
            tuple(sorted(set(value.grant_ids), key=lambda item: item.encode('utf-8'))),
            value.language, value.kind, value.tag, 'true' if value.tombstoned else 'false')


def encode_stage_intent(record: object) -> _JsonResult:
    parsed = _parse(_Stage, record)
    initial = parsed.initial_authorization
    if initial is not None and (parsed.expected_active_generation_id is not None
        or parsed.expected_mutation_epoch != 1 or initial.tombstoned
        or initial.authorization_revision != parsed.expected_authorization_revision):
        raise InvalidRequest()
    return _result(('cragkit.qdrant.intent.v1', 'stage', parsed.intent_id, parsed.tenant_id,
                    parsed.collection, parsed.document_id, parsed.manifest_sha256,
                    parsed.expected_active_generation_id, parsed.expected_authorization_revision,
                    str(parsed.expected_mutation_epoch), _authorization(initial) if initial is not None else None))


def encode_security_intent(record: object) -> _JsonResult:
    parsed = _parse(_Security, record)
    if parsed.action == 'tombstone' and not parsed.authorization.tombstoned:
        raise InvalidRequest()
    return _result(('cragkit.qdrant.intent.v1', parsed.action, parsed.intent_id, parsed.tenant_id,
                    parsed.collection, parsed.document_id, parsed.expected_authorization_revision,
                    str(parsed.expected_mutation_epoch), _authorization(parsed.authorization)))


def encode_purge_intent(record: object) -> _JsonResult:
    parsed = _parse(_Purge, record)
    return _result(('cragkit.qdrant.intent.v1', 'purge', parsed.intent_id, parsed.tenant_id,
                    parsed.collection, parsed.document_id, parsed.tombstone_intent_payload_sha256,
                    parsed.expected_authorization_revision, str(parsed.expected_mutation_epoch)))


def _blob(kind: Literal['dense', 'sparse'], original: tuple[float, ...],
          indices: tuple[int, ...] | None = None) -> bytes:
    name = kind.encode('ascii')
    parts = [_REPLAY_DOMAIN, struct.pack('<I', len(name)), name, struct.pack('<I', len(original))]
    if indices is not None:
        parts.append(struct.pack(f'<{len(indices)}I', *indices))
    parts.append(struct.pack(f'<{len(original)}d', *original))
    return b''.join(parts)


def encode_dense_replay(original: object, profile: object) -> _ReplayResult:
    values = tuple(_numbers(original, minimum=1536, maximum=1536))
    encoded = encode_dense(values, profile)
    blob = _blob('dense', values)
    return _ReplayResult(blob, hashlib.sha256(blob).hexdigest(), encoded.input_sha256, encoded)


def encode_sparse_replay(indices: object, original: object, profile: object) -> _ReplayResult:
    checked_indices = tuple(_numbers(indices, minimum=1, maximum=16))
    values = tuple(_numbers(original, minimum=1, maximum=16))
    encoded = encode_sparse(checked_indices, values, profile)
    blob = _blob('sparse', values, encoded.indices)
    return _ReplayResult(blob, hashlib.sha256(blob).hexdigest(), encoded.input_sha256, encoded)


def _restore(kind: Literal['dense', 'sparse'], blob: object, expected_blob_sha256: object,
             expected_input_sha256: object, profile: object) -> _DenseVector | _SparseVector:
    try:
        cap = 12326 if kind == 'dense' else 231
        if type(blob) is not bytes or not 1 <= len(blob) <= cap:
            raise IntegrityViolation()
        for digest in (expected_blob_sha256, expected_input_sha256):
            if type(digest) is not str or len(digest) != 64 or _HASH.fullmatch(digest) is None:
                raise IntegrityViolation()
        if hashlib.sha256(blob).hexdigest() != expected_blob_sha256:
            raise IntegrityViolation()
        name = kind.encode('ascii')
        prefix = _REPLAY_DOMAIN + struct.pack('<I', len(name)) + name
        if not blob.startswith(prefix) or len(blob) < len(prefix) + 4:
            raise IntegrityViolation()
        count = cast(int, struct.unpack_from('<I', blob, len(prefix))[0])
        offset = len(prefix) + 4
        if (kind == 'dense' and count != 1536) or (kind == 'sparse' and not 1 <= count <= 16):
            raise IntegrityViolation()
        if len(blob) != offset + count * (8 if kind == 'dense' else 12):
            raise IntegrityViolation()
        indices: tuple[int, ...] = ()
        if kind == 'sparse':
            indices = struct.unpack_from(f'<{count}I', blob, offset)
            offset += count * 4
        values = struct.unpack_from(f'<{count}d', blob, offset)
        encoded = encode_dense(values, profile) if kind == 'dense' else encode_sparse(indices, values, profile)
        if encoded.input_sha256 != expected_input_sha256:
            raise IntegrityViolation()
        return encoded
    except (InvalidRequest, EmbeddingProfileMismatch, UnsupportedCapability, IntegrityViolation):
        raise IntegrityViolation() from None


def restore_dense_replay(blob: object, expected_blob_sha256: object, expected_input_sha256: object,
                         profile: object) -> _DenseVector:
    return cast(_DenseVector, _restore('dense', blob, expected_blob_sha256, expected_input_sha256, profile))


def restore_sparse_replay(blob: object, expected_blob_sha256: object, expected_input_sha256: object,
                          profile: object) -> _SparseVector:
    return cast(_SparseVector, _restore('sparse', blob, expected_blob_sha256, expected_input_sha256, profile))
