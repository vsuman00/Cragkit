"""Internal scoped reads and native lexical candidates over bounded pool leases.

Trusted application code supplies scope. Borrowed-pool TLS remains the caller's
responsibility. Every adapter-owned transaction rolls back, including success.
"""
from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager, asynccontextmanager
import json
import math
from typing import AsyncIterator, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ._postgres_filters import compile_filters
from ._postgres_pool import PoolResource
from ._postgres_source import SourceFetch, _SOURCE_SQL, verify_source
from .contracts import RetrievalRequest, TrustedScope, parse_request, parse_scope
from .errors import (
    CragkitError, DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable,
    UnauthorizedScope, UnsupportedCapability,
)

# Check both ledger identity and actual catalog shape: neither alone proves compatibility.
EXPECTED_HISTORY = (
    ('0001_initial', '5a7259e6375f8578c8775fe91994bd28b85ff76734744dc2c2b4ee63f623d92f'),
    ('0002_portable_lexical_config', 'a7380a57690791bc5766d969decba36b5a5ec4591d7481601eb0fd5ce096c875'),
)
_TABLE_COLUMNS = {
    'collections': 'tenant_id:identity_text collection_id:collection_text schema_version:text active_profile:identity_text policy_metadata:jsonb created_at:timestamptz',
    'documents': 'tenant_id:identity_text collection_id:collection_text document_id:identity_text active_generation_id:identity_text tombstoned:bool metadata:jsonb authorization_revision:identity_text created_at:timestamptz',
    'document_revisions': 'tenant_id:identity_text collection_id:collection_text document_id:identity_text revision_id:identity_text source_sha256:sha256_hex source_locator:identity_text canonical_text:text canonical_sha256:sha256_hex parser_id:identity_text created_at:timestamptz',
    'index_generations': 'tenant_id:identity_text collection_id:collection_text document_id:identity_text revision_id:identity_text generation_id:identity_text chunker_profile:identity_text lexical_profile:identity_text embedding_profile:identity_text status:text expected_chunk_count:int4 created_at:timestamptz',
    'chunks': 'tenant_id:identity_text collection_id:collection_text document_id:identity_text revision_id:identity_text generation_id:identity_text chunk_id:identity_text parent_chunk_id:identity_text ordinal:int4 start_byte:safe_count end_byte:safe_count text:text text_sha256:sha256_hex metadata:jsonb',
    'chunk_lexical': 'tenant_id:identity_text collection_id:collection_text document_id:identity_text revision_id:identity_text generation_id:identity_text chunk_id:identity_text language_config:text search_vector:tsvector identifier_tokens:identity_text[]',
    'document_grants': 'tenant_id:identity_text collection_id:collection_text document_id:identity_text grant_id:identity_text principal_id:identity_text authorization_revision:identity_text',
    'ingestion_jobs': 'tenant_id:identity_text collection_id:collection_text document_id:identity_text intent_id:identity_text payload_sha256:sha256_hex generation_id:identity_text state:text attempt_count:safe_count last_error_code:text created_at:timestamptz',
    'migration_history': 'version:text checksum:text applied_at:timestamptz',
}
_DOMAINS = {'identity_text', 'collection_text', 'sha256_hex', 'safe_count', 'identity_text[]'}
_COLUMN_VALUES = ','.join(
    "('%s','%s','%s')" % (table, column, ('cragkit.' if kind in _DOMAINS else 'pg_catalog.') + kind)
    for table, columns in _TABLE_COLUMNS.items()
    for column, kind in (entry.split(':') for entry in columns.split())
)
_CATALOG_SQL = """
SELECT current_setting('server_encoding') = 'UTF8'
 AND to_regprocedure('pg_catalog.to_tsvector(regconfig,text)') IS NOT NULL
 AND to_regprocedure('pg_catalog.websearch_to_tsquery(regconfig,text)') IS NOT NULL
 AND NOT EXISTS (
   SELECT 1 FROM (VALUES """ + _COLUMN_VALUES + """) expected(tbl,col,typ)
   LEFT JOIN pg_namespace n ON n.nspname='cragkit'
   LEFT JOIN pg_class c ON c.relnamespace=n.oid AND c.relname=expected.tbl
   LEFT JOIN pg_attribute a ON a.attrelid=c.oid AND a.attname=expected.col
     AND a.attnum>0 AND NOT a.attisdropped
   WHERE c.relkind IS DISTINCT FROM 'r' OR NOT c.relrowsecurity
     OR a.atttypid IS DISTINCT FROM to_regtype(expected.typ)
 ) AND NOT EXISTS (
   SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname='cragkit' AND p.prosecdef
 )
"""
_ROLE_SQL = """
SELECT current_user = session_user
 AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolcanlogin)
 AND NOT EXISTS (
   SELECT 1 FROM pg_roles r WHERE pg_has_role(current_user,r.oid,'MEMBER')
     AND (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication)
 ) AND NOT EXISTS (
   SELECT 1 FROM pg_namespace n WHERE n.nspname='cragkit'
     AND (pg_has_role(current_user,n.nspowner,'MEMBER')
       OR has_schema_privilege(current_user,n.oid,'CREATE'))
 ) AND NOT EXISTS (
   SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='cragkit' AND c.relkind IN ('r','p')
     AND (pg_has_role(current_user,c.relowner,'MEMBER')
       OR NOT row_security_active(c.oid)
       OR has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
       OR has_any_column_privilege(current_user,c.oid,'INSERT,UPDATE,REFERENCES'))
 ) AND NOT EXISTS (
   SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname='cragkit' AND pg_has_role(current_user,p.proowner,'MEMBER')
 ) AND NOT EXISTS (
   SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
   WHERE n.nspname='cragkit' AND pg_has_role(current_user,t.typowner,'MEMBER')
 )
"""
_HISTORY_SQL = 'SELECT version, checksum FROM cragkit.migration_history ORDER BY version'
_COLLECTION_SQL = ('SELECT schema_version, active_profile FROM cragkit.collections '
                   'WHERE tenant_id=%s AND collection_id=%s')
