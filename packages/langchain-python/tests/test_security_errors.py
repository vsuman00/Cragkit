"""CSR-r1 failures visible through the real LangChain tool API stay redacted."""

import asyncio

import pytest

from cragkit.errors import (CragkitError, ContextBudgetTooSmall, DeadlineExceeded, EmbeddingProfileMismatch,
    IndexNotReady, IntegrityViolation, InvalidRequest, ProviderUnavailable,
    UnauthorizedScope, UnsupportedCapability)
from cragkit_langchain import create_tool

import test_adapter as support


CANARY = 'CSR-r1-private-langchain-credential-canary'
ERROR_TYPES = [InvalidRequest, UnauthorizedScope, UnsupportedCapability, IndexNotReady,
    EmbeddingProfileMismatch, ProviderUnavailable, DeadlineExceeded,
    ContextBudgetTooSmall, IntegrityViolation]


class UnknownCragkitError(CragkitError):
    code = 'unknown_callback_error'
    message = CANARY


@pytest.mark.parametrize('error_type', ERROR_TYPES)
@pytest.mark.parametrize('subclass', [False, True])
@pytest.mark.parametrize('boundary', ['engine', 'serializer'])
def test_declared_failure_is_fresh_canonical_error_without_private_properties(error_type, subclass, boundary):
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

    class Failing:
        async def retrieve(self, *args, **kwargs):
            raise failure

    def bad_serializer(actual):
        raise failure

    async def scenario():
        target = create_tool(Failing() if boundary == 'engine' else support.Engine(),
            template=support.TEMPLATE, scope=support.SCOPE,
            final_serializer=bad_serializer if boundary == 'serializer' else support.serializer)
        with pytest.raises(error_type) as caught:
            await target.ainvoke(support.native())
        assert caught.value is not failure
        assert type(caught.value) is error_type
        assert caught.value.to_dict() == error_type().to_dict()
        assert str(caught.value) == error_type.message
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert not hasattr(caught.value, 'credential')
        assert constructor_calls == initial_calls
    asyncio.run(scenario())


@pytest.mark.parametrize('boundary,expected', [('engine', ProviderUnavailable), ('serializer', InvalidRequest)])
@pytest.mark.parametrize('error_type', [RuntimeError, UnknownCragkitError])
def test_unknown_failure_has_no_private_exception_context(boundary, expected, error_type):
    failure = error_type(CANARY) if error_type is RuntimeError else error_type()
    failure.args = (CANARY,)
    failure.code = CANARY
    failure.credential = CANARY

    class Failing:
        async def retrieve(self, *args, **kwargs):
            raise failure

    def bad_serializer(actual):
        raise failure

    async def scenario():
        target = create_tool(Failing() if boundary == 'engine' else support.Engine(),
            template=support.TEMPLATE, scope=support.SCOPE,
            final_serializer=bad_serializer if boundary == 'serializer' else support.serializer)
        with pytest.raises(expected) as caught:
            await target.ainvoke(support.native())
        assert type(caught.value) is expected
        assert caught.value.to_dict() == expected().to_dict()
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert not hasattr(caught.value, 'credential')
    asyncio.run(scenario())
