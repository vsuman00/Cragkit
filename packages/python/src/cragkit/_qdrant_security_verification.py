"""Private security observations bound to one genuine recovery session."""
from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any, cast
from uuid import uuid4
from weakref import WeakKeyDictionary, ref

from ._qdrant_reconciliation import physical_binding
from ._qdrant_security_readback import (SecurityReadbackBudget, security_readback_budget,
                                       verify_security_readback)
from ._qdrant_supervisor import ManagedQdrantSupervisor, _ControlSession, control_session_binding
from ._qdrant_transport import deadline_value
from ._qdrant_writer import PostgresQdrantWriter, security_projection_data, writer_binding, security_recovery_projection
from ._qdrant_writer_contract import WriterContext, context
from .errors import (DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest,
                     ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)

_CLEANUP_SECONDS = 1.0


class SecurityReceipt:
    __slots__ = ('__weakref__',)

    def __repr__(self) -> str:
        return 'SecurityReceipt()'

    def __reduce__(self) -> Any:
        raise TypeError('Security receipts cannot be serialized')


_VERIFIERS: WeakKeyDictionary[QdrantSecurityVerifier, tuple[PostgresQdrantWriter, ManagedQdrantSupervisor]] = WeakKeyDictionary()
_RECEIPTS: WeakKeyDictionary[SecurityReceipt, tuple[QdrantSecurityVerifier, dict[str, Any], Mapping[str, Any]]] = WeakKeyDictionary()
_ORDINARY_VERIFIERS: WeakKeyDictionary[object, Any] = WeakKeyDictionary()
_ORDINARY_RECEIPTS: WeakKeyDictionary[object, tuple[Any, dict[str,Any], Mapping[str,Any]]] = WeakKeyDictionary()


class OrdinarySecurityReceipt:
    __slots__=('__weakref__',)
    def __reduce__(self) -> Any:
        raise TypeError('Security receipts cannot be serialized')


def security_verifier_supervisor(verifier: object, writer: object) -> ManagedQdrantSupervisor:
    original,supervisor=_origin(verifier)
    if original is not writer or cast(QdrantSecurityVerifier,verifier)._closed:raise InvalidRequest()
    return supervisor


async def verify_security_ordinary(verifier: object, attempt: object, value: object, *, deadline: float,
                                   budget: SecurityReadbackBudget | None=None) -> OrdinarySecurityReceipt:
    _origin(verifier)
    if verifier not in _ORDINARY_VERIFIERS:raise InvalidRequest()
    return cast(OrdinarySecurityReceipt,await _ORDINARY_VERIFIERS[verifier](attempt,value,deadline=deadline,budget=budget))


def _ordinary_check(verifier: QdrantSecurityVerifier, record: dict[str,Any], deadline: float) -> None:
    writer,supervisor=_origin(verifier)
    if verifier._closed:raise InvalidRequest()
    _check(record,deadline)
    binding=supervisor.attempt_binding(record['attempt'])
    if dict(binding)!=dict(record['attempt_binding']) or 'recovery_id' in binding:raise UnsupportedCapability()
    profile=supervisor.profile_binding(writer.config)
    if any(profile[key]!=binding[key] for key in ('instance_id','storage_identity','supervisor_id','epoch','credential_generation')):
        raise UnsupportedCapability()


def ordinary_security_receipt_data(receipt: object, verifier: object, *, deadline: float) -> Mapping[str,Any]:
    from ._qdrant_publication_worker import require_publication_finalization
    _,supervisor=_origin(verifier)
    if type(receipt) is not OrdinarySecurityReceipt or receipt not in _ORDINARY_RECEIPTS:raise InvalidRequest()
    issuer,record,data=_ORDINARY_RECEIPTS[receipt]
    if issuer is not verifier:raise InvalidRequest()
    _ordinary_check(cast(QdrantSecurityVerifier,verifier),record,deadline)
    require_publication_finalization(supervisor,deadline=deadline)
    return data


def _origin(value: object) -> tuple[PostgresQdrantWriter, ManagedQdrantSupervisor]:
    if type(value) is not QdrantSecurityVerifier or value not in _VERIFIERS:
        raise InvalidRequest()
    writer,supervisor = _VERIFIERS[value]
    if value._writer is not writer or value._supervisor is not supervisor:
        raise InvalidRequest()
    writer_binding(writer)
    return writer,supervisor


def security_verifier_binding(verifier: object, writer: object, supervisor: object) -> None:
    original_writer,original_supervisor = _origin(verifier)
    assert isinstance(verifier,QdrantSecurityVerifier)
    if original_writer is not writer or original_supervisor is not supervisor or verifier._closed:
        raise InvalidRequest()