_SCOPE_SQL = """SELECT
 set_config('cragkit.tenant_id',%s,true),
 set_config('cragkit.principal_id',%s,true),
 set_config('cragkit.authorization_revision',%s,true),
 set_config('cragkit.grant_ids',%s,true)
"""
_DOCUMENT_SQL = """
SELECT d.document_id, g.revision_id, g.lexical_profile
FROM cragkit.documents d
JOIN cragkit.index_generations g ON g.tenant_id=d.tenant_id
 AND g.collection_id=d.collection_id AND g.document_id=d.document_id
 AND g.generation_id=d.active_generation_id
WHERE d.tenant_id=%s AND d.collection_id=%s AND NOT d.tombstoned
 AND d.authorization_revision=%s AND g.status='ready'
 AND EXISTS (
   SELECT 1 FROM cragkit.document_grants x
   WHERE x.tenant_id=d.tenant_id AND x.collection_id=d.collection_id
     AND x.document_id=d.document_id AND x.authorization_revision=%s
     AND (x.principal_id=%s OR (x.principal_id IS NULL AND x.grant_id=ANY(%s::text[])))
 ) AND ({predicate})
ORDER BY d.document_id COLLATE pg_catalog."C", g.revision_id COLLATE pg_catalog."C"
LIMIT %s
"""


class CursorProtocol(Protocol):
    async def fetchall(self) -> list[tuple[object, ...]]: ...


class InfoProtocol(Protocol):
    @property
    def transaction_status(self) -> int: ...


class SessionConnection(Protocol):
    @property
    def info(self) -> InfoProtocol: ...
    def transaction(self, *, force_rollback: bool = False) -> AbstractAsyncContextManager[object]: ...
    async def execute(self, query: str, params: tuple[object, ...] | None = None) -> CursorProtocol: ...
    async def close(self) -> None: ...


