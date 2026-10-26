"""Private, I/O-free admission for committed QW-r1 writer operations."""
from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, cast
from weakref import WeakKeyDictionary

from pydantic import Field

from ._qdrant_contract import FrozenModel, QdrantConfig, bind_embedding_batch, parse_model
from ._qdrant_manifest import (_Manifest, _Stage, _ReplayResult, _JsonResult, _parse, _snapshot,
    encode_manifest, encode_stage_intent, encode_dense_replay, encode_sparse_replay)
from .contracts import TrustedScope
from .contracts.models import Collection, Identity
from .embeddings import FAKE_PROFILE
from .errors import EmbeddingProfileMismatch, IntegrityViolation, InvalidRequest, UnauthorizedScope


class WriterContext(FrozenModel):
    scope: TrustedScope
    collection: Collection
    document_id: Identity
    intent_id: Identity
    owner_token: str = Field(pattern=r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class StagePlan:
    manifest_sha256: str
    payload_sha256: str
    member_count: int


@dataclass(frozen=True, slots=True)
class StageData:
    manifest: _Manifest
    intent: _Stage
    source: bytes = field(repr=False)
    manifest_encoding: _JsonResult = field(repr=False)
    intent_encoding: _JsonResult = field(repr=False)
    dense: tuple[_ReplayResult, ...] = field(repr=False)
    sparse: tuple[_ReplayResult | None, ...] = field(repr=False)


_PLANS: WeakKeyDictionary[StagePlan, StageData] = WeakKeyDictionary()


def sequence(value: object, maximum: int = 64) -> tuple[Any, ...]:
    if type(value) not in (list, tuple):
        raise InvalidRequest()
    values = cast(list[Any] | tuple[Any, ...], value)
    if not 1 <= len(values) <= maximum:
        raise InvalidRequest()
    return tuple(values)


def context(value: object) -> WriterContext:
    if type(value) is WriterContext:
        value = value.model_dump(mode='json')
    if type(value) is not dict or any(type(key) is not str for key in value) or set(value) != {'scope','collection','document_id','intent_id','owner_token'}:
        raise InvalidRequest()
    raw = dict(value)
    scope_value = raw['scope']
    if type(scope_value) is TrustedScope:
        scope_value = vars(scope_value)
    raw['scope'] = _snapshot(scope_value)
    parsed = parse_model(WriterContext, _snapshot(raw))
    if re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', parsed.owner_token) is None:
        raise InvalidRequest()
    return parsed


def stage_data(plan: object) -> StageData:
    if type(plan) is not StagePlan or plan not in _PLANS:
        raise InvalidRequest()
    return _PLANS[plan]


def issue_stage(data: StageData) -> StagePlan:
    """Internal issuance after native authority has verified the complete graph."""
    plan=StagePlan(data.manifest_encoding.sha256,data.intent_encoding.sha256,len(data.dense))
    _PLANS[plan]=data
    return plan


def prepare_stage(record: object) -> StagePlan:
    """Bind source, intent and original vectors once, without provider calls."""
    if type(record) is not dict:
        raise InvalidRequest()
    data = cast(dict[str, Any], record)
    if any(type(key) is not str for key in data):
        raise InvalidRequest()
    if set(data) - {'manifest', 'canonical_text', 'intent', 'dense_batches', 'dense_vectors', 'sparse_vectors'}:
        raise InvalidRequest()
    if not {'manifest', 'canonical_text', 'intent'} <= set(data):
        raise InvalidRequest()
    if ('dense_batches' in data) == ('dense_vectors' in data):
        raise InvalidRequest()
    manifest_encoding = encode_manifest(data['manifest'], data['canonical_text'])
    manifest = _parse(_Manifest, data['manifest'])
    intent_encoding = encode_stage_intent(data['intent'])
    intent = _parse(_Stage, data['intent'])
    if (intent.manifest_sha256 != manifest_encoding.sha256 or
        (intent.tenant_id, intent.collection, intent.document_id) !=
        (manifest.tenant_id, manifest.collection, manifest.document_id)):
        raise IntegrityViolation()
    originals: list[object] = []
    if 'dense_batches' in data:
        for raw in sequence(data['dense_batches'], 8):
            batch = bind_embedding_batch(raw, manifest.dense_profile)
            originals.extend(batch.vectors)
            if len(originals) > 64:
                raise InvalidRequest()
    else:
        if manifest.dense_profile.model_dump() != FAKE_PROFILE.model_dump():
            raise EmbeddingProfileMismatch()
        originals.extend(sequence(data['dense_vectors']))
    if len(originals) != len(manifest.members):
        raise InvalidRequest()
    dense = tuple(encode_dense_replay(vector, manifest.dense_profile) for vector in originals)
    sparse: tuple[_ReplayResult | None, ...]
    if manifest.sparse_profile is None:
        if data.get('sparse_vectors') is not None:
            raise InvalidRequest()
        sparse = (None,) * len(dense)
    else:
        arrays = sequence(data.get('sparse_vectors'))
        if len(arrays) != len(dense):
            raise InvalidRequest()
        encoded: list[_ReplayResult | None] = []
        for vector in arrays:
            if type(vector) is not dict or any(type(key) is not str for key in vector) or set(vector) != {'indices', 'values'}:
                raise InvalidRequest()
            encoded.append(encode_sparse_replay(vector['indices'], vector['values'], manifest.sparse_profile))
        sparse = tuple(encoded)
    for member, dense_item, sparse_item in zip(manifest.members, dense, sparse, strict=True):
        if member.dense_input_sha256 != dense_item.input_sha256 or member.sparse_input_sha256 != (
            sparse_item.input_sha256 if sparse_item is not None else None
        ):
            raise IntegrityViolation()
    plan = StagePlan(manifest_encoding.sha256, intent_encoding.sha256, len(dense))
    text = data['canonical_text']
    assert type(text) is str
    _PLANS[plan] = StageData(manifest, intent, text.encode('utf-8'), manifest_encoding,
                              intent_encoding, dense, sparse)
    return plan


def bind_stage(plan: object, scope: object, owner_token: object, config: QdrantConfig) -> tuple[StageData, WriterContext]:
    bound = stage_data(plan)
    manifest = bound.manifest
    parsed = context({'scope': scope, 'collection': manifest.collection, 'document_id': manifest.document_id,
                      'intent_id': bound.intent.intent_id, 'owner_token': owner_token})
    if parsed.scope.tenant_id != manifest.tenant_id or parsed.scope.authorization_revision != bound.intent.expected_authorization_revision:
        raise UnauthorizedScope()
    if (manifest.backend_namespace != config.backend_namespace or
        manifest.physical_collection != config.physical_collection or
        manifest.collection_incarnation != config.collection_incarnation or
        manifest.dense_profile != config.dense_profile or manifest.sparse_profile != config.sparse_profile):
        raise IntegrityViolation()
    return bound, parsed
