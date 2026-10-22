"""Synthetic VG-r1 publication transactions and failure barriers."""
import asyncio

import pytest

from cragkit.errors import IndexNotReady, IntegrityViolation, InvalidRequest, UnauthorizedScope
from test_vector_ingestion import fixture, stage


async def publish(indexer, source='synthetic source', **changes):
    from test_vector_ingestion import scope
    values = dict(collection='collection',document_id='document',intent_id='intent',
        source_locator='synthetic:source',scope=scope(),deadline=asyncio.get_running_loop().time()+2)
    values.update(changes)
    return await indexer.publish(source,**values)


def publication_fixture(**options):
    connection, resource, transport, indexer = fixture(**options)
    original = connection.execute
    connection.cas_rows = [(1,)]
    connection.job_rows = [(1,)]
    async def execute(query,params=None):
        if query.lstrip().startswith('UPDATE cragkit.documents'):
            connection.calls.append((query,params))
            if connection.cas_rows == [(1,)]:
                connection.document = [(params[0],False,params[-1])]
                connection.published.append(params)
            from test_ingestion import Cursor
            return Cursor(connection.cas_rows)
        if query.lstrip().startswith('UPDATE cragkit.ingestion_jobs') and "state='succeeded'" in query:
            connection.calls.append((query,params))
            if connection.job_rows == [(1,)]:
                job = connection.vector_job[0]
                connection.vector_job = [(job[0],job[1],'succeeded',*job[3:])]
            from test_ingestion import Cursor
            return Cursor(connection.job_rows)
        result = await original(query,params)
        if query.lstrip().startswith('UPDATE cragkit.index_generations') and connection.ready_rows == [(1,)]:
            generation = connection.vector_generation[0]
            connection.vector_generation = [(generation[0],'ready',*generation[2:])]
        return result
    connection.execute = execute
    return connection,resource,transport,indexer


def test_ready_barrier_pointer_and_job_commit_atomically_without_provider():
    async def run():
        connection, resource, transport, indexer = publication_fixture()
        staged = await stage(indexer)
        before = len(transport.calls)
        result = await publish(indexer)
        assert result.generation_id == staged.generation_id
        assert result.provider_calls == 0 and result.usage == ()
        assert connection.document == [(result.generation_id,False,'auth')]
        assert connection.vector_generation[0][1] == 'ready'
        assert connection.vector_job[0][2] == 'succeeded'
        assert len(transport.calls) == before
        assert resource.leased == resource.returned
        queries = [query for query,_ in connection.calls]
        ready = next(i for i,q in enumerate(queries) if q.startswith('UPDATE cragkit.index_generations'))
        pointer = next(i for i,q in enumerate(queries) if q.startswith('UPDATE cragkit.documents'))
        assert ready < pointer
        replay = await publish(indexer)
        assert replay.replayed and replay.provider_calls == 0
        assert len(connection.published) == 1
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['chunks','lexical','vectors','mixed-profile','mixed-generation','chunker','lexical-profile'])
def test_incomplete_or_mixed_manifest_never_publishes(kind):
    async def run():
        connection, resource, transport, indexer = publication_fixture()
        await stage(indexer)
        if kind == 'chunks': connection.counts_override = [(0,1)]
        if kind == 'lexical': connection.counts_override = [(1,0)]
        if kind == 'vectors': connection.vector_count_override = [(0,)]
        if kind in ('mixed-profile','mixed-generation','chunker','lexical-profile'):
            row = list(connection.vector_generation[0])
            row[{'mixed-profile':3,'mixed-generation':0,'chunker':4,'lexical-profile':5}[kind]] = 'wrong'
            connection.vector_generation = [tuple(row)]
        with pytest.raises(IntegrityViolation): await publish(indexer)
        assert connection.document == [(None,False,'auth')]
        assert not connection.published and connection.vector_job[0][2] == 'running'
        assert len(transport.calls) == 1 and resource.leased == resource.returned
    asyncio.run(run())


@pytest.mark.parametrize('barrier,kind', [('ready_rows',IntegrityViolation),('cas_rows',IndexNotReady),('job_rows',IntegrityViolation)])
def test_missing_transition_row_rolls_back_all_publication_mutations(barrier,kind):
    async def run():
        connection, _, _, indexer = publication_fixture()
        await stage(indexer)
        setattr(connection,barrier,[])
        with pytest.raises(kind): await publish(indexer)
        assert connection.document == [(None,False,'auth')]
        assert connection.vector_generation[0][1] == 'staging'
        assert connection.vector_job[0][2] == 'running' and not connection.published
        assert connection.rolled_back >= 1
    asyncio.run(run())


