"""Additive dispatch observation admission; synthetic injected calls only."""
import asyncio
import time

import pytest

from cragkit.embeddings import EmbeddingAdapter, EmbeddingPolicy, OPENAI_PROFILE
from cragkit.errors import InvalidRequest, ProviderUnavailable, UnsupportedCapability
from cragkit.execution import BudgetExhausted


class OpenAICounter:
    name = 'cl100k_base'
    def count(self, value):
        return 2


def test_dispatch_runs_after_admission_before_transport_and_keeps_typed_error():
    async def run():
        events = []
        async def transport(*args, **kwargs):
            events.append('transport')
            raise RuntimeError('private')
        adapter = EmbeddingAdapter(transport, OpenAICounter(), profile=OPENAI_PROFILE,
            policy=EmbeddingPolicy(allow_live=True, max_cost_usd=.01, usd_per_million_tokens=.02))
        def dispatch():
            events.append('dispatch')
        with pytest.raises(ProviderUnavailable):
            await adapter.embed_query('tiny', deadline=time.monotonic()+10, on_dispatch=dispatch)
        assert events == ['dispatch','transport']
        events.clear()
        def exhausted():
            raise BudgetExhausted()
        with pytest.raises(BudgetExhausted):
            await adapter.embed_query('tiny', deadline=time.monotonic()+10, on_dispatch=exhausted)
        assert events == []
        adapter.policy = EmbeddingPolicy(allow_live=False)
        with pytest.raises(UnsupportedCapability):
            await adapter.embed_query('tiny', deadline=time.monotonic()+10, on_dispatch=dispatch)
        assert events == []
    asyncio.run(run())


def test_invalid_async_or_nonvoid_hook_never_dispatches():
    async def run():
        calls = []
        async def transport(*args, **kwargs):
            calls.append(True)
            raise AssertionError()
        adapter = EmbeddingAdapter(transport, OpenAICounter(), profile=OPENAI_PROFILE,
            policy=EmbeddingPolicy(allow_live=True, max_cost_usd=.01, usd_per_million_tokens=.02))
        async def asynchronous():
            pass
        for hook in (asynchronous, lambda: asynchronous(), lambda: 1, 12):
            with pytest.raises(InvalidRequest):
                await adapter.embed_query('tiny', deadline=time.monotonic()+10, on_dispatch=hook)
        assert calls == []
    asyncio.run(run())


def test_invalid_pending_hook_task_observes_later_cancellation_cleanup_failure():
    async def run():
        calls, observed, loop_errors = [], [], []
        loop = asyncio.get_running_loop()
        previous = loop.get_exception_handler()
        loop.set_exception_handler(lambda loop, context: loop_errors.append(context))
        started = asyncio.Event()
        class TrackingTask(asyncio.Task):
            def exception(self):
                observed.append(True)
                return super().exception()
        async def pending():
            try:
                started.set()
                await asyncio.Event().wait()
            finally:
                raise RuntimeError('injected cancellation cleanup failure')
        async def transport(*args, **kwargs):
            calls.append(True)
            raise AssertionError('transport must not run')
        task = TrackingTask(pending(), loop=loop)
        await started.wait()
        adapter = EmbeddingAdapter(transport, OpenAICounter(), profile=OPENAI_PROFILE,
            policy=EmbeddingPolicy(allow_live=True, max_cost_usd=.01, usd_per_million_tokens=.02))
        try:
            with pytest.raises(InvalidRequest):
                await adapter.embed_query('tiny', deadline=time.monotonic()+10, on_dispatch=lambda: task)
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            assert task.done() and not task.cancelled()
            assert observed and not calls and not loop_errors
        finally:
            loop.set_exception_handler(previous)
    asyncio.run(run())
