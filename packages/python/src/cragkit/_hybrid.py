"""Internal bounded synthetic dense/hybrid selection."""
from __future__ import annotations

import asyncio
import math
from typing import Any, Callable

from pydantic import ValidationError

from ._fusion import fuse
from ._identifiers import extract_identifiers
from ._postgres_session import (DenseCandidate, IdentifierCandidate, LexicalCandidate,
                                PostgresSession, _check_deadline)
from .contracts import RetrievalRequest, TrustedScope
from .embeddings import EmbeddingAdapter, EmbeddingBatch, EmbeddingProfile, EmbeddingUsage, FAKE_PROFILE
from ._postgres_profiles import snapshot_profile
from .errors import (DeadlineExceeded, EmbeddingProfileMismatch, IntegrityViolation,
                     InvalidRequest, ProviderUnavailable, UnsupportedCapability)


def profile_snapshot(embedder: EmbeddingAdapter, selected: EmbeddingProfile = FAKE_PROFILE) -> EmbeddingProfile:
    try:
        profile = EmbeddingProfile.model_validate(embedder.profile.model_dump())
    except Exception:
        raise InvalidRequest() from None
    if profile != snapshot_profile(selected):
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
        if (batch.synthetic != (batch.profile.provider == 'fake') or batch.provider_calls != 1
                or len(batch.vectors) != 1
                or (usage.cost_usd is not None and (not math.isfinite(usage.cost_usd) or usage.cost_usd < 0))):
            raise ValueError()
        if batch.profile != profile or len(batch.vectors[0]) != profile.dimensions:
            raise EmbeddingProfileMismatch()
        if ((profile.provider == 'fake' and (usage.cost_kind != 'known' or usage.cost_usd != 0))
                or (profile.provider != 'fake' and usage.cost_kind not in ('estimated', 'unknown'))):
            raise ValueError()
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
                 profile: EmbeddingProfile, on_dispatch: Callable[[], None] | None = None,
                 on_usage: Callable[[EmbeddingUsage], None] | None = None,
                 observation: dict[str, Any] | None = None) -> tuple[tuple[LexicalCandidate, ...], bool, int | None, list[dict[str, Any]]]:
    live = profile.provider != 'fake'
    if live and request.limits.max_spend_usd is not None:
        raise UnsupportedCapability()
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
    calls = 0 if live else 1
    usage: EmbeddingUsage | None = None
    if live:
        # Fail incompatible storage before provider disclosure or fallback.
        await session.preauthorize_embedding(request, scope=scope, deadline=deadline)
    def dispatch() -> None:
        nonlocal calls
        if on_dispatch is not None:
            on_dispatch()
        calls += 1
    def observe() -> None:
        if observation is not None:
            prompt = usage.prompt_tokens if usage else (None if calls else 0)
            output = (usage.total_tokens - usage.prompt_tokens
                      if usage and usage.total_tokens is not None and usage.prompt_tokens is not None
                      else None if calls else 0)
            observation.update(provider_calls=calls, input_tokens=prompt, output_tokens=output if live else 0,
                cost_usd=None if live and calls else 0, cost_kind='unknown' if live and calls else 'known')
    observe()
    started = asyncio.get_running_loop().time()
    try:
        try:
            async with asyncio.timeout(max(0, deadline - started)):
                raw = await embedder.embed_query(request.query, deadline=deadline, on_dispatch=dispatch) if live else await embedder.embed_query(request.query, deadline=deadline)
        except TimeoutError:
            raise DeadlineExceeded() from None
        _check_deadline(deadline)
        batch = validated_batch(raw, profile)
        usage = batch.usage
        observe()
        if live and on_usage is not None:
            on_usage(usage)
        stages.append({'stage': 'embedding_complete', 'duration_ms': (asyncio.get_running_loop().time() - started) * 1000})
    except (ProviderUnavailable, UnsupportedCapability) as error:
        if not allow_degraded:
            raise
        observe()
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