def _check(record: dict[str, Any], deadline: float) -> None:
    caller = record['caller']()
    if record['cancelled'] or caller is not None and caller.cancelling():
        raise asyncio.CancelledError()
    requested = deadline_value(deadline)
    deadline_value(record['deadline'])
    if requested > record['deadline']:
        raise InvalidRequest()


def _session(verifier: QdrantSecurityVerifier, record: dict[str, Any], *, deadline: float,
             activity: int | None = None) -> tuple[Mapping[str, Any], int]:
    _,supervisor = _origin(verifier)
    _check(record,deadline)
    current = control_session_binding(record['control'],supervisor,record['proof'])
    physical = physical_binding(dict(current['physical_binding']))
    counter = current['activity']
    if type(counter) is not int or not 0 <= counter <= 9007199254740991:
        raise IntegrityViolation()
    if dict(physical) != dict(record['physical']):
        raise UnsupportedCapability()
    if record['attempt'] is not None and dict(supervisor.attempt_binding(record['attempt'])) != dict(record['attempt_binding']):
        raise UnsupportedCapability()
    if activity is not None and counter != activity:
        raise UnsupportedCapability()
    return physical,counter


def security_receipt_data(receipt: object, verifier: object, control: object, *, deadline: float) -> Mapping[str, Any]:
    writer,supervisor = _origin(verifier)
    assert isinstance(verifier,QdrantSecurityVerifier)
    security_verifier_binding(verifier,writer,supervisor)
    if type(receipt) is not SecurityReceipt or receipt not in _RECEIPTS:
        raise InvalidRequest()
    issuer,record,data = _RECEIPTS[receipt]
    if issuer is not verifier or record['control'] is not control:
        raise InvalidRequest()
    _session(verifier,record,deadline=deadline,activity=data['activity'])
    return data


def _identities(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values),key=lambda value:value.encode('utf-8')))


def _witness(data: Mapping[str, Any], owner: WriterContext, security: WriterContext,
             physical: Mapping[str, Any], attempt: Mapping[str, Any], activity: int) -> tuple[Any, ...]:
    return (
        'cragkit.qdrant.security-readback.v1',
        (physical['instance_id'],physical['storage_identity'],physical['supervisor_id'],physical['recovery_id'],
         str(physical['old_epoch']),str(physical['new_epoch']),physical['credential_generation']),
        (attempt['intent_id'],attempt['owner_token'],str(attempt['epoch']),attempt['dispatch_id'],attempt['recovery_id']),
        str(activity),
        (owner.scope.tenant_id,owner.collection,owner.document_id,owner.intent_id,owner.owner_token),
        (security.scope.tenant_id,security.scope.principal_id,_identities(security.scope.grant_ids),security.scope.authorization_revision),
        (security.intent_id,security.owner_token,data['intent_sha256'],data['authorization_revision'],str(data['mutation_epoch']),
         data['active_generation_id'],'true' if data['tombstoned'] else 'false',_identities(data['principal_ids']),
         _identities(data['grant_ids']),data['language'],data['kind'],data['tag']),
        (data['inventory_sha256'],tuple((group['revision_id'],group['generation_id'],group['manifest_sha256'],
                                        tuple(group['point_ids'])) for group in data['generations'])),
        tuple((point.point_id,point.dense.input_sha256,point.sparse.input_sha256 if point.sparse else None)
              for point in data['points']),
    )


def _safe(error: Exception) -> Exception:
    for kind in (DeadlineExceeded,IndexNotReady,IntegrityViolation,InvalidRequest,ProviderUnavailable,
                 UnauthorizedScope,UnsupportedCapability):
        if type(error) is kind:
            return kind()
    return ProviderUnavailable()


