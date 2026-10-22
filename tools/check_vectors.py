"""Synthetic native vector-generation checks; called by the explicit fixture owner."""
from __future__ import annotations

import asyncio
import json


class VectorCheckError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise VectorCheckError(code)


async def run(config, fixture: dict, admin, *, typescript: bool = False, neon: bool = False) -> dict:
    from psycopg import sql
    from cragkit._postgres_pool import PoolResource
    from cragkit._postgres_session import PostgresSession
    from cragkit.contracts import parse_request, parse_scope
    from cragkit.embeddings import EmbeddingAdapter, EmbeddingLimits
    from cragkit.ingestion import PostgresIndexer
    from cragkit.vector_ingestion import PostgresVectorIndexer
    from cragkit.errors import InvalidRequest, ProviderUnavailable, EmbeddingProfileMismatch

    scopes = [parse_scope(value) for value in fixture['scopes']]
    collection = fixture['collection']
    resource = PoolResource(config.model_copy(update={'max_size': 1}))
    loop = asyncio.get_running_loop()
    checks = []
    state = {'calls': 0, 'fail_at': None, 'wrong_model': False}

    class Counter:
        name = 'fake-byte-v1'
        def count(self, value):
            return len(value.encode('utf-8'))

    async def rows(query, values=None):
        async with asyncio.timeout(8):
            return await (await admin.execute(query, values)).fetchall()

    async def transport(body, *, deadline, max_response_bytes):
        state['calls'] += 1
        # Actual PostgreSQL observation while provider code is executing.
        require(await rows("SELECT count(*) FROM pg_stat_activity WHERE usename=%s AND state='idle in transaction'", (config.user,)) == [(0,)], 'model_called_inside_transaction')
        if state['fail_at'] == state['calls']:
            raise RuntimeError('synthetic provider failure')
        data = json.loads(body)
        vector = [1.0] + [0.0] * 1535
        return json.dumps({'model': 'other-model' if state['wrong_model'] else data['model'],
                          'data': [{'index': i, 'embedding': vector} for i in range(len(data['input']))]}).encode()

    async def authorize(scope, target, document):
        return scope in scopes and target == collection and document in ('vector-shared', 'vector-node')

    adapter = EmbeddingAdapter(transport, Counter(), limits=EmbeddingLimits(max_items=1))
    indexer = PostgresVectorIndexer(resource, authorize_write=authorize, embedder=adapter)
    lexical = PostgresIndexer(resource, authorize_write=authorize)
    source = 'alpha retained baseline\n\nsecond paragraph'
    options = dict(collection=collection, document_id='vector-shared', source_locator='synthetic:vector-generations',
                   scope=scopes[0], metadata={'unicode': 'Café🙂', 'nested': [None, True, 1.25]},
                   canonical_options={'target_bytes': 12, 'max_chunk_bytes': 32})

    def arguments(intent, **changes):
        return {**options, 'intent_id': intent, 'deadline': loop.time()+25, **changes}

    async def pointer(scope=scopes[0], document='vector-shared'):
        values = await rows('SELECT active_generation_id FROM cragkit.documents WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',
                            (scope.tenant_id, collection, document))
        return None if not values else values[0][0]

    write_tables = ('collections','documents','document_revisions','index_generations','chunks','chunk_lexical','document_grants','ingestion_jobs','chunk_vectors_fake_1536')

    async def lexical_ids(scope=scopes[0]):
        # Same restricted LOGIN and pooled client, with write permissions temporarily removed.
        for table in write_tables:
            await admin.execute(sql.SQL('REVOKE INSERT,UPDATE ON cragkit.{} FROM {}').format(sql.Identifier(table),sql.Identifier(config.user)))
        try:
            request = parse_request({'query': 'alpha', 'collection': collection})
            session = PostgresSession(resource)
            async with session.transaction(request, scope=scope, deadline=loop.time()+10) as handle:
                candidates = await handle.lexical_candidates(limit=8)
            return [(item.document_id,item.generation_id,item.start_byte,item.end_byte) for item in candidates]
        finally:
            for table in write_tables:
                await admin.execute(sql.SQL('GRANT INSERT,UPDATE ON cragkit.{} TO {}').format(sql.Identifier(table),sql.Identifier(config.user)))

    try:
        await resource.open()
        baseline = await lexical.ingest(source, **arguments('vector-baseline'))
        original = await lexical_ids()
        require(original and all(row[1] == baseline.generation_id for row in original), 'baseline_lexical_result')
        replacement = 'alpha shadow replacement\n\nthird paragraph'
        state['fail_at'] = 2
        caught = False
        try:
            await indexer.stage(replacement, **arguments('vector-build', expected_generation_id=baseline.generation_id))
        except ProviderUnavailable:
            caught = True
        require(caught and await pointer() == baseline.generation_id, 'interrupted_stage_pointer')
        require(await lexical_ids() == original, 'interrupted_stage_prior_lexical')
        counts = await rows('SELECT count(*) FROM cragkit.chunk_vectors_fake_1536 WHERE tenant_id=%s AND collection_id=%s', (scopes[0].tenant_id,collection))
        require(counts == [(1,)], 'first_batch_persisted')
        checks.append('partial_batch_preserves_exact_prior_pointer_and_lexical')
        state['fail_at'] = None
        first = await indexer.stage(replacement, **arguments('vector-build', expected_generation_id=baseline.generation_id))
        require(first.provider_calls == first.chunk_count-1 and await pointer() == baseline.generation_id, 'missing_only_resume')
        require(await lexical_ids() == original, 'staged_generation_invisible')
        replay = await indexer.stage(replacement, **arguments('vector-build', expected_generation_id=baseline.generation_id))
        require(replay.provider_calls == 0 and replay.generation_id == first.generation_id, 'complete_stage_replay')
        checks.append('bounded_missing_only_resume_and_staging_invisibility')
        try:
            await indexer.stage(replacement+'changed', **arguments('vector-build', expected_generation_id=baseline.generation_id))
        except InvalidRequest:
            pass
        else:
            raise VectorCheckError('changed_payload_accepted')
        checks.append('same_intent_changed_payload_rejected')
        state['wrong_model'] = True
        try:
            await indexer.stage('alpha wrong model', **arguments('vector-wrong-model',expected_generation_id=baseline.generation_id))
        except EmbeddingProfileMismatch:
            pass
        else:
            raise VectorCheckError('same_dimension_wrong_model_accepted')
        finally:
            state['wrong_model'] = False
        require(await pointer() == baseline.generation_id and await lexical_ids() == original, 'wrong_model_prior_pointer_lexical')
        checks.append('same_dimension_model_mismatch_preserves_prior_result')
        other = await indexer.stage(replacement, **arguments('vector-build',scope=scopes[1]))
        require(other.tenant_id != first.tenant_id and other.generation_id != first.generation_id and await pointer(scopes[1]) is None, 'tenant_collision_isolation')
        checks.append('colliding_tenant_intent_document_ids_isolated')
        # D/F append publication acceptance after stage has separately passed.
        return {'state':'passed','runtime':'python','checks':checks,'maximum_connections':2,'cleanup_verified':True}
    finally:
        await resource.close()
