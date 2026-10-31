"""Bounded corrective retrieval over an explicitly trusted backend."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import math
import re
from typing import Any, Awaitable, Callable, TypeVar

from ._postgres_session import DenseCandidate, IdentifierCandidate, LexicalCandidate
from .assessment import _policy, assess_evidence
from .context import Cl100kCounter, count_context
from .contracts import Evidence, RetrievalRequest, RetrievalResult, TrustedScope, parse_request, parse_scope
from .contracts._validation import MAX_SAFE_NUMBER, identity, integer, native_json
from .contracts.results import digest
from .errors import CragkitError, DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability
from .evidence import pack_and_assess
from .execution import BudgetExhausted, ExecutionLedger
from .events import EventSink, new_trace
from .planning import PlannerAdapter, validate_plan

_T = TypeVar('_T')
_KEYS = ('tenant_id', 'collection', 'document_id', 'revision_id', 'generation_id', 'chunk_id')
_CAP = 16_777_216


def _option_integer(value: object) -> int:
    parsed = integer(value)
    if type(parsed) is not int:
        raise InvalidRequest()
    return parsed


async def _bounded(work: Awaitable[_T], deadline: float) -> _T:
    if asyncio.get_running_loop().time() >= deadline:
        if asyncio.iscoroutine(work):
            work.close()
        raise DeadlineExceeded()
    task = asyncio.ensure_future(work)
    task.add_done_callback(lambda result: None if result.cancelled() else result.exception())
    try:
        done, _ = await asyncio.wait({task}, timeout=max(0, deadline - asyncio.get_running_loop().time()))
        if not done:
            raise DeadlineExceeded()
        result = task.result()
        if asyncio.get_running_loop().time() >= deadline:
            raise DeadlineExceeded()
        return result
    finally:
        if not task.done():
            task.cancel()


def _candidate(value: Any, request: RetrievalRequest, scope: TrustedScope) -> LexicalCandidate:
    try:
        if type(value) in (LexicalCandidate, DenseCandidate, IdentifierCandidate):
            value = value.model_dump(warnings=False)
        if type(value) is not dict:
            raise ValueError()
        native_json(value)
        model = (DenseCandidate if 'embedding_profile' in value else
                 IdentifierCandidate if 'identifier_profile' in value else LexicalCandidate)
        item = model.model_validate(value)
        for key in _KEYS:
            identity(getattr(item, key))
        if item.tenant_id != scope.tenant_id or item.collection != request.collection or item.end_byte <= item.start_byte:
            raise ValueError()
        return item
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise IntegrityViolation() from None


class CorrectiveRetriever:
    def __init__(self, backend: Any, *, policy: object = None, variants: object = None,
                 planner: PlannerAdapter | None = None, counter: Cl100kCounter | None = None,
                 batch_size: int = 16, max_retries: int = 0, backoff_ms: int = 0,
                 no_progress_limit: int = 1, event_sink: EventSink | None = None) -> None:
        batch_size = _option_integer(batch_size)
        max_retries = _option_integer(max_retries)
        backoff_ms = _option_integer(backoff_ms)
        no_progress_limit = _option_integer(no_progress_limit)
        if (not callable(getattr(backend, 'search', None)) or not callable(getattr(backend, 'capture', None))
                or type(batch_size) is not int or not 1 <= batch_size <= 64
                or type(max_retries) is not int or not 0 <= max_retries <= 2
                or type(backoff_ms) is not int or not 0 <= backoff_ms <= 1000
                or type(no_progress_limit) is not int or not 1 <= no_progress_limit <= 3
                or (planner is not None and type(planner) is not PlannerAdapter)
                or (counter is not None and type(counter) is not Cl100kCounter)
                or (event_sink is not None and type(event_sink) is not EventSink)):
            raise InvalidRequest()
        self._backend, self._planner, self._counter = backend, planner, counter
        accounting=getattr(backend,'candidate_accounting','outer')
        if type(accounting) is not str or accounting not in ('outer','backend'):
            raise InvalidRequest()
        self._candidate_accounting=accounting
        if event_sink is not None:
            try:
                EventSink.snapshot(event_sink)
            except Exception:
                raise InvalidRequest() from None
        self._event_sink = event_sink
        self._batch = batch_size
        self._max_retries, self._backoff, self._no_progress = max_retries, backoff_ms, no_progress_limit
        try:
            native_json(policy)
            native_json([] if variants is None else variants)
            self._policy, self._variants = copy.deepcopy(policy), copy.deepcopy([] if variants is None else variants)
        except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError):
            raise InvalidRequest() from None
        validate_plan({'queries': []}, query='validation', variants=self._variants, missing_facets=[], max_subqueries=16)
        if policy is not None:
            try:
                native_json(self._policy)
                if type(self._policy) is not dict:
                    raise ValueError()
                validation = dict(self._policy)
                digest(validation['query_sha256'])
                validation['query_sha256'] = hashlib.sha256(b'validation').hexdigest()
                _policy(validation, 'validation')
            except (ValueError, TypeError, KeyError, RecursionError, OverflowError):
                raise InvalidRequest() from None

    async def retrieve(self, request: object, *, scope: object, deadline: float) -> dict[str, Any]:
        if type(request) is RetrievalRequest:
            request = request.model_dump(mode='json', warnings=False)
        if type(scope) is TrustedScope:
            scope = scope.model_dump(mode='json', warnings=False)
        req, trusted = parse_request(request), parse_scope(scope)
        if (type(deadline) not in (int, float) or not math.isfinite(deadline) or abs(deadline) > MAX_SAFE_NUMBER):
            raise InvalidRequest()
        ledger = ExecutionLedger(req.limits, deadline=deadline)
        deadline = ledger.deadline
        loop = asyncio.get_running_loop()
        started = loop.time()
        sink = self._event_sink
        trace = new_trace() if sink is not None else None

        def emit(stage: str, reason: str | None = None) -> None:
            if sink is None or trace is None:
                return
            try:
                state = ledger.snapshot()
                EventSink.emit(sink, stage, trace_id=trace, attempt=state['attempts'],
                    elapsed_ms=min(300000, max(0, (loop.time() - started) * 1000)),
                    candidate_count=state['candidates'], provider_calls=state['provider_calls'], stop_reason=reason)
            except Exception:
                pass

        emit('start')
        try:
            if loop.time() >= deadline:
                raise DeadlineExceeded()
            response = await self._run(req, trusted, ledger, deadline, emit)
            emit('stop', response['diagnostics']['stop_reason'])
            if sink is not None:
                response['diagnostics']['events'] = dict(trace_id=trace, **EventSink.snapshot(sink))
            return response
        except asyncio.CancelledError:
            emit('cancelled', 'cancelled')
            raise
        except Exception as error:
            emit('error', error.code if isinstance(error, CragkitError) else 'provider_unavailable')
            raise
        finally:
            ledger.close()

    async def _run(self, req: RetrievalRequest, trusted: TrustedScope,
                   ledger: ExecutionLedger, deadline: float,
                   emit: Callable[[str, str | None], None]) -> dict[str, Any]:
        policy, variants = copy.deepcopy(self._policy), copy.deepcopy(self._variants)
        assess_evidence(req.query, [], policy)
        validate_plan({'queries': []}, query=req.query, variants=variants,
                      missing_facets=[], max_subqueries=req.limits.max_subqueries)
        output = req.output_profile
        if output.renderer != 'cragkit.context.v2':
            raise UnsupportedCapability()
        counted = count_context([], max_tokens=req.limits.max_context_tokens,
                                reserve=output.envelope_reserve_tokens, counter=self._counter,
                                counting_mode=output.counting_mode)
        if output.counting_mode == 'strict' and output.tokenizer != counted['tokenizer']:
            raise UnsupportedCapability()
        retained: dict[tuple[str, ...], LexicalCandidate] = {}
        loaded = queries = 0
        degraded = stale = exhausted = fallback = False
        packed: dict[str, Any]

        async def capture() -> dict[str, Any]:
            nonlocal loaded, stale, exhausted
            candidates = list(retained.values())
            emit('capture', None)
            try:
                raw = await _bounded(self._backend.capture(candidates, request=req, scope=trusted,
                    deadline=deadline, max_source_bytes=_CAP - loaded, ledger=ledger), deadline)
            except BudgetExhausted:
                # A mandatory fresh capture could not finish; release no earlier evidence.
                ledger.close()
                exhausted = True
                return await _bounded(pack_and_assess(req.query, [], [], deadline=deadline,
                    max_tokens=req.limits.max_context_tokens, reserve=output.envelope_reserve_tokens,
                    counter=self._counter, counting_mode=output.counting_mode, policy=policy, rebalance=True), deadline)
            try:
                if type(raw) is not dict or set(raw) != {'evidence', 'sources', 'source_bytes', 'stale', 'budget_exhausted'}:
                    raise ValueError()
                raw = dict(raw)
                raw['source_bytes'] = integer(raw['source_bytes'])
                if (type(raw['source_bytes']) is not int or not 0 <= raw['source_bytes'] <= _CAP - loaded
                        or type(raw['stale']) is not bool or type(raw['budget_exhausted']) is not bool
                        or type(raw['evidence']) is not list or len(raw['evidence']) > 64
                        or type(raw['sources']) is not list or len(raw['sources']) > 64):
                    raise ValueError()
                for source in raw['sources']:
                    if type(source) is not dict or type(source.get('text')) is not str or len(source['text']) > _CAP - loaded:
                        raise ValueError()
                # The trusted callback must not retain mutable authority over packing inputs.
                raw = copy.deepcopy(raw)
                identities = {(c.collection, c.document_id, c.revision_id, c.chunk_id): c for c in candidates}
                items = []
                evidence_ids = set()
                for row in raw['evidence']:
                    if type(row) is Evidence:
                        row = row.model_dump(mode='json', warnings=False)
                    item = Evidence.model_validate(row)
                    candidate = identities.get((item.collection, item.document_id, item.revision_id, item.chunk_id))
                    if (candidate is None or item.evidence_id in evidence_ids
                            or (item.start_byte, item.end_byte, item.text_sha256) !=
                            (candidate.start_byte, candidate.end_byte, candidate.text_sha256)):
                        raise ValueError()
                    evidence_ids.add(item.evidence_id)
                    items.append(item.model_dump(mode='json'))
                source_keys = set()
                source_size = 0
                allowed = {(c.collection, c.document_id, c.revision_id) for c in candidates}
                for source in raw['sources']:
                    if type(source) is not dict or set(source) != {'collection', 'document_id', 'revision_id', 'source_sha256', 'text'}:
                        raise ValueError()
                    for name in ('collection', 'document_id', 'revision_id'):
                        if type(source[name]) is not str:
                            raise ValueError()
                        identity(source[name])
                    key = (source['collection'], source['document_id'], source['revision_id'])
                    if key not in allowed or key in source_keys or type(source['text']) is not str:
                        raise ValueError()
                    source_keys.add(key)
                    source_size += len(source['text'].encode('utf-8'))
                    if source_size > raw['source_bytes']:
                        raise ValueError()
                if source_size > raw['source_bytes']:
                    raise ValueError()
            except (ValueError, TypeError, UnicodeError, KeyError, RecursionError, OverflowError):
                raise IntegrityViolation() from None
            loaded += raw['source_bytes']
            stale = stale or raw['stale']
            exhausted = exhausted or raw['budget_exhausted']
            try:
                return await _bounded(pack_and_assess(req.query, items, raw['sources'], deadline=deadline,
                    max_tokens=req.limits.max_context_tokens, reserve=output.envelope_reserve_tokens,
                    counter=self._counter, counting_mode=output.counting_mode, policy=policy, rebalance=True), deadline)
            except InvalidRequest:
                raise IntegrityViolation() from None

        executed: set[str] = set()
        batches: set[frozenset[tuple[str, ...]]] = set()

        def query_key(query: str) -> str:
            lowered = query.translate(str.maketrans('ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))
            return re.sub(r'[ \t\r\n\f\v]+', ' ', lowered).strip(' ')

        async def search(query: str) -> frozenset[tuple[str, ...]]:
            nonlocal queries, degraded
            last_error: ProviderUnavailable | None = None
            started = False
            for retry in range(self._max_retries + 1):
                remaining = req.limits.max_candidates - ledger.snapshot()['candidates']
                size = min(self._batch, remaining, 64 - len(retained))
                try:
                    if size <= 0:
                        raise BudgetExhausted()
                    token = ledger.reserve(attempts=1, candidates=0 if self._candidate_accounting=='backend' else size)
                except BudgetExhausted:
                    if last_error is not None:
                        raise last_error
                    raise
                try:
                    ledger.dispatch(token)
                except BaseException:
                    ledger.abandon(token)
                    raise
                if not started:
                    queries += 1
                    executed.add(query_key(query))
                    started = True
                attempt = req.model_copy(update={'query': query})
                emit('search', None)
                candidate_start=ledger.snapshot()['candidates']
                try:
                    try:
                        raw = await _bounded(self._backend.search(attempt, scope=trusted, deadline=deadline,
                            limit=size, ledger=ledger), deadline)
                        if self._candidate_accounting=='backend' and ledger.snapshot()['candidates']-candidate_start!=size:
                            raise IntegrityViolation()
                    finally:
                        ledger.reconcile(token)
                except ProviderUnavailable as error:
                    last_error = error
                    if retry >= self._max_retries:
                        raise
                    emit('retry', None)
                    await _bounded(asyncio.sleep(self._backoff / 1000), deadline)
                    continue
                except BudgetExhausted:
                    if last_error is not None:
                        raise last_error
                    raise
                try:
                    if (type(raw) is not dict or set(raw) != {'candidates', 'degraded'} or type(raw['degraded']) is not bool
                            or type(raw['candidates']) is not list or len(raw['candidates']) > size):
                        raise ValueError()
                    batch = [_candidate(item, req, trusted) for item in raw['candidates']]
                    keys = [tuple(getattr(item, field) for field in _KEYS) for item in batch]
                    if len(set(keys)) != len(keys):
                        raise ValueError()
                    for key, item in zip(keys, batch):
                        retained.setdefault(key, item)
                    degraded = degraded or raw['degraded']
                except (ValueError, TypeError, RecursionError, OverflowError):
                    raise IntegrityViolation() from None
                return frozenset(keys)
            raise IntegrityViolation()

        try:
            batches.add(await search(req.query))
            packed = await capture()
        except BudgetExhausted:
            exhausted = True
            packed = await capture()
        reason = 'sufficient' if packed['status'] == 'sufficient' else ''
        selected: list[dict[str, str]] = []
        if not reason:
            if exhausted:
                reason = 'budget_exhausted'
            elif ledger.snapshot()['candidates'] >= req.limits.max_candidates or len(retained) >= 64:
                exhausted = True
                reason = 'budget_exhausted'
            elif ledger.snapshot()['attempts'] >= req.limits.max_attempts:
                reason = 'attempts_exhausted'
            elif queries >= req.limits.max_subqueries:
                reason = 'subqueries_exhausted'
            elif self._planner is None or not variants:
                reason = 'coverage_unknown' if policy is None else 'no_plan'
            else:
                missing = [f['facet_id'] for f in packed['facets'] if f['required'] and f['state'] != 'supported']
                emit('planning', None)
                try:
                    planned = await _bounded(self._planner.plan(req.query, variants=variants, missing_facets=missing,
                        max_subqueries=req.limits.max_subqueries, ledger=ledger, deadline=deadline), deadline)
                    selected, fallback = planned['queries'], planned['fallback']
                    # Planning can change application authorization while awaiting its provider.
                    packed = await capture()
                    if packed['status'] == 'sufficient':
                        reason = 'sufficient'
                    elif exhausted:
                        reason = 'budget_exhausted'
                except BudgetExhausted:
                    exhausted = True
                    packed = await capture()
                    reason = 'budget_exhausted'
                if not selected and not reason:
                    reason = 'coverage_unknown' if policy is None else 'no_plan'
        no_progress = 0
        supported = sum(f['required'] and f['state'] == 'supported' for f in packed['facets'])
        for variant in selected:
            if reason:
                break
            if not any(f['facet_id'] == variant['facet_id'] and f['required'] and f['state'] != 'supported' for f in packed['facets']):
                continue
            if query_key(variant['query']) in executed:
                reason = 'repeated_query'
                break
            if queries >= req.limits.max_subqueries:
                reason = 'subqueries_exhausted'
                break
            if ledger.snapshot()['attempts'] >= req.limits.max_attempts:
                reason = 'attempts_exhausted'
                break
            try:
                batch_keys = await search(variant['query'])
                packed = await capture()
            except BudgetExhausted:
                exhausted = True
                packed = await capture()
                reason = 'budget_exhausted'
                break
            current = sum(f['required'] and f['state'] == 'supported' for f in packed['facets'])
            no_progress = 0 if current > supported else no_progress + 1
            supported = current
            repeated = batch_keys in batches
            batches.add(batch_keys)
            if packed['status'] == 'sufficient':
                reason = 'sufficient'
            elif exhausted:
                reason = 'budget_exhausted'
            elif repeated:
                reason = 'repeated_candidates'
            elif no_progress >= self._no_progress:
                reason = 'no_progress'
        reason = reason or 'plan_complete'
        limitations = []
        if any(f['required'] and f['state'] == 'unknown' for f in packed['facets']):
            limitations.append({'code': 'coverage_unknown'})
        if any(f['required'] and f['state'] != 'supported' for f in packed['facets']):
            limitations.append({'code': 'incomplete_facets'})
        if degraded:
            limitations.append({'code': 'degraded_search'})
        if stale:
            limitations.append({'code': 'stale_evidence'})
        if packed['omitted_count']:
            limitations.append({'code': 'truncated_evidence'})
        if exhausted or packed['omitted_count']:
            limitations.append({'code': 'budget_exhausted'})
        usage = ledger.snapshot()
        try:
            result = RetrievalResult.model_validate(dict(request_id=req.request_id, status=packed['status'],
                execution='degraded' if degraded else 'complete', evidence=packed['evidence'], facets=packed['facets'],
                context=packed['context'], limitations=limitations,
                versions=dict(policy=packed['policy'], tokenizer=packed['tokenizer']),
                usage=dict(attempt_count=usage['attempts'], provider_calls=usage['provider_calls'],
                    provider_input_tokens=usage['input_tokens'], provider_output_tokens=usage['output_tokens'],
                    cost_usd=usage['cost_usd'], cost_kind=usage['cost_kind'], context_tokens=packed['context_tokens'],
                    context_counting=packed['counting_mode'])))
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise IntegrityViolation() from None
        if asyncio.get_running_loop().time() >= deadline:
            raise DeadlineExceeded()
        return {'result': result.model_dump(mode='json'), 'diagnostics': dict(stop_reason=reason,
            queries_executed=queries, candidate_work=usage['candidates'], planning_fallback=fallback, ledger=usage)}
