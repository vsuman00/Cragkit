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
    from cragkit._fusion import fuse
    from cragkit.contracts import parse_request, parse_scope
    from cragkit.embeddings import EmbeddingAdapter, EmbeddingBatch, EmbeddingUsage, FAKE_PROFILE
    from cragkit.errors import CragkitError, UnsupportedCapability
    from cragkit.ingestion import PostgresIndexer
    from cragkit.vector_ingestion import PostgresVectorIndexer

    shared = json.loads((Path(__file__).resolve().parents[1] / 'contracts/fixtures/dense.json').read_text())
    identifier_fixture = json.loads((Path(__file__).resolve().parents[1] / 'contracts/fixtures/identifier_fusion.json').read_text())['native']
    # Keep DN-r1 math fixtures immutable; add explicit IF-r1 synthetic identifiers only to this native run.
    for item in shared['documents']:
        item['source'] += identifier_fixture['suffix']
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

    async def read_ids(*, scope=scopes[0], parsed=None, token=None, limit=100):
        async with PostgresSession(resource).transaction(parsed or request(), scope=scope, deadline=loop.time()+12) as handle:
            return await handle.identifier_candidates(identifier_fixture['token'] if token is None else token, limit=limit)

    async def check_identifiers():
        token = identifier_fixture['token']
        identifiers = await read_ids()
        require([item.document_id for item in identifiers] == ['dense-a', 'dense-b', 'dense-c', 'dense-d', 'legacy-only'], 'identifier_order_storage')
        require(all(item.score == 1. and item.identifier_profile == 'identifier_ascii_v1' for item in identifiers), 'identifier_metadata')
        require(not await read_ids(token=token.lower()), 'identifier_case_folded')
        require([item.document_id for item in await read_ids(parsed=request(required_filters=[{'field': 'document_id', 'op': 'eq', 'value': 'dense-c'}]), limit=1)] == ['dense-c'], 'identifier_filter_before_limit')
        require(len(await read_ids(parsed=request(limits={'max_candidates': 1}))) == 1, 'identifier_request_limit')
        require(not await read_ids(scope=scopes[0].model_copy(update={'principal_id': 'denied'})), 'identifier_principal_leak')
        grant_scope = scopes[0].model_copy(update={'principal_id': 'grant-only', 'grant_ids': ('dense-reader',)})
        granted = await read_ids(scope=grant_scope)
        require([item.document_id for item in granted] == ['dense-c'], 'identifier_grant_scope')
        require((await read(scope=grant_scope, candidate=granted[0])).state == 'verified', 'identifier_grant_source')
        wrong = grant_scope.model_copy(update={'grant_ids': ('wrong',)})
        require(not await read_ids(scope=wrong), 'identifier_wrong_grant')
        require((await read(scope=wrong, candidate=granted[0])).state == 'unavailable', 'identifier_wrong_grant_source')
        other = await read_ids(scope=scopes[1])
        require(len(other) == 1 and other[0].generation_id == receipts['other']['generation_id'], 'identifier_tenant_collision')
        async with PostgresSession(resource).transaction(request(), scope=scopes[0], deadline=loop.time()+12) as handle:
            branches = [('dense', await handle.dense_candidates(batch([1., 0.]))),
                        ('lexical', await handle.lexical_candidates()),
                        ('identifier', await handle.identifier_candidates(token))]
            result = fuse([dict(list_id=family, facet_id='original', family=family, weight=1.,
                                candidates=[item.model_dump(mode='json') for item in rows]) for family, rows in branches])
            require(len(result) == 5 and all(item['candidate']['tenant_id'] == scopes[0].tenant_id for item in result), 'native_fusion_scope_union')
            require(any(vote['family'] == 'identifier' for item in result for vote in item['contributions']), 'native_identifier_vote_missing')
            for item in result:
                expected = sum(1./3/(60+next(i+1 for i, row in enumerate(rows) if row.document_id == item['candidate']['document_id']))
                               for _, rows in branches if any(row.document_id == item['candidate']['document_id'] for row in rows))
                require(abs(item['score']-expected) <= 1e-12, 'native_fusion_arithmetic')
        return identifiers[0]

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
        other = await indexer.ingest('alpha other tenant'+identifier_fixture['suffix'], collection=collection, document_id='dense-a',
            intent_id='seed-dense-a', source_locator='synthetic:dense', scope=scopes[1], deadline=loop.time()+30)
        receipts['other'] = other.model_dump(mode='json')
        await PostgresIndexer(resource, authorize_write=allowed).ingest('alpha lexical only'+identifier_fixture['suffix'], collection=collection,
            document_id='legacy-only', intent_id='legacy-only', source_locator='synthetic:dense', scope=scopes[0], deadline=loop.time()+30)
        shadow = await indexer.stage('alpha shadow replacement '+identifier_fixture['shadow_token'], collection=collection, document_id='dense-a',
            intent_id='dense-shadow', source_locator='synthetic:dense', scope=scopes[0], deadline=loop.time()+30,
            expected_generation_id=receipts['dense-a']['generation_id'])
        receipts['shadow'] = shadow.model_dump(mode='json')
        unready = await indexer.stage('alpha unready vector'+identifier_fixture['suffix'], collection=collection, document_id='unready-only',
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
        identifier_candidate = await check_identifiers()
        checks.append('python_identifier_exact_storage_scope_filters_grants_source_and_native_fusion')
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
                require(all(item.document_id != 'dense-a' for item in await read_ids()), 'denied_identifier_candidate')
                require((await read(candidate=identifier_candidate)).state == 'unavailable', 'denied_identifier_source')
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
                require(bool(await handle.identifier_candidates(identifier_fixture['token'])), 'missing_profile_broke_identifier')
        finally:
            await mutate('hide_profile', False)
        checks.append('python_missing_profile_typed_failure_keeps_lexical_available')
        stage = 'snapshot'
        advanced = False
        try:
            async with PostgresSession(resource).transaction(request(), scope=scopes[0], deadline=loop.time()+12) as handle:
                before = await handle.dense_candidates(batch([1., 0.]))
                lexical_before = await handle.lexical_candidates()
                identifiers_before = await handle.identifier_candidates(identifier_fixture['token'])
                require(bool(lexical_before), 'same_snapshot_lexical_empty')
                await mutate('advance', True)
                advanced = True
                require(normalized(await handle.dense_candidates(batch([1., 0.]))) == normalized(before), 'dense_snapshot_changed')
                require(normalized(await handle.lexical_candidates()) == normalized(lexical_before), 'lexical_snapshot_changed')
                require(normalized(await handle.identifier_candidates(identifier_fixture['token'])) == normalized(identifiers_before), 'identifier_snapshot_changed')
            historical_identifier = await read(candidate=identifiers_before[0])
            require(historical_identifier.state == 'verified' and historical_identifier.stale and historical_identifier.evidence.text == shared['documents'][0]['source'], 'identifier_retained_source')
            require(all(item.document_id != 'dense-a' for item in await read_ids()), 'identifier_new_generation_tokens')
            historical = await read(candidate=before[0])
            require(historical.state == 'verified' and historical.stale and historical.evidence.text == shared['documents'][0]['source'], 'dense_retained_source')
        finally:
            if advanced:
                await mutate('advance', False)
        checks.append('python_dense_and_lexical_repeatable_snapshot_retained_source')
        stage = 'node'
        if typescript:
            await resource.close()
            result = await run_node(config, dict(**fixture, shared=shared, receipts=receipts, neon=neon, identifier_fixture=identifier_fixture), mutate)
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
