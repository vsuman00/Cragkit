import asyncio

import pytest

from cragkit.errors import DeadlineExceeded, IntegrityViolation, InvalidRequest, UnsupportedCapability
from cragkit.execution import BudgetExhausted, ExecutionLedger


def ledger(**limits):
    return ExecutionLedger(limits, deadline=asyncio.get_running_loop().time() + 10)


def test_final_slot_race_and_nested_sdk_retry():
    async def scenario():
        shared = ledger(max_provider_calls=1)
        async def attempt():
            await asyncio.sleep(0)
            try:
                token = shared.reserve(provider_calls=1)
                shared.dispatch(token)
                await asyncio.sleep(0)
                shared.reconcile(token, input_tokens=2, output_tokens=3, cost_usd=0)
                return True
            except BudgetExhausted:
                return False
        assert sum(await asyncio.gather(attempt(), attempt())) == 1
        assert shared.snapshot()['provider_calls'] == 1
        # A transport retry needs its own slot even inside one logical operation.
        with pytest.raises(BudgetExhausted):
            shared.reserve(provider_calls=1)
    asyncio.run(scenario())


def test_cancel_before_and_after_dispatch():
    async def scenario():
        shared = ledger(max_provider_calls=1)
        token = shared.reserve(provider_calls=1)
        shared.abandon(token)
        assert shared.snapshot()['cost_usd'] == 0
        ready = asyncio.Event()
        async def provider():
            token = shared.reserve(provider_calls=1)
            shared.dispatch(token)
            ready.set()
            try:
                await asyncio.Future()
            finally:
                shared.abandon(token)
        task = asyncio.create_task(provider())
        await ready.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert shared.snapshot() == dict(provider_calls=1, candidates=0, attempts=0,
                                        input_tokens=None, output_tokens=None, cost_usd=None,
                                        cost_kind='unknown', pending=0)
        with pytest.raises(BudgetExhausted):
            shared.reserve(provider_calls=1)
    asyncio.run(scenario())


def test_strict_holds_reconciliation_and_overrun():
    async def scenario():
        shared = ledger(max_spend_usd=1)
        with pytest.raises(UnsupportedCapability):
            shared.reserve(provider_calls=1)
        token = shared.reserve(provider_calls=1, cost_upper_usd=0.75)
        with pytest.raises(BudgetExhausted):
            shared.reserve(provider_calls=1, cost_upper_usd=0.5)
        shared.dispatch(token)
        shared.reconcile(token, input_tokens=0, output_tokens=0, cost_usd=0.25)
        token = shared.reserve(provider_calls=1, cost_upper_usd=0.75)
        shared.dispatch(token)
        with pytest.raises(IntegrityViolation):
            shared.reconcile(token, cost_usd=0.8)
        assert shared.snapshot()['cost_usd'] == 1.05
        with pytest.raises(IntegrityViolation):
            shared.reserve(candidates=1)
    asyncio.run(scenario())


def test_ownership_exactly_once_and_validation():
    async def scenario():
        shared, other = ledger(), ledger()
        token = shared.reserve(candidates=1)
        with pytest.raises(InvalidRequest):
            other.dispatch(token)
        with pytest.raises(InvalidRequest):
            shared.reconcile(token)
        shared.dispatch(token)
        with pytest.raises(InvalidRequest):
            shared.reconcile(token, input_tokens=1)
        shared.reconcile(token)
        for method in (shared.dispatch, shared.reconcile, shared.abandon):
            with pytest.raises(InvalidRequest):
                method(token)
        for bad in (True, -1, 1.5, 9007199254740992):
            with pytest.raises(InvalidRequest):
                shared.reserve(candidates=bad)
        with pytest.raises(InvalidRequest):
            shared.reserve()
        snapshot = shared.snapshot()
        snapshot['candidates'] = 999
        assert shared.snapshot()['candidates'] == 1
    asyncio.run(scenario())


def test_deadline_cleanup_and_unknown_cost_hold():
    async def scenario():
        shared = ledger(max_spend_usd=1)
        token = shared.reserve(provider_calls=1, cost_upper_usd=1)
        shared.dispatch(token)
        shared.reconcile(token)
        with pytest.raises(BudgetExhausted):
            shared.reserve(provider_calls=1, cost_upper_usd=0.1)
        expired = ExecutionLedger({}, deadline=-1)
        with pytest.raises(DeadlineExceeded):
            expired.reserve(candidates=1)
        short = ledger(deadline_ms=1)
        token = short.reserve(provider_calls=1)
        await asyncio.sleep(0.01)
        with pytest.raises(DeadlineExceeded):
            short.dispatch(token)
        short.abandon(token)
        assert short.snapshot()['provider_calls'] == 0
    asyncio.run(scenario())


def test_known_overflow_with_unknown_usage_and_refund_loop():
    async def scenario():
        shared = ledger()
        for _ in range(100):
            shared.abandon(shared.reserve(provider_calls=1))
        assert shared.snapshot()['pending'] == 0
        unknown = shared.reserve(provider_calls=1)
        shared.dispatch(unknown)
        shared.reconcile(unknown)
        token = shared.reserve(provider_calls=1)
        shared.dispatch(token)
        shared.reconcile(token, input_tokens=9007199254740991)
        token = shared.reserve(provider_calls=1)
        shared.dispatch(token)
        with pytest.raises(IntegrityViolation):
            shared.reconcile(token, input_tokens=1)
        assert shared.snapshot()['input_tokens'] is None
        with pytest.raises(IntegrityViolation):
            shared.reserve(attempts=1)
    asyncio.run(scenario())


def test_close_revokes_future_dispatch_but_preserves_accounting_cleanup():
    async def scenario():
        shared = ledger()
        active = shared.reserve(provider_calls=1)
        shared.dispatch(active)
        waiting = shared.reserve(candidates=1)
        shared.close(); shared.close()
        with pytest.raises(InvalidRequest):
            shared.reserve(attempts=1)
        with pytest.raises(InvalidRequest):
            shared.dispatch(waiting)
        shared.abandon(waiting)
        shared.reconcile(active, input_tokens=1, output_tokens=0, cost_usd=0)
        assert shared.snapshot()['pending'] == 0
    asyncio.run(scenario())