_LEXICAL_SQL = """
WITH search AS (SELECT websearch_to_tsquery('pg_catalog.simple'::regconfig,%s) AS query)
SELECT d.tenant_id,d.collection_id,d.document_id,g.revision_id,g.generation_id,c.chunk_id,
 c.start_byte,c.end_byte,c.text_sha256,ts_rank_cd(l.search_vector,search.query)::double precision,g.lexical_profile,l.language_config
FROM cragkit.documents d
JOIN cragkit.index_generations g ON g.tenant_id=d.tenant_id AND g.collection_id=d.collection_id
 AND g.document_id=d.document_id AND g.generation_id=d.active_generation_id
JOIN cragkit.chunks c ON c.tenant_id=g.tenant_id AND c.collection_id=g.collection_id
 AND c.document_id=g.document_id AND c.revision_id=g.revision_id AND c.generation_id=g.generation_id
JOIN cragkit.chunk_lexical l ON l.tenant_id=c.tenant_id AND l.collection_id=c.collection_id
 AND l.document_id=c.document_id AND l.revision_id=c.revision_id AND l.generation_id=c.generation_id AND l.chunk_id=c.chunk_id
CROSS JOIN search
WHERE d.tenant_id=%s AND d.collection_id=%s AND NOT d.tombstoned
 AND d.authorization_revision=%s AND g.status='ready'
 AND EXISTS(SELECT 1 FROM cragkit.document_grants x WHERE x.tenant_id=d.tenant_id AND x.collection_id=d.collection_id
  AND x.document_id=d.document_id AND x.authorization_revision=%s
  AND (x.principal_id=%s OR (x.principal_id IS NULL AND x.grant_id=ANY(%s::text[]))))
 AND ({predicate}) AND l.search_vector @@ search.query
ORDER BY ts_rank_cd(l.search_vector,search.query) DESC,d.document_id COLLATE pg_catalog."C",
 g.revision_id COLLATE pg_catalog."C",c.ordinal,c.chunk_id COLLATE pg_catalog."C"
LIMIT %s
"""


def _remaining(deadline: float) -> float:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise DeadlineExceeded()
    return remaining


def _check_deadline(deadline: float) -> None:
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
        raise InvalidRequest()
    finite = False
    try:
        finite = math.isfinite(deadline)
    except OverflowError:
        pass
    if not finite:
        raise InvalidRequest()
    _remaining(deadline)


def _safe_error(error: Exception) -> CragkitError:
    state = getattr(error, 'sqlstate', None)
    if state == '57014':
        return DeadlineExceeded()
    if isinstance(state, str) and state.startswith('23'):
        return IntegrityViolation()
    if state == '42501':
        return UnauthorizedScope()
    if state in ('42P01', '42703', '42883', '3F000'):
        return UnsupportedCapability()
    return ProviderUnavailable()


async def _query(connection: SessionConnection, sql: str, params: tuple[object, ...] | None,
                 deadline: float) -> list[tuple[object, ...]]:
    failure: CragkitError | None = None
    rows: list[tuple[object, ...]] = []
    try:
        # PostgreSQL bounds each statement; the outer timer also bounds body and fetch work.
        milliseconds = max(1, math.floor(min(_remaining(deadline), 2_147_483.647) * 1000))
        await connection.execute("SELECT set_config('statement_timeout',%s,true)", (str(milliseconds),))
        cursor = await connection.execute(sql, params)
        rows = await cursor.fetchall()
        _remaining(deadline)
    except CragkitError:
        raise
    except Exception as error:
        failure = _safe_error(error)
    if failure is not None:
        raise failure from None
    if not isinstance(rows, list) or any(not isinstance(row, tuple) for row in rows):
        raise UnsupportedCapability()
    return rows


async def _validate(connection: SessionConnection, deadline: float) -> None:
    if await _query(connection, _ROLE_SQL, None, deadline) != [(True,)]:
        raise UnauthorizedScope()
    if await _query(connection, _CATALOG_SQL, None, deadline) != [(True,)]:
        raise UnsupportedCapability()
    if tuple(await _query(connection, _HISTORY_SQL, None, deadline)) != EXPECTED_HISTORY:
        raise UnsupportedCapability()


class LexicalCandidate(BaseModel):
    """Internal candidate identity; score is native FTS rank, not confidence."""

    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    tenant_id: str
    collection: str
    document_id: str
    revision_id: str
    generation_id: str
    chunk_id: str
    start_byte: int = Field(ge=0, le=9_007_199_254_740_991)
    end_byte: int = Field(gt=0, le=9_007_199_254_740_991)
    text_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    score: float = Field(ge=0, allow_inf_nan=False)


