"""Bounded structured events with explicit, off-path asynchronous export."""
from __future__ import annotations

import asyncio
import copy
import math
import re
from collections import deque
from typing import Any, Protocol
from uuid import uuid4

from .contracts._validation import MAX_SAFE_NUMBER, integer
from .errors import InvalidRequest

_STAGES = {'start', 'search', 'capture', 'planning', 'retry', 'stop', 'error', 'cancelled'}
_STOPS = {'sufficient', 'repeated_query', 'repeated_candidates', 'no_progress', 'no_plan',
          'coverage_unknown', 'attempts_exhausted', 'subqueries_exhausted', 'plan_complete', 'budget_exhausted'}
_ERRORS = {'invalid_request', 'unauthorized_scope', 'unsupported_capability', 'index_not_ready',
           'embedding_profile_mismatch', 'provider_unavailable', 'deadline_exceeded',
           'context_budget_too_small', 'integrity_violation'}
_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def new_trace() -> str:
    return str(uuid4())


class EventExporter(Protocol):
    async def __call__(self, event: dict[str, Any], *, deadline: float) -> None: ...


def _count(value: object, maximum: int) -> int:
    parsed = integer(value)
    if type(parsed) is not int or not 0 <= parsed <= maximum:
        raise InvalidRequest()
    return parsed


class EventSink:
    def __init__(self, exporter: EventExporter | None = None, *, capacity: int = 32,
                 timeout_ms: int = 25) -> None:
        capacity, timeout_ms = _count(capacity, 128), _count(timeout_ms, 100)
        if not capacity or not timeout_ms or (exporter is not None and not callable(exporter)):
            raise InvalidRequest()
        self._exporter, self._capacity, self._timeout = exporter, capacity, timeout_ms / 1000
        self._queue: deque[dict[str, Any]] = deque()
        self._ordinal = self._dropped = self._exported = 0
        self._closed = self._flushing = False
        self._pending: asyncio.Task[None] | None = None

    def emit(self, stage: str, *, trace_id: str, attempt: int, elapsed_ms: float,
             candidate_count: int = 0, provider_calls: int = 0,
             stop_reason: str | None = None) -> bool:
        if self._closed:
            raise InvalidRequest()
        if (type(stage) is not str or stage not in _STAGES or type(trace_id) is not str
                or not _UUID.fullmatch(trace_id)):
            raise InvalidRequest()
        attempt = _count(attempt, 10)
        candidate_count, provider_calls = _count(candidate_count, MAX_SAFE_NUMBER), _count(provider_calls, MAX_SAFE_NUMBER)
        if (type(elapsed_ms) not in (int, float) or not math.isfinite(elapsed_ms)
                or not 0 <= elapsed_ms <= 300000):
            raise InvalidRequest()
        allowed = _STOPS if stage == 'stop' else _ERRORS if stage == 'error' else {'cancelled'} if stage == 'cancelled' else {None}
        if type(stop_reason) not in (str, type(None)) or stop_reason not in allowed:
            raise InvalidRequest()
        if self._ordinal >= MAX_SAFE_NUMBER:
            raise InvalidRequest()
        self._ordinal += 1
        if len(self._queue) >= self._capacity:
            self._dropped += 1
            return False
        self._queue.append(dict(event_id=f'{trace_id}:{self._ordinal}', stage=stage, trace_id=trace_id,
            attempt=attempt, elapsed_ms=elapsed_ms, candidate_count=candidate_count,
            provider_calls=provider_calls, stop_reason=stop_reason))
        return True

    def snapshot(self) -> dict[str, int]:
        return dict(queued=len(self._queue), dropped=self._dropped, exported=self._exported)

    def _drop_queue(self) -> None:
        self._dropped += len(self._queue)
        self._queue.clear()

    def drain(self) -> list[dict[str, Any]]:
        events = list(self._queue)
        self._drop_queue()
        return copy.deepcopy(events)

    def _settled(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled():
            task.exception()
        if self._pending is task:
            self._pending = None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._drop_queue()
        if self._pending is not None and not self._pending.done():
            self._pending.cancel()

    async def flush(self, deadline: float) -> dict[str, int]:
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or abs(deadline) > MAX_SAFE_NUMBER):
            raise InvalidRequest()
        if self._flushing:
            return self.snapshot()
        if self._pending is not None and not self._pending.done():
            self._drop_queue()
            return self.snapshot()
        if self._closed or self._exporter is None:
            self._drop_queue()
            return self.snapshot()
        self._flushing = True
        try:
            remaining = len(self._queue)
            loop = asyncio.get_running_loop()
            for _ in range(remaining):
                if loop.time() >= deadline or self._closed:
                    self._drop_queue()
                    break
                if not self._queue:
                    break
                event = self._queue.popleft()
                limit = min(deadline, loop.time() + self._timeout)
                async def invoke(item: dict[str, Any] = event, until: float = limit) -> None:
                    assert self._exporter is not None
                    if self._closed or loop.time() >= until:
                        return
                    await self._exporter(copy.deepcopy(item), deadline=until)
                task = asyncio.create_task(invoke())
                self._pending = task
                task.add_done_callback(self._settled)
                try:
                    done, _ = await asyncio.wait({task}, timeout=max(0, limit - loop.time()))
                    if not done or loop.time() >= limit:
                        self._dropped += 1
                        self._drop_queue()
                        task.cancel()
                        break
                    if self._closed or task.cancelled():
                        self._dropped += 1
                        if self._closed:
                            self._drop_queue()
                            break
                        continue
                    try:
                        task.result()
                    except Exception:
                        self._dropped += 1
                    else:
                        self._exported += 1
                except asyncio.CancelledError:
                    self._dropped += 1
                    self._drop_queue()
                    task.cancel()
                    raise
            return self.snapshot()
        finally:
            self._flushing = False
