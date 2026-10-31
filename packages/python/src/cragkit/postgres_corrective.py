"""Optional corrective backend over caller-owned PostgreSQL resources."""
from __future__ import annotations

import asyncio
from types import MappingProxyType
import math
import copy
from typing import Any, Mapping

from ._hybrid import profile_snapshot, select
from ._identifiers import extract_identifiers
from ._postgres_pool import PoolResource
from ._postgres_session import PostgresSession, LexicalCandidate, DenseCandidate, IdentifierCandidate, _check_deadline
from .contracts import RetrievalRequest, TrustedScope, parse_request, parse_scope
from .embeddings import EmbeddingAdapter, EmbeddingProfile, EmbeddingUsage, FAKE_PROFILE
from ._postgres_profiles import snapshot_profile
from .reranking import RerankingAdapter, RerankProfile
from .execution import BudgetExhausted, ExecutionLedger
from .errors import IntegrityViolation, InvalidRequest, DeadlineExceeded


def _candidates(value: Any, request: RetrievalRequest, scope: TrustedScope) -> list[LexicalCandidate]:
    if type(value) not in (list, tuple) or len(value) > 64:
        raise InvalidRequest()
    result = []
    seen = set()
    try:
        for raw in value:
            data = raw.model_dump() if isinstance(raw, LexicalCandidate) else raw
            model = DenseCandidate if 'embedding_profile' in data else IdentifierCandidate if 'identifier_profile' in data else LexicalCandidate
            item = model.model_validate(data)
            key = tuple(getattr(item, name) for name in ('tenant_id', 'collection', 'document_id', 'revision_id', 'generation_id', 'chunk_id'))
            if key in seen or item.tenant_id != scope.tenant_id or item.collection != request.collection or item.end_byte <= item.start_byte:
                raise ValueError()
            seen.add(key)
            result.append(item)
    except Exception:
        raise IntegrityViolation() from None
    return result


