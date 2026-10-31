"""PGO-r1 orchestration with injected model bytes; no native live-quality claim."""
import asyncio
from contextlib import asynccontextmanager
import json
import time

import pytest

from cragkit.contracts import parse_request, parse_scope
from cragkit.embeddings import EmbeddingAdapter, EmbeddingPolicy, OPENAI_PROFILE
from cragkit.errors import ProviderUnavailable, UnsupportedCapability
from cragkit.execution import ExecutionLedger
from cragkit.postgres_corrective import PostgresCorrectiveBackend
from cragkit.retrieval import PostgresRetriever
from test_hybrid import Session


class Scoped(Session):
    def __init__(self, *, reject=False, failures=None):
        super().__init__(failures)
        self.preauthorized = 0
        self.active = False
        self.reject = reject
    async def preauthorize_embedding(self, request, *, scope, deadline):
        self.preauthorized += 1
        if self.reject:
            raise UnsupportedCapability()
    @asynccontextmanager
    async def transaction(self, *args, **kwargs):
        self.active = True
        try:
            async with super().transaction(*args, **kwargs) as handle:
                yield handle
        finally:
            self.active = False


class Counter:
    name = 'cl100k_base'
    def count(self, text):
        return 2


def setup(*, failure=False, allowed=True, reject=False, failures=None):
    session = Scoped(reject=reject, failures=failures)
    calls = []
    async def transport(body, **kwargs):
        assert session.preauthorized == 1 and not session.active
        calls.append(True)
        if failure:
            raise RuntimeError('private failure')
        return json.dumps(dict(model=OPENAI_PROFILE.model, data=[dict(index=0, embedding=[1.] + [0.]*1535)],
                               usage=dict(prompt_tokens=2, total_tokens=2))).encode()
    adapter = EmbeddingAdapter(transport, Counter(), profile=OPENAI_PROFILE,
        policy=EmbeddingPolicy(allow_live=allowed, max_cost_usd=.01, usd_per_million_tokens=.02))
    request = parse_request(dict(query='tiny', collection='docs'))
    scope = parse_scope(dict(tenant_id='tenant', principal_id='principal', authorization_revision='auth'))
    return session, calls, adapter, request, scope


def test_live_selection_metadata_and_no_transaction_during_model():
    async def run():
        session, calls, adapter, request, scope = setup()
        retriever = PostgresRetriever(object(), mode='dense', embedder=adapter, embedding_profile=OPENAI_PROFILE)
        retriever._session = session
        result = await retriever.retrieve(request, scope=scope, deadline=time.monotonic()+10)
        assert calls == [True] and session.preauthorized == 1
        assert result.versions.model == OPENAI_PROFILE.model and result.versions.index == 'dense_openai.v1'
        assert result.usage.provider_calls == 1 and result.usage.provider_input_tokens == 2
        assert result.usage.provider_output_tokens == 0
        assert result.usage.cost_usd is None and result.usage.cost_kind == 'unknown'
    asyncio.run(run())


def test_legacy_refusal_is_not_hidden_by_hybrid_fallback():
    async def run():
        session, calls, adapter, request, scope = setup(reject=True)
        retriever = PostgresRetriever(object(), mode='hybrid', embedder=adapter,
            embedding_profile=OPENAI_PROFILE, allow_degraded=True)
        retriever._session = session
        with pytest.raises(UnsupportedCapability):
            await retriever.retrieve(request, scope=scope, deadline=time.monotonic()+10)
        assert not calls and session.transactions == 0
    asyncio.run(run())


def test_dispatched_failure_is_counted_unknown_in_fallback():
    async def run():
        session, calls, adapter, request, scope = setup(failure=True)
        retriever = PostgresRetriever(object(), mode='hybrid', embedder=adapter,
            embedding_profile=OPENAI_PROFILE, allow_degraded=True)
        retriever._session = session
        result = await retriever.retrieve(request, scope=scope, deadline=time.monotonic()+10)
        assert calls == [True] and result.execution == 'degraded'
        assert result.usage.provider_calls == 1
        assert result.usage.provider_input_tokens is None and result.usage.provider_output_tokens is None
        assert result.usage.cost_kind == 'unknown' and result.usage.cost_usd is None
    asyncio.run(run())


