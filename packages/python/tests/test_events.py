import asyncio

import pytest

from cragkit.errors import InvalidRequest
from cragkit.events import EventSink, new_trace

TRACE = '00000000-0000-4000-8000-000000000001'


def emit(sink, stage='search', **options):
    return sink.emit(stage, trace_id=TRACE, attempt=1, elapsed_ms=0, **options)


def test_emit_queue_only_overflow_ordinal_drain_and_close():
    calls = []
    async def exporter(event, *, deadline):
        calls.append(event)
    sink = EventSink(exporter, capacity=1)
    assert emit(sink)
    assert not emit(sink)
    assert calls == []
    rows = sink.drain()
    assert rows[0]['event_id'] == TRACE + ':1'
    assert sink.snapshot() == {'queued': 0, 'dropped': 2, 'exported': 0}
    assert emit(sink)
    assert sink.drain()[0]['event_id'] == TRACE + ':3'
    sink.close()
    sink.close()
    with pytest.raises(InvalidRequest):
        emit(sink)
    assert new_trace() != new_trace()


def test_only_fixed_redacted_fields_are_accepted():
    sink = EventSink()
    for key, value in [('trace_id', 'postgres://private'), ('stage', 'private query'),
                       ('candidate_count', True), ('provider_calls', -1), ('elapsed_ms', float('nan')),
                       ('attempt', 11), ('stop_reason', 'secret')]:
        options = dict(stage='search', trace_id=TRACE, attempt=0, elapsed_ms=0)
        options[key] = value
        with pytest.raises(InvalidRequest):
            sink.emit(**options)
    assert emit(sink, 'error', stop_reason='provider_unavailable')
    assert emit(sink, 'stop', stop_reason='no_progress')
    assert emit(sink, 'cancelled', stop_reason='cancelled')
    assert 'private' not in str(sink.drain())


def test_flush_success_fault_and_snapshot_work_bound():
    async def scenario():
        calls = []
        async def exporter(event, *, deadline):
            calls.append(event)
            if len(calls) == 1:
                emit(sink)
                raise RuntimeError('secret backend error')
            event['stage'] = 'mutated'
        sink = EventSink(exporter)
        emit(sink)
        emit(sink)
        result = await sink.flush(asyncio.get_running_loop().time() + 1)
        assert result == dict(queued=1, dropped=1, exported=1)
        assert len(calls) == 2
        result['exported'] = 999
        assert sink.snapshot()['exported'] == 1
        assert sink.drain()[0]['stage'] == 'search'
    asyncio.run(scenario())


def test_timeout_ignoring_cancel_has_at_most_one_unsettled_exporter():
    async def scenario():
        release, finished = asyncio.Event(), asyncio.Event()
        calls = []
        async def exporter(event, *, deadline):
            calls.append(event)
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            finished.set()
        sink = EventSink(exporter, timeout_ms=1)
        emit(sink)
        emit(sink)
        result = await sink.flush(asyncio.get_running_loop().time() + 1)
        assert result == dict(queued=0, dropped=2, exported=0)
        emit(sink)
        await sink.flush(asyncio.get_running_loop().time() + 1)
        assert len(calls) == 1 and sink.snapshot()['dropped'] == 3
        release.set()
        await finished.wait()
        await asyncio.sleep(0)
        sink.close()
    asyncio.run(scenario())


def test_concurrent_flush_and_native_cancellation_are_bounded():
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def exporter(event, *, deadline):
            calls.append(event)
            started.set()
            await release.wait()
        sink = EventSink(exporter, timeout_ms=100)
        emit(sink)
        emit(sink)
        task = asyncio.create_task(sink.flush(asyncio.get_running_loop().time() + 1))
        await started.wait()
        await sink.flush(asyncio.get_running_loop().time() + 1)
        assert len(calls) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert sink.snapshot() == dict(queued=0, dropped=2, exported=0)
        release.set()
        await asyncio.sleep(0)
        sink.close()
    asyncio.run(scenario())


def test_expired_deadline_no_exporter_and_closed_sink_drop_events():
    async def scenario():
        calls = []
        async def exporter(event, *, deadline):
            calls.append(event)
        sink = EventSink(exporter)
        emit(sink)
        assert (await sink.flush(-1))['dropped'] == 1
        assert calls == []
        no_exporter = EventSink()
        emit(no_exporter)
        assert (await no_exporter.flush(asyncio.get_running_loop().time() + 1))['dropped'] == 1
        emit(sink)
        sink.close()
        assert (await sink.flush(asyncio.get_running_loop().time() + 1))['dropped'] == 2
    asyncio.run(scenario())


def test_exporter_self_cancellation_and_close_do_not_cancel_flush_caller():
    async def scenario():
        async def self_cancel(event, *, deadline):
            raise asyncio.CancelledError()
        sink = EventSink(self_cancel)
        emit(sink)
        assert await sink.flush(asyncio.get_running_loop().time() + 1) == dict(queued=0, dropped=1, exported=0)
        started = asyncio.Event()
        async def hanging(event, *, deadline):
            started.set()
            await asyncio.Event().wait()
        sink = EventSink(hanging, timeout_ms=100)
        emit(sink)
        emit(sink)
        task = asyncio.create_task(sink.flush(asyncio.get_running_loop().time() + 1))
        await started.wait()
        sink.close()
        assert await task == dict(queued=0, dropped=2, exported=0)
    asyncio.run(scenario())
