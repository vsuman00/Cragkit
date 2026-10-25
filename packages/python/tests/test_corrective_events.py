import asyncio

import pytest

from cragkit.corrective import CorrectiveRetriever
from cragkit.errors import InvalidRequest, ProviderUnavailable
from cragkit.events import EventSink
from test_corrective import A, Backend, REQUEST, SCOPE, retriever, run


def test_corrective_events_order_counts_and_no_export_on_retrieval():
    delivered = []
    async def exporter(event, *, deadline):
        delivered.append(event)
    sink = EventSink(exporter)
    output = run(retriever(Backend(), event_sink=sink))
    assert delivered == []
    metadata = output['diagnostics']['events']
    assert metadata['queued'] == 8 and metadata['exported'] == 0
    rows = sink.drain()
    assert [row['stage'] for row in rows] == ['start', 'search', 'capture', 'planning', 'capture', 'search', 'capture', 'stop']
    assert [row['attempt'] for row in rows] == [0, 1, 1, 1, 1, 2, 2, 2]
    assert rows[1]['candidate_count'] == 16 and rows[-1]['candidate_count'] == 32
    assert rows[-1]['stop_reason'] == 'sufficient'
    assert {row['trace_id'] for row in rows} == {metadata['trace_id']}
    assert [row['event_id'] for row in rows] == [metadata['trace_id'] + ':' + str(index) for index in range(1, 9)]


def test_overflow_closed_sink_and_invalid_sink_do_not_change_evidence():
    plain = run(CorrectiveRetriever(Backend()))
    assert 'events' not in plain['diagnostics']
    for closed in (False, True):
        sink = EventSink(capacity=1)
        if closed:
            sink.close()
        output = run(CorrectiveRetriever(Backend(), event_sink=sink))
        assert output['result'] == plain['result']
        assert output['diagnostics']['events']['exported'] == 0
        if not closed:
            assert output['diagnostics']['events']['dropped'] == 3
    sink = EventSink()
    def fail(*args, **kwargs):
        raise RuntimeError('private sink failure')
    sink.emit = fail
    output = run(CorrectiveRetriever(Backend(), event_sink=sink))
    assert output['result'] == plain['result']
    class Subclass(EventSink):
        pass
    with pytest.raises(InvalidRequest):
        CorrectiveRetriever(Backend(), event_sink=Subclass())


def test_error_retry_and_secret_canaries_are_redacted():
    class Fault(Backend):
        async def search(self, request, **options):
            self.calls.append(request)
            raise ProviderUnavailable()
    sink = EventSink()
    backend = Fault()
    with pytest.raises(ProviderUnavailable):
        run(CorrectiveRetriever(backend, max_retries=1, event_sink=sink), dict(REQUEST, query='private-query-secret'))
    rows = sink.drain()
    assert [row['stage'] for row in rows] == ['start', 'search', 'retry', 'search', 'error']
    assert rows[-1]['stop_reason'] == 'provider_unavailable'
    assert 'private-query-secret' not in str(rows)
    assert A[1]['source_sha256'] not in str(rows)


def test_native_cancellation_emits_terminal_event_and_keeps_sink_open():
    async def scenario():
        started = asyncio.Event()
        class Slow(Backend):
            async def search(self, request, **options):
                started.set()
                await asyncio.Event().wait()
        sink = EventSink()
        core = CorrectiveRetriever(Slow(), event_sink=sink)
        task = asyncio.create_task(core.retrieve(REQUEST, scope=SCOPE, deadline=asyncio.get_running_loop().time() + 1))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        rows = sink.drain()
        assert [row['stage'] for row in rows] == ['start', 'search', 'cancelled']
        assert rows[-1]['stop_reason'] == 'cancelled'
        assert sink.emit('start', trace_id=rows[0]['trace_id'], attempt=0, elapsed_ms=0)
    asyncio.run(scenario())


def test_shared_sink_keeps_concurrent_request_traces_separate():
    async def scenario():
        sink = EventSink()
        core = CorrectiveRetriever(Backend(), event_sink=sink)
        responses = await asyncio.gather(*(core.retrieve(dict(REQUEST, request_id=rid), scope=SCOPE,
                    deadline=asyncio.get_running_loop().time() + 1) for rid in ('one', 'two')))
        traces = [row['diagnostics']['events']['trace_id'] for row in responses]
        assert len(set(traces)) == 2
        rows = sink.drain()
        for trace in traces:
            own = [row for row in rows if row['trace_id'] == trace]
            assert [row['stage'] for row in own] == ['start', 'search', 'capture', 'stop']
    asyncio.run(scenario())
