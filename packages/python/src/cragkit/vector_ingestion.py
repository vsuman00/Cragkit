"""Explicit bounded shadow-vector staging; importing this module has no side effects."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, cast

from pydantic import ValidationError

from . import ingestion as lexical
from ._postgres_pool import PoolResource
from ._postgres_session import (EXPECTED_HISTORY, SessionConnection, _CATALOG_SQL, _COLLECTION_SQL,
                                _HISTORY_SQL, _SCOPE_SQL, _check_deadline, _query)
from .canonical import CanonicalDocument, canonicalize
from .contracts import TrustedScope, parse_scope
from .embeddings import EmbeddingAdapter, EmbeddingBatch, EmbeddingUsage, FAKE_PROFILE
from .errors import (DeadlineExceeded, EmbeddingProfileMismatch, IndexNotReady,
                     IntegrityViolation, InvalidRequest, UnauthorizedScope, UnsupportedCapability)


class VectorIngestionReceipt(lexical.IngestionReceipt):
    embedding_profile: str
    provider_calls: int
    usage: tuple[EmbeddingUsage, ...]


_VECTOR_CAPABILITY_SQL = """SELECT current_setting('server_encoding')='UTF8'
 AND EXISTS (SELECT 1 FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace
  WHERE e.extname='vector' AND e.extversion='0.8.0' AND n.nspname='cragkit_vector')
 AND EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
  JOIN pg_depend d ON d.classid='pg_type'::regclass AND d.objid=t.oid AND d.deptype='e'
  JOIN pg_extension e ON e.oid=d.refobjid AND d.refclassid='pg_extension'::regclass
  WHERE n.nspname='cragkit_vector' AND t.typname='vector' AND t.typtype='b' AND e.extname='vector'
  AND EXISTS (SELECT 1 FROM pg_proc p JOIN pg_depend pd ON pd.classid='pg_proc'::regclass AND pd.objid=p.oid AND pd.deptype='e'
   WHERE p.pronamespace=n.oid AND p.proname='vector_dims' AND p.pronargs=1 AND p.proargtypes[0]=t.oid
   AND p.prorettype='int4'::regtype AND NOT p.prosecdef AND pd.refclassid='pg_extension'::regclass AND pd.refobjid=e.oid))
 AND NOT EXISTS (SELECT 1 FROM (VALUES ('embedding_profiles'),('chunk_vectors_fake_1536')) expected(name)
  LEFT JOIN pg_namespace n ON n.nspname='cragkit' LEFT JOIN pg_class c ON c.relnamespace=n.oid AND c.relname=expected.name
  WHERE c.relkind IS DISTINCT FROM 'r' OR NOT coalesce(c.relrowsecurity,false))
 AND EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  JOIN pg_attribute a ON a.attrelid=c.oid AND a.attname='embedding' AND NOT a.attisdropped
  WHERE n.nspname='cragkit' AND c.relname='chunk_vectors_fake_1536'
   AND a.atttypid=to_regtype('cragkit_vector.vector') AND a.atttypmod=1536)
 AND NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname IN ('cragkit','cragkit_vector') AND p.prosecdef)
 AND NOT EXISTS (SELECT 1 FROM pg_namespace n WHERE n.nspname='cragkit_vector'
  AND (pg_has_role(current_user,n.nspowner,'MEMBER')
   OR has_schema_privilege(current_user,n.oid,'CREATE')))
 AND NOT EXISTS (SELECT 1 FROM pg_extension e WHERE e.extname='vector'
  AND pg_has_role(current_user,e.extowner,'MEMBER'))
 AND NOT EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='cragkit_vector' AND pg_has_role(current_user,p.proowner,'MEMBER'))
 AND NOT EXISTS (SELECT 1 FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
  WHERE n.nspname='cragkit_vector' AND pg_has_role(current_user,t.typowner,'MEMBER'))
 AND NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE n.nspname='cragkit_vector' AND c.relname='setup_history'
   AND (pg_has_role(current_user,c.relowner,'MEMBER') OR NOT row_security_active(c.oid)
    OR has_table_privilege(current_user,c.oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
    OR has_any_column_privilege(current_user,c.oid,'INSERT,UPDATE,REFERENCES')))"""
EXPECTED_VECTOR_HISTORY = (
    ('0001_pgvector', 'b98de4a67f46ab7cc7187447757b30844ceee01901a88186746ae322cf1a7e2c'),
    ('0002_vector_profiles', '33fda8141215cbdb961165822a13bc74639c97c41985529ce1b1b3ae585140fb'),
)
_SETUP_HISTORY_SQL = 'SELECT version,checksum FROM cragkit_vector.setup_history ORDER BY version'
_PROFILE_SQL = 'SELECT profile_id,provider,model,dimensions,tokenizer,normalization,storage_table FROM cragkit.embedding_profiles ORDER BY profile_id'
_VECTOR_JOB_SQL = """SELECT payload_sha256,generation_id,state,document_id,attempt_count
FROM cragkit.ingestion_jobs WHERE tenant_id=%s AND collection_id=%s AND intent_id=%s FOR UPDATE"""
_VECTOR_GENERATION_SQL = """SELECT revision_id,status,expected_chunk_count,embedding_profile,chunker_profile,lexical_profile
FROM cragkit.index_generations WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s"""
_VECTOR_REVISION_SQL = """SELECT source_sha256,canonical_sha256,source_locator,parser_id,canonical_text
FROM cragkit.document_revisions WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND revision_id=%s"""
_MANIFEST_SQL = """SELECT chunk_id,ordinal,start_byte,end_byte,text,text_sha256,metadata FROM cragkit.chunks
WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s ORDER BY ordinal"""
_MISSING_SQL = """SELECT c.chunk_id FROM cragkit.chunks c
LEFT JOIN cragkit.chunk_vectors_fake_1536 v ON v.tenant_id=c.tenant_id AND v.collection_id=c.collection_id
 AND v.document_id=c.document_id AND v.revision_id=c.revision_id AND v.generation_id=c.generation_id AND v.chunk_id=c.chunk_id
