"""Minimal lexical evidence results with verified sources and unknown coverage."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
from typing import Any

from pydantic import ValidationError

from ._hybrid import profile_snapshot, select
from .embeddings import EmbeddingAdapter
from ._postgres_pool import PoolResource
from ._postgres_session import PostgresSession, _check_deadline
from .contracts import Evidence, RetrievalRequest, RetrievalResult, TrustedScope, parse_request, parse_scope
from .errors import ContextBudgetTooSmall, IntegrityViolation, InvalidRequest, UnsupportedCapability
from .errors import DeadlineExceeded
from .assessment import assess_evidence, _policy
from .context import count_context
from .contracts._validation import native_json
from .contracts.results import digest
from .evidence import pack_and_assess
from .reranking import RerankingAdapter, RerankProfile


class PostgresRetriever:
    """Reuse caller-owned resources; do not infer semantic support from lexical hits."""

    def __init__(self, resource: PoolResource, *, mode: str = 'lexical',
                 embedder: EmbeddingAdapter | None = None, allow_degraded: bool = False,
                 identifiers: bool = True, evidence_options: dict[str, Any] | None = None) -> None:
        if (type(mode) is not str or mode not in ('lexical', 'dense', 'hybrid')
                or type(allow_degraded) is not bool or type(identifiers) is not bool
                or (mode == 'lexical' and (embedder is not None or allow_degraded))
                or (mode != 'lexical' and not isinstance(embedder, EmbeddingAdapter))
                or (mode == 'dense' and allow_degraded)):
            raise InvalidRequest()
        self._mode, self._embedder = mode, embedder
        self._allow_degraded, self._identifiers = allow_degraded, identifiers
        self._session = PostgresSession(resource)
        self._evidence_options: dict[str, Any] | None = None
        if evidence_options is not None:
            try:
                if type(evidence_options) is not dict or not set(evidence_options) <= {
                    'policy', 'counter', 'rebalance', 'surrounding_bytes', 'reranker', 'rerank_fallback', 'rerank_limit'
                }:
                    raise ValueError()
                options: dict[str, Any] = dict(policy=None, counter=None, rebalance=False, surrounding_bytes=256,
                               reranker=None, rerank_fallback=False, rerank_limit=40)
                options.update(evidence_options)
                if (type(options['rebalance']) is not bool or type(options['rerank_fallback']) is not bool
                        or type(options['surrounding_bytes']) is not int
                        or not 0 <= options['surrounding_bytes'] <= 4096
                        or type(options['rerank_limit']) is not int or not 1 <= options['rerank_limit'] <= 40
                        or (options['reranker'] is not None and not isinstance(options['reranker'], RerankingAdapter))):
                    raise ValueError()
                if options['policy'] is not None:
                    native_json(options['policy'])
                    configured = copy.deepcopy(options['policy'])
                    validation = dict(configured)
                    validation['query_sha256'] = hashlib.sha256(b'validation').hexdigest()
                    _policy(validation, 'validation')
                    # Validate the original digest independently of the temporary binding.
                    if type(configured.get('query_sha256')) is not str:
                        raise ValueError()
                    digest(configured['query_sha256'])
                    options['policy'] = configured
                if options['counter'] is not None:
                    count_context([], max_tokens=1000000, reserve=0, counting_mode='strict', counter=options['counter'])
                if options['reranker'] is not None:
                    RerankProfile.model_validate(options['reranker'].profile.model_dump())
                self._evidence_options = options
            except Exception:
                raise InvalidRequest() from None

    async def retrieve(self, request: RetrievalRequest, *, scope: TrustedScope,
                       deadline: float) -> RetrievalResult:
        started = asyncio.get_running_loop().time()
        _check_deadline(deadline)
        mode, embedder = self._mode, self._embedder
        allow_degraded, identifiers = self._allow_degraded, self._identifiers
        if not isinstance(request, RetrievalRequest) or not isinstance(scope, TrustedScope):
            raise InvalidRequest()
        invalid = False
        try:
            request = parse_request(request.model_dump(mode='json'))
            scope = parse_scope(scope.model_dump(mode='json'))
        except Exception:
            invalid = True
        if invalid:
            raise InvalidRequest()
        output = request.output_profile
        if self._evidence_options is not None:
            return await self._retrieve_evidence(request, scope=scope, deadline=min(
                deadline, started + request.limits.deadline_ms / 1000))
        if output.renderer != 'cragkit.context.v1' or output.counting_mode != 'estimated' or output.tokenizer is not None:
            raise UnsupportedCapability()
        if output.envelope_reserve_tokens >= request.limits.max_context_tokens:
            raise ContextBudgetTooSmall()
        deadline = min(deadline, started + request.limits.deadline_ms / 1000)
        _check_deadline(deadline)
        profile = profile_snapshot(embedder) if embedder is not None else None
        capacity = min(262_144, 4 * (request.limits.max_context_tokens - output.envelope_reserve_tokens))
        candidate_limit = min(65, request.limits.max_candidates)
        degraded = False
        prompt_tokens: int | None = 0
        stages: list[dict[str, Any]] = []
        if mode == 'lexical':
            async with self._session.transaction(request, scope=scope, deadline=deadline) as handle:
                candidates = await handle.lexical_candidates(limit=candidate_limit)
        else:
            assert embedder is not None and profile is not None
            candidates, degraded, prompt_tokens, stages = await select(
                self._session, request, scope, deadline, mode=mode, embedder=embedder,
                allow_degraded=allow_degraded, identifiers=identifiers, profile=profile)
        if len(candidates) > candidate_limit:
            raise IntegrityViolation()
        identities = [(item.tenant_id, item.collection, item.document_id, item.revision_id,
                       item.generation_id, item.chunk_id) for item in candidates]
        if len(set(identities)) != len(identities):
            raise IntegrityViolation()
        evidence: list[Evidence] = []
        evidence_ids: set[str] = set()
        context = ''
        stale = False
        truncated = len(candidates) > 64
        exhausted = False
        loaded = 0
        # A fresh snapshot rechecks current authorization after candidate selection.
        if candidates:
            async with self._session.transaction(request, scope=scope, deadline=deadline) as handle:
                for candidate in candidates[:64]:
                    _check_deadline(deadline)
                    remaining = 16_777_216 - loaded
                    if remaining <= 0:
                        exhausted = True
                        break
                    source = await handle.fetch_evidence(candidate, max_source_bytes=remaining)
                    if source.state == 'unavailable':
                        stale = True
                        continue
                    if source.state == 'budget_exhausted':
                        exhausted = True
                        break
                    if source.evidence is None or not 0 < source.source_bytes <= remaining:
                        raise IntegrityViolation()
                    loaded += source.source_bytes
                    stale = stale or source.stale
                    item = source.evidence
                    if item.evidence_id in evidence_ids:
                        raise IntegrityViolation()
                    evidence_ids.add(item.evidence_id)
                    proposed = json.dumps([entry.model_dump(mode='json') for entry in (*evidence, item)],
                                          ensure_ascii=False, separators=(',', ':'))
                    if len(proposed.encode('utf-8')) > capacity:
                        truncated = exhausted = True
                        continue
                    evidence.append(item)
                    context = proposed
        limitations = [{'code': 'coverage_unknown'}]
        if degraded:
            limitations.append({'code': 'degraded_search'})
        if stale:
            limitations.append({'code': 'stale_evidence'})
        if truncated:
            limitations.append({'code': 'truncated_evidence'})
        if exhausted:
            limitations.append({'code': 'budget_exhausted'})
        _check_deadline(deadline)
        result = None
        try:
            result = RetrievalResult.model_validate({
                'execution': 'degraded' if degraded else 'complete',
                'request_id': request.request_id, 'status': 'partial' if evidence else 'insufficient',
                'evidence': [item.model_dump(mode='json') for item in evidence], 'facets': [],
                'context': context, 'limitations': limitations,
                'usage': {'attempt_count': 1, 'provider_calls': 0 if mode == 'lexical' else 1, 'provider_input_tokens': prompt_tokens,
                          'stage_durations': stages,
                          'provider_output_tokens': 0, 'cost_usd': 0, 'cost_kind': 'known',
                          'context_counting': 'estimated', 'context_tokens': (len(context.encode('utf-8')) + 3) // 4},
                'versions': {'index': 'native_fts.v1'} if mode == 'lexical' else {
                    'model': 'fake_embedding_model_v1',
                    'index': 'dense_fake.v1' if mode == 'dense' else 'hybrid_rrf.v1'},
            })
        except (ValidationError, TypeError, ValueError):
            pass
        if result is None:
            raise IntegrityViolation()
        _check_deadline(deadline)
        return result

    async def _retrieve_evidence(self, request: RetrievalRequest, *, scope: TrustedScope,
                                 deadline: float) -> RetrievalResult:
        options = self._evidence_options
        assert options is not None
        output = request.output_profile
        counter = options['counter'] if output.counting_mode == 'strict' else None
        if (output.renderer != 'cragkit.context.v2'
                or (output.counting_mode == 'strict' and output.tokenizer != 'cl100k_base')
                or (output.counting_mode == 'estimated' and output.tokenizer is not None)):
            raise UnsupportedCapability()
        count_context([], max_tokens=request.limits.max_context_tokens,
                      reserve=output.envelope_reserve_tokens, counter=counter,
                      counting_mode=output.counting_mode)
        assess_evidence(request.query, [], options['policy'])
        reranker = options['reranker']
        try:
            rerank_profile = RerankProfile.model_validate(reranker.profile.model_dump()) if reranker else None
        except Exception:
            raise InvalidRequest() from None
        if reranker and len(request.query.encode('utf-8')) > 8192:
            raise InvalidRequest()
        embedding_calls = int(self._mode != 'lexical')
        if request.limits.max_provider_calls < embedding_calls + int(reranker is not None):
            raise InvalidRequest()
        if (rerank_profile is not None and rerank_profile.provider != 'fake'
                and request.limits.max_spend_usd is not None):
            raise UnsupportedCapability()
        _check_deadline(deadline)
        stages: list[dict[str, Any]] = []
        degraded = False
        prompt_tokens: int | None = 0
        candidate_limit = min(65, request.limits.max_candidates)
        if self._mode == 'lexical':
            async with self._session.transaction(request, scope=scope, deadline=deadline) as handle:
                candidates = await handle.lexical_candidates(limit=candidate_limit)
        else:
            assert self._embedder is not None
            candidates, degraded, prompt_tokens, stages = await select(
                self._session, request, scope, deadline, mode=self._mode, embedder=self._embedder,
                allow_degraded=self._allow_degraded, identifiers=self._identifiers,
                profile=profile_snapshot(self._embedder))
        if len(candidates) > candidate_limit:
            raise IntegrityViolation()
        keys = [(c.tenant_id, c.collection, c.document_id, c.revision_id, c.generation_id, c.chunk_id)
                for c in candidates]
        if len(set(keys)) != len(keys):
            raise IntegrityViolation()
        cap = options['rerank_limit'] if reranker else 64
        truncated = len(candidates) > cap
        stale = exhausted = False
        loaded = 0

        async def capture(selected: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, Any]]:
            nonlocal stale, exhausted, loaded, truncated
            items: list[dict[str, Any]] = []
            sources: list[dict[str, str]] = []
            mapping: dict[str, Any] = {}
            if selected:
                async with self._session.transaction(request, scope=scope, deadline=deadline) as handle:
                    for candidate in selected:
                        _check_deadline(deadline)
                        remaining = 16777216 - loaded
                        if remaining <= 0:
                            exhausted = True
                            break
                        fetched = await handle.fetch_evidence(candidate, max_source_bytes=remaining, include_source=True)
                        if fetched.state == 'unavailable':
                            stale = True
                            continue
                        if fetched.state == 'budget_exhausted':
                            exhausted = True
                            break
                        if (fetched.evidence is None or type(fetched.source_bytes) is not int
                                or not 0 < fetched.source_bytes <= remaining):
                            raise IntegrityViolation()
                        loaded += fetched.source_bytes
                        stale = stale or fetched.stale
                        item = fetched.evidence.model_dump(mode='json')
                        if item['evidence_id'] in mapping:
                            raise IntegrityViolation()
                        proposal = [*items, item]
                        if len(json.dumps(proposal, ensure_ascii=False, separators=(',', ':')).encode('utf-8')) > 262144:
                            exhausted = truncated = True
                            continue
                        mapping[item['evidence_id']] = candidate
                        items.append(item)
                        sources.append(fetched.source_snapshot())
            return items, sources, mapping

        items, sources, mapping = await capture(list(candidates[:cap]))
        dispatched = 0
        if reranker and items:
            assert rerank_profile is not None
            views = [{'candidate_id': item['evidence_id'], 'text': item['text']} for item in items]
            expected_truncations = []
            accepted_views = []
            total = len(request.query.encode('utf-8'))
            for view in views:
                raw = view['text'].encode('utf-8')
                size = len(raw)
                if size > 16384:
                    if rerank_profile.truncation_policy != 'utf8_prefix':
                        raise InvalidRequest()
                    size = len(raw[:16384].decode('utf-8', errors='ignore').encode('utf-8'))
                    expected_truncations.append(dict(candidate_id=view['candidate_id'], original_bytes=len(raw), view_bytes=size))
                if total + size > 262144:
                    truncated = exhausted = True
                    expected_truncations = [record for record in expected_truncations if record['candidate_id'] != view['candidate_id']]
                    continue
                total += size
                accepted_views.append(view)
            views = accepted_views
            mapping = {view['candidate_id']: mapping[view['candidate_id']] for view in views}
            if total > 262144:
                raise InvalidRequest()
            started = asyncio.get_running_loop().time()
            dispatched = 1
            task = asyncio.create_task(reranker.rank(request.query, views, deadline=deadline,
                                                    max_provider_calls=1, allow_fallback=options['rerank_fallback']))
            def settled(done: asyncio.Task[Any]) -> None:
                if not done.cancelled():
                    done.exception()
            task.add_done_callback(settled)
            try:
                done, _ = await asyncio.wait({task}, timeout=max(0, deadline - asyncio.get_running_loop().time()))
                if not done:
                    task.cancel()
                    raise DeadlineExceeded()
                ranked = task.result()
            except asyncio.CancelledError:
                task.cancel()
                raise
            _check_deadline(deadline)
            try:
                if type(ranked) is not dict or set(ranked) != {'profile', 'order', 'scores', 'truncations', 'degraded', 'provider_calls', 'synthetic'}:
                    raise ValueError()
                if type(ranked['scores']) is not list or len(ranked['scores']) > 40:
                    raise ValueError()
                safe_ranked = {**ranked, 'scores': [
                    {**row, 'raw_score': 0} if type(row) is dict and 'raw_score' in row else row
                    for row in ranked['scores']]}
                native_json(safe_ranked)
                if (ranked['profile'] != rerank_profile.model_dump() or type(ranked['provider_calls']) is not int
                        or ranked['provider_calls'] != 1 or type(ranked['synthetic']) is not bool
                        or ranked['synthetic'] != (rerank_profile.provider == 'fake')
                        or type(ranked['degraded']) is not bool or ranked['truncations'] != expected_truncations
                        or type(ranked['order']) is not list or len(ranked['order']) != len(mapping)
                        or any(type(ref) is not str for ref in ranked['order'])
                        or set(ranked['order']) != set(mapping)):
                    raise ValueError()
                scores = ranked['scores']
                if ranked['degraded']:
                    if not options['rerank_fallback'] or scores != [] or ranked['order'] != list(mapping):
                        raise ValueError()
                else:
                    if type(scores) is not list or len(scores) != len(mapping):
                        raise ValueError()
                    seen = set()
                    for score in scores:
                        if (type(score) is not dict or set(score) != {'candidate_id', 'raw_score'}
                                or type(score['candidate_id']) is not str or score['candidate_id'] not in mapping
                                or score['candidate_id'] in seen or type(score['raw_score']) not in (int, float)
                                or not math.isfinite(score['raw_score'])):
                            raise ValueError()
                        seen.add(score['candidate_id'])
                    score_map = {row['candidate_id']: row['raw_score'] for row in scores}
                    expected_order = sorted(mapping, key=lambda ref: score_map[ref],
                                            reverse=rerank_profile.score_direction == 'higher_is_better')
                    if ranked['order'] != expected_order:
                        raise ValueError()
            except (ValueError, TypeError, OverflowError):
                raise IntegrityViolation() from None
            degraded = degraded or ranked['degraded']
            truncated = truncated or bool(expected_truncations)
            stages.append(dict(stage='reranking_complete', duration_ms=min(300000, (asyncio.get_running_loop().time() - started) * 1000)))
            items, sources, _ = await capture([mapping[ref] for ref in ranked['order']])
        started = asyncio.get_running_loop().time()
        packed = await pack_and_assess(request.query, items, sources, deadline=deadline,
            max_tokens=request.limits.max_context_tokens, reserve=output.envelope_reserve_tokens,
            counter=counter, counting_mode=output.counting_mode, policy=options['policy'],
            rebalance=options['rebalance'], surrounding_bytes=options['surrounding_bytes'])
        stages.append(dict(stage='packing_rebalance_complete' if packed['rebalance_count'] else 'packing_complete',
                           duration_ms=min(300000, (asyncio.get_running_loop().time() - started) * 1000)))
        limitations: list[dict[str, Any]] = []
        unknown = [f['facet_id'] for f in packed['facets'] if f['required'] and f['state'] == 'unknown']
        incomplete = [f['facet_id'] for f in packed['facets'] if f['required'] and f['state'] != 'supported']
        if unknown: limitations.append(dict(code='coverage_unknown'))
        if incomplete: limitations.append(dict(code='incomplete_facets'))
        if degraded: limitations.append(dict(code='degraded_search'))
        if stale: limitations.append(dict(code='stale_evidence'))
        if truncated or packed['omitted_count']: limitations.append(dict(code='truncated_evidence'))
        if exhausted or packed['omitted_count']: limitations.append(dict(code='budget_exhausted'))
        live = rerank_profile is not None and rerank_profile.provider != 'fake' and dispatched > 0
        versions = dict(index='native_fts.v1' if self._mode == 'lexical' else 'dense_fake.v1' if self._mode == 'dense' else 'hybrid_rrf.v1',
                        policy=packed['policy'], tokenizer=packed['tokenizer'])
        if rerank_profile is not None: versions['model'] = rerank_profile.profile_id
        elif self._mode != 'lexical': versions['model'] = 'fake_embedding_model_v1'
        try:
            result = RetrievalResult.model_validate(dict(request_id=request.request_id,
                execution='degraded' if degraded else 'complete', status=packed['status'], evidence=packed['evidence'],
                facets=packed['facets'], context=packed['context'], limitations=limitations, versions=versions,
                usage=dict(attempt_count=1, provider_calls=embedding_calls + dispatched,
                    provider_input_tokens=None if dispatched else prompt_tokens, provider_output_tokens=None if dispatched else 0,
                    cost_usd=None if live else 0, cost_kind='unknown' if live else 'known',
                    context_counting=packed['counting_mode'], context_tokens=packed['context_tokens'], stage_durations=stages)))
        except (ValidationError, TypeError, ValueError):
            raise IntegrityViolation() from None
        _check_deadline(deadline)
        return result