class ScopedSession:
    """A task-bound read handle that expires when its transaction exits."""

    def __init__(self, connection: SessionConnection, request: RetrievalRequest,
                 scope: TrustedScope, deadline: float, predicate: str, parameters: tuple[object, ...]) -> None:
        self._connection = connection
        self._request = request
        self._scope = scope
        self._deadline = deadline
        self._predicate = predicate
        self._parameters = parameters
        self._task = asyncio.current_task()
        self._active = True

    async def visible_documents(self, *, limit: int = 100) -> tuple[tuple[str, str], ...]:
        if not self._active or asyncio.current_task() is not self._task:
            raise InvalidRequest()
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise InvalidRequest()
        rows = await _query(self._connection, _DOCUMENT_SQL.format(predicate=self._predicate), (
            self._scope.tenant_id, self._request.collection, self._scope.authorization_revision,
            self._scope.authorization_revision, self._scope.principal_id, list(self._scope.grant_ids),
            *self._parameters, min(limit, self._request.limits.max_candidates),
        ), self._deadline)
        if any(len(row) != 3 or not all(isinstance(value, str) for value in row)
               or row[2] != 'native_fts.v1' for row in rows):
            raise UnsupportedCapability()
        return cast(tuple[tuple[str, str], ...], tuple((row[0], row[1]) for row in rows))


    async def lexical_candidates(self, *, limit: int = 100) -> tuple[LexicalCandidate, ...]:
        if not self._active or asyncio.current_task() is not self._task:
            raise InvalidRequest()
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise InvalidRequest()
        # Existing filters use d/g aliases; their values precede the final LIMIT parameter.
        rows = await _query(self._connection, _LEXICAL_SQL.format(predicate=self._predicate), (
            self._request.query, self._scope.tenant_id, self._request.collection,
            self._scope.authorization_revision, self._scope.authorization_revision,
            self._scope.principal_id, list(self._scope.grant_ids), *self._parameters,
            min(limit, self._request.limits.max_candidates),
        ), self._deadline)
        candidates = []
        fields = tuple(LexicalCandidate.model_fields)
        for row in rows:
            if len(row) != 12 or row[-2:] != ('native_fts.v1', 'pg_catalog.simple'):
                raise UnsupportedCapability()
            candidate = None
            try:
                candidate = LexicalCandidate.model_validate(dict(zip(fields, row[:-2], strict=True)))
            except ValidationError:
                pass
            if (candidate is None or candidate.tenant_id != self._scope.tenant_id
                    or candidate.collection != self._request.collection or candidate.end_byte <= candidate.start_byte):
                raise IntegrityViolation()
            candidates.append(candidate)
        return tuple(candidates)


    async def fetch_evidence(self, candidate: LexicalCandidate, *, max_source_bytes: int) -> SourceFetch:
        if not self._active or asyncio.current_task() is not self._task:
            raise InvalidRequest()
        if type(max_source_bytes) is not int or not 0 <= max_source_bytes <= 16_777_216:
            raise InvalidRequest()
        if not isinstance(candidate, LexicalCandidate):
            raise InvalidRequest()
        validated = None
        try:
            validated = LexicalCandidate.model_validate(candidate.model_dump(mode='json'))
        except (ValidationError, ValueError, TypeError):
            pass
        if validated is None:
            raise InvalidRequest()
        candidate = validated
        identities = (candidate.tenant_id, candidate.collection, candidate.document_id,
                      candidate.revision_id, candidate.generation_id, candidate.chunk_id)
        try:
            malformed = (len(candidate.collection) > 128 or len(candidate.collection.encode('utf-8')) > 128
                         or any(not value.strip(' \t\r\n\f\v') or '\0' in value
                                or len(value) > 256 or len(value.encode('utf-8')) > 256 for value in identities))
        except UnicodeError:
            malformed = True
        if malformed or candidate.end_byte <= candidate.start_byte:
            raise InvalidRequest()
        if candidate.tenant_id != self._scope.tenant_id or candidate.collection != self._request.collection:
            raise UnauthorizedScope()
        rows = await _query(self._connection, _SOURCE_SQL.format(predicate=self._predicate), (
            max_source_bytes, *identities, self._scope.tenant_id, self._request.collection,
            self._scope.authorization_revision, self._scope.authorization_revision,
            self._scope.principal_id, list(self._scope.grant_ids), *self._parameters,
        ), self._deadline)
        result = verify_source(candidate, rows, max_source_bytes)
        _remaining(self._deadline)
        return result