WHERE c.tenant_id=%s AND c.collection_id=%s AND c.document_id=%s AND c.generation_id=%s
 AND v.chunk_id IS NULL ORDER BY c.ordinal"""
_VECTOR_COUNTS_SQL = """SELECT count(*) FROM cragkit.chunk_vectors_fake_1536
WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s AND embedding_profile=%s"""
_GRANTS_SQL = """SELECT EXISTS(SELECT 1 FROM cragkit.document_grants WHERE tenant_id=%s AND collection_id=%s
 AND document_id=%s AND authorization_revision=%s
 AND (principal_id=%s OR (principal_id IS NULL AND grant_id=ANY(%s::text[]))))"""
_VECTOR_INSERT_SQL = """INSERT INTO cragkit.chunk_vectors_fake_1536
(tenant_id,collection_id,document_id,revision_id,generation_id,embedding_profile,chunk_id,embedding)
SELECT %s,%s,%s,%s,%s,%s,x.chunk_id,x.embedding::cragkit_vector.vector(1536)
FROM jsonb_to_recordset(%s::jsonb) AS x(chunk_id text,embedding text)
ON CONFLICT DO NOTHING RETURNING chunk_id"""


@dataclass(frozen=True)
class _Prepared:
    document: CanonicalDocument
    receipt: VectorIngestionReceipt
    scope: TrustedScope
    locator: str
    metadata_json: str
    expected: str | None

    @property
    def key(self) -> tuple[str, str, str]:
        return self.scope.tenant_id, self.receipt.collection, self.receipt.document_id


def _chunk_rows(document: CanonicalDocument) -> list[dict[str, object]]:
    return [dict(chunk_id=c.chunk_id, ordinal=c.ordinal, start_byte=c.start_byte, end_byte=c.end_byte,
                 text=c.text, text_sha256=c.text_sha256,
                 metadata=dict(oversized_split=c.oversized_split, token_count=c.token_count,
                               tokenizer_id=document.tokenizer_id)) for c in document.chunks]


class PostgresVectorIndexer:
    """Bind the write authorizer and an explicitly provisioned embedding adapter."""

    def __init__(self, resource: PoolResource, *,
                 authorize_write: Callable[[TrustedScope, str, str], Awaitable[bool]],
                 embedder: EmbeddingAdapter, max_batches: int = 128, max_attempts: int = 8) -> None:
        if not callable(authorize_write) or not isinstance(embedder, EmbeddingAdapter):
            raise InvalidRequest()
        if type(max_batches) is not int or not 1 <= max_batches <= 128 or type(max_attempts) is not int or not 1 <= max_attempts <= 8:
            raise InvalidRequest()
        if embedder.profile != FAKE_PROFILE:
            raise UnsupportedCapability()
        self._resource, self._authorize_write, self._embedder = resource, authorize_write, embedder
        self._max_batches, self._max_attempts = max_batches, max_attempts
        self._inflight = False

    async def _prepare(self, source: str | bytes, *, collection: str, document_id: str, intent_id: str,
                       source_locator: str, scope: TrustedScope, deadline: float,
                       expected_generation_id: str | None, metadata: dict[str, object] | None,
                       format: str, canonical_options: dict[str, Any] | None) -> _Prepared:
        _check_deadline(deadline)
        collection = lexical._identity(collection, 128)
        document_id, intent_id, source_locator = map(lexical._identity, (document_id, intent_id, source_locator))
        if expected_generation_id is not None:
            expected_generation_id = lexical._identity(expected_generation_id)
        if not isinstance(scope, TrustedScope):
            raise InvalidRequest()
        scope = parse_scope(scope.model_dump(mode='json'))
        for value in (scope.tenant_id, scope.principal_id, scope.authorization_revision, *scope.grant_ids):
            lexical._identity(value)
        options = {} if canonical_options is None else canonical_options.copy() if type(canonical_options) is dict else canonical_options
        if type(options) is not dict or any(key not in ('max_source_bytes', 'target_bytes', 'max_chunk_bytes',
            'token_counter', 'tokenizer_id', 'token_target', 'max_tokens') for key in options):
            raise InvalidRequest()
        metadata_json, metadata_hash = lexical._metadata({} if metadata is None else metadata)
        await self._authorize_application(scope, collection, document_id, deadline)
        document = canonicalize(source, format=format, **options)
        base, revision, _ = lexical._identifiers(document, scope, collection, document_id, intent_id,
                                                source_locator, metadata_hash, expected_generation_id)
        payload = lexical._hash(['cragkit.vector-ingest.v1', base, list(FAKE_PROFILE.model_dump().values())])
        generation = lexical._hash(['cragkit.vector-generation.v1', payload])
        receipt = VectorIngestionReceipt(tenant_id=scope.tenant_id, collection=collection, document_id=document_id,
            intent_id=intent_id, revision_id=revision, generation_id=generation, payload_sha256=payload,
            canonical_sha256=document.canonical_sha256, chunk_count=len(document.chunks), replayed=False,
            embedding_profile=FAKE_PROFILE.profile_id, provider_calls=0, usage=())
        return _Prepared(document, receipt, scope, source_locator, metadata_json, expected_generation_id)

    async def _authorize_application(self, scope: TrustedScope, collection: str, document_id: str, deadline: float) -> None:
        timer = asyncio.timeout_at(deadline)
        try:
            async with timer:
                allowed = await self._authorize_write(scope, collection, document_id)
        except TimeoutError:
            if timer.expired():
                raise DeadlineExceeded() from None
            raise
        _check_deadline(deadline)
        if allowed is not True:
            raise UnauthorizedScope()

    async def _transaction(self, prepared: _Prepared, deadline: float,
                           work: Callable[[SessionConnection], Awaitable[VectorIngestionReceipt]]) -> VectorIngestionReceipt:
        await self._authorize_application(prepared.scope, prepared.receipt.collection, prepared.receipt.document_id, deadline)
        async with self._resource.lease(deadline=deadline) as leased:
            connection = cast(SessionConnection, leased)
            async def run() -> VectorIngestionReceipt:
                await self._bind(connection, prepared, deadline)
                return await work(connection)
            return await lexical._write_transaction(connection, deadline, self._resource.config.release_timeout, run)

    async def _bind(self, connection: SessionConnection, prepared: _Prepared, deadline: float) -> None:
        async def query(sql: str, values: tuple[object, ...] | None = None) -> list[tuple[object, ...]]:
            return await _query(connection, sql, values, deadline)
        if await query(lexical._WRITER_ROLE_SQL) != [(True,)]:
            raise UnauthorizedScope()
        if await query(_CATALOG_SQL) != [(True,)] or tuple(await query(_HISTORY_SQL)) != EXPECTED_HISTORY:
            raise UnsupportedCapability()
        if await query(_VECTOR_CAPABILITY_SQL) != [(True,)]:
            raise UnsupportedCapability()
        if tuple(await query(_SETUP_HISTORY_SQL)) != EXPECTED_VECTOR_HISTORY:
            raise UnsupportedCapability()
        if await query(_PROFILE_SQL) != [(*FAKE_PROFILE.model_dump().values(), 'chunk_vectors_fake_1536')]:
            raise UnsupportedCapability()
        scope = prepared.scope
        await query(_SCOPE_SQL, (scope.tenant_id, scope.principal_id, scope.authorization_revision,
            lexical._json(sorted(set(scope.grant_ids), key=lambda value: value.encode('utf-8')))))
        await query(lexical._LOCK_SQL, (lexical._json(['cragkit.intent.v1', *prepared.key[:2], prepared.receipt.intent_id]),))
        await query(lexical._LOCK_SQL, (lexical._json(['cragkit.document.v1', *prepared.key]),))

    async def _authorized(self, connection: SessionConnection, prepared: _Prepared, deadline: float, *,
                          require_expected: bool = False) -> list[tuple[object, ...]]:
        rows = await _query(connection, lexical._DOCUMENT_LOCK_SQL, prepared.key, deadline)
        lexical.PostgresIndexer._authorize(rows, prepared.scope)
        if await _query(connection, _GRANTS_SQL, (*prepared.key, prepared.scope.authorization_revision,
            prepared.scope.principal_id, list(prepared.scope.grant_ids)), deadline) != [(True,)]:
            raise UnauthorizedScope()
        if require_expected and rows[0][0] != prepared.expected:
            raise IndexNotReady()
        return rows

    async def _manifest(self, connection: SessionConnection, prepared: _Prepared, deadline: float, *, ready: bool = False) -> None:
        r, d = prepared.receipt, prepared.document
        if await _query(connection, _VECTOR_REVISION_SQL, (*prepared.key, r.revision_id), deadline) != [
            (d.source_sha256, d.canonical_sha256, prepared.locator, d.parser_id, d.canonical_text)]:
            raise IntegrityViolation()
        if await _query(connection, _VECTOR_GENERATION_SQL, (*prepared.key, r.generation_id), deadline) != [
            (r.revision_id, 'ready' if ready else 'staging', r.chunk_count, FAKE_PROFILE.profile_id, d.chunker_profile, 'native_fts.v1')]:
            raise IntegrityViolation()
        expected = [tuple(row.values()) for row in _chunk_rows(d)]
        if await _query(connection, _MANIFEST_SQL, (*prepared.key, r.generation_id), deadline) != expected:
            raise IntegrityViolation()
        values = (*prepared.key, r.generation_id)
        if await _query(connection, lexical._COUNTS_SQL, (*values, *values), deadline) != [(r.chunk_count, r.chunk_count)]:
            raise IntegrityViolation()

    def _batches(self, prepared: _Prepared, missing: list[str]) -> list[list[str]]:
        chunks = {chunk.chunk_id: chunk.text for chunk in prepared.document.chunks}
        if len(missing) != len(set(missing)) or any(chunk_id not in chunks for chunk_id in missing):
            raise IntegrityViolation()
        batches: list[list[str]] = []
        for chunk_id in missing:
            if not batches:
                batches.append([])
            candidate = [chunks[key] for key in (*batches[-1], chunk_id)]
            try:
                self._embedder._inputs(candidate)
            except InvalidRequest:
                if not batches[-1]:
                    raise
                self._embedder._inputs([chunks[chunk_id]])
                if len(batches) >= self._max_batches:
                    raise InvalidRequest()
                batches.append([])
            batches[-1].append(chunk_id)
        if len(batches) > self._max_batches:
            raise InvalidRequest()
        return batches

    async def stage(self, source: str | bytes, *, collection: str, document_id: str, intent_id: str,
                    source_locator: str, scope: TrustedScope, deadline: float,
                    expected_generation_id: str | None = None, metadata: dict[str, object] | None = None,
                    format: str = 'text/plain', canonical_options: dict[str, Any] | None = None) -> VectorIngestionReceipt:
        if self._inflight:
            raise IndexNotReady()
        self._inflight = True
        try:
            return await self._stage_operation(source, collection=collection, document_id=document_id,
                intent_id=intent_id, source_locator=source_locator, scope=scope, deadline=deadline,
                expected_generation_id=expected_generation_id, metadata=metadata, format=format,
                canonical_options=canonical_options)
        finally:
            self._inflight = False

    async def _stage_operation(self, source: str | bytes, *, collection: str, document_id: str, intent_id: str,
                    source_locator: str, scope: TrustedScope, deadline: float,
                    expected_generation_id: str | None = None, metadata: dict[str, object] | None = None,
                    format: str = 'text/plain', canonical_options: dict[str, Any] | None = None) -> VectorIngestionReceipt:
        prepared = await self._prepare(source, collection=collection, document_id=document_id, intent_id=intent_id,
            source_locator=source_locator, scope=scope, deadline=deadline, expected_generation_id=expected_generation_id,
            metadata=metadata, format=format, canonical_options=canonical_options)
        self._batches(prepared, [chunk.chunk_id for chunk in prepared.document.chunks])
        missing: list[str] = []
        async def initial(connection: SessionConnection) -> VectorIngestionReceipt:
            nonlocal missing
            result = await self._stage_initial(connection, prepared, deadline)
            if not result.replayed:
                rows = await _query(connection, _MISSING_SQL, (*prepared.key, result.generation_id), deadline)
                if any(len(row) != 1 or type(row[0]) is not str for row in rows):
                    raise IntegrityViolation()
                missing = [cast(str, row[0]) for row in rows]
            return result
        result = await self._transaction(prepared, deadline, initial)
        chunks = {chunk.chunk_id: chunk.text for chunk in prepared.document.chunks}
        usage: list[EmbeddingUsage] = []
        for batch_ids in self._batches(prepared, missing):
            # Recheck the persisted source and current grants immediately before disclosure.
            async def check(connection: SessionConnection) -> VectorIngestionReceipt:
                await self._authorized(connection, prepared, deadline, require_expected=True)
                await self._manifest(connection, prepared, deadline)
                return prepared.receipt
            await self._transaction(prepared, deadline, check)
            response = await self._embedder.embed_batch([chunks[key] for key in batch_ids], deadline=deadline)
            self._validate_batch(response, len(batch_ids))
            usage.append(response.usage)
            async def store(connection: SessionConnection) -> VectorIngestionReceipt:
                await self._authorized(connection, prepared, deadline, require_expected=True)
                await self._manifest(connection, prepared, deadline)
                rows = [dict(chunk_id=key, embedding=lexical._json(list(vector)))
                        for key, vector in zip(batch_ids, response.vectors, strict=True)]
                await _query(connection, _VECTOR_INSERT_SQL, (*prepared.key, prepared.receipt.revision_id,
                    prepared.receipt.generation_id, FAKE_PROFILE.profile_id, lexical._json(rows)), deadline)
                return prepared.receipt
            await self._transaction(prepared, deadline, store)
        if not result.replayed:
            async def finish(connection: SessionConnection) -> VectorIngestionReceipt:
                await self._authorized(connection, prepared, deadline, require_expected=True)
                await self._manifest(connection, prepared, deadline)
                if await _query(connection, _VECTOR_COUNTS_SQL, (*prepared.key, prepared.receipt.generation_id, FAKE_PROFILE.profile_id), deadline) != [(prepared.receipt.chunk_count,)]:
                    raise IntegrityViolation()
                return prepared.receipt
            await self._transaction(prepared, deadline, finish)
        return result.model_copy(update={'provider_calls': len(usage), 'usage': tuple(usage)})

    @staticmethod
    def _validate_batch(response: EmbeddingBatch, count: int) -> None:
        if not isinstance(response, EmbeddingBatch):
            raise IntegrityViolation()
        if response.profile != FAKE_PROFILE:
            raise EmbeddingProfileMismatch()
        try:
            checked = EmbeddingBatch.model_validate(response.model_dump())
        except (ValidationError, TypeError, ValueError):
            raise IntegrityViolation() from None
        if any(len(vector) != FAKE_PROFILE.dimensions for vector in checked.vectors):
            raise EmbeddingProfileMismatch()
        import math
        if len(checked.vectors) != count or not checked.synthetic or checked.provider_calls != 1:
            raise IntegrityViolation()
        if any(any(not math.isfinite(x) for x in vector) or abs(math.sqrt(sum(x*x for x in vector))-1) > 0.001 for vector in checked.vectors):
            raise IntegrityViolation()

    async def _stage_initial(self, connection: SessionConnection, prepared: _Prepared, deadline: float) -> VectorIngestionReceipt:
        r, d, key = prepared.receipt, prepared.document, prepared.key
        async def query(sql: str, values: tuple[object, ...] | None = None) -> list[tuple[object, ...]]:
            return await _query(connection, sql, values, deadline)
        jobs = await query(_VECTOR_JOB_SQL, (*key[:2], r.intent_id))
        if jobs:
            if len(jobs) != 1 or jobs[0][0] != r.payload_sha256 or jobs[0][3] != r.document_id:
                raise InvalidRequest()
            if jobs[0][1] != r.generation_id or jobs[0][2] not in ('running', 'succeeded'):
                raise IndexNotReady()
            succeeded = jobs[0][2] == 'succeeded'
            await self._authorized(connection, prepared, deadline, require_expected=not succeeded)
            await self._manifest(connection, prepared, deadline, ready=succeeded)
            if succeeded:
                if await query(_VECTOR_COUNTS_SQL, (*key, r.generation_id, FAKE_PROFILE.profile_id)) != [(r.chunk_count,)]:
                    raise IntegrityViolation()
                return r.model_copy(update={'replayed': True})
            if type(jobs[0][4]) is not int or jobs[0][4] < 1 or jobs[0][4] >= self._max_attempts:
                raise IndexNotReady()
            await query("UPDATE cragkit.ingestion_jobs SET attempt_count=attempt_count+1 WHERE tenant_id=%s AND collection_id=%s AND intent_id=%s RETURNING 1", (*key[:2], r.intent_id))
            return r
        await query('INSERT INTO cragkit.collections(tenant_id,collection_id) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING collection_id', key[:2])
        if await query(_COLLECTION_SQL, key[:2]) != [('0.1', 'native_fts.v1')]:
            raise UnsupportedCapability()
        created = await query('INSERT INTO cragkit.documents(tenant_id,collection_id,document_id,authorization_revision) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING document_id', (*key, prepared.scope.authorization_revision))
        documents = await query(lexical._DOCUMENT_LOCK_SQL, key)
        lexical.PostgresIndexer._authorize(documents, prepared.scope)
        if (not created and prepared.expected is None) or documents[0][0] != prepared.expected:
            raise IndexNotReady()
        if created:
            grant = lexical._hash(['cragkit.principal.v1', prepared.scope.principal_id])
            await query('INSERT INTO cragkit.document_grants(tenant_id,collection_id,document_id,grant_id,principal_id,authorization_revision) VALUES (%s,%s,%s,%s,%s,%s) RETURNING 1', (*key, grant, prepared.scope.principal_id, prepared.scope.authorization_revision))
        await self._authorized(connection, prepared, deadline)
        await query("INSERT INTO cragkit.ingestion_jobs(tenant_id,collection_id,document_id,intent_id,payload_sha256,generation_id,state,attempt_count) VALUES (%s,%s,%s,%s,%s,%s,'running',1) RETURNING 1", (*key, r.intent_id, r.payload_sha256, r.generation_id))
        await query('INSERT INTO cragkit.document_revisions(tenant_id,collection_id,document_id,revision_id,source_sha256,source_locator,canonical_text,canonical_sha256,parser_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING revision_id', (*key, r.revision_id, d.source_sha256, prepared.locator, d.canonical_text, d.canonical_sha256, d.parser_id))
        await query("INSERT INTO cragkit.index_generations(tenant_id,collection_id,document_id,revision_id,generation_id,chunker_profile,lexical_profile,embedding_profile,status,expected_chunk_count) VALUES (%s,%s,%s,%s,%s,%s,'native_fts.v1',%s,'staging',%s) RETURNING 1", (*key, r.revision_id, r.generation_id, d.chunker_profile, FAKE_PROFILE.profile_id, r.chunk_count))
        await query(lexical._CHUNKS_SQL, (*key, r.revision_id, r.generation_id, lexical._json(_chunk_rows(d))))
        await query(lexical._LEXICAL_SQL, (*key, r.generation_id))
        await self._manifest(connection, prepared, deadline)
        return r

    async def publish(self, source: str | bytes, *, collection: str, document_id: str, intent_id: str,
                      source_locator: str, scope: TrustedScope, deadline: float,
                      expected_generation_id: str | None = None, metadata: dict[str, object] | None = None,
                      format: str = 'text/plain', canonical_options: dict[str, Any] | None = None,
                      before_publish: Callable[[], Awaitable[None]] | None = None) -> VectorIngestionReceipt:
        if self._inflight:
            raise IndexNotReady()
        self._inflight = True
        try:
            return await self._publish_operation(source, collection=collection, document_id=document_id,
                intent_id=intent_id, source_locator=source_locator, scope=scope, deadline=deadline,
                expected_generation_id=expected_generation_id, metadata=metadata, format=format,
                canonical_options=canonical_options, before_publish=before_publish)
        finally:
            self._inflight = False

    async def _publish_operation(self, source: str | bytes, *, collection: str, document_id: str, intent_id: str,
                                 source_locator: str, scope: TrustedScope, deadline: float,
                                 expected_generation_id: str | None, metadata: dict[str, object] | None,
                                 format: str, canonical_options: dict[str, Any] | None,
                                 before_publish: Callable[[], Awaitable[None]] | None) -> VectorIngestionReceipt:
        if before_publish is not None and not callable(before_publish):
            raise InvalidRequest()
        prepared = await self._prepare(source, collection=collection, document_id=document_id, intent_id=intent_id,
            source_locator=source_locator, scope=scope, deadline=deadline, expected_generation_id=expected_generation_id,
            metadata=metadata, format=format, canonical_options=canonical_options)
        async def publish(connection: SessionConnection) -> VectorIngestionReceipt:
            r, key = prepared.receipt, prepared.key
            async def query(sql: str, values: tuple[object, ...] | None = None) -> list[tuple[object, ...]]:
                return await _query(connection, sql, values, deadline)
            jobs = await query(_VECTOR_JOB_SQL, (*key[:2], r.intent_id))
            if not jobs:
                raise IndexNotReady()
            if len(jobs) != 1 or jobs[0][0] != r.payload_sha256 or jobs[0][3] != r.document_id:
                raise InvalidRequest()
            if jobs[0][1] != r.generation_id or jobs[0][2] not in ('running', 'succeeded'):
                raise IndexNotReady()
            succeeded = jobs[0][2] == 'succeeded'
            async def barrier() -> None:
                await self._authorized(connection, prepared, deadline, require_expected=not succeeded)
                await self._manifest(connection, prepared, deadline, ready=succeeded)
                if await query(_VECTOR_COUNTS_SQL, (*key, r.generation_id, FAKE_PROFILE.profile_id)) != [(r.chunk_count,)]:
                    raise IntegrityViolation()
            await barrier()
            if succeeded:
                return r.model_copy(update={'replayed': True})
            if before_publish is not None:
                await before_publish()
            _check_deadline(deadline)
            # Hooks may await application work; authorization is checked again before mutation.
            await self._authorize_application(prepared.scope, r.collection, r.document_id, deadline)
            await barrier()
            if await query("UPDATE cragkit.index_generations SET status='ready' WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s AND status='staging' AND embedding_profile=%s RETURNING 1", (*key, r.generation_id, FAKE_PROFILE.profile_id)) != [(1,)]:
                raise IntegrityViolation()
            changed = await query('UPDATE cragkit.documents SET active_generation_id=%s,metadata=%s::jsonb WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND active_generation_id IS NOT DISTINCT FROM %s AND NOT tombstoned AND authorization_revision=%s RETURNING 1', (r.generation_id, prepared.metadata_json, *key, prepared.expected, prepared.scope.authorization_revision))
            if changed != [(1,)]:
                raise IndexNotReady()
            if await query("UPDATE cragkit.ingestion_jobs SET state='succeeded' WHERE tenant_id=%s AND collection_id=%s AND intent_id=%s AND payload_sha256=%s AND generation_id=%s AND state='running' RETURNING 1", (*key[:2], r.intent_id, r.payload_sha256, r.generation_id)) != [(1,)]:
                raise IntegrityViolation()
            return r
        return await self._transaction(prepared, deadline, publish)

    async def ingest(self, source: str | bytes, *, collection: str, document_id: str, intent_id: str,
                     source_locator: str, scope: TrustedScope, deadline: float,
                     expected_generation_id: str | None = None, metadata: dict[str, object] | None = None,
                     format: str = 'text/plain', canonical_options: dict[str, Any] | None = None,
                     before_publish: Callable[[], Awaitable[None]] | None = None) -> VectorIngestionReceipt:
        if self._inflight:
            raise IndexNotReady()
        if before_publish is not None and not callable(before_publish):
            raise InvalidRequest()
        self._inflight = True
        try:
            # One operation owns one input snapshot, including the convenience path.
            metadata = json.loads(lexical._metadata({} if metadata is None else metadata)[0])
            canonical_options = canonical_options.copy() if type(canonical_options) is dict else canonical_options
            staged = await self._stage_operation(source, collection=collection, document_id=document_id,
                intent_id=intent_id, source_locator=source_locator, scope=scope, deadline=deadline,
                expected_generation_id=expected_generation_id, metadata=metadata, format=format,
                canonical_options=canonical_options)
            published = await self._publish_operation(source, collection=collection, document_id=document_id,
                intent_id=intent_id, source_locator=source_locator, scope=scope, deadline=deadline,
                expected_generation_id=expected_generation_id, metadata=metadata, format=format,
                canonical_options=canonical_options, before_publish=before_publish)
            return published.model_copy(update={'provider_calls': staged.provider_calls, 'usage': staged.usage})
        finally:
            self._inflight = False
