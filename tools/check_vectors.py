"""Synthetic native vector-generation checks; called by the explicit fixture owner."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path


class VectorCheckError(RuntimeError):
    pass


def require(condition: bool, code: str) -> None:
    if not condition:
        raise VectorCheckError(code)


async def run(config, fixture: dict, admin, *, typescript: bool = False, neon: bool = False, stage_only: bool = False) -> dict:
    from psycopg import sql
    from cragkit._postgres_pool import PoolResource
    from cragkit._postgres_session import PostgresSession
    from cragkit.contracts import parse_request, parse_scope
    from cragkit.embeddings import EmbeddingAdapter, EmbeddingLimits
    from cragkit.ingestion import PostgresIndexer
    from cragkit.vector_ingestion import PostgresVectorIndexer
    from cragkit.errors import InvalidRequest, ProviderUnavailable, EmbeddingProfileMismatch, IntegrityViolation, UnauthorizedScope, IndexNotReady

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
    shared = json.loads((Path(__file__).resolve().parents[1]/'contracts/fixtures/vector_generations.json').read_text())
    source = shared['baseline_source']
    options = dict(collection=collection, document_id='vector-shared', source_locator='synthetic:vector-generations',
                   scope=scopes[0], metadata=shared['metadata'], canonical_options=shared['canonical_options'])

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
        replacement = shared['replacement_source']
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
        publication_args = dict(expected_generation_id=baseline.generation_id)
        async def unchanged(expected_pointer, expected_lexical=original):
            require(await pointer() == expected_pointer, 'failed_publication_changed_pointer')
            require(await lexical_ids() == expected_lexical, 'failed_publication_changed_lexical')
        async def rejected_publish(error, **changes):
            try:
                await indexer.publish(replacement, **arguments('vector-build',**publication_args,**changes))
            except error:
                return
            raise VectorCheckError('publication_failure_accepted')
        sentinel = RuntimeError('synthetic publication interruption')
        async def interrupt():
            raise sentinel
        await rejected_publish(RuntimeError,before_publish=interrupt)
        await unchanged(baseline.generation_id)
        checks.append('hook_interruption_preserves_pointer_and_prior_lexical')
        key=(scopes[0].tenant_id,collection,'vector-shared',first.generation_id)
        removed = await rows('DELETE FROM cragkit.chunk_vectors_fake_1536 WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s AND chunk_id=(SELECT chunk_id FROM cragkit.chunk_vectors_fake_1536 WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s LIMIT 1) RETURNING chunk_id,embedding::text', (*key,*key))
        require(len(removed)==1,'missing_vector_probe_shape')
        try:
            await rejected_publish(IntegrityViolation)
            await unchanged(baseline.generation_id)
        finally:
            await admin.execute('INSERT INTO cragkit.chunk_vectors_fake_1536(tenant_id,collection_id,document_id,revision_id,generation_id,chunk_id,embedding_profile,embedding) VALUES(%s,%s,%s,%s,%s,%s,%s,%s::cragkit_vector.vector(1536))',(*key[:3],first.revision_id,first.generation_id,removed[0][0],first.embedding_profile,removed[0][1]))
        checks.append('incomplete_vectors_preserve_pointer_and_prior_lexical')
        await admin.execute("UPDATE cragkit.index_generations SET lexical_profile='mismatched.v1' WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s",key)
        try:
            await rejected_publish(IntegrityViolation)
            await unchanged(baseline.generation_id)
        finally:
            await admin.execute("UPDATE cragkit.index_generations SET lexical_profile='native_fts.v1' WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s",key)
        checks.append('mixed_manifest_preserves_pointer_and_prior_lexical')
        block = config.user+'_block_ready'
        await admin.execute(sql.SQL("CREATE POLICY {} ON cragkit.index_generations AS RESTRICTIVE FOR UPDATE TO {} USING(true) WITH CHECK(status<>'ready')").format(sql.Identifier(block),sql.Identifier(config.user)))
        try:
            await rejected_publish(UnauthorizedScope)
            await unchanged(baseline.generation_id)
            require(await rows('SELECT status FROM cragkit.index_generations WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s',key)==[('staging',)], 'failed_ready_update_persisted')
        finally:
            await admin.execute(sql.SQL('DROP POLICY {} ON cragkit.index_generations').format(sql.Identifier(block)))
        checks.append('ready_write_failure_rolls_back_generation_and_job')
        published = await indexer.publish(replacement, **arguments('vector-build',**publication_args))
        require(await pointer()==first.generation_id and published.provider_calls==0, 'published_pointer')
        replay = await indexer.publish(replacement, **arguments('vector-build',**publication_args))
        require(replay.replayed and replay.provider_calls==0, 'published_replay')
        current_lexical=await lexical_ids()
        require(current_lexical and all(row[1]==first.generation_id for row in current_lexical), 'published_lexical_result')
        checks.append('complete_generation_atomic_publish_and_replay')
        slow_source='alpha slower competing shadow'
        fast_source='alpha newer competing shadow'
        slow=await indexer.stage(slow_source, **arguments('vector-slow',expected_generation_id=first.generation_id))
        fast=await indexer.stage(fast_source, **arguments('vector-fast',expected_generation_id=first.generation_id))
        await indexer.publish(fast_source, **arguments('vector-fast',expected_generation_id=first.generation_id))
        prior=await lexical_ids()
        try:
            await indexer.publish(slow_source, **arguments('vector-slow',expected_generation_id=first.generation_id))
        except IndexNotReady:
            pass
        else:
            raise VectorCheckError('stale_cas_accepted')
        await unchanged(fast.generation_id,prior)
        checks.append('out_of_order_completion_preserves_newer_exact_pointer_and_lexical')
        denied_source='alpha authorization-sensitive staged build'
        denied=await indexer.stage(denied_source, **arguments('vector-denied',expected_generation_id=fast.generation_id))
        grants=await rows('DELETE FROM cragkit.document_grants WHERE tenant_id=%s AND collection_id=%s AND document_id=%s RETURNING grant_id,principal_id,authorization_revision',key[:3])
        try:
            try:
                await indexer.publish(denied_source, **arguments('vector-denied',expected_generation_id=fast.generation_id))
            except UnauthorizedScope:
                pass
            else:
                raise VectorCheckError('revoked_grant_published')
            await unchanged(fast.generation_id,[])
        finally:
            for grant in grants:
                await admin.execute('INSERT INTO cragkit.document_grants(tenant_id,collection_id,document_id,grant_id,principal_id,authorization_revision) VALUES(%s,%s,%s,%s,%s,%s)',(*key[:3],*grant))
        await admin.execute('UPDATE cragkit.documents SET tombstoned=true WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',key[:3])
        try:
            try:
                await indexer.publish(denied_source, **arguments('vector-denied',expected_generation_id=fast.generation_id))
            except UnauthorizedScope:
                pass
            else:
                raise VectorCheckError('tombstone_published')
            await unchanged(fast.generation_id,[])
        finally:
            await admin.execute('UPDATE cragkit.documents SET tombstoned=false WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',key[:3])
        checks.append('revocation_and_tombstone_never_restore_older_authorization')
        if typescript:
            await resource.close()
            node = await run_node(config, {**fixture,'shared':shared,'neon':neon,
                'python_receipt':published.model_dump(mode='json'),'python_expected':baseline.generation_id,
                'stage_only':stage_only}, admin)
            checks.extend(node['checks'])
            require(node['phase']==('stage' if stage_only else 'full'),'node_phase_mismatch')

        return {'state':'passed','runtime':'python_and_node' if typescript else 'python','checks':checks,'maximum_connections':2,'cleanup_verified':True}
    finally:
        await resource.close()


async def run_node(config, fixture, admin):
    """Give the child restricted credentials; handle only fixed owner operations."""
    import os
    import tempfile
    from psycopg import sql
    write_tables=('collections','documents','document_revisions','index_generations','chunks','chunk_lexical','document_grants','ingestion_jobs','chunk_vectors_fake_1536')
    process=None
    block=config.user+'_block_ready'
    try:
        with tempfile.TemporaryDirectory(prefix='cragkit-vector-node-') as directory:
            paths=[Path(directory)/'runtime.json',Path(directory)/'fixture.json']
            for path,value in zip(paths,(config.model_dump(mode='json'),fixture),strict=True):
                descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(descriptor,'w') as destination:
                    json.dump(value,destination)
            process=await asyncio.create_subprocess_exec('node',str(Path(__file__).with_name('check_typescript_vectors.mjs')),
                '--allow-vector-checks',str(paths[0]),str(paths[1]),stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=65536)
            result=None
            async with asyncio.timeout(300):
                while True:
                    line=await process.stdout.readline()
                    if not line:
                        break
                    value=json.loads(line)
                    if value.get('type')=='owner':
                        action=value.get('action')
                        if action in ('read','write'):
                            verb='REVOKE INSERT,UPDATE ON' if action=='read' else 'GRANT INSERT,UPDATE ON'
                            recipient='FROM' if action=='read' else 'TO'
                            for table in write_tables:
                                await admin.execute(sql.SQL(verb+' cragkit.{} '+recipient+' {}').format(sql.Identifier(table),sql.Identifier(config.user)))
                        elif action=='deny_ready' and type(value.get('enabled')) is bool:
                            if value['enabled']:
                                await admin.execute(sql.SQL("CREATE POLICY {} ON cragkit.index_generations AS RESTRICTIVE FOR UPDATE TO {} USING(true) WITH CHECK(status<>'ready' OR document_id<>'vector-node' OR embedding_profile IS NULL)").format(sql.Identifier(block),sql.Identifier(config.user)))
                            else:
                                await admin.execute(sql.SQL('DROP POLICY {} ON cragkit.index_generations').format(sql.Identifier(block)))
                        else:
                            raise VectorCheckError('node_owner_action_invalid')
                        process.stdin.write(b'{"ok":true}\n')
                        await process.stdin.drain()
                    elif value.get('type')=='result':
                        require(result is None,'node_duplicate_result')
                        result=value
                    elif value.get('type')=='error':
                        code=value.get('code')
                        import re
                        raise VectorCheckError('node_'+code if isinstance(code,str) and re.fullmatch('[a-z_]+',code) else 'node_check_failed')
                    else:
                        raise VectorCheckError('node_message_invalid')
                require(await process.wait()==0 and result is not None,'node_result_missing')
                return result
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await asyncio.wait_for(process.wait(),5)
        await admin.execute(sql.SQL('DROP POLICY IF EXISTS {} ON cragkit.index_generations').format(sql.Identifier(block)))