class PostgresSession:
    """Validate each leased connection and bind immutable scope within read-only work."""

    def __init__(self, resource: PoolResource) -> None:
        self._resource = resource

    @asynccontextmanager
    async def _transaction(self, deadline: float) -> AsyncIterator[SessionConnection]:
        _check_deadline(deadline)
        async with self._resource.lease(deadline=deadline) as leased:
            connection = cast(SessionConnection, leased)
            setup_error: CragkitError | None = None
            transaction: AbstractAsyncContextManager[object] | None = None
            try:
                if connection.info.transaction_status != 0:
                    raise InvalidRequest()
                transaction = connection.transaction(force_rollback=True)
            except InvalidRequest:
                raise
            except Exception as error:
                setup_error = _safe_error(error)
            if setup_error is not None:
                raise setup_error from None
            assert transaction is not None
            begun = False
            dispatched = False
            yielded = False
            failure: BaseException | None = None
            timer = asyncio.timeout_at(deadline)
            try:
                async with timer:
                    dispatched = True
                    await transaction.__aenter__()
                    begun = True
                    await connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
                    await connection.execute("SET LOCAL search_path = pg_catalog")
                    yielded = True
                    yield connection
                    _remaining(deadline)
            except TimeoutError as error:
                failure = DeadlineExceeded() if timer.expired() else error
            except BaseException as error:
                failure = error if yielded or not isinstance(error, Exception) or isinstance(error, CragkitError) else _safe_error(error)
            finally:
                if dispatched:
                    async def rollback() -> bool:
                        budget = self._resource.config.release_timeout
                        end = asyncio.get_running_loop().time() + budget
                        try:
                            async with asyncio.timeout(budget / 2 if begun else budget):
                                if begun:
                                    await transaction.__aexit__(None, None, None)
                                    # The driver can return normally after a failed
                                    # rollback. Verify the connection is reusable.
                                    if connection.info.transaction_status != 0:
                                        raise ProviderUnavailable()
                                else:
                                    await connection.close()
                            return True
                        except Exception:
                            if begun:
                                try:
                                    async with asyncio.timeout(max(0.0, end - asyncio.get_running_loop().time())):
                                        await connection.close()
                                except Exception:
                                    pass
                            return False
                    cleanup = asyncio.create_task(rollback())
                    try:
                        clean = await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        await asyncio.shield(cleanup)
                        raise
                    if not clean and failure is None:
                        failure = ProviderUnavailable()
            if failure is not None:
                raise failure

    async def validate(self, *, deadline: float) -> None:
        async with self._transaction(deadline) as connection:
            await _validate(connection, deadline)

    @asynccontextmanager
    async def transaction(self, request: RetrievalRequest, *, scope: TrustedScope,
                          deadline: float) -> AsyncIterator[ScopedSession]:
        _check_deadline(deadline)
        if not isinstance(request, RetrievalRequest) or not isinstance(scope, TrustedScope):
            raise InvalidRequest()
        invalid = False
        try:
            request = parse_request(request.model_dump(mode='json'))
            scope = parse_scope(scope.model_dump(mode='json'))
        except Exception:
            invalid = True
        if invalid:
            raise InvalidRequest() from None
        if any('\0' in value for value in (request.query, request.collection, scope.tenant_id,
                scope.principal_id, scope.authorization_revision, *scope.grant_ids)):
            raise InvalidRequest()
        predicate, parameters = compile_filters(request.required_filters)
        deadline = min(deadline, asyncio.get_running_loop().time() + request.limits.deadline_ms / 1000)
        async with self._transaction(deadline) as connection:
            await _validate(connection, deadline)
            await _query(connection, _SCOPE_SQL, (
                scope.tenant_id, scope.principal_id, scope.authorization_revision,
                json.dumps(scope.grant_ids, ensure_ascii=True, separators=(',', ':')),
            ), deadline)
            if await _query(connection, _COLLECTION_SQL, (scope.tenant_id, request.collection), deadline) != [('0.1', 'native_fts.v1')]:
                raise UnsupportedCapability()
            session = ScopedSession(connection, request, scope, deadline, predicate, parameters)
            try:
                yield session
            finally:
                session._active = False
