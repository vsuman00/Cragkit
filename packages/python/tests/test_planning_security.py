"""CSR-r1 provider failures cannot retain private diagnostics in public errors."""

import asyncio
import json

import pytest

from cragkit.errors import DeadlineExceeded, ProviderUnavailable
from cragkit.execution import ExecutionLedger
from cragkit.planning import PlannerAdapter


CANARY = 'CSR-r1-private-planner-credential-canary'
CONFIG = dict(query='Explain ERR-42',
    variants=[dict(facet_id='cause', variant_id='variant', query='ERR-42 cause')],
    missing_facets=['cause'], max_subqueries=2)


@pytest.mark.parametrize('error_type', [ProviderUnavailable, DeadlineExceeded])
@pytest.mark.parametrize('subclass', [False, True])
def test_declared_planner_errors_keep_only_canonical_type_code_and_message(error_type, subclass):
    constructor_calls = []

    class PrivateFailure(error_type):
        def __init__(self):
            constructor_calls.append('called')
            super().__init__()

    failure = PrivateFailure() if subclass else error_type()
    initial_calls = list(constructor_calls)
    failure.args = (CANARY,)
    failure.message = failure.code = CANARY
    failure.credential = CANARY
    failure.__cause__ = RuntimeError(CANARY)

    async def transport(payload, *, deadline):
        raise failure

    async def scenario():
        deadline = asyncio.get_running_loop().time() + 1
        ledger = ExecutionLedger({}, deadline=deadline)
        with pytest.raises(error_type) as caught:
            await PlannerAdapter(transport).plan(**CONFIG, ledger=ledger, deadline=deadline)
        assert caught.value is not failure
        assert type(caught.value) is error_type
        assert caught.value.to_dict() == error_type().to_dict()
        assert str(caught.value) == error_type.message
        assert CANARY not in json.dumps(caught.value.to_dict())
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert not hasattr(caught.value, 'credential')
        assert constructor_calls == initial_calls
        assert ledger.snapshot()['provider_calls'] == 1
        assert ledger.snapshot()['cost_usd'] is None
        assert ledger.snapshot()['pending'] == 0
    asyncio.run(scenario())


@pytest.mark.parametrize('failure_type', [RuntimeError, TimeoutError])
def test_unknown_planner_error_does_not_retain_private_context(failure_type):
    failure = failure_type(CANARY)

    async def transport(payload, *, deadline):
        raise failure

    async def scenario():
        deadline = asyncio.get_running_loop().time() + 1
        with pytest.raises(ProviderUnavailable) as caught:
            await PlannerAdapter(transport).plan(**CONFIG,
                ledger=ExecutionLedger({}, deadline=deadline), deadline=deadline)
        assert type(caught.value) is ProviderUnavailable
        assert caught.value.to_dict() == ProviderUnavailable().to_dict()
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
    asyncio.run(scenario())


def test_declared_provider_failure_keeps_explicit_planner_fallback_and_unknown_usage():
    async def transport(payload, *, deadline):
        failure = ProviderUnavailable()
        failure.args = (CANARY,)
        raise failure

    async def scenario():
        deadline = asyncio.get_running_loop().time() + 1
        ledger = ExecutionLedger({}, deadline=deadline)
        result = await PlannerAdapter(transport, allow_fallback=True).plan(
            **CONFIG, ledger=ledger, deadline=deadline)
        assert result == {'queries': [], 'fallback': True}
        assert ledger.snapshot()['provider_calls'] == 1
        assert ledger.snapshot()['cost_usd'] is None
        assert ledger.snapshot()['pending'] == 0
    asyncio.run(scenario())
