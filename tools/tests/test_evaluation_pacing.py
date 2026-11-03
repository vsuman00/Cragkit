"""Synthetic clock tests only: no waits, account access or provider quality claims."""
import asyncio
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation_pacing import EvaluationPacer
from provider_adapters import ProviderAdapterError


class Clock:
    def __init__(self):
        self.now = 100.0
        self.delays = []

    def read(self):
        return self.now

    async def sleep(self, delay):
        self.delays.append(delay)
        self.now += delay


def fixture():
    clock = Clock()
    pacer = EvaluationPacer()
    pacer._clock, pacer._sleep = clock.read, clock.sleep
    return pacer, clock


def test_serial_spacing_and_cross_provider_independence():
    async def run():
        pacer, clock = fixture()
        await pacer.wait('cohere', deadline=200)
        await pacer.wait('openai', deadline=200)
        assert clock.delays == []
        await pacer.wait('cohere', deadline=200)
        assert clock.now >= 106.1
        assert len(clock.delays) == 1 and clock.delays[0] >= 6.1
        clock.now = 120
        await pacer.wait('cohere', deadline=200)
        assert len(clock.delays) == 1
    asyncio.run(run())


@pytest.mark.parametrize('provider', [None, [], 'private-provider', True])
def test_invalid_provider(provider):
    async def run():
        pacer, clock = fixture()
        with pytest.raises(ProviderAdapterError, match='^provider_pacing_invalid$'):
            await pacer.wait(provider, deadline=200)
        assert clock.delays == [] and pacer._last_cohere is None
    asyncio.run(run())


@pytest.mark.parametrize('deadline', [None, True, 'private', float('nan'), float('inf'), 10**1000])
def test_malformed_deadlines(deadline):
    async def run():
        pacer, _ = fixture()
        with pytest.raises(ProviderAdapterError, match='^provider_pacing_invalid$'):
            await pacer.wait('cohere', deadline=deadline)
        assert pacer._last_cohere is None
    asyncio.run(run())


@pytest.mark.parametrize('value', [None, True, 'private', float('nan'), float('inf'), 10**1000, 99])
def test_malformed_or_backwards_clock(value):
    async def run():
        pacer, clock = fixture()
        await pacer.wait('cohere', deadline=200)
        clock.now = value
        with pytest.raises(ProviderAdapterError, match='^provider_pacing_invalid$'):
            await pacer.wait('openai', deadline=200)
        assert pacer._last_cohere == 100
    asyncio.run(run())


@pytest.mark.parametrize('deadline', [99, 100, 105, 106.1])
def test_elapsed_or_insufficient_deadline_never_waits(deadline):
    async def run():
        pacer, clock = fixture()
        await pacer.wait('cohere', deadline=200)
        with pytest.raises(ProviderAdapterError, match='^deadline_exceeded$'):
            await pacer.wait('cohere', deadline=deadline)
        assert clock.delays == [] and pacer._last_cohere == 100
    asyncio.run(run())


@pytest.mark.parametrize('wake,code', [(105, 'provider_pacing_failed'), (200, 'deadline_exceeded'),
                                        (201, 'deadline_exceeded')])
def test_early_and_late_wakeup_do_not_consume_slot(wake, code):
    async def run():
        pacer, clock = fixture()
        await pacer.wait('cohere', deadline=200)
        async def sleep(delay):
            clock.delays.append(delay)
            clock.now = wake
        pacer._sleep = sleep
        with pytest.raises(ProviderAdapterError, match='^' + code + '$'):
            await pacer.wait('cohere', deadline=200)
        assert len(clock.delays) == 1 and pacer._last_cohere == 100 and not pacer._busy
    asyncio.run(run())


def test_sleeper_and_clock_errors_are_fixed_without_private_context():
    async def run():
        pacer, clock = fixture()
        await pacer.wait('cohere', deadline=200)
        async def broken(delay):
            raise RuntimeError('private callback detail')
        pacer._sleep = broken
        with pytest.raises(ProviderAdapterError, match='^provider_pacing_failed$') as caught:
            await pacer.wait('cohere', deadline=200)
        assert caught.value.__context__ is None and pacer._last_cohere == 100
        def broken_clock():
            raise RuntimeError('private clock detail')
        pacer._clock = broken_clock
        with pytest.raises(ProviderAdapterError, match='^provider_pacing_invalid$') as caught:
            await pacer.wait('openai', deadline=200)
        assert caught.value.__context__ is None
    asyncio.run(run())


@pytest.mark.parametrize('suppress', [False, True])
def test_cancellation_and_concurrent_use(suppress):
    async def run():
        pacer, clock = fixture()
        await pacer.wait('cohere', deadline=200)
        entered, release = asyncio.Event(), asyncio.Event()
        async def sleep(delay):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                if not suppress:
                    raise
            clock.now = 107
        pacer._sleep = sleep
        task = asyncio.create_task(pacer.wait('cohere', deadline=200))
        await entered.wait()
        with pytest.raises(ProviderAdapterError, match='^concurrent_dispatch$'):
            await pacer.wait('openai', deadline=200)
        task.cancel('private cancellation detail')
        with pytest.raises(asyncio.CancelledError) as caught:
            await task
        assert caught.value.args == ()
        assert pacer._last_cohere == 100 and not pacer._busy
        pacer._sleep = clock.sleep
        await pacer.wait('cohere', deadline=200)
        assert pacer._last_cohere >= 106.1
    asyncio.run(run())


