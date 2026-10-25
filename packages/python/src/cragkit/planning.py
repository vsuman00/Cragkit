"""Optional planning selects trusted variants without changing retrieval authority."""
from __future__ import annotations

import asyncio
import json
import math
from typing import Any, Protocol

from ._identifiers import extract_identifiers
from .contracts._validation import MAX_SAFE_NUMBER, identity, input_text, integer, native_json
from .errors import DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable
from .execution import ExecutionLedger


def _string(value: object, *, query: bool = False) -> str:
    if type(value) is not str:
        raise ValueError()
    return input_text(value, 16384) if query else identity(value)


def _configuration(query: object, variants: object, missing: object, maximum: object) -> dict[str, Any]:
    try:
        maximum = integer(maximum)
        query = _string(query, query=True)
        if type(maximum) is not int or not 1 <= maximum <= 16:
            raise ValueError()
        if type(variants) is not list or len(variants) > 16 or type(missing) is not list or len(missing) > 32:
            raise ValueError()
        facets = [_string(facet) for facet in missing]
        if len(set(facets)) != len(facets):
            raise ValueError()
        approved = []
        seen = set()
        required = set(extract_identifiers(query))
        for item in variants:
            if type(item) is not dict or set(item) != {'facet_id', 'variant_id', 'query'}:
                raise ValueError()
            row = {key: _string(item[key], query=key == 'query') for key in item}
            if row['variant_id'] in seen or not required <= set(extract_identifiers(row['query'])):
                raise ValueError()
            seen.add(row['variant_id'])
            approved.append(row)
        return dict(query=query, variants=approved, missing_facets=facets, max_subqueries=maximum)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise InvalidRequest() from None


def validate_plan(value: object, *, query: object, variants: object,
                  missing_facets: object, max_subqueries: object) -> list[dict[str, str]]:
    config = _configuration(query, variants, missing_facets, max_subqueries)
    try:
        native_json(value)
        if type(value) is not dict or set(value) != {'queries'}:
            raise ValueError()
        rows = value['queries']
        if type(rows) is not list or len(rows) > min(16, config['max_subqueries'] - 1):
            raise ValueError()
        approved = {row['variant_id']: row for row in config['variants']}
        selected = []
        seen = set()
        for row in rows:
            if type(row) is not dict or set(row) != {'facet_id', 'variant_id'}:
                raise ValueError()
            facet, variant = _string(row['facet_id']), _string(row['variant_id'])
            match = approved.get(variant)
            if (variant in seen or facet not in config['missing_facets']
                    or match is None or match['facet_id'] != facet):
                raise ValueError()
            seen.add(variant)
            selected.append(dict(match))
        return selected
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise InvalidRequest() from None


class PlannerTransport(Protocol):
    async def __call__(self, payload: dict[str, Any], *, deadline: float) -> object: ...


def _usage(response: object) -> tuple[object, dict[str, Any]]:
    try:
        native_json(response)
        if len(json.dumps(response, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')) > 16384:
            raise ValueError()
        if type(response) is not dict or set(response) != {'plan', 'usage'}:
            raise ValueError()
        usage = response['usage']
        if type(usage) is not dict or set(usage) != {'input_tokens', 'output_tokens', 'cost_usd'}:
            raise ValueError()
        for key, value in usage.items():
            if value is None:
                continue
            if type(value) not in (int, float):
                raise ValueError()
            if not 0 <= value <= MAX_SAFE_NUMBER or not math.isfinite(value):
                raise ValueError()
            if key != 'cost_usd':
                value = integer(value)
                if type(value) is not int:
                    raise ValueError()
        return response['plan'], {key: integer(value) if key != 'cost_usd' else value
                                   for key, value in usage.items()}
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
        raise IntegrityViolation() from None


class PlannerAdapter:
    def __init__(self, transport: PlannerTransport, *, sdk_retries: int = 0,
                 cost_upper_usd: float | None = None, allow_fallback: bool = False) -> None:
        normalized_retries = integer(sdk_retries)  # same JSON integer normalization as request limits
        if not callable(transport) or type(normalized_retries) is not int or normalized_retries != 0 or type(allow_fallback) is not bool:
            raise InvalidRequest()
        if cost_upper_usd is not None:
            if (type(cost_upper_usd) not in (int, float) or not math.isfinite(cost_upper_usd)
                    or not 0 <= cost_upper_usd <= MAX_SAFE_NUMBER):
                raise InvalidRequest()
        self._transport = transport
        self._bound = cost_upper_usd
        self._fallback = allow_fallback

    async def plan(self, query: object, *, variants: object, missing_facets: object,
                   max_subqueries: object, ledger: ExecutionLedger, deadline: float) -> dict[str, Any]:
        config = _configuration(query, variants, missing_facets, max_subqueries)
        if (type(ledger) is not ExecutionLedger or type(deadline) not in (int, float)
                or not math.isfinite(deadline) or abs(deadline) > MAX_SAFE_NUMBER):
            raise InvalidRequest()
        deadline = min(deadline, ledger.deadline)
        loop = asyncio.get_running_loop()
        if loop.time() >= deadline:
            raise DeadlineExceeded()
        if not config['variants'] or not config['missing_facets'] or config['max_subqueries'] == 1:
            return {'queries': [], 'fallback': False}
        token = ledger.reserve(provider_calls=1, cost_upper_usd=self._bound)
        try:
            ledger.dispatch(token)
        except BaseException:
            ledger.abandon(token)
            raise
        task: asyncio.Task[object] | None = None
        try:
            # The callback owns its payload; validation retains a separate snapshot.
            payload = json.loads(json.dumps(config))
            async def invoke() -> object:
                return await self._transport(payload, deadline=deadline)
            task = asyncio.create_task(invoke())
            done, _ = await asyncio.wait({task}, timeout=max(0, deadline - loop.time()))
            if not done:
                task.cancel()
                raise DeadlineExceeded()
            try:
                response = task.result()
            except (asyncio.CancelledError, DeadlineExceeded, ProviderUnavailable):
                raise
            except Exception:
                raise ProviderUnavailable() from None
            if loop.time() >= deadline:
                raise DeadlineExceeded()
            plan, usage = _usage(response)
        except BaseException as exc:
            if task is not None and not task.done():
                task.cancel()
                task.add_done_callback(lambda result: None if result.cancelled() else result.exception())
            ledger.abandon(token)
            if self._fallback and isinstance(exc, (ProviderUnavailable, IntegrityViolation)):
                return {'queries': [], 'fallback': True}
            raise
        # Accounting failures must never be converted to a planning fallback.
        ledger.reconcile(token, **usage)
        try:
            selected = validate_plan(plan, **config)
        except InvalidRequest:
            if self._fallback:
                return {'queries': [], 'fallback': True}
            raise IntegrityViolation() from None
        return {'queries': selected, 'fallback': False}
