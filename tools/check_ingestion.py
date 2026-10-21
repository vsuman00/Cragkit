"""Synthetic ingestion checks called only by the explicitly authorized fixture owner."""
from __future__ import annotations


class IngestionCheckError(RuntimeError):
    """Contains a fixed diagnostic code, never driver or source details."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise IngestionCheckError(code)


async def run(config, fixture: dict, admin) -> dict:
    import asyncio
    import hashlib
    from cragkit._postgres_pool import PoolResource
    from cragkit.canonical import canonicalize
    from cragkit.contracts import parse_scope
    from cragkit.ingestion import PostgresIndexer
    from cragkit.errors import IndexNotReady, InvalidRequest, UnauthorizedScope

    scopes = [parse_scope(value) for value in fixture['scopes']]
    require(len(scopes) == 2 and scopes[0].tenant_id != scopes[1].tenant_id, 'fixture_scope_shape')
    collection = fixture['collection']
    document = 'ingestion-shared-document'
    resource = PoolResource(config.model_copy(update={'max_size': 1}))
    checks: list[str] = []
    loop = asyncio.get_running_loop()

    async def rows(query, params=None):
        async with asyncio.timeout(10):
            cursor = await admin.execute(query, params)
            return await cursor.fetchall()

    async def snapshot():
        output = []
        for table in ('collections', 'documents', 'document_revisions', 'index_generations',
                      'chunks', 'chunk_lexical', 'document_grants', 'ingestion_jobs'):
            # Table names are a closed library-owned allowlist.
            output.append(await rows(f'SELECT count(*) FROM cragkit.{table}'))
        output.append(await rows('SELECT tenant_id,document_id,active_generation_id FROM cragkit.documents ORDER BY tenant_id,document_id'))
        return output

    async def ingest(indexer, source, **changes):
        arguments = dict(collection=collection, document_id=document, intent_id='initial-intent',
                         source_locator='synthetic:ingestion', scope=scopes[0], deadline=loop.time() + 15,
                         canonical_options={'target_bytes': 8, 'max_chunk_bytes': 16},
                         metadata={'unicode': 'Café🙂', 'nested': [None, True, 1.25]})
        arguments.update(changes)
        return await indexer.ingest(source, **arguments)

    try:
        await resource.open()
        async with resource.lease(deadline=loop.time() + 8) as connection:
            cursor = await connection.execute('SELECT current_user=session_user,current_user=%s,ssl FROM pg_stat_ssl WHERE pid=pg_backend_pid()', (config.user,))
            identity = await cursor.fetchall()
            require(identity == [(True, True, True)], 'actual_writer_login_tls')
            cursor = await connection.execute('SELECT count(*) FROM cragkit.documents')
            require(await cursor.fetchall() == [(0,)], 'unscoped_writer_rls')
            await connection.rollback()
        checks.append('actual_writer_login_tls_rls')
        async def authorize_write(scope, target_collection, target_document):
            return (scope in scopes and target_collection == collection
                    and target_document in (document, 'other-document'))
        indexer = PostgresIndexer(resource, authorize_write=authorize_write)
        source = '\ufeffCafé🙂\r\n\r\nUnicode source\n'
        first = await ingest(indexer, source)
        require(first.replayed is False and first.chunk_count > 1, 'initial_receipt')
        before = await snapshot()
        denied = False
        try:
            await ingest(indexer, 'unauthorized replacement', scope=scopes[0].model_copy(update={'principal_id': 'unauthorized-principal'}),
                         intent_id='unauthorized-intent', expected_generation_id=first.generation_id)
        except UnauthorizedScope:
            denied = True
        require(denied and await snapshot() == before, 'unauthorized_write_changed_storage')
        checks.append('separate_write_authorization_denies_same_tenant_principal')
        replay = await ingest(indexer, source)
        require(replay.replayed is True and replay.generation_id == first.generation_id
                and replay.revision_id == first.revision_id and replay.payload_sha256 == first.payload_sha256, 'intent_replay')
        require(await snapshot() == before, 'replay_changed_storage')
        for changed in ({'source': source + 'changed'}, {'document_id': 'other-document'}):
            changed_source = changed.get('source', source)
            arguments = {key: value for key, value in changed.items() if key != 'source'}
            rejected = False
            try:
                await ingest(indexer, changed_source, **arguments)
            except InvalidRequest as error:
                rejected = error.__cause__ is None
            require(rejected, 'intent_conflict_accepted')
        require(await snapshot() == before, 'conflict_changed_storage')
        checks.append('intent_replay_payload_document_conflicts')

        canonical = canonicalize(source, target_bytes=8, max_chunk_bytes=16)
        revision = await rows('SELECT source_sha256,canonical_sha256,canonical_text FROM cragkit.document_revisions WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND revision_id=%s',
                              (scopes[0].tenant_id, collection, document, first.revision_id))
        require(revision == [(canonical.source_sha256, canonical.canonical_sha256, canonical.canonical_text)], 'stored_revision_digest')
        stored = await rows('SELECT c.start_byte,c.end_byte,c.text,c.text_sha256,l.search_vector=to_tsvector(l.language_config::regconfig,c.text) FROM cragkit.chunks c JOIN cragkit.chunk_lexical l USING(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id) WHERE c.tenant_id=%s AND c.collection_id=%s AND c.document_id=%s AND c.generation_id=%s ORDER BY c.ordinal',
                            (scopes[0].tenant_id, collection, document, first.generation_id))
        require(len(stored) == first.chunk_count, 'stored_chunk_count')
        raw = canonical.canonical_text.encode('utf-8')
        for start, end, text, digest, vector_ok in stored:
            require(raw[start:end].decode('utf-8') == text and hashlib.sha256(text.encode()).hexdigest() == digest and vector_ok is True, 'stored_span_digest_vector')
        checks.append('canonical_unicode_spans_digests_native_fts')

        second = await ingest(indexer, 'independent tenant text🙂', scope=scopes[1])
        require(second.tenant_id == scopes[1].tenant_id and second.generation_id != first.generation_id, 'tenant_intent_isolation')
        require(await rows('SELECT count(*) FROM cragkit.documents WHERE collection_id=%s AND document_id=%s', (collection, document)) == [(2,)], 'tenant_document_isolation')
        checks.append('same_intent_document_two_tenants')
        before = await snapshot()
        sentinel = RuntimeError('synthetic prepublication sentinel')

        async def fail_before_publish():
            raise sentinel

        caught = False
        try:
            await ingest(indexer, 'unpublished new revision🙂', intent_id='failing-intent',
                         expected_generation_id=first.generation_id, before_publish=fail_before_publish)
        except RuntimeError as error:
            caught = error is sentinel
        require(caught, 'prepublication_callback_identity')
        require(await snapshot() == before, 'prepublication_failure_not_atomic')
        checks.append('prepublication_failure_preserves_previous_generation')

        updated = await ingest(indexer, 'published replacement🙂', intent_id='replacement-intent', expected_generation_id=first.generation_id)
        before = await snapshot()
        rejected = False
        try:
            await ingest(indexer, 'stale writer content', intent_id='stale-intent', expected_generation_id=first.generation_id)
        except IndexNotReady:
            rejected = True
        require(rejected and await snapshot() == before, 'stale_generation_publish')
        require(updated.generation_id != first.generation_id, 'replacement_generation')
        checks.append('compare_and_swap_rejects_stale_generation')

        entered = asyncio.Event()
        async def wait_before_publish():
            entered.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(ingest(indexer, 'cancelled staged revision🙂', intent_id='cancelled-intent',
                                         expected_generation_id=updated.generation_id, before_publish=wait_before_publish))
        try:
            async with asyncio.timeout(12):
                await entered.wait()
            task.cancel()
            cancelled = False
            try:
                await task
            except asyncio.CancelledError:
                cancelled = True
            require(cancelled, 'ingestion_cancellation_suppressed')
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        require(await snapshot() == before, 'cancelled_ingestion_not_atomic')
        replay = await ingest(indexer, 'published replacement🙂', intent_id='replacement-intent', expected_generation_id=first.generation_id)
        require(replay.replayed is True, 'pool_not_reusable_after_cancellation')
        checks.append('cancelled_staging_rollback_pool_reuse')
        return {'state': 'passed', 'checks': checks}
    finally:
        await resource.close()