def test_invalid_clock_after_wait_preserves_admission():
    async def run():
        pacer, clock = fixture()
        await pacer.wait('cohere', deadline=200)
        async def sleep(delay):
            clock.now = float('nan')
        pacer._sleep = sleep
        with pytest.raises(ProviderAdapterError, match='^provider_pacing_invalid$'):
            await pacer.wait('cohere', deadline=200)
        assert pacer._last_cohere == 100 and not pacer._busy
    asyncio.run(run())


def test_preexisting_suppressed_cancellation_refuses_immediate_admission():
    async def run():
        pacer, _ = fixture()
        async def cancelled_caller():
            task = asyncio.current_task()
            task.cancel()
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                pass
            await pacer.wait('openai', deadline=200)
        task = asyncio.create_task(cancelled_caller())
        with pytest.raises(asyncio.CancelledError):
            await task
        assert pacer._last_cohere is None and not pacer._busy
    asyncio.run(run())


def test_terminal_time_anchors_next_admission_without_sleeping_at_finish():
    async def run():
        pacer, clock = fixture()
        await pacer.wait('cohere', deadline=200)
        clock.now = 110
        pacer.finish('cohere')
        assert clock.delays == [] and pacer._last_cohere == 100
        await pacer.wait('openai', deadline=200)
        assert clock.delays == []
        await pacer.wait('cohere', deadline=200)
        assert clock.now - 110 >= 6.1 and len(clock.delays) == 1
        clock.now = 130
        pacer.finish('openai')
        await pacer.wait('cohere', deadline=200)
        assert len(clock.delays) == 1
    asyncio.run(run())


@pytest.mark.parametrize('value', [None, True, 'private', float('nan'), float('inf'), 10**1000, 99])
def test_bad_terminal_clock_invalidates_future_admissions(value):
    async def run():
        pacer, clock = fixture()
        await pacer.wait('cohere', deadline=200)
        clock.now = value
        with pytest.raises(ProviderAdapterError, match='^provider_pacing_invalid$') as caught:
            pacer.finish('cohere')
        assert caught.value.__context__ is None
        clock.now = 150
        for provider in ('openai', 'cohere'):
            with pytest.raises(ProviderAdapterError, match='^provider_pacing_invalid$'):
                await pacer.wait(provider, deadline=200)
        assert pacer._last_cohere == 100 and pacer._last_terminal_cohere is None
        assert clock.delays == [] and not pacer._busy
    asyncio.run(run())


def test_terminal_clock_callback_failure_has_no_private_context():
    pacer, clock = fixture()
    def broken():
        raise RuntimeError('private clock marker')
    pacer._clock = broken
    with pytest.raises(ProviderAdapterError, match='^provider_pacing_invalid$') as caught:
        pacer.finish('cohere')
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    pacer._clock = clock.read
    with pytest.raises(ProviderAdapterError, match='^provider_pacing_invalid$'):
        pacer.finish('openai')


def test_terminal_finish_refuses_during_wait_without_invalidating():
    async def run():
        pacer, clock = fixture()
        await pacer.wait('cohere', deadline=200)
        entered, release = asyncio.Event(), asyncio.Event()
        async def sleep(delay):
            entered.set()
            await release.wait()
            clock.now += delay
        pacer._sleep = sleep
        task = asyncio.create_task(pacer.wait('cohere', deadline=200))
        await entered.wait()
        with pytest.raises(ProviderAdapterError, match='^concurrent_dispatch$'):
            pacer.finish('cohere')
        assert not pacer._invalidated and pacer._last_terminal_cohere is None
        release.set()
        await task
        pacer.finish('cohere')
        assert pacer._last_terminal_cohere == clock.now
    asyncio.run(run())


@pytest.mark.parametrize('provider', [None, True, [], 'private-provider'])
def test_terminal_finish_rejects_invalid_provider(provider):
    pacer, clock = fixture()
    with pytest.raises(ProviderAdapterError, match='^provider_pacing_invalid$'):
        pacer.finish(provider)
    assert clock.delays == [] and pacer._last_terminal_cohere is None


def test_insufficient_terminal_gap_deadline_preserves_both_anchors():
    async def run():
        pacer, clock = fixture()
        await pacer.wait('cohere', deadline=200)
        clock.now = 110
        pacer.finish('cohere')
        with pytest.raises(ProviderAdapterError, match='^deadline_exceeded$'):
            await pacer.wait('cohere', deadline=115)
        assert clock.delays == []
        assert pacer._last_cohere == 100 and pacer._last_terminal_cohere == 110
    asyncio.run(run())


def test_finish_records_terminal_time_even_while_cancellation_is_latched():
    async def run():
        pacer, clock = fixture()
        async def operation():
            await pacer.wait('cohere', deadline=200)
            asyncio.current_task().cancel()
            try:
                await asyncio.sleep(0)
            except asyncio.CancelledError:
                clock.now = 110
                pacer.finish('cohere')
                raise
        task = asyncio.create_task(operation())
        with pytest.raises(asyncio.CancelledError):
            await task
        assert pacer._last_terminal_cohere == 110
        await pacer.wait('cohere', deadline=200)
        assert clock.now - 110 >= 6.1
    asyncio.run(run())
