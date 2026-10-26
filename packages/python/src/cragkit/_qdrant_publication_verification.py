"""Private ordinary readback receipts; no dispatch, settlement or publication."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, TYPE_CHECKING
from weakref import WeakKeyDictionary

from ._qdrant_reconciliation import _Readback, _ReadbackTransport, _safe, _verify_readback
from ._qdrant_source import metadata_guard
from ._qdrant_supervisor import ManagedQdrantSupervisor
from ._qdrant_transport import deadline_value
from .errors import (DeadlineExceeded, InvalidRequest, ProviderUnavailable,
                     UnsupportedCapability)

if TYPE_CHECKING:
    from ._qdrant_writer import PostgresQdrantWriter


class PublicationProjection:
    __slots__ = ('__weakref__',)

    def __repr__(self) -> str:
        return 'PublicationProjection()'

    def __reduce__(self) -> Any:
        raise TypeError('Projections cannot be serialized')


class PublicationReadbackReceipt:
    __slots__ = ('__weakref__',)

    def __repr__(self) -> str:
        return 'PublicationReadbackReceipt()'

    def __reduce__(self) -> Any:
        raise TypeError('Receipts cannot be serialized')


_PROJECTIONS: WeakKeyDictionary[PublicationProjection, tuple[object, Mapping[str, Any]]] = WeakKeyDictionary()
_RECEIPTS: WeakKeyDictionary[PublicationReadbackReceipt, tuple[object, object, Mapping[str, Any]]] = WeakKeyDictionary()
_VERIFIERS: WeakKeyDictionary[object, tuple[object, ManagedQdrantSupervisor]] = WeakKeyDictionary()
_ATTEMPT_FIELDS = ('instance_id', 'storage_identity', 'supervisor_id', 'epoch',
                   'credential_generation', 'intent_id', 'owner_token', 'dispatch_id')
_CLEANUP_SECONDS = 1.0


async def _close_handle(handle: _ReadbackTransport) -> None:
    try:
        async with asyncio.timeout(_CLEANUP_SECONDS):
            await handle.close()
    except asyncio.CancelledError:
        raise
    except Exception:
        raise ProviderUnavailable() from None


def ordinary_binding(value: object) -> Mapping[str, Any]:
    if type(value) is not dict:
        raise InvalidRequest()
    metadata_guard(value)
    if 'recovery_id' in value:
        raise UnsupportedCapability()
    if set(value) != set(_ATTEMPT_FIELDS):
        raise InvalidRequest()
    for key, item in value.items():
        if key == 'epoch':
            if (type(item) not in (int, float) or not 1 <= item <= 9007199254740991
                    or int(item) != item):
                raise InvalidRequest()
        elif (type(item) is not str or not item.strip(' \t\r\n\v\f')
              or '\0' in item or len(item.encode('utf-8')) > 256):
            raise InvalidRequest()
    if re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                    value['owner_token']) is None:
        raise InvalidRequest()
    return MappingProxyType({**value, 'epoch': int(value['epoch'])})


def publication_projection_data(value: object, writer: object) -> Mapping[str, Any]:
    if (type(value) is not PublicationProjection or value not in _PROJECTIONS
            or _PROJECTIONS[value][0] is not writer):
        raise InvalidRequest()
    return _PROJECTIONS[value][1]


def finalize_publication_projection(writer: object, data: dict[str, Any]) -> PublicationProjection:
    data['points'] = tuple(sorted(data['points'], key=lambda point: point.point_id))
    data['point_ids'] = tuple(point.point_id for point in data['points'])
    binding = data['attempt_binding']
    context = data['context']
    authority = data.pop('authority')
    members = tuple((point.point_id, point.dense.input_sha256,
                     point.sparse.input_sha256 if point.sparse else None)
                    for point in data['points'])
    authorization = (
        tuple(sorted(set(authority['principal_ids']), key=lambda item: item.encode('utf-8'))),
        tuple(sorted(set(authority['grant_ids']), key=lambda item: item.encode('utf-8'))),
        authority['language'], authority['kind'], authority['tag'],
    )
    data['witness'] = (
        'cragkit.qdrant.publication.readback.v1', binding['instance_id'],
        binding['storage_identity'], binding['supervisor_id'], str(binding['epoch']),
        binding['credential_generation'], binding['intent_id'], binding['owner_token'],
        binding['dispatch_id'], context.scope.tenant_id, context.collection,
        context.document_id, data['revision_id'], data['generation_id'],
        data['manifest_sha256'], data['authorization_revision'], str(data['mutation_epoch']),
        data['active_generation_id'], 'false', members, authorization,
    )
    data['encoded_bytes'] = json.dumps(data['witness'], ensure_ascii=False,
                                      separators=(',', ':'), allow_nan=False).encode('utf-8')
    data['readback_sha256'] = hashlib.sha256(data['encoded_bytes']).hexdigest()
    result = PublicationProjection()
    _PROJECTIONS[result] = (writer, MappingProxyType(data))
    return result


def publication_receipt_data(value: object, verifier: object) -> Mapping[str, Any]:
    if (type(value) is not PublicationReadbackReceipt or value not in _RECEIPTS
            or _RECEIPTS[value][0] is not verifier):
        raise InvalidRequest()
    assert isinstance(verifier, QdrantPublicationVerifier)
    _, attempt, data = _RECEIPTS[value]
    supervisor = _VERIFIERS[verifier][1]
    if dict(supervisor.attempt_binding(attempt)) != dict(data['attempt_binding']):
        raise UnsupportedCapability()
    return data


class QdrantPublicationVerifier:
    def __init__(self, writer: PostgresQdrantWriter,
                 supervisor: ManagedQdrantSupervisor) -> None:
        from ._qdrant_writer import PostgresQdrantWriter
        if type(writer) is not PostgresQdrantWriter or type(supervisor) is not ManagedQdrantSupervisor:
            raise InvalidRequest()
        self.writer = writer
        self.supervisor = supervisor
        _VERIFIERS[self] = (writer, supervisor)
        self._active: asyncio.Task[Any] | None = None
        self._closed = False

    async def verify(self, attempt: object, context: object, *,
                     deadline: float) -> PublicationReadbackReceipt:
        deadline = deadline_value(deadline)
        if self._closed or self._active is not None:
            raise ProviderUnavailable()
        self._active = asyncio.current_task()
        handle = None
        try:
            async with asyncio.timeout_at(deadline):
                binding = dict(self.supervisor.attempt_binding(attempt))
                if 'recovery_id' in binding:
                    raise UnsupportedCapability()
                projection = await self.writer.project_publication(context, binding, deadline=deadline)
                data = publication_projection_data(projection, self.writer)
                handle = self.supervisor.transport_for(attempt)
                path = '/collections/' + self.writer.config.physical_collection + '/points'
                await _verify_readback(_Readback(handle, deadline), path, data)
                await _close_handle(handle)
                handle = None
                await self.writer.validate_publication_projection(projection, deadline=deadline)
                if dict(self.supervisor.attempt_binding(attempt)) != binding:
                    raise UnsupportedCapability()
                deadline_value(deadline)
                fields = ('context', 'attempt_binding', 'manifest_sha256', 'revision_id',
                          'generation_id', 'authorization_revision', 'mutation_epoch',
                          'active_generation_id', 'tombstoned', 'point_ids', 'witness',
                          'encoded_bytes', 'readback_sha256')
                result = {key: data[key] for key in fields}
                result.update(projection=projection, sha256=data['readback_sha256'])
                receipt = PublicationReadbackReceipt()
                _RECEIPTS[receipt] = (self, attempt, MappingProxyType(result))
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
                    await _close_handle(handle)
            except Exception:
                raise ProviderUnavailable() from None
            finally:
                self._active = None

    async def close(self) -> None:
        self._closed = True
        active = self._active
        if active is not None and active is not asyncio.current_task():
            active.cancel()
            try:
                async with asyncio.timeout(1):
                    await asyncio.shield(active)
            except asyncio.CancelledError:
                if not active.done():
                    raise
            except Exception:
                raise ProviderUnavailable() from None
