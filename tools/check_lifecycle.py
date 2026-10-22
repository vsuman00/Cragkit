"""Bounded lifecycle acceptance inside the explicitly authorized empty-target fixture."""
from __future__ import annotations


async def run(config, fixture, admin):
    import asyncio
    import json
    from contextlib import asynccontextmanager
    import os
    from pathlib import Path
    import tempfile
    from psycopg import sql

    from cragkit._postgres_pool import PoolResource
    from cragkit._postgres_session import LexicalCandidate, PostgresSession, _SCOPE_SQL
    from cragkit.contracts import parse_request, parse_scope
    from cragkit.errors import CragkitError, IndexNotReady, UnauthorizedScope
    from cragkit.ingestion import PostgresIndexer
    from cragkit.lifecycle import PostgresLifecycle, _PURGE_INSERT_SQL
    from cragkit.retrieval import PostgresRetriever
    from check_ingestion import IngestionCheckError, require

    loop = asyncio.get_running_loop()
    scope = parse_scope(fixture['scopes'][0])
    collection = fixture['collection']
    role = config.user
    checks = []
    stage = 'setup'
    tables = ('collections', 'documents', 'document_revisions', 'index_generations',
              'chunks', 'chunk_lexical', 'document_grants', 'ingestion_jobs')
    documents = {'python': 'lifecycle-python', 'node': 'lifecycle-node'}
    results = {}
    candidates = {}
    blocked_policy = role + '_lifecycle_insert'
    hidden_policy = role + '_lifecycle_hidden'

    async def command(statement, parameters=None):
        async with asyncio.timeout(10):
            return await admin.execute(statement, parameters)

    async def rows(statement, parameters=None):
        cursor = await command(statement, parameters)
        async with asyncio.timeout(10):
            return await cursor.fetchall()

    async def permissions(mode):
        # Every runtime pool has closed before changing this isolated fixture role.
        for table in tables:
            await command(sql.SQL('REVOKE INSERT,UPDATE,DELETE ON cragkit.{} FROM {}').format(
                sql.Identifier(table), sql.Identifier(role)))
        await command(sql.SQL('REVOKE UPDATE(created_at) ON cragkit.documents FROM {}').format(sql.Identifier(role)))
        if mode == 'write':
            for table in tables:
                await command(sql.SQL('GRANT INSERT,UPDATE ON cragkit.{} TO {}').format(
                    sql.Identifier(table), sql.Identifier(role)))
        elif mode == 'purge':
            await command(sql.SQL('GRANT INSERT,DELETE ON cragkit.documents TO {}').format(sql.Identifier(role)))
            # SELECT FOR UPDATE requires UPDATE on at least one column.
            await command(sql.SQL('GRANT UPDATE(created_at) ON cragkit.documents TO {}').format(sql.Identifier(role)))

    async def snapshot(document):
        key = (scope.tenant_id, collection, document)
        output = []
        for table in tables[1:]:
            output.append(await rows(sql.SQL('SELECT count(*) FROM cragkit.{} WHERE tenant_id=%s AND collection_id=%s AND document_id=%s').format(sql.Identifier(table)), key))
        output.append(await rows('SELECT active_generation_id,tombstoned,metadata,authorization_revision,created_at::text FROM cragkit.documents WHERE tenant_id=%s AND collection_id=%s AND document_id=%s', key))
        return output

    async def node(mode, **extra):
        value = {'mode': mode, 'collection': collection, 'document_id': documents['node'],
                 'scope': scope.model_dump(mode='json'), **extra}
        with tempfile.TemporaryDirectory(prefix='cragkit-lifecycle-') as directory:
            paths = [Path(directory) / name for name in ('runtime.json', 'fixture.json')]
            for path, content in zip(paths, (config.model_dump(mode='json'), value)):
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                    json.dump(content, stream)
            process = await asyncio.create_subprocess_exec(
                'node', str(Path(__file__).with_name('check_typescript_lifecycle.mjs').resolve()),
                '--allow-lifecycle-checks', *(str(path) for path in paths),
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=8192)
            try:
                async with asyncio.timeout(90):
                    output, _ = await process.communicate()
                require(len(output) <= 8192, 'lifecycle_node_output_size')
                result = json.loads(output)
                require(process.returncode == 0 and result.get('state') == 'passed',
                        result.get('code', 'lifecycle_node_failed'))
                return result
            finally:
                if process.returncode is None:
                    process.kill()
                    await process.wait()

    async def python(operation):
        resource = PoolResource(config.model_copy(update={'max_size': 1}))
        try:
            await resource.open()
            return await operation(resource)
        finally:
            await resource.close()

    async def authorize(*args):
        return True

    def options(document, expected):
        return dict(collection=collection, document_id=document, scope=scope,
                    expected_generation_id=expected, deadline=loop.time() + 25)

    def receipt(document, state, active):
        return dict(tenant_id=scope.tenant_id, collection=collection, document_id=document,
                    state=state, active_generation_id=active, changed=True)

    async def rejected(operation, kind, code):
        denied = False
        try:
            await operation()
        except kind:
            denied = True
        require(denied, code)

    async def python_writes(resource):
        document = documents['python']
        indexer = PostgresIndexer(resource, authorize_write=authorize)
        async def ingest(source, writer=indexer, **changes):
            arguments = dict(collection=collection, document_id=document, scope=scope,
                             intent_id=documents['python'] + ':initial', source_locator='synthetic:lifecycle', deadline=loop.time() + 25)
            arguments.update(changes)
            return await writer.ingest(source, **arguments)
        first = await ingest('Lifecycle old café🙂')
        prepared, release = asyncio.Event(), asyncio.Event()
        async def slow_authorizer(*args):
            prepared.set()
            await release.wait()
            return True
        slow_writer = PostgresIndexer(resource, authorize_write=slow_authorizer)
        slow = asyncio.create_task(ingest('Lifecycle slow loser', writer=slow_writer,
                                         intent_id=documents['python'] + ':slow', expected_generation_id=first.generation_id))
        try:
            async with asyncio.timeout(5):
                await prepared.wait()
            winner = await ingest('Lifecycle fast winner', intent_id=documents['python'] + ':fast', expected_generation_id=first.generation_id)
        finally:
            release.set()
            # Always consume the task, even if the fast writer fails.
            outcome = await asyncio.gather(slow, return_exceptions=True)
        require(isinstance(outcome[0], IndexNotReady), 'lifecycle_python_stale_update_overwrote')
        before = await snapshot(document)
        class Crash(Exception):
            pass
        async def crash():
            raise Crash()
        await rejected(lambda: ingest('Lifecycle crash unpublished', intent_id=documents['python'] + ':crash',
                                      expected_generation_id=winner.generation_id, before_publish=crash),
                       Crash, 'lifecycle_python_crash_published')
        require(await snapshot(document) == before, 'lifecycle_python_crash_left_storage')
        return dict(first=first.model_dump(mode='json'), winner=winner.model_dump(mode='json'))

    async def python_read(resource, visible):
        document = documents['python']
        request = parse_request(dict(collection=collection, query='Lifecycle',
            required_filters=[dict(op='eq', field='document_id', value=document)]))
        result = await PostgresRetriever(resource).retrieve(request, scope=scope, deadline=loop.time() + 20)
        require(result.status == ('partial' if visible else 'insufficient'), 'lifecycle_python_visibility')
        if visible:
            require(len(result.evidence) == 1 and result.evidence[0].revision_id == results['python']['winner']['revision_id'],
                    'lifecycle_python_active_revision')
        else:
            require(not result.evidence, 'lifecycle_python_deleted_evidence')
        async with PostgresSession(resource).transaction(request, scope=scope, deadline=loop.time() + 20) as handle:
            source = await handle.fetch_evidence(LexicalCandidate.model_validate(candidates['python']), max_source_bytes=16777216)
        require(source.state == ('verified' if visible else 'unavailable'), 'lifecycle_python_historical_state')
        if visible:
            require(source.stale and source.evidence.text == 'Lifecycle old café🙂', 'lifecycle_python_revision_mixed')

    async def both_read(visible):
        await python(lambda resource: python_read(resource, visible))
        await node('read', visible=visible, winner=results['node']['winner'], candidate=candidates['node'])

    try:
        unrelated_before = await rows('SELECT tenant_id,document_id,active_generation_id FROM cragkit.documents WHERE tenant_id=%s ORDER BY document_id', (fixture['scopes'][1]['tenant_id'],))
        await permissions('write')
        stage = 'python_updates'
        results['python'] = await python(python_writes)
        stage = 'node_updates'
        results['node'] = await node('write')
        for language, document in documents.items():
            key = (scope.tenant_id, collection, document)
            require(await rows('SELECT active_generation_id,tombstoned FROM cragkit.documents WHERE tenant_id=%s AND collection_id=%s AND document_id=%s', key) == [(results[language]['winner']['generation_id'], False)], 'lifecycle_winner_pointer')
            require(await rows('SELECT count(*) FROM cragkit.ingestion_jobs WHERE tenant_id=%s AND collection_id=%s AND document_id=%s', key) == [(2,)], 'lifecycle_crash_or_loser_job_leaked')
            require(await rows('SELECT count(*) FROM cragkit.document_revisions WHERE tenant_id=%s AND collection_id=%s AND document_id=%s', key) == [(2,)], 'lifecycle_crash_or_loser_revision_leaked')
            first = results[language]['first']
            chunk = await rows('SELECT chunk_id,start_byte,end_byte,text_sha256 FROM cragkit.chunks WHERE tenant_id=%s AND collection_id=%s AND document_id=%s AND generation_id=%s', (*key, first['generation_id']))
            require(len(chunk) == 1, 'lifecycle_old_chunk_shape')
            candidates[language] = dict(tenant_id=scope.tenant_id, collection=collection, document_id=document,
                revision_id=first['revision_id'], generation_id=first['generation_id'], chunk_id=chunk[0][0],
                start_byte=chunk[0][1], end_byte=chunk[0][2], text_sha256=chunk[0][3], score=1.0)
        checks.append('python_node_controlled_late_update_cas_and_interrupted_publication_rollback')
        await permissions('read')
        stage = 'retained_read'
        await both_read(True)
        checks.append('python_node_active_winner_and_retained_immutable_stale_source')

        await permissions('write')
        async def tombstone(resource):
            lifecycle = PostgresLifecycle(resource, authorize_lifecycle=authorize)
            input = options(documents['python'], results['python']['winner']['generation_id'])
            async def deny(*args): return False
            await rejected(lambda: PostgresLifecycle(resource, authorize_lifecycle=deny).tombstone(**input), UnauthorizedScope, 'lifecycle_python_callback_denial')
            await rejected(lambda: lifecycle.tombstone(**{**input, 'expected_generation_id': 'stale'}), IndexNotReady, 'lifecycle_python_stale_tombstone')
            first = await lifecycle.tombstone(**input)
            require(first.model_dump(mode='json') == receipt(documents['python'], 'tombstoned', input['expected_generation_id']), 'lifecycle_python_tombstone_receipt')
            require((await lifecycle.tombstone(**input)).changed is False, 'lifecycle_python_tombstone_repeat')
        stage = 'tombstone'
        await python(tombstone)
        await node('tombstone', expected_generation_id=results['node']['winner']['generation_id'],
                   expected=receipt(documents['node'], 'tombstoned', results['node']['winner']['generation_id']))
        await permissions('read')
        stage = 'deleted_read'
        await both_read(False)
        checks.append('python_node_tombstone_receipts_denial_and_immediate_fresh_retrieval_exclusion')

        before = {language: await snapshot(document) for language, document in documents.items()}
        await permissions('purge')
        await command(sql.SQL('CREATE POLICY {} ON cragkit.documents AS RESTRICTIVE FOR INSERT TO {} WITH CHECK (NOT tombstoned)').format(sql.Identifier(blocked_policy), sql.Identifier(role)))
        async def purge(resource, expected):
            return await PostgresLifecycle(resource, authorize_lifecycle=authorize).purge_tombstoned(**options(documents['python'], expected))
        stage = 'purge_rollback'
        async def rejected_reinsertion(resource):
            observed = []
            class ConnectionProbe:
                def __init__(self, connection): self.connection = connection
                def __getattr__(self, name): return getattr(self.connection, name)
                async def execute(self, statement, parameters=None):
                    if statement == _PURGE_INSERT_SQL:
                        observed.append(True)
                    return await self.connection.execute(statement, parameters)
            class ResourceProbe:
                config = resource.config
                @asynccontextmanager
                async def lease(self, *, deadline):
                    async with resource.lease(deadline=deadline) as connection:
                        yield ConnectionProbe(connection)
            lifecycle = PostgresLifecycle(ResourceProbe(), authorize_lifecycle=authorize)
            await rejected(lambda: lifecycle.purge_tombstoned(**options(documents['python'], results['python']['winner']['generation_id'])),
                           UnauthorizedScope, 'lifecycle_python_failed_purge_committed')
            require(observed == [True], 'lifecycle_python_reinsertion_not_reached')
        await python(rejected_reinsertion)
        await node('purge_denied', expected_generation_id=results['node']['winner']['generation_id'])
        for language, document in documents.items():
            require(await snapshot(document) == before[language], 'lifecycle_purge_rollback_lost_graph')
        checks.append('python_node_failed_stub_reinsertion_rolls_back_entire_cascade')
        await command(sql.SQL('DROP POLICY {} ON cragkit.documents').format(sql.Identifier(blocked_policy)))
        await command(sql.SQL('CREATE POLICY {} ON cragkit.document_revisions AS RESTRICTIVE FOR SELECT TO {} USING (false)').format(sql.Identifier(hidden_policy), sql.Identifier(role)))
        async def hidden_purge(resource):
            async with resource.lease(deadline=loop.time() + 10) as connection:
                async with connection.transaction(force_rollback=True):
                    await connection.execute(_SCOPE_SQL, (scope.tenant_id, scope.principal_id, scope.authorization_revision, json.dumps(list(scope.grant_ids))))
                    cursor = await connection.execute('SELECT count(*) FROM cragkit.document_revisions WHERE tenant_id=%s AND collection_id=%s AND document_id=%s', (scope.tenant_id, collection, documents['python']))
                    require(await cursor.fetchall() == [(0,)], 'lifecycle_python_child_not_hidden')
            return await purge(resource, results['python']['winner']['generation_id'])
        stage = 'hidden_purge'
        output = await python(hidden_purge)
        require(output.model_dump(mode='json') == receipt(documents['python'], 'purged', None), 'lifecycle_python_purge_receipt')
        require((await python(lambda resource: purge(resource, None))).model_dump(mode='json') == output.model_dump(mode='json'), 'lifecycle_python_repeat_purge')
        await node('purge', expected_generation_id=results['node']['winner']['generation_id'], expected=receipt(documents['node'], 'purged', None))
        for language, document in documents.items():
            after = await snapshot(document)
            require(after[:7] == [[(1,)], *[[(0,)]] * 6], 'lifecycle_purge_hidden_child_survived')
            marker = after[-1]
            require(len(marker) == 1 and marker[0][:4] == (None, True, {}, scope.authorization_revision)
                    and marker[0][4] == before[language][-1][0][4], 'lifecycle_purge_marker_changed')
        checks.append('python_node_restricted_parent_cascade_purges_hidden_source_and_preserves_minimal_marker')
        await command(sql.SQL('DROP POLICY {} ON cragkit.document_revisions').format(sql.Identifier(hidden_policy)))
        await permissions('write')
        async def resurrection(resource):
            writer = PostgresIndexer(resource, authorize_write=authorize)
            await rejected(lambda: writer.ingest('Lifecycle old café🙂', collection=collection, document_id=documents['python'],
                intent_id=documents['python'] + ':initial', source_locator='synthetic:lifecycle', scope=scope, deadline=loop.time() + 20),
                UnauthorizedScope, 'lifecycle_python_resurrection')
        stage = 'resurrection'
        await python(resurrection)
        await node('resurrection')
        await permissions('read')
        stage = 'deleted_read'
        await both_read(False)
        require(await rows('SELECT tenant_id,document_id,active_generation_id FROM cragkit.documents WHERE tenant_id=%s ORDER BY document_id', (fixture['scopes'][1]['tenant_id'],)) == unrelated_before, 'lifecycle_other_tenant_changed')
        checks.append('python_node_purged_historical_citations_unavailable_and_resurrection_blocked_other_tenant_unchanged')
        return checks
    except CragkitError as error:
        raise IngestionCheckError('lifecycle_' + stage + '_' + error.code) from None
    finally:
        await command(sql.SQL('DROP POLICY IF EXISTS {} ON cragkit.documents').format(sql.Identifier(blocked_policy)))
        await command(sql.SQL('DROP POLICY IF EXISTS {} ON cragkit.document_revisions').format(sql.Identifier(hidden_policy)))
        await permissions('read')
