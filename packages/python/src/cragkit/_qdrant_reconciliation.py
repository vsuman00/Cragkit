"""Authority-bound readback receipts; no SQL settlement or ordinary reopening."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, TYPE_CHECKING, Protocol, cast
from collections.abc import Mapping
from weakref import WeakKeyDictionary

from ._qdrant_contract import CandidatePayload, decode_response, parse_model
from ._qdrant_source import metadata_guard
from ._qdrant_supervisor import ManagedQdrantSupervisor
from ._qdrant_transport import deadline_value
from ._qdrant_vectors import _DenseVector, _SparseVector, verify_dense_readback, verify_sparse_readback
from .errors import (CragkitError, DeadlineExceeded, IntegrityViolation, InvalidRequest,
                     ProviderUnavailable, UnsupportedCapability, UnauthorizedScope)

if TYPE_CHECKING:
    from ._qdrant_writer import PostgresQdrantWriter


class ExpectedProjection:
    __slots__ = ('__weakref__',)

    def __repr__(self) -> str:
        return 'ExpectedProjection()'

    def __reduce__(self) -> Any:
        raise TypeError('Projections cannot be serialized')


class ReconciliationReceipt:
    __slots__ = ('__weakref__',)

    def __repr__(self) -> str:
        return 'ReconciliationReceipt()'

    def __reduce__(self) -> Any:
        raise TypeError('Receipts cannot be serialized')


@dataclass(frozen=True, slots=True)
class ExpectedPoint:
    point_id: str
    payload: CandidatePayload
    dense: _DenseVector
    sparse: _SparseVector | None


_PROJECTIONS: WeakKeyDictionary[
    ExpectedProjection, tuple[object, Mapping[str, Any]]
] = WeakKeyDictionary()
_RECEIPTS: WeakKeyDictionary[
    ReconciliationReceipt, tuple[object, object, Mapping[str, Any]]
] = WeakKeyDictionary()
_UUID = re.compile('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
_PHYSICAL = (
    'instance_id', 'storage_identity', 'supervisor_id', 'recovery_id',
    'old_epoch', 'new_epoch', 'credential_generation',
)


def physical_binding(value: object) -> Mapping[str, Any]:
    # Native supervisor accessors return a mapping proxy over their own plain
    # dictionary; verifier snapshots that trusted result before this boundary.
    if type(value) is not dict:
        raise InvalidRequest()
    metadata_guard(value)
    if set(value) != set(_PHYSICAL):
        raise InvalidRequest()
    for key in _PHYSICAL:
        item = value[key]
        if key in ('old_epoch', 'new_epoch'):
            if (type(item) not in (int, float)
                    or not 1 <= item <= 9007199254740991 or int(item) != item):
                raise InvalidRequest()
        elif (type(item) is not str or not item.strip(' \t\r\n\v\f')
              or '\0' in item or len(item.encode('utf-8')) > 256):
            raise InvalidRequest()
    if value['new_epoch'] != value['old_epoch'] + 1:
        raise InvalidRequest()
    return MappingProxyType({
        key: int(value[key]) if key.endswith('_epoch') else value[key]
        for key in _PHYSICAL
    })


def issue_projection(writer: object, data: dict[str, Any]) -> ExpectedProjection:
    projection = ExpectedProjection()
    _PROJECTIONS[projection] = (writer, MappingProxyType(dict(data)))
    return projection


def projection_data(projection: object, writer: object) -> Mapping[str, Any]:
    if (type(projection) is not ExpectedProjection or projection not in _PROJECTIONS
            or _PROJECTIONS[projection][0] is not writer):
        raise InvalidRequest()
    return _PROJECTIONS[projection][1]


def receipt_data(receipt: object, verifier: object) -> Mapping[str, Any]:
    if (type(receipt) is not ReconciliationReceipt or receipt not in _RECEIPTS
            or _RECEIPTS[receipt][0] is not verifier):
        raise InvalidRequest()
    assert isinstance(verifier, QdrantReconciliationVerifier)
    _, proof, data = _RECEIPTS[receipt]
    current = dict(verifier.supervisor.recovery_binding(proof))
    if current != dict(data['physical_binding']):
        raise UnsupportedCapability()
    return data


def witness(data: Mapping[str, Any]) -> tuple[Any, ...]:
    context = data['context']
    physical = data['physical_binding']
    points = sorted(data['points'], key=lambda point: point.point_id)
    authority = data['authority']
    members = tuple(
        (point.point_id, point.dense.input_sha256,
         point.sparse.input_sha256 if point.sparse else None)
        for point in points
    )
    authorization = (
        tuple(sorted(set(authority['principal_ids']), key=lambda item: item.encode('utf-8'))),
        tuple(sorted(set(authority['grant_ids']), key=lambda item: item.encode('utf-8'))),
        authority['language'], authority['kind'], authority['tag'],
    )
    return (
        'cragkit.qdrant.readback.v1', physical['instance_id'], physical['storage_identity'],
        physical['supervisor_id'], physical['recovery_id'], str(physical['old_epoch']),
        str(physical['new_epoch']), physical['credential_generation'], context.scope.tenant_id,
        context.collection, context.document_id, context.intent_id, context.owner_token,
        data['revision_id'], data['generation_id'], data['manifest_sha256'],
        data['authorization_revision'], str(data['mutation_epoch']), data['active_generation_id'],
        'true' if data['tombstoned'] else 'false', members, authorization,
    )


def finalize_projection(writer: object, data: dict[str, Any]) -> ExpectedProjection:
    data['points'] = tuple(sorted(data['points'], key=lambda point: point.point_id))
    data['point_ids'] = tuple(point.point_id for point in data['points'])
    data['witness'] = witness(data)
    del data['authority']
    encoded = json.dumps(
        data['witness'], ensure_ascii=False, separators=(',', ':'), allow_nan=False,
    ).encode('utf-8')
    data['encoded_bytes'] = encoded
    data['readback_sha256'] = hashlib.sha256(encoded).hexdigest()
    return issue_projection(writer, data)


def _safe(error: Exception) -> CragkitError:
    for kind in (DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable,
                 UnsupportedCapability, UnauthorizedScope):
        if type(error) is kind:
            return kind()
    return ProviderUnavailable()


class _ReadbackTransport(Protocol):
    async def request(self, method: str, path: str, *, body: bytes,
                      deadline: float, max_response_bytes: int) -> bytes: ...

    async def close(self) -> None: ...


class _Readback:
    def __init__(self, transport: _ReadbackTransport, deadline: float) -> None:
        self.transport = transport
        self.deadline = deadline
        self.calls = 0
        self.response_bytes = 0

    async def request(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if self.calls >= 17 or self.response_bytes >= 8388608:
            raise ProviderUnavailable()
        self.calls += 1
        encoded = json.dumps(body, separators=(',', ':'), allow_nan=False).encode('utf-8')
        remaining = min(1048576, 8388608 - self.response_bytes)
        raw = await self.transport.request(
            'POST', path, body=encoded, deadline=self.deadline, max_response_bytes=remaining,
        )
        if type(raw) is not bytes or len(raw) > 1048576:
            raise IntegrityViolation()
        self.response_bytes += len(raw)
        if self.response_bytes > 8388608:
            raise ProviderUnavailable()
        value = decode_response(raw)
        if type(value) is not dict or value.get('status') != 'ok':
            raise IntegrityViolation()
        return cast(dict[str, Any], value)


def _verify_point(value: object, expected: dict[str, ExpectedPoint]) -> str:
    if (type(value) is not dict or not {'id', 'payload', 'vector'} <= set(value)
            or set(value) - {'id', 'payload', 'vector', 'shard_key'}):
        raise IntegrityViolation()
    if value.get('shard_key') is not None:
        raise IntegrityViolation()
    identity = value['id']
    if (type(identity) is not str or _UUID.fullmatch(identity) is None
            or identity not in expected):
        raise IntegrityViolation()
    target = expected[identity]
    try:
        metadata_guard(value['payload'])
        payload = parse_model(CandidatePayload, value['payload'])
    except InvalidRequest:
        raise IntegrityViolation() from None
    if payload.model_dump(mode='json') != target.payload.model_dump(mode='json'):
        raise IntegrityViolation()
    vectors = value['vector']
    names = {'dense'} | ({'sparse'} if target.sparse is not None else set())
    if type(vectors) is not dict or set(vectors) != names:
        raise IntegrityViolation()
    verify_dense_readback(target.dense, vectors['dense'])
    if target.sparse is not None:
        sparse = vectors['sparse']
        if type(sparse) is not dict or set(sparse) != {'indices', 'values'}:
            raise IntegrityViolation()
        verify_sparse_readback(target.sparse, sparse['indices'], sparse['values'])
    return identity


async def _verify_readback(readback: _Readback, path: str, data: Mapping[str, Any]) -> None:
    expected = {point.point_id: point for point in data['points']}
    identities = tuple(sorted(expected))
    for start in range(0, len(identities), 8):
        batch = identities[start:start + 8]
        response = await readback.request(path, {
            'ids': batch, 'with_payload': True, 'with_vector': True,
        })
        points = response.get('result')
        if type(points) is not list or len(points) > 8:
            raise IntegrityViolation()
        if data['tombstoned']:
            if points:
                raise IntegrityViolation()
        else:
            observed = [_verify_point(point, expected) for point in points]
            if len(set(observed)) != len(observed) or set(observed) != set(batch):
                raise IntegrityViolation()

    sample = data['points'][0].payload
    fields = (
        'backend_namespace', 'physical_collection', 'collection_incarnation', 'tenant_id',
        'collection', 'document_id', 'revision_id', 'generation_id',
    )
    filters = [{'key': field, 'match': {'value': getattr(sample, field)}} for field in fields]
    offset: str | None = None
    offsets: set[str] = set()
    seen: set[str] = set()
    for _ in range(9):
        body = {'filter': {'must': filters}, 'limit': 8,
                'with_payload': True, 'with_vector': True}
        if offset is not None:
            body['offset'] = offset
        response = await readback.request(path + '/scroll', body)
        result = response.get('result')
        if (type(result) is not dict or set(result) != {'points', 'next_page_offset'}
                or type(result['points']) is not list or len(result['points']) > 8):
            raise IntegrityViolation()
        points = result['points']
        if data['tombstoned'] and points:
            raise IntegrityViolation()
        for point in points:
            identity = _verify_point(point, expected)
            if identity in seen:
                raise IntegrityViolation()
            seen.add(identity)
            if len(seen) > 64:
                raise IntegrityViolation()
        following = result['next_page_offset']
        if following is None:
            if not data['tombstoned'] and seen != set(identities):
                raise IntegrityViolation()
            return
        if not points:
            raise IntegrityViolation()
        if (type(following) is not str or _UUID.fullmatch(following) is None
                or following in offsets):
            raise IntegrityViolation()
        offsets.add(following)
        offset = following
    raise ProviderUnavailable()


class QdrantReconciliationVerifier:
    def __init__(self, writer: PostgresQdrantWriter,
                 supervisor: ManagedQdrantSupervisor) -> None:
        from ._qdrant_writer import PostgresQdrantWriter
        if type(writer) is not PostgresQdrantWriter or type(supervisor) is not ManagedQdrantSupervisor:
            raise InvalidRequest()
        self.writer = writer
        self.supervisor = supervisor
        self._active: asyncio.Task[Any] | None = None

    async def verify(self, proof: object, context: object, *,
                     deadline: float) -> ReconciliationReceipt:
        deadline = deadline_value(deadline)
        if self._active is not None:
            raise ProviderUnavailable()
        self._active = asyncio.current_task()
        handle = None
        try:
            async with asyncio.timeout_at(deadline):
                physical = dict(self.supervisor.recovery_binding(proof))
                projection = await self.writer.project_stage(context, physical, deadline=deadline)
                data = projection_data(projection, self.writer)
                projected_context = data['context']
                binding = {
                    'intent_id': projected_context.intent_id,
                    'owner_token': projected_context.owner_token,
                    'epoch': physical['new_epoch'],
                    'dispatch_id': 'readback-' + data['readback_sha256'][:32],
                    'recovery_id': physical['recovery_id'],
                }
                capability = self.supervisor.issue_recovery_attempt(proof, binding, deadline=deadline)
                handle = self.supervisor.transport_for(capability)
                path = '/collections/' + self.writer.config.physical_collection + '/points'
                await _verify_readback(_Readback(handle, deadline), path, data)
                await handle.close()
                handle = None
                await self.writer.validate_projection(projection, deadline=deadline)
                if dict(self.supervisor.recovery_binding(proof)) != physical:
                    raise UnsupportedCapability()
                deadline_value(deadline)
                fields = (
                    'context', 'physical_binding', 'manifest_sha256', 'revision_id',
                    'generation_id', 'authorization_revision', 'mutation_epoch',
                    'active_generation_id', 'tombstoned', 'point_ids', 'readback_sha256',
                    'witness', 'encoded_bytes',
                )
                result = {key: data[key] for key in fields}
                result['projection'] = projection
                result['sha256'] = data['readback_sha256']
                receipt = ReconciliationReceipt()
                _RECEIPTS[receipt] = (self, proof, MappingProxyType(result))
                return receipt
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise DeadlineExceeded() from None
        except Exception as error:
            raise _safe(error) from None
        finally:
            try:
                if handle is not None:
                    async with asyncio.timeout(1):
                        await handle.close()
            except Exception:
                raise ProviderUnavailable() from None
            finally:
                self._active = None