class PostgresCorrectiveBackend:
    def __init__(self, resource: PoolResource, *, mode: str = 'lexical',
                 embedder: EmbeddingAdapter | None = None, embedding_profile: EmbeddingProfile = FAKE_PROFILE, reranker: RerankingAdapter | None = None) -> None:
        if (type(mode) is not str or mode not in ('lexical', 'dense', 'hybrid')
                or (mode == 'lexical' and embedder is not None)
                or (mode != 'lexical' and not isinstance(embedder, EmbeddingAdapter))
                or (reranker is not None and not isinstance(reranker, RerankingAdapter))):
            raise InvalidRequest()
        selected = snapshot_profile(embedding_profile)
        self._session = PostgresSession(resource, embedding_profile=selected)
        self._mode, self._embedder, self._reranker = mode, embedder, reranker
        self._profile = profile_snapshot(embedder, selected) if embedder else None
        self._rerank_profile = RerankProfile.model_validate(reranker.profile.model_dump()) if reranker else None

    @property
    def result_versions(self) -> Mapping[str, str] | None:
        if self._profile is None or self._profile.provider == 'fake':
            return None
        return MappingProxyType(dict(model=self._profile.model,
            index='dense_openai.v1' if self._mode == 'dense' else 'hybrid_rrf.v1'))

    async def search(self, request: RetrievalRequest, *, scope: TrustedScope, deadline: float,
                     limit: int, ledger: ExecutionLedger) -> dict[str, Any]:
        request = parse_request(request.model_dump(mode='json'))
        scope = parse_scope(scope.model_dump(mode='json'))
        deadline = min(deadline, ledger.deadline)
        _check_deadline(deadline)
        if type(limit) is not int or not 1 <= limit <= request.limits.max_candidates:
            raise InvalidRequest()
        if self._mode == 'hybrid':
            minimum = 3 if extract_identifiers(request.query) else 2
            if request.limits.max_candidates < minimum:
                raise InvalidRequest()
            if limit < minimum:
                raise BudgetExhausted()
        wire = request.model_dump(mode='json')
        wire['limits']['max_candidates'] = limit
        bounded_request = parse_request(wire)
        if self._mode == 'lexical':
            async with self._session.transaction(bounded_request, scope=scope, deadline=deadline) as handle:
                candidates = await handle.lexical_candidates(limit=min(64, limit))
            return dict(candidates=_candidates(candidates, request, scope), degraded=False)
        assert self._embedder is not None and self._profile is not None
        live = self._profile.provider != 'fake'
        token = None
        settled = False
        if not live:
            token = ledger.reserve(provider_calls=1, cost_upper_usd=0)
            ledger.dispatch(token)
        def dispatch() -> None:
            nonlocal token
            token = ledger.reserve(provider_calls=1, cost_upper_usd=None)
            ledger.dispatch(token)
        def usage_reported(usage: EmbeddingUsage) -> None:
            nonlocal settled
            assert token is not None
            outputs = usage.total_tokens - usage.prompt_tokens if usage.total_tokens is not None and usage.prompt_tokens is not None else None
            settled = True
            ledger.reconcile(token, input_tokens=usage.prompt_tokens, output_tokens=outputs, cost_usd=None)
        try:
            candidates, degraded, tokens, _ = await select(self._session, bounded_request, scope, deadline,
                mode=self._mode, embedder=self._embedder, allow_degraded=False, identifiers=True,
                profile=profile_snapshot(self._embedder, self._profile),
                on_dispatch=dispatch if live else None, on_usage=usage_reported if live else None)
        except BaseException:
            if token is not None and not settled:
                ledger.abandon(token)
            raise
        if not live:
            assert token is not None
            ledger.reconcile(token, input_tokens=tokens, output_tokens=0, cost_usd=0)
        return dict(candidates=_candidates(candidates[:64], request, scope), degraded=degraded)

    async def capture(self, candidates: Any, *, request: RetrievalRequest, scope: TrustedScope,
                      deadline: float, max_source_bytes: int, ledger: ExecutionLedger) -> dict[str, Any]:
        request = parse_request(request.model_dump(mode='json'))
        scope = parse_scope(scope.model_dump(mode='json'))
        deadline = min(deadline, ledger.deadline)
        _check_deadline(deadline)
        if type(max_source_bytes) is not int or not 0 <= max_source_bytes <= 16_777_216:
            raise InvalidRequest()
        selected = _candidates(candidates, request, scope)
        loaded = 0
        stale = exhausted = False

        async def fetch(ordered: list[LexicalCandidate]) -> tuple[list[Any], list[Any], dict[str, LexicalCandidate]]:
            nonlocal loaded, stale, exhausted
            evidence, sources, mapping = [], [], {}
            source_map: dict[tuple[str, str, str], dict[str, str]] = {}
            if ordered and loaded == max_source_bytes:
                exhausted = True
            if ordered and loaded < max_source_bytes:
                async with self._session.transaction(request, scope=scope, deadline=deadline) as handle:
                    for candidate in ordered:
                        _check_deadline(deadline)
                        remaining = max_source_bytes - loaded
                        if remaining == 0:
                            exhausted = True
                            break
                        value = await handle.fetch_evidence(candidate, max_source_bytes=remaining, include_source=True)
                        if value.state == 'unavailable':
                            stale = True
                            continue
                        if value.state == 'budget_exhausted':
                            exhausted = True
                            break
                        if value.evidence is None or type(value.source_bytes) is not int or not 0 < value.source_bytes <= remaining:
                            raise IntegrityViolation()
                        loaded += value.source_bytes
                        stale = stale or value.stale
                        item = value.evidence.model_dump(mode='json')
                        if item['evidence_id'] in mapping:
                            raise IntegrityViolation()
                        evidence.append(item)
                        snapshot = value.source_snapshot()
                        source_key = (snapshot['collection'], snapshot['document_id'], snapshot['revision_id'])
                        if source_key in source_map:
                            if source_map[source_key] != snapshot:
                                raise IntegrityViolation()
                        else:
                            source_map[source_key] = snapshot
                            sources.append(snapshot)
                        mapping[item['evidence_id']] = candidate
            return evidence, sources, mapping

        evidence, sources, mapping = await fetch(selected[:40] if self._reranker else selected)
        if self._reranker and evidence:
            profile = self._rerank_profile
            assert profile is not None
            views = []
            size = len(request.query.encode('utf-8'))
            for item in evidence:
                raw = item['text'].encode('utf-8')
                view_size = len(raw[:16384].decode('utf-8', errors='ignore').encode('utf-8'))
                if size + view_size > 262144:
                    exhausted = True
                    continue
                size += view_size
                views.append(dict(candidate_id=item['evidence_id'], text=item['text']))
            if views:
                validation_views = copy.deepcopy(views)
                token = ledger.reserve(provider_calls=1, cost_upper_usd=0 if profile.provider == 'fake' else None)
                ledger.dispatch(token)
                try:
                    async with asyncio.timeout(max(0, deadline - asyncio.get_running_loop().time())):
                        ranked = await self._reranker.rank(request.query, views, deadline=deadline, max_provider_calls=1, allow_fallback=False)
                except TimeoutError:
                    ledger.abandon(token)
                    raise DeadlineExceeded() from None
                except BaseException:
                    ledger.abandon(token)
                    raise
                ledger.reconcile(token, input_tokens=0 if profile.provider == 'fake' else None,
                    output_tokens=0 if profile.provider == 'fake' else None, cost_usd=0 if profile.provider == 'fake' else None)
                ranked = _validated_rank(ranked, validation_views, profile)
                evidence, sources, _ = await fetch([mapping[key] for key in ranked['order']])
            else:
                evidence, sources = [], []
        _check_deadline(deadline)
        return dict(evidence=evidence, sources=sources, source_bytes=loaded, stale=stale, budget_exhausted=exhausted)


