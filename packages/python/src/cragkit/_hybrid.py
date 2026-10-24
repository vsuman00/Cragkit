"""Internal bounded synthetic dense/hybrid selection."""
from __future__ import annotations

import asyncio
import math
from typing import Any

from pydantic import ValidationError

from ._fusion import fuse
from ._identifiers import extract_identifiers
from ._postgres_session import (DenseCandidate, IdentifierCandidate, LexicalCandidate,
                                PostgresSession, _check_deadline)
from .contracts import RetrievalRequest, TrustedScope
from .embeddings import EmbeddingAdapter, EmbeddingBatch, EmbeddingProfile, FAKE_PROFILE
from .errors import (DeadlineExceeded, EmbeddingProfileMismatch, IntegrityViolation,
                     InvalidRequest, ProviderUnavailable, UnsupportedCapability)


def profile_snapshot(embedder: EmbeddingAdapter) -> EmbeddingProfile:
    try:
        profile = EmbeddingProfile.model_validate(embedder.profile.model_dump())
    except Exception:
        raise InvalidRequest() from None
    if profile != FAKE_PROFILE:
        raise EmbeddingProfileMismatch()
    return profile


def validated_batch(value: object, profile: EmbeddingProfile) -> EmbeddingBatch:
    try:
        if type(value) is not EmbeddingBatch or type(value.provider_calls) is not int:
            raise ValueError()
        batch = EmbeddingBatch.model_validate(value.model_dump(warnings=False))
        usage = batch.usage
        if any(item is not None and (type(item) is not int or not 0 <= item <= 9_007_199_254_740_991)
               for item in (usage.prompt_tokens, usage.total_tokens)):
            raise ValueError()
        if (usage.prompt_tokens is not None and usage.total_tokens is not None
                and usage.total_tokens < usage.prompt_tokens):
            raise ValueError()
        if (batch.synthetic is not True or batch.provider_calls != 1 or usage.cost_kind != 'known'
                or usage.cost_usd is None or type(usage.cost_usd) not in (float, int) or not math.isfinite(usage.cost_usd)
                or usage.cost_usd != 0 or len(batch.vectors) != 1):
            raise ValueError()
        if batch.profile != profile or len(batch.vectors[0]) != profile.dimensions:
            raise EmbeddingProfileMismatch()
        vector = batch.vectors[0]
        norm = math.sqrt(sum(component * component for component in vector))
        if any(not math.isfinite(component) for component in vector) or not math.isfinite(norm) or abs(norm - 1) > .001:
            raise ValueError()
        return batch
    except EmbeddingProfileMismatch:
        raise
    except (ValidationError, ValueError, TypeError, AttributeError, OverflowError):
        raise InvalidRequest() from None


async def select(session: PostgresSession, request: RetrievalRequest, scope: TrustedScope,
                 deadline: float, *, mode: str, embedder: EmbeddingAdapter,
                 allow_degraded: bool, identifiers: bool,
                 profile: EmbeddingProfile) -> tuple[tuple[LexicalCandidate, ...], bool, int | None, list[dict[str, Any]]]:
    tokens = extract_identifiers(request.query) if mode == 'hybrid' and identifiers else ()
    families = ['dense'] if mode == 'dense' else ['dense', 'lexical'] + (['identifier'] if tokens else [])
    cap = min(request.limits.max_candidates, 200)
    if cap < len(families) or request.limits.max_provider_calls < 1:
        raise InvalidRequest()
    quotient, remainder = divmod(cap, len(families))
    budgets = {family: min(40, quotient + (index < remainder)) for index, family in enumerate(families)}
    stages: list[dict[str, Any]] = []
    failures = []
    batch = None
    started = asyncio.get_running_loop().time()
    try:
        try:
            async with asyncio.timeout(max(0, deadline - started)):
                raw = await embedder.embed_query(request.query, deadline=deadline)
        except TimeoutError:
            raise DeadlineExceeded() from None
        _check_deadline(deadline)
        batch = validated_batch(raw, profile)
        stages.append({'stage': 'embedding_complete', 'duration_ms': (asyncio.get_running_loop().time() - started) * 1000})
    except (ProviderUnavailable, UnsupportedCapability) as error:
        if not allow_degraded:
            raise
        failures.append(error)
        stages.append({'stage': 'embedding_failed_' + error.code, 'duration_ms': (asyncio.get_running_loop().time() - started) * 1000})
    lists = []
    async with session.transaction(request, scope=scope, deadline=deadline) as handle:
        for family in families:
            if family == 'dense' and batch is None:
                continue
            started = asyncio.get_running_loop().time()
            async def operation() -> tuple[LexicalCandidate, ...]:
                if family == 'dense':
                    return await handle.dense_candidates(batch, limit=budgets[family])
                if family == 'lexical':
                    return await handle.lexical_candidates(limit=budgets[family])
                return await handle.identifier_candidates(tokens[0], limit=budgets[family])
            try:
                candidates = await handle.candidate_branch(operation)
                _check_deadline(deadline)
                if len(candidates) > budgets[family]:
                    raise IntegrityViolation()
                lists.append({'list_id': family, 'facet_id': 'original', 'family': family,
                              'weight': 1.0, 'candidates': [item.model_dump(mode='json') for item in candidates]})
                stages.append({'stage': family + '_complete', 'duration_ms': (asyncio.get_running_loop().time() - started) * 1000})
            except (ProviderUnavailable, UnsupportedCapability) as error:
                if not allow_degraded or getattr(handle, '_branch_broken', False):
                    raise
                failures.append(error)
                stages.append({'stage': family + '_failed_' + error.code, 'duration_ms': (asyncio.get_running_loop().time() - started) * 1000})
    if not lists:
        raise failures[0]
    fused = fuse(lists, max_candidates=cap)
    candidates_out: list[LexicalCandidate] = []
    for item in fused[:65]:
        candidate = item['candidate']
        model = DenseCandidate if 'embedding_profile' in candidate else IdentifierCandidate if 'identifier_profile' in candidate else LexicalCandidate
        candidates_out.append(model.model_validate(candidate))
    return tuple(candidates_out), bool(failures), batch.usage.prompt_tokens if batch else None, stages
