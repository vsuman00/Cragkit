"""Authorized source-result checks inside the explicitly owned empty-target fixture."""
from __future__ import annotations


async def run(config, fixture, admin):
    import asyncio
    import hashlib
    from contextlib import asynccontextmanager
    import json
    import os
    from pathlib import Path
    import tempfile

    from cragkit._postgres_pool import PoolResource
    from cragkit._postgres_session import PostgresSession, _ROLE_SQL
    from cragkit.canonical import canonicalize
    from cragkit.contracts import parse_request, parse_scope
    from cragkit.errors import IntegrityViolation
    from cragkit.retrieval import PostgresRetriever
    from check_ingestion import require

    collection = fixture['collection']
    scopes = [parse_scope(value) for value in fixture['scopes']]
    loop = asyncio.get_running_loop()
    resource = PoolResource(config.model_copy(update={'max_size': 1}))
    checks = []
    stored_span = None
    original_span = None
    canonical = canonicalize('\ufeffNode Café🙂\r\n\r\nNative source\n', target_bytes=8, max_chunk_bytes=16)
    canonical_bytes = canonical.canonical_text.encode('utf-8')

    async def command(statement, params=None):
        async with asyncio.timeout(10):
            return await admin.execute(statement, params)

    async def rows(statement, params=None):
        cursor = await command(statement, params)
        async with asyncio.timeout(10):
            return await cursor.fetchall()

    async def query(request, scope):
        result = await PostgresRetriever(resource).retrieve(
            parse_request(request), scope=scope, deadline=loop.time() + 20)
        return result.model_dump(mode='json')

    async def node_check(value, boundary=None):
        with tempfile.TemporaryDirectory(prefix='cragkit-results-') as directory:
            runtime_path = Path(directory) / 'runtime.json'
            fixture_path = Path(directory) / 'fixture.json'
            for path, content in ((runtime_path, config.model_dump(mode='json')), (fixture_path, value)):
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w', encoding='utf-8') as destination:
                    json.dump(content, destination)
            process = await asyncio.create_subprocess_exec(
                'node', str(Path(__file__).with_name('check_typescript_retrieval.mjs').resolve()),
                '--allow-result-checks', str(runtime_path), str(fixture_path),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=8192)
            try:
                async with asyncio.timeout(60):
                    if boundary is not None:
                        ready = await process.stdout.readline()
                        require(ready == b'{"state":"boundary"}\n', 'source_node_boundary')
                        await boundary()
                        process.stdin.write(b'continue\n')
                        await process.stdin.drain()
                    output, _ = await process.communicate()
                require(len(output) <= 8192, 'source_node_result_size')
                result = json.loads(output)
                require(process.returncode == 0 and result.get('state') == 'passed',
                        result.get('code', 'source_node_failed'))
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()

    async def assert_trigger():
        require(await rows("SELECT tgenabled FROM pg_trigger WHERE tgrelid='cragkit.chunks'::regclass AND tgname='canonical_chunk_span'") == [('O',)],
                'source_trigger_not_enabled')

    try:
        await assert_trigger()
        await resource.open()
        request = {'request_id': 'native-source-result', 'query': 'Café', 'collection': collection}
        cases = []
        for scope in scopes:
            result = await query(request, scope)
            require(result['status'] == 'partial' and result['execution'] == 'complete'
                    and len(result['evidence']) == 2 and result['facets'] == [], 'source_partial_result')
            require([item['document_id'] for item in result['evidence']] == ['node-document', 'tie-document'],
                    'source_evidence_order')
            require(result['limitations'] == [{'code': 'coverage_unknown', 'facet_ids': [], 'evidence_ids': []}],
                    'source_unknown_coverage')
            require(json.loads(result['context']) == result['evidence'], 'source_context_disagrees')
            for evidence in result['evidence']:
                excerpt = canonical_bytes[evidence['start_byte']:evidence['end_byte']]
                require(excerpt.decode('utf-8') == evidence['text']
                        and hashlib.sha256(excerpt).hexdigest() == evidence['text_sha256']
                        and evidence['source_sha256'] == canonical.canonical_sha256
                        and evidence['source_sha256'] != canonical.source_sha256, 'source_span_digest_provenance')
            cases.append({'request': request, 'scope': scope.model_dump(mode='json'), 'expected': result})
        require(cases[0]['expected']['evidence'][0]['revision_id'] != cases[1]['expected']['evidence'][0]['revision_id'],
                'source_tenant_revision_leak')
        for changed_request, scope in (
            ({**request, 'query': 'token-without-any-match'}, scopes[0]),
            (request, parse_scope({**scopes[0].model_dump(mode='json'), 'principal_id': 'unauthorized-principal'})),
            ({**request, 'required_filters': [{'op': 'eq', 'field': 'document_id', 'value': 'missing'}]}, scopes[0]),
        ):
            result = await query(changed_request, scope)
            require(result['status'] == 'insufficient' and result['evidence'] == [] and result['context'] == '',
                    'source_empty_or_denied_result')
            cases.append({'request': changed_request, 'scope': scope.model_dump(mode='json'), 'expected': result})
        tiny = {**request, 'limits': {'max_context_tokens': 1}, 'output_profile': {'envelope_reserve_tokens': 0}}
        result = await query(tiny, scopes[0])
        require(result['status'] == 'insufficient' and result['evidence'] == []
                and [item['code'] for item in result['limitations']] == ['coverage_unknown', 'truncated_evidence', 'budget_exhausted'],
                'source_estimated_context_cap')
        cases.append({'request': tiny, 'scope': scopes[0].model_dump(mode='json'), 'expected': result})
        session = PostgresSession(resource)
        async with session.transaction(parse_request(request), scope=scopes[0], deadline=loop.time()+10) as handle:
            candidates = await handle.lexical_candidates(limit=1)
        denied_scope = parse_scope({**scopes[0].model_dump(mode='json'), 'principal_id': 'unauthorized-principal', 'grant_ids': []})
        async with session.transaction(parse_request(request), scope=denied_scope, deadline=loop.time()+10) as handle:
            denied = await handle.fetch_evidence(candidates[0], max_source_bytes=16777216)
            require(denied.state == 'unavailable' and denied.evidence is None and denied.source_bytes == 0,
                    'source_direct_denial_failed')
        checks.append('python_verified_sources_unknown_coverage_and_empty_authorized_results')
        checks.append('python_source_fetch_reauthorizes_bound_principal')
        # Force committed permission changes after candidate selection, before the
        # fresh source transaction starts. The same retriever/pool must recover.
        require(await rows(_ROLE_SQL) == [(False,)], 'source_admin_role_accepted')
        key = (scopes[0].tenant_id, collection, 'node-document')
        mutations = {
            'document_revision': ('UPDATE cragkit.documents SET authorization_revision=%s WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',
                                  ('revoked-native', *key), (scopes[0].authorization_revision, *key)),
            'grant_revision': ('UPDATE cragkit.document_grants SET authorization_revision=%s WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',
                               ('revoked-native', *key), (scopes[0].authorization_revision, *key)),
            'tombstone': ('UPDATE cragkit.documents SET tombstoned=%s WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',
                          (True, *key), (False, *key)),
        }
        for name, (statement, changed, original) in mutations.items():
            retriever = PostgresRetriever(resource)
            session = PostgresSession(resource)
            transactions = 0

            class BoundarySession:
                @asynccontextmanager
                async def transaction(self, *args, **kwargs):
                    nonlocal transactions
                    transactions += 1
                    if transactions == 2:
                        await command(statement, changed)
                    async with session.transaction(*args, **kwargs) as handle:
                        yield handle

            retriever._session = BoundarySession()
            try:
                result = await retriever.retrieve(parse_request(request), scope=scopes[0], deadline=loop.time() + 20)
                require([item.document_id for item in result.evidence] == ['tie-document']
                        and any(item.code == 'stale_evidence' for item in result.limitations), 'source_python_revocation_' + name)
            finally:
                await command(statement, original)
            require(await query(request, scopes[0]) == cases[0]['expected'], 'source_python_reuse_' + name)
            await resource.close()
            try:
                await node_check({'mode': 'revocation', 'request': request,
                                  'scope': scopes[0].model_dump(mode='json')},
                                 lambda: command(statement, changed))
            finally:
                await command(statement, original)
            resource = PoolResource(config.model_copy(update={'max_size': 1}))
            await resource.open()
        checks.append('both_native_committed_revision_grant_tombstone_revocation_between_candidate_and_source')
        require(await query(request, scopes[1]) == cases[1]['expected'], 'source_cross_tenant_pool_reuse')
        checks.append('native_owner_bypass_role_rejection_and_cross_tenant_pool_reuse')
        await resource.close()
        await node_check({'mode': 'baseline', 'cases': cases, 'source_candidate': candidates[0].model_dump(mode='json'), 'source_request': request, 'source_scope': denied_scope.model_dump(mode='json')})
        checks.append('node_python_typed_result_context_usage_and_source_parity')

        installed = [os.environ.get(name) for name in (
            'CRAGKIT_INSTALLED_PYTHON', 'CRAGKIT_INSTALLED_PYTHON_EXAMPLE', 'CRAGKIT_INSTALLED_NODE_EXAMPLE')]
        if any(installed):
            require(all(installed), 'installed_example_configuration_incomplete')
            with tempfile.TemporaryDirectory(prefix='cragkit-installed-results-') as directory:
                runtime_path = Path(directory) / 'runtime.json'
                input_path = Path(directory) / 'request.json'
                descriptor = os.open(runtime_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w', encoding='utf-8') as destination:
                    json.dump(config.model_dump(mode='json'), destination)
                for executable, arguments, label in (
                        (installed[0], ['-I', '-B', installed[1]], 'wheel'),
                        ('node', [installed[2]], 'npm')):
                    for case in (cases[0], cases[3]):
                        input_path.write_text(json.dumps({'request': case['request'], 'scope': case['scope']}), encoding='utf-8')
                        process = await asyncio.create_subprocess_exec(
                            executable, *arguments, str(runtime_path), str(input_path),
                            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=16384)
                        try:
                            async with asyncio.timeout(60):
                                output, _ = await process.communicate()
                            require(process.returncode == 0 and len(output) <= 16384,
                                    'installed_' + label + '_example_failed')
                            require(json.loads(output) == case['expected'], 'installed_' + label + '_result_mismatch')
                        finally:
                            if process.returncode is None:
                                process.kill()
                                await process.wait()
                    checks.append('installed_' + label + '_authorized_query_and_denied_scope_example')

        # Corrupt only the owned synthetic chunk while retaining DB length/hash checks.
        # The named span trigger is restored before this transaction becomes visible.
        original = await rows('SELECT revision_id,generation_id,chunk_id,start_byte,end_byte FROM cragkit.chunks WHERE tenant_id=%s AND collection_id=%s AND document_id=%s ORDER BY ordinal LIMIT 1',
                              (scopes[0].tenant_id, collection, 'node-document'))
        require(len(original) == 1, 'source_corrupt_fixture_shape')
        revision, generation, chunk, start, end = original[0]
        stored_span = (scopes[0].tenant_id, collection, 'node-document', revision, generation, chunk)
        original_span = (start, end)
        async with admin.transaction():
            await command('ALTER TABLE cragkit.chunks DISABLE TRIGGER canonical_chunk_span')
            await command('UPDATE cragkit.chunks SET start_byte=%s,end_byte=%s WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND revision_id=%s AND generation_id=%s AND chunk_id=%s',
                          (start + 1, end + 1, *stored_span))
            await command('ALTER TABLE cragkit.chunks ENABLE TRIGGER canonical_chunk_span')
        await assert_trigger()
        resource = PoolResource(config.model_copy(update={'max_size': 1}))
        await resource.open()
        rejected = False
        try:
            await query(request, scopes[0])
        except IntegrityViolation:
            rejected = True
        require(rejected, 'source_python_corruption_accepted')
        await resource.close()
        await node_check({'mode': 'corrupt', 'request': request, 'scope': scopes[0].model_dump(mode='json')})
        checks.append('python_node_stored_span_corruption_refused_as_integrity_failure')
        await command('UPDATE cragkit.chunks SET start_byte=%s,end_byte=%s WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND revision_id=%s AND generation_id=%s AND chunk_id=%s',
                      (*original_span, *stored_span))
        original_span = None
        await assert_trigger()
        resource = PoolResource(config.model_copy(update={'max_size': 1}))
        await resource.open()
        require(await query(request, scopes[0]) == cases[0]['expected'], 'source_recovery_result_changed')
        await resource.close()
        checks.append('source_trigger_and_span_restored_runtime_reuse_passed')
        return checks
    finally:
        await resource.close()
        if original_span is not None and stored_span is not None:
            await command('UPDATE cragkit.chunks SET start_byte=%s,end_byte=%s WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND revision_id=%s AND generation_id=%s AND chunk_id=%s',
                          (*original_span, *stored_span))
        await assert_trigger()
