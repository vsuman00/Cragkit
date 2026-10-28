"""Bounded full-document diagnostics; no receipt or mutation authority is issued."""
from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, cast
from weakref import WeakKeyDictionary

from ._qdrant_contract import CandidatePayload, QdrantConfig, SparseProfile, SPARSE_PROFILE, decode_response, parse_model, point_id
from ._qdrant_reconciliation import ExpectedPoint, _ReadbackTransport
from ._qdrant_source import metadata_guard
from ._qdrant_transport import deadline_value
from ._qdrant_vectors import _DenseVector, _SparseVector, verify_dense_readback, verify_sparse_readback
from ._qdrant_writer_contract import WriterContext, context
from .embeddings import EmbeddingProfile, FAKE_PROFILE, OPENAI_PROFILE
from .errors import (DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable,
                     UnauthorizedScope, UnsupportedCapability)

_UUID = re.compile('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
_SCOPE = ('backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id')
_MUTABLE = frozenset(('authorization_revision','principal_ids','grant_ids','language','kind','tag'))
_BUDGETS: WeakKeyDictionary[SecurityReadbackBudget, tuple[int, int]] = WeakKeyDictionary()


class SecurityReadbackBudget:
    __slots__ = ('__weakref__',)

    def __init__(self) -> None:
        if type(self) is not SecurityReadbackBudget or self in _BUDGETS:
            raise InvalidRequest()
        _BUDGETS[self] = (8388608,513)

    def __reduce__(self) -> Any:
        raise TypeError('Readback budgets cannot be copied')

    @property
    def remaining_bytes(self) -> int:
        security_readback_budget(self)
        return _BUDGETS[self][0]

    @property
    def remaining_calls(self) -> int:
        security_readback_budget(self)
        return _BUDGETS[self][1]


def security_readback_budget(value: object = None) -> SecurityReadbackBudget:
    if value is None:
        return SecurityReadbackBudget()
    if type(value) is not SecurityReadbackBudget or value not in _BUDGETS:
        raise InvalidRequest()
    return value


def _check(deadline: float) -> None:
    task = asyncio.current_task()
    if task is not None and task.cancelling():
        raise asyncio.CancelledError()
    deadline_value(deadline)


def _normalized(payload: CandidatePayload) -> dict[str, Any]:
    return payload.model_dump(mode='json')


def _expected(config: object, expected: object) -> tuple[QdrantConfig, WriterContext, tuple[ExpectedPoint, ...], bool]:
    metadata_guard(config)
    parsed = parse_model(QdrantConfig,config)
    if parsed.dense_profile.model_dump() not in (FAKE_PROFILE.model_dump(),OPENAI_PROFILE.model_dump()):
        raise UnsupportedCapability()
    if parsed.sparse_profile is not None and (parsed.sparse_profile != SPARSE_PROFILE or
            parsed.dense_profile.model_dump() != FAKE_PROFILE.model_dump()):
        raise UnsupportedCapability()
    if type(expected) not in (dict,MappingProxyType):
        raise InvalidRequest()
    data = cast(Mapping[str, Any],expected)
    if not {'context','point_ids','points','tombstoned'} <= set(data):
        raise InvalidRequest()
    ctx = context(data['context'])
    ids,points = data['point_ids'],data['points']
    if (type(data['tombstoned']) is not bool or type(ids) not in (list,tuple)
            or type(points) not in (list,tuple) or len(ids) > 2048 or len(points) != len(ids)
            or any(type(identity) is not str or _UUID.fullmatch(identity) is None for identity in ids)
            or tuple(ids) != tuple(sorted(set(ids)))):
        raise InvalidRequest()
    generations: dict[tuple[str, str], int] = {}
    for index,target in enumerate(points):
        if type(target) is not ExpectedPoint or target.point_id != ids[index] or type(target.payload) is not CandidatePayload:
            raise InvalidRequest()
        metadata_guard(target.payload)
        payload = parse_model(CandidatePayload,target.payload)
        physical = (payload.backend_namespace,payload.physical_collection,payload.collection_incarnation)
        if (physical != (parsed.backend_namespace,parsed.physical_collection,parsed.collection_incarnation)
                or (payload.tenant_id,payload.collection,payload.document_id)
                != (ctx.scope.tenant_id,ctx.collection,ctx.document_id)
                or payload.authorization_revision != ctx.scope.authorization_revision
                or payload.dense_profile != parsed.dense_profile or payload.dense_profile_id != parsed.dense_profile.profile_id
                or payload.sparse_profile != parsed.sparse_profile
                or payload.sparse_profile_id != (parsed.sparse_profile.profile_id if parsed.sparse_profile else '')
                or payload.start_byte >= payload.end_byte or payload.end_byte-payload.start_byte > 32768
                or target.point_id != point_id(['cragkit.qdrant.point.v1',*physical,payload.tenant_id,payload.collection,
                    payload.document_id,payload.revision_id,payload.generation_id,payload.chunk_id,
                    payload.dense_profile_id,payload.sparse_profile_id])):
            raise InvalidRequest()
        generation = (payload.revision_id,payload.generation_id)
        generations[generation] = generations.get(generation,0)+1
        if generations[generation] > 64:
            raise InvalidRequest()
        if (type(target.dense) is not _DenseVector or type(target.dense.profile) is not EmbeddingProfile
                or target.dense.profile.model_dump() != parsed.dense_profile.model_dump()
                or type(target.dense.values) is not tuple or len(target.dense.values) != 1536
                or any(type(value) not in (int,float) or not math.isfinite(value) for value in target.dense.values)):
            raise InvalidRequest()
        if (parsed.sparse_profile is None) != (target.sparse is None):
            raise InvalidRequest()
        try:
            norm = math.sqrt(sum(value*value for value in target.dense.values))
            verify_dense_readback(target.dense,tuple(value/norm for value in target.dense.values))
            if target.sparse is not None:
                if (type(target.sparse) is not _SparseVector or type(target.sparse.profile) is not SparseProfile
                        or target.sparse.profile != parsed.sparse_profile):
                    raise InvalidRequest()
                verify_sparse_readback(target.sparse,target.sparse.indices,target.sparse.values)
        except (IntegrityViolation,ZeroDivisionError,ValueError,OverflowError):
            raise InvalidRequest() from None
    if len(generations) > 64:
        raise InvalidRequest()
    return parsed,ctx,tuple(points),data['tombstoned']


def _point(value: object, expected: Mapping[str, ExpectedPoint]) -> tuple[str, dict[str, Any], bool]:
    if (type(value) is not dict or not {'id','payload','vector'} <= set(value)
            or set(value)-{'id','payload','vector','shard_key'} or value.get('shard_key') is not None):
        raise IntegrityViolation()
    identity = value['id']
    if type(identity) is not str or identity not in expected:
        raise IntegrityViolation()
    target = expected[identity]
    try:
        metadata_guard(value['payload'])
        payload = parse_model(CandidatePayload,value['payload'])
    except InvalidRequest:
        raise IntegrityViolation() from None
    actual,current = _normalized(payload),_normalized(target.payload)
    if {key:item for key,item in actual.items() if key not in _MUTABLE} != {
            key:item for key,item in current.items() if key not in _MUTABLE}:
        raise IntegrityViolation()
    vectors = value['vector']
    names = {'dense'} | ({'sparse'} if target.sparse is not None else set())
    if type(vectors) is not dict or set(vectors) != names:
        raise IntegrityViolation()
    verify_dense_readback(target.dense,vectors['dense'])
    if target.sparse is not None:
        sparse = vectors['sparse']
        if type(sparse) is not dict or set(sparse) != {'indices','values'}:
            raise IntegrityViolation()
        verify_sparse_readback(target.sparse,sparse['indices'],sparse['values'])
    return identity,actual,actual != current


async def inspect_security_readback(transport: _ReadbackTransport, config: object, expected: object, *,
                                    deadline: float, budget: SecurityReadbackBudget | None = None) -> Mapping[str, tuple[str, ...]]:
    parsed,ctx,points,_ = _expected(config,expected)
    budget = security_readback_budget(budget)
    deadline = deadline_value(deadline)
    targets = {point.point_id:point for point in points}
    identities = tuple(targets)
    path = '/collections/'+parsed.physical_collection+'/points'

    async def request(route: str, body: dict[str, Any]) -> dict[str, Any]:
        _check(deadline)
        remaining,calls = _BUDGETS[budget]
        if remaining <= 0 or calls <= 0:
            raise ProviderUnavailable()
        allowance = min(1048576,remaining)
        encoded = json.dumps(body,separators=(',',':'),allow_nan=False).encode('utf-8')
        _BUDGETS[budget] = (remaining,calls-1)
        try:
            async with asyncio.timeout_at(deadline):
                raw = await transport.request('POST',route,body=encoded,deadline=deadline,max_response_bytes=allowance)
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise DeadlineExceeded() from None
        except Exception as error:
            for kind in (DeadlineExceeded,IntegrityViolation,InvalidRequest,ProviderUnavailable,UnauthorizedScope,UnsupportedCapability):
                if type(error) is kind:
                    raise kind() from None
            raise ProviderUnavailable() from None
        if type(raw) is not bytes:
            raise IntegrityViolation()
        remaining,calls = _BUDGETS[budget]
        _BUDGETS[budget] = (max(0,remaining-len(raw)),calls)
        _check(deadline)
        if len(raw) > remaining:
            raise ProviderUnavailable()
        if len(raw) > allowance:
            raise IntegrityViolation()
        value = decode_response(raw)
        if type(value) is not dict or value.get('status') != 'ok':
            raise IntegrityViolation()
        return cast(dict[str, Any],value)

    retrieved: dict[str, dict[str, Any]] = {}
    stale: set[str] = set()
    for start in range(0,len(identities),8):
        batch = identities[start:start+8]
        response = await request(path,dict(ids=batch,with_payload=True,with_vector=True))
        returned = response.get('result')
        if type(returned) is not list or len(returned) > 8:
            raise IntegrityViolation()
        for value in returned:
            identity,payload,old = _point(value,targets)
            if identity not in batch or identity in retrieved:
                raise IntegrityViolation()
            retrieved[identity] = payload
            if old:stale.add(identity)
    scope_values = dict(backend_namespace=parsed.backend_namespace,physical_collection=parsed.physical_collection,
        collection_incarnation=parsed.collection_incarnation,tenant_id=ctx.scope.tenant_id,
        collection=ctx.collection,document_id=ctx.document_id)
    filters = [dict(key=field,match=dict(value=scope_values[field])) for field in _SCOPE]
    offset = None
    offsets: set[str] = set()
    seen: set[str] = set()
    for _ in range(257):
        body: dict[str, Any] = dict(filter=dict(must=filters),limit=8,with_payload=True,with_vector=True)
        if offset is not None:body['offset'] = offset
        response = await request(path+'/scroll',body)
        result = response.get('result')
        if (type(result) is not dict or set(result) != {'points','next_page_offset'}
                or type(result['points']) is not list or len(result['points']) > 8):
            raise IntegrityViolation()
        for value in result['points']:
            identity,payload,_ = _point(value,targets)
            if identity in seen or identity not in retrieved or payload != retrieved[identity]:
                raise IntegrityViolation()
            seen.add(identity)
        following = result['next_page_offset']
        if following is None:
            if seen != set(retrieved):
                raise IntegrityViolation()
            return MappingProxyType(dict(present_ids=tuple(sorted(seen)),
                missing_ids=tuple(identity for identity in identities if identity not in seen),stale_ids=tuple(sorted(stale))))
        if (not result['points'] or type(following) is not str or _UUID.fullmatch(following) is None or following in offsets):
            raise IntegrityViolation()
        offsets.add(following)
        offset = following
    raise ProviderUnavailable()


async def verify_security_readback(transport: _ReadbackTransport, config: object, expected: object, *,
                                   deadline: float, budget: SecurityReadbackBudget | None = None) -> None:
    _,_,_,tombstoned = _expected(config,expected)
    result = await inspect_security_readback(transport,config,expected,deadline=deadline,budget=budget)
    if (result['present_ids'] if tombstoned else result['missing_ids'] or result['stale_ids']):
        raise IntegrityViolation()
