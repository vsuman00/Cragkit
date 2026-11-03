"""Explicit asynchronous LangChain tools over caller-bound Cragkit retrieval."""
from __future__ import annotations

import asyncio
import inspect
import json
from typing import Any, AsyncIterator, Callable

from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langsmith.run_helpers import tracing_context
from pydantic import ConfigDict, PrivateAttr

from cragkit.context import Cl100kCounter, _ISSUED, count_context
from cragkit.contracts import RetrievalRequest, RetrievalResult, ToolRequest, TrustedScope
from cragkit.contracts import parse_request, parse_result, parse_scope, parse_tool_request
from cragkit.contracts._validation import identity, native_json
from cragkit.errors import (CragkitError, ContextBudgetTooSmall, DeadlineExceeded,
    EmbeddingProfileMismatch, IndexNotReady, IntegrityViolation, InvalidRequest,
    ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)

__all__ = ['create_tool']
_FACTORY = object()
_ERROR_TYPES: tuple[type[CragkitError], ...] = (InvalidRequest, UnauthorizedScope,
    UnsupportedCapability, IndexNotReady, EmbeddingProfileMismatch, ProviderUnavailable,
    DeadlineExceeded, ContextBudgetTooSmall, IntegrityViolation)


def _reject(*args: Any, **kwargs: Any) -> Any:
    raise UnsupportedCapability()


async def _areject(*args: Any, **kwargs: Any) -> Any:
    raise UnsupportedCapability()


async def _astream_reject(*args: Any, **kwargs: Any) -> AsyncIterator[Any]:
    raise UnsupportedCapability()
    yield  # pragma: no cover