def _validated_rank(raw: Any, views: list[dict[str, str]], profile: RerankProfile) -> dict[str, Any]:
    """Validate overridden adapters as well as the built-in transport adapter."""
    nodes = 0
    ancestors: set[int] = set()
    def native(value: Any, depth: int = 0) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > 4096 or depth > 16:
            raise ValueError()
        if type(value) in (dict, list):
            if id(value) in ancestors or len(value) > 128:
                raise ValueError()
            ancestors.add(id(value))
            try:
                if type(value) is dict:
                    for key, child in value.items():
                        if type(key) is not str:
                            raise ValueError()
                        native(child, depth + 1)
                else:
                    for child in value:
                        native(child, depth + 1)
            finally:
                ancestors.remove(id(value))
        elif type(value) in (int, float):
            if not math.isfinite(value):
                raise ValueError()
        elif value is not None and type(value) not in (str, bool):
            raise ValueError()
    try:
        native(raw)
        if type(raw) is not dict or set(raw) != {'profile','order','scores','truncations','degraded','provider_calls','synthetic'}:
            raise ValueError()
        if (raw['profile'] != profile.model_dump() or type(raw['provider_calls']) is not int or raw['provider_calls'] != 1
                or raw['degraded'] is not False or type(raw['synthetic']) is not bool
                or raw['synthetic'] != (profile.provider == 'fake')):
            raise ValueError()
        ids = [view['candidate_id'] for view in views]
        order, scores = raw['order'], raw['scores']
        if (type(order) is not list or len(order) != len(ids) or any(type(key) is not str for key in order)
                or len(set(order)) != len(ids) or set(order) != set(ids)
                or type(scores) is not list or len(scores) != len(ids)):
            raise ValueError()
        values: dict[str, float] = {}
        for score in scores:
            if (type(score) is not dict or set(score) != {'candidate_id','raw_score'}
                    or type(score['candidate_id']) is not str or score['candidate_id'] not in ids
                    or score['candidate_id'] in values or type(score['raw_score']) not in (int,float)
                    or not math.isfinite(score['raw_score'])):
                raise ValueError()
            values[score['candidate_id']] = score['raw_score']
        expected_order = sorted(ids, key=lambda key: values[key], reverse=profile.score_direction == 'higher_is_better')
        if order != expected_order:
            raise ValueError()
        truncations = []
        for view in views:
            encoded = view['text'].encode('utf-8')
            if len(encoded) > 16384:
                truncations.append(dict(candidate_id=view['candidate_id'], original_bytes=len(encoded),
                    view_bytes=len(encoded[:16384].decode('utf-8', errors='ignore').encode('utf-8'))))
        if (truncations and profile.truncation_policy != 'utf8_prefix') or raw['truncations'] != truncations:
            raise ValueError()
        # Dict equality treats bool as int; require exact integer truncation fields.
        if type(raw['truncations']) is not list or any(type(row) is not dict or set(row) != {'candidate_id','original_bytes','view_bytes'}
                or type(row['candidate_id']) is not str or type(row['original_bytes']) is not int or type(row['view_bytes']) is not int
                for row in raw['truncations']):
            raise ValueError()
        return copy.deepcopy(raw)
    except Exception:
        raise IntegrityViolation() from None
