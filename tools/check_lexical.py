"""Scoped lexical acceptance within the explicit empty-target fixture."""
from __future__ import annotations


async def run(config, fixture, admin):
    import asyncio
    import json
    import os
    from pathlib import Path
    import tempfile
    from psycopg import sql
    from cragkit._postgres_pool import PoolResource
    from cragkit._postgres_session import PostgresSession, _LEXICAL_SQL
    from cragkit.contracts import parse_request, parse_scope
    from cragkit.ingestion import PostgresIndexer
    from check_ingestion import require

    scopes = [parse_scope(value) for value in fixture['scopes']]
    collection = fixture['collection']
    resource = PoolResource(config.model_copy(update={'max_size': 1}))
    loop = asyncio.get_running_loop()
    checks = []

    async def query(scope, *, filters=None, limit=100):
        request = parse_request({'query': 'Café', 'collection': collection, 'required_filters': filters or []})
        async with PostgresSession(resource).transaction(request, scope=scope, deadline=loop.time()+8) as handle:
            return [candidate.model_dump(mode='json') for candidate in await handle.lexical_candidates(limit=limit)]

    async def authorize(scope, target_collection, document):
        return scope in scopes and target_collection == collection and document == 'tie-document'

    async def node_verify(expected, label):
        with tempfile.TemporaryDirectory(prefix='cragkit-lexical-') as directory:
            paths = [Path(directory)/'runtime.json', Path(directory)/'fixture.json']
            for path, value in zip(paths,(config.model_dump(mode='json'),{**fixture,'expected':expected}),strict=True):
                descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                with os.fdopen(descriptor,'w',encoding='utf-8') as destination:json.dump(value,destination)
            process=await asyncio.create_subprocess_exec('node',str(Path(__file__).with_name('check_typescript_lexical.mjs').resolve()),
                '--allow-lexical-checks',*(str(path) for path in paths),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,limit=8192)
            try:
                async with asyncio.timeout(40):output,_=await process.communicate()
                require(len(output)<8192,'lexical_node_result_size')
                result=json.loads(output)
                require(process.returncode==0 and result.get('state')=='passed',result.get('code','lexical_node_failed'))
                require(result.get('checks')==['node_scoped_fts_matches_python_filters_limit_authorization_tombstone_readiness'],'lexical_node_protocol')
                checks.append(label)
            finally:
                if process.returncode is None:process.kill();await process.wait()

    try:
        await resource.open()
        indexer = PostgresIndexer(resource, authorize_write=authorize)
        source = '\ufeffNode Café🙂\r\n\r\nNative source\n'
        for scope in scopes:
            await indexer.ingest(source, collection=collection, document_id='tie-document', intent_id='lexical-tie',
                source_locator='synthetic:lexical', scope=scope, deadline=loop.time()+15,
                canonical_options={'target_bytes': 8, 'max_chunk_bytes': 16})
        # Convert the actual fixture LOGIN to a read-only role; the admin remains separate.
        for table in ('collections','documents','document_revisions','index_generations','chunks','chunk_lexical','document_grants','ingestion_jobs'):
            await admin.execute(sql.SQL('REVOKE INSERT,UPDATE ON cragkit.{} FROM {}').format(sql.Identifier(table),sql.Identifier(config.user)))
        expected = []
        for scope in scopes:
            candidates = await query(scope)
            require([item['document_id'] for item in candidates] == ['node-document','tie-document'], 'lexical_stable_tie')
            require(all(item['tenant_id'] == scope.tenant_id and item['collection'] == collection for item in candidates), 'lexical_tenant_leak')
            require(candidates == await query(scope), 'lexical_order_unstable')
            require(await query(scope, limit=1) == candidates[:1], 'lexical_limit')
            require(await query(scope, filters=[{'op':'eq','field':'document_id','value':'tie-document'}], limit=1) == candidates[1:], 'lexical_filter_before_limit')
            require(await query(scope, filters=[{'op':'eq','field':'document_id','value':"missing' OR TRUE --"}]) == [], 'lexical_filter_injection')
            expected.append(candidates)
        require(expected[0][0]['revision_id'] != expected[1][0]['revision_id'], 'lexical_cross_tenant_revision')
        for changes in ({'principal_id':'unauthorized-principal','grant_ids':[]}, {'authorization_revision':'stale'}):
            require(await query(parse_scope({**scopes[0].model_dump(mode='json'),**changes})) == [], 'lexical_unauthorized_scope')
        checks.append('python_scoped_fts_stable_ties_filters_limit_principal_revision')
        key = (scopes[0].tenant_id, collection, 'tie-document')
        await admin.execute('UPDATE cragkit.documents SET tombstoned=true WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',key)
        try:
            require([item['document_id'] for item in await query(scopes[0])] == ['node-document'], 'lexical_tombstone')
        finally:
            await admin.execute('UPDATE cragkit.documents SET tombstoned=false WHERE tenant_id=%s AND collection_id=%s AND document_id=%s',key)
        generation = expected[0][0]['generation_id']
        await admin.execute("UPDATE cragkit.index_generations SET status='staging' WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s", (scopes[0].tenant_id,collection,'node-document',generation))
        try:
            require([item['document_id'] for item in await query(scopes[0])] == ['tie-document'], 'lexical_unready_generation')
        finally:
            await admin.execute("UPDATE cragkit.index_generations SET status='ready' WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s", (scopes[0].tenant_id,collection,'node-document',generation))
        checks.append('python_tombstone_and_unready_generation_exclusion')
        async with resource.lease(deadline=loop.time()+8) as connection:
            async with connection.transaction(force_rollback=True):
                await connection.execute("SELECT set_config('cragkit.tenant_id',%s,true)",(scopes[0].tenant_id,))
                statement = _LEXICAL_SQL.format(predicate='TRUE')
                cursor = await connection.execute('EXPLAIN (FORMAT JSON) '+statement,('Café',scopes[0].tenant_id,collection,
                    scopes[0].authorization_revision,scopes[0].authorization_revision,scopes[0].principal_id,[],1))
                rows = await cursor.fetchall()
                require(rows[0][0][0]['Plan']['Node Type'] == 'Limit','lexical_explain_limit')
        checks.append('scoped_fts_explain_limit_inspected')
        await resource.close()
        await node_verify(expected, 'node_scoped_fts_ties_filters_before_limit_matches_python')
        resource = PoolResource(config.model_copy(update={'max_size': 1}))
        await resource.open()
        # Leave one tombstone and one unready generation for the native Node exclusion checks.
        await admin.execute('UPDATE cragkit.documents SET tombstoned=true WHERE tenant_id=%s AND collection_id=%s AND document_id=%s', key)
        await admin.execute("UPDATE cragkit.index_generations SET status='staging' WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s",
            (scopes[1].tenant_id,collection,'node-document',expected[1][0]['generation_id']))
        expected = [await query(scope) for scope in scopes]
        require([[item['document_id'] for item in candidates] for candidates in expected] == [['node-document'],['tie-document']], 'lexical_node_exclusion_fixture')
        await resource.close()
        await node_verify(expected, 'node_scoped_fts_tombstone_readiness_matches_python')
        return checks
    finally:
        await resource.close()
        await admin.execute('UPDATE cragkit.documents SET tombstoned=false WHERE tenant_id=ANY(%s) AND collection_id=%s AND document_id=%s',
            ([scope.tenant_id for scope in scopes],collection,'tie-document'))
        await admin.execute("UPDATE cragkit.index_generations SET status='ready' WHERE tenant_id=ANY(%s) AND collection_id=%s AND document_id=%s",
            ([scope.tenant_id for scope in scopes],collection,'node-document'))
