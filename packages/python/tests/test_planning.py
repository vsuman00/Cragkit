import asyncio

import pytest

from cragkit.errors import DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability
from cragkit.execution import ExecutionLedger
from cragkit.planning import PlannerAdapter, validate_plan


CONFIG = dict(query='Explain ERR-42', variants=[dict(facet_id='cause', variant_id='v1', query='ERR-42 cause')],
              missing_facets=['cause'], max_subqueries=2)
PLAN = {'queries': [{'facet_id': 'cause', 'variant_id': 'v1'}]}


def response(plan=PLAN, cost=0):
    return dict(plan=plan, usage=dict(input_tokens=2, output_tokens=3, cost_usd=cost))


def test_select_only_approved_identifier_preserving_variants():
    assert validate_plan(PLAN, **CONFIG) == CONFIG['variants']
    for value in ('{}', {'queries': [{'facet_id': 'cause', 'variant_id': 'invented'}]},
                  {'queries': [], 'scope': 'forged'}, {'queries': PLAN['queries'] * 2}):
        with pytest.raises(InvalidRequest):
            validate_plan(value, **CONFIG)
    bad = dict(CONFIG, variants=[dict(facet_id='cause', variant_id='v1', query='cause')])
    with pytest.raises(InvalidRequest):
        validate_plan({'queries': []}, **bad)


def test_snapshot_input_and_account_success():
    async def scenario():
        async def transport(payload, *, deadline):
            payload['variants'][0]['query'] = 'mutated'
            return response()
        deadline = asyncio.get_running_loop().time() + 1
        ledger = ExecutionLedger({}, deadline=deadline)
        result = await PlannerAdapter(transport).plan(**CONFIG, ledger=ledger, deadline=deadline)
        assert result == {'queries': CONFIG['variants'], 'fallback': False}
        assert ledger.snapshot()['input_tokens'] == 2
        assert ledger.snapshot()['provider_calls'] == 1
    asyncio.run(scenario())


def test_malformed_fallback_but_accounting_overrun_propagates():
    async def scenario():
        deadline = asyncio.get_running_loop().time() + 1
        async def malformed(payload, *, deadline):
            return response({'queries': [], 'scope': 'forged'})
        ledger = ExecutionLedger({}, deadline=deadline)
        assert await PlannerAdapter(malformed, allow_fallback=True).plan(**CONFIG, ledger=ledger, deadline=deadline) == {'queries': [], 'fallback': True}
        assert ledger.snapshot()['input_tokens'] == 2
        async def overrun(payload, *, deadline):
            return response(cost=2)
        with pytest.raises(IntegrityViolation):
            await PlannerAdapter(overrun, cost_upper_usd=1, allow_fallback=True).plan(**CONFIG, ledger=ExecutionLedger({}, deadline=deadline), deadline=deadline)
        with pytest.raises(UnsupportedCapability):
            await PlannerAdapter(overrun, allow_fallback=True).plan(**CONFIG, ledger=ExecutionLedger({'max_spend_usd': 1}, deadline=deadline), deadline=deadline)
    asyncio.run(scenario())


def test_malformed_usage_oversize_and_redacted_failure():
    async def scenario():
        deadline = asyncio.get_running_loop().time() + 1
        for output in ({'plan': PLAN, 'usage': {}}, response({'queries': [], 'large': 'x' * 16384})):
            async def transport(payload, *, deadline):
                return output
            ledger = ExecutionLedger({}, deadline=deadline)
            with pytest.raises(IntegrityViolation):
                await PlannerAdapter(transport).plan(**CONFIG, ledger=ledger, deadline=deadline)
            assert ledger.snapshot()['cost_usd'] is None
        async def unavailable(payload, *, deadline):
            raise RuntimeError('private transport detail')
        with pytest.raises(ProviderUnavailable) as error:
            await PlannerAdapter(unavailable).plan(**CONFIG, ledger=ExecutionLedger({}, deadline=deadline), deadline=deadline)
        assert 'private' not in str(error.value)
    asyncio.run(scenario())


def test_timeout_and_native_cancellation_keep_unknown_usage():
    async def scenario():
        started = asyncio.Event()
        release = asyncio.Event()
        async def ignores_deadline(payload, *, deadline):
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return response()
        deadline = asyncio.get_running_loop().time() + 0.01
        ledger = ExecutionLedger({'deadline_ms': 1}, deadline=deadline + 1)
        with pytest.raises(DeadlineExceeded):
            await PlannerAdapter(ignores_deadline, allow_fallback=True).plan(**CONFIG, ledger=ledger, deadline=deadline)
        assert ledger.snapshot()['provider_calls'] == 1
        assert ledger.snapshot()['cost_usd'] is None
        deadline = asyncio.get_running_loop().time() + 1
        ledger = ExecutionLedger({}, deadline=deadline)
        started.clear()
        task = asyncio.create_task(PlannerAdapter(ignores_deadline).plan(**CONFIG, ledger=ledger, deadline=deadline))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert ledger.snapshot()['pending'] == 0
        release.set()
        await asyncio.sleep(0)
    asyncio.run(scenario())


def test_empty_config_validated_without_call_and_retries_rejected():
    async def scenario():
        async def transport(payload, *, deadline):
            raise AssertionError('must not dispatch')
        deadline = asyncio.get_running_loop().time() + 1
        ledger = ExecutionLedger({}, deadline=deadline)
        assert await PlannerAdapter(transport).plan(**dict(CONFIG, max_subqueries=1), ledger=ledger, deadline=deadline) == {'queries': [], 'fallback': False}
        assert ledger.snapshot()['provider_calls'] == 0
        with pytest.raises(InvalidRequest):
            PlannerAdapter(transport, sdk_retries=1)
    asyncio.run(scenario())
