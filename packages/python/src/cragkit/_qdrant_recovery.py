"""Restricted recovery SQL and the private SQL-to-native admission handoff."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from uuid import UUID
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from types import MappingProxyType
from typing import Any, Protocol, TypeVar, cast
from weakref import WeakKeyDictionary, ref

from ._postgres_pool import PoolResource
from ._postgres_session import SessionConnection
from ._qdrant_authority import (
    _CATALOG_FINGERPRINT_SQL, _HISTORY_SQL, _PUBLICATION_CATALOG_SQL,
    EXPECTED_PUBLICATION_CATALOG_FINGERPRINT, EXPECTED_PUBLICATION_HISTORY,
    EXPECTED_ATTESTATION_CATALOG_FINGERPRINT, EXPECTED_ATTESTATION_HISTORY, _ATTESTATION_CATALOG_SQL,
    EXPECTED_SECURITY_GUARD_HISTORY, EXPECTED_SECURITY_GUARD_CATALOG_FINGERPRINT,
    _SECURITY_GUARD_CATALOG_SQL, _SECURITY_GUARD_OWNER_SQL, EXPECTED_PURGE_HISTORY,
    EXPECTED_PURGE_CATALOG_FINGERPRINT, EXPECTED_PURGE_CAPABILITY_FINGERPRINT, _PURGE_CATALOG_SQL,
    _PURGE_OWNER_SQL, _PURGE_CAPABILITY_FINGERPRINT_SQL,
)
from ._qdrant_reconciliation import (
    QdrantReconciliationVerifier, physical_binding, receipt_data, verifier_authority,
    VerificationBudget, verification_budget, _Readback, inspect_missing_readback, projection_data,
)
from ._qdrant_supervisor import ManagedQdrantSupervisor, _config, control_session_binding
from ._qdrant_transport import deadline_value
from ._qdrant_writer import (PostgresQdrantWriter, writer_binding, _safe as writer_error,
    recovery_dispatch_plan_data, security_projection_data, validate_guarded_security_projection,
    security_dispatch_plan_data, security_recovery_projection)
from ._qdrant_writer import _GuardedWriterConnection
from ._qdrant_security_verification import (QdrantSecurityVerifier, security_verifier_binding,
                                           security_receipt_data)
from ._qdrant_security_readback import SecurityReadbackBudget, security_readback_budget
from ._qdrant_writer_contract import WriterContext, context
from .contracts.models import Identity
from ._qdrant_manifest import _parse, _Model
from .errors import (
    CragkitError, DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest,
    ProviderUnavailable, UnauthorizedScope, UnsupportedCapability,
)

_T = TypeVar('_T')
_RECOVERY_ORIGINS: WeakKeyDictionary[
    object, tuple[PoolResource, PostgresQdrantWriter, ManagedQdrantSupervisor,
                  QdrantReconciliationVerifier, object]
] = WeakKeyDictionary()
_DOC = 'tenant_id=%s AND collection=%s AND document_id=%s'
_INTENT = _DOC + ' AND intent_id=%s'
_BACKEND_FIELDS = ('backend_namespace', 'storage_identity', 'supervisor_id',
                   'epoch', 'state', 'recovery_id')
_DOCUMENT_FIELDS = ('active_generation_id','authorization_revision','mutation_epoch','principal_ids',
                    'grant_ids','language','kind','tag','tombstoned')
_SECURITY_JOURNAL_COLUMNS = ('dispatch_id,instance_id,sequence,owner_token::text,backend_epoch,'
    'credential_generation,operation,recovery,request_sha256,created_xid::text,state,completion_sha256')
_SECURITY_MEMBER_COLUMNS = 'dispatch_id,backend_namespace,physical_collection,collection_incarnation,point_id::text'
_GUARD_DRIVERS: WeakKeyDictionary[object, Callable[..., Awaitable[None]]] = WeakKeyDictionary()
_SECURITY_SETTLERS: WeakKeyDictionary[object, Callable[..., Awaitable[Mapping[str, Any]]]] = WeakKeyDictionary()
_SECURITY_DISPATCHERS: WeakKeyDictionary[object, Callable[..., Awaitable[Mapping[str, Any]]]] = WeakKeyDictionary()
_GUARDS: WeakKeyDictionary[object, dict[str, Any]] = WeakKeyDictionary()


class _SecurityGuard:
    __slots__ = ('__weakref__',)

    def __reduce__(self) -> Any:
        raise TypeError('Security guards cannot be serialized')


def _guard_check(record: dict[str, Any], *, deadline: float) -> None:
    requested = deadline_value(deadline)
    deadline_value(record['deadline'])
    if requested > record['deadline']:
        raise InvalidRequest()
    task = asyncio.current_task()
    scope = record['scope']
    if task is not scope['task']:
        raise InvalidRequest()
    if scope['cancelled'] or task is None or task.cancelling():
        raise asyncio.CancelledError()
    recovery = record['recovery']
    resource,writer,supervisor,_,_ = _recovery_origin(recovery)
    if (recovery._closed or writer._closed or scope['poisoned'] or record['poisoned'] or record['ending']
            or recovery._active is not task or recovery._guard_scope is not scope
            or recovery._guard_transaction is not record or recovery._scoped_control is not record['control']
            or resource is not record['resource'] or writer is not record['writer']
            or supervisor is not record['supervisor']):
        raise ProviderUnavailable()
    connection = record['connection']
    status = connection.info.transaction_status
    if isinstance(status,bool) or not isinstance(status,int) or status != 2:
        raise ProviderUnavailable()
    security_verifier_binding(record['verifier'],writer,supervisor)
    receipt = security_receipt_data(record['receipt'],record['verifier'],record['control'],deadline=record['deadline'])
    if receipt is not record['receipt_data'] or receipt['projection'] is not record['projection']:
        raise InvalidRequest()
    security_projection_data(record['projection'],writer)


def _guard_boundary(record: dict[str, Any], *, deadline: float) -> None:
    try:
        _guard_check(record,deadline=deadline)
    except BaseException:
        # Invalid caller copies/options cannot poison someone else's operation.
        # Actual custody loss is irreversible even if a continuation catches it.
        if (asyncio.current_task() is record['scope']['task'] and type(deadline) in (int,float)
                and deadline <= record['deadline']):
            record['poisoned'] = True
            record['valid'] = False
        raise


def security_guard_binding(guard: object, writer: object, projection: object, *, deadline: float) -> Mapping[str, Any]:
    if type(guard) is not _SecurityGuard or guard not in _GUARDS:
        raise InvalidRequest()
    record = _GUARDS[guard]
    if record['writer'] is not writer or record['projection'] is not projection:
        raise InvalidRequest()
    _guard_boundary(record,deadline=deadline)
    if not record['valid']:
        raise InvalidRequest()
    return cast(Mapping[str, Any], record['metadata'])


async def validate_security_guarded(recovery: object, security_verifier: object, proof: object,
                                    owner_context: object, security_context: object, *,
                                    deadline: float, budget: SecurityReadbackBudget | None = None) -> None:
    _recovery_origin(recovery)
    if recovery not in _GUARD_DRIVERS:
        raise InvalidRequest()
    await _GUARD_DRIVERS[recovery](security_verifier,proof,owner_context,security_context,
                                 deadline=deadline,budget=budget)


async def settle_security_guarded(recovery: object, security_verifier: object, proof: object,
                                  owner_context: object, security_context: object, *, deadline: float,
                                  budget: SecurityReadbackBudget | None = None) -> Mapping[str, Any]:
    _recovery_origin(recovery)
    if recovery not in _SECURITY_SETTLERS:
        raise InvalidRequest()
    return await _SECURITY_SETTLERS[recovery](security_verifier,proof,owner_context,security_context,
                                             deadline=deadline,budget=budget)


def _confirmation_boundary(record: dict[str, Any], *, attached: bool = True) -> None:
    deadline_value(record['deadline'])
    task=asyncio.current_task();scope=record['scope'];recovery=record['recovery']
    if task is not scope['task']:
        raise InvalidRequest()
    if scope['cancelled'] or task is None or task.cancelling():
        raise asyncio.CancelledError()
    _recovery_origin(recovery)
    if (recovery._closed or scope['poisoned'] or record['ending']
            or recovery._active is not task or recovery._guard_scope is not scope
            or recovery._scoped_control is not record['control']):
        raise ProviderUnavailable()
    if attached:
        status=record['connection'].info.transaction_status
        if (recovery._security_confirmation is not record or isinstance(status,bool)
                or not isinstance(status,int) or status!=2):
            raise ProviderUnavailable()
    current=control_session_binding(record['control'],recovery.supervisor,record['proof'])
    if dict(current['physical_binding'])!=dict(record['physical']) or current['activity']!=record['activity']:
        raise UnsupportedCapability()
_SUPERVISOR_ROLE_SQL = """
SELECT current_user=session_user
 AND EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolcanlogin)
 AND EXISTS(SELECT 1 FROM pg_roles r WHERE r.rolname='cragkit_qdrant_supervisor'
  AND NOT (r.rolcanlogin OR r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication)
  AND NOT EXISTS(SELECT 1 FROM pg_auth_members m WHERE m.member=r.oid))
 AND pg_has_role(current_user,'cragkit_qdrant_supervisor','USAGE')
 AND NOT pg_has_role(current_user,'cragkit_qdrant_writer','MEMBER')
 AND NOT EXISTS(SELECT 1 FROM pg_roles r WHERE pg_has_role(current_user,r.oid,'MEMBER') AND
  (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR
   r.rolname IN ('pg_read_all_data','pg_write_all_data','pg_read_server_files','pg_write_server_files','pg_execute_server_program')))
 AND NOT EXISTS(SELECT 1 FROM pg_database WHERE pg_has_role(current_user,datdba,'MEMBER'))
 AND has_schema_privilege(current_user,'cragkit_qdrant','USAGE')
 AND NOT EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname='cragkit_qdrant' AND
  (pg_has_role(current_user,n.nspowner,'MEMBER') OR has_schema_privilege(current_user,n.oid,'CREATE')))
 AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='cragkit_qdrant' AND (pg_has_role(current_user,c.relowner,'MEMBER')
   OR (c.relkind='r' AND c.relname<>'schema_migrations' AND NOT row_security_active(c.oid))))
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='cragkit_qdrant' AND pg_has_role(current_user,p.proowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
  WHERE n.nspname='cragkit_qdrant' AND pg_has_role(current_user,t.typowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) privilege
  WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND
  has_table_privilege(current_user,c.oid,privilege) IS DISTINCT FROM CASE
   WHEN privilege='SELECT' THEN c.relname IN ('schema_migrations','backend_instances','document_owners','point_claims','dispatch_points','preparations')
   WHEN privilege='INSERT' THEN c.relname IN ('backend_instances','dispatch_journal','dispatch_points')
   WHEN privilege='UPDATE' THEN c.relname='backend_instances'
   ELSE false END)
 AND NOT EXISTS(SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid
  JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) privilege
  WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped AND
  has_column_privilege(current_user,c.oid,a.attnum,privilege) IS DISTINCT FROM CASE
   WHEN privilege='SELECT' THEN c.relname IN ('schema_migrations','backend_instances','document_owners','point_claims','dispatch_points','preparations')
    OR (c.relname='publication_intents' AND a.attname IN ('tenant_id','collection','document_id','intent_id','instance_id','action','payload_sha256','manifest_sha256','revision_id','generation_id','expected_active_generation_id','expected_authorization_revision','expected_mutation_epoch','state','authority_committed','replica_complete','purge_complete'))
    OR (c.relname='dispatch_journal' AND a.attname IN ('tenant_id','collection','document_id','intent_id','dispatch_id','instance_id','sequence','owner_token','backend_epoch','credential_generation','operation','recovery','request_sha256','state','completion_sha256','created_xid'))
   WHEN privilege='INSERT' THEN c.relname IN ('backend_instances','dispatch_journal','dispatch_points')
   WHEN privilege='UPDATE' THEN c.relname='backend_instances'
    OR (c.relname='document_owners' AND a.attname='backend_epoch')
    OR (c.relname='dispatch_journal' AND a.attname IN ('state','completion_sha256'))
   ELSE false END)
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='cragkit_qdrant' AND has_function_privilege(current_user,p.oid,'EXECUTE')
  IS DISTINCT FROM (
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.valid_identity_array(text[])') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.scope_grants()') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.writer_scope(text,text,text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.bound_stage(text,text,text,text,text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.supervisor_instance(text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.lock_publication_owner(text,text,text,text,uuid,bigint,boolean)')))
"""
_SECURITY_GUARD_SIGNATURE = 'cragkit_qdrant.lock_current_security(text,text,text,text,text,bigint,text,text,text,text,uuid,text,text,text,text,bigint,text[],text[],text,text,text,boolean)'
_SUPERVISOR_SECURITY_GUARD_ROLE_SQL = _SUPERVISOR_ROLE_SQL.replace(
    "p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.valid_identity_array(text[])') OR",
    "p.oid IS NOT DISTINCT FROM to_regprocedure('" + _SECURITY_GUARD_SIGNATURE + "') OR\n"
    "   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.valid_identity_array(text[])') OR")

_SUPERVISOR_PURGE_ROLE_SQL = _SUPERVISOR_SECURITY_GUARD_ROLE_SQL.replace(
    "OR (c.relname='publication_intents' AND a.attname IN",
    "OR (c.relname='documents' AND a.attname IN ('tenant_id','collection','document_id','content_unavailable'))\n"
    "    OR (c.relname='publication_intents' AND a.attname IN"
).replace("WHEN privilege='UPDATE' THEN c.relname='backend_instances'\n"
    "    OR (c.relname='document_owners'",
    "WHEN privilege='UPDATE' THEN c.relname='backend_instances'\n"
    "    OR (c.relname='documents' AND a.attname='content_unavailable')\n"
    "    OR (c.relname='document_owners'"
).replace("p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.valid_identity_array(text[])') OR",
    "p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)') OR\n"
    "   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.valid_identity_array(text[])') OR")


class _RecoveryId(_Model):
    recovery_id: Identity


class _CommitUnknown(Exception):
    """Internal signal: discard the lease and reconcile the same identity."""


class _ScopedControl(Protocol):
    def block_ordinary(self) -> None: ...

    async def recover(self, request: object, *, deadline: float) -> object: ...

    async def seal_recovery(self, proof: object, *, deadline: float) -> object: ...

    def finish_recovery(self, barrier: object, settlement: object, *, deadline: float) -> None: ...

    def issue_recovery_attempt(self, proof: object, binding: object, *, deadline: float) -> object: ...

    def recovery_transport_for(self, attempt: object) -> Any: ...


class _RecoveryDispatchAuthorization:
    __slots__ = ('__weakref__',)
    def __repr__(self) -> str:
        return 'RecoveryDispatchAuthorization()'
    def __reduce__(self) -> Any:
        raise TypeError('Dispatch authorizations cannot be serialized')


_DISPATCH_AUTHORIZATIONS: WeakKeyDictionary[_RecoveryDispatchAuthorization, dict[str, Any]] = WeakKeyDictionary()


class _SecurityDispatchAuthorization:
    __slots__=('__weakref__',)

    def __reduce__(self) -> Any:
        raise TypeError('Security dispatch authorizations cannot be serialized')


_SECURITY_DISPATCH_AUTHORIZATIONS: WeakKeyDictionary[_SecurityDispatchAuthorization, dict[str, Any]] = WeakKeyDictionary()


def security_dispatch_authorization(value: object, expected_writer: object, *, deadline: float) -> Mapping[str, Any]:
    _dispatch_check(deadline)
    if type(value) is not _SecurityDispatchAuthorization or value not in _SECURITY_DISPATCH_AUTHORIZATIONS:
        raise InvalidRequest()
    record=_SECURITY_DISPATCH_AUTHORIZATIONS[value];owner=record['owner'];scope=record['scope']
    _,writer,supervisor,_,_=_recovery_origin(owner)
    if (writer is not expected_writer or not record['active'] or deadline>record['deadline']
            or owner._active is not asyncio.current_task() or record['task'] is not asyncio.current_task()
            or owner._scoped_control is not record['control'] or owner._guard_scope is not scope):
        raise InvalidRequest()
    _dispatch_check(record['deadline'])
    if scope['cancelled'] or scope['poisoned'] or owner._closed or writer._closed:
        raise ProviderUnavailable()
    actual=control_session_binding(record['control'],supervisor,record['proof'])
    if (dict(actual['physical_binding'])!=dict(record['data']['physical_binding'])
            or dict(supervisor.attempt_binding(record['attempt']))!=dict(record['data']['attempt_binding'])):
        raise UnsupportedCapability()
    return cast(Mapping[str, Any],record['data'])


async def dispatch_security_recovery(recovery: object, proof: object, owner_context: object,
                                     security_context: object, authorize: object, *, deadline: float,
                                     budget: SecurityReadbackBudget | None = None) -> Mapping[str, Any]:
    _recovery_origin(recovery)
    if recovery not in _SECURITY_DISPATCHERS:
        raise InvalidRequest()
    return await _SECURITY_DISPATCHERS[recovery](proof,owner_context,security_context,authorize,
                                               deadline=deadline,budget=budget)


def _dispatch_check(deadline: float) -> None:
    deadline_value(deadline)
    task = asyncio.current_task()
    if task is None:
        raise InvalidRequest()
    if task.cancelling():
        raise asyncio.CancelledError()


def recovery_dispatch_authorization(value: object, expected_writer: object, *, deadline: float) -> Mapping[str, Any]:
    _dispatch_check(deadline)
    if type(value) is not _RecoveryDispatchAuthorization or value not in _DISPATCH_AUTHORIZATIONS:
        raise InvalidRequest()
    record = _DISPATCH_AUTHORIZATIONS[value]
    owner = record['owner']
    _, writer, supervisor, _, _ = _recovery_origin(owner)
    if (writer is not expected_writer or not record['active'] or owner._active is not asyncio.current_task()
            or record['task'] is not asyncio.current_task() or owner._scoped_control is not record['control']
            or deadline > record['deadline']):
        raise InvalidRequest()
    _dispatch_check(record['deadline'])
    if (dict(supervisor.recovery_binding(record['proof'])) != dict(record['data']['physical_binding'])
            or dict(supervisor.attempt_binding(record['attempt'])) != dict(record['data']['attempt_binding'])):
        raise UnsupportedCapability()
    return cast(Mapping[str, Any], record['data'])


class _SQLSettlement:
    __slots__ = ('__weakref__',)

    def __repr__(self) -> str:
        return 'SQLSettlement()'

    def __reduce__(self) -> Any:
        raise TypeError('Settlements cannot be serialized')


_SETTLEMENTS: WeakKeyDictionary[
    _SQLSettlement, tuple[object, object, Mapping[str, Any]]
] = WeakKeyDictionary()


def settlement_data(token: object, supervisor: object, barrier: object) -> Mapping[str, Any]:
    """Validate one private committed handoff; no public minting function exists."""
    if type(token) is not _SQLSettlement or token not in _SETTLEMENTS:
        raise UnsupportedCapability()
    issuer, issued_barrier, physical = _SETTLEMENTS[token]
    if issuer is not supervisor or issued_barrier is not barrier:
        raise UnsupportedCapability()
    assert type(supervisor) is ManagedQdrantSupervisor
    if dict(supervisor.barrier_binding(barrier)) != dict(physical):
        raise UnsupportedCapability()
    del _SETTLEMENTS[token]
    return physical


def _target(value: WriterContext) -> tuple[object, ...]:
    return value.scope.tenant_id, value.collection, value.document_id


def _intent(value: WriterContext) -> tuple[object, ...]:
    return (*_target(value), value.intent_id)


def _recovery_origin(value: object) -> tuple[
        PoolResource, PostgresQdrantWriter, ManagedQdrantSupervisor,
        QdrantReconciliationVerifier, object]:
    if type(value) is not PostgresQdrantRecovery or value not in _RECOVERY_ORIGINS:
        raise InvalidRequest()
    original = _RECOVERY_ORIGINS[value]
    resource, writer, supervisor, verifier, config = original
    if (value.resource is not resource or value._writer is not writer
            or value.supervisor is not supervisor or value.verifier is not verifier
            or value.config is not config):
        raise InvalidRequest()
    writer_binding(writer)
    if (verifier_authority(verifier, supervisor) is not writer
            or verifier.writer is not writer or verifier.supervisor is not supervisor):
        raise InvalidRequest()
    return original


def recovery_components(value: object, expected_writer: object, expected_supervisor: object,
                        expected_config: object) -> QdrantReconciliationVerifier:
    """Resolve only the original issuer-bound verifier, without initializing."""
    if (type(expected_writer) is not PostgresQdrantWriter
            or type(expected_supervisor) is not ManagedQdrantSupervisor):
        raise InvalidRequest()
    _, writer, supervisor, verifier, config = _recovery_origin(value)
    if writer is not expected_writer or supervisor is not expected_supervisor:
        raise InvalidRequest()
    parsed = _config(expected_config)
    original_config = writer_binding(writer)['config']
    if parsed != config or parsed != original_config:
        raise UnsupportedCapability()
    return verifier


def _error(error: Exception, deadline: float) -> CragkitError:
    try:
        code = getattr(error, 'sqlstate', None)
    except Exception:
        code = None
    if type(code) is str:
        if code in ('42704', '3F000'):
            return UnsupportedCapability()
        if code == '23502':
            return IntegrityViolation()
    return writer_error(error, deadline)


class PostgresQdrantRecovery:
    """Borrow dedicated supervisor SQL, the actual controller and its verifier."""

    def __init__(self, resource: PoolResource, config: object,
                 supervisor: ManagedQdrantSupervisor,
                 verifier: QdrantReconciliationVerifier) -> None:
        if type(resource) is not PoolResource or type(supervisor) is not ManagedQdrantSupervisor:
            raise InvalidRequest()
        self._writer = verifier_authority(verifier, supervisor)
        self.config = _config(config)
        self.resource = resource
        self.supervisor = supervisor
        self.verifier = verifier
        self._identity: Mapping[str, Any] | None = None
        self._ready = False
        self._schema_profile = 2
        self._security_guard_admitted = False
        self._closed = False
        self._active: asyncio.Task[Any] | None = None
        self._scoped_control: _ScopedControl | None = None
        self._guard_scope: dict[str, Any] | None = None
        self._guard_transaction: dict[str, Any] | None = None
        self._security_confirmation: dict[str, Any] | None = None
        _RECOVERY_ORIGINS[self] = (resource, self._writer, supervisor, verifier, self.config)
        fixed = PostgresQdrantRecovery._validate_security_guarded
        original = ref(self)
        async def guarded(*args: Any, **kwargs: Any) -> None:
            recovery = original()
            if recovery is None:
                raise InvalidRequest()
            await fixed(recovery,*args,**kwargs)
        _GUARD_DRIVERS[self] = guarded
        async def settle(*args: Any, **kwargs: Any) -> Mapping[str, Any]:
            recovery=original()
            if recovery is None:
                raise InvalidRequest()
            return cast(Mapping[str, Any],await fixed(recovery,*args,**kwargs,settle=True))
        _SECURITY_SETTLERS[self]=settle
        dispatch_fixed=PostgresQdrantRecovery._dispatch_security_owned
        async def dispatch(*args: Any,**kwargs: Any) -> Mapping[str, Any]:
            recovery=original()
            if recovery is None:raise InvalidRequest()
            return await dispatch_fixed(recovery,*args,**kwargs)
        _SECURITY_DISPATCHERS[self]=dispatch

    def _control(self) -> _ScopedControl:
        if self._scoped_control is None:
            raise ProviderUnavailable()
        return self._scoped_control

    @asynccontextmanager
    async def _operation(self, deadline: float, *, initialize: bool = False) -> AsyncIterator[None]:
        _recovery_origin(self)
        deadline_value(deadline)
        if self._closed or self._active is not None:
            raise ProviderUnavailable()
        if self._guard_scope is not None and self._guard_scope['task'] is not asyncio.current_task():
            raise ProviderUnavailable()
        if not initialize and not self._ready:
            raise IndexNotReady()
        self._active = asyncio.current_task()
        completed = False
        try:
            async with asyncio.timeout_at(deadline):
                async with self.supervisor.control_session() as scoped:
                    self._scoped_control = scoped
                    try:
                        yield
                    finally:
                        self._scoped_control = None
            completed = True
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise DeadlineExceeded() from None
        except Exception as error:
            raise _error(error, deadline) from None
        finally:
            if initialize and not completed:
                self._ready = False
            self._active = None

    async def _query(self, connection: SessionConnection, sql: str,
                     params: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
        guard = self._guard_transaction
        confirmation=self._security_confirmation
        if confirmation is not None and confirmation['connection'] is connection:
            _confirmation_boundary(confirmation)
        if guard is not None and guard['connection'] is connection:
            _guard_boundary(guard,deadline=guard['deadline'])
        cursor = await connection.execute(sql, params)
        if confirmation is not None and confirmation['connection'] is connection:
            _confirmation_boundary(confirmation)
        if guard is not None and guard['connection'] is connection:
            _guard_boundary(guard,deadline=guard['deadline'])
        rows = await cursor.fetchall()
        if confirmation is not None and confirmation['connection'] is connection:
            _confirmation_boundary(confirmation)
        if guard is not None and guard['connection'] is connection:
            _guard_boundary(guard,deadline=guard['deadline'])
        if type(rows) is not list or any(type(row) is not tuple for row in rows):
            raise IntegrityViolation()
        return rows

    @staticmethod
    def _history_profile(rows: list[tuple[Any, ...]]) -> int:
        if (type(rows) is not list or len(rows) not in (2, 3, 4, 5)
                or any(type(row) is not tuple or len(row) != 2
                       or any(type(value) is not str for value in row) for row in rows)):
            raise UnsupportedCapability()
        for profile, history in ((2, EXPECTED_PUBLICATION_HISTORY),
                                 (3, EXPECTED_ATTESTATION_HISTORY),
                                 (4, EXPECTED_SECURITY_GUARD_HISTORY),
                                 (5, EXPECTED_PURGE_HISTORY)):
            if rows == list(history):
                return profile
        raise UnsupportedCapability()

    async def _catalog_profile(self, connection: SessionConnection, profile: int) -> None:
        catalog, fingerprint = {
            2: (_PUBLICATION_CATALOG_SQL, EXPECTED_PUBLICATION_CATALOG_FINGERPRINT),
            3: (_ATTESTATION_CATALOG_SQL, EXPECTED_ATTESTATION_CATALOG_FINGERPRINT),
            4: (_SECURITY_GUARD_CATALOG_SQL, EXPECTED_SECURITY_GUARD_CATALOG_FINGERPRINT),
            5: (_PURGE_CATALOG_SQL, EXPECTED_PURGE_CATALOG_FINGERPRINT),
        }[profile]
        checks: list[tuple[str, object]] = [(catalog, True), (_CATALOG_FINGERPRINT_SQL, fingerprint)]
        if profile == 4:
            checks.append((_SECURITY_GUARD_OWNER_SQL, True))
        elif profile == 5:
            checks.extend(((_PURGE_OWNER_SQL, True),
                           (_PURGE_CAPABILITY_FINGERPRINT_SQL, EXPECTED_PURGE_CAPABILITY_FINGERPRINT)))
        for sql, expected in checks:
            try:
                rows = await self._query(connection, sql)
            except IntegrityViolation:
                raise UnsupportedCapability() from None
            if (type(rows) is not list or len(rows) != 1 or type(rows[0]) is not tuple
                    or len(rows[0]) != 1 or type(rows[0][0]) is not type(expected)
                    or rows[0][0] != expected):
                raise UnsupportedCapability()

    async def _transaction(self, deadline: float,
                           action: Callable[[SessionConnection], Awaitable[_T]], *,
                           initializing: bool = False,
                           guarded: dict[str, Any] | None = None,
                           confirmation: dict[str, Any] | None = None) -> _T:
        if confirmation is not None:_confirmation_boundary(confirmation,attached=False)
        async with self.resource.lease(deadline=deadline) as leased:
            connection = cast(SessionConnection, leased)
            if connection.info.transaction_status != 0:
                async with asyncio.timeout(self.resource.config.release_timeout):
                    await connection.close()
                raise InvalidRequest()
            transaction = connection.transaction()
            entered = False
            committing = False
            try:
                if confirmation is not None:_confirmation_boundary(confirmation,attached=False)
                await transaction.__aenter__()
                entered = True
                if confirmation is not None:
                    confirmation['connection']=connection;confirmation['transaction']=transaction
                    self._security_confirmation=confirmation
                    _confirmation_boundary(confirmation)
                    connection=cast(SessionConnection,_GuardedWriterConnection(connection,
                        lambda:_confirmation_boundary(confirmation)))
                if guarded is not None:
                    guarded['connection'] = connection
                    guarded['transaction'] = transaction
                    self._guard_transaction = guarded
                    _guard_boundary(guarded,deadline=deadline)
                await connection.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED'+(' READ ONLY' if confirmation is not None and confirmation.get('read_only',True) else ''))
                if confirmation is not None:_confirmation_boundary(confirmation)
                await connection.execute('SET LOCAL search_path=pg_catalog')
                if confirmation is not None:_confirmation_boundary(confirmation)
                milliseconds = max(1, min(2147483647, int(
                    (deadline - asyncio.get_running_loop().time()) * 1000)))
                await connection.execute("SELECT set_config('statement_timeout',%s,true)",
                                         (str(milliseconds),))
                if confirmation is not None:_confirmation_boundary(confirmation)
                try:
                    profile = self._history_profile(await self._query(connection, _HISTORY_SQL))
                except IntegrityViolation:
                    raise UnsupportedCapability() from None
                if ((self._security_guard_admitted and profile != self._schema_profile)
                        or (not initializing and profile != self._schema_profile)):
                    raise UnsupportedCapability()
                if initializing or profile in (4, 5):
                    await self._catalog_profile(connection, profile)
                role_sql = (_SUPERVISOR_PURGE_ROLE_SQL if profile == 5 else
                            _SUPERVISOR_SECURITY_GUARD_ROLE_SQL if profile == 4 else _SUPERVISOR_ROLE_SQL)
                try:
                    role = await self._query(connection, role_sql)
                except IntegrityViolation:
                    raise UnsupportedCapability() from None
                if (type(role) is not list or len(role) != 1 or type(role[0]) is not tuple
                        or len(role[0]) != 1 or role[0][0] is not True):
                    raise UnauthorizedScope()
                if initializing:
                    # Keep lost-COMMIT confirmation bound to this exact profile.
                    self._schema_profile = profile
                if self._identity is not None:
                    if confirmation is not None:_confirmation_boundary(confirmation)
                    if guarded is not None:
                        _guard_boundary(guarded,deadline=deadline)
                    await connection.execute(
                        "SELECT set_config('cragkit_qdrant.backend_instance_id',%s,true)",
                        (self._identity['instance_id'],))
                    if guarded is not None:
                        _guard_boundary(guarded,deadline=deadline)
                    if confirmation is not None:_confirmation_boundary(confirmation)
                result = await action(connection)
                _dispatch_check(deadline)
                if guarded is not None:
                    _guard_boundary(guarded,deadline=deadline)
                    if not guarded['required'] or not guarded['validated'] or guarded['valid']:
                        raise ProviderUnavailable()
                    guarded['ending'] = True
                if confirmation is not None:
                    _confirmation_boundary(confirmation)
                    confirmation['ending']=True
                committing = True
                await transaction.__aexit__(None, None, None)
                entered = False
                if connection.info.transaction_status != 0:
                    raise ProviderUnavailable()
                deadline_value(deadline)
                return result
            except (TimeoutError, DeadlineExceeded):
                raise
            except Exception as error:
                if committing:
                    try:
                        sqlstate = getattr(error, 'sqlstate', None)
                    except Exception:
                        sqlstate = None
                    if type(sqlstate) is not str or sqlstate not in (
                        '23502', '23503', '23505', '23514', '40001', '40P01', '57014',
                    ):
                        raise _CommitUnknown() from None
                raise
            finally:
                if confirmation is not None:confirmation['ending']=True
                if guarded is not None:
                    guarded['valid'] = False
                    guarded['ending'] = True
                try:
                    if entered:
                        async def cleanup() -> None:
                            try:
                                async with asyncio.timeout(self.resource.config.release_timeout):
                                    if committing:
                                        await connection.close()
                                    else:
                                        await transaction.__aexit__(Exception, Exception(), None)
                                        if connection.info.transaction_status != 0:
                                            await connection.close()
                            except BaseException:
                                try:
                                    async with asyncio.timeout(self.resource.config.release_timeout):
                                        await connection.close()
                                except BaseException:
                                    pass
                        task = asyncio.create_task(cleanup())
                        try:
                            await asyncio.shield(task)
                        except asyncio.CancelledError:
                            await asyncio.shield(task)
                            raise
                finally:
                    if guarded is not None and self._guard_transaction is guarded:
                        self._guard_transaction = None
                    if confirmation is not None and self._security_confirmation is confirmation:
                        self._security_confirmation=None

    async def _settle_security_rows(self, connection: SessionConnection, target: WriterContext,
                                    physical: Mapping[str, Any], projection: Mapping[str, Any],
                                    completion: str) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        intent=await self._query(connection,'SELECT action,instance_id,manifest_sha256,revision_id,generation_id '
            'FROM cragkit_qdrant.publication_intents WHERE '+_INTENT,_intent(target))
        if len(intent)!=1 or len(intent[0])!=5:
            raise IntegrityViolation()
        action,instance,manifest,revision,generation=intent[0]
        if any(type(value) is not str for value in intent[0]):
            raise IntegrityViolation()
        if action!='stage':
            raise UnsupportedCapability()
        groups=[group for group in projection['generations'] if
                (group['revision_id'],group['generation_id'],group['manifest_sha256'])==(revision,generation,manifest)]
        if instance!=physical['instance_id'] or len(groups)!=1:
            raise IntegrityViolation()
        foreign=await self._query(connection,'SELECT 1 FROM cragkit_qdrant.dispatch_journal WHERE '+_DOC+
            " AND intent_id<>%s AND state<>'settled' LIMIT 1",_intent(target))
        if foreign:
            raise ProviderUnavailable()
        rows=await self._query(connection,'SELECT '+_SECURITY_JOURNAL_COLUMNS+
            ' FROM cragkit_qdrant.dispatch_journal WHERE '+_INTENT+' ORDER BY sequence LIMIT 257 FOR UPDATE',_intent(target))
        members=await self._query(connection,'SELECT '+_SECURITY_MEMBER_COLUMNS+
            ' FROM cragkit_qdrant.dispatch_points WHERE '+_INTENT+' LIMIT 2049',_intent(target))
        if len(rows)>256 or len(members)>2048:
            raise IntegrityViolation()
        identifiers=set();sequences=set();pending=[]
        def identity(value: object) -> None:
            if type(value) is not str:
                raise IntegrityViolation()
            try:
                _parse(_RecoveryId,{'recovery_id':value})
            except InvalidRequest:
                raise IntegrityViolation() from None
        for row in rows:
            if len(row)!=12:
                raise IntegrityViolation()
            dispatch,instance,sequence,owner,epoch,credential,operation,recovery,request,xid,state,digest=row
            identity(dispatch);identity(credential)
            if (type(sequence) is not int or not 1<=sequence<=256
                    or dispatch in identifiers or sequence in sequences or type(epoch) is not int
                    or not 1<=epoch<=physical['new_epoch'] or instance!=physical['instance_id']
                    or type(instance) is not str or type(owner) is not str or owner!=target.owner_token
                    or type(recovery) is not bool or type(request) is not str or re.fullmatch('[0-9a-f]{64}',request) is None
                    or type(xid) is not str or re.fullmatch('[1-9][0-9]{0,19}',xid) is None
                    or int(xid)>18446744073709551615 or type(state) is not str
                    or state not in ('reserved','dispatched','unknown','settled')):
                raise IntegrityViolation()
            if operation!='complete_point_upsert' or type(operation) is not str:
                raise UnsupportedCapability()
            if state=='settled':
                if type(digest) is not str or re.fullmatch('[0-9a-f]{64}',digest) is None:
                    raise IntegrityViolation()
            else:
                if digest is not None:
                    raise IntegrityViolation()
                if credential==physical['credential_generation']:
                    raise ProviderUnavailable()
                pending.append(row)
            identifiers.add(dispatch);sequences.add(sequence)
        grouped: dict[str, set[str]]={row[0]:set() for row in rows}
        headers={row[0]:row for row in rows}
        physical_tuple=(self.config.backend_namespace,self.config.physical_collection,self.config.collection_incarnation)
        for member in members:
            if (len(member)!=5 or any(type(item) is not str for item in member)
                    or member[0] not in grouped or member[1:4]!=physical_tuple):
                raise IntegrityViolation()
            selected=projection['point_ids'] if headers[member[0]][7] else groups[0]['point_ids']
            try:
                parsed=UUID(member[4])
                if str(parsed)!=member[4] or parsed.version!=5:raise ValueError()
            except (ValueError,AttributeError):
                raise IntegrityViolation() from None
            if member[4] not in selected or member[4] in grouped[member[0]]:
                raise IntegrityViolation()
            grouped[member[0]].add(member[4])
        if any(not 1<=len(points)<=8 for points in grouped.values()):
            raise IntegrityViolation()
        attempted=tuple(sorted(row[0] for row in pending))
        snapshot=MappingProxyType(dict(headers=tuple(sorted((row[:10] for row in pending),key=lambda row:row[0])),
            members=tuple(sorted(row for row in members if row[0] in attempted)),completion=completion))
        for dispatch in attempted:
            changed=await self._query(connection,"UPDATE cragkit_qdrant.dispatch_journal SET state='settled',completion_sha256=%s WHERE "+
                _INTENT+" AND dispatch_id=%s AND state IN ('reserved','dispatched','unknown') AND completion_sha256 IS NULL RETURNING dispatch_id",
                (completion,*_intent(target),dispatch))
            if len(changed)!=1 or changed[0]!=(dispatch,):
                raise IntegrityViolation()
        return MappingProxyType({'settled_count':len(attempted)}),snapshot

    async def _confirm_security_rows(self, connection: SessionConnection, target: WriterContext,
                                     snapshot: Mapping[str, Any]) -> None:
        expected=snapshot['headers'];identifiers=[row[0] for row in expected]
        try:
            rows=await self._query(connection,'SELECT '+_SECURITY_JOURNAL_COLUMNS+
                ' FROM cragkit_qdrant.dispatch_journal WHERE '+_INTENT+
                ' AND dispatch_id=ANY(%s::text[]) ORDER BY sequence LIMIT 257',(*_intent(target),identifiers))
            members=await self._query(connection,'SELECT '+_SECURITY_MEMBER_COLUMNS+
                ' FROM cragkit_qdrant.dispatch_points WHERE '+_INTENT+
                ' AND dispatch_id=ANY(%s::text[]) LIMIT 2049',(*_intent(target),identifiers))
        except IntegrityViolation:
            raise ProviderUnavailable() from None
        if (len(rows)!=len(expected) or any(len(row)!=12 for row in rows)
                or len({row[0] for row in rows})!=len(rows)
                or any(type(row[10]) is not str or type(row[11]) is not str
                       or row[10:]!=('settled',snapshot['completion']) for row in rows)):
            raise ProviderUnavailable()
        actual=tuple(sorted((row[:10] for row in rows),key=lambda row:row[0]))
        if (len(actual)!=len(expected) or any(any(type(a) is not type(b) or a!=b for a,b in zip(row,bound,strict=True))
                for row,bound in zip(actual,expected,strict=True))
                or any(len(row)!=5 or any(type(item) is not str for item in row) for row in members)
                or tuple(sorted(members))!=snapshot['members']):
            raise ProviderUnavailable()

    async def _validate_security_guarded(self, verifier: object, proof: object,
                                         owner_value: object, security_value: object, *, deadline: float,
                                         budget: SecurityReadbackBudget | None = None,
                                         settle: bool = False) -> Mapping[str, Any] | None:
        deadline = deadline_value(deadline)
        owner,security = context(owner_value),context(security_value)
        if (owner.scope != security.scope or (owner.collection,owner.document_id) != (security.collection,security.document_id)
                or owner.intent_id == security.intent_id):
            raise InvalidRequest()
        security_verifier_binding(verifier,self._writer,self.supervisor)
        assert isinstance(verifier,QdrantSecurityVerifier)
        allowance = security_readback_budget(budget)
        if self._closed or self._active is not None or self._guard_scope is not None:
            raise ProviderUnavailable()
        if not self._ready:
            raise IndexNotReady()
        if self._schema_profile != 4:
            raise UnsupportedCapability()
        if self._writer._schema_profile != 4:
            raise UnsupportedCapability()
        scope: dict[str, Any] = dict(task=None,cancelled=False,poisoned=False)
        self._guard_scope = scope

        async def work() -> Mapping[str, Any] | None:
            try:
                async with self._operation(deadline):
                    if scope['cancelled']:
                        raise asyncio.CancelledError()
                    control = self._control()
                    receipt = await verifier.verify(proof,control,owner,security,deadline=deadline,budget=allowance)
                    current_task = asyncio.current_task()
                    if scope['cancelled'] or current_task is None or current_task.cancelling():
                        raise asyncio.CancelledError()
                    received = security_receipt_data(receipt,verifier,control,deadline=deadline)
                    if received['owner_context'] != owner or received['security_context'] != security:
                        raise InvalidRequest()
                    projection = received['projection']
                    data = security_projection_data(projection,self._writer)
                    physical = received['physical_binding']
                    if (self._identity is None or physical['instance_id'] != self._identity['instance_id']
                            or data['context'] != security):
                        raise InvalidRequest()
                    document = MappingProxyType({field:data[field] for field in _DOCUMENT_FIELDS})
                    record: dict[str, Any] = dict(recovery=self,writer=self._writer,supervisor=self.supervisor,
                        resource=self.resource,verifier=verifier,receipt=receipt,receipt_data=received,projection=projection,
                        control=control,scope=scope,deadline=deadline,connection=None,transaction=None,
                        required=False,validated=False,valid=False,poisoned=False,ending=False,
                        metadata=MappingProxyType(dict(context=security,owner_context=owner,document=document)))
                    attempted: dict[str, Any] = {}
                    outcome: Mapping[str, Any] | None = None
                    async def validate(connection: SessionConnection) -> None:
                        nonlocal outcome
                        record['required'] = True
                        arguments = (physical['instance_id'],self.config.backend_namespace,physical['storage_identity'],
                            physical['supervisor_id'],physical['recovery_id'],physical['new_epoch'],owner.scope.tenant_id,
                            owner.collection,owner.document_id,owner.intent_id,owner.owner_token,security.intent_id,
                            data['intent_sha256'],data['active_generation_id'],data['authorization_revision'],
                            data['mutation_epoch'],list(data['principal_ids']),list(data['grant_ids']),data['language'],
                            data['kind'],data['tag'],data['tombstoned'])
                        try:
                            try:
                                rows = await self._query(connection,'SELECT true FROM '+_SECURITY_GUARD_SIGNATURE.split('(')[0]+
                                    '('+','.join(['%s']*22)+')',arguments)
                            except Exception as error:
                                code = getattr(error,'sqlstate',None)
                                if type(code) is str and code in ('42501','23514'):
                                    raise UnauthorizedScope() from None
                                if code == '22023':
                                    raise UnsupportedCapability() from None
                                raise
                            if len(rows) != 1 or len(rows[0]) != 1 or rows[0][0] is not True:
                                raise IntegrityViolation()
                            _guard_boundary(record,deadline=deadline)
                            guard = _SecurityGuard()
                            _GUARDS[guard] = record
                            record['valid'] = True
                            try:
                                await validate_guarded_security_projection(self._writer,guard,projection,deadline=deadline)
                                _guard_boundary(record,deadline=deadline)
                                record['validated'] = True
                            finally:
                                record['valid'] = False
                            if settle:
                                outcome,snapshot=await self._settle_security_rows(connection,owner,physical,data,received['readback_sha256'])
                                attempted.update(snapshot)
                        except BaseException:
                            record['poisoned'] = True
                            raise
                    try:
                        await self._transaction(deadline,validate,guarded=record)
                    except _CommitUnknown:
                        if not settle:
                            raise
                        confirmation=dict(recovery=self,scope=scope,control=control,proof=proof,physical=physical,
                            activity=received['activity'],deadline=deadline,connection=None,transaction=None,ending=False)
                        async def confirm(connection: SessionConnection) -> None:
                            await self._confirm_security_rows(connection,owner,attempted)
                        await self._transaction(deadline,confirm,confirmation=confirmation)
                    return outcome
            finally:
                if self._guard_scope is scope:
                    self._guard_scope = None

        task = asyncio.create_task(work())
        scope['task'] = task
        def finished(done: asyncio.Task[Any]) -> None:
            if self._guard_scope is scope and self._active is not done:
                self._guard_scope = None
            if not done.cancelled():
                done.exception()
        task.add_done_callback(finished)
        try:
            done,_ = await asyncio.wait({task},timeout=max(0,deadline-asyncio.get_running_loop().time()))
            if not done:
                raise TimeoutError()
            return await task
        except (asyncio.CancelledError,TimeoutError) as error:
            scope['cancelled'] = True
            task.cancel()
            try:
                await asyncio.wait({task},timeout=self.resource.config.release_timeout*2)
            except BaseException:
                pass
            if not task.done():
                scope['poisoned'] = True
                self._closed = True
                if self._writer._active is task:
                    self._writer._closed = True
            if isinstance(error,asyncio.CancelledError):
                raise
            raise DeadlineExceeded() from None

    async def _backend(self, connection: SessionConnection) -> Mapping[str, Any]:
        assert self._identity is not None
        instance = self._identity['instance_id']
        await self._query(connection,
            'SELECT instance_id FROM cragkit_qdrant.backend_instances '
            'WHERE instance_id=%s FOR UPDATE', (instance,))
        rows = await self._query(connection, 'SELECT ' + ','.join(_BACKEND_FIELDS) +
            ' FROM cragkit_qdrant.backend_instances WHERE instance_id=%s', (instance,))
        if not rows:
            raise ProviderUnavailable()
        if len(rows) != 1 or len(rows[0]) != len(_BACKEND_FIELDS):
            raise IntegrityViolation()
        row = dict(zip(_BACKEND_FIELDS, rows[0], strict=True))
        expected = (self.config.backend_namespace, self._identity['storage_identity'],
                    self._identity['supervisor_id'])
        if tuple(row[key] for key in _BACKEND_FIELDS[:3]) != expected:
            raise IntegrityViolation()
        if (type(row['epoch']) is not int or not 1 <= row['epoch'] <= 9007199254740991
                or row['state'] not in ('open', 'recovery_blocked')
                or row['recovery_id'] is not None and type(row['recovery_id']) is not str
                or (row['state'] == 'open') != (row['recovery_id'] is None)):
            raise IntegrityViolation()
        return MappingProxyType(row)

    async def _blocked(self, connection: SessionConnection,
                       physical: Mapping[str, Any]) -> Mapping[str, Any]:
        assert self._identity is not None
        backend = await self._backend(connection)
        if (backend['state'], backend['epoch'], backend['recovery_id']) != (
            'recovery_blocked', physical['new_epoch'], physical['recovery_id'],
        ):
            raise ProviderUnavailable()
        if (physical['instance_id'] != self._identity['instance_id']
                or physical['storage_identity'] != backend['storage_identity']
                or physical['supervisor_id'] != backend['supervisor_id']):
            raise IntegrityViolation()
        return backend

    @staticmethod
    def _compatible_local(backend: Mapping[str, Any], local: Mapping[str, Any]) -> None:
        recovery = local['recovery']
        if recovery is None:
            valid = (
                backend['state'] == 'open' and backend['epoch'] == local['epoch']
                or backend['state'] == 'recovery_blocked'
                and backend['epoch'] == local['epoch'] + 1
            )
        else:
            valid = local['epoch'] in (recovery['old_epoch'], recovery['new_epoch']) and (
                backend['state'] == 'recovery_blocked'
                and backend['epoch'] == recovery['new_epoch']
                and backend['recovery_id'] == recovery['recovery_id']
                or backend['state'] == 'open' and backend['epoch'] == recovery['new_epoch']
                and local['sealed'] and local['epoch'] == recovery['new_epoch']
            )
        if not valid:
            raise ProviderUnavailable()

    async def initialize(self, *, deadline: float) -> None:
        if self._closed or self._active is not None:
            raise ProviderUnavailable()
        deadline_value(deadline)
        self._ready = False
        async with self._operation(deadline, initialize=True):
            local = dict(self.supervisor.control_binding())
            if local['backend_namespace'] != self.config.backend_namespace:
                raise UnsupportedCapability()
            self._identity = MappingProxyType({key: local[key] for key in
                ('instance_id', 'storage_identity', 'supervisor_id')})
            async def install(connection: SessionConnection) -> bool:
                rows = await self._query(connection,
                    'SELECT instance_id FROM cragkit_qdrant.backend_instances WHERE instance_id=%s',
                    (local['instance_id'],))
                if not rows:
                    if (local['epoch'] != 1 or local['recovery'] is not None
                            or local['sealed'] or not local['alive']):
                        raise ProviderUnavailable()
                    await connection.execute(
                        'INSERT INTO cragkit_qdrant.backend_instances '
                        '(instance_id,backend_namespace,storage_identity,supervisor_id) '
                        'VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING',
                        (local['instance_id'], self.config.backend_namespace,
                         local['storage_identity'], local['supervisor_id']))
                backend = await self._backend(connection)
                self._compatible_local(backend, local)
                return bool(backend['state'] == 'recovery_blocked')
            try:
                blocked = await self._transaction(deadline, install, initializing=True)
            except _CommitUnknown:
                # The same exact registration is safe to inspect; no second INSERT.
                async def confirm(connection: SessionConnection) -> bool:
                    backend = await self._backend(connection)
                    self._compatible_local(backend, local)
                    return bool(backend['state'] == 'recovery_blocked')
                blocked = await self._transaction(deadline, confirm)
            if blocked:
                self._control().block_ordinary()
            self._security_guard_admitted = self._security_guard_admitted or self._schema_profile in (4, 5)
            self._ready = True

    async def recover(self, recovery_id: object, *, deadline: float) -> object:
        identity = _parse(_RecoveryId, {'recovery_id': recovery_id}).recovery_id
        async with self._operation(deadline):
            local = dict(self.supervisor.control_binding())
            recovery = local['recovery']
            if recovery is not None and recovery['recovery_id'] != identity:
                raise ProviderUnavailable()
            self._control().block_ordinary()
            desired: dict[str, Any] = {}
            async def block(connection: SessionConnection) -> Mapping[str, Any]:
                backend = await self._backend(connection)
                if backend['state'] == 'open':
                    if recovery is not None or backend['epoch'] != local['epoch']:
                        raise ProviderUnavailable()
                    if backend['epoch'] == 9007199254740991:
                        raise InvalidRequest()
                    desired.update(recovery_id=identity, old_epoch=backend['epoch'],
                                   new_epoch=backend['epoch'] + 1)
                    await connection.execute(
                        "UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',"
                        'epoch=%s,recovery_id=%s WHERE instance_id=%s',
                        (desired['new_epoch'], identity, local['instance_id']))
                else:
                    if backend['recovery_id'] != identity:
                        raise ProviderUnavailable()
                    desired.update(recovery_id=identity, old_epoch=backend['epoch'] - 1,
                                   new_epoch=backend['epoch'])
                    if local['epoch'] not in (desired['old_epoch'], desired['new_epoch']):
                        raise ProviderUnavailable()
                    if recovery is None and local['epoch'] != desired['old_epoch']:
                        raise ProviderUnavailable()
                    if recovery is not None and (recovery['old_epoch'], recovery['new_epoch']) != (
                            desired['old_epoch'], desired['new_epoch']):
                        raise ProviderUnavailable()
                return MappingProxyType(dict(desired))
            async def confirm(connection: SessionConnection) -> Mapping[str, Any]:
                backend = await self._backend(connection)
                if (not desired or backend['state'] != 'recovery_blocked'
                        or backend['epoch'] != desired['new_epoch']
                        or backend['recovery_id'] != identity):
                    raise ProviderUnavailable()
                return MappingProxyType(dict(desired))
            try:
                request = await self._transaction(deadline, block)
            except _CommitUnknown:
                request = await self._transaction(deadline, confirm)
            # No SQL lease remains while native stop/rotation/HTTP executes.
            proof = await self._control().recover(dict(request), deadline=deadline)
            actual = self.supervisor.recovery_binding(proof)
            expected = {**dict(request), **{key: local[key] for key in
                ('instance_id', 'storage_identity', 'supervisor_id')}}
            if any(actual[key] != value for key, value in expected.items()):
                raise IntegrityViolation()
            return proof

    async def _owner(self, connection: SessionConnection,
                     target: WriterContext) -> tuple[Any, ...]:
        assert self._identity is not None
        rows = await self._query(connection,
            'SELECT instance_id,intent_id,owner_token::text,backend_epoch '
            'FROM cragkit_qdrant.document_owners WHERE ' + _DOC + ' FOR UPDATE', _target(target))
        if len(rows) != 1 or len(rows[0]) != 4:
            raise ProviderUnavailable()
        if rows[0][:3] != (self._identity['instance_id'], target.intent_id, target.owner_token):
            raise ProviderUnavailable()
        return rows[0]

    async def advance_owner(self, proof: object, value: object, *,
                            deadline: float) -> Mapping[str, Any]:
        target = context(value)
        async with self._operation(deadline):
            physical = physical_binding(dict(self.supervisor.recovery_binding(proof)))
            async def advance(connection: SessionConnection) -> Mapping[str, Any]:
                await self._blocked(connection, physical)
                owner = await self._owner(connection, target)
                if type(owner[3]) is not int or not 1 <= owner[3] <= physical['new_epoch']:
                    raise ProviderUnavailable()
                if owner[3] != physical['new_epoch']:
                    await connection.execute(
                        'UPDATE cragkit_qdrant.document_owners SET backend_epoch=%s WHERE ' + _DOC,
                        (physical['new_epoch'], *_target(target)))
                return MappingProxyType({'owner_token': target.owner_token,
                    'backend_epoch': physical['new_epoch']})
            try:
                return await self._transaction(deadline, advance)
            except _CommitUnknown:
                async def confirm(connection: SessionConnection) -> Mapping[str, Any]:
                    await self._blocked(connection, physical)
                    owner = await self._owner(connection, target)
                    if owner[3] != physical['new_epoch']:
                        raise ProviderUnavailable()
                    return MappingProxyType({'owner_token': target.owner_token,
                        'backend_epoch': physical['new_epoch']})
                return await self._transaction(deadline, confirm)

    async def settle_retired(self, proof: object, receipt: object, *,
                             deadline: float) -> Mapping[str, Any]:
        async with self._operation(deadline):
            physical = physical_binding(dict(self.supervisor.recovery_binding(proof)))
            data = receipt_data(receipt, self.verifier)
            if dict(data['physical_binding']) != dict(physical):
                raise UnsupportedCapability()
            await self._writer.validate_projection(data['projection'], deadline=deadline)
            if dict(self.supervisor.recovery_binding(proof)) != dict(physical):
                raise UnsupportedCapability()
            target = data['context']
            settled: list[str] = []
            async def settle(connection: SessionConnection) -> Mapping[str, Any]:
                await self._blocked(connection, physical)
                owner = await self._owner(connection, target)
                if owner[3] != physical['new_epoch']:
                    raise ProviderUnavailable()
                intent = await self._query(connection,
                    'SELECT action,manifest_sha256,revision_id,generation_id '
                    'FROM cragkit_qdrant.publication_intents WHERE ' + _INTENT, _intent(target))
                if len(intent) != 1 or len(intent[0]) != 4:
                    raise IntegrityViolation()
                if intent[0][0] != 'stage':
                    raise UnsupportedCapability()
                if intent[0][1:] != (data['manifest_sha256'], data['revision_id'], data['generation_id']):
                    raise IntegrityViolation()
                journals = await self._query(connection,
                    'SELECT dispatch_id,credential_generation,operation,owner_token::text,backend_epoch,instance_id '
                    'FROM cragkit_qdrant.dispatch_journal WHERE ' + _INTENT +
                    " AND state<>'settled' ORDER BY sequence LIMIT 257 FOR UPDATE", _intent(target))
                if len(journals) > 256:
                    raise IntegrityViolation()
                for row in journals:
                    if len(row) != 6 or type(row[0]) is not str or type(row[1]) is not str:
                        raise IntegrityViolation()
                    if row[1] == physical['credential_generation']:
                        raise ProviderUnavailable()
                    if row[2] != 'complete_point_upsert':
                        raise UnsupportedCapability()
                    if (row[3] != target.owner_token or type(row[4]) is not int
                            or not 1 <= row[4] <= physical['new_epoch']
                            or row[5] != physical['instance_id']):
                        raise IntegrityViolation()
                identifiers = [row[0] for row in journals]
                if len(set(identifiers)) != len(identifiers):
                    raise IntegrityViolation()
                if not identifiers:
                    return MappingProxyType({'settled_count': 0})
                points = await self._query(connection,
                    'SELECT dispatch_id,point_id::text,backend_namespace,physical_collection,collection_incarnation '
                    'FROM cragkit_qdrant.dispatch_points WHERE ' + _INTENT +
                    ' AND dispatch_id=ANY(%s::text[]) LIMIT 2049', (*_intent(target), identifiers))
                if len(points) > 2048:
                    raise IntegrityViolation()
                grouped: dict[str, set[str]] = {identity: set() for identity in identifiers}
                for row in points:
                    if (len(row) != 5 or any(type(value) is not str for value in row)
                            or row[0] not in grouped
                            or row[1] not in data['point_ids'] or row[1] in grouped[row[0]]
                            or row[2:] != (self.config.backend_namespace,
                                self.config.physical_collection, self.config.collection_incarnation)):
                        raise IntegrityViolation()
                    grouped[row[0]].add(row[1])
                if any(not 1 <= len(group) <= 8 for group in grouped.values()):
                    raise IntegrityViolation()
                for identity in identifiers:
                    changed = await self._query(connection,
                        "UPDATE cragkit_qdrant.dispatch_journal SET state='settled',completion_sha256=%s WHERE " +
                        _INTENT + " AND dispatch_id=%s AND state<>'settled' RETURNING dispatch_id",
                        (data['readback_sha256'], *_intent(target), identity))
                    if changed != [(identity,)]:
                        raise IntegrityViolation()
                    settled.append(identity)
                return MappingProxyType({'settled_count': len(settled)})
            try:
                return await self._transaction(deadline, settle)
            except _CommitUnknown:
                async def confirm(connection: SessionConnection) -> Mapping[str, Any]:
                    await self._blocked(connection, physical)
                    rows = await self._query(connection,
                        'SELECT dispatch_id,state,completion_sha256 FROM cragkit_qdrant.dispatch_journal WHERE ' +
                        _INTENT + ' AND dispatch_id=ANY(%s::text[]) LIMIT 257', (*_intent(target), settled))
                    if (len(rows) != len(settled) or {row[0] for row in rows} != set(settled)
                            or any(row[1:] != ('settled', data['readback_sha256']) for row in rows)):
                        raise ProviderUnavailable()
                    return MappingProxyType({'settled_count': len(settled)})
                return await self._transaction(deadline, confirm)

    async def dispatch_stage_recovery(self, proof: object, value: object, authorize: object, *,
                                      deadline: float, budget: VerificationBudget | None = None) -> Mapping[str, Any]:
        from ._qdrant_contract import decode_response
        target = context(value)
        allowance = verification_budget(budget)
        self._writer._attestation_profile()
        if not callable(authorize):
            raise InvalidRequest()
        callback = cast(Callable[..., Awaitable[object]], authorize)
        async with self._operation(deadline):
            physical = physical_binding(dict(self.supervisor.recovery_binding(proof)))
            allowed=await callback(target.scope,target.collection,target.document_id)
            _dispatch_check(deadline)
            if type(allowed) is not bool:
                raise InvalidRequest()
            if not allowed:
                raise UnauthorizedScope()
            projection = await self._writer.project_stage(target,dict(physical),deadline=deadline)
            _dispatch_check(deadline)
            source = projection_data(projection,self._writer)
            if source['tombstoned']:
                raise UnsupportedCapability()
            ids = tuple(source['point_ids'])
            if not 1 <= len(ids) <= 64 or len(set(ids)) != len(ids):
                raise IntegrityViolation()
            active: list[_RecoveryDispatchAuthorization] = []

            async def permitted() -> None:
                _dispatch_check(deadline)
                allowed = await callback(target.scope,target.collection,target.document_id)
                _dispatch_check(deadline)
                if type(allowed) is not bool:
                    raise InvalidRequest()
                if not allowed:
                    raise UnauthorizedScope()

            async def fences(connection: SessionConnection, plan: Mapping[str, Any] | None = None) -> tuple[Any, ...]:
                await self._blocked(connection,physical)
                owner = await self._owner(connection,target)
                if owner[3] != physical['new_epoch']:
                    raise ProviderUnavailable()
                rows = await self._query(connection,
                    'SELECT action,state,manifest_sha256,revision_id,generation_id,expected_authorization_revision,'
                    'expected_mutation_epoch,expected_active_generation_id,instance_id '
                    'FROM cragkit_qdrant.publication_intents WHERE '+_INTENT,_intent(target))
                if len(rows) != 1 or len(rows[0]) != 9:
                    raise IntegrityViolation()
                row = rows[0]
                if row[0] != 'stage' or row[1] not in ('writing','prepared'):
                    raise UnsupportedCapability()
                wanted = (source['manifest_sha256'],source['revision_id'],source['generation_id'],
                    source['authorization_revision'],source['mutation_epoch'],source['active_generation_id'],physical['instance_id'])
                if row[2:] != wanted:
                    raise IntegrityViolation()
                if plan is not None and tuple(plan[key] for key in ('manifest_sha256','revision_id','generation_id',
                        'expected_authorization_revision','expected_mutation_epoch','expected_active_generation_id')) != row[2:8]:
                    raise IntegrityViolation()
                return row

            async def preflight(connection: SessionConnection) -> tuple[int,str]:
                row = await fences(connection)
                foreign=await self._query(connection,'SELECT 1 FROM cragkit_qdrant.dispatch_journal WHERE '+_DOC+
                    " AND intent_id<>%s AND state<>'settled' LIMIT 1",_intent(target))
                if foreign:
                    raise ProviderUnavailable()
                journals = await self._query(connection,
                    'SELECT dispatch_id,instance_id,sequence,owner_token::text,backend_epoch,credential_generation,operation,recovery,state,completion_sha256,request_sha256 '
                    'FROM cragkit_qdrant.dispatch_journal WHERE '+_INTENT+' ORDER BY sequence LIMIT 257',_intent(target))
                memberships = await self._query(connection,
                    'SELECT dispatch_id,backend_namespace,physical_collection,collection_incarnation,point_id::text FROM cragkit_qdrant.dispatch_points WHERE '+_INTENT+' LIMIT 2049',_intent(target))
                if len(journals)>256 or len(memberships)>2048:
                    raise IntegrityViolation()
                sequences:set[int]=set();names:set[str]=set()
                for journal in journals:
                    if (len(journal)!=11 or type(journal[0]) is not str or type(journal[2]) is not int
                            or not 1<=journal[2]<=256 or journal[2] in sequences or journal[0] in names
                            or type(journal[5]) is not str or journal[8] not in ('reserved','dispatched','unknown','settled')
                            or journal[3]!=target.owner_token or type(journal[4]) is not int
                            or not 1<=journal[4]<=physical['new_epoch'] or journal[1]!=physical['instance_id']
                            or journal[6]!='complete_point_upsert' or type(journal[7]) is not bool
                            or type(journal[10]) is not str or len(journal[10])!=64
                            or any(character not in '0123456789abcdef' for character in journal[10])
                            or (journal[8]=='settled') != (journal[9] is not None)):
                        raise IntegrityViolation()
                    if journal[8]=='settled' and (type(journal[9]) is not str or len(journal[9])!=64
                            or any(character not in '0123456789abcdef' for character in journal[9])):
                        raise IntegrityViolation()
                    if journal[8]!='settled' and journal[5]==physical['credential_generation']:
                        raise ProviderUnavailable()
                    sequences.add(journal[2]);names.add(journal[0])
                grouped:dict[str,set[str]]={name:set() for name in names}
                for membership in memberships:
                    if (len(membership)!=5 or membership[0] not in grouped or type(membership[4]) is not str
                            or membership[4] not in ids or membership[4] in grouped[membership[0]]
                            or membership[1:4]!=(self.config.backend_namespace,self.config.physical_collection,self.config.collection_incarnation)):
                        raise IntegrityViolation()
                    grouped[membership[0]].add(membership[4])
                if any(not 1<=len(group)<=8 for group in grouped.values()):
                    raise IntegrityViolation()
                claims = await self._query(connection,
                    'SELECT point_id::text FROM cragkit_qdrant.point_claims WHERE '+_DOC+
                    ' AND revision_id=%s AND generation_id=%s AND instance_id=%s '
                    'AND backend_namespace=%s AND physical_collection=%s AND collection_incarnation=%s LIMIT 65',
                    (*_target(target),source['revision_id'],source['generation_id'],physical['instance_id'],
                     self.config.backend_namespace,self.config.physical_collection,self.config.collection_incarnation))
                if (len(claims)!=len(ids) or any(len(item)!=1 for item in claims)
                        or {item[0] for item in claims}!=set(ids)):
                    raise IntegrityViolation()
                return max(sequences,default=0),row[1]

            def issue(number: int, identity: str) -> tuple[object,_RecoveryDispatchAuthorization]:
                binding=dict(intent_id=target.intent_id,owner_token=target.owner_token,epoch=physical['new_epoch'],
                    dispatch_id=identity,recovery_id=physical['recovery_id'])
                attempt=self._control().issue_recovery_attempt(proof,binding,deadline=deadline)
                actual=MappingProxyType(dict(self.supervisor.attempt_binding(attempt)))
                token=_RecoveryDispatchAuthorization()
                _DISPATCH_AUTHORIZATIONS[token]=dict(owner=self,task=asyncio.current_task(),proof=proof,attempt=attempt,
                    control=self._control(),deadline=deadline,active=True,data=MappingProxyType(dict(
                        context=target,physical_binding=physical,attempt_binding=actual,sequence=number)))
                active.append(token)
                return attempt,token

            async def commit(action: Callable[[SessionConnection], Awaitable[Any]],
                             confirm: Callable[[SessionConnection], Awaitable[Any]],
                             before_retry: Callable[[], Awaitable[None]]) -> Any:
                try:
                    result=await self._transaction(deadline,action)
                except _CommitUnknown:
                    _dispatch_check(deadline)
                    result=await self._transaction(deadline,confirm)
                    if result is None:
                        await before_retry()
                        _dispatch_check(deadline)
                        try:result=await self._transaction(deadline,action)
                        except _CommitUnknown:
                            result=await self._transaction(deadline,confirm)
                            if result is None:raise ProviderUnavailable() from None
                _dispatch_check(deadline)
                return result

            try:
                maximum,state=await self._transaction(deadline,preflight)
                _dispatch_check(deadline)
                inspect_id='g1b-inspect-'+hashlib.sha256(json.dumps([physical['recovery_id'],target.intent_id,target.owner_token],separators=(',',':')).encode()).hexdigest()
                attempt,inspection=issue(min(maximum+1,256),inspect_id)
                await self._writer.project_recovery_dispatch(inspection,target,ids[:8],deadline=deadline)
                _dispatch_check(deadline)
                handle=self._control().recovery_transport_for(attempt)
                try:
                    missing=await inspect_missing_readback(_Readback(handle,deadline,allowance),
                        '/collections/'+self.config.physical_collection+'/points',source)
                    _dispatch_check(deadline)
                finally:
                    await handle.close()
                _dispatch_check(deadline)
                if not missing:
                    return MappingProxyType(dict(batches=0,points=0))
                batches=(len(missing)+7)//8
                ordinary=0 if state=='prepared' else (len(ids)+7)//8
                if maximum+batches+ordinary>256:
                    raise ProviderUnavailable()
                for index in range(batches):
                    if allowance.remaining_bytes<=0:
                        raise ProviderUnavailable()
                    selected=tuple(missing[index*8:index*8+8]);number=maximum+index+1
                    identity='g1b-'+hashlib.sha256(json.dumps([physical['instance_id'],physical['recovery_id'],
                        str(physical['new_epoch']),physical['credential_generation'],target.intent_id,target.owner_token,str(number),selected],
                        separators=(',',':')).encode()).hexdigest()
                    attempt,authorization=issue(number,identity)
                    plan=await self._writer.project_recovery_dispatch(authorization,target,selected,deadline=deadline)
                    _dispatch_check(deadline)
                    data=recovery_dispatch_plan_data(plan,authorization,self._writer,deadline=deadline)
                    async def fresh() -> None:
                        await permitted()
                        await self._writer.validate_recovery_dispatch(plan,authorization,deadline=deadline)
                        _dispatch_check(deadline)
                    async def exact(connection: SessionConnection) -> str | None:
                        await fences(connection,data)
                        rows=await self._query(connection,
                            'SELECT sequence,owner_token::text,backend_epoch,credential_generation,operation,recovery,request_sha256,state,completion_sha256,instance_id '
                            'FROM cragkit_qdrant.dispatch_journal WHERE '+_INTENT+' AND dispatch_id=%s',(*_intent(target),identity))
                        if not rows:return None
                        expected=(number,target.owner_token,physical['new_epoch'],physical['credential_generation'],
                            'complete_point_upsert',True,data['request_sha256'])
                        if (len(rows)!=1 or len(rows[0])!=10 or rows[0][:7]!=expected or rows[0][9]!=physical['instance_id']
                                or rows[0][7] not in ('reserved','dispatched','unknown','settled')
                                or (rows[0][7]=='settled') != (rows[0][8] is not None)):
                            raise IntegrityViolation()
                        members=await self._query(connection,
                            'SELECT point_id::text,backend_namespace,physical_collection,collection_incarnation '
                            'FROM cragkit_qdrant.dispatch_points WHERE '+_INTENT+' AND dispatch_id=%s ORDER BY point_id::text LIMIT 9',(*_intent(target),identity))
                        if members!=[(point,self.config.backend_namespace,self.config.physical_collection,self.config.collection_incarnation) for point in selected]:
                            raise IntegrityViolation()
                        return cast(str,rows[0][7])
                    async def reserve(connection: SessionConnection) -> str:
                        await fences(connection,data)
                        if await exact(connection) is not None:
                            raise IntegrityViolation()
                        claims=await self._query(connection,'SELECT point_id::text FROM cragkit_qdrant.point_claims WHERE '+_DOC+
                            ' AND point_id=ANY(%s::uuid[]) AND revision_id=%s AND generation_id=%s AND instance_id=%s '
                            'AND backend_namespace=%s AND physical_collection=%s AND collection_incarnation=%s ORDER BY point_id::text LIMIT 9',
                            (*_target(target),list(selected),data['revision_id'],data['generation_id'],physical['instance_id'],
                             self.config.backend_namespace,self.config.physical_collection,self.config.collection_incarnation))
                        if claims!=[(point,) for point in selected]:raise IntegrityViolation()
                        await connection.execute('INSERT INTO cragkit_qdrant.dispatch_journal '
                            '(tenant_id,collection,document_id,intent_id,dispatch_id,instance_id,sequence,owner_token,backend_epoch,credential_generation,operation,recovery,request_bytes,request_sha256) '
                            'VALUES ('+','.join('%s' for _ in range(14))+')',(*_intent(target),identity,physical['instance_id'],number,target.owner_token,
                             physical['new_epoch'],physical['credential_generation'],'complete_point_upsert',True,data['request_bytes'],data['request_sha256']))
                        for point in selected:
                            await connection.execute('INSERT INTO cragkit_qdrant.dispatch_points '
                                '(tenant_id,collection,document_id,intent_id,dispatch_id,backend_namespace,physical_collection,collection_incarnation,point_id) '
                                'VALUES ('+','.join('%s' for _ in range(9))+')',(*_intent(target),identity,self.config.backend_namespace,
                                 self.config.physical_collection,self.config.collection_incarnation,point))
                        return 'reserved'
                    await permitted()
                    await self._writer.validate_recovery_dispatch(plan,authorization,deadline=deadline);_dispatch_check(deadline)
                    if await commit(reserve,exact,fresh)!='reserved':raise ProviderUnavailable()
                    async def mark(connection: SessionConnection, desired: str, completion: str | None) -> str:
                        current=await exact(connection)
                        needed='reserved' if desired=='dispatched' else 'dispatched'
                        if current!=needed:raise ProviderUnavailable()
                        await connection.execute('UPDATE cragkit_qdrant.dispatch_journal SET state=%s,completion_sha256=%s WHERE '+_INTENT+' AND dispatch_id=%s',
                            (desired,completion,*_intent(target),identity))
                        return desired
                    async def confirm_dispatched(connection: SessionConnection) -> str | None:
                        current=await exact(connection)
                        if current=='dispatched':return current
                        if current=='reserved':return None
                        raise ProviderUnavailable()
                    await permitted()
                    await self._writer.validate_recovery_dispatch(plan,authorization,deadline=deadline);_dispatch_check(deadline)
                    await commit(lambda connection:mark(connection,'dispatched',None),confirm_dispatched,fresh)
                    await permitted()
                    await self._writer.validate_recovery_dispatch(plan,authorization,deadline=deadline);_dispatch_check(deadline)
                    recovery_dispatch_authorization(authorization,self._writer,deadline=deadline)
                    handle=self._control().recovery_transport_for(attempt)
                    try:
                        raw=await handle.request('PUT','/collections/'+self.config.physical_collection+'/points?wait=true&ordering=strong',
                            body=data['request_bytes'],deadline=deadline,max_response_bytes=1048576)
                        _dispatch_check(deadline)
                        response=decode_response(raw)
                        if (type(response) is not dict or response.get('status')!='ok'
                                or type(response.get('result')) is not dict or response['result'].get('status')!='completed'
                                or set(response['result'])-{'status','operation_id'}):
                            raise IntegrityViolation()
                        operation_id=response['result'].get('operation_id')
                        if 'operation_id' in response['result'] and (type(operation_id) not in (int,float)
                                or not 0<=operation_id<=9007199254740991 or int(operation_id)!=operation_id):
                            raise IntegrityViolation()
                        completion=hashlib.sha256(raw).hexdigest()
                    finally:await handle.close()
                    _dispatch_check(deadline)
                    await permitted()
                    await self._writer.validate_recovery_dispatch(plan,authorization,deadline=deadline);_dispatch_check(deadline)
                    async def confirm_settled(connection: SessionConnection) -> str | None:
                        current=await exact(connection)
                        if current=='dispatched':return None
                        if current!='settled':raise ProviderUnavailable()
                        rows=await self._query(connection,'SELECT completion_sha256 FROM cragkit_qdrant.dispatch_journal WHERE '+_INTENT+' AND dispatch_id=%s',(*_intent(target),identity))
                        if rows!=[(completion,)]:raise IntegrityViolation()
                        return current
                    await commit(lambda connection:mark(connection,'settled',completion),confirm_settled,fresh)
                return MappingProxyType(dict(batches=batches,points=len(missing)))
            finally:
                for token in active:
                    _DISPATCH_AUTHORIZATIONS[token]['active']=False

    async def _dispatch_security_owned(self, proof: object, owner_value: object, security_value: object,
                                       authorize: object, *, deadline: float,
                                       budget: SecurityReadbackBudget | None=None) -> Mapping[str, Any]:
        deadline=deadline_value(deadline);owner,current=context(owner_value),context(security_value)
        allowance=security_readback_budget(budget)
        if (owner.scope!=current.scope or (owner.collection,owner.document_id)!=(current.collection,current.document_id)
                or owner.intent_id==current.intent_id or not callable(authorize)):
            raise InvalidRequest()
        if self._closed or self._active is not None or self._guard_scope is not None:
            raise ProviderUnavailable()
        if not self._ready:raise IndexNotReady()
        if self._schema_profile!=4 or self._writer._schema_profile!=4:raise UnsupportedCapability()
        scope: dict[str, Any]=dict(task=None,cancelled=False,poisoned=False)
        self._guard_scope=scope
        async def work() -> Mapping[str, Any]:
            try:return await self._dispatch_security_work(proof,owner,current,authorize,scope,deadline=deadline,budget=allowance)
            finally:
                if self._guard_scope is scope:self._guard_scope=None
        task=asyncio.create_task(work());scope['task']=task
        def finished(done: asyncio.Task[Any]) -> None:
            if self._guard_scope is scope and self._active is not done:self._guard_scope=None
            if not done.cancelled():done.exception()
        task.add_done_callback(finished)
        try:
            done,_=await asyncio.wait({task},timeout=max(0,deadline-asyncio.get_running_loop().time()))
            if not done:raise TimeoutError()
            return await task
        except (asyncio.CancelledError,TimeoutError) as error:
            scope['cancelled']=True;task.cancel()
            try:await asyncio.wait({task},timeout=self.resource.config.release_timeout*2)
            except BaseException:pass
            if not task.done():
                scope['poisoned']=True;self._closed=True
                if self._writer._active is task:self._writer._closed=True
            if isinstance(error,asyncio.CancelledError):raise
            raise DeadlineExceeded() from None

    async def _dispatch_security_work(self, proof: object, owner_value: object, security_value: object,
                                      authorize: object, scope: dict[str, Any], *, deadline: float,
                                      budget: SecurityReadbackBudget) -> Mapping[str, Any]:
        from ._qdrant_contract import decode_response
        from ._qdrant_security_readback import inspect_security_readback, security_storage_request
        target,current=context(owner_value),context(security_value)
        allowance=budget
        if not callable(authorize):raise InvalidRequest()
        callback = cast(Callable[..., Awaitable[object]], authorize)
        async with self._operation(deadline):
            physical = physical_binding(dict(self.supervisor.recovery_binding(proof)))
            async def transaction(action: Callable[[SessionConnection], Awaitable[Any]]) -> Any:
                _dispatch_check(deadline)
                if scope['cancelled'] or scope['poisoned'] or self._closed:raise ProviderUnavailable()
                bound=control_session_binding(self._control(),self.supervisor,proof)
                custody=dict(recovery=self,scope=scope,control=self._control(),proof=proof,physical=physical,
                    activity=bound['activity'],deadline=deadline,connection=None,transaction=None,ending=False,read_only=False)
                return await self._transaction(deadline,action,confirmation=custody)
            allowed=await callback(target.scope,target.collection,target.document_id)
            _dispatch_check(deadline)
            if type(allowed) is not bool:
                raise InvalidRequest()
            if not allowed:
                raise UnauthorizedScope()
            projection = await security_recovery_projection(self._writer,current,deadline=deadline)
            _dispatch_check(deadline)
            source = security_projection_data(projection,self._writer)
            if source['tombstoned']:
                raise UnsupportedCapability()
            ids = tuple(source['point_ids'])
            if len(ids)>2048 or len(set(ids)) != len(ids):
                raise IntegrityViolation()
            active: list[_SecurityDispatchAuthorization] = []

            async def permitted() -> None:
                _dispatch_check(deadline)
                allowed = await callback(target.scope,target.collection,target.document_id)
                _dispatch_check(deadline)
                if type(allowed) is not bool:
                    raise InvalidRequest()
                if not allowed:
                    raise UnauthorizedScope()

            async def fences(connection: SessionConnection, plan: Mapping[str, Any] | None = None) -> tuple[Any, ...]:
                await self._blocked(connection,physical)
                owner = await self._owner(connection,target)
                if owner[3] != physical['new_epoch']:
                    raise ProviderUnavailable()
                rows = await self._query(connection,
                    'SELECT action,state,manifest_sha256,revision_id,generation_id,expected_authorization_revision,'
                    'expected_mutation_epoch,expected_active_generation_id,instance_id '
                    'FROM cragkit_qdrant.publication_intents WHERE '+_INTENT,_intent(target))
                if len(rows) != 1 or len(rows[0]) != 9:
                    raise IntegrityViolation()
                row = rows[0]
                if row[0] != 'stage':
                    raise UnsupportedCapability()
                if row[8]!=physical['instance_id'] or not any((group['manifest_sha256'],group['revision_id'],group['generation_id'])==row[2:5] for group in source['generations']):
                    raise IntegrityViolation()
                if plan is not None and (plan['manifest_sha256'],plan['revision_id'],plan['generation_id'])!=row[2:5]:
                    raise IntegrityViolation()
                security_rows=await self._query(connection,'SELECT action,payload_sha256,authority_committed,instance_id FROM cragkit_qdrant.publication_intents WHERE '+_INTENT,_intent(current))
                if security_rows!=[('update_authorization',source['intent_sha256'],True,physical['instance_id'])]:
                    raise UnauthorizedScope()
                if plan is not None:
                    foreign=await self._query(connection,'SELECT 1 FROM cragkit_qdrant.dispatch_journal WHERE '+_DOC+
                        " AND intent_id<>%s AND state<>'settled' LIMIT 1",_intent(target))
                    pending=await self._query(connection,'SELECT dispatch_id FROM cragkit_qdrant.dispatch_journal WHERE '+_INTENT+
                        " AND credential_generation=%s AND dispatch_id<>%s AND state<>'settled' LIMIT 1",
                        (*_intent(target),physical['credential_generation'],plan['attempt_binding']['dispatch_id']))
                    if foreign or pending:raise ProviderUnavailable()
                return row

            async def preflight(connection: SessionConnection) -> tuple[int,str]:
                row = await fences(connection)
                foreign=await self._query(connection,'SELECT 1 FROM cragkit_qdrant.dispatch_journal WHERE '+_DOC+
                    " AND intent_id<>%s AND state<>'settled' LIMIT 1",_intent(target))
                if foreign:
                    raise ProviderUnavailable()
                journals = await self._query(connection,
                    'SELECT dispatch_id,instance_id,sequence,owner_token::text,backend_epoch,credential_generation,operation,recovery,state,completion_sha256,request_sha256 '
                    'FROM cragkit_qdrant.dispatch_journal WHERE '+_INTENT+' ORDER BY sequence LIMIT 257',_intent(target))
                memberships = await self._query(connection,
                    'SELECT dispatch_id,backend_namespace,physical_collection,collection_incarnation,point_id::text FROM cragkit_qdrant.dispatch_points WHERE '+_INTENT+' LIMIT 2049',_intent(target))
                if len(journals)>256 or len(memberships)>2048:
                    raise IntegrityViolation()
                sequences:set[int]=set();names:set[str]=set()
                for journal in journals:
                    if (len(journal)!=11 or type(journal[0]) is not str or type(journal[2]) is not int
                            or not 1<=journal[2]<=256 or journal[2] in sequences or journal[0] in names
                            or type(journal[5]) is not str or journal[8] not in ('reserved','dispatched','unknown','settled')
                            or journal[3]!=target.owner_token or type(journal[4]) is not int
                            or not 1<=journal[4]<=physical['new_epoch'] or journal[1]!=physical['instance_id']
                            or journal[6]!='complete_point_upsert' or type(journal[7]) is not bool
                            or type(journal[10]) is not str or len(journal[10])!=64
                            or any(character not in '0123456789abcdef' for character in journal[10])
                            or (journal[8]=='settled') != (journal[9] is not None)):
                        raise IntegrityViolation()
                    if journal[8]=='settled' and (type(journal[9]) is not str or len(journal[9])!=64
                            or any(character not in '0123456789abcdef' for character in journal[9])):
                        raise IntegrityViolation()
                    if journal[8]!='settled' and journal[5]==physical['credential_generation']:
                        raise ProviderUnavailable()
                    sequences.add(journal[2]);names.add(journal[0])
                grouped:dict[str,set[str]]={name:set() for name in names}
                journal_by_name={item[0]:item for item in journals}
                stage_ids=next(group['point_ids'] for group in source['generations'] if (group['manifest_sha256'],group['revision_id'],group['generation_id'])==row[2:5])
                for membership in memberships:
                    if (len(membership)!=5 or membership[0] not in grouped or type(membership[4]) is not str
                            or membership[4] not in ids or membership[4] in grouped[membership[0]]
                            or (not journal_by_name[membership[0]][7] and membership[4] not in stage_ids)
                            or membership[1:4]!=(self.config.backend_namespace,self.config.physical_collection,self.config.collection_incarnation)):
                        raise IntegrityViolation()
                    grouped[membership[0]].add(membership[4])
                if any(not 1<=len(group)<=8 for group in grouped.values()):
                    raise IntegrityViolation()
                claims = await self._query(connection,
                    'SELECT point_id::text FROM cragkit_qdrant.point_claims WHERE '+_DOC+
                    ' AND instance_id=%s '
                    'AND backend_namespace=%s AND physical_collection=%s AND collection_incarnation=%s LIMIT 2049',
                    (*_target(target),physical['instance_id'],
                     self.config.backend_namespace,self.config.physical_collection,self.config.collection_incarnation))
                if (len(claims)!=len(ids) or any(len(item)!=1 for item in claims)
                        or {item[0] for item in claims}!=set(ids)):
                    raise IntegrityViolation()
                return max(sequences,default=0),row[1]

            def issue(number: int, identity: str) -> tuple[object,_SecurityDispatchAuthorization]:
                binding=dict(intent_id=target.intent_id,owner_token=target.owner_token,epoch=physical['new_epoch'],
                    dispatch_id=identity,recovery_id=physical['recovery_id'])
                attempt=self._control().issue_recovery_attempt(proof,binding,deadline=deadline)
                actual=MappingProxyType(dict(self.supervisor.attempt_binding(attempt)))
                token=_SecurityDispatchAuthorization()
                _SECURITY_DISPATCH_AUTHORIZATIONS[token]=dict(owner=self,task=asyncio.current_task(),proof=proof,attempt=attempt,
                    control=self._control(),deadline=deadline,active=True,scope=scope,data=MappingProxyType(dict(
                        context=target,security_context=current,projection=projection,physical_binding=physical,attempt_binding=actual,sequence=number)))
                active.append(token)
                return attempt,token

            async def commit(action: Callable[[SessionConnection], Awaitable[Any]],
                             confirm: Callable[[SessionConnection], Awaitable[Any]],
                             before_retry: Callable[[], Awaitable[None]]) -> Any:
                try:
                    result=await transaction(action)
                except _CommitUnknown:
                    _dispatch_check(deadline)
                    result=await transaction(confirm)
                    if result is None:
                        await before_retry()
                        _dispatch_check(deadline)
                        try:result=await transaction(action)
                        except _CommitUnknown:
                            result=await transaction(confirm)
                            if result is None:raise ProviderUnavailable() from None
                _dispatch_check(deadline)
                return result

            try:
                maximum,state=await transaction(preflight)
                _dispatch_check(deadline)
                inspect_id='security-inspect-'+hashlib.sha256(json.dumps([physical['recovery_id'],target.intent_id,target.owner_token],separators=(',',':')).encode()).hexdigest()
                attempt,inspection=issue(min(maximum+1,256),inspect_id)
                await security_recovery_projection(self._writer,current,deadline=deadline,previous=projection)
                _dispatch_check(deadline)
                handle=self._control().recovery_transport_for(attempt)
                try:
                    diagnostic=await inspect_security_readback(handle,self.config,source,deadline=deadline,budget=allowance)
                    missing=tuple(sorted(set(diagnostic['missing_ids'])|set(diagnostic['stale_ids'])))
                    _dispatch_check(deadline)
                finally:
                    await handle.close()
                _dispatch_check(deadline)
                maximum,state=await transaction(preflight)
                _dispatch_check(deadline)
                if not missing:
                    await security_recovery_projection(self._writer,current,deadline=deadline,previous=projection)
                    _dispatch_check(deadline)
                    return MappingProxyType(dict(batches=0,points=0))
                batches=(len(missing)+7)//8
                if maximum+batches>256:
                    raise ProviderUnavailable()
                for index in range(batches):
                    if allowance.remaining_bytes<=0 or allowance.remaining_calls<=0:
                        raise ProviderUnavailable()
                    selected=tuple(missing[index*8:index*8+8]);number=maximum+index+1
                    identity='security-dispatch-'+hashlib.sha256(json.dumps([physical['instance_id'],physical['recovery_id'],
                        str(physical['new_epoch']),physical['credential_generation'],target.intent_id,target.owner_token,str(number),selected],
                        separators=(',',':')).encode()).hexdigest()
                    attempt,authorization=issue(number,identity)
                    plan=await self._writer.project_security_dispatch(authorization,selected,deadline=deadline)
                    _dispatch_check(deadline)
                    data=security_dispatch_plan_data(plan,authorization,self._writer,deadline=deadline)
                    async def fresh() -> None:
                        await permitted()
                        await self._writer.validate_security_dispatch(plan,authorization,deadline=deadline)
                        _dispatch_check(deadline)
                    async def exact(connection: SessionConnection) -> str | None:
                        await fences(connection,data)
                        rows=await self._query(connection,
                            'SELECT sequence,owner_token::text,backend_epoch,credential_generation,operation,recovery,request_sha256,state,completion_sha256,instance_id '
                            'FROM cragkit_qdrant.dispatch_journal WHERE '+_INTENT+' AND dispatch_id=%s',(*_intent(target),identity))
                        if not rows:return None
                        expected=(number,target.owner_token,physical['new_epoch'],physical['credential_generation'],
                            'complete_point_upsert',True,data['request_sha256'])
                        if (len(rows)!=1 or len(rows[0])!=10 or rows[0][:7]!=expected or rows[0][9]!=physical['instance_id']
                                or rows[0][7] not in ('reserved','dispatched','unknown','settled')
                                or (rows[0][7]=='settled') != (rows[0][8] is not None)):
                            raise IntegrityViolation()
                        members=await self._query(connection,
                            'SELECT point_id::text,backend_namespace,physical_collection,collection_incarnation '
                            'FROM cragkit_qdrant.dispatch_points WHERE '+_INTENT+' AND dispatch_id=%s ORDER BY point_id::text LIMIT 9',(*_intent(target),identity))
                        if members!=[(point,self.config.backend_namespace,self.config.physical_collection,self.config.collection_incarnation) for point in selected]:
                            raise IntegrityViolation()
                        return cast(str,rows[0][7])
                    async def reserve(connection: SessionConnection) -> str:
                        latest,_=await preflight(connection)
                        if latest+1!=number:raise ProviderUnavailable()
                        await fences(connection,data)
                        if await exact(connection) is not None:
                            raise IntegrityViolation()
                        claims=await self._query(connection,'SELECT point_id::text FROM cragkit_qdrant.point_claims WHERE '+_DOC+
                            ' AND point_id=ANY(%s::uuid[]) AND instance_id=%s '
                            'AND backend_namespace=%s AND physical_collection=%s AND collection_incarnation=%s ORDER BY point_id::text LIMIT 9',
                            (*_target(target),list(selected),physical['instance_id'],
                             self.config.backend_namespace,self.config.physical_collection,self.config.collection_incarnation))
                        if claims!=[(point,) for point in selected]:raise IntegrityViolation()
                        await connection.execute('INSERT INTO cragkit_qdrant.dispatch_journal '
                            '(tenant_id,collection,document_id,intent_id,dispatch_id,instance_id,sequence,owner_token,backend_epoch,credential_generation,operation,recovery,request_bytes,request_sha256) '
                            'VALUES ('+','.join('%s' for _ in range(14))+')',(*_intent(target),identity,physical['instance_id'],number,target.owner_token,
                             physical['new_epoch'],physical['credential_generation'],'complete_point_upsert',True,data['request_bytes'],data['request_sha256']))
                        for point in selected:
                            await connection.execute('INSERT INTO cragkit_qdrant.dispatch_points '
                                '(tenant_id,collection,document_id,intent_id,dispatch_id,backend_namespace,physical_collection,collection_incarnation,point_id) '
                                'VALUES ('+','.join('%s' for _ in range(9))+')',(*_intent(target),identity,self.config.backend_namespace,
                                 self.config.physical_collection,self.config.collection_incarnation,point))
                        return 'reserved'
                    await permitted()
                    await self._writer.validate_security_dispatch(plan,authorization,deadline=deadline);_dispatch_check(deadline)
                    if await commit(reserve,exact,fresh)!='reserved':raise ProviderUnavailable()
                    async def mark(connection: SessionConnection, desired: str, completion: str | None) -> str:
                        current=await exact(connection)
                        needed='reserved' if desired=='dispatched' else 'dispatched'
                        if current!=needed:raise ProviderUnavailable()
                        await connection.execute('UPDATE cragkit_qdrant.dispatch_journal SET state=%s,completion_sha256=%s WHERE '+_INTENT+' AND dispatch_id=%s',
                            (desired,completion,*_intent(target),identity))
                        return desired
                    async def confirm_dispatched(connection: SessionConnection) -> str | None:
                        current=await exact(connection)
                        if current=='dispatched':return current
                        if current=='reserved':return None
                        raise ProviderUnavailable()
                    await permitted()
                    await self._writer.validate_security_dispatch(plan,authorization,deadline=deadline);_dispatch_check(deadline)
                    await commit(lambda connection:mark(connection,'dispatched',None),confirm_dispatched,fresh)
                    await permitted()
                    await self._writer.validate_security_dispatch(plan,authorization,deadline=deadline);_dispatch_check(deadline)
                    security_dispatch_authorization(authorization,self._writer,deadline=deadline)
                    handle=self._control().recovery_transport_for(attempt)
                    try:
                        try:
                            raw=await security_storage_request(handle,'PUT','/collections/'+self.config.physical_collection+'/points?wait=true&ordering=strong',
                                data['request_bytes'],deadline=deadline,budget=allowance)
                        except BaseException:
                            try:
                                _dispatch_check(deadline);await fresh()
                                async def confirm_unknown(connection: SessionConnection) -> str | None:
                                    current=await exact(connection)
                                    if current=='unknown':return current
                                    if current=='dispatched':return None
                                    raise ProviderUnavailable()
                                await commit(lambda connection:mark(connection,'unknown',None),confirm_unknown,fresh)
                            except BaseException:
                                pass
                            raise
                        _dispatch_check(deadline)
                        response=decode_response(raw)
                        if (type(response) is not dict or response.get('status')!='ok'
                                or type(response.get('result')) is not dict or response['result'].get('status')!='completed'
                                or set(response['result'])-{'status','operation_id'}):
                            raise IntegrityViolation()
                        operation_id=response['result'].get('operation_id')
                        if 'operation_id' in response['result'] and (type(operation_id) not in (int,float)
                                or not 0<=operation_id<=9007199254740991 or int(operation_id)!=operation_id):
                            raise IntegrityViolation()
                        completion=hashlib.sha256(raw).hexdigest()
                    finally:await handle.close()
                    _dispatch_check(deadline)
                    await permitted()
                    await self._writer.validate_security_dispatch(plan,authorization,deadline=deadline);_dispatch_check(deadline)
                    async def confirm_settled(connection: SessionConnection) -> str | None:
                        current=await exact(connection)
                        if current=='dispatched':return None
                        if current!='settled':raise ProviderUnavailable()
                        rows=await self._query(connection,'SELECT completion_sha256 FROM cragkit_qdrant.dispatch_journal WHERE '+_INTENT+' AND dispatch_id=%s',(*_intent(target),identity))
                        if rows!=[(completion,)]:raise IntegrityViolation()
                        return current
                    await commit(lambda connection:mark(connection,'settled',completion),confirm_settled,fresh)
                await security_recovery_projection(self._writer,current,deadline=deadline,previous=projection)
                _dispatch_check(deadline)
                return MappingProxyType(dict(batches=batches,points=len(missing)))
            finally:
                for token in active:
                    _SECURITY_DISPATCH_AUTHORIZATIONS[token]['active']=False

    async def reopen(self, proof: object, *, deadline: float) -> Mapping[str, Any]:
        async with self._operation(deadline):
            barrier = await self._control().seal_recovery(proof, deadline=deadline)
            physical = physical_binding(dict(self.supervisor.barrier_binding(barrier)))
            async def open_instance(connection: SessionConnection, *, reconcile: bool = False) -> int:
                backend = await self._backend(connection)
                if (backend['epoch'] != physical['new_epoch']
                        or backend['storage_identity'] != physical['storage_identity']
                        or backend['supervisor_id'] != physical['supervisor_id']):
                    raise IntegrityViolation()
                if (backend['state'], backend['recovery_id']) not in (
                    ('recovery_blocked', physical['recovery_id']), ('open', None),
                ):
                    raise ProviderUnavailable()
                pending = await self._query(connection,
                    'SELECT dispatch_id FROM cragkit_qdrant.dispatch_journal '
                    "WHERE instance_id=%s AND state<>'settled' LIMIT 1", (physical['instance_id'],))
                if pending:
                    raise ProviderUnavailable()
                if backend['state'] == 'recovery_blocked':
                    if reconcile:
                        raise ProviderUnavailable()
                    await connection.execute(
                        "UPDATE cragkit_qdrant.backend_instances SET state='open',recovery_id=NULL "
                        'WHERE instance_id=%s', (physical['instance_id'],))
                return cast(int, physical['new_epoch'])
            try:
                epoch = await self._transaction(deadline, open_instance)
            except _CommitUnknown:
                epoch = await self._transaction(deadline,
                    lambda connection: open_instance(connection, reconcile=True))
            if dict(self.supervisor.barrier_binding(barrier)) != dict(physical):
                raise UnsupportedCapability()
            token = _SQLSettlement()
            _SETTLEMENTS[token] = (self.supervisor, barrier, physical)
            self._control().finish_recovery(barrier, token, deadline=deadline)
            return MappingProxyType({'state': 'open', 'epoch': epoch})

    async def close(self) -> None:
        self._closed = True
        task = self._active
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            done, pending = await asyncio.wait({task}, timeout=self.resource.config.release_timeout * 2)
            for finished in done:
                if not finished.cancelled():
                    finished.exception()
            if pending:
                raise ProviderUnavailable()
