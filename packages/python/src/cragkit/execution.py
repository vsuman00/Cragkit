"""Atomic request-local reservations; transitions never await or dispatch work."""
from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass
from typing import Any

from .contracts import Limits
from .contracts._validation import MAX_SAFE_NUMBER, integer
from .errors import DeadlineExceeded, IntegrityViolation, InvalidRequest, UnsupportedCapability


class BudgetExhausted(Exception):
    """The next reservation would exceed a request limit."""


@dataclass
class _Entry:
    calls: int
    candidates: int
    attempts: int
    bound: float | None
    state: str = 'reserved'
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost: float | None = None


def _count(value: object) -> int:
    value = integer(value)
    if type(value) is not int or not 0 <= value <= MAX_SAFE_NUMBER:
        raise InvalidRequest()
    return value


def _amount(value: object) -> float:
    if type(value) not in (int, float):
        raise InvalidRequest()
    assert isinstance(value, (int, float))
    if not 0 <= value <= MAX_SAFE_NUMBER or not math.isfinite(value):
        raise InvalidRequest()
    return float(value)


class ExecutionLedger:
    def __init__(self, limits: object, *, deadline: float) -> None:
        try:
            if type(limits) is Limits:
                limits = limits.model_dump(warnings=False)
            self._limits = Limits.model_validate(limits)
        except (ValueError, TypeError, OverflowError, RecursionError):
            raise InvalidRequest() from None
        now = asyncio.get_running_loop().time()
        self._deadline = now + self._limits.deadline_ms / 1000
        if (type(deadline) not in (int, float) or not math.isfinite(deadline)
                or abs(deadline) > MAX_SAFE_NUMBER):
            raise InvalidRequest()
        self._deadline = min(self._deadline, deadline)
        self._entries: dict[object, _Entry] = {}
        self._calls = self._candidates = self._attempts = 0
        self._closed = False
        self._poisoned = False
        self._overflow = False
        self._held_cost = 0.0

    @property
    def deadline(self) -> float:
        return self._deadline

    def close(self) -> None:
        self._closed = True

    def _admit(self) -> None:
        if self._closed:
            raise InvalidRequest()
        if self._poisoned:
            raise IntegrityViolation()
        if asyncio.get_running_loop().time() >= self._deadline:
            raise DeadlineExceeded()

    def _entry(self, reservation: object, states: tuple[str, ...]) -> _Entry:
        if type(reservation) is not object:
            raise InvalidRequest()
        try:
            entry = self._entries.get(reservation)
        except TypeError:
            raise InvalidRequest() from None
        if entry is None or entry.state not in states:
            raise InvalidRequest()
        return entry

    def reserve(self, *, provider_calls: int = 0, candidates: int = 0,
                attempts: int = 0, cost_upper_usd: float | None = None) -> object:
        calls, candidates, attempts = _count(provider_calls), _count(candidates), _count(attempts)
        if calls + candidates + attempts == 0:
            raise InvalidRequest()
        bound = None if cost_upper_usd is None else _amount(cost_upper_usd)
        if not calls and bound not in (None, 0):
            raise InvalidRequest()
        self._admit()
        if calls and self._limits.max_spend_usd is not None and bound is None:
            raise UnsupportedCapability()
        if (self._calls + calls > self._limits.max_provider_calls
                or self._candidates + candidates > self._limits.max_candidates
                or self._attempts + attempts > self._limits.max_attempts):
            raise BudgetExhausted()
        ceiling = self._limits.max_spend_usd
        spent = self._held_cost
        if ceiling is not None and (bound or 0) > ceiling - spent:
            raise BudgetExhausted()
        if spent + (bound or 0) > MAX_SAFE_NUMBER:
            self._poisoned = True
            raise IntegrityViolation()
        token = object()
        self._entries[token] = _Entry(calls, candidates, attempts, bound)
        self._held_cost += bound or 0
        self._calls += calls
        self._candidates += candidates
        self._attempts += attempts
        return token

    def dispatch(self, reservation: object) -> None:
        entry = self._entry(reservation, ('reserved',))
        self._admit()
        entry.state = 'dispatched'

    def reconcile(self, reservation: object, *, input_tokens: int | None = None,
                  output_tokens: int | None = None, cost_usd: float | None = None) -> None:
        entry = self._entry(reservation, ('dispatched',))
        inputs = None if input_tokens is None else _count(input_tokens)
        outputs = None if output_tokens is None else _count(output_tokens)
        cost = None if cost_usd is None else _amount(cost_usd)
        if not entry.calls and any(value not in (None, 0) for value in (inputs, outputs, cost)):
            raise InvalidRequest()
        entry.input_tokens, entry.output_tokens, entry.cost = inputs, outputs, cost
        entry.state = 'completed'
        totals = [sum(getattr(item, field) or 0 for item in self._entries.values() if item.calls)
                  for field in ('input_tokens', 'output_tokens', 'cost')]
        if any(total > MAX_SAFE_NUMBER for total in totals):
            self._overflow = True
            self._poisoned = True
            raise IntegrityViolation()
        if entry.calls and cost is not None:
            self._held_cost += cost - (entry.bound or 0)
        if cost is not None and entry.bound is not None and cost > entry.bound:
            self._poisoned = True
            raise IntegrityViolation()

    def abandon(self, reservation: object) -> None:
        entry = self._entry(reservation, ('reserved', 'dispatched'))
        if entry.state == 'reserved':
            self._calls -= entry.calls
            self._candidates -= entry.candidates
            self._attempts -= entry.attempts
            self._held_cost -= entry.bound or 0
            del self._entries[reservation]
        else:
            entry.state = 'completed'

    def snapshot(self) -> dict[str, Any]:
        providers = [entry for entry in self._entries.values() if entry.calls and entry.state != 'abandoned']
        def total(field: str) -> int | float | None:
            if self._overflow:
                return None
            values = [getattr(entry, field) for entry in providers]
            if any(value is None for value in values):
                return None
            summed = sum(values)
            return summed if summed <= MAX_SAFE_NUMBER else None
        cost = total('cost')
        return {'provider_calls': self._calls, 'candidates': self._candidates,
                'attempts': self._attempts, 'input_tokens': total('input_tokens'),
                'output_tokens': total('output_tokens'), 'cost_usd': cost,
                'cost_kind': 'unknown' if cost is None else 'known',
                'pending': sum(entry.state in ('reserved', 'dispatched') for entry in self._entries.values())}
