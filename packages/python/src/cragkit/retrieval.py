"""Minimal lexical evidence results with verified sources and unknown coverage."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from pydantic import ValidationError

from ._hybrid import profile_snapshot, select
from .embeddings import EmbeddingAdapter
from ._postgres_pool import PoolResource
from ._postgres_session import PostgresSession, _check_deadline
from .contracts import Evidence, RetrievalRequest, RetrievalResult, TrustedScope, parse_request, parse_scope
from .errors import ContextBudgetTooSmall, IntegrityViolation, InvalidRequest, UnsupportedCapability


class PostgresRetriever:
    """Reuse caller-owned resources; do not infer semantic support from lexical hits."""

    def __init__(self, resource: PoolResource, *, mode: str = 'lexical',
                 embedder: EmbeddingAdapter | None = None, allow_degraded: bool = False,
                 identifiers: bool = True) -> None:
        if (type(mode) is not str or mode not in ('lexical', 'dense', 'hybrid')
                or type(allow_degraded) is not bool or type(identifiers) is not bool
                or (mode == 'lexical' and (embedder is not None or allow_degraded))
                or (mode != 'lexical' and not isinstance(embedder, EmbeddingAdapter))
                or (mode == 'dense' and allow_degraded)):
            raise InvalidRequest()
        self._mode, self._embedder = mode, embedder
        self._allow_degraded, self._identifiers = allow_degraded, identifiers
        self._session = PostgresSession(resource)

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
