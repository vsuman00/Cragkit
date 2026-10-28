"""Committed, bounded QW-r1 authority operations; no vector service calls."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
import json
import re
from types import MappingProxyType
from collections.abc import Mapping
from typing import Any, Awaitable, Callable, TypeVar, cast
from weakref import WeakKeyDictionary

from ._postgres_pool import PoolResource
from ._postgres_session import SessionConnection
from ._qdrant_authority import (_HISTORY_SQL, _PUBLICATION_CATALOG_SQL, _CATALOG_FINGERPRINT_SQL,
    EXPECTED_PUBLICATION_HISTORY, EXPECTED_PUBLICATION_CATALOG_FINGERPRINT,
    _ATTESTATION_CATALOG_SQL, EXPECTED_ATTESTATION_HISTORY, EXPECTED_ATTESTATION_CATALOG_FINGERPRINT)
from ._qdrant_contract import (CandidatePayload, QdrantConfig, SPARSE_PROFILE, decode_response,
                               parse_model, point_id)
from ._qdrant_manifest import (_Security, _Purge, _Manifest, _Stage, _ReplayResult, _parse,
    encode_security_intent, encode_stage_intent, encode_purge_intent, encode_manifest,
    restore_dense_replay, restore_sparse_replay)
from ._qdrant_transport import deadline_value
from ._qdrant_writer_contract import (StagePlan, StageData, WriterContext, bind_stage, context,
    prepare_stage, sequence, issue_stage, stage_data)
from ._qdrant_reconciliation import (ExpectedPoint, ExpectedProjection, physical_binding,
    finalize_projection, projection_data)
from ._qdrant_publication_verification import (PublicationProjection, ordinary_binding,
    finalize_publication_projection, publication_projection_data, attestation_receipt_data, publication_verifier_controller)
from ._qdrant_publication_worker import require_publication_finalization
from ._qdrant_vectors import _DenseVector, _SparseVector
from ._qdrant_source import IMMUTABLE_FIELDS, metadata_guard
from .contracts import TrustedScope
from .embeddings import FAKE_PROFILE, OPENAI_PROFILE
from .errors import (CragkitError, DeadlineExceeded, IndexNotReady, IntegrityViolation,
    InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)

_T = TypeVar('_T')
_WRITER_ORIGINS: WeakKeyDictionary[
    object, tuple[PoolResource, QdrantConfig, str]
] = WeakKeyDictionary()
_DOC = 'tenant_id=%s AND collection=%s AND document_id=%s'
_INTENT = _DOC + ' AND intent_id=%s'
_META = ('action','state','payload_sha256','manifest_sha256','revision_id','generation_id',
         'authority_committed','replica_complete','purge_complete')
_SCOPE_SQL = """SELECT set_config('cragkit_qdrant.tenant_id',%s,true),
 set_config('cragkit_qdrant.collection',%s,true),set_config('cragkit_qdrant.principal_id',%s,true),
 set_config('cragkit_qdrant.grant_ids',%s,true),set_config('cragkit_qdrant.authorization_revision',%s,true),
 set_config('cragkit_qdrant.writer_document_id',%s,true),set_config('cragkit_qdrant.writer_intent_id',%s,true),
 set_config('cragkit_qdrant.writer_owner_token',%s,true),set_config('cragkit_qdrant.backend_instance_id',%s,true)"""
_WRITER_ROLE_SQL = """
SELECT current_user=session_user
 AND EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolcanlogin)
 AND EXISTS(SELECT 1 FROM pg_roles r WHERE r.rolname='cragkit_qdrant_writer'
  AND NOT (r.rolcanlogin OR r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication)
  AND NOT EXISTS(SELECT 1 FROM pg_auth_members membership WHERE membership.member=r.oid))
 AND pg_has_role(current_user,'cragkit_qdrant_writer','USAGE')
 AND NOT pg_has_role(current_user,'cragkit_qdrant_supervisor','MEMBER')
 AND NOT EXISTS(SELECT 1 FROM pg_roles r WHERE pg_has_role(current_user,r.oid,'MEMBER') AND
  (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication OR
   r.rolname IN ('pg_read_all_data','pg_write_all_data','pg_read_server_files','pg_write_server_files','pg_execute_server_program')))
 AND NOT EXISTS(SELECT 1 FROM pg_namespace n WHERE n.nspname='cragkit_qdrant' AND
  (pg_has_role(current_user,n.nspowner,'MEMBER') OR has_schema_privilege(current_user,n.oid,'CREATE')))
 AND has_schema_privilege(current_user,'cragkit_qdrant','USAGE')
 AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='cragkit_qdrant' AND (pg_has_role(current_user,c.relowner,'MEMBER') OR
   has_table_privilege(current_user,c.oid,'DELETE,TRUNCATE,REFERENCES,TRIGGER')))
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='cragkit_qdrant' AND pg_has_role(current_user,p.proowner,'MEMBER'))
 AND NOT EXISTS(SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
  WHERE n.nspname='cragkit_qdrant' AND pg_has_role(current_user,t.typowner,'MEMBER'))
 AND has_table_privilege(current_user,'cragkit_qdrant.schema_migrations','SELECT')
 AND has_table_privilege(current_user,'cragkit_qdrant.publication_intents','SELECT,INSERT,UPDATE')
 AND has_table_privilege(current_user,'cragkit_qdrant.point_claims','SELECT,INSERT')
 AND has_table_privilege(current_user,'cragkit_qdrant.vector_replays','SELECT,INSERT')
 AND NOT has_table_privilege(current_user,'cragkit_qdrant.backend_instances','INSERT,DELETE')
 AND NOT EXISTS(SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) privilege
  WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND
  has_table_privilege(current_user,c.oid,privilege) IS DISTINCT FROM CASE
   WHEN privilege='SELECT' THEN c.relname IN ('schema_migrations','documents','document_revisions','generations','members',
    'backend_instances','publication_intents','document_owners','point_claims','vector_replays','dispatch_journal','dispatch_points','preparations')
   WHEN privilege='INSERT' THEN c.relname IN ('documents','document_revisions','generations','members',
    'publication_intents','document_owners','point_claims','vector_replays','dispatch_journal','dispatch_points','preparations')
   WHEN privilege='UPDATE' THEN c.relname IN ('documents','generations','publication_intents','document_owners','dispatch_journal')
   ELSE false END)
 AND NOT EXISTS(SELECT 1 FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
  CROSS JOIN unnest(ARRAY['SELECT','INSERT','UPDATE','REFERENCES']) privilege
  WHERE n.nspname='cragkit_qdrant' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped AND
  has_column_privilege(current_user,c.oid,a.attnum,privilege) IS DISTINCT FROM CASE
   WHEN privilege='SELECT' THEN c.relname IN ('schema_migrations','documents','document_revisions','generations','members',
    'backend_instances','publication_intents','document_owners','point_claims','vector_replays','dispatch_journal','dispatch_points','preparations')
   WHEN privilege='INSERT' THEN c.relname IN ('documents','document_revisions','generations','members',
    'publication_intents','document_owners','point_claims','vector_replays','dispatch_journal','dispatch_points','preparations')
   WHEN privilege='UPDATE' THEN c.relname IN ('documents','generations','publication_intents','document_owners','dispatch_journal')
    OR (c.relname='members' AND a.attname='point_id') OR (c.relname='backend_instances' AND a.attname='epoch')
   ELSE false END)
 AND NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='cragkit_qdrant' AND has_function_privilege(current_user,p.oid,'EXECUTE')
  IS DISTINCT FROM (
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.valid_identity_array(text[])') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.scope_grants()') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.writer_scope(text,text,text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.bound_stage(text,text,text,text,text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.supervisor_instance(text)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.scope_visible(text,text,text[],text[],text,boolean)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.lock_publication_owner(text,text,text,text,uuid,bigint,boolean)') OR
   p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.assert_publication(text,text,text,text)')))
"""


_WRITER_ATTESTATION_ROLE_SQL = _WRITER_ROLE_SQL.replace(
    "'dispatch_points','preparations')", "'dispatch_points','preparations','preparation_attestations')"
).replace(" AND has_table_privilege(current_user,'cragkit_qdrant.vector_replays','SELECT,INSERT')",
    " AND has_table_privilege(current_user,'cragkit_qdrant.vector_replays','SELECT,INSERT')"
    "\n AND has_table_privilege(current_user,'cragkit_qdrant.preparation_attestations','SELECT,INSERT')")
_ATTESTATION_FIELDS = ('tenant_id','collection','document_id','intent_id','instance_id','owner_token',
    'backend_epoch','authorization_revision','mutation_epoch','manifest_sha256',
    'expected_active_generation_id','credential_generation','verification_id','readback_sha256')
_PREPARATION_FIELDS = ('owner_token','backend_epoch','authorization_revision','mutation_epoch','manifest_sha256','readback_sha256')


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def _complete_point_request(points: list[dict[str, Any]]) -> bytes:
    encoded = _json({'points': points}).encode('utf-8')
    if len(encoded) > 1048576:
        raise InvalidRequest()
    return encoded


class _RecoveryDispatchPlan:
    __slots__ = ('__weakref__',)
    def __repr__(self) -> str:
        return 'RecoveryDispatchPlan()'
    def __reduce__(self) -> Any:
        raise TypeError('Dispatch plans cannot be serialized')


_RECOVERY_PLANS: WeakKeyDictionary[_RecoveryDispatchPlan, tuple[object, object, Mapping[str, Any]]] = WeakKeyDictionary()


def recovery_dispatch_plan_data(plan: object, authorization: object, expected_writer: object,
                                *, deadline: float) -> Mapping[str, Any]:
    from ._qdrant_recovery import recovery_dispatch_authorization
    data = recovery_dispatch_authorization(authorization, expected_writer, deadline=deadline)
    if type(plan) is not _RecoveryDispatchPlan or plan not in _RECOVERY_PLANS:
        raise InvalidRequest()
    writer, issued, result = _RECOVERY_PLANS[plan]
    if (writer is not expected_writer or issued is not authorization
            or any(result[key] != data[key] for key in ('context','physical_binding','attempt_binding','sequence'))):
        raise InvalidRequest()
    return result


def _acl(value: tuple[str, ...]) -> list[str]:
    return sorted(set(value),key=lambda item:item.encode('utf-8'))


def _identity(value: object) -> str:
    if type(value) is not str or not value.strip(' \t\r\n\v\f') or '\0' in value or len(value) > 256:
        raise InvalidRequest()
    try:
        if len(value.encode('utf-8')) > 256:
            raise InvalidRequest()
    except UnicodeError:
        raise InvalidRequest() from None
    return value


def _digest(value: object) -> str:
    if type(value) is not str or re.fullmatch('[0-9a-f]{64}', value) is None:
        raise InvalidRequest()
    return value


def _doc(ctx: WriterContext) -> tuple[object, ...]:
    return ctx.scope.tenant_id, ctx.collection, ctx.document_id


def _key(ctx: WriterContext) -> tuple[object, ...]:
    return (*_doc(ctx), ctx.intent_id)


def _safe(error: Exception, deadline: float) -> CragkitError:
    for kind in (DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest, UnauthorizedScope, UnsupportedCapability):
        if type(error) is kind:
            return kind()
    try:
        code = getattr(error, 'sqlstate', None)
    except Exception:
        code = None
    if type(code) is not str:
        code = None
    if code in ('42P01','42703','42883'):
        return UnsupportedCapability()
    if code == '42501':
        return UnauthorizedScope()
    if code in ('23503','23505','23514'):
        return IntegrityViolation()
    if code == '57014' and asyncio.get_running_loop().time() >= deadline:
        return DeadlineExceeded()
    return ProviderUnavailable()


@dataclass(frozen=True, slots=True)
class Dispatch:
    dispatch_id: str
    request_bytes: bytes
    request_sha256: str
    point_ids: tuple[str, ...]
    operation: str
    state: str


class _CommitUnknown(Exception):
    """Private discrimination for an unacknowledged committing transaction."""


def _stored_identity(value: object, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    try:
        return _identity(value)
    except InvalidRequest:
        raise IntegrityViolation() from None


def _stored_count(value: object, minimum: int = 0, maximum: int = 9007199254740991) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise IntegrityViolation()
    return value


def _stored_uuid(value: object) -> str:
    if type(value) is not str or re.fullmatch(
            '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', value) is None:
        raise IntegrityViolation()
    return value


def writer_binding(value: object) -> Mapping[str, Any]:
    """Return nominal constructor metadata, never a resource or permission."""
    if type(value) is not PostgresQdrantWriter or value not in _WRITER_ORIGINS:
        raise InvalidRequest()
    resource, config, instance_id = _WRITER_ORIGINS[value]
    if (value.resource is not resource or value.config is not config
            or type(value.instance_id) is not str or value.instance_id != instance_id):
        raise InvalidRequest()
    return MappingProxyType({'config': config, 'instance_id': instance_id})


class PostgresQdrantWriter:
    def __init__(self, resource: PoolResource, config: object, instance_id: object) -> None:
        if type(resource) is not PoolResource:
            raise InvalidRequest()
        self.resource = resource
        metadata_guard(config)
        self.config = parse_model(QdrantConfig, config)
        if self.config.dense_profile.model_dump() not in (FAKE_PROFILE.model_dump(),OPENAI_PROFILE.model_dump()):
            raise UnsupportedCapability()
        if self.config.sparse_profile is not None and (self.config.sparse_profile != SPARSE_PROFILE or
            self.config.dense_profile.model_dump() != FAKE_PROFILE.model_dump()):
            raise UnsupportedCapability()
        self.instance_id = _identity(instance_id)
        self._ready = False
        self._schema_profile = 2
        self._closed = False
        self._active: asyncio.Task[Any] | None = None
        _WRITER_ORIGINS[self] = (self.resource, self.config, self.instance_id)

    async def _query(self, connection: SessionConnection, sql: str,
                     params: tuple[object, ...] = ()) -> list[tuple[Any, ...]]:
        cursor = await connection.execute(sql, params)
        rows = await cursor.fetchall()
        if type(rows) is not list or any(type(row) is not tuple for row in rows):
            raise IntegrityViolation()
        return rows

    async def _run(self, ctx: WriterContext | None, deadline: float,
                   operation: Callable[[SessionConnection], Awaitable[_T]], *, initializing: bool = False,
                   detect_commit_unknown: bool = False) -> _T:
        deadline = deadline_value(deadline)
        if self._closed or self._active is not None:
            raise ProviderUnavailable()
        if not initializing and not self._ready:
            raise IndexNotReady()
        self._active = asyncio.current_task()
        try:
            async with asyncio.timeout_at(deadline):
                async with self.resource.lease(deadline=deadline) as leased:
                    connection = cast(SessionConnection, leased)
                    if connection.info.transaction_status != 0:
                        await connection.close()
                        raise InvalidRequest()
                    transaction = connection.transaction()
                    entered = committing = False
                    try:
                        await transaction.__aenter__()
                        entered = True
                        await connection.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                        await connection.execute('SET LOCAL search_path=pg_catalog')
                        milliseconds = max(1, min(2147483647, int((deadline-asyncio.get_running_loop().time())*1000)))
                        await connection.execute("SELECT set_config('statement_timeout',%s,true)", (str(milliseconds),))
                        profile = self._schema_profile
                        if initializing:
                            history = await self._query(connection, _HISTORY_SQL)
                            if history == list(EXPECTED_PUBLICATION_HISTORY):
                                profile = 2
                            elif history == list(EXPECTED_ATTESTATION_HISTORY):
                                profile = 3
                            else:
                                raise UnsupportedCapability()
                        role_sql = _WRITER_ATTESTATION_ROLE_SQL if profile == 3 else _WRITER_ROLE_SQL
                        if await self._query(connection, role_sql) != [(True,)]:
                            raise UnauthorizedScope()
                        if ctx is not None:
                            grants = _json(list(ctx.scope.grant_ids))
                            if len(grants.encode('utf-8')) > 131072:
                                raise InvalidRequest()
                            await connection.execute(_SCOPE_SQL, (ctx.scope.tenant_id, ctx.collection,
                                ctx.scope.principal_id, grants, ctx.scope.authorization_revision,
                                ctx.document_id, ctx.intent_id, ctx.owner_token, self.instance_id))
                        result = await operation(connection)
                        deadline_value(deadline)
                        committing = True
                        try:
                            await transaction.__aexit__(None, None, None)
                        except (asyncio.CancelledError, TimeoutError, DeadlineExceeded):
                            raise
                        except Exception as error:
                            try:
                                code = getattr(error, 'sqlstate', None)
                            except Exception:
                                code = None
                            known_rollback = type(code) is str and code in (
                                '23503', '23505', '23514', '23502', '40001', '40P01', '57014')
                            if detect_commit_unknown and not known_rollback:
                                raise _CommitUnknown() from None
                            raise
                        entered = False
                        if connection.info.transaction_status != 0:
                            raise ProviderUnavailable()
                        deadline_value(deadline)
                        return result
                    finally:
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
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise DeadlineExceeded() from None
        except _CommitUnknown:
            if detect_commit_unknown:
                raise
            raise ProviderUnavailable() from None
        except Exception as error:
            raise _safe(error, deadline) from None
        finally:
            self._active = None

    async def initialize(self, *, deadline: float) -> None:
        if self._closed or self._active is not None:
            raise ProviderUnavailable()
        self._ready = False
        async def initialize(connection: SessionConnection) -> None:
            history = await self._query(connection, _HISTORY_SQL)
            if history == list(EXPECTED_PUBLICATION_HISTORY):
                profile, catalog, fingerprint = 2, _PUBLICATION_CATALOG_SQL, EXPECTED_PUBLICATION_CATALOG_FINGERPRINT
            elif history == list(EXPECTED_ATTESTATION_HISTORY):
                profile, catalog, fingerprint = 3, _ATTESTATION_CATALOG_SQL, EXPECTED_ATTESTATION_CATALOG_FINGERPRINT
            else:
                raise UnsupportedCapability()
            if await self._query(connection, catalog) != [(True,)]:
                raise UnsupportedCapability()
            if await self._query(connection, _CATALOG_FINGERPRINT_SQL) != [(fingerprint,)]:
                raise UnsupportedCapability()
            self._schema_profile = profile
        await self._run(None, deadline, initialize, initializing=True)
        self._ready = True

    async def _inspect(self, connection: SessionConnection, ctx: WriterContext) -> Mapping[str, Any] | None:
        rows = await self._query(connection, 'SELECT '+','.join(_META)+' FROM cragkit_qdrant.publication_intents WHERE '+_INTENT, _key(ctx))
        if not rows:
            return None
        if len(rows) != 1 or len(rows[0]) != len(_META):
            raise IntegrityViolation()
        return MappingProxyType(dict(zip(_META, rows[0], strict=True)))

    async def inspect(self, value: object, *, deadline: float) -> Mapping[str, Any] | None:
        ctx = context(value)
        return await self._run(ctx, deadline, lambda connection: self._inspect(connection, ctx))

    async def _manager_intent(self, connection: SessionConnection,
                              ctx: WriterContext) -> Mapping[str, Any] | None:
        result = await self._inspect(connection, ctx)
        if result is None:
            return None
        if (set(result) != set(_META) or type(result['action']) is not str
                or result['action'] not in ('stage', 'update_authorization', 'tombstone', 'purge')
                or type(result['state']) is not str or result['state'] not in (
                    'staged', 'writing', 'prepared', 'published', 'conflict', 'denied',
                    'authority_committed', 'complete')):
            raise IntegrityViolation()
        try:
            _digest(result['payload_sha256'])
            if result['manifest_sha256'] is not None:
                _digest(result['manifest_sha256'])
        except InvalidRequest:
            raise IntegrityViolation() from None
        _stored_identity(result['revision_id'], nullable=True)
        _stored_identity(result['generation_id'], nullable=True)
        for key in ('authority_committed', 'replica_complete', 'purge_complete'):
            if type(result[key]) is not bool:
                raise IntegrityViolation()
        if result['action'] == 'stage' and any(result[key] is None for key in
                ('manifest_sha256', 'revision_id', 'generation_id')):
            raise IntegrityViolation()
        return MappingProxyType(dict(result))

    async def _manager_document(self, connection: SessionConnection, ctx: WriterContext, *,
                                lock: bool = False) -> Mapping[str, Any] | None:
        columns = ('active_generation_id', 'authorization_revision', 'mutation_epoch', 'tombstoned')
        rows = await self._query(connection, 'SELECT ' + ','.join(columns)
            + ' FROM cragkit_qdrant.documents WHERE ' + _DOC
            + ' LIMIT 2' + (' FOR UPDATE' if lock else ''), _doc(ctx))
        if not rows:
            return None
        if len(rows) != 1 or len(rows[0]) != len(columns):
            raise IntegrityViolation()
        result = dict(zip(columns, rows[0], strict=True))
        _stored_identity(result['active_generation_id'], nullable=True)
        _stored_identity(result['authorization_revision'])
        _stored_count(result['mutation_epoch'])
        if type(result['tombstoned']) is not bool:
            raise IntegrityViolation()
        if result['authorization_revision'] != ctx.scope.authorization_revision:
            raise UnauthorizedScope()
        return MappingProxyType(result)

    async def _manager_backend(self, connection: SessionConnection, *,
                               lock: bool = False) -> Mapping[str, Any]:
        columns = ('instance_id', 'backend_namespace', 'storage_identity', 'supervisor_id',
                   'epoch', 'state', 'recovery_id')
        rows = await self._query(connection, 'SELECT ' + ','.join(columns)
            + ' FROM cragkit_qdrant.backend_instances WHERE instance_id=%s LIMIT 2'
            + (' FOR SHARE' if lock else ''), (self.instance_id,))
        if not rows:
            raise ProviderUnavailable()
        if len(rows) != 1 or len(rows[0]) != len(columns):
            raise IntegrityViolation()
        result = dict(zip(columns, rows[0], strict=True))
        for key in ('instance_id', 'backend_namespace', 'storage_identity', 'supervisor_id'):
            _stored_identity(result[key])
        _stored_count(result['epoch'], 1)
        _stored_identity(result['recovery_id'], nullable=True)
        if (result['instance_id'] != self.instance_id
                or result['backend_namespace'] != self.config.backend_namespace
                or type(result['state']) is not str or result['state'] not in ('open', 'recovery_blocked')
                or (result['state'] == 'open') != (result['recovery_id'] is None)):
            raise IntegrityViolation()
        return MappingProxyType(result)

    async def _manager_owner(self, connection: SessionConnection, ctx: WriterContext, *,
                             lock: bool = False) -> Mapping[str, Any] | None:
        columns = ('instance_id', 'intent_id', 'owner_token', 'backend_epoch')
        rows = await self._query(connection,
            'SELECT instance_id,intent_id,owner_token::text,backend_epoch '
            'FROM cragkit_qdrant.document_owners WHERE ' + _DOC + ' LIMIT 2'
            + (' FOR UPDATE' if lock else ''), _doc(ctx))
        if not rows:
            return None
        if len(rows) != 1 or len(rows[0]) != len(columns):
            raise IntegrityViolation()
        result = dict(zip(columns, rows[0], strict=True))
        _stored_identity(result['instance_id'])
        _stored_identity(result['intent_id'])
        _stored_uuid(result['owner_token'])
        _stored_count(result['backend_epoch'], 1)
        return MappingProxyType(result)

    async def manager_snapshot(self, value: object, *, deadline: float) -> Mapping[str, Any]:
        ctx = context(value)

        async def snapshot(connection: SessionConnection) -> Mapping[str, Any]:
            document = await self._manager_document(connection, ctx)
            intent = await self._manager_intent(connection, ctx)
            backend = await self._manager_backend(connection)
            owner = await self._manager_owner(connection, ctx)
            rows = await self._query(connection,
                'SELECT sequence FROM cragkit_qdrant.dispatch_journal WHERE ' + _INTENT
                + ' ORDER BY sequence LIMIT 257', _key(ctx))
            if len(rows) > 256 or any(len(row) != 1 for row in rows):
                raise IntegrityViolation()
            numbers = tuple(_stored_count(row[0], 1, 256) for row in rows)
            if len(set(numbers)) != len(numbers):
                raise IntegrityViolation()
            pending = await self._query(connection,
                'SELECT dispatch_id FROM cragkit_qdrant.dispatch_journal WHERE ' + _DOC
                + " AND state<>'settled' LIMIT 1", _doc(ctx))
            if len(pending) > 1 or any(len(row) != 1 for row in pending):
                raise IntegrityViolation()
            if pending:
                _stored_identity(pending[0][0])
            return MappingProxyType({'intent': intent, 'document': document, 'backend': backend,
                'owner': owner, 'max_sequence': max(numbers, default=0), 'pending': bool(pending)})
        return await self._run(ctx, deadline, snapshot)

    async def preflight_repair(self, value: object, *, deadline: float) -> Mapping[str, Any]:
        self._attestation_profile()
        ctx = context(value)
        async def preflight(connection: SessionConnection) -> Mapping[str, Any]:
            backend = await self._manager_backend(connection, lock=True)
            owner = await self._manager_owner(connection, ctx, lock=True)
            document = await self._manager_document(connection, ctx, lock=True)
            if document is None:
                raise UnauthorizedScope()
            intent = await self._manager_intent(connection, ctx)
            if intent is None:
                raise InvalidRequest()
            if intent['action'] != 'stage':
                raise UnsupportedCapability()
            if intent['state'] not in ('published', 'conflict', 'denied'):
                rows = await self._query(connection,
                    'SELECT expected_authorization_revision,expected_mutation_epoch,'
                    'expected_active_generation_id,manifest_sha256,generation_id,revision_id,state '
                    'FROM cragkit_qdrant.publication_intents WHERE ' + _INTENT, _key(ctx))
                if len(rows) != 1 or len(rows[0]) != 7:
                    raise IntegrityViolation()
                original = rows[0]
                failure = None
                if document['tombstoned'] or original[:2] != (document['authorization_revision'], document['mutation_epoch']):
                    failure = 'denied'
                elif original[2] != document['active_generation_id']:
                    failure = 'conflict'
                if failure is not None:
                    intent = await self._outcome(connection, ctx, failure)
                else:
                    plan = await self._load_stage(connection, ctx)
                    self._attestation_intent(plan, original, intent)
            rows = await self._query(connection,
                'SELECT dispatch_id FROM cragkit_qdrant.dispatch_journal WHERE ' + _DOC
                + " AND state<>'settled' LIMIT 1", _doc(ctx))
            if len(rows) > 1 or any(len(row) != 1 for row in rows):
                raise IntegrityViolation()
            if rows:
                _stored_identity(rows[0][0])
            return MappingProxyType({'intent': intent, 'owner': owner, 'backend': backend, 'pending': bool(rows)})
        return await self._run(ctx, deadline, preflight)

    async def admit_publication(self, value: object, *, deadline: float) -> Mapping[str, Any]:
        ctx = context(value)

        async def admit(connection: SessionConnection) -> Mapping[str, Any]:
            document = await self._manager_document(connection, ctx)
            if document is None:
                raise UnauthorizedScope()
            intent = await self._manager_intent(connection, ctx)
            if intent is None or intent['action'] != 'stage':
                raise InvalidRequest()
            if intent['state'] in ('published', 'conflict', 'denied'):
                return MappingProxyType({'intent': intent, 'owner': None})
            backend = await self._manager_backend(connection, lock=True)
            await self._manager_owner(connection, ctx, lock=True)
            document = await self._manager_document(connection, ctx, lock=True)
            if document is None:
                raise UnauthorizedScope()
            intent = await self._manager_intent(connection, ctx)
            if intent is None or intent['action'] != 'stage':
                raise IntegrityViolation()
            if intent['state'] in ('published', 'conflict', 'denied'):
                return MappingProxyType({'intent': intent, 'owner': None})
            fences = await self._query(connection,
                'SELECT expected_authorization_revision,expected_mutation_epoch,'
                'expected_active_generation_id FROM cragkit_qdrant.publication_intents WHERE '
                + _INTENT, _key(ctx))
            if len(fences) != 1 or len(fences[0]) != 3:
                raise IntegrityViolation()
            expected_revision, expected_epoch, expected_active = fences[0]
            _stored_identity(expected_revision)
            _stored_count(expected_epoch)
            _stored_identity(expected_active, nullable=True)
            failure = None
            if (document['tombstoned'] or expected_revision != document['authorization_revision']
                    or expected_epoch != document['mutation_epoch']):
                failure = 'denied'
            elif expected_active != document['active_generation_id']:
                failure = 'conflict'
            if failure is not None:
                outcome = await self._outcome(connection, ctx, failure)
                return MappingProxyType({'intent': outcome, 'owner': None})
            if backend['state'] != 'open':
                raise ProviderUnavailable()
            await self._require_settled(connection, ctx)
            await self._load_stage(connection, ctx)
            await connection.execute(
                'INSERT INTO cragkit_qdrant.document_owners '
                '(tenant_id,collection,document_id,instance_id,intent_id,owner_token,backend_epoch) '
                'VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (tenant_id,collection,document_id) '
                'DO UPDATE SET intent_id=EXCLUDED.intent_id,owner_token=EXCLUDED.owner_token,'
                'backend_epoch=EXCLUDED.backend_epoch',
                (*_doc(ctx), self.instance_id, ctx.intent_id, ctx.owner_token, backend['epoch']))
            await connection.execute("UPDATE cragkit_qdrant.publication_intents SET state='writing' "
                'WHERE ' + _INTENT + " AND state IN ('staged','authority_committed')", _key(ctx))
            result = await self._manager_intent(connection, ctx)
            if result is None:
                raise IntegrityViolation()
            return MappingProxyType({'intent': result, 'owner': MappingProxyType({
                'owner_token': ctx.owner_token, 'backend_epoch': backend['epoch']})})

        try:
            return await self._run(ctx, deadline, admit, detect_commit_unknown=True)
        except _CommitUnknown:
            snapshot = await self.manager_snapshot(ctx, deadline=deadline)
            intent, owner, backend = snapshot['intent'], snapshot['owner'], snapshot['backend']
            if intent is not None and intent['action'] == 'stage':
                if intent['state'] in ('published', 'conflict', 'denied'):
                    return MappingProxyType({'intent': intent, 'owner': None})
                if (intent['state'] in ('writing', 'prepared') and not snapshot['pending']
                        and backend['state'] == 'open' and owner is not None
                        and owner['instance_id'] == self.instance_id
                        and owner['intent_id'] == ctx.intent_id and owner['owner_token'] == ctx.owner_token
                        and owner['backend_epoch'] == backend['epoch']):
                    return MappingProxyType({'intent': intent, 'owner': MappingProxyType({
                        'owner_token': ctx.owner_token, 'backend_epoch': backend['epoch']})})
            return await self._run(ctx, deadline, admit)

    async def dispatch_status(self, value: object, dispatch_id: object, *,
                              deadline: float) -> Mapping[str, Any] | None:
        ctx = context(value)
        identity = _identity(dispatch_id)
        return await self._run(ctx, deadline,
            lambda connection: self._dispatch_status(connection, ctx, identity))

    async def _dispatch_status(self, connection: SessionConnection, ctx: WriterContext,
                               identity: str) -> Mapping[str, Any] | None:

        async def status(connection: SessionConnection) -> Mapping[str, Any] | None:
            document = await self._manager_document(connection, ctx)
            if document is None:
                raise UnauthorizedScope()
            columns = ('sequence', 'owner_token', 'backend_epoch', 'credential_generation',
                       'operation', 'state', 'completion_sha256', 'request_sha256',
                       'request_bytes', 'instance_id', 'recovery')
            rows = await self._query(connection,
                'SELECT sequence,owner_token::text,backend_epoch,credential_generation,operation,'
                'state,completion_sha256,request_sha256,request_bytes,instance_id,recovery '
                'FROM cragkit_qdrant.dispatch_journal WHERE ' + _INTENT
                + ' AND dispatch_id=%s LIMIT 2', (*_key(ctx), identity))
            if not rows:
                return None
            if len(rows) != 1 or len(rows[0]) != len(columns):
                raise IntegrityViolation()
            journal = dict(zip(columns, rows[0], strict=True))
            _stored_count(journal['sequence'], 1, 256)
            _stored_count(journal['backend_epoch'], 1)
            _stored_uuid(journal['owner_token'])
            _stored_identity(journal['credential_generation'])
            if (journal['instance_id'] != self.instance_id or type(journal['recovery']) is not bool
                    or type(journal['operation']) is not str
                    or journal['operation'] not in ('complete_point_upsert', 'delete_points')
                    or type(journal['state']) is not str
                    or journal['state'] not in ('reserved', 'dispatched', 'unknown', 'settled')):
                raise IntegrityViolation()
            try:
                _digest(journal['request_sha256'])
                if journal['completion_sha256'] is not None:
                    _digest(journal['completion_sha256'])
            except InvalidRequest:
                raise IntegrityViolation() from None
            if (journal['state'] == 'settled') != (journal['completion_sha256'] is not None):
                raise IntegrityViolation()
            raw = journal['request_bytes']
            if type(raw) is memoryview:
                if raw.ndim != 1 or raw.itemsize != 1 or not raw.c_contiguous:
                    raise IntegrityViolation()
                if not 1 <= raw.nbytes <= 1048576:
                    raise IntegrityViolation()
                raw = raw.tobytes()
            elif type(raw) is bytearray:
                if not 1 <= len(raw) <= 1048576:
                    raise IntegrityViolation()
                raw = bytes(raw)
            if type(raw) is not bytes or not 1 <= len(raw) <= 1048576:
                raise IntegrityViolation()
            if hashlib.sha256(raw).hexdigest() != journal['request_sha256']:
                raise IntegrityViolation()
            try:
                body = decode_response(raw)
            except InvalidRequest:
                raise IntegrityViolation() from None
            if type(body) is not dict or set(body) != {'points'} or type(body['points']) is not list:
                raise IntegrityViolation()
            if not 1 <= len(body['points']) <= 8:
                raise IntegrityViolation()
            if journal['operation'] == 'delete_points':
                body_ids = tuple(_stored_uuid(item) for item in body['points'])
            else:
                body_ids_list = []
                for point in body['points']:
                    if (type(point) is not dict or set(point) != {'id', 'payload', 'vector'}
                            or type(point['payload']) is not dict or type(point['vector']) is not dict):
                        raise IntegrityViolation()
                    body_ids_list.append(_stored_uuid(point['id']))
                body_ids = tuple(body_ids_list)
            if len(set(body_ids)) != len(body_ids):
                raise IntegrityViolation()
            members = await self._query(connection,
                'SELECT backend_namespace,physical_collection,collection_incarnation,point_id::text '
                'FROM cragkit_qdrant.dispatch_points WHERE ' + _INTENT
                + ' AND dispatch_id=%s ORDER BY point_id::text LIMIT 9', (*_key(ctx), identity))
            if not 1 <= len(members) <= 8 or any(len(row) != 4 for row in members):
                raise IntegrityViolation()
            physical = (self.config.backend_namespace, self.config.physical_collection,
                        self.config.collection_incarnation)
            if any(row[:3] != physical for row in members):
                raise IntegrityViolation()
            ids = tuple(sorted(_stored_uuid(row[3]) for row in members))
            if len(set(ids)) != len(ids) or ids != tuple(sorted(body_ids)):
                raise IntegrityViolation()
            claims = await self._query(connection,
                'SELECT point_id::text FROM cragkit_qdrant.point_claims WHERE ' + _DOC
                + ' AND instance_id=%s AND backend_namespace=%s AND physical_collection=%s'
                ' AND collection_incarnation=%s AND point_id=ANY(%s::uuid[]) LIMIT 9',
                (*_doc(ctx), self.instance_id, *physical, list(ids)))
            if (any(len(row) != 1 for row in claims)
                    or tuple(sorted(_stored_uuid(row[0]) for row in claims)) != ids):
                raise IntegrityViolation()
            result = {key: journal[key] for key in columns if key not in
                      ('request_bytes', 'instance_id', 'recovery')}
            result.update(dispatch_id=identity, point_ids=ids)
            return MappingProxyType(result)
        return await status(connection)

    async def publication_preparation(self, value: object, *,
                                      deadline: float) -> Mapping[str, Any] | None:
        ctx = context(value)

        async def read(connection: SessionConnection) -> Mapping[str, Any] | None:
            document = await self._manager_document(connection, ctx)
            if document is None:
                raise UnauthorizedScope()
            intent = await self._manager_intent(connection, ctx)
            if intent is None or intent['action'] != 'stage':
                raise InvalidRequest()
            backend = await self._manager_backend(connection)
            columns = ('owner_token', 'backend_epoch', 'authorization_revision', 'mutation_epoch',
                       'manifest_sha256', 'readback_sha256')
            rows = await self._query(connection,
                'SELECT owner_token::text,backend_epoch,authorization_revision,mutation_epoch,'
                'manifest_sha256,readback_sha256 FROM cragkit_qdrant.preparations WHERE '
                + _INTENT + ' LIMIT 2', _key(ctx))
            if not rows:
                if intent['state'] == 'prepared':
                    raise IntegrityViolation()
                return None
            if len(rows) != 1 or len(rows[0]) != len(columns):
                raise IntegrityViolation()
            preparation = dict(zip(columns, rows[0], strict=True))
            _stored_uuid(preparation['owner_token'])
            _stored_count(preparation['backend_epoch'], 1)
            _stored_identity(preparation['authorization_revision'])
            _stored_count(preparation['mutation_epoch'])
            try:
                _digest(preparation['manifest_sha256'])
                _digest(preparation['readback_sha256'])
            except InvalidRequest:
                raise IntegrityViolation() from None
            fences = await self._query(connection,
                'SELECT expected_authorization_revision,expected_mutation_epoch,manifest_sha256 '
                'FROM cragkit_qdrant.publication_intents WHERE ' + _INTENT, _key(ctx))
            if (len(fences) != 1 or fences[0] != (preparation['authorization_revision'],
                    preparation['mutation_epoch'], preparation['manifest_sha256'])
                    or intent['manifest_sha256'] != preparation['manifest_sha256']):
                raise IntegrityViolation()
            # Validate the original immutable intent bytes; current authority may
            # have advanced and is classified separately by admit_publication.
            payloads = await self._query(connection,
                'SELECT payload_bytes,payload_sha256,manifest_bytes FROM '
                'cragkit_qdrant.publication_intents WHERE ' + _INTENT, _key(ctx))
            if len(payloads) != 1 or len(payloads[0]) != 3:
                raise IntegrityViolation()
            payload, digest, manifest = payloads[0]
            if (type(payload) is not bytes or type(manifest) is not bytes
                    or not 1 <= len(payload) <= 1048576 or not 1 <= len(manifest) <= 1048576
                    or hashlib.sha256(payload).hexdigest() != digest
                    or digest != intent['payload_sha256']
                    or hashlib.sha256(manifest).hexdigest() != preparation['manifest_sha256']):
                raise IntegrityViolation()
            if backend['state'] != 'open' or backend['epoch'] != preparation['backend_epoch']:
                raise ProviderUnavailable()
            # Metadata lookup does not require the caller or current owner to
            # own this preparation. Admission performs the authoritative CAS.
            await self._require_settled(connection, ctx)
            await self._load_stage(connection, ctx)
            journals = await self._query(connection,
                'SELECT dispatch_id,sequence FROM cragkit_qdrant.dispatch_journal WHERE '
                + _INTENT + " AND state='settled' ORDER BY sequence DESC LIMIT 2", _key(ctx))
            if not journals or any(len(row) != 2 for row in journals):
                raise IntegrityViolation()
            selected_id = _stored_identity(journals[0][0])
            assert selected_id is not None
            selected_sequence = _stored_count(journals[0][1], 1, 256)
            if len(journals) > 1 and _stored_count(journals[1][1], 1, 256) >= selected_sequence:
                raise IntegrityViolation()
            dispatch = await self._dispatch_status(connection, ctx, selected_id)
            if (dispatch is None or dispatch['state'] != 'settled'
                    or dispatch['operation'] != 'complete_point_upsert'
                    or dispatch['owner_token'] != preparation['owner_token']
                    or dispatch['backend_epoch'] != preparation['backend_epoch']):
                raise IntegrityViolation()
            return MappingProxyType({'preparation': MappingProxyType(preparation), 'dispatch': dispatch})
        return await self._run(ctx, deadline, read)

    async def _ensure(self, connection: SessionConnection, table: str, values: dict[str, Any],
                      keys: tuple[str, ...], json_columns: tuple[str, ...] = ()) -> None:
        columns = tuple(values)
        selection = ','.join(key+'::text' if key in ('point_id','owner_token') else key for key in columns)
        select = 'SELECT '+selection+' FROM cragkit_qdrant.'+table+' WHERE '+' AND '.join(key+'=%s' for key in keys)
        key_values = tuple(values[key] for key in keys)
        expected = [tuple(values[key] for key in columns)]
        existing = await self._query(connection,select,key_values)
        if existing:
            if existing != expected:
                raise IntegrityViolation()
            return
        placeholders = ','.join('%s::jsonb' if key in json_columns else '%s' for key in columns)
        params = tuple(_json(values[key]) if key in json_columns and values[key] is not None else values[key] for key in columns)
        await connection.execute('INSERT INTO cragkit_qdrant.'+table+' ('+','.join(columns)+') VALUES ('+placeholders+') ON CONFLICT DO NOTHING', params)
        rows = await self._query(connection,select,key_values)
        if rows != expected:
            raise IntegrityViolation()

    async def _document(self, connection: SessionConnection, ctx: WriterContext, *, check_revision: bool = True,
                        lock: bool = True) -> dict[str, Any]:
        columns = ('active_generation_id','authorization_revision','mutation_epoch','principal_ids','grant_ids','language','kind','tag','tombstoned')
        rows = await self._query(connection, 'SELECT '+','.join(columns)+' FROM cragkit_qdrant.documents WHERE '+_DOC+(' FOR UPDATE' if lock else ''), _doc(ctx))
        if len(rows) != 1:
            raise UnauthorizedScope()
        row = dict(zip(columns, rows[0], strict=True))
        if check_revision and row['authorization_revision'] != ctx.scope.authorization_revision:
            raise UnauthorizedScope()
        return row

    async def stage(self, plan: StagePlan, scope: object, *, owner_token: object, deadline: float) -> Mapping[str, Any]:
        data, ctx = bind_stage(plan, scope, owner_token, self.config)
        m, intent = data.manifest, data.intent
        async def stage(connection: SessionConnection) -> Mapping[str, Any]:
            base = dict(zip(('tenant_id','collection','document_id'), _doc(ctx), strict=True))
            prior_intent = await self._inspect(connection,ctx)
            prior_document = await self._query(connection,'SELECT document_id FROM cragkit_qdrant.documents WHERE '+_DOC,_doc(ctx))
            if intent.initial_authorization is not None and prior_document and prior_intent is None:
                raise IntegrityViolation()
            await self._ensure(connection, 'publication_intents', {**base, 'intent_id':ctx.intent_id,
                'instance_id':self.instance_id, 'action':'stage','payload_bytes':data.intent_encoding.encoded_bytes,
                'payload_sha256':data.intent_encoding.sha256,'manifest_bytes':data.manifest_encoding.encoded_bytes,
                'manifest_sha256':data.manifest_encoding.sha256,'revision_id':m.revision_id,'generation_id':m.generation_id,
                'expected_active_generation_id':intent.expected_active_generation_id,
                'expected_authorization_revision':intent.expected_authorization_revision,
                'expected_mutation_epoch':intent.expected_mutation_epoch}, ('tenant_id','collection','document_id','intent_id'))
            if intent.initial_authorization is not None:
                auth = intent.initial_authorization
                created = await self._query(connection,'INSERT INTO cragkit_qdrant.documents (tenant_id,collection,document_id,principal_ids,grant_ids,authorization_revision,mutation_epoch,language,kind,tag,tombstoned) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING document_id',
                    (*_doc(ctx),_acl(auth.principal_ids),_acl(auth.grant_ids),auth.authorization_revision,
                     intent.expected_mutation_epoch,auth.language,auth.kind,auth.tag,auth.tombstoned))
                if not created and prior_intent is None:
                    raise IntegrityViolation()
            document = await self._document(connection, ctx)
            conflicting=await self._query(connection,'SELECT intent_id FROM cragkit_qdrant.publication_intents WHERE '+_DOC+
                " AND action='stage' AND revision_id=%s AND generation_id=%s AND (manifest_sha256 IS DISTINCT FROM %s OR manifest_bytes IS DISTINCT FROM %s) LIMIT 1",
                (*_doc(ctx),m.revision_id,m.generation_id,data.manifest_encoding.sha256,data.manifest_encoding.encoded_bytes))
            if conflicting:
                raise IntegrityViolation()
            if intent.initial_authorization is not None and not prior_document:
                initial = intent.initial_authorization
                if (document['principal_ids'] != _acl(initial.principal_ids) or document['grant_ids'] != _acl(initial.grant_ids)
                    or any(document[key] != getattr(initial,key) for key in ('language','kind','tag','tombstoned'))):
                    raise IntegrityViolation()
            if document['tombstoned'] or document['mutation_epoch'] != intent.expected_mutation_epoch or document['active_generation_id'] != intent.expected_active_generation_id:
                existing = await self._inspect(connection, ctx)
                if existing is None or existing['state'] != 'published' or document['tombstoned']:
                    raise IntegrityViolation()
            await self._ensure(connection, 'document_revisions', {**base,'revision_id':m.revision_id,
                'canonical_utf8':data.source,'source_sha256':m.source_sha256,'source_locator':m.source_locator,'parser_id':m.parser_id},
                ('tenant_id','collection','document_id','revision_id'))
            await self._ensure(connection, 'generations', {**base,'revision_id':m.revision_id,'generation_id':m.generation_id,
                'backend_namespace':m.backend_namespace,'physical_collection':m.physical_collection,
                'collection_incarnation':m.collection_incarnation,'chunker_profile':m.chunker_profile,
                'dense_profile_id':m.dense_profile.profile_id,'sparse_profile_id':m.sparse_profile.profile_id if m.sparse_profile else '',
                'dense_profile':m.dense_profile.model_dump(),'sparse_profile':m.sparse_profile.model_dump() if m.sparse_profile else None,
                'expected_member_count':len(m.members)}, ('tenant_id','collection','document_id','generation_id'), ('dense_profile','sparse_profile'))
            for member, dense, sparse in zip(m.members, data.dense, data.sparse, strict=True):
                member_base = {**base,'revision_id':m.revision_id,'generation_id':m.generation_id,'chunk_id':member.chunk_id}
                await self._ensure(connection, 'members', {**member_base,'point_id':member.point_id,'start_byte':member.start_byte,
                    'end_byte':member.end_byte,'source_sha256':m.source_sha256,'text_sha256':member.text_sha256,
                    'excerpt_utf8':data.source[member.start_byte:member.end_byte]}, tuple(member_base))
                physical = {'backend_namespace':m.backend_namespace,'physical_collection':m.physical_collection,
                    'collection_incarnation':m.collection_incarnation,'point_id':member.point_id}
                await self._ensure(connection, 'point_claims', {**physical,'instance_id':self.instance_id,**member_base,
                    'source_sha256':m.source_sha256,'text_sha256':member.text_sha256,'start_byte':member.start_byte,'end_byte':member.end_byte,
                    'dense_profile':m.dense_profile.model_dump(),'sparse_profile':m.sparse_profile.model_dump() if m.sparse_profile else None,
                    'dense_input_sha256':dense.input_sha256,'sparse_input_sha256':sparse.input_sha256 if sparse else None},
                    tuple(physical), ('dense_profile','sparse_profile'))
                await self._ensure(connection, 'vector_replays', {**member_base,**physical,'dense_blob':dense.blob,
                    'dense_blob_sha256':dense.blob_sha256,'sparse_blob':sparse.blob if sparse else None,
                    'sparse_blob_sha256':sparse.blob_sha256 if sparse else None}, tuple(member_base))
            result = await self._inspect(connection, ctx)
            if result is None:
                raise IntegrityViolation()
            return result
        return await self._run(ctx, deadline, stage)

    async def _lock(self, connection: SessionConnection, ctx: WriterContext, *, acquire: bool = False,
                    check_revision: bool = True, validate_owner: bool = True) -> tuple[int, dict[str, Any]]:
        backend = await self._query(connection, 'SELECT epoch,state,backend_namespace FROM cragkit_qdrant.backend_instances WHERE instance_id=%s FOR SHARE', (self.instance_id,))
        if len(backend) != 1 or backend[0][1] != 'open' or backend[0][2] != self.config.backend_namespace:
            raise ProviderUnavailable()
        epoch = cast(int, backend[0][0])
        owners = await self._query(connection, 'SELECT owner_token::text,intent_id,backend_epoch FROM cragkit_qdrant.document_owners WHERE '+_DOC+' FOR UPDATE', _doc(ctx))
        if not acquire and validate_owner and owners != [(ctx.owner_token,ctx.intent_id,epoch)]:
            raise ProviderUnavailable()
        document = await self._document(connection, ctx, check_revision=check_revision)
        return epoch, document

    async def acquire_owner(self, value: object, *, deadline: float) -> Mapping[str, Any]:
        ctx = context(value)
        async def acquire(connection: SessionConnection) -> Mapping[str, Any]:
            epoch, document = await self._lock(connection, ctx, acquire=True)
            await self._operation_fences(connection,ctx,document)
            pending = await self._query(connection, 'SELECT dispatch_id FROM cragkit_qdrant.dispatch_journal WHERE '+_DOC+" AND state<>'settled' LIMIT 1", _doc(ctx))
            if pending:
                raise ProviderUnavailable()
            await connection.execute('INSERT INTO cragkit_qdrant.document_owners (tenant_id,collection,document_id,instance_id,intent_id,owner_token,backend_epoch) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (tenant_id,collection,document_id) DO UPDATE SET intent_id=EXCLUDED.intent_id,owner_token=EXCLUDED.owner_token,backend_epoch=EXCLUDED.backend_epoch',
                (*_doc(ctx),self.instance_id,ctx.intent_id,ctx.owner_token,epoch))
            await connection.execute("UPDATE cragkit_qdrant.publication_intents SET state='writing' WHERE "+_INTENT+" AND state IN ('staged','authority_committed')", _key(ctx))
            result = await self._inspect(connection, ctx)
            if result is None:
                raise IntegrityViolation()
            return MappingProxyType({'owner_token':ctx.owner_token,'backend_epoch':epoch})
        return await self._run(ctx, deadline, acquire)

    async def _operation_fences(self, connection: SessionConnection, ctx: WriterContext,
                                document: dict[str, Any], operation: str | None = None) -> tuple[Any, ...]:
        rows = await self._query(connection,'SELECT action,expected_authorization_revision,expected_mutation_epoch,expected_active_generation_id,generation_id,revision_id,authority_committed,payload_bytes,payload_sha256,state FROM cragkit_qdrant.publication_intents WHERE '+_INTENT,_key(ctx))
        if len(rows) != 1 or len(rows[0]) != 10:
            raise IntegrityViolation()
        row = rows[0]
        revision, epoch = row[1],row[2]
        if row[0] in ('update_authorization','tombstone') and row[6]:
            raw = row[7]
            if type(raw) is not bytes or len(raw)>1048576 or hashlib.sha256(raw).hexdigest()!=row[8]:
                raise IntegrityViolation()
            try:
                payload = json.loads(raw.decode('utf-8'))
                revision = payload[8][0]
                if type(revision) is not str:
                    raise ValueError()
            except (ValueError,TypeError,IndexError,KeyError,UnicodeError):
                raise IntegrityViolation() from None
            epoch += 1
        if (document['authorization_revision'],document['mutation_epoch']) != (revision,epoch):
            raise IntegrityViolation()
        if row[0]=='stage' and (document['active_generation_id']!=row[3] or document['tombstoned']):
            raise IntegrityViolation()
        if row[0] in ('tombstone','purge') and (not document['tombstoned'] or operation=='complete_point_upsert'):
            raise IntegrityViolation()
        return row

    async def close(self) -> None:
        self._closed = True
        task = self._active
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            try:
                async with asyncio.timeout(self.resource.config.release_timeout * 2):
                    await asyncio.shield(task)
            except (asyncio.CancelledError, TimeoutError, CragkitError):
                pass

    async def reserve_dispatch(self, value: object, reservation: object, *, deadline: float) -> Mapping[str, Any]:
        ctx = context(value)
        if type(reservation) is not dict or any(type(key) is not str for key in reservation) or set(reservation) != {'dispatch_id','sequence','credential_generation','operation','point_ids'}:
            raise InvalidRequest()
        record = cast(dict[str, Any], reservation)
        dispatch_id = _identity(record['dispatch_id'])
        credential = _identity(record['credential_generation'])
        number = record['sequence']
        if type(number) is not int or not 1 <= number <= 256:
            raise InvalidRequest()
        operation = record['operation']
        if type(operation) is not str or operation not in ('complete_point_upsert','delete_points'):
            raise InvalidRequest()
        ids = sequence(record['point_ids'], 8)
        if any(type(item) is not str or re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',item) is None for item in ids) or len(set(ids)) != len(ids):
            raise InvalidRequest()
        ids = tuple(sorted(ids))
        async def reserve(connection: SessionConnection) -> Mapping[str, Any]:
            epoch, document = await self._lock(connection, ctx)
            intent = await self._operation_fences(connection,ctx,document,operation)
            if operation=='delete_points' and (intent[0]!='purge' or not document['tombstoned']):
                raise InvalidRequest()
            if document['tombstoned'] and operation != 'delete_points':
                raise UnauthorizedScope()
            points: list[dict[str, Any]] = []
            for point in ids:
                rows = await self._query(connection, """SELECT p.revision_id,p.generation_id,p.chunk_id,p.start_byte,p.end_byte,
 p.source_sha256,p.text_sha256,p.dense_profile,p.sparse_profile,p.dense_input_sha256,p.sparse_input_sha256,
 r.dense_blob,r.dense_blob_sha256,r.sparse_blob,r.sparse_blob_sha256
 FROM cragkit_qdrant.point_claims p JOIN cragkit_qdrant.vector_replays r
 ON r.tenant_id=p.tenant_id AND r.collection=p.collection AND r.document_id=p.document_id
 AND r.revision_id=p.revision_id AND r.generation_id=p.generation_id AND r.chunk_id=p.chunk_id
 AND r.backend_namespace=p.backend_namespace AND r.physical_collection=p.physical_collection
 AND r.collection_incarnation=p.collection_incarnation AND r.point_id=p.point_id
 WHERE p.tenant_id=%s AND p.collection=%s AND p.document_id=%s AND p.instance_id=%s
 AND p.backend_namespace=%s AND p.physical_collection=%s AND p.collection_incarnation=%s AND p.point_id=%s LIMIT 2""",
                    (*_doc(ctx),self.instance_id,self.config.backend_namespace,self.config.physical_collection,self.config.collection_incarnation,point))
                if len(rows) != 1 or len(rows[0]) != 15:
                    raise IntegrityViolation()
                row = rows[0]
                if intent[0]=='stage' and (row[0],row[1]) != (intent[5],intent[4]):
                    raise IntegrityViolation()
                identity = ('cragkit.qdrant.point.v1',self.config.backend_namespace,self.config.physical_collection,
                    self.config.collection_incarnation,ctx.scope.tenant_id,ctx.collection,ctx.document_id,
                    row[0],row[1],row[2],self.config.dense_profile.profile_id,
                    self.config.sparse_profile.profile_id if self.config.sparse_profile else '')
                if point_id(identity) != point:
                    raise IntegrityViolation()
                if row[7] != self.config.dense_profile.model_dump() or row[8] != (self.config.sparse_profile.model_dump() if self.config.sparse_profile else None):
                    raise IntegrityViolation()
                dense = restore_dense_replay(row[11],row[12],row[9],row[7])
                vectors: dict[str, Any] = {'dense': list(dense.values)}
                if row[8] is not None:
                    sparse = restore_sparse_replay(row[13],row[14],row[10],row[8])
                    vectors['sparse'] = {'indices':list(sparse.indices),'values':list(sparse.values)}
                elif row[13] is not None or row[14] is not None or row[10] is not None:
                    raise IntegrityViolation()
                payload = {'backend_namespace':self.config.backend_namespace,'physical_collection':self.config.physical_collection,
                    'collection_incarnation':self.config.collection_incarnation,'tenant_id':ctx.scope.tenant_id,
                    'collection':ctx.collection,'document_id':ctx.document_id,'revision_id':row[0],
                    'generation_id':row[1],'chunk_id':row[2],'start_byte':row[3],'end_byte':row[4],
                    'source_sha256':row[5],'text_sha256':row[6],'dense_profile':row[7],'sparse_profile':row[8],
                    'dense_profile_id':self.config.dense_profile.profile_id,
                    'sparse_profile_id':self.config.sparse_profile.profile_id if self.config.sparse_profile else '',
                    'authorization_revision':document['authorization_revision'],
                    'principal_ids':document['principal_ids'],'grant_ids':document['grant_ids']}
                for field in ('language','kind','tag'):
                    if document[field] is not None:
                        payload[field] = document[field]
                points.append({'id':point,'vector':vectors,'payload':payload})
            body = (_complete_point_request(points) if operation == 'complete_point_upsert'
                    else _json({'points':list(ids)}).encode('utf-8'))
            if len(body) > 1048576:
                raise InvalidRequest()
            digest = hashlib.sha256(body).hexdigest()
            journal = {**dict(zip(('tenant_id','collection','document_id'),_doc(ctx),strict=True)),
                'intent_id':ctx.intent_id,'dispatch_id':dispatch_id,'instance_id':self.instance_id,'sequence':number,
                'owner_token':ctx.owner_token,'backend_epoch':epoch,'credential_generation':credential,
                'operation':operation,'request_bytes':body,'request_sha256':digest}
            existing = await self._query(connection, 'SELECT request_bytes,request_sha256,state,sequence,credential_generation,operation,owner_token::text,backend_epoch FROM cragkit_qdrant.dispatch_journal WHERE '+_INTENT+' AND dispatch_id=%s',(*_key(ctx),dispatch_id))
            if existing:
                if len(existing) != 1 or existing[0][:2] != (body,digest) or existing[0][3:] != (number,credential,operation,ctx.owner_token,epoch):
                    raise IntegrityViolation()
                stored_points = await self._query(connection, 'SELECT point_id::text FROM cragkit_qdrant.dispatch_points WHERE '+_INTENT+' AND dispatch_id=%s ORDER BY point_id::text',(*_key(ctx),dispatch_id))
                if [row[0] for row in stored_points] != sorted(ids):
                    raise IntegrityViolation()
                state = existing[0][2]
            else:
                await self._require_settled(connection,ctx)
                await self._ensure(connection,'dispatch_journal',journal,('tenant_id','collection','document_id','intent_id','dispatch_id'))
                for point in ids:
                    await self._ensure(connection,'dispatch_points',{**dict(zip(('tenant_id','collection','document_id'),_doc(ctx),strict=True)),
                        'intent_id':ctx.intent_id,'dispatch_id':dispatch_id,'backend_namespace':self.config.backend_namespace,
                        'physical_collection':self.config.physical_collection,'collection_incarnation':self.config.collection_incarnation,
                        'point_id':point},('tenant_id','collection','document_id','intent_id','dispatch_id','point_id'))
                state = 'reserved'
            return MappingProxyType({'dispatch_id':dispatch_id,'request_bytes':body,'request_sha256':digest,
                                     'point_ids':ids,'operation':operation,'state':state})
        return await self._run(ctx,deadline,reserve)

    async def _dispatch_state(self, value: object, dispatch_id: object, state: str,
                              digest: str | None, deadline: float) -> None:
        ctx = context(value)
        identity = _identity(dispatch_id)
        async def update(connection: SessionConnection) -> None:
            _,document = await self._lock(connection,ctx,check_revision=state == 'dispatched')
            if state == 'dispatched':
                await self._operation_fences(connection,ctx,document)
            rows = await self._query(connection, 'SELECT state,completion_sha256,owner_token::text FROM cragkit_qdrant.dispatch_journal WHERE '+_INTENT+' AND dispatch_id=%s FOR UPDATE',(*_key(ctx),identity))
            if len(rows) != 1 or rows[0][2] != ctx.owner_token:
                raise IntegrityViolation()
            if rows[0][:2] == (state,digest):
                return
            if rows[0][0] == 'unknown' and state in ('dispatched', 'settled'):
                raise ProviderUnavailable()
            if rows[0][0] == 'settled' or (state == 'dispatched' and rows[0][0] != 'reserved'):
                raise InvalidRequest()
            await connection.execute('UPDATE cragkit_qdrant.dispatch_journal SET state=%s,completion_sha256=%s WHERE '+_INTENT+' AND dispatch_id=%s',(state,digest,*_key(ctx),identity))
        await self._run(ctx,deadline,update)

    async def mark_dispatched(self, value: object, dispatch_id: object, *, deadline: float) -> None:
        await self._dispatch_state(value,dispatch_id,'dispatched',None,deadline)

    async def mark_unknown(self, value: object, dispatch_id: object, *, deadline: float) -> None:
        await self._dispatch_state(value,dispatch_id,'unknown',None,deadline)

    async def settle_dispatch(self, value: object, dispatch_id: object, completion_sha256: object, *, deadline: float) -> None:
        await self._dispatch_state(value,dispatch_id,'settled',_digest(completion_sha256),deadline)

    async def _fences(self, connection: SessionConnection, ctx: WriterContext) -> tuple[int, dict[str, Any], tuple[Any, ...], str | None]:
        rows = await self._query(connection, 'SELECT expected_authorization_revision,expected_mutation_epoch,expected_active_generation_id,manifest_sha256,generation_id,revision_id,state FROM cragkit_qdrant.publication_intents WHERE '+_INTENT,_key(ctx))
        if len(rows) != 1:
            raise IntegrityViolation()
        intent = rows[0]
        def classify(document: dict[str, Any]) -> str | None:
            if document['tombstoned'] or intent[:2] != (document['authorization_revision'],document['mutation_epoch']):
                return 'denied'
            if intent[2] != document['active_generation_id']:
                return 'conflict'
            if document['authorization_revision']!=ctx.scope.authorization_revision:
                raise UnauthorizedScope()
            return None
        document=await self._document(connection,ctx,check_revision=False,lock=False)
        failure=classify(document)
        if failure is not None:
            return 0,document,intent,failure
        epoch,document=await self._lock(connection,ctx,check_revision=False,validate_owner=False)
        failure=classify(document)
        if failure is None:
            owners=await self._query(connection,'SELECT owner_token::text,intent_id,backend_epoch FROM cragkit_qdrant.document_owners WHERE '+_DOC,_doc(ctx))
            if owners!=[(ctx.owner_token,ctx.intent_id,epoch)]:
                raise ProviderUnavailable()
        return epoch,document,intent,failure

    async def _outcome(self, connection: SessionConnection, ctx: WriterContext, state: str) -> Mapping[str, Any]:
        await connection.execute('UPDATE cragkit_qdrant.publication_intents SET state=%s WHERE '+_INTENT,(state,*_key(ctx)))
        result=await self._inspect(connection,ctx)
        if result is None:
            raise IntegrityViolation()
        return result

    async def _require_settled(self, connection: SessionConnection, ctx: WriterContext) -> None:
        pending=await self._query(connection,'SELECT dispatch_id FROM cragkit_qdrant.dispatch_journal WHERE '+_DOC+" AND state<>'settled' LIMIT 1",_doc(ctx))
        if pending:
            raise ProviderUnavailable()

    async def _load_stage(self, connection: SessionConnection, ctx: WriterContext) -> StagePlan:
        """Reconstruct the entire immutable graph, rather than trust row counts."""
        intents = await self._query(connection,'SELECT revision_id,generation_id,manifest_bytes,manifest_sha256 FROM cragkit_qdrant.publication_intents WHERE '+_INTENT+" AND action='stage'",_key(ctx))
        if len(intents)!=1 or len(intents[0])!=4:
            raise IntegrityViolation()
        revision,generation,manifest_bytes,manifest_sha = intents[0]
        if type(manifest_bytes) is not bytes or not 1<=len(manifest_bytes)<=1048576 or hashlib.sha256(manifest_bytes).hexdigest()!=manifest_sha:
            raise IntegrityViolation()
        rows = await self._query(connection,"""SELECT r.canonical_utf8,r.source_sha256,r.source_locator,r.parser_id,
 g.backend_namespace,g.physical_collection,g.collection_incarnation,g.chunker_profile,
 g.dense_profile,g.sparse_profile,g.expected_member_count
 FROM cragkit_qdrant.generations g JOIN cragkit_qdrant.document_revisions r
 ON r.tenant_id=g.tenant_id AND r.collection=g.collection AND r.document_id=g.document_id AND r.revision_id=g.revision_id
 WHERE g.tenant_id=%s AND g.collection=%s AND g.document_id=%s AND g.revision_id=%s AND g.generation_id=%s LIMIT 2""",
            (*_doc(ctx),revision,generation))
        if len(rows)!=1 or len(rows[0])!=11:
            raise IntegrityViolation()
        row = rows[0]
        source = row[0]
        if type(source) is not bytes or not 1<=len(source)<=16777216:
            raise IntegrityViolation()
        try:
            canonical = source.decode('utf-8',errors='strict')
        except UnicodeError:
            raise IntegrityViolation() from None
        if (row[4:7]!=(self.config.backend_namespace,self.config.physical_collection,self.config.collection_incarnation)
            or row[8]!=self.config.dense_profile.model_dump()
            or row[9]!=(self.config.sparse_profile.model_dump() if self.config.sparse_profile else None)
            or type(row[10]) is not int or not 1<=row[10]<=64):
            raise IntegrityViolation()
        raw_members=await self._query(connection,'SELECT chunk_id,point_id::text FROM cragkit_qdrant.members WHERE '+_DOC+' AND revision_id=%s AND generation_id=%s LIMIT 65',(*_doc(ctx),revision,generation))
        if (len(raw_members)!=row[10] or any(len(item)!=2 or any(type(value) is not str for value in item) for item in raw_members)
            or len(set(raw_members))!=len(raw_members)):
            raise IntegrityViolation()
        raw_claims=await self._query(connection,'SELECT chunk_id,point_id::text,instance_id,backend_namespace,physical_collection,collection_incarnation FROM cragkit_qdrant.point_claims WHERE '+_DOC+' AND revision_id=%s AND generation_id=%s LIMIT 65',(*_doc(ctx),revision,generation))
        raw_replays=await self._query(connection,'SELECT chunk_id,point_id::text,backend_namespace,physical_collection,collection_incarnation FROM cragkit_qdrant.vector_replays WHERE '+_DOC+' AND revision_id=%s AND generation_id=%s LIMIT 65',(*_doc(ctx),revision,generation))
        for records,width,physical in ((raw_claims,6,(self.instance_id,*row[4:7])),(raw_replays,5,row[4:7])):
            if (len(records)!=row[10] or any(len(item)!=width or any(type(value) is not str for value in item) or item[2:]!=physical for item in records)
                or {item[:2] for item in records}!=set(raw_members)):
                raise IntegrityViolation()
        members = await self._query(connection,"""SELECT m.chunk_id,m.point_id::text,m.start_byte,m.end_byte,
 m.source_sha256,m.text_sha256,m.excerpt_utf8,p.dense_input_sha256,p.sparse_input_sha256,
 v.dense_blob,v.dense_blob_sha256,v.sparse_blob,v.sparse_blob_sha256,p.dense_profile,p.sparse_profile
 FROM cragkit_qdrant.members m JOIN cragkit_qdrant.point_claims p
 ON p.tenant_id=m.tenant_id AND p.collection=m.collection AND p.document_id=m.document_id
 AND p.revision_id=m.revision_id AND p.generation_id=m.generation_id AND p.chunk_id=m.chunk_id AND p.point_id=m.point_id
 AND p.start_byte=m.start_byte AND p.end_byte=m.end_byte AND p.source_sha256=m.source_sha256 AND p.text_sha256=m.text_sha256
 JOIN cragkit_qdrant.vector_replays v ON v.tenant_id=p.tenant_id AND v.collection=p.collection AND v.document_id=p.document_id
 AND v.revision_id=p.revision_id AND v.generation_id=p.generation_id AND v.chunk_id=p.chunk_id AND v.point_id=p.point_id
 AND v.backend_namespace=p.backend_namespace AND v.physical_collection=p.physical_collection AND v.collection_incarnation=p.collection_incarnation
 WHERE m.tenant_id=%s AND m.collection=%s AND m.document_id=%s AND m.revision_id=%s AND m.generation_id=%s
 AND p.instance_id=%s AND p.backend_namespace=%s AND p.physical_collection=%s AND p.collection_incarnation=%s LIMIT 65""",
            (*_doc(ctx),revision,generation,self.instance_id,self.config.backend_namespace,self.config.physical_collection,self.config.collection_incarnation))
        if len(members)!=row[10]:
            raise IntegrityViolation()
        metadata_members=[]
        dense_replays: list[_ReplayResult]=[]
        sparse_replays: list[_ReplayResult | None]=[]
        for member in members:
            if len(member)!=15 or type(member[2]) is not int or type(member[3]) is not int:
                raise IntegrityViolation()
            if (not 0<=member[2]<member[3]<=len(source) or member[3]-member[2]>32768
                or type(member[6]) is not bytes or member[6]!=source[member[2]:member[3]]
                or member[4]!=row[1] or member[13:15]!=(row[8],row[9])):
                raise IntegrityViolation()
            dense=restore_dense_replay(member[9],member[10],member[7],row[8])
            dense_replays.append(_ReplayResult(member[9],member[10],member[7],dense))
            if row[9] is not None:
                sparse=restore_sparse_replay(member[11],member[12],member[8],row[9])
                sparse_replays.append(_ReplayResult(member[11],member[12],member[8],sparse))
            elif any(member[index] is not None for index in (8,11,12)):
                raise IntegrityViolation()
            else:
                sparse_replays.append(None)
            metadata_members.append({'chunk_id':member[0],'point_id':member[1],'start_byte':member[2],
                'end_byte':member[3],'text_sha256':member[5],'dense_input_sha256':member[7],
                'sparse_input_sha256':member[8]})
        record={'tenant_id':ctx.scope.tenant_id,'collection':ctx.collection,'document_id':ctx.document_id,
            'revision_id':revision,'generation_id':generation,'source_sha256':row[1],'source_bytes':len(source),
            'source_locator':row[2],'parser_id':row[3],'backend_namespace':row[4],'physical_collection':row[5],
            'collection_incarnation':row[6],'chunker_profile':row[7],'dense_profile':row[8],
            'sparse_profile':row[9],'members':metadata_members}
        try:
            encoded=encode_manifest(record,canonical)
        except (InvalidRequest,UnsupportedCapability):
            raise IntegrityViolation() from None
        if encoded.encoded_bytes!=manifest_bytes or encoded.sha256!=manifest_sha:
            raise IntegrityViolation()
        rows=await self._query(connection,'SELECT payload_bytes,payload_sha256 FROM cragkit_qdrant.publication_intents WHERE '+_INTENT,_key(ctx))
        if len(rows)!=1 or len(rows[0])!=2:
            raise IntegrityViolation()
        payload_bytes,payload_sha=rows[0]
        if type(payload_bytes) is not bytes or not 1<=len(payload_bytes)<=1048576 or hashlib.sha256(payload_bytes).hexdigest()!=payload_sha:
            raise IntegrityViolation()
        try:
            payload=json.loads(payload_bytes.decode('utf-8',errors='strict'))
            if type(payload) is not list or len(payload)!=11 or payload[:2]!=['cragkit.qdrant.intent.v1','stage']:
                raise ValueError()
            initial=payload[10]
            if initial is not None:
                if type(initial) is not list or len(initial)!=7 or initial[6] not in ('true','false'):
                    raise ValueError()
                initial={'authorization_revision':initial[0],'principal_ids':initial[1],'grant_ids':initial[2],
                    'language':initial[3],'kind':initial[4],'tag':initial[5],'tombstoned':initial[6]=='true'}
            intent_record={'intent_id':payload[2],'tenant_id':payload[3],'collection':payload[4],
                'document_id':payload[5],'manifest_sha256':payload[6],'expected_active_generation_id':payload[7],
                'expected_authorization_revision':payload[8],'expected_mutation_epoch':int(payload[9]),
                'initial_authorization':initial}
            intent_encoded=encode_stage_intent(intent_record)
            intent=_parse(_Stage,intent_record)
            if (intent_encoded.encoded_bytes!=payload_bytes or intent_encoded.sha256!=payload_sha
                or (intent.tenant_id,intent.collection,intent.document_id,intent.intent_id)!=(*_doc(ctx),ctx.intent_id)
                or intent.manifest_sha256!=encoded.sha256):
                raise IntegrityViolation()
        except (ValueError,TypeError,IndexError,KeyError,UnicodeError,InvalidRequest):
            raise IntegrityViolation() from None
        return issue_stage(StageData(_parse(_Manifest,record),intent,source,encoded,intent_encoded,
                                    tuple(dense_replays),tuple(sparse_replays)))

    async def load_stage(self, value: object, *, deadline: float) -> StagePlan:
        ctx=context(value)
        async def load(connection: SessionConnection) -> StagePlan:
            await self._document(connection,ctx)
            return await self._load_stage(connection,ctx)
        return await self._run(ctx,deadline,load)

    def _projection_points(self, graph: StageData, document: Mapping[str, Any]) -> tuple[ExpectedPoint, ...]:
        manifest = graph.manifest
        points = []
        for member, dense, sparse in zip(manifest.members, graph.dense, graph.sparse, strict=True):
            payload = {
                'backend_namespace': manifest.backend_namespace,
                'physical_collection': manifest.physical_collection,
                'collection_incarnation': manifest.collection_incarnation,
                'tenant_id': manifest.tenant_id, 'collection': manifest.collection,
                'document_id': manifest.document_id, 'revision_id': manifest.revision_id,
                'generation_id': manifest.generation_id, 'chunk_id': member.chunk_id,
                'start_byte': member.start_byte, 'end_byte': member.end_byte,
                'source_sha256': manifest.source_sha256, 'text_sha256': member.text_sha256,
                'dense_profile_id': manifest.dense_profile.profile_id,
                'dense_profile': manifest.dense_profile.model_dump(),
                'sparse_profile_id': manifest.sparse_profile.profile_id if manifest.sparse_profile else '',
                'sparse_profile': manifest.sparse_profile.model_dump() if manifest.sparse_profile else None,
                'authorization_revision': document['authorization_revision'],
                'principal_ids': document['principal_ids'], 'grant_ids': document['grant_ids'],
            }
            for key in ('language', 'kind', 'tag'):
                if document[key] is not None:
                    payload[key] = document[key]
            points.append(ExpectedPoint(member.point_id, parse_model(CandidatePayload, payload),
                cast(_DenseVector, dense.encoded),
                cast(_SparseVector, sparse.encoded) if sparse is not None else None))
        return tuple(points)

    async def project_publication(self, value: object, binding: object, *,
                                  deadline: float) -> PublicationProjection:
        ctx = context(value)
        attempt = ordinary_binding(binding)
        if (attempt['instance_id'] != self.instance_id or attempt['intent_id'] != ctx.intent_id
                or attempt['owner_token'] != ctx.owner_token):
            raise UnsupportedCapability()

        async def project(connection: SessionConnection) -> PublicationProjection:
            rows = await self._query(connection,
                'SELECT backend_namespace,storage_identity,supervisor_id,epoch,state,recovery_id '
                'FROM cragkit_qdrant.backend_instances WHERE instance_id=%s FOR SHARE',
                (self.instance_id,))
            if not rows:
                raise ProviderUnavailable()
            if (len(rows) != 1 or len(rows[0]) != 6
                    or any(type(item) is not str for item in rows[0][:3])
                    or type(rows[0][3]) is not int or type(rows[0][4]) is not str
                    or rows[0][5] is not None and type(rows[0][5]) is not str):
                raise IntegrityViolation()
            if rows[0][:3] != (self.config.backend_namespace, attempt['storage_identity'],
                                attempt['supervisor_id']):
                raise IntegrityViolation()
            if rows[0][3:] != (attempt['epoch'], 'open', None):
                raise ProviderUnavailable()
            owners = await self._query(connection,
                'SELECT owner_token::text,intent_id,backend_epoch,instance_id '
                'FROM cragkit_qdrant.document_owners WHERE ' + _DOC + ' FOR UPDATE', _doc(ctx))
            if owners != [(ctx.owner_token, ctx.intent_id, attempt['epoch'], self.instance_id)]:
                raise ProviderUnavailable()
            document = await self._document(connection, ctx)
            if document['tombstoned']:
                raise UnauthorizedScope()
            await self._require_settled(connection, ctx)
            plan = await self._load_stage(connection, ctx)
            graph = stage_data(plan)
            authority = MappingProxyType({
                key: tuple(document[key]) if key in ('principal_ids', 'grant_ids') else document[key]
                for key in ('principal_ids', 'grant_ids', 'language', 'kind', 'tag')
            })
            return finalize_publication_projection(self, {
                'context': ctx, 'attempt_binding': attempt, 'manifest_sha256': plan.manifest_sha256,
                'revision_id': graph.manifest.revision_id, 'generation_id': graph.manifest.generation_id,
                'authorization_revision': document['authorization_revision'],
                'mutation_epoch': document['mutation_epoch'],
                'active_generation_id': document['active_generation_id'], 'tombstoned': False,
                'points': self._projection_points(graph, document), 'authority': authority,
            })
        return await self._run(ctx, deadline, project)

    async def validate_publication_projection(self, projection: object, *, deadline: float) -> None:
        original = publication_projection_data(projection, self)
        fresh = await self.project_publication(original['context'], dict(original['attempt_binding']),
                                               deadline=deadline)
        current = publication_projection_data(fresh, self)
        if any(original[key] != current[key] for key in
               ('manifest_sha256', 'revision_id', 'generation_id', 'point_ids')):
            raise IntegrityViolation()
        for expected, observed in zip(original['points'], current['points'], strict=True):
            if (expected.dense.input_sha256 != observed.dense.input_sha256
                    or (expected.sparse.input_sha256 if expected.sparse else None)
                    != (observed.sparse.input_sha256 if observed.sparse else None)
                    or any(getattr(expected.payload, key) != getattr(observed.payload, key)
                           for key in IMMUTABLE_FIELDS)):
                raise IntegrityViolation()
        if (original['witness'] != current['witness']
                or tuple(point.payload.model_dump(mode='json') for point in original['points'])
                != tuple(point.payload.model_dump(mode='json') for point in current['points'])):
            raise UnauthorizedScope()

    async def project_recovery_dispatch(self, authorization: object, value: object, point_ids: object,
                                        *, deadline: float) -> _RecoveryDispatchPlan:
        from ._qdrant_recovery import recovery_dispatch_authorization
        self._attestation_profile()
        auth = recovery_dispatch_authorization(authorization, self, deadline=deadline)
        ctx = context(value)
        ids = tuple(sorted(sequence(point_ids, 8)))
        if (ctx != auth['context'] or len(set(ids)) != len(ids)
                or any(type(item) is not str or re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',item) is None for item in ids)):
            raise InvalidRequest()
        physical = auth['physical_binding']
        async def project(connection: SessionConnection) -> Mapping[str, Any]:
            rows = await self._query(connection,'SELECT backend_namespace,storage_identity,supervisor_id,epoch,state,recovery_id FROM cragkit_qdrant.backend_instances WHERE instance_id=%s FOR SHARE',(self.instance_id,))
            expected = (self.config.backend_namespace,physical['storage_identity'],physical['supervisor_id'],physical['new_epoch'],'recovery_blocked',physical['recovery_id'])
            if len(rows) != 1 or len(rows[0]) != 6:
                raise ProviderUnavailable()
            if rows[0][:3] != expected[:3]:
                raise IntegrityViolation()
            if rows[0][3:] != expected[3:]:
                raise ProviderUnavailable()
            owners = await self._query(connection,'SELECT owner_token::text,intent_id,backend_epoch,instance_id FROM cragkit_qdrant.document_owners WHERE '+_DOC+' FOR UPDATE',_doc(ctx))
            if owners != [(ctx.owner_token,ctx.intent_id,physical['new_epoch'],self.instance_id)]:
                raise ProviderUnavailable()
            document = await self._document(connection,ctx)
            existing = await self._inspect(connection,ctx)
            if existing is None or existing['action'] != 'stage' or existing['state'] not in ('writing','prepared'):
                raise InvalidRequest()
            if document['tombstoned']:
                raise UnsupportedCapability()
            fences = await self._operation_fences(connection,ctx,document,'complete_point_upsert')
            plan = await self._load_stage(connection,ctx)
            graph = stage_data(plan)
            self._attestation_intent(plan,(fences[1],fences[2],fences[3],existing['manifest_sha256'],existing['generation_id'],existing['revision_id'],existing['state']),existing)
            available = {point.point_id:point for point in self._projection_points(graph,document)}
            if any(identity not in available for identity in ids):
                raise IntegrityViolation()
            points = []
            for identity in ids:
                point = available[identity]
                vector: dict[str, Any] = {'dense':list(point.dense.values)}
                if point.sparse is not None:
                    vector['sparse'] = {'indices':list(point.sparse.indices),'values':list(point.sparse.values)}
                payload=point.payload.model_dump(mode='json')
                for field in ('language','kind','tag'):
                    if payload[field] is None:
                        del payload[field]
                points.append({'id':identity,'vector':vector,'payload':payload})
            body = _complete_point_request(points)
            return MappingProxyType({**dict(auth),'point_ids':ids,'request_bytes':body,
                'request_sha256':hashlib.sha256(body).hexdigest(),'manifest_sha256':plan.manifest_sha256,
                'revision_id':graph.manifest.revision_id,'generation_id':graph.manifest.generation_id,
                'expected_active_generation_id':fences[3],'expected_authorization_revision':fences[1],
                'expected_mutation_epoch':fences[2]})
        result = await self._run(ctx,deadline,project)
        recovery_dispatch_authorization(authorization,self,deadline=deadline)
        token = _RecoveryDispatchPlan()
        _RECOVERY_PLANS[token] = (self,authorization,result)
        return token

    async def validate_recovery_dispatch(self, plan: object, authorization: object, *, deadline: float) -> None:
        original = recovery_dispatch_plan_data(plan,authorization,self,deadline=deadline)
        fresh = await self.project_recovery_dispatch(authorization,original['context'],original['point_ids'],deadline=deadline)
        current = recovery_dispatch_plan_data(fresh,authorization,self,deadline=deadline)
        if dict(current) != dict(original):
            raise UnauthorizedScope()

    async def project_stage(self,value: object,binding: object,*,deadline: float) -> ExpectedProjection:
        ctx=context(value)
        physical=physical_binding(binding)
        if physical['instance_id']!=self.instance_id:
            raise UnsupportedCapability()
        async def project(connection: SessionConnection) -> ExpectedProjection:
            rows=await self._query(connection,'SELECT backend_namespace,storage_identity,supervisor_id,epoch,state,recovery_id FROM cragkit_qdrant.backend_instances WHERE instance_id=%s FOR SHARE',(self.instance_id,))
            expected=(self.config.backend_namespace,physical['storage_identity'],physical['supervisor_id'],
                      physical['new_epoch'],'recovery_blocked',physical['recovery_id'])
            if not rows:
                raise ProviderUnavailable()
            if (len(rows)!=1 or len(rows[0])!=6 or any(type(item) is not str for item in rows[0][:3])
                or type(rows[0][3]) is not int or type(rows[0][4]) is not str
                or rows[0][5] is not None and type(rows[0][5]) is not str):
                raise IntegrityViolation()
            if rows[0][:3]!=expected[:3]:
                raise IntegrityViolation()
            if rows[0][3:]!=expected[3:]:
                raise ProviderUnavailable()
            owners=await self._query(connection,'SELECT owner_token::text,intent_id,backend_epoch,instance_id FROM cragkit_qdrant.document_owners WHERE '+_DOC+' FOR UPDATE',_doc(ctx))
            if owners!=[(ctx.owner_token,ctx.intent_id,physical['new_epoch'],self.instance_id)]:
                raise ProviderUnavailable()
            document=await self._document(connection,ctx)
            plan=await self._load_stage(connection,ctx)
            graph=stage_data(plan);manifest=graph.manifest
            points = self._projection_points(graph, document)
            authority=MappingProxyType({key:tuple(document[key]) if key in ('principal_ids','grant_ids') else document[key]
                for key in ('principal_ids','grant_ids','language','kind','tag')})
            return finalize_projection(self,{'context':ctx,'physical_binding':physical,
                'manifest_sha256':plan.manifest_sha256,'revision_id':manifest.revision_id,
                'generation_id':manifest.generation_id,'authorization_revision':document['authorization_revision'],
                'mutation_epoch':document['mutation_epoch'],'active_generation_id':document['active_generation_id'],
                'tombstoned':document['tombstoned'],'points':tuple(points),'authority':authority})
        return await self._run(ctx,deadline,project)

    async def validate_projection(self,projection: object,*,deadline: float) -> None:
        original=projection_data(projection,self)
        fresh=await self.project_stage(original['context'],dict(original['physical_binding']),deadline=deadline)
        current=projection_data(fresh,self)
        immutable=('manifest_sha256','revision_id','generation_id','point_ids')
        if any(original[key]!=current[key] for key in immutable):
            raise IntegrityViolation()
        for expected,observed in zip(original['points'],current['points'],strict=True):
            expected_seals=(expected.dense.input_sha256,expected.sparse.input_sha256 if expected.sparse else None)
            observed_seals=(observed.dense.input_sha256,observed.sparse.input_sha256 if observed.sparse else None)
            if (expected_seals!=observed_seals or any(getattr(expected.payload,key)!=getattr(observed.payload,key)
                for key in IMMUTABLE_FIELDS)):
                raise IntegrityViolation()
        if (original['witness']!=current['witness'] or
            tuple(point.payload.model_dump(mode='json') for point in original['points'])!=
            tuple(point.payload.model_dump(mode='json') for point in current['points'])):
            raise UnauthorizedScope()

    async def prepare(self, value: object, readback_sha256: object, *, deadline: float) -> Mapping[str, Any]:
        ctx = context(value)
        digest = _digest(readback_sha256)
        async def prepare(connection: SessionConnection) -> Mapping[str, Any]:
            existing=await self._inspect(connection,ctx)
            if existing is None or existing['action']!='stage':
                raise InvalidRequest()
            if existing is not None and existing['state'] in ('published','conflict','denied'):
                return existing
            epoch,document,intent,failure = await self._fences(connection,ctx)
            if failure is not None:
                return await self._outcome(connection,ctx,failure)
            await self._require_settled(connection,ctx)
            await self._load_stage(connection,ctx)
            await self._ensure(connection,'preparations',{**dict(zip(('tenant_id','collection','document_id'),_doc(ctx),strict=True)),
                'intent_id':ctx.intent_id,'instance_id':self.instance_id,'owner_token':ctx.owner_token,'backend_epoch':epoch,
                'authorization_revision':document['authorization_revision'],'mutation_epoch':document['mutation_epoch'],
                'manifest_sha256':intent[3],'readback_sha256':digest},('tenant_id','collection','document_id','intent_id'))
            await connection.execute("UPDATE cragkit_qdrant.publication_intents SET state='prepared' WHERE "+_INTENT,_key(ctx))
            result = await self._inspect(connection,ctx)
            assert result is not None
            return result
        return await self._run(ctx,deadline,prepare)

    def _attestation_profile(self) -> None:
        writer_binding(self)
        if self._closed or self._active is not None:
            raise ProviderUnavailable()
        if not self._ready:
            raise IndexNotReady()
        if self._schema_profile != 3:
            raise UnsupportedCapability()

    @staticmethod
    def _attestation_intent(plan: StagePlan, intent: tuple[Any, ...], existing: Mapping[str, Any]) -> None:
        graph = stage_data(plan)
        if len(intent) != 7:
            raise IntegrityViolation()
        if ((graph.intent.expected_authorization_revision,graph.intent.expected_mutation_epoch,
                graph.intent.expected_active_generation_id,plan.manifest_sha256,
                graph.manifest.generation_id,graph.manifest.revision_id) != intent[:6]
                or plan.payload_sha256 != existing['payload_sha256']
                or plan.manifest_sha256 != existing['manifest_sha256']):
            raise IntegrityViolation()

    async def _attestation_material(self, connection: SessionConnection, ctx: WriterContext,
                                    epoch: int, document: Mapping[str, Any],
                                    intent: tuple[Any, ...]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        rows = await self._query(connection,
            'SELECT instance_id,owner_token::text,backend_epoch,authorization_revision,mutation_epoch,'
            'manifest_sha256,readback_sha256 FROM cragkit_qdrant.preparations WHERE ' + _INTENT + ' LIMIT 2', _key(ctx))
        if len(rows) != 1 or len(rows[0]) != 7:
            raise IntegrityViolation()
        instance = _stored_identity(rows[0][0])
        preparation = dict(zip(_PREPARATION_FIELDS, rows[0][1:], strict=True))
        _stored_uuid(preparation['owner_token'])
        _stored_count(preparation['backend_epoch'], 1)
        _stored_identity(preparation['authorization_revision'])
        _stored_count(preparation['mutation_epoch'])
        try:
            _digest(preparation['manifest_sha256'])
            _digest(preparation['readback_sha256'])
        except InvalidRequest:
            raise IntegrityViolation() from None
        if (instance != self.instance_id or preparation['backend_epoch'] > epoch
                or (preparation['authorization_revision'], preparation['mutation_epoch'], preparation['manifest_sha256'])
                    != (intent[0], intent[1], intent[3])):
            raise IntegrityViolation()
        columns = ','.join('owner_token::text' if key == 'owner_token' else key for key in _ATTESTATION_FIELDS)
        rows = await self._query(connection, 'SELECT ' + columns + ' FROM cragkit_qdrant.preparation_attestations WHERE '
            + _INTENT + ' AND backend_epoch=%s AND owner_token=%s AND instance_id=%s LIMIT 2',
            (*_key(ctx), epoch, ctx.owner_token, self.instance_id))
        if not rows:
            return preparation, None
        if len(rows) != 1 or len(rows[0]) != len(_ATTESTATION_FIELDS):
            raise IntegrityViolation()
        attestation = dict(zip(_ATTESTATION_FIELDS, rows[0], strict=True))
        for key in ('tenant_id','collection','document_id','intent_id','instance_id','authorization_revision',
                    'credential_generation','verification_id'):
            _stored_identity(attestation[key])
        _stored_identity(attestation['expected_active_generation_id'], nullable=True)
        _stored_uuid(attestation['owner_token'])
        _stored_count(attestation['backend_epoch'], 1)
        _stored_count(attestation['mutation_epoch'])
        try:
            _digest(attestation['manifest_sha256'])
            _digest(attestation['readback_sha256'])
        except InvalidRequest:
            raise IntegrityViolation() from None
        if (tuple(attestation[key] for key in ('tenant_id','collection','document_id','intent_id')) != _key(ctx)
                or attestation['instance_id'] != self.instance_id or attestation['owner_token'] != ctx.owner_token
                or attestation['backend_epoch'] != epoch or epoch <= preparation['backend_epoch']
                or (attestation['authorization_revision'],attestation['mutation_epoch'],attestation['manifest_sha256'],
                    attestation['expected_active_generation_id']) != (intent[0],intent[1],intent[3],intent[2])
                or (attestation['authorization_revision'],attestation['mutation_epoch'],attestation['expected_active_generation_id'])
                    != (document['authorization_revision'],document['mutation_epoch'],document['active_generation_id'])):
            raise IntegrityViolation()
        return preparation, attestation

    async def attestation_snapshot(self, value: object, *, deadline: float) -> Mapping[str, Any]:
        self._attestation_profile()
        ctx = context(value)
        async def snapshot(connection: SessionConnection) -> Mapping[str, Any]:
            existing = await self._inspect(connection, ctx)
            if existing is None or existing['action'] != 'stage' or existing['state'] != 'prepared':
                raise InvalidRequest()
            epoch, document, intent, failure = await self._fences(connection, ctx)
            if failure == 'denied':
                raise UnauthorizedScope()
            if failure is not None:
                raise ProviderUnavailable()
            await self._require_settled(connection, ctx)
            plan = await self._load_stage(connection, ctx)
            self._attestation_intent(plan, intent, existing)
            preparation, attestation = await self._attestation_material(connection, ctx, epoch, document, intent)
            return MappingProxyType({'preparation': MappingProxyType(preparation),
                'attestation': MappingProxyType(attestation) if attestation is not None else None})
        return await self._run(ctx, deadline, snapshot)

    async def attest_prepared(self, receipt: object, verifier: object, *, deadline: float) -> Mapping[str, Any]:
        self._attestation_profile()
        deadline = deadline_value(deadline)
        data = await attestation_receipt_data(receipt, verifier, self, deadline=deadline)
        projection_failure: UnauthorizedScope | None = None
        try:
            await self.validate_publication_projection(data['projection'], deadline=deadline)
        except UnauthorizedScope as error:
            projection_failure = error
        data = await attestation_receipt_data(receipt, verifier, self, deadline=deadline)
        controller = publication_verifier_controller(verifier, self)
        require_publication_finalization(controller, deadline=deadline)
        ctx = context(data['context'])
        binding = ordinary_binding(dict(data['attempt_binding']))
        if (binding['instance_id'] != self.instance_id or binding['intent_id'] != ctx.intent_id
                or binding['owner_token'] != ctx.owner_token):
            raise UnsupportedCapability()
        desired: dict[str, Any] | None = None

        async def operation(connection: SessionConnection, *, insert: bool) -> Mapping[str, Any] | None:
            nonlocal desired
            require_publication_finalization(controller, deadline=deadline)
            existing = await self._inspect(connection, ctx)
            if existing is None or existing['action'] != 'stage':
                raise InvalidRequest()
            if existing['state'] in ('conflict','denied'):
                return MappingProxyType({'intent': existing, 'attestation': None})
            if existing['state'] != 'prepared':
                raise InvalidRequest()
            epoch, document, intent, failure = await self._fences(connection, ctx)
            require_publication_finalization(controller, deadline=deadline)
            if failure is not None:
                return MappingProxyType({'intent': await self._outcome(connection, ctx, failure), 'attestation': None})
            if intent[6] != 'prepared':
                raise InvalidRequest()
            if projection_failure is not None:
                raise projection_failure
            if binding['epoch'] != epoch:
                raise ProviderUnavailable()
            await self._require_settled(connection, ctx)
            plan = await self._load_stage(connection, ctx)
            graph = stage_data(plan)
            self._attestation_intent(plan, intent, existing)
            if (data['manifest_sha256'] != plan.manifest_sha256 or data['generation_id'] != graph.manifest.generation_id
                    or data['revision_id'] != graph.manifest.revision_id
                    or (data['authorization_revision'],data['mutation_epoch'],data['active_generation_id'],data['tombstoned'])
                        != (document['authorization_revision'],document['mutation_epoch'],document['active_generation_id'],False)):
                raise IntegrityViolation()
            current_projection = finalize_publication_projection(self, {
                'context': ctx, 'attempt_binding': binding, 'manifest_sha256': plan.manifest_sha256,
                'revision_id': graph.manifest.revision_id, 'generation_id': graph.manifest.generation_id,
                'authorization_revision': document['authorization_revision'], 'mutation_epoch': document['mutation_epoch'],
                'active_generation_id': document['active_generation_id'], 'tombstoned': False,
                'points': self._projection_points(graph, document),
                'authority': MappingProxyType({key: tuple(document[key]) if key in ('principal_ids','grant_ids') else document[key]
                    for key in ('principal_ids','grant_ids','language','kind','tag')}),
            })
            if publication_projection_data(current_projection, self)['readback_sha256'] != data['readback_sha256']:
                raise IntegrityViolation()
            preparation, stored = await self._attestation_material(connection, ctx, epoch, document, intent)
            if epoch <= preparation['backend_epoch']:
                raise ProviderUnavailable()
            row = dict(zip(('tenant_id','collection','document_id','intent_id'), _key(ctx), strict=True))
            row.update(instance_id=self.instance_id, owner_token=ctx.owner_token, backend_epoch=epoch,
                authorization_revision=document['authorization_revision'], mutation_epoch=document['mutation_epoch'],
                manifest_sha256=intent[3], expected_active_generation_id=intent[2],
                credential_generation=binding['credential_generation'], verification_id=binding['dispatch_id'],
                readback_sha256=_digest(data['readback_sha256']))
            if desired is None:
                desired = row
            elif desired != row:
                raise IntegrityViolation()
            if stored is not None:
                if stored != row:
                    raise IntegrityViolation()
            elif not insert:
                return None
            else:
                require_publication_finalization(controller, deadline=deadline)
                await connection.execute('INSERT INTO cragkit_qdrant.preparation_attestations ('
                    + ','.join(_ATTESTATION_FIELDS) + ') VALUES (' + ','.join('%s' for _ in _ATTESTATION_FIELDS) + ')',
                    tuple(row[key] for key in _ATTESTATION_FIELDS))
            require_publication_finalization(controller, deadline=deadline)
            return MappingProxyType({'intent': existing, 'attestation': MappingProxyType(row)})

        async def insert(connection: SessionConnection) -> Mapping[str, Any]:
            result = await operation(connection, insert=True)
            assert result is not None
            return result
        async def confirm(connection: SessionConnection) -> Mapping[str, Any] | None:
            return await operation(connection, insert=False)
        try:
            return await self._run(ctx, deadline, insert, detect_commit_unknown=True)
        except _CommitUnknown:
            require_publication_finalization(controller, deadline=deadline)
            confirmed = await self._run(ctx, deadline, confirm)
            if confirmed is not None:
                return confirmed
            try:
                return await self._run(ctx, deadline, insert, detect_commit_unknown=True)
            except _CommitUnknown:
                confirmed = await self._run(ctx, deadline, confirm)
                if confirmed is not None:
                    return confirmed
                raise ProviderUnavailable() from None

    async def publish(self, value: object, *, deadline: float) -> Mapping[str, Any]:
        ctx = context(value)
        async def publish(connection: SessionConnection) -> Mapping[str, Any]:
            existing = await self._inspect(connection,ctx)
            if existing is None or existing['action']!='stage':
                raise InvalidRequest()
            if existing is not None and existing['state'] in ('published','conflict','denied'):
                return existing
            epoch,document,intent,failure = await self._fences(connection,ctx)
            if failure is not None:
                return await self._outcome(connection,ctx,failure)
            if intent[6] != 'prepared':
                raise InvalidRequest()
            await self._require_settled(connection,ctx)
            plan = await self._load_stage(connection,ctx)
            self._attestation_intent(plan, intent, existing)
            if self._schema_profile == 3:
                preparation, attestation = await self._attestation_material(connection,ctx,epoch,document,intent)
                current = (preparation['owner_token'] == ctx.owner_token and preparation['backend_epoch'] == epoch)
                if not current and attestation is None:
                    raise ProviderUnavailable()
            else:
                rows = await self._query(connection, 'SELECT owner_token::text,backend_epoch,instance_id,'
                    'manifest_sha256,authorization_revision,mutation_epoch FROM cragkit_qdrant.preparations WHERE '
                    + _INTENT + ' LIMIT 2', _key(ctx))
                expected = (ctx.owner_token,epoch,self.instance_id,intent[3],document['authorization_revision'],document['mutation_epoch'])
                if not rows:
                    raise IntegrityViolation()
                if len(rows) != 1 or len(rows[0]) != 6:
                    raise IntegrityViolation()
                _stored_uuid(rows[0][0]); _stored_count(rows[0][1],1); _stored_identity(rows[0][2])
                _stored_identity(rows[0][4]); _stored_count(rows[0][5])
                try:
                    _digest(rows[0][3])
                except InvalidRequest:
                    raise IntegrityViolation() from None
                if rows[0] != expected:
                    raise ProviderUnavailable()
            if document['active_generation_id'] is not None:
                await connection.execute('UPDATE cragkit_qdrant.generations SET published=false WHERE '+_DOC+' AND generation_id=%s',(*_doc(ctx),document['active_generation_id']))
            await connection.execute('UPDATE cragkit_qdrant.generations SET published=true,ever_published=true WHERE '+_DOC+' AND generation_id=%s',(*_doc(ctx),intent[4]))
            await connection.execute('UPDATE cragkit_qdrant.documents SET active_generation_id=%s WHERE '+_DOC,(intent[4],*_doc(ctx)))
            await connection.execute("UPDATE cragkit_qdrant.publication_intents SET state='published',authority_committed=true,replica_complete=true WHERE "+_INTENT,_key(ctx))
            result = await self._inspect(connection,ctx)
            assert result is not None
            return result
        return await self._run(ctx,deadline,publish)

    async def apply_security(self, record: object, scope: object, *, owner_token: object, deadline: float) -> Mapping[str, Any]:
        encoded = encode_security_intent(record)
        intent = _parse(_Security,record)
        ctx = context({'scope':scope,'collection':intent.collection,'document_id':intent.document_id,
                       'intent_id':intent.intent_id,'owner_token':owner_token})
        if ctx.scope.tenant_id != intent.tenant_id:
            raise UnauthorizedScope()
        async def apply(connection: SessionConnection) -> Mapping[str, Any]:
            await self._ensure(connection,'publication_intents',{**dict(zip(('tenant_id','collection','document_id'),_doc(ctx),strict=True)),
                'intent_id':ctx.intent_id,'instance_id':self.instance_id,'action':intent.action,
                'payload_bytes':encoded.encoded_bytes,'payload_sha256':encoded.sha256,
                'expected_authorization_revision':intent.expected_authorization_revision,
                'expected_mutation_epoch':intent.expected_mutation_epoch},('tenant_id','collection','document_id','intent_id'))
            existing = await self._inspect(connection,ctx)
            if existing is not None and (existing['authority_committed'] or existing['state'] in ('denied', 'conflict')):
                return existing
            if ctx.scope.authorization_revision != intent.expected_authorization_revision:
                raise UnauthorizedScope()
            document = await self._document(connection,ctx,check_revision=False)
            if (document['authorization_revision'] != intent.expected_authorization_revision
                or document['mutation_epoch'] != intent.expected_mutation_epoch
                or document['tombstoned'] and not intent.authorization.tombstoned):
                return await self._outcome(connection,ctx,'denied')
            if intent.expected_mutation_epoch == 9007199254740991:
                raise InvalidRequest()
            auth = intent.authorization
            await connection.execute('UPDATE cragkit_qdrant.documents SET authorization_revision=%s,mutation_epoch=%s,principal_ids=%s,grant_ids=%s,language=%s,kind=%s,tag=%s,tombstoned=%s WHERE '+_DOC,
                (auth.authorization_revision,intent.expected_mutation_epoch+1,_acl(auth.principal_ids),_acl(auth.grant_ids),auth.language,auth.kind,auth.tag,auth.tombstoned,*_doc(ctx)))
            await connection.execute("UPDATE cragkit_qdrant.publication_intents SET state='authority_committed',authority_committed=true WHERE "+_INTENT,_key(ctx))
            result = await self._inspect(connection,ctx)
            assert result is not None
            return result
        try:
            return await self._run(ctx,deadline,apply,detect_commit_unknown=True)
        except _CommitUnknown:
            async def confirm(connection: SessionConnection) -> Mapping[str, Any]:
                rows = await self._query(connection,
                    'SELECT instance_id,action,payload_bytes,payload_sha256,expected_authorization_revision,'
                    'expected_mutation_epoch FROM cragkit_qdrant.publication_intents WHERE '+_INTENT,
                    _key(ctx))
                if not rows:
                    raise ProviderUnavailable()
                expected = (self.instance_id,intent.action,encoded.encoded_bytes,encoded.sha256,
                            intent.expected_authorization_revision,intent.expected_mutation_epoch)
                if (len(rows) != 1 or len(rows[0]) != len(expected)
                        or any(type(actual) is not type(wanted) or actual != wanted
                               for actual,wanted in zip(rows[0],expected,strict=True))):
                    raise IntegrityViolation()
                result = await self._inspect(connection,ctx)
                if result is None:
                    raise ProviderUnavailable()
                if (type(result['authority_committed']) is not bool
                        or result['action'] != intent.action or result['payload_sha256'] != encoded.sha256):
                    raise IntegrityViolation()
                if not result['authority_committed'] and result['state'] not in ('denied','conflict'):
                    raise ProviderUnavailable()
                return result
            return await self._run(ctx,deadline,confirm)

    async def bind_purge(self, record: object, scope: object, *, owner_token: object, deadline: float) -> Mapping[str, Any]:
        encoded = encode_purge_intent(record)
        intent = _parse(_Purge,record)
        ctx = context({'scope':scope,'collection':intent.collection,'document_id':intent.document_id,
                       'intent_id':intent.intent_id,'owner_token':owner_token})
        if ctx.scope.tenant_id != intent.tenant_id:
            raise UnauthorizedScope()
        async def bind(connection: SessionConnection) -> Mapping[str, Any]:
            await self._ensure(connection,'publication_intents',{**dict(zip(('tenant_id','collection','document_id'),_doc(ctx),strict=True)),
                'intent_id':ctx.intent_id,'instance_id':self.instance_id,'action':'purge','payload_bytes':encoded.encoded_bytes,
                'payload_sha256':encoded.sha256,'expected_authorization_revision':intent.expected_authorization_revision,
                'expected_mutation_epoch':intent.expected_mutation_epoch},('tenant_id','collection','document_id','intent_id'))
            existing = await self._inspect(connection,ctx)
            if existing is not None and existing['authority_committed']:
                return existing
            if ctx.scope.authorization_revision != intent.expected_authorization_revision:
                raise UnauthorizedScope()
            document = await self._document(connection,ctx)
            if not document['tombstoned'] or document['mutation_epoch'] != intent.expected_mutation_epoch:
                raise IntegrityViolation()
            tombstone = await self._query(connection,'SELECT intent_id FROM cragkit_qdrant.publication_intents WHERE '+_DOC+" AND action='tombstone' AND payload_sha256=%s AND authority_committed LIMIT 2",(*_doc(ctx),intent.tombstone_intent_payload_sha256))
            if len(tombstone) != 1:
                raise IntegrityViolation()
            await connection.execute("UPDATE cragkit_qdrant.publication_intents SET state='authority_committed',authority_committed=true WHERE "+_INTENT,_key(ctx))
            result = await self._inspect(connection,ctx)
            assert result is not None
            return result
        return await self._run(ctx,deadline,bind)
