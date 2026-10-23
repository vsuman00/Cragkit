"""Explicit synthetic pgvector acceptance under a temporary restricted LOGIN."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import re
import tempfile


class DenseCheckError(RuntimeError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise DenseCheckError(code)


async def run(config, fixture, admin, *, typescript=False, neon=False):
    from psycopg import sql
    from cragkit._postgres_pool import PoolResource
    from cragkit._postgres_session import PostgresSession
    from cragkit.contracts import parse_request, parse_scope
    from cragkit.embeddings import EmbeddingAdapter, EmbeddingBatch, EmbeddingUsage, FAKE_PROFILE
    from cragkit.errors import CragkitError, UnsupportedCapability
    from cragkit.ingestion import PostgresIndexer
    from cragkit.vector_ingestion import PostgresVectorIndexer

    shared = json.loads((Path(__file__).resolve().parents[1] / 'contracts/fixtures/dense.json').read_text())
    scopes = [parse_scope(value) for value in fixture['scopes']]
    collection = fixture['collection']
    resource = PoolResource(config.model_copy(update={'max_size': 1}))
    loop = asyncio.get_running_loop()
    checks = []
    receipts = {}
    stage = 'seed'
    documents = {item['source']: item for item in shared['documents']}
    writes = ('collections', 'documents', 'document_revisions', 'index_generations', 'chunks',
              'chunk_lexical', 'document_grants', 'ingestion_jobs', 'chunk_vectors_fake_1536')
    profile_policy = config.user + '_hide_profile'

    async def command(statement, parameters=None):
        async with asyncio.timeout(8):
            return await admin.execute(statement, parameters)

    def vector(coordinates):
        return [*coordinates, *([0.] * (shared['dimension'] - len(coordinates)))]

    def batch(coordinates):
        return EmbeddingBatch(profile=FAKE_PROFILE, vectors=(tuple(vector(coordinates)),),
            usage=EmbeddingUsage(prompt_tokens=0, total_tokens=0, cost_usd=0., cost_kind='known'), synthetic=True)

    async def transport(body, *, deadline, max_response_bytes):
        payload = json.loads(body)
        return json.dumps(dict(model=FAKE_PROFILE.model, data=[dict(index=index,
            embedding=vector(documents.get(text, {'coordinates': [0., 1.]})['coordinates']))
            for index, text in enumerate(payload['input'])])).encode()

    class Counter:
        name = 'fake-byte-v1'
        def count(self, text):
            return len(text.encode('utf-8'))

    async def allowed(scope, target, document):
        return scope in scopes and target == collection

    async def mutate(action, enabled):
        key = (scopes[0].tenant_id, collection, 'dense-a')
        if action == 'revoke':
            await command('UPDATE cragkit.document_grants SET authorization_revision=%s WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',
                          ('revoked' if enabled else scopes[0].authorization_revision, *key))
        elif action == 'tombstone':
            await command('UPDATE cragkit.documents SET tombstoned=%s WHERE tenant_id=%s AND collection_id=%s AND document_id=%s', (enabled, *key))
        elif action == 'advance':
            async with admin.transaction():
                if enabled:
                    await command("UPDATE cragkit.index_generations SET status='ready' WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s", (*key, receipts['shadow']['generation_id']))
                    await command("UPDATE cragkit.ingestion_jobs SET state='succeeded' WHERE tenant_id=%s AND collection_id=%s AND intent_id='dense-shadow'", key[:2])
                await command('UPDATE cragkit.documents SET active_generation_id=%s WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',
                              (receipts['shadow' if enabled else 'dense-a']['generation_id'], *key))
        elif action == 'hide_profile':
            if enabled:
                await command(sql.SQL('CREATE POLICY {} ON cragkit.embedding_profiles AS RESTRICTIVE FOR SELECT TO {} USING(false)').format(sql.Identifier(profile_policy), sql.Identifier(config.user)))
            else:
                await command(sql.SQL('DROP POLICY {} ON cragkit.embedding_profiles').format(sql.Identifier(profile_policy)))
        else:
            raise DenseCheckError('owner_action_invalid')

    def request(entry=None, **changes):
        return parse_request({'query': 'alpha', 'collection': collection,
            'required_filters': [] if entry is None else entry['filters'], **changes})

    async def read(entry=None, *, scope=scopes[0], candidate=None, parsed=None):
        async with PostgresSession(resource).transaction(parsed or request(entry), scope=scope, deadline=loop.time()+12) as handle:
            if candidate is not None:
                return await handle.fetch_evidence(candidate, max_source_bytes=1048576)
            return await handle.dense_candidates(batch([1., 0.] if entry is None else entry['coordinates']),
                                                 limit=100 if entry is None else entry['limit'])

    def normalized(candidates):
        return [(item.document_id, item.generation_id, item.chunk_id, item.score) for item in candidates]

    def assert_case(candidates, entry):
        require(len(candidates) == len(entry['expected']), 'dense_case_count')
        for item, expected in zip(candidates, entry['expected'], strict=True):
            require(item.document_id == expected[0] and abs(item.score-expected[1]) <= shared['tolerance'], 'dense_case_order')
            require(item.tenant_id == scopes[0].tenant_id and item.collection == collection
                    and item.score_direction == 'lower_is_better' and item.score_kind == 'cosine_distance'
                    and item.embedding_profile == FAKE_PROFILE.profile_id, 'dense_case_scope_metadata')

    try:
        await resource.open()
        indexer = PostgresVectorIndexer(resource, authorize_write=allowed, embedder=EmbeddingAdapter(transport, Counter()))
        for item in shared['documents']:
            result = await indexer.ingest(item['source'], collection=collection, document_id=item['document_id'],
                intent_id='seed-'+item['document_id'], source_locator='synthetic:dense', scope=scopes[0], deadline=loop.time()+30)
            receipts[item['document_id']] = result.model_dump(mode='json')
        other = await indexer.ingest('alpha other tenant', collection=collection, document_id='dense-a',
            intent_id='seed-dense-a', source_locator='synthetic:dense', scope=scopes[1], deadline=loop.time()+30)
        receipts['other'] = other.model_dump(mode='json')
        await PostgresIndexer(resource, authorize_write=allowed).ingest('alpha lexical only', collection=collection,
            document_id='legacy-only', intent_id='legacy-only', source_locator='synthetic:dense', scope=scopes[0], deadline=loop.time()+30)
        shadow = await indexer.stage('alpha shadow replacement', collection=collection, document_id='dense-a',
            intent_id='dense-shadow', source_locator='synthetic:dense', scope=scopes[0], deadline=loop.time()+30,
            expected_generation_id=receipts['dense-a']['generation_id'])
        receipts['shadow'] = shadow.model_dump(mode='json')
        unready = await indexer.stage('alpha unready vector', collection=collection, document_id='unready-only',
            intent_id='unready-only', source_locator='synthetic:dense', scope=scopes[0], deadline=loop.time()+30)
        await command('UPDATE cragkit.documents SET active_generation_id=%s WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',
                      (unready.generation_id, scopes[0].tenant_id, collection, 'unready-only'))
        await command('INSERT INTO cragkit.document_grants(tenant_id,collection_id,document_id,grant_id,principal_id,authorization_revision) VALUES(%s,%s,%s,%s,NULL,%s)',
                      (scopes[0].tenant_id, collection, 'dense-c', 'dense-reader', scopes[0].authorization_revision))
        stage = 'ranking'
        for table in writes:
            await command(sql.SQL('REVOKE INSERT,UPDATE ON cragkit.{} FROM {}').format(sql.Identifier(table), sql.Identifier(config.user)))
        for entry in shared['cases']:
            assert_case(await read(entry), entry)
        checks.append('python_exact_distance_order_ties_filters_before_limit_and_staging_legacy_exclusion')
        require(len(await read(parsed=request(limits={'max_candidates': 1}))) == 1, 'request_candidate_limit')
        denied = scopes[0].model_copy(update={'principal_id': 'not-authorized'})
        require(not await read(scope=denied), 'same_tenant_principal_leak')
        try:
            await read(parsed=request(collection=collection+'-other'))
        except UnsupportedCapability:
            pass  # Existing session contract rejects an unavailable collection.
        else:
            raise DenseCheckError('missing_collection_accepted')
        grant_scope = scopes[0].model_copy(update={'principal_id': 'grant-only', 'grant_ids': ('dense-reader',)})
        grant_rows = await read(scope=grant_scope)
        require([item.document_id for item in grant_rows] == ['dense-c'], 'grant_only_scope')
        require((await read(scope=grant_scope, candidate=grant_rows[0])).state == 'verified', 'grant_only_source')
        wrong_grant = grant_scope.model_copy(update={'grant_ids': ('wrong-grant',)})
        require(not await read(scope=wrong_grant), 'wrong_grant_leak')
        require((await read(scope=wrong_grant, candidate=grant_rows[0])).state == 'unavailable', 'wrong_grant_source')
        other_rows = await read(scope=scopes[1])
        require(len(other_rows) == 1 and other_rows[0].tenant_id == scopes[1].tenant_id
                and other_rows[0].generation_id == receipts['other']['generation_id'], 'tenant_collision')
        checks.append('python_tenant_collection_principal_and_request_limits')
        stage = 'source_authorization'
        candidate = (await read())[0]
        source = await read(candidate=candidate)
        require(source.state == 'verified' and source.evidence.text == shared['documents'][0]['source'], 'dense_exact_source')
        for action in ('revoke', 'tombstone'):
            await mutate(action, True)
            try:
                require(all(item.document_id != 'dense-a' for item in await read()), 'denied_dense_candidate')
                require((await read(candidate=candidate)).state == 'unavailable', 'denied_dense_source')
            finally:
                await mutate(action, False)
        checks.append('python_dense_source_fidelity_and_revocation_tombstone_denial')
        stage = 'missing_profile'
        await mutate('hide_profile', True)
        try:
            try:
                await read()
            except UnsupportedCapability:
                pass
            else:
                raise DenseCheckError('unavailable_profile_accepted')
            async with PostgresSession(resource).transaction(request(), scope=scopes[0], deadline=loop.time()+12) as handle:
                require(bool(await handle.lexical_candidates()), 'missing_profile_broke_lexical')
        finally:
            await mutate('hide_profile', False)
        checks.append('python_missing_profile_typed_failure_keeps_lexical_available')
        stage = 'snapshot'
        advanced = False
        try:
            async with PostgresSession(resource).transaction(request(), scope=scopes[0], deadline=loop.time()+12) as handle:
                before = await handle.dense_candidates(batch([1., 0.]))
                lexical_before = await handle.lexical_candidates()
                require(bool(lexical_before), 'same_snapshot_lexical_empty')
                await mutate('advance', True)
                advanced = True
                require(normalized(await handle.dense_candidates(batch([1., 0.]))) == normalized(before), 'dense_snapshot_changed')
                require(normalized(await handle.lexical_candidates()) == normalized(lexical_before), 'lexical_snapshot_changed')
            historical = await read(candidate=before[0])
            require(historical.state == 'verified' and historical.stale and historical.evidence.text == shared['documents'][0]['source'], 'dense_retained_source')
        finally:
            if advanced:
                await mutate('advance', False)
        checks.append('python_dense_and_lexical_repeatable_snapshot_retained_source')
        stage = 'node'
        if typescript:
            await resource.close()
            result = await run_node(config, dict(**fixture, shared=shared, receipts=receipts, neon=neon), mutate)
            checks.extend(result['checks'])
        return dict(state='passed', runtime='python_and_node' if typescript else 'python', checks=checks,
                    maximum_connections=2, cleanup_verified=True)
    except CragkitError as error:
        raise DenseCheckError(stage+'_'+error.code) from None
    finally:
        await resource.close()
        await command(sql.SQL('DROP POLICY IF EXISTS {} ON cragkit.embedding_profiles').format(sql.Identifier(profile_policy)))


async def run_node(config, fixture, mutate):
    """Local fixed owner actions only; the child never receives administrative credentials."""
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix='cragkit-dense-node-') as directory:
            paths = [Path(directory)/name for name in ('runtime.json', 'fixture.json')]
            for path, value in zip(paths, (config.model_dump(mode='json'), fixture), strict=True):
                descriptor = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w') as destination:
                    json.dump(value, destination)
            process = await asyncio.create_subprocess_exec('node', str(Path(__file__).with_name('check_typescript_dense.mjs')),
                '--allow-dense-checks', *(str(path) for path in paths), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=65536)
            result = None
            async with asyncio.timeout(300):
                while line := await process.stdout.readline():
                    value = json.loads(line)
                    if value.get('type') == 'owner':
                        require(value.get('action') in ('advance', 'revoke', 'tombstone', 'hide_profile')
                                and type(value.get('enabled')) is bool, 'node_owner_action_invalid')
                        await mutate(value['action'], value['enabled'])
                        process.stdin.write(b'{"ok":true}\n')
                        await process.stdin.drain()
                    elif value.get('type') == 'result':
                        require(result is None, 'node_duplicate_result')
                        result = value
                    elif value.get('type') == 'error':
                        code = value.get('code')
                        safe = isinstance(code, str) and len(code) <= 96 and re.fullmatch('[a-z_]+', code)
                        raise DenseCheckError('node_'+code if safe else 'node_dense_check_failed')
                    else:
                        raise DenseCheckError('node_dense_check_failed')
                require(await process.wait() == 0 and result is not None, 'node_result_missing')
                return result
    finally:
        if process is not None and process.returncode is None:
            process.kill()
            await asyncio.wait_for(process.wait(), 5)
        for action in ('revoke', 'tombstone', 'advance'):
            await mutate(action, False)