@pytest.mark.parametrize('allowed,db_failure,expected_calls,expected_tokens', [(False,False,0,0),(True,True,1,2)])
def test_corrective_ledger_preserves_admission_and_reported_usage(allowed, db_failure, expected_calls, expected_tokens):
    async def run():
        session, calls, adapter, request, scope = setup(allowed=allowed,
            failures={'dense': ProviderUnavailable()} if db_failure else None)
        backend = PostgresCorrectiveBackend(object(), mode='dense', embedder=adapter, embedding_profile=OPENAI_PROFILE)
        backend._session = session
        deadline = time.monotonic()+10
        ledger = ExecutionLedger(request.limits, deadline=deadline)
        with pytest.raises((UnsupportedCapability, ProviderUnavailable)):
            await backend.search(request, scope=scope, deadline=deadline, limit=10, ledger=ledger)
        usage = ledger.snapshot()
        assert len(calls) == usage['provider_calls'] == expected_calls
        assert usage['input_tokens'] == expected_tokens and usage['pending'] == 0
        assert usage['cost_kind'] == ('unknown' if expected_calls else 'known')
    asyncio.run(run())


def test_corrective_versions_snapshot_uses_existing_validated_fields():
    from cragkit.corrective import CorrectiveRetriever
    from cragkit.errors import InvalidRequest
    class Backend:
        result_versions = dict(model=OPENAI_PROFILE.model, index='dense_openai.v1')
        async def search(self, *args, **kwargs):
            return dict(candidates=[], degraded=False)
        async def capture(self, *args, **kwargs):
            return dict(evidence=[], sources=[], stale=False)
    backend = Backend()
    retriever = CorrectiveRetriever(backend)
    backend.result_versions['model'] = 'changed'
    assert retriever._backend_versions.model == OPENAI_PROFILE.model
    backend.result_versions = dict(model=12, index='dense_openai.v1')
    with pytest.raises(InvalidRequest):
        CorrectiveRetriever(backend)
    del Backend.result_versions
    backend.result_versions = None
    assert CorrectiveRetriever(backend)._backend_versions.model is None


def test_reported_usage_survives_reconcile_error_without_masking_typed_failure():
    from cragkit.errors import IntegrityViolation
    class ReconcileFailure(ExecutionLedger):
        def reconcile(self, token, **usage):
            super().reconcile(token, **usage)
            raise IntegrityViolation()
    async def run():
        session, _, adapter, request, scope = setup()
        backend = PostgresCorrectiveBackend(object(), mode='dense', embedder=adapter, embedding_profile=OPENAI_PROFILE)
        backend._session = session
        deadline = time.monotonic()+10
        ledger = ReconcileFailure(request.limits, deadline=deadline)
        with pytest.raises(IntegrityViolation):
            await backend.search(request, scope=scope, deadline=deadline, limit=10, ledger=ledger)
        assert ledger.snapshot()['input_tokens'] == 2
        assert ledger.snapshot()['provider_calls'] == 1
        assert ledger.snapshot()['pending'] == 0
    asyncio.run(run())


@pytest.mark.parametrize('actual_is_fake', [True, False])
def test_valid_wrong_profile_batch_is_profile_mismatch(actual_is_fake):
    from cragkit._hybrid import validated_batch
    from cragkit.embeddings import EmbeddingBatch, EmbeddingUsage, FAKE_PROFILE
    from cragkit.errors import EmbeddingProfileMismatch, InvalidRequest
    actual, selected = (FAKE_PROFILE, OPENAI_PROFILE) if actual_is_fake else (OPENAI_PROFILE, FAKE_PROFILE)
    batch = EmbeddingBatch(profile=actual, vectors=((1.,)+(0.,)*1535,), synthetic=actual_is_fake,
        usage=EmbeddingUsage(prompt_tokens=1, total_tokens=1, cost_usd=0 if actual_is_fake else None,
                             cost_kind='known' if actual_is_fake else 'unknown'))
    with pytest.raises(EmbeddingProfileMismatch):
        validated_batch(batch, selected)
    with pytest.raises(InvalidRequest):
        validated_batch(batch.model_copy(update={'synthetic': not actual_is_fake}), selected)
