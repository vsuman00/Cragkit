"""Explicit document tombstones and caller-controlled source purge."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Literal, cast

from pydantic import BaseModel, ConfigDict

from ._postgres_pool import PoolResource
from ._postgres_session import (
    EXPECTED_HISTORY, SessionConnection, _CATALOG_SQL, _HISTORY_SQL, _SCOPE_SQL,
    _check_deadline, _query,
)
from .contracts import TrustedScope, parse_scope
from .errors import (
    DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest,
    UnauthorizedScope, UnsupportedCapability,
)
from .ingestion import (
    _DOCUMENT_LOCK_SQL, _LOCK_SQL, _WRITER_ROLE_SQL, _identity, _json, _write_transaction,
)

Operation = Literal['tombstone', 'purge']
LifecycleAuthorizer = Callable[[TrustedScope, str, str, Operation], Awaitable[bool]]


class LifecycleReceipt(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    tenant_id: str
    collection: str
    document_id: str
    state: Literal['tombstoned', 'purged']
    active_generation_id: str | None
    changed: bool


# Purge requires parent DELETE, while direct child DELETE remains forbidden.
_PURGER_ROLE_SQL = _WRITER_ROLE_SQL.replace(
    "OR has_table_privilege(current_user,c.oid,'DELETE')",
    "OR (c.relname<>'documents' AND has_table_privilege(current_user,c.oid,'DELETE'))",
)
_PURGE_CATALOG_SQL = """
WITH known_vector_storage AS (
 SELECT c.relkind,c.relrowsecurity FROM pg_catalog.pg_class c
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='cragkit' AND c.relname='chunk_vectors_fake_1536'
), known_openai_vector_storage AS (
 SELECT c.relkind,c.relrowsecurity FROM pg_catalog.pg_class c
 JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname='cragkit' AND c.relname='chunk_vectors_openai_te3small_1536'
), base_expected(child,parent,child_columns,parent_columns,delete_action) AS (VALUES
    ('document_revisions','documents',ARRAY['tenant_id','collection_id','document_id']::text[],ARRAY['tenant_id','collection_id','document_id']::text[],'c'),
    ('document_grants','documents',ARRAY['tenant_id','collection_id','document_id']::text[],ARRAY['tenant_id','collection_id','document_id']::text[],'c'),
    ('ingestion_jobs','documents',ARRAY['tenant_id','collection_id','document_id']::text[],ARRAY['tenant_id','collection_id','document_id']::text[],'c'),
    ('index_generations','document_revisions',ARRAY['tenant_id','collection_id','document_id','revision_id']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id']::text[],'c'),
    ('chunks','index_generations',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id']::text[],'c'),
    ('chunk_lexical','chunks',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']::text[],'c'),
    ('documents','index_generations',ARRAY['tenant_id','collection_id','document_id','active_generation_id']::text[],ARRAY['tenant_id','collection_id','document_id','generation_id']::text[],'a'),
    ('ingestion_jobs','index_generations',ARRAY['tenant_id','collection_id','document_id','generation_id']::text[],ARRAY['tenant_id','collection_id','document_id','generation_id']::text[],'a'),
    ('chunks','chunks',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','parent_chunk_id']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']::text[],'a')
), expected AS (
 SELECT * FROM base_expected
 UNION ALL
 SELECT * FROM (VALUES
    ('chunk_vectors_fake_1536','chunks',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']::text[],'c'),
    ('chunk_vectors_fake_1536','index_generations',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','embedding_profile']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','embedding_profile']::text[],'c')
 ) optional(child,parent,child_columns,parent_columns,delete_action)
 WHERE EXISTS (SELECT 1 FROM known_vector_storage)
 UNION ALL
 SELECT * FROM (VALUES
    ('chunk_vectors_openai_te3small_1536','chunks',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']::text[],'c'),
    ('chunk_vectors_openai_te3small_1536','index_generations',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','embedding_profile']::text[],ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','embedding_profile']::text[],'c')
 ) optional_openai(child,parent,child_columns,parent_columns,delete_action)
 WHERE EXISTS (SELECT 1 FROM known_openai_vector_storage)
), actual AS (
 SELECT c.oid,c.conrelid,c.confrelid,c.confdeltype::text AS delete_action,c.convalidated,
        child.relname::text AS child,parent.relname::text AS parent,
        ARRAY(SELECT a.attname::text FROM unnest(c.conkey) WITH ORDINALITY k(n,i)
              JOIN pg_catalog.pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=k.n ORDER BY k.i) AS child_columns,
        ARRAY(SELECT a.attname::text FROM unnest(c.confkey) WITH ORDINALITY k(n,i)
              JOIN pg_catalog.pg_attribute a ON a.attrelid=c.confrelid AND a.attnum=k.n ORDER BY k.i) AS parent_columns,
        child_ns.nspname::text AS child_schema
 FROM pg_catalog.pg_constraint c
 JOIN pg_catalog.pg_class child ON child.oid=c.conrelid
 JOIN pg_catalog.pg_namespace child_ns ON child_ns.oid=child.relnamespace
 JOIN pg_catalog.pg_class parent ON parent.oid=c.confrelid
 JOIN pg_catalog.pg_namespace parent_ns ON parent_ns.oid=parent.relnamespace
 WHERE c.contype='f' AND parent_ns.nspname='cragkit'
   AND (parent.relname IN ('documents','document_revisions','index_generations','chunks','chunk_vectors_fake_1536','document_grants','ingestion_jobs','chunk_lexical')
    OR parent.relname='chunk_vectors_openai_te3small_1536')
)
SELECT current_setting('session_replication_role')='origin'
 AND NOT EXISTS (SELECT 1 FROM known_openai_vector_storage WHERE relkind<>'r' OR NOT relrowsecurity)
 AND NOT EXISTS (SELECT 1 FROM known_vector_storage
  WHERE relkind<>'r' OR NOT relrowsecurity)
 AND (SELECT count(*) FROM actual)=(SELECT count(*) FROM expected)
 AND NOT EXISTS (
   SELECT 1 FROM expected e WHERE (SELECT count(*) FROM actual a
     WHERE a.child_schema='cragkit' AND a.child=e.child AND a.parent=e.parent
       AND a.child_columns=e.child_columns AND a.parent_columns=e.parent_columns
       AND a.delete_action=e.delete_action AND a.convalidated)<>1)
 AND NOT EXISTS (
   SELECT 1 FROM actual a WHERE
     (SELECT count(*) FROM pg_catalog.pg_trigger t WHERE t.tgconstraint=a.oid AND t.tgisinternal)=4
       IS NOT TRUE
     OR EXISTS (SELECT 1 FROM pg_catalog.pg_trigger t WHERE t.tgconstraint=a.oid
                AND (NOT t.tgisinternal OR t.tgenabled NOT IN ('O','A'))))
"""

_TOMBSTONE_SQL = """
UPDATE cragkit.documents SET tombstoned=true
WHERE tenant_id=%s AND collection_id=%s AND document_id=%s
 AND authorization_revision=%s AND NOT tombstoned
 AND active_generation_id IS NOT DISTINCT FROM %s
RETURNING 1
"""
_PURGE_DELETE_SQL = """
DELETE FROM cragkit.documents
WHERE tenant_id=%s AND collection_id=%s AND document_id=%s
 AND authorization_revision=%s AND tombstoned
 AND active_generation_id IS NOT DISTINCT FROM %s
RETURNING created_at::text
"""
_PURGE_INSERT_SQL = """
INSERT INTO cragkit.documents
 (tenant_id,collection_id,document_id,authorization_revision,active_generation_id,tombstoned,metadata,created_at)
VALUES (%s,%s,%s,%s,NULL,true,'{}'::jsonb,%s::timestamptz)
RETURNING 1
"""


class PostgresLifecycle:
    """Bind application mutation authorization; never install retention timers or policies."""

    def __init__(self, resource: PoolResource, *, authorize_lifecycle: LifecycleAuthorizer) -> None:
        if not callable(authorize_lifecycle):
            raise InvalidRequest()
        self._resource = resource
        self._authorize_lifecycle = authorize_lifecycle

    async def tombstone(self, *, collection: str, document_id: str,
                        expected_generation_id: str | None, scope: TrustedScope,
                        deadline: float) -> LifecycleReceipt:
        return await self._run('tombstone', collection, document_id, expected_generation_id, scope, deadline)

    async def purge_tombstoned(self, *, collection: str, document_id: str,
                              expected_generation_id: str | None, scope: TrustedScope,
                              deadline: float) -> LifecycleReceipt:
        return await self._run('purge', collection, document_id, expected_generation_id, scope, deadline)

    async def _run(self, operation: Operation, collection: str, document_id: str,
                   expected: str | None, scope: TrustedScope, deadline: float) -> LifecycleReceipt:
        _check_deadline(deadline)
        collection = _identity(collection, 128)
        document_id = _identity(document_id)
        if expected is not None:
            expected = _identity(expected)
        if not isinstance(scope, TrustedScope):
            raise InvalidRequest()
        invalid = False
        try:
            scope = parse_scope(scope.model_dump(mode='json'))
        except Exception:
            invalid = True
        if invalid:
            raise InvalidRequest()
        for value in (scope.tenant_id, scope.principal_id, scope.authorization_revision, *scope.grant_ids):
            _identity(value)
        authorization_timer = asyncio.timeout_at(deadline)
        try:
            async with authorization_timer:
                allowed = await self._authorize_lifecycle(scope, collection, document_id, operation)
        except TimeoutError:
            if authorization_timer.expired():
                raise DeadlineExceeded() from None
            raise
        _check_deadline(deadline)
        if allowed is not True:
            raise UnauthorizedScope()
        async with self._resource.lease(deadline=deadline) as leased:
            connection = cast(SessionConnection, leased)
            return await _write_transaction(connection, deadline, self._resource.config.release_timeout,
                lambda: self._mutate(connection, operation, collection, document_id, expected, scope, deadline))

    async def _mutate(self, connection: SessionConnection, operation: Operation,
                      collection: str, document_id: str, expected: str | None,
                      scope: TrustedScope, deadline: float) -> LifecycleReceipt:
        async def query(sql: str, values: tuple[object, ...] | None = None) -> list[tuple[object, ...]]:
            return await _query(connection, sql, values, deadline)
        guard = _WRITER_ROLE_SQL if operation == 'tombstone' else _PURGER_ROLE_SQL
        if await query(guard) != [(True,)]:
            raise UnauthorizedScope()
        if await query(_CATALOG_SQL) != [(True,)]:
            raise UnsupportedCapability()
        if tuple(await query(_HISTORY_SQL)) != EXPECTED_HISTORY:
            raise UnsupportedCapability()
        await query(_SCOPE_SQL, (scope.tenant_id, scope.principal_id, scope.authorization_revision,
                                _json(sorted(set(scope.grant_ids), key=lambda value: value.encode('utf-8')))))
        key = (scope.tenant_id, collection, document_id)
        await query(_LOCK_SQL, (_json(['cragkit.document.v1', *key]),))
        rows = await query(_DOCUMENT_LOCK_SQL, key)
        if not rows:
            raise UnauthorizedScope()
        if len(rows) != 1 or len(rows[0]) != 3 or type(rows[0][1]) is not bool:
            raise IntegrityViolation()
        active, tombstoned, authorization_revision = rows[0]
        malformed = False
        try:
            if active is not None:
                _identity(active)
            _identity(authorization_revision)
        except InvalidRequest:
            malformed = True
        if malformed:
            raise IntegrityViolation()
        if authorization_revision != scope.authorization_revision:
            raise UnauthorizedScope()
        if active != expected:
            raise IndexNotReady()
        if operation == 'tombstone':
            changed = not tombstoned
            if changed and await query(_TOMBSTONE_SQL, (*key, scope.authorization_revision, expected)) != [(1,)]:
                raise IntegrityViolation()
            return LifecycleReceipt(tenant_id=scope.tenant_id, collection=collection,
                document_id=document_id, state='tombstoned', active_generation_id=active,
                changed=changed)
        if not tombstoned:
            raise InvalidRequest()
        # Parent cascades erase even child rows the purger cannot SELECT under RLS.
        if await query(_PURGE_CATALOG_SQL) != [(True,)]:
            raise UnsupportedCapability() from None
        deleted = await query(_PURGE_DELETE_SQL, (*key, scope.authorization_revision, expected))
        if len(deleted) != 1 or len(deleted[0]) != 1:
            raise IntegrityViolation()
        created_at = deleted[0][0]
        invalid_timestamp = False
        try:
            _identity(created_at, 128)
        except InvalidRequest:
            invalid_timestamp = True
        if invalid_timestamp:
            raise IntegrityViolation()
        # Cast the server's text back on the server, retaining sub-millisecond precision.
        if await query(_PURGE_INSERT_SQL, (*key, scope.authorization_revision, created_at)) != [(1,)]:
            raise IntegrityViolation()
        return LifecycleReceipt(tenant_id=scope.tenant_id, collection=collection,
            document_id=document_id, state='purged', active_generation_id=None, changed=True)