def test_before_publish_failure_preserves_exception_and_staged_generation():
    async def run():
        connection, resource, _, indexer = publication_fixture()
        await stage(indexer)
        sentinel = RuntimeError('caller hook failure')
        async def fail():
            assert not connection.published and connection.vector_generation[0][1] == 'staging'
            raise sentinel
        with pytest.raises(RuntimeError) as caught: await publish(indexer,before_publish=fail)
        assert caught.value is sentinel
        assert connection.document == [(None,False,'auth')]
        assert connection.vector_generation[0][1] == 'staging' and not connection.published
        assert resource.leased == resource.returned
    asyncio.run(run())


@pytest.mark.parametrize('change', ['grants','revision','tombstone'])
def test_revocation_or_tombstone_is_rechecked_after_hook(change):
    async def run():
        connection, _, transport, indexer = publication_fixture()
        await stage(indexer)
        async def revoke():
            if change == 'grants': connection.grants = [(False,)]
            elif change == 'revision': connection.document = [(None,False,'revoked')]
            else: connection.document = [(None,True,'auth')]
        with pytest.raises(UnauthorizedScope): await publish(indexer,before_publish=revoke)
        assert not connection.published and connection.vector_generation[0][1] == 'staging'
        assert len(transport.calls) == 1
    asyncio.run(run())


def test_newer_publication_wins_and_stale_build_cannot_replace_pointer():
    async def run():
        connection, resource, _, indexer = publication_fixture()
        await stage(indexer)
        connection.document = [('newer-ready-generation',False,'auth')]
        with pytest.raises(IndexNotReady): await publish(indexer)
        assert connection.document[0][0] == 'newer-ready-generation'
        assert connection.vector_generation[0][1] == 'staging' and not connection.published
        assert resource.leased == resource.returned
    asyncio.run(run())


def test_publish_recomputes_full_source_and_metadata_identity():
    async def run():
        connection, _, transport, indexer = publication_fixture()
        await stage(indexer)
        for changes in [dict(source='other source'),dict(metadata={'changed':True}),dict(expected_generation_id='forged-pointer')]:
            with pytest.raises(InvalidRequest): await publish(indexer,**changes)
        assert not connection.published and len(transport.calls) == 1
    asyncio.run(run())


def test_publish_without_staged_intent_does_not_create_or_embed():
    async def run():
        connection, resource, transport, indexer = publication_fixture()
        with pytest.raises(IndexNotReady): await publish(indexer)
        assert not connection.staged and not transport.calls and not connection.published
        assert resource.leased == resource.returned
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['cancel','deadline'])
def test_interrupted_publication_hook_rolls_back_and_can_retry(mode):
    from cragkit.errors import DeadlineExceeded
    async def run():
        connection, resource, transport, indexer = publication_fixture()
        await stage(indexer)
        entered = asyncio.Event()
        async def block():
            entered.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(publish(indexer,before_publish=block,
            deadline=asyncio.get_running_loop().time()+(.03 if mode=='deadline' else 2)))
        await entered.wait()
        if mode=='cancel': task.cancel()
        with pytest.raises(asyncio.CancelledError if mode=='cancel' else DeadlineExceeded): await task
        assert not connection.published and connection.vector_generation[0][1] == 'staging'
        assert connection.document == [(None,False,'auth')]
        assert resource.leased == resource.returned
        await publish(indexer)
        assert connection.vector_generation[0][1] == 'ready' and len(transport.calls) == 1
    asyncio.run(run())


def test_ingest_carries_stage_usage_into_publication_receipt():
    async def run():
        from test_vector_ingestion import scope
        connection, resource, transport, indexer = publication_fixture()
        result = await indexer.ingest('synthetic source',collection='collection',document_id='document',
            intent_id='intent',source_locator='synthetic:source',scope=scope(),
            deadline=asyncio.get_running_loop().time()+2)
        assert result.provider_calls == 1 and len(result.usage) == 1
        assert result.usage[0].cost_usd == 0 and len(transport.calls) == 1
        assert connection.document[0][0] == result.generation_id
        assert resource.leased == resource.returned
    asyncio.run(run())


def test_succeeded_retained_generation_replay_never_reverts_newer_pointer():
    async def run():
        connection, _, transport, indexer = publication_fixture()
        await stage(indexer)
        await publish(indexer)
        connection.document = [('newer-ready-generation',False,'auth')]
        replay = await publish(indexer)
        assert replay.replayed and replay.provider_calls == 0
        assert connection.document[0][0] == 'newer-ready-generation'
        assert len(connection.published) == 1 and len(transport.calls) == 1
        connection.grants = [(False,)]
        with pytest.raises(UnauthorizedScope): await publish(indexer)
        assert connection.document[0][0] == 'newer-ready-generation'
    asyncio.run(run())