class _RetrievalTool(StructuredTool):
    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True, extra='forbid')
    _engine: Any = PrivateAttr()
    _template: RetrievalRequest = PrivateAttr()
    _scope: TrustedScope = PrivateAttr()
    _serializer: Callable[[str | ToolMessage], str] = PrivateAttr()
    _counter: Cl100kCounter | None = PrivateAttr(default=None)

    def __init__(self, **data: Any) -> None:
        if data.pop('_factory_token', None) is not _FACTORY:
            raise UnsupportedCapability()
        if data.get('func') is not None or data.get('coroutine') is not None:
            raise UnsupportedCapability()
        super().__init__(**data)

    async def ainvoke(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        if kwargs or (config is not None and (type(config) is not dict or config)):
            raise InvalidRequest()
        return await self._execute(input)

    async def arun(self, tool_input: Any, *args: Any, **kwargs: Any) -> Any:
        if args:
            raise InvalidRequest()
        config = kwargs.pop('config', None)
        return await self.ainvoke(tool_input, config=config, **kwargs)

    async def _execute(self, value: object) -> str | ToolMessage:
        try:
            return await self._execute_bound(value)
        except CragkitError as error:
            failure = next((kind for kind in _ERROR_TYPES if isinstance(error, kind)), InvalidRequest)
        except Exception:
            failure = InvalidRequest
        # Leave the handler before raising so no private exception context survives.
        raise failure() from None

    async def _execute_bound(self, value: object) -> str | ToolMessage:
        with tracing_context(enabled=False, parent=False):
            call_id: str | None = None
            try:
                native_json(value)
                if type(value) is dict and value.get('type') == 'tool_call':
                    if set(value) != {'type', 'id', 'name', 'args'} or value['name'] != self.name:
                        raise ValueError()
                    if type(value['id']) is not str:
                        raise ValueError()
                    call_id = identity(value['id'])
                    value = value['args']
                args = parse_tool_request(value)
                if args.collection != self._template.collection:
                    raise ValueError()
                request = parse_request({**self._template.model_dump(mode='json'),
                                         **args.model_dump(mode='json')})
                scope = parse_scope(self._scope.model_dump(mode='json'))
            except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
                raise InvalidRequest() from None
            loop = asyncio.get_running_loop()
            deadline = loop.time() + request.limits.deadline_ms / 1000
            async def invoke_engine() -> object:
                if loop.time() >= deadline:
                    raise DeadlineExceeded()
                return await self._engine.retrieve(request, scope=scope, deadline=deadline)
            task = asyncio.create_task(invoke_engine())
            task.add_done_callback(lambda result: None if result.cancelled() else result.exception())
            try:
                done, _ = await asyncio.wait({task}, timeout=max(0, deadline - loop.time()))
                if not done:
                    raise DeadlineExceeded()
                try:
                    raw = task.result()
                except _ERROR_TYPES:
                    raise
                except Exception:
                    raise ProviderUnavailable() from None
                if loop.time() >= deadline:
                    raise DeadlineExceeded()
            finally:
                if not task.done():
                    task.cancel()
            try:
                if type(raw) is not dict or 'result' not in raw:
                    raise ValueError()
                result = raw['result']
                if type(result) is RetrievalResult:
                    result = result.model_dump(mode='json', warnings=False)
                validated = parse_result(result)
                if validated.request_id != request.request_id:
                    raise ValueError()
                content = json.dumps(validated.model_dump(mode='json'), ensure_ascii=False,
                                     separators=(',', ':'), allow_nan=False)
                if len(content.encode('utf-8')) > 262144:
                    raise ContextBudgetTooSmall()
            except ContextBudgetTooSmall:
                raise
            except (InvalidRequest, ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
                raise IntegrityViolation() from None
            actual: str | ToolMessage = (content if call_id is None else
                ToolMessage(content=content, name=self.name, tool_call_id=call_id))
            try:
                serialized = self._serializer(actual)
            except CragkitError:
                raise
            except Exception:
                raise InvalidRequest() from None
            if type(serialized) is not str:
                raise InvalidRequest()
            try:
                size = len(serialized.encode('utf-8', errors='strict'))
            except UnicodeError:
                raise InvalidRequest() from None
            if size > 262144:
                raise ContextBudgetTooSmall()
            profile = request.output_profile
            if profile.counting_mode == 'strict':
                assert self._counter is not None
                tokens = Cl100kCounter.count(self._counter, serialized)
            else:
                tokens = (size + 3) // 4
            if tokens + profile.envelope_reserve_tokens > request.limits.max_context_tokens:
                raise ContextBudgetTooSmall()
            if loop.time() >= deadline:
                raise DeadlineExceeded()
            return actual

    invoke = _reject
    run = _reject
    __call__ = _reject
    _run = _reject
    _arun = _areject
    _call = _reject
    _acall = _areject
    stream = _reject
    astream = _astream_reject
    transform = _reject
    atransform = _astream_reject
    batch = _reject
    abatch = _areject
    batch_as_completed = _reject
    abatch_as_completed = _astream_reject
    async def astream_log(self, input: Any, config: Any = None, **kwargs: Any) -> AsyncIterator[Any]:
        raise UnsupportedCapability()
        yield  # pragma: no cover
    def astream_events(self, input: Any, config: Any = None, **kwargs: Any) -> Any:
        return _astream_reject(input, config, **kwargs)
    model_copy = _reject
    copy = _reject

    @classmethod
    def model_construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Any:
        raise UnsupportedCapability()

    @classmethod
    def construct(cls, _fields_set: set[str] | None = None, **values: Any) -> Any:
        raise UnsupportedCapability()


def create_tool(engine: Any, *, template: object, scope: object,
                final_serializer: Callable[[str | ToolMessage], str], counter: Cl100kCounter | None = None,
                name: str = 'cragkit_retrieve') -> StructuredTool:
    try:
        if (not callable(getattr(engine, 'retrieve', None)) or not callable(final_serializer)
                or inspect.iscoroutinefunction(final_serializer) or type(template) is not dict
                or not {'collection'} <= set(template) <= {'collection', 'required_filters', 'limits', 'output_profile'}
                or type(name) is not str):
            raise ValueError()
        identity(name)
        native_json(template)
        request = parse_request(dict(template, query='validation', request_id='template-validation'))
        if type(scope) is TrustedScope:
            scope = scope.model_dump(mode='json', warnings=False)
        trusted = parse_scope(scope)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise InvalidRequest() from None
    output = request.output_profile
    if output.counting_mode == 'strict':
        if type(counter) is not Cl100kCounter or counter not in _ISSUED or output.tokenizer != 'cl100k_base':
            raise UnsupportedCapability()
        if Cl100kCounter.count(counter, '[]') + output.envelope_reserve_tokens > request.limits.max_context_tokens:
            raise ContextBudgetTooSmall()
    else:
        count_context([], max_tokens=request.limits.max_context_tokens,
            reserve=output.envelope_reserve_tokens, counter=counter, counting_mode=output.counting_mode)
    tool = _RetrievalTool(_factory_token=_FACTORY, name=name,
                          description='Retrieve scoped source-linked evidence with coverage and limitations.',
                          args_schema=ToolRequest, func=None, coroutine=None)
    tool._engine, tool._template, tool._scope = engine, request, trusted
    tool._serializer, tool._counter = final_serializer, counter
    return tool
