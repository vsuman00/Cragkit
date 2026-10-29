"""Optional local stdio MCP host over caller-owned native retrieval."""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import sys
from types import TracebackType
from typing import Any, Callable, cast

import anyio
from mcp import types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage
from mcp.shared.exceptions import MCPError

from cragkit.context import Cl100kCounter, _ISSUED, count_context
from cragkit.contracts import RetrievalResult, ToolRequest, TrustedScope
from cragkit.contracts import parse_request, parse_result, parse_scope, parse_tool_request
from cragkit.contracts._validation import native_json
from cragkit.errors import (CragkitError, ContextBudgetTooSmall, DeadlineExceeded,
    IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability)

__all__ = ['create_server', 'RetrievalHost']
_CODES = frozenset({'invalid_request', 'unauthorized_scope', 'unsupported_capability',
    'index_not_ready', 'embedding_profile_mismatch', 'provider_unavailable',
    'deadline_exceeded', 'context_budget_too_small', 'integrity_violation'})
_MAX_FRAME = 65536
_MAX_OUTPUT = 262144


def _error(code: str) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type='text', text=code)], is_error=True)


class _Stdin:
    async def receive(self, size: int) -> bytes:
        fd = sys.stdin.fileno()
        await anyio.wait_readable(fd)
        return os.read(fd, size)


class _BoundedText:
    """Feed validated UTF-8 lines to the SDK's own stdio parser."""
    def __init__(self, source: Any) -> None:
        self.source = source
        self.pending = bytearray()
        self.first = True

    def __aiter__(self) -> _BoundedText:
        return self

    async def __anext__(self) -> str:
        while True:
            end = self.pending.find(b'\n')
            if end >= 0:
                line = bytes(self.pending[:end + 1])
                del self.pending[:end + 1]
                break
            if len(self.pending) >= _MAX_FRAME:
                raise InvalidRequest()
            try:
                chunk = await self.source.receive(min(4096, _MAX_FRAME - len(self.pending)))
            except anyio.EndOfStream:
                chunk = b''
            if not chunk:
                if not self.pending:
                    raise StopAsyncIteration
                # An unterminated frame is not a complete stdio message.
                raise InvalidRequest()
            if type(chunk) is not bytes or len(chunk) > _MAX_FRAME - len(self.pending):
                raise InvalidRequest()
            self.pending.extend(chunk)
        try:
            text = line.decode('utf-8', errors='strict')
            parsed = types.jsonrpc_message_adapter.validate_json(text, by_name=False)
            if self.first:
                # Do not let the SDK's pre-handshake debug path log arbitrary frames.
                if not isinstance(parsed, types.JSONRPCRequest):
                    raise ValueError()
                self.first = False
            return text
        except Exception:
            raise InvalidRequest() from None


class _SafeWrite:
    def __init__(self, stream: Any) -> None:
        self.stream = stream

    async def send(self, item: SessionMessage, /) -> None:
        if isinstance(item.message, types.JSONRPCError):
            original = item.message
            item = SessionMessage(types.JSONRPCError(jsonrpc='2.0', id=original.id,
                error=types.ErrorData(code=original.error.code, message='invalid_request')))
        await self.stream.send(item)

    async def aclose(self) -> None:
        await self.stream.aclose()

    async def __aenter__(self) -> _SafeWrite:
        await self.stream.__aenter__()
        return self

    async def __aexit__(self, kind: type[BaseException] | None, value: BaseException | None,
                        traceback: TracebackType | None) -> None:
        await self.stream.__aexit__(kind, value, traceback)


