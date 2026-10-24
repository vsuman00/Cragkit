"""Explicit atomic text ingestion. Applications authorize writes; no migrations run here."""
from __future__ import annotations

import asyncio
from hashlib import sha256
import json
import math
import struct
from typing import Any, Awaitable, Callable, TypeVar, cast

from pydantic import BaseModel, ConfigDict

from ._identifiers import extract_identifiers
from ._postgres_pool import PoolResource
from ._postgres_session import (
    EXPECTED_HISTORY, SessionConnection, _CATALOG_SQL, _COLLECTION_SQL,
    _HISTORY_SQL, _SCOPE_SQL, _check_deadline, _query, _safe_error,
)
from .canonical import CanonicalDocument, canonicalize
from .contracts import TrustedScope, parse_scope
from .contracts._validation import native_json
from .errors import (
    CragkitError, DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest,
    ProviderUnavailable, UnauthorizedScope, UnsupportedCapability,
)


class IngestionReceipt(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    tenant_id: str
    collection: str
    document_id: str
    intent_id: str
    revision_id: str
    generation_id: str
    payload_sha256: str
    canonical_sha256: str
    chunk_count: int
    replayed: bool


_WRITER_ROLE_SQL = """
SELECT current_user = session_user
 AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolcanlogin)
 AND NOT EXISTS (
   SELECT 1 FROM pg_roles r WHERE pg_has_role(current_user,r.oid,'MEMBER')
     AND (r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication
       -- MEMBER rejects direct/transitive membership even for NOINHERIT logins.
       -- Exact broad-data and server file/program role denylist:
       OR r.rolname IN ('pg_read_all_data','pg_write_all_data','pg_read_server_files',
                        'pg_write_server_files','pg_execute_server_program'))
 ) AND NOT EXISTS (
   SELECT 1 FROM pg_namespace n WHERE n.nspname='cragkit'
     AND (pg_has_role(current_user,n.nspowner,'MEMBER') OR has_schema_privilege(current_user,n.oid,'CREATE'))
 ) AND NOT EXISTS (
   SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
   WHERE n.nspname='cragkit' AND c.relkind IN ('r','p')
     AND (pg_has_role(current_user,c.relowner,'MEMBER') OR NOT row_security_active(c.oid)
          OR has_table_privilege(current_user,c.oid,'TRUNCATE')
          OR has_table_privilege(current_user,c.oid,'DELETE'))
 ) AND NOT EXISTS (
   SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
   WHERE n.nspname='cragkit' AND pg_has_role(current_user,p.proowner,'MEMBER')
 ) AND NOT EXISTS (
   SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
   WHERE n.nspname='cragkit' AND pg_has_role(current_user,t.typowner,'MEMBER')
 )
"""
_LOCK_SQL = 'SELECT pg_advisory_xact_lock(hashtextextended(%s,0))'
_JOB_SQL = """SELECT payload_sha256,generation_id,state,document_id FROM cragkit.ingestion_jobs
WHERE tenant_id=%s AND collection_id=%s AND intent_id=%s FOR UPDATE"""
_DOCUMENT_LOCK_SQL = """SELECT active_generation_id,tombstoned,authorization_revision FROM cragkit.documents
WHERE tenant_id=%s AND collection_id=%s AND document_id=%s FOR UPDATE"""
_REVISION_SQL = """SELECT source_sha256,canonical_sha256,source_locator,parser_id FROM cragkit.document_revisions
WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND revision_id=%s"""
_GENERATION_SQL = """SELECT revision_id,status,expected_chunk_count FROM cragkit.index_generations
WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s"""
_COUNTS_SQL = """SELECT
 (SELECT count(*) FROM cragkit.chunks WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s),
 (SELECT count(*) FROM cragkit.chunk_lexical WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s)"""
_CHUNKS_SQL = """INSERT INTO cragkit.chunks
(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,ordinal,start_byte,end_byte,text,text_sha256,metadata)
SELECT %s,%s,%s,%s,%s,x.chunk_id,x.ordinal,x.start_byte,x.end_byte,x.text,x.text_sha256,x.metadata
FROM jsonb_to_recordset(%s::jsonb) AS x(chunk_id text,ordinal integer,start_byte bigint,end_byte bigint,
 text text,text_sha256 text,metadata jsonb) RETURNING 1"""
_LEXICAL_SQL = """WITH selected AS (
 SELECT * FROM cragkit.chunks WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s
)
INSERT INTO cragkit.chunk_lexical
(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,language_config,search_vector,identifier_tokens)
SELECT tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,'pg_catalog.simple',''::tsvector,
 ARRAY(SELECT jsonb_array_elements_text(%s::jsonb -> chunk_id))::cragkit.identity_text[]
FROM selected RETURNING 1"""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def _hash(value: object) -> str:
    return sha256(_json(value).encode('utf-8')).hexdigest()


def _identity(value: object, limit: int = 256) -> str:
    if type(value) is not str:
        raise InvalidRequest()
    assert isinstance(value, str)
    invalid = False
    try:
        invalid = not value.strip(' \t\r\n\f\v') or '\0' in value or len(value) > limit or len(value.encode('utf-8')) > limit
    except UnicodeError:
        invalid = True
    if invalid:
        raise InvalidRequest()
    return value


def _metadata(value: object) -> tuple[str, str]:
    """Hash bounded JSON by TLV, independent of either runtime's float formatting."""
    failed = False
    encoded = bytearray()

    def append(data: bytes) -> None:
        encoded.extend(data)
        if len(encoded) > 65_536:
            raise ValueError()

    def encode(item: object) -> None:
        if item is None:
            append(b'n')
        elif type(item) is bool:
            append(b't' if item else b'f')
        elif type(item) in (int, float):
            assert isinstance(item, (int, float))
            if not math.isfinite(item) or abs(item) > 9_007_199_254_740_991:
                raise ValueError()
            append(b'd' + struct.pack('>d', 0.0 if item == 0 else float(item)))
        elif type(item) is str:
            assert isinstance(item, str)
            if len(item) > 65_536 or '\0' in item:
                raise ValueError()
            data = item.encode('utf-8')
            append(b's' + struct.pack('>I', len(data)) + data)
        elif type(item) is list:
            assert isinstance(item, list)
            append(b'a' + struct.pack('>I', len(item)))
            for child in item:
                encode(child)
        elif type(item) is dict:
            assert isinstance(item, dict)
            append(b'o' + struct.pack('>I', len(item)))
            for key in sorted(item, key=lambda entry: entry.encode('utf-8')):
                encode(key)
                encode(item[key])
        else:
            raise ValueError()

    serialized = ''
    digest = ''
    try:
        if type(value) is not dict:
            raise ValueError()
        native_json(value)
        encode(value)
        serialized = _json(value)
        # Snapshot before any await so later caller mutations cannot alter stored metadata.
        snapshot = json.loads(serialized)
        encoded.clear()
        encode(snapshot)
        digest = sha256(encoded).hexdigest()
    except (ValueError, TypeError, OverflowError, RecursionError):
        failed = True
    if failed:
        raise InvalidRequest() from None
    return serialized, digest


def _identifiers(document: CanonicalDocument, scope: TrustedScope, collection: str, document_id: str,
                 intent_id: str, locator: str, metadata_hash: str, expected: str | None) -> tuple[str, str, str]:
    grants = sorted(set(scope.grant_ids), key=lambda value: value.encode('utf-8'))
    manifest = _hash([[chunk.chunk_id, str(chunk.start_byte), str(chunk.end_byte), chunk.text_sha256,
                      'true' if chunk.oversized_split else 'false',
                      None if chunk.token_count is None else str(chunk.token_count)] for chunk in document.chunks])
    payload = _hash(['cragkit.ingest.v1', scope.tenant_id, collection, document_id, intent_id, locator,
                     document.source_sha256, document.canonical_sha256, document.parser_id,
                     document.chunker_profile, metadata_hash, manifest, scope.principal_id,
                     scope.authorization_revision, grants, expected])
    revision = _hash(['cragkit.revision.v1', scope.tenant_id, collection, document_id,
                     document.source_sha256, document.canonical_sha256, document.parser_id, locator])
    return payload, revision, _hash(['cragkit.generation.v1', payload])


_Receipt = TypeVar('_Receipt', bound=BaseModel)


async def _write_transaction(connection: SessionConnection, deadline: float, release_timeout: float,
                             stage: Callable[[], Awaitable[_Receipt]]) -> _Receipt:
    setup_error: CragkitError | None = None
    transaction = None
    try:
        if connection.info.transaction_status != 0:
            raise InvalidRequest()
        transaction = connection.transaction()
    except InvalidRequest:
        raise
    except Exception as error:
        setup_error = _safe_error(error)
    if setup_error is not None:
        raise setup_error from None
    assert transaction is not None
    dispatched = False
    entered = False
    failure: BaseException | None = None
    result: _Receipt | None = None
    timer = asyncio.timeout_at(deadline)
    try:
        async with timer:
            dispatched = True
            begin_error: CragkitError | None = None
            try:
                await transaction.__aenter__()
                entered = True
                await connection.execute('SET LOCAL search_path = pg_catalog')
            except Exception as error:
                begin_error = _safe_error(error)
            if begin_error is not None:
                raise begin_error from None
            result = await stage()
            _check_deadline(deadline)
            await transaction.__aexit__(None, None, None)
            entered = False
            if connection.info.transaction_status != 0:
                raise ProviderUnavailable()
            _check_deadline(deadline)
    except TimeoutError as error:
        failure = DeadlineExceeded() if timer.expired() else error
    except BaseException as error:
        failure = error
        if not isinstance(error, (CragkitError, asyncio.CancelledError)) and result is not None:
            failure = _safe_error(cast(Exception, error))
    finally:
        if dispatched and (entered or result is None or connection.info.transaction_status != 0):
            async def cleanup() -> None:
                end = asyncio.get_running_loop().time() + release_timeout
                try:
                    async with asyncio.timeout(release_timeout / 2):
                        if entered and result is None:
                            await transaction.__aexit__(Exception, Exception(), None)
                            if connection.info.transaction_status != 0:
                                raise ProviderUnavailable()
                        else:
                            await connection.close()
                except Exception:
                    try:
                        async with asyncio.timeout(max(0.0, end - asyncio.get_running_loop().time())):
                            await connection.close()
                    except Exception:
                        pass
            task = asyncio.create_task(cleanup())
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await asyncio.shield(task)
                raise
    if failure is not None:
        raise failure
    assert result is not None
    return result


class PostgresIndexer:
    """Bind an application-owned write authorizer outside editable ingestion input."""

    def __init__(self, resource: PoolResource, *,
                 authorize_write: Callable[[TrustedScope, str, str], Awaitable[bool]]) -> None:
        if not callable(authorize_write):
            raise InvalidRequest()
        self._resource = resource
        self._authorize_write = authorize_write

    async def ingest(
        self, source: str | bytes, *, collection: str, document_id: str, intent_id: str,
        source_locator: str, scope: TrustedScope, deadline: float,
        expected_generation_id: str | None = None, metadata: dict[str, object] | None = None,
        format: str = 'text/plain', canonical_options: dict[str, Any] | None = None,
        before_publish: Callable[[], Awaitable[None]] | None = None,
    ) -> IngestionReceipt:
        _check_deadline(deadline)
        collection = _identity(collection, 128)
        document_id, intent_id, source_locator = map(_identity, (document_id, intent_id, source_locator))
        if expected_generation_id is not None:
            expected_generation_id = _identity(expected_generation_id)
        if not isinstance(scope, TrustedScope):
            raise InvalidRequest()
        scope = parse_scope(scope.model_dump(mode='json'))
        for value in (scope.tenant_id, scope.principal_id, scope.authorization_revision, *scope.grant_ids):
            _identity(value)
        if before_publish is not None and not callable(before_publish):
            raise InvalidRequest()
        options = {} if canonical_options is None else canonical_options.copy() if type(canonical_options) is dict else canonical_options
        if type(options) is not dict or any(key not in ('max_source_bytes', 'target_bytes', 'max_chunk_bytes',
            'token_counter', 'tokenizer_id', 'token_target', 'max_tokens') for key in options):
            raise InvalidRequest()
        metadata_json, metadata_hash = _metadata({} if metadata is None else metadata)
        authorization_timer = asyncio.timeout_at(deadline)
        try:
            async with authorization_timer:
                allowed = await self._authorize_write(scope, collection, document_id)
        except TimeoutError:
            if authorization_timer.expired():
                raise DeadlineExceeded() from None
            raise
        _check_deadline(deadline)
        if allowed is not True:
            raise UnauthorizedScope()
        document = canonicalize(source, format=format, **options)
        payload, revision, generation = _identifiers(document, scope, collection, document_id,
                                                     intent_id, source_locator, metadata_hash, expected_generation_id)
        _check_deadline(deadline)
        receipt = IngestionReceipt(tenant_id=scope.tenant_id, collection=collection,
            document_id=document_id, intent_id=intent_id, revision_id=revision, generation_id=generation,
            payload_sha256=payload, canonical_sha256=document.canonical_sha256,
            chunk_count=len(document.chunks), replayed=False)
        async with self._resource.lease(deadline=deadline) as leased:
            connection = cast(SessionConnection, leased)
            return await self._transaction(connection, deadline, lambda: self._stage(connection, document,
                receipt, scope, source_locator, metadata_json, expected_generation_id, deadline, before_publish))

    async def _transaction(self, connection: SessionConnection, deadline: float,
                           stage: Callable[[], Awaitable[IngestionReceipt]]) -> IngestionReceipt:
        return await _write_transaction(connection, deadline, self._resource.config.release_timeout, stage)

    async def _stage(self, connection: SessionConnection, document: CanonicalDocument,
                     receipt: IngestionReceipt, scope: TrustedScope, locator: str, metadata_json: str,
                     expected: str | None, deadline: float,
                     hook: Callable[[], Awaitable[None]] | None) -> IngestionReceipt:
        async def query(sql: str, values: tuple[object, ...] | None = None) -> list[tuple[object, ...]]:
            return await _query(connection, sql, values, deadline)
        if await query(_WRITER_ROLE_SQL) != [(True,)]:
            raise UnauthorizedScope()
        if await query(_CATALOG_SQL) != [(True,)]:
            raise UnsupportedCapability()
        if tuple(await query(_HISTORY_SQL)) != EXPECTED_HISTORY:
            raise UnsupportedCapability()
        await query(_SCOPE_SQL, (scope.tenant_id, scope.principal_id, scope.authorization_revision,
                                _json(sorted(set(scope.grant_ids), key=lambda value: value.encode('utf-8')))))
        key = (scope.tenant_id, receipt.collection, receipt.document_id)
        await query(_LOCK_SQL, (_json(['cragkit.intent.v1', *key[:2], receipt.intent_id]),))
        await query(_LOCK_SQL, (_json(['cragkit.document.v1', *key]),))
        jobs = await query(_JOB_SQL, (*key[:2], receipt.intent_id))
        if jobs:
            if len(jobs) != 1 or jobs[0][0] != receipt.payload_sha256 or jobs[0][3] != receipt.document_id:
                raise InvalidRequest()
            if jobs[0][1:3] != (receipt.generation_id, 'succeeded'):
                raise IndexNotReady()
            documents = await query(_DOCUMENT_LOCK_SQL, key)
            self._authorize(documents, scope)
            await self._verify(connection, key, receipt, deadline)
            return receipt.model_copy(update={'replayed': True})
        await query('INSERT INTO cragkit.collections(tenant_id,collection_id) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING collection_id', key[:2])
        if await query(_COLLECTION_SQL, key[:2]) != [('0.1', 'native_fts.v1')]:
            raise UnsupportedCapability()
        created = await query('INSERT INTO cragkit.documents(tenant_id,collection_id,document_id,authorization_revision) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING document_id', (*key, scope.authorization_revision))
        documents = await query(_DOCUMENT_LOCK_SQL, key)
        self._authorize(documents, scope)
        if (not created and expected is None) or documents[0][0] != expected:
            raise IndexNotReady()
        await query('INSERT INTO cragkit.ingestion_jobs(tenant_id,collection_id,document_id,intent_id,payload_sha256,generation_id,state,attempt_count) VALUES (%s,%s,%s,%s,%s,%s,\'running\',1) RETURNING 1', (*key, receipt.intent_id, receipt.payload_sha256, receipt.generation_id))
        await query('INSERT INTO cragkit.document_revisions(tenant_id,collection_id,document_id,revision_id,source_sha256,source_locator,canonical_text,canonical_sha256,parser_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING revision_id', (*key, receipt.revision_id, document.source_sha256, locator, document.canonical_text, document.canonical_sha256, document.parser_id))
        if await query(_REVISION_SQL, (*key, receipt.revision_id)) != [(document.source_sha256, document.canonical_sha256, locator, document.parser_id)]:
            raise IntegrityViolation()
        await query('INSERT INTO cragkit.index_generations(tenant_id,collection_id,document_id,revision_id,generation_id,chunker_profile,lexical_profile,status,expected_chunk_count) VALUES (%s,%s,%s,%s,%s,%s,\'native_fts.v1\',\'staging\',%s) RETURNING 1', (*key, receipt.revision_id, receipt.generation_id, document.chunker_profile, len(document.chunks)))
        chunks_json = _json([{'chunk_id': chunk.chunk_id, 'ordinal': chunk.ordinal,
            'start_byte': chunk.start_byte, 'end_byte': chunk.end_byte, 'text': chunk.text,
            'text_sha256': chunk.text_sha256, 'metadata': {'oversized_split': chunk.oversized_split,
            'token_count': chunk.token_count, 'tokenizer_id': document.tokenizer_id}} for chunk in document.chunks])
        await query(_CHUNKS_SQL, (*key, receipt.revision_id, receipt.generation_id, chunks_json))
        await query(_LEXICAL_SQL, (*key, receipt.generation_id, _json({chunk.chunk_id: extract_identifiers(chunk.text) for chunk in document.chunks})))
        if created:
            principal_grant = _hash(['cragkit.principal.v1', scope.principal_id])
            await query('INSERT INTO cragkit.document_grants(tenant_id,collection_id,document_id,grant_id,principal_id,authorization_revision) VALUES (%s,%s,%s,%s,%s,%s) RETURNING 1', (*key, principal_grant, scope.principal_id, scope.authorization_revision))
        await self._counts(connection, key, receipt, deadline)
        if hook is not None:
            await hook()
        _check_deadline(deadline)
        if await query('UPDATE cragkit.index_generations SET status=\'ready\' WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s RETURNING 1', (*key, receipt.generation_id)) != [(1,)]:
            raise IntegrityViolation()
        changed = await query('UPDATE cragkit.documents SET active_generation_id=%s,metadata=%s::jsonb WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND active_generation_id IS NOT DISTINCT FROM %s AND NOT tombstoned AND authorization_revision=%s RETURNING 1', (receipt.generation_id, metadata_json, *key, expected, scope.authorization_revision))
        if changed != [(1,)]:
            raise IndexNotReady()
        if await query('UPDATE cragkit.ingestion_jobs SET state=\'succeeded\' WHERE tenant_id=%s AND collection_id=%s AND intent_id=%s AND payload_sha256=%s RETURNING 1', (*key[:2], receipt.intent_id, receipt.payload_sha256)) != [(1,)]:
            raise IntegrityViolation()
        return receipt

    @staticmethod
    def _authorize(rows: list[tuple[object, ...]], scope: TrustedScope) -> None:
        if len(rows) != 1 or len(rows[0]) != 3 or rows[0][1] is not False or rows[0][2] != scope.authorization_revision:
            raise UnauthorizedScope()

    async def _counts(self, connection: SessionConnection, key: tuple[str, str, str],
                      receipt: IngestionReceipt, deadline: float) -> None:
        values = (*key, receipt.generation_id)
        if await _query(connection, _COUNTS_SQL, (*values, *values), deadline) != [(receipt.chunk_count, receipt.chunk_count)]:
            raise IntegrityViolation()

    async def _verify(self, connection: SessionConnection, key: tuple[str, str, str],
                      receipt: IngestionReceipt, deadline: float) -> None:
        if await _query(connection, _GENERATION_SQL, (*key, receipt.generation_id), deadline) != [(receipt.revision_id, 'ready', receipt.chunk_count)]:
            raise IntegrityViolation()
        await self._counts(connection, key, receipt, deadline)
