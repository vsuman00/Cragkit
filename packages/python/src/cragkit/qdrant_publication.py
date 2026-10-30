"""Optional native stage/publication manager with explicit borrowed dependencies."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
import hashlib
import inspect
import json
from types import MappingProxyType
from typing import Any, cast
from uuid import uuid4
from weakref import WeakKeyDictionary

from ._qdrant_contract import QdrantConfig, decode_response, parse_model
from ._qdrant_publication_verification import (
    QdrantPublicationVerifier, validate_publication_receipt,
)
from ._qdrant_reconciliation import QdrantReconciliationVerifier, _ReadbackTransport, VerificationBudget
from ._qdrant_recovery import PostgresQdrantRecovery, recovery_components
from ._qdrant_recovery import dispatch_security_recovery, settle_security_guarded
from ._qdrant_security_readback import SecurityReadbackBudget
from ._qdrant_security_verification import QdrantSecurityVerifier, verify_security_ordinary
from ._qdrant_source import metadata_guard
from ._qdrant_security import QdrantSecurityManager
from ._qdrant_supervisor import ManagedQdrantSupervisor
from ._qdrant_transport import deadline_value
from ._qdrant_publication_worker import (is_controller, is_worker, controller_profile,
    controller_attempt, controller_issue, controller_finalization,
    ManagedQdrantPublicationWorkerHost, OwnedPublicationWorker, OrdinaryWorkerController)
from ._qdrant_writer import PostgresQdrantWriter, writer_binding
from ._qdrant_writer import admit_security_owner, complete_security_replica
from ._qdrant_writer import PURGE_POLICY, purge_projection_data
from ._qdrant_manifest import _Purge, _parse, encode_purge_intent
from ._qdrant_recovery import dispatch_purge_recovery, settle_purge_guarded
from ._qdrant_security_verification import verify_purge_ordinary
from ._qdrant_writer_contract import context, prepare_stage, stage_data
from .contracts import TrustedScope
from .execution import ExecutionLedger, BudgetExhausted
from .errors import (DeadlineExceeded, IndexNotReady,
                     IntegrityViolation, InvalidRequest, ProviderUnavailable,
                     UnauthorizedScope, UnsupportedCapability)

__all__ = ('QdrantSecurityManager', 'QdrantPublicationManager', 'PostgresQdrantPublicationAuthority',
           'ManagedQdrantPublicationTransport', 'PostgresQdrantWriter',
           'PostgresQdrantRecovery', 'ManagedQdrantSupervisor', 'QdrantReconciliationVerifier',
           'ManagedQdrantPublicationWorkerHost', 'OwnedPublicationWorker')

_AUTHORITIES: WeakKeyDictionary[object, tuple[PostgresQdrantWriter, PostgresQdrantRecovery | None]] = WeakKeyDictionary()
_TRANSPORTS: WeakKeyDictionary[object, Any] = WeakKeyDictionary()
_ACKS: WeakKeyDictionary[object, tuple[object, object, str]] = WeakKeyDictionary()
_SESSIONS: WeakKeyDictionary[object, tuple[object, object, object]] = WeakKeyDictionary()
_CLEANUP_SECONDS = 1.0


class PostgresQdrantPublicationAuthority:
    """A borrowed nominal pair; it neither initializes nor grants permission."""
    def __init__(self, writer: PostgresQdrantWriter, recovery: PostgresQdrantRecovery | None) -> None:
        writer_binding(writer)
        if recovery is not None and type(recovery) is not PostgresQdrantRecovery:
            raise InvalidRequest()
        _AUTHORITIES[self] = (writer, recovery)


class _Acknowledgment:
    __slots__ = ('__weakref__',)


@dataclass(eq=False, slots=True, weakref_slot=True)
class _Session:
    issuer: object
    attempt: object
    binding: Mapping[str, Any]
    handle: _ReadbackTransport
    sent: bool = False
    closed: bool = False


class ManagedQdrantPublicationTransport:
    """One-send immutable native sessions, never caller-supplied completion."""
    def __init__(self, supervisor: ManagedQdrantSupervisor | OrdinaryWorkerController) -> None:
        if not is_controller(supervisor):
            raise InvalidRequest()
        _TRANSPORTS[self] = supervisor
        self._closed = False

    async def _open(self, binding: dict[str, Any], *, deadline: float) -> _Session:
        if self._closed:
            raise ProviderUnavailable()
        supervisor = _TRANSPORTS[self]
        attempt = await controller_issue(supervisor, binding, deadline=deadline)
        session = _Session(self, attempt, await controller_attempt(supervisor, attempt, deadline=deadline),
                           supervisor.transport_for(attempt))
        _SESSIONS[session] = (self, attempt, session.handle)
        return session

    async def _send(self, session: _Session, collection: str, body: bytes, *,
                    deadline: float) -> _Acknowledgment:
        if self._closed:
            raise ProviderUnavailable()
        if (type(session) is not _Session or session not in _SESSIONS
                or _SESSIONS[session][0] is not self
                or _SESSIONS[session][1] is not session.attempt
                or _SESSIONS[session][2] is not session.handle
                or session.issuer is not self or session.sent
                or session.closed or type(body) is not bytes or not 1 <= len(body) <= 1048576):
            raise InvalidRequest()
        session.sent = True
        raw = await session.handle.request('PUT', '/collections/' + collection
            + '/points?wait=true&ordering=strong', body=body, deadline=deadline,
            max_response_bytes=1048576)
        if type(raw) is not bytes or not 1 <= len(raw) <= 1048576:
            raise IntegrityViolation()
        try:
            value = decode_response(raw)
        except InvalidRequest:
            raise IntegrityViolation() from None
        if (type(value) is not dict or value.get('status') != 'ok'
                or type(value.get('result')) is not dict
                or value['result'].get('status') != 'completed'
                or set(value['result']) - {'status', 'operation_id'}):
            raise IntegrityViolation()
        operation_id = value['result'].get('operation_id')
        if 'operation_id' in value['result'] and (type(operation_id) not in (int, float)
                or not 0 <= operation_id <= 9007199254740991 or int(operation_id) != operation_id):
            raise IntegrityViolation()
        acknowledgment = _Acknowledgment()
        _ACKS[acknowledgment] = (self, session, hashlib.sha256(raw).hexdigest())
        return acknowledgment

    def _ack_hash(self, acknowledgment: object, session: _Session) -> str:
        if (type(acknowledgment) is not _Acknowledgment or acknowledgment not in _ACKS
                or _ACKS[acknowledgment][:2] != (self, session)):
            raise InvalidRequest()
        return _ACKS[acknowledgment][2]

    async def _close(self, session: _Session) -> None:
        if session.issuer is not self:
            raise InvalidRequest()
        if session.closed:
            return
        try:
            async with asyncio.timeout(_CLEANUP_SECONDS):
                await session.handle.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ProviderUnavailable() from None
        session.closed = True

    async def close(self) -> None:
        self._closed = True
        try:
            async with asyncio.timeout(_CLEANUP_SECONDS):
                for session in tuple(_SESSIONS):
                    if type(session) is _Session and session.issuer is self and not session.closed:
                        await self._close(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise ProviderUnavailable() from None


def _safe(error: Exception) -> Exception:
    for kind in (BudgetExhausted, DeadlineExceeded, IndexNotReady, IntegrityViolation,
                 InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability):
        if type(error) is kind:
            return kind()
    return ProviderUnavailable()


def _scope(value: object) -> TrustedScope:
    if type(value) is TrustedScope:
        value = value.model_dump(mode='json')
    metadata_guard(value)
    return parse_model(TrustedScope, value)


def _reference(value: object) -> dict[str, str]:
    metadata_guard(value)
    if type(value) is not dict or set(value) != {'collection', 'document_id', 'intent_id'}:
        raise InvalidRequest()
    # Reuse the exact context identity parser without exposing an owner input.
    parsed = context({**value, 'scope': {'tenant_id': 'validation', 'principal_id': 'validation',
        'grant_ids': [], 'authorization_revision': 'validation'}, 'owner_token': str(uuid4())})
    return {'collection': parsed.collection, 'document_id': parsed.document_id,
            'intent_id': parsed.intent_id}


def _result(intent_id: str, operation: str, intent: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType({'intent_id': intent_id, 'operation': operation,
        'state': intent['state'], 'revision_id': intent['revision_id'],
        'generation_id': intent['generation_id'], 'authority_committed': intent['authority_committed'],
        'replica_complete': intent['replica_complete'], 'published': intent['state'] == 'published',
        'purge_complete': intent['purge_complete']})


class QdrantPublicationManager:
    def __init__(self, authority: PostgresQdrantPublicationAuthority,
                 transport: ManagedQdrantPublicationTransport, config: object,
                 supervisor: ManagedQdrantSupervisor | OrdinaryWorkerController,
                 authorize_write: Callable[[TrustedScope, str, str], Awaitable[bool]]) -> None:
        if (type(authority) is not PostgresQdrantPublicationAuthority or authority not in _AUTHORITIES
                or type(transport) is not ManagedQdrantPublicationTransport or transport not in _TRANSPORTS
                or not is_controller(supervisor) or not callable(authorize_write)):
            raise InvalidRequest()
        metadata_guard(config)
        self._config = parse_model(QdrantConfig, config)
        self._writer, self._recovery = _AUTHORITIES[authority]
        binding = writer_binding(self._writer)
        if binding['config'] != self._config:
            raise UnsupportedCapability()
        if _TRANSPORTS[transport] is not supervisor:
            raise InvalidRequest()
        self._original_verifier: object | None
        if self._recovery is None:
            if not is_worker(supervisor):
                raise InvalidRequest()
            self._original_verifier = None
        else:
            if is_worker(supervisor):
                raise InvalidRequest()
            self._original_verifier = recovery_components(
                self._recovery, self._writer, cast(ManagedQdrantSupervisor, supervisor), self._config)
        self._supervisor = supervisor
        self._transport = transport
        self._authorize_write = authorize_write
        self._instance = binding['instance_id']
        self._verifier = QdrantPublicationVerifier(self._writer, supervisor)
        self._security_verifier = (None if is_worker(supervisor) else
            QdrantSecurityVerifier(self._writer, cast(ManagedQdrantSupervisor, supervisor)))
        self._ready = False
        self._closed = False
        self._active: asyncio.Task[Any] | None = None
        self._cancelled = False

    def _check(self, deadline: float) -> None:
        if self._cancelled:
            raise asyncio.CancelledError()
        deadline_value(deadline)

    async def _run(self, body: Callable[[float], Awaitable[Any]], *, deadline: float,
                   ledger: ExecutionLedger | None = None, initializing: bool = False) -> Any:
        deadline = deadline_value(deadline)
        if self._closed or self._active is not None:
            raise ProviderUnavailable()
        if not initializing and not self._ready:
            raise IndexNotReady()
        if ledger is not None:
            if type(ledger) is not ExecutionLedger:
                raise InvalidRequest()
            deadline = min(deadline, ledger.deadline)
        deadline_value(deadline)
        self._cancelled = False

        async def work() -> Any:
            reservation = None
            completed = False
            try:
                if ledger is not None:
                    reservation = ledger.reserve(attempts=1)
                    ledger.dispatch(reservation)
                self._check(deadline)
                result = await body(deadline)
                self._check(deadline)
                if ledger is not None:
                    ledger.reconcile(reservation)
                    completed = True
                return result
            finally:
                if ledger is not None and reservation is not None and not completed:
                    ledger.abandon(reservation)

        task = asyncio.create_task(work())
        self._active = task

        def finished(done: asyncio.Task[Any]) -> None:
            if self._active is done:
                self._active = None
            if not done.cancelled():
                done.exception()

        task.add_done_callback(finished)
        try:
            async with asyncio.timeout_at(deadline):
                return await asyncio.shield(task)
        except (asyncio.CancelledError, TimeoutError) as error:
            self._cancelled = True
            task.cancel()
            try:
                async with asyncio.timeout(_CLEANUP_SECONDS):
                    await asyncio.shield(task)
            except BaseException:
                if not task.done():
                    self._closed = True
            if isinstance(error, asyncio.CancelledError):
                raise
            raise DeadlineExceeded() from None
        except Exception as error:
            raise _safe(error) from None
        finally:
            if task.done() and self._active is task:
                self._active = None

    async def _authorize(self, ctx: Any, deadline: float) -> None:
        self._check(deadline)
        try:
            pending = self._authorize_write(ctx.scope, ctx.collection, ctx.document_id)
            if not inspect.isawaitable(pending):
                raise InvalidRequest()
            allowed = await pending
        except asyncio.CancelledError:
            raise
        except InvalidRequest:
            raise InvalidRequest() from None
        except Exception:
            raise ProviderUnavailable() from None
        self._check(deadline)
        if type(allowed) is not bool:
            raise InvalidRequest()
        if not allowed:
            raise UnauthorizedScope()

    async def _controller(self, snapshot: Mapping[str, Any], deadline: float) -> Mapping[str, Any]:
        native = await controller_profile(self._supervisor, self._config, deadline=deadline)
        backend = snapshot['backend']
        if native['instance_id'] != self._instance:
            raise UnsupportedCapability()
        for key in ('backend_namespace', 'storage_identity', 'supervisor_id'):
            if backend[key] != native[key]:
                raise IntegrityViolation()
        if (backend['state'] != 'open' or backend['recovery_id'] is not None
                or native['epoch'] != backend['epoch'] or native['recovery'] is not None
                or native['sealed'] or not native['alive']):
            raise ProviderUnavailable()
        return cast(Mapping[str, Any], native)

    async def initialize(self, *, deadline: float) -> None:
        async def initialize(limit: float) -> None:
            self._check(limit)
            native = await controller_profile(self._supervisor, self._config, deadline=limit)
            if native['instance_id'] != self._instance:
                raise UnsupportedCapability()
            if self._recovery is not None:
                await self._recovery.initialize(deadline=limit)
            self._check(limit)
            await self._writer.initialize(deadline=limit)
            self._check(limit)
            if is_worker(self._supervisor):
                job = cast(Any, self._supervisor).job
                lookup = context({**job['reference'], 'scope': job['scope'], 'owner_token': str(uuid4())})
                snapshot = await self._writer.manager_snapshot(lookup, deadline=limit)
                self._check(limit)
                await self._controller(snapshot, limit)
            self._ready = True
        await self._run(initialize, deadline=deadline, initializing=True)

    async def stage(self, change: object, scope: object, ledger: ExecutionLedger, *,
                    deadline: float) -> Mapping[str, Any]:
        if type(ledger) is not ExecutionLedger:
            raise InvalidRequest()
        if is_worker(self._supervisor):
            raise UnsupportedCapability()
        plan = prepare_stage(change)
        graph = stage_data(plan)
        trusted = _scope(scope)
        if trusted.tenant_id != graph.manifest.tenant_id:
            raise UnauthorizedScope()
        ctx = context({'scope': trusted, 'collection': graph.manifest.collection,
            'document_id': graph.manifest.document_id, 'intent_id': graph.intent.intent_id,
            'owner_token': str(uuid4())})

        async def stage(limit: float) -> Mapping[str, Any]:
            await self._authorize(ctx, limit)
            snapshot = await self._writer.manager_snapshot(ctx, deadline=limit)
            self._check(limit)
            prior = snapshot['intent']
            if prior is not None:
                if (prior['action'] != 'stage' or prior['payload_sha256'] != plan.payload_sha256
                        or prior['manifest_sha256'] != plan.manifest_sha256):
                    raise IntegrityViolation()
                if prior['state'] in ('published', 'conflict', 'denied'):
                    return _result(ctx.intent_id, 'stage', prior)
            await self._controller(snapshot, limit)
            result = await self._writer.stage(plan, trusted, owner_token=ctx.owner_token, deadline=limit)
            self._check(limit)
            return _result(ctx.intent_id, 'stage', result)
        return cast(Mapping[str, Any], await self._run(stage, deadline=deadline, ledger=ledger))

    async def _unknown(self, ctx: Any, dispatch_id: str, deadline: float) -> None:
        if self._cancelled:
            return
        try:
            deadline_value(deadline)
            await self._writer.mark_unknown(ctx, dispatch_id, deadline=deadline)
        except Exception:
            pass

    @staticmethod
    def _matching(status: Mapping[str, Any] | None, request: Mapping[str, Any],
                  ctx: Any, epoch: int) -> bool:
        return status is not None and all((
            status['dispatch_id'] == request['dispatch_id'], status['sequence'] == request['sequence'],
            status['owner_token'] == ctx.owner_token, status['backend_epoch'] == epoch,
            status['credential_generation'] == request['credential_generation'],
            status['operation'] == request['operation'],
            tuple(status['point_ids']) == tuple(request['point_ids']),
        ))

    async def _batch(self, ctx: Any, ids: tuple[str, ...], sequence: int, epoch: int,
                     deadline: float) -> object:
        await self._authorize(ctx, deadline)
        dispatch_id = 'publication-' + str(uuid4())
        session = await self._transport._open({'intent_id': ctx.intent_id, 'owner_token': ctx.owner_token,
            'epoch': epoch, 'dispatch_id': dispatch_id}, deadline=deadline)
        request = {'dispatch_id': dispatch_id, 'sequence': sequence,
            'credential_generation': session.binding['credential_generation'],
            'operation': 'complete_point_upsert', 'point_ids': ids}
        settled = False
        try:
            try:
                reservation = await self._writer.reserve_dispatch(ctx, request, deadline=deadline)
            except ProviderUnavailable:
                self._check(deadline)
                status = await self._writer.dispatch_status(ctx, dispatch_id, deadline=deadline)
                self._check(deadline)
                if status is None or not self._matching(status, request, ctx, epoch) or status['state'] != 'reserved':
                    raise ProviderUnavailable() from None
                reservation = await self._writer.reserve_dispatch(ctx, request, deadline=deadline)
            self._check(deadline)
            if is_worker(self._supervisor):
                await cast(Any, self._supervisor).reserved(session.attempt, dict(dispatch_id=dispatch_id,
                    sequence=sequence, request_sha256=hashlib.sha256(reservation['request_bytes']).hexdigest()),
                    deadline=deadline)
                self._check(deadline)
            try:
                await self._writer.mark_dispatched(ctx, dispatch_id, deadline=deadline)
            except ProviderUnavailable:
                self._check(deadline)
                status = await self._writer.dispatch_status(ctx, dispatch_id, deadline=deadline)
                self._check(deadline)
                if status is None or not self._matching(status, request, ctx, epoch):
                    raise IntegrityViolation() from None
                if status['state'] == 'reserved':
                    await self._authorize(ctx, deadline)
                    await self._writer.mark_dispatched(ctx, dispatch_id, deadline=deadline)
                elif status['state'] != 'dispatched':
                    raise ProviderUnavailable() from None
            self._check(deadline)
            if is_worker(self._supervisor):
                await cast(Any, self._supervisor).before_write(session.attempt, dict(dispatch_id=dispatch_id,
                    sequence=sequence, request_sha256=hashlib.sha256(reservation['request_bytes']).hexdigest()),
                    deadline=deadline)
                self._check(deadline)
            acknowledgment = await self._transport._send(session, self._config.physical_collection,
                reservation['request_bytes'], deadline=deadline)
            self._check(deadline)
            digest = self._transport._ack_hash(acknowledgment, session)
            await self._transport._close(session)
            self._check(deadline)
            try:
                await self._writer.settle_dispatch(ctx, dispatch_id, digest, deadline=deadline)
            except ProviderUnavailable:
                self._check(deadline)
                status = await self._writer.dispatch_status(ctx, dispatch_id, deadline=deadline)
                self._check(deadline)
                if status is None or not self._matching(status, request, ctx, epoch):
                    raise IntegrityViolation() from None
                if status['state'] == 'settled':
                    if status['completion_sha256'] != digest:
                        raise IntegrityViolation() from None
                elif status['state'] == 'dispatched':
                    await self._writer.settle_dispatch(ctx, dispatch_id, digest, deadline=deadline)
                else:
                    raise ProviderUnavailable() from None
            self._check(deadline)
            settled = True
            return session.attempt
        finally:
            try:
                if not settled:
                    await self._unknown(ctx, dispatch_id, deadline)
            finally:
                await self._transport._close(session)

    async def publish(self, reference: object, scope: object, ledger: ExecutionLedger, *,
                      deadline: float) -> Mapping[str, Any]:
        if type(ledger) is not ExecutionLedger:
            raise InvalidRequest()
        target = _reference(reference)
        trusted = _scope(scope)
        lookup = context({**target, 'scope': trusted, 'owner_token': str(uuid4())})

        return cast(Mapping[str, Any], await self._run(
            lambda limit: self._publish_body(lookup, target, trusted, limit), deadline=deadline, ledger=ledger))

    async def _publish_body(self, lookup: Any, target: Mapping[str, Any], trusted: TrustedScope,
                            limit: float, operation: str = 'publish',
                            preserved_owner: str | None = None,
                            budget: VerificationBudget | None = None) -> Mapping[str, Any]:
        budget = VerificationBudget() if budget is None else budget
        await self._authorize(lookup, limit)
        snapshot = await self._writer.manager_snapshot(lookup, deadline=limit)
        self._check(limit)
        intent = snapshot['intent']
        if intent is None or intent['action'] != 'stage':
            raise InvalidRequest()
        if intent['state'] in ('published', 'conflict', 'denied'):
            outcome = await self._writer.admit_publication(lookup, deadline=limit)
            self._check(limit)
            return _result(lookup.intent_id, operation, outcome['intent'])
        prepared = None
        if intent['state'] == 'prepared':
            prepared = await self._writer.publication_preparation(lookup, deadline=limit)
            self._check(limit)
            if prepared is None:
                raise IntegrityViolation()
            owner_token = prepared['preparation']['owner_token']
        else:
            owner_token = preserved_owner or str(uuid4())
        ctx = context({**target, 'scope': trusted, 'owner_token': owner_token})
        admission = await self._writer.admit_publication(ctx, deadline=limit)
        self._check(limit)
        if admission['owner'] is None:
            return _result(ctx.intent_id, operation, admission['intent'])
        snapshot = await self._writer.manager_snapshot(ctx, deadline=limit)
        self._check(limit)
        native = await self._controller(snapshot, limit)
        if snapshot['pending']:
            raise ProviderUnavailable()
        epoch = admission['owner']['backend_epoch']
        if prepared is not None:
            selected = prepared['dispatch']
            if (selected['credential_generation'] != native['credential_generation']
                    or selected['backend_epoch'] != epoch):
                raise ProviderUnavailable()
            session = await self._transport._open({'intent_id': ctx.intent_id,
                'owner_token': owner_token, 'epoch': epoch,
                'dispatch_id': selected['dispatch_id']}, deadline=limit)
            try:
                attempt = session.attempt
            finally:
                await self._transport._close(session)
            self._check(limit)
        else:
            plan = await self._writer.load_stage(ctx, deadline=limit)
            self._check(limit)
            ids = tuple(sorted(member.point_id for member in stage_data(plan).manifest.members))
            batches = (len(ids) + 7) // 8
            if not 1 <= len(ids) <= 64:
                raise IntegrityViolation()
            if snapshot['max_sequence'] + batches > 256:
                raise BudgetExhausted()
            attempt = None
            for index, start in enumerate(range(0, len(ids), 8), 1):
                if budget.remaining_bytes <= 0:
                    raise ProviderUnavailable()
                attempt = await self._batch(ctx, ids[start:start + 8],
                    snapshot['max_sequence'] + index, epoch, limit)
                self._check(limit)
            if attempt is None:
                raise IntegrityViolation()
        receipt = await self._verifier.verify(attempt, ctx, deadline=limit, budget=budget)
        self._check(limit)
        async with controller_finalization(self._supervisor, attempt, deadline=limit):
            self._check(limit)
            data = await validate_publication_receipt(receipt, self._verifier, deadline=limit)
            if prepared is not None and data['readback_sha256'] != prepared['preparation']['readback_sha256']:
                raise IntegrityViolation()
            await self._authorize(ctx, limit)
            await self._writer.validate_publication_projection(data['projection'], deadline=limit)
            self._check(limit)
            if prepared is None:
                try:
                    outcome = await self._writer.prepare(ctx, data['readback_sha256'], deadline=limit)
                    self._check(limit)
                except ProviderUnavailable:
                    self._check(limit)
                    confirmed = await self._writer.publication_preparation(ctx, deadline=limit)
                    self._check(limit)
                    if (confirmed is None or confirmed['preparation']['readback_sha256'] != data['readback_sha256']
                            or confirmed['preparation']['owner_token'] != owner_token
                            or confirmed['preparation']['backend_epoch'] != epoch):
                        raise ProviderUnavailable() from None
                else:
                    if outcome['state'] in ('denied', 'conflict'):
                        return _result(ctx.intent_id, operation, outcome)
            await self._authorize(ctx, limit)
            try:
                result = await self._writer.publish(ctx, deadline=limit)
                self._check(limit)
            except ProviderUnavailable:
                self._check(limit)
                confirmed = await self._writer.manager_snapshot(ctx, deadline=limit)
                self._check(limit)
                result = confirmed['intent']
                if result is None or result['state'] != 'published':
                    raise ProviderUnavailable() from None
            return _result(ctx.intent_id, operation, result)

    async def repair(self, reference: object, scope: object, ledger: ExecutionLedger, *,
                     deadline: float) -> Mapping[str, Any]:
        if type(ledger) is not ExecutionLedger:
            raise InvalidRequest()
        target = _reference(reference)
        trusted = _scope(scope)
        # Capability refusal is local and precedes callbacks or resource checkout.
        if is_worker(self._supervisor) or self._recovery is None or self._original_verifier is None:
            raise UnsupportedCapability()
        recovery = self._recovery
        lookup = context({**target, 'scope': trusted, 'owner_token': str(uuid4())})

        async def repair(limit: float) -> Mapping[str, Any]:
            budget = VerificationBudget()
            await self._authorize(lookup, limit)
            preflight = await self._writer.preflight_repair(lookup, deadline=limit)
            self._check(limit)
            intent, backend, owner = preflight['intent'], preflight['backend'], preflight['owner']
            if intent['state'] in ('published', 'conflict', 'denied'):
                return _result(lookup.intent_id, 'repair', intent)
            prepared = intent['state'] == 'prepared'
            needs_recovery = (preflight['pending'] or backend['state'] != 'open'
                or (prepared and owner is not None and owner['backend_epoch'] != backend['epoch']))
            if owner is not None and (owner['instance_id'] != self._instance or owner['intent_id'] != lookup.intent_id):
                raise ProviderUnavailable()
            if (prepared or needs_recovery) and owner is None:
                raise ProviderUnavailable()
            token = owner['owner_token'] if owner is not None else str(uuid4())
            ctx = context({**target, 'scope': trusted, 'owner_token': token})
            if needs_recovery:
                if backend['state'] == 'recovery_blocked':
                    identity = backend['recovery_id']
                else:
                    raw = ['cragkit.qdrant.repair-recovery.v1', self._instance, str(backend['epoch'])]
                    identity = 'g1-' + hashlib.sha256(json.dumps(raw, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
                await self._authorize(ctx, limit)
                proof = await recovery.recover(identity, deadline=limit)
                self._check(limit)
                await recovery.advance_owner(proof, ctx, deadline=limit)
                self._check(limit)
                if preflight['pending']:
                    verifier = cast(QdrantReconciliationVerifier, self._original_verifier)
                    try:
                        reconciliation_receipt = await verifier.verify(proof, ctx, deadline=limit, budget=budget)
                    except IntegrityViolation:
                        self._check(limit)
                        async def authorize_recovery(selected: TrustedScope, collection: str, document_id: str) -> bool:
                            if selected != ctx.scope or collection != ctx.collection or document_id != ctx.document_id:
                                raise InvalidRequest()
                            await self._authorize(ctx, limit)
                            return True
                        await recovery.dispatch_stage_recovery(proof, ctx, authorize_recovery, deadline=limit, budget=budget)
                        self._check(limit)
                        reconciliation_receipt = await verifier.verify(proof, ctx, deadline=limit, budget=budget)
                    self._check(limit)
                    await recovery.settle_retired(proof, reconciliation_receipt, deadline=limit)
                    self._check(limit)
                await recovery.reopen(proof, deadline=limit)
                self._check(limit)
                preflight = await self._writer.preflight_repair(ctx, deadline=limit)
                self._check(limit)
                intent, backend, owner = preflight['intent'], preflight['backend'], preflight['owner']
                if intent['state'] in ('published', 'conflict', 'denied'):
                    return _result(ctx.intent_id, 'repair', intent)
            if not prepared:
                return await self._publish_body(ctx, target, trusted, limit, 'repair', token, budget)
            snapshot = await self._writer.manager_snapshot(ctx, deadline=limit)
            self._check(limit)
            native = await self._controller(snapshot, limit)
            material = await self._writer.attestation_snapshot(ctx, deadline=limit)
            self._check(limit)
            original, attestation = material['preparation'], material['attestation']
            if original['backend_epoch'] == backend['epoch']:
                if original['owner_token'] != token:
                    raise ProviderUnavailable()
                return await self._publish_body(ctx, target, trusted, limit, 'repair', token, budget)
            if original['backend_epoch'] > backend['epoch']:
                raise IntegrityViolation()
            if attestation is not None:
                if attestation['credential_generation'] != native['credential_generation']:
                    raise ProviderUnavailable()
                dispatch = attestation['verification_id']
            else:
                raw = ['cragkit.qdrant.repair-verification.v1', self._instance, ctx.intent_id,
                    token, str(backend['epoch']), native['credential_generation'], intent['manifest_sha256']]
                dispatch = 'g1-' + hashlib.sha256(json.dumps(raw, separators=(',', ':'), ensure_ascii=False).encode('utf-8')).hexdigest()
            attempt = await controller_issue(self._supervisor, {'intent_id': ctx.intent_id,
                'owner_token': token, 'epoch': backend['epoch'], 'dispatch_id': dispatch}, deadline=limit)
            self._check(limit)
            receipt = await self._verifier.verify(attempt, ctx, deadline=limit, budget=budget)
            self._check(limit)
            async with controller_finalization(self._supervisor, attempt, deadline=limit):
                await self._authorize(ctx, limit)
                data = await validate_publication_receipt(receipt, self._verifier, deadline=limit)
                await self._writer.validate_publication_projection(data['projection'], deadline=limit)
                self._check(limit)
                attested = await self._writer.attest_prepared(receipt, self._verifier, deadline=limit)
                self._check(limit)
                if attested['intent']['state'] in ('denied', 'conflict'):
                    return _result(ctx.intent_id, 'repair', attested['intent'])
                await self._authorize(ctx, limit)
                try:
                    result = await self._writer.publish(ctx, deadline=limit)
                except ProviderUnavailable:
                    self._check(limit)
                    result = (await self._writer.manager_snapshot(ctx, deadline=limit))['intent']
                    if result is None or result['state'] != 'published':
                        raise ProviderUnavailable() from None
                self._check(limit)
                return _result(ctx.intent_id, 'repair', result)
        return cast(Mapping[str, Any], await self._run(repair, deadline=deadline, ledger=ledger))

    async def converge_security(self, reference: object, scope: object, ledger: ExecutionLedger, *,
                                deadline: float) -> Mapping[str, Any]:
        if type(ledger) is not ExecutionLedger:
            raise InvalidRequest()
        target = _reference(reference)
        trusted = _scope(scope)
        if (self._writer._schema_profile != 5 or is_worker(self._supervisor)
                or self._recovery is None or self._security_verifier is None):
            raise UnsupportedCapability()
        recovery = self._recovery
        verifier = self._security_verifier
        lookup = context({**target, 'scope': trusted, 'owner_token': str(uuid4())})

        async def converge(limit: float) -> Mapping[str, Any]:
            budget = SecurityReadbackBudget()
            await self._authorize(lookup, limit)
            snapshot = await self._writer.manager_snapshot(lookup, deadline=limit)
            self._check(limit)
            intent, backend, owner = snapshot['intent'], snapshot['backend'], snapshot['owner']
            if intent is None:
                raise InvalidRequest()
            if intent['action'] == 'tombstone':
                raise UnsupportedCapability()
            if intent['action'] != 'update_authorization' or not intent['authority_committed']:
                raise InvalidRequest()
            if intent['state'] not in ('authority_committed', 'writing', 'complete'):
                raise InvalidRequest()
            if intent['replica_complete'] != (intent['state'] == 'complete') or intent['purge_complete']:
                raise IntegrityViolation()
            if intent['state'] == 'complete' and intent['replica_complete']:
                return _result(lookup.intent_id, 'converge_security', intent)
            token = (owner['owner_token'] if owner is not None
                     and owner['intent_id'] == lookup.intent_id else lookup.owner_token)
            current = context({**target, 'scope': trusted, 'owner_token': token})
            await self._writer.project_security(current, deadline=limit)
            self._check(limit)
            if owner is None:
                if backend['state'] != 'open' or snapshot['pending']:
                    raise ProviderUnavailable()
                await admit_security_owner(self._writer, current, deadline=limit)
                self._check(limit)
                snapshot = await self._writer.manager_snapshot(current, deadline=limit)
                self._check(limit)
                backend, owner = snapshot['backend'], snapshot['owner']
            if owner is None or owner['instance_id'] != self._instance:
                raise ProviderUnavailable()
            previous = context({**target, 'intent_id': owner['intent_id'], 'scope': trusted,
                                'owner_token': owner['owner_token']})
            if backend['state'] == 'recovery_blocked':
                identity = backend['recovery_id']
            else:
                raw = ['cragkit.qdrant.security-recovery.v1', self._instance, str(backend['epoch'])]
                identity = 'g2-' + hashlib.sha256(json.dumps(raw, separators=(',', ':'),
                    ensure_ascii=False).encode('utf-8')).hexdigest()
            await self._authorize(current, limit)
            proof = await recovery.recover(identity, deadline=limit)
            self._check(limit)
            await recovery.advance_owner(proof, previous, deadline=limit)
            self._check(limit)

            async def authorize(selected: TrustedScope, collection: str, document_id: str) -> bool:
                if selected != trusted or collection != current.collection or document_id != current.document_id:
                    raise InvalidRequest()
                await self._authorize(current, limit)
                return True

            await dispatch_security_recovery(recovery, proof, previous, current, authorize,
                                             deadline=limit, budget=budget)
            self._check(limit)
            await settle_security_guarded(recovery, verifier, proof, previous, current,
                                          deadline=limit, budget=budget)
            self._check(limit)
            await recovery.reopen(proof, deadline=limit)
            self._check(limit)
            await self._authorize(current, limit)
            admitted = await admit_security_owner(self._writer, current, deadline=limit)
            self._check(limit)
            attempt = await controller_issue(self._supervisor, {'intent_id': current.intent_id,
                'owner_token': current.owner_token, 'epoch': admitted['backend_epoch'],
                'dispatch_id': 'security-completion-' + str(uuid4())}, deadline=limit)
            self._check(limit)
            receipt = await verify_security_ordinary(verifier, attempt, current, deadline=limit, budget=budget)
            self._check(limit)
            async with controller_finalization(self._supervisor, attempt, deadline=limit):
                await self._authorize(current, limit)
                result = await complete_security_replica(self._writer, verifier, receipt, deadline=limit)
                self._check(limit)
                return _result(current.intent_id, 'converge_security', result)

        return cast(Mapping[str, Any], await self._run(converge, deadline=deadline, ledger=ledger))

    async def purge(self, record: object, scope: object, ledger: ExecutionLedger, *,
                    retention_policy: str, deadline: float) -> Mapping[str,Any]:
        if type(retention_policy) is not str:
            raise InvalidRequest()
        if retention_policy != PURGE_POLICY:
            raise UnsupportedCapability()
        if type(ledger) is not ExecutionLedger:
            raise InvalidRequest()
        if (self._writer._schema_profile != 5 or is_worker(self._supervisor)
                or self._recovery is None or self._security_verifier is None):
            raise UnsupportedCapability()
        encode_purge_intent(record)
        intent = _parse(_Purge,record)
        trusted = _scope(scope)
        if intent.tenant_id != trusted.tenant_id:
            raise UnauthorizedScope()
        target = dict(collection=intent.collection,document_id=intent.document_id,intent_id=intent.intent_id)
        lookup = context({**target,'scope':trusted,'owner_token':str(uuid4())})
        recovery,verifier = self._recovery,self._security_verifier
        async def purge(limit: float) -> Mapping[str,Any]:
            budget = SecurityReadbackBudget()
            await self._authorize(lookup,limit)
            bound = await self._writer.bind_purge(record,trusted,owner_token=lookup.owner_token,deadline=limit)
            self._check(limit)
            if bound['purge_complete']:
                historical = await self._writer.historical_purge(lookup,deadline=limit)
                self._check(limit)
                return _result(lookup.intent_id,'purge',historical)
            snapshot = await self._writer.manager_snapshot(lookup,deadline=limit)
            self._check(limit)
            backend,owner = snapshot['backend'],snapshot['owner']
            if owner is not None and owner['instance_id'] != self._instance:
                raise ProviderUnavailable()
            token = lookup.owner_token if owner is None else owner['owner_token']
            current = context({**target,'scope':trusted,'owner_token':token})
            projection = await self._writer.project_purge(current,retention_policy,deadline=limit)
            self._check(limit)
            if owner is None:
                if backend['state'] != 'open' or snapshot['pending']:
                    raise ProviderUnavailable()
                await self._writer.admit_purge_tombstone_owner(projection,deadline=limit)
                self._check(limit)
                snapshot = await self._writer.manager_snapshot(current,deadline=limit)
                self._check(limit)
                backend,owner = snapshot['backend'],snapshot['owner']
            if owner is None:
                raise ProviderUnavailable()
            if owner['intent_id']!=current.intent_id and backend['state']=='open' and not snapshot['pending']:
                prior = context({**target,'scope':trusted,'intent_id':owner['intent_id'],'owner_token':owner['owner_token']})
                retained = await self._writer.inspect(prior,deadline=limit)
                self._check(limit)
                if retained is not None and retained['action']=='purge':
                    await self._authorize(current,limit)
                    native = await self._controller(snapshot,limit)
                    self._check(limit)
                    controller_identity = {key:native[key] for key in ('instance_id','storage_identity','supervisor_id','epoch')}
                    await self._writer.admit_purge_successor(projection,owner,controller_identity,deadline=limit)
                    self._check(limit)
                    await self._authorize(current,limit)
                    snapshot = await self._writer.manager_snapshot(current,deadline=limit)
                    self._check(limit)
                    backend,owner = snapshot['backend'],snapshot['owner']
                    if owner is None:
                        raise ProviderUnavailable()
            resumed = owner['intent_id'] == current.intent_id
            if resumed:
                if backend['state'] != 'open' or snapshot['pending'] or owner['backend_epoch'] != backend['epoch']:
                    raise ProviderUnavailable()
            else:
                previous = context({**target,'scope':trusted,'intent_id':owner['intent_id'],'owner_token':owner['owner_token']})
                identity = backend['recovery_id'] if backend['state'] == 'recovery_blocked' else 'g3-'+hashlib.sha256(
                    json.dumps(['cragkit.qdrant.purge-recovery.v1',self._instance,str(backend['epoch'])],
                        separators=(',',':')).encode('utf-8')).hexdigest()
                await self._authorize(current,limit)
                proof = await recovery.recover(identity,deadline=limit)
                self._check(limit)
                await recovery.advance_owner(proof,previous,deadline=limit)
                self._check(limit)
                async def authorize(selected: TrustedScope, collection: str, document_id: str) -> bool:
                    if selected != trusted or collection != current.collection or document_id != current.document_id:
                        raise InvalidRequest()
                    await self._authorize(current,limit)
                    return True
                await dispatch_purge_recovery(recovery,proof,previous,projection,authorize,deadline=limit,budget=budget)
                self._check(limit)
                await settle_purge_guarded(recovery,verifier,proof,previous,projection,deadline=limit,budget=budget)
                self._check(limit)
                await recovery.reopen(proof,deadline=limit)
                self._check(limit)
            await self._authorize(current,limit)
            await self._writer.validate_purge_projection(projection,deadline=limit)
            self._check(limit)
            admitted = await self._writer.acquire_owner(current,deadline=limit)
            self._check(limit)
            # The purge owner only observes absence; all physical mutations retain
            # the original stage/security owner until fencing has settled them.
            projection = await self._writer.project_purge(current,retention_policy,deadline=limit)
            self._check(limit)
            attempt = await controller_issue(self._supervisor,dict(intent_id=current.intent_id,owner_token=token,
                epoch=admitted['backend_epoch'],dispatch_id='purge-completion-'+str(uuid4())),deadline=limit)
            self._check(limit)
            receipt = await verify_purge_ordinary(verifier,attempt,current,projection,deadline=limit,budget=budget)
            self._check(limit)
            async with controller_finalization(self._supervisor,attempt,deadline=limit):
                await self._authorize(current,limit)
                result = await self._writer.complete_purge(verifier,receipt,deadline=limit)
                self._check(limit)
                return _result(current.intent_id,'purge',result)
        return cast(Mapping[str,Any],await self._run(purge,deadline=deadline,ledger=ledger))

    async def close(self) -> None:
        self._closed = True
        self._cancelled = True
        active = self._active
        if active is not None:
            active.cancel()
            try:
                async with asyncio.timeout(_CLEANUP_SECONDS):
                    await asyncio.shield(active)
            except asyncio.CancelledError:
                if not active.done():
                    raise
            except Exception:
                raise ProviderUnavailable() from None
        await self._verifier.close()
        if self._security_verifier is not None:
            await self._security_verifier.close()