class QdrantSecurityVerifier:
    def __init__(self, writer: PostgresQdrantWriter, supervisor: ManagedQdrantSupervisor) -> None:
        if type(self) is not QdrantSecurityVerifier:
            raise InvalidRequest()
        writer_binding(writer)
        if type(supervisor) is not ManagedQdrantSupervisor:
            raise InvalidRequest()
        self._writer = writer
        self._supervisor = supervisor
        self._closed = False
        self._active: asyncio.Task[Any] | None = None
        self._operation: dict[str, Any] | None = None
        _VERIFIERS[self] = (writer,supervisor)
        original=ref(self)
        fixed=QdrantSecurityVerifier._verify_ordinary
        async def ordinary(attempt: object,value: object,*,deadline: float,budget: SecurityReadbackBudget | None=None) -> OrdinarySecurityReceipt:
            verifier=original()
            if verifier is None:raise InvalidRequest()
            return await fixed(verifier,attempt,value,deadline=deadline,budget=budget)
        _ORDINARY_VERIFIERS[self]=ordinary

    async def _verify_ordinary(self, attempt: object, value: object, *, deadline: float,
                               budget: SecurityReadbackBudget | None=None) -> OrdinarySecurityReceipt:
        writer,supervisor=_origin(self)
        security=context(value);deadline=deadline_value(deadline);allowance=security_readback_budget(budget)
        if self._closed or self._active is not None:raise ProviderUnavailable()
        if writer._schema_profile not in (4,5):raise UnsupportedCapability()
        binding=MappingProxyType(dict(supervisor.attempt_binding(attempt)))
        if ('recovery_id' in binding or binding['intent_id']!=security.intent_id or binding['owner_token']!=security.owner_token
                or binding['instance_id']!=writer_binding(writer)['instance_id']):raise InvalidRequest()
        caller=asyncio.current_task()
        assert caller is not None
        record=dict(caller=ref(caller),deadline=deadline,cancelled=False,attempt=attempt,attempt_binding=binding)
        async def work() -> OrdinarySecurityReceipt:
            handle=None
            try:
                _ordinary_check(self,record,deadline)
                projection=await security_recovery_projection(writer,security,deadline=deadline)
                _ordinary_check(self,record,deadline)
                data=security_projection_data(projection,writer)
                if data['tombstoned']:raise UnauthorizedScope()
                handle=supervisor.transport_for(attempt)
                await verify_security_readback(handle,writer.config,data,deadline=deadline,budget=allowance)
                _ordinary_check(self,record,deadline)
                await handle.close();handle=None
                _ordinary_check(self,record,deadline)
                await security_recovery_projection(writer,security,deadline=deadline,previous=projection)
                _ordinary_check(self,record,deadline)
                witness=(
                    'cragkit.qdrant.security-ordinary-readback.v1',
                    (binding['instance_id'],binding['storage_identity'],binding['supervisor_id'],str(binding['epoch']),
                     binding['credential_generation'],binding['intent_id'],binding['owner_token'],binding['dispatch_id']),
                    (security.scope.tenant_id,security.collection,security.document_id,security.scope.principal_id,
                     _identities(security.scope.grant_ids),security.scope.authorization_revision),
                    (data['intent_sha256'],data['inventory_sha256'],data['active_generation_id'],data['authorization_revision'],
                     str(data['mutation_epoch']),_identities(data['principal_ids']),_identities(data['grant_ids']),
                     data['language'],data['kind'],data['tag'],False),
                    tuple((g['revision_id'],g['generation_id'],g['manifest_sha256'],g['point_ids']) for g in data['generations']),
                    tuple((p.point_id,p.dense.input_sha256,p.sparse.input_sha256 if p.sparse else None) for p in data['points']))
                encoded=json.dumps(witness,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
                digest=hashlib.sha256(encoded).hexdigest()
                result=MappingProxyType(dict(context=security,projection=projection,attempt_binding=binding,
                    intent_sha256=data['intent_sha256'],inventory_sha256=data['inventory_sha256'],readback_sha256=digest,
                    witness=witness,encoded_bytes=encoded,sha256=digest))
                receipt=OrdinarySecurityReceipt();_ORDINARY_RECEIPTS[receipt]=(self,record,result)
                return receipt
            finally:
                if handle is not None:
                    async with asyncio.timeout(_CLEANUP_SECONDS):await handle.close()
        task=asyncio.create_task(work());self._active=task;self._operation=record
        def finished(done: asyncio.Task[Any]) -> None:
            if self._active is done:self._active=None;self._operation=None
            if not done.cancelled():done.exception()
        task.add_done_callback(finished)
        try:
            done,_=await asyncio.wait({task},timeout=max(0,deadline-asyncio.get_running_loop().time()))
            if not done:raise TimeoutError()
            return task.result()
        except (asyncio.CancelledError,TimeoutError) as error:
            record['cancelled']=True;task.cancel()
            done,_=await asyncio.wait({task},timeout=_CLEANUP_SECONDS)
            if not done:self._closed=True
            if isinstance(error,asyncio.CancelledError):raise
            raise DeadlineExceeded() from None
        except Exception as error:raise _safe(error) from None

    async def verify(self, proof: object, control: object, owner_context: object, security_context: object, *,
                     deadline: float, budget: SecurityReadbackBudget | None = None) -> SecurityReceipt:
        writer,supervisor = _origin(self)
        deadline = deadline_value(deadline)
        allowance = security_readback_budget(budget)
        owner,security = context(owner_context),context(security_context)
        if (owner.scope != security.scope or (owner.collection,owner.document_id) != (security.collection,security.document_id)):
            raise InvalidRequest()
        if self._closed or self._active is not None:
            raise ProviderUnavailable()
        binding = control_session_binding(control,supervisor,proof)
        facade = cast(_ControlSession,control)
        physical = physical_binding(dict(binding['physical_binding']))
        if physical['instance_id'] != writer_binding(writer)['instance_id']:
            raise UnsupportedCapability()
        profile = supervisor.profile_binding(writer.config)
        expected_profile = dict(instance_id=physical['instance_id'],storage_identity=physical['storage_identity'],
            supervisor_id=physical['supervisor_id'],epoch=physical['new_epoch'],credential_generation=physical['credential_generation'])
        if any(profile[key] != value for key,value in expected_profile.items()):
            raise UnsupportedCapability()
        caller = asyncio.current_task()
        assert caller is not None
        record: dict[str, Any] = dict(control=control,proof=proof,physical=physical,attempt=None,attempt_binding=None,
                      caller=ref(caller),deadline=deadline,cancelled=False)

        async def work() -> SecurityReceipt:
            handle = None
            try:
                _session(self,record,deadline=deadline)
                projection = await writer.project_security(security,deadline=deadline)
                _session(self,record,deadline=deadline)
                data = security_projection_data(projection,writer)
                if data['context'] != security:
                    raise IntegrityViolation()
                requested = dict(intent_id=owner.intent_id,owner_token=owner.owner_token,epoch=physical['new_epoch'],
                    dispatch_id='security-readback-'+str(uuid4()),recovery_id=physical['recovery_id'])
                attempt = facade.issue_recovery_attempt(proof,requested,deadline=deadline)
                record['attempt'] = attempt
                record['attempt_binding'] = MappingProxyType(dict(
                    instance_id=physical['instance_id'],storage_identity=physical['storage_identity'],
                    supervisor_id=physical['supervisor_id'],credential_generation=physical['credential_generation'],**requested))
                _session(self,record,deadline=deadline)
                handle = facade.recovery_transport_for(attempt)
                await verify_security_readback(handle,writer.config,data,deadline=deadline,budget=allowance)
                # This synchronous snapshot precedes both close and source SQL awaits.
                _,activity = _session(self,record,deadline=deadline)
                await handle.close()
                handle = None
                _session(self,record,deadline=deadline,activity=activity)
                await writer.validate_security_projection(projection,deadline=deadline)
                _session(self,record,deadline=deadline,activity=activity)
                witness = _witness(data,owner,security,physical,record['attempt_binding'],activity)
                encoded = json.dumps(witness,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
                digest = hashlib.sha256(encoded).hexdigest()
                result = MappingProxyType(dict(projection=projection,owner_context=owner,security_context=security,
                    physical_binding=physical,attempt_binding=record['attempt_binding'],activity=activity,
                    intent_sha256=data['intent_sha256'],inventory_sha256=data['inventory_sha256'],point_ids=data['point_ids'],
                    readback_sha256=digest,witness=witness,encoded_bytes=encoded,sha256=digest))
                receipt = SecurityReceipt()
                _RECEIPTS[receipt] = (self,record,result)
                return receipt
            finally:
                if handle is not None:
                    try:
                        async with asyncio.timeout(_CLEANUP_SECONDS):
                            await handle.close()
                    except BaseException:
                        raise ProviderUnavailable() from None

        task = asyncio.create_task(work())
        self._active = task
        self._operation = record
        def finished(done: asyncio.Task[Any]) -> None:
            if self._active is done:
                self._active = None
                self._operation = None
            if not done.cancelled():done.exception()
        task.add_done_callback(finished)
        try:
            async with asyncio.timeout_at(deadline):
                return await asyncio.shield(task)
        except (asyncio.CancelledError,TimeoutError) as error:
            record['cancelled'] = True
            task.cancel()
            try:
                async with asyncio.timeout(_CLEANUP_SECONDS):await asyncio.shield(task)
            except BaseException:
                if not task.done():self._closed = True
            if isinstance(error,asyncio.CancelledError):raise
            raise DeadlineExceeded() from None
        except Exception as error:
            raise _safe(error) from None
        finally:
            if task.done() and self._active is task:
                self._active = None
                self._operation = None

    async def close(self) -> None:
        self._closed = True
        active = self._active
        if active is not None:
            assert self._operation is not None
            self._operation['cancelled'] = True
            active.cancel()
            done,_ = await asyncio.wait({active},timeout=_CLEANUP_SECONDS)
            if not done:raise ProviderUnavailable()
            for task in done:
                if not task.cancelled():task.exception()