class RetrievalHost:
    def __init__(self, engine: Any, template: Any, scope: Any,
                 serializer: Callable[[types.CallToolResult], str], counter: Cl100kCounter | None) -> None:
        self._engine, self._template, self._scope = engine, template, scope
        self._serializer, self._counter = serializer, counter
        self._active: asyncio.Task[object] | None = None
        self._close_waiter: asyncio.Future[None] | None = None
        self._closed = False
        self._serving = False
        self._runner: asyncio.Task[Any] | None = None
        self.server: Server[Any] = Server('cragkit', version='0.0.0',
            on_list_tools=self._list_tools, on_call_tool=self._call_tool)
        # The pinned SDK enables ambient OpenTelemetry middleware by default.
        self.server.middleware.clear()

    async def _list_tools(self, context: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name='cragkit_retrieve',
            description='Retrieve scoped source-linked evidence with coverage and limitations.',
            input_schema=ToolRequest.model_json_schema(),
            annotations=types.ToolAnnotations(read_only_hint=True, destructive_hint=False,
                idempotent_hint=True, open_world_hint=False))])

    async def _call_tool(self, context: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        try:
            if params.name != 'cragkit_retrieve':
                raise InvalidRequest()
            return await self.retrieve(params.arguments)
        except asyncio.CancelledError:
            raise
        except CragkitError as exc:
            code = exc.code if exc.code in _CODES else 'provider_unavailable'
        except Exception:
            code = 'provider_unavailable'
        actual = _error(code)
        try:
            self._check_output(actual)
        except Exception:
            raise MCPError(code=-32603, message='invalid_request') from None
        return actual

    def _check_output(self, actual: types.CallToolResult) -> None:
        try:
            serialized = self._serializer(actual)
            if type(serialized) is not str:
                raise ValueError()
            size = len(serialized.encode('utf-8', errors='strict'))
        except CragkitError:
            raise
        except Exception:
            raise InvalidRequest() from None
        if size > _MAX_OUTPUT:
            raise ContextBudgetTooSmall()
        profile = self._template.output_profile
        tokens = (Cl100kCounter.count(self._counter, serialized) if profile.counting_mode == 'strict'
                  and self._counter is not None else (size + 3) // 4)
        if tokens + profile.envelope_reserve_tokens > self._template.limits.max_context_tokens:
            raise ContextBudgetTooSmall()

    def _drained(self, task: asyncio.Task[object]) -> None:
        if not task.cancelled():
            task.exception()
        if self._active is task:
            self._active = None

    async def retrieve(self, value: object) -> types.CallToolResult:
        if self._closed or self._active is not None:
            raise ProviderUnavailable()
        try:
            args = parse_tool_request(value)
            if args.collection != self._template.collection:
                raise InvalidRequest()
            request = parse_request({**self._template.model_dump(mode='json'), **args.model_dump(mode='json')})
            scope = parse_scope(self._scope.model_dump(mode='json'))
        except Exception:
            raise InvalidRequest() from None
        loop = asyncio.get_running_loop()
        deadline = loop.time() + request.limits.deadline_ms / 1000

        async def invoke() -> object:
            if self._closed or loop.time() >= deadline:
                raise DeadlineExceeded()
            value: object = await self._engine.retrieve(request, scope=scope, deadline=deadline)
            return value

        task = asyncio.create_task(invoke())
        self._active = task
        stopped: asyncio.Future[None] = loop.create_future()
        self._close_waiter = stopped
        task.add_done_callback(self._drained)
        # wait only observes these futures; the close signal is completed with
        # None through its original Future[None] reference, never this view.
        watched: set[asyncio.Future[object]] = {task, cast(asyncio.Future[object], stopped)}
        try:
            done, _ = await asyncio.wait(watched, timeout=max(0, deadline - loop.time()),
                                        return_when=asyncio.FIRST_COMPLETED)
            if self._closed:
                raise asyncio.CancelledError()
            if not done or loop.time() >= deadline:
                raise DeadlineExceeded()
            try:
                raw = task.result()
            except CragkitError:
                raise
            except Exception:
                raise ProviderUnavailable() from None
            try:
                result: object = raw
                if type(raw) is dict and 'result' in raw:
                    result = raw['result']
                if type(result) is RetrievalResult:
                    result = result.model_dump(mode='json', warnings=False)
                validated = parse_result(result)
                if validated.request_id != request.request_id:
                    raise ValueError()
                content = json.dumps(validated.model_dump(mode='json'), ensure_ascii=False,
                    separators=(',', ':'), allow_nan=False)
                if len(content.encode('utf-8')) > _MAX_OUTPUT:
                    raise ContextBudgetTooSmall()
            except ContextBudgetTooSmall:
                raise
            except Exception:
                raise IntegrityViolation() from None
            actual = types.CallToolResult(content=[types.TextContent(type='text', text=content)], is_error=False)
            self._check_output(actual)
            if self._closed:
                raise asyncio.CancelledError()
            if loop.time() >= deadline:
                raise DeadlineExceeded()
            return actual
        finally:
            stopped.cancel()
            if self._close_waiter is stopped:
                self._close_waiter = None
            if not task.done():
                task.cancel()
            # Ownership is released by actual task completion, never by timeout.

    async def run_streams(self, read_stream: Any, write_stream: Any) -> None:
        if self._closed or self._serving:
            raise ProviderUnavailable()
        self._serving = True
        self._runner = asyncio.current_task()
        try:
            await self.server.run(read_stream, _SafeWrite(write_stream), self.server.create_initialization_options())
        finally:
            self._runner = None
            await self.close()

    async def run_stdio(self, *, stdin: Any = None, stdout: Any = None) -> None:
        try:
            # Pinned mcp 2.3.0 consumes only async iteration from this argument;
            # its AsyncFile annotation is narrower than that injected surface.
            bounded = cast(Any, _BoundedText(stdin or _Stdin()))
            async with stdio_server(stdin=bounded, stdout=stdout) as streams:
                await self.run_streams(*streams)
        finally:
            await self.close()

    async def close(self) -> None:
        self._closed = True
        if self._close_waiter is not None and not self._close_waiter.done():
            self._close_waiter.set_result(None)
        if self._active is not None:
            self._active.cancel()
        if self._runner is not None and self._runner is not asyncio.current_task():
            self._runner.cancel()


def create_server(engine: Any, *, template: object, scope: object,
                  final_serializer: Callable[[types.CallToolResult], str],
                  counter: Cl100kCounter | None = None) -> RetrievalHost:
    try:
        if (not callable(getattr(engine, 'retrieve', None)) or not callable(final_serializer)
                or inspect.iscoroutinefunction(final_serializer) or type(template) is not dict
                or not {'collection'} <= set(template) <= {'collection', 'required_filters', 'limits', 'output_profile'}):
            raise ValueError()
        native_json(template)
        request = parse_request(dict(template, query='validation', request_id='template-validation'))
        if type(scope) is TrustedScope:
            scope = scope.model_dump(mode='json', warnings=False)
        trusted = parse_scope(scope)
    except Exception:
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
    return RetrievalHost(engine, request, trusted, final_serializer, counter)
