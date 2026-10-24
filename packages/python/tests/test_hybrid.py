import asyncio
from contextlib import asynccontextmanager

import pytest

from cragkit.contracts import parse_request, parse_scope
from cragkit.embeddings import EmbeddingAdapter, EmbeddingBatch, EmbeddingUsage, FAKE_PROFILE, OPENAI_PROFILE
from cragkit.errors import EmbeddingProfileMismatch, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope
from cragkit.retrieval import PostgresRetriever


class Embedder(EmbeddingAdapter):
    def __init__(self, failure=None, usage=None):
        self.profile = FAKE_PROFILE
        self.calls = 0
        self.failure = failure
        self.usage = usage or EmbeddingUsage(prompt_tokens=3, total_tokens=3, cost_usd=0., cost_kind='known')
    async def embed_query(self, text, *, deadline):
        self.calls += 1
        if self.failure:
            raise self.failure
        return EmbeddingBatch(profile=self.profile, vectors=((1.,) + (0.,) * 1535,), usage=self.usage, synthetic=True)


class Session:
    def __init__(self, failures=None):
        self.transactions = 0
        self.calls = []
        self.failures = failures or {}
    @asynccontextmanager
    async def transaction(self, request, *, scope, deadline):
        self.transactions += 1
        parent = self
        class Handle:
            async def candidate_branch(self, operation):
                return await operation()
            async def dense_candidates(self, batch, *, limit):
                return self.run('dense', limit)
            async def lexical_candidates(self, *, limit):
                return self.run('lexical', limit)
            async def identifier_candidates(self, token, *, limit):
                parent.token = token
                return self.run('identifier', limit)
            def run(self, family, limit):
                parent.calls.append((family, limit))
                if family in parent.failures:
                    raise parent.failures[family]
                return ()
        yield Handle()


def run(*, mode='hybrid', degraded=False, embedder=None, session=None, limits=None):
    async def scenario():
        adapter = embedder or Embedder()
        fake = session or Session()
        retriever = PostgresRetriever(None, mode=mode, embedder=adapter, allow_degraded=degraded)
        retriever._session = fake
        result = await retriever.retrieve(parse_request({'query': 'ERR_CONN-42 x.y', 'collection': 'docs', 'limits': limits or {}}),
            scope=parse_scope({'tenant_id': 'tenant', 'principal_id': 'person', 'authorization_revision': 'a'}),
            deadline=asyncio.get_running_loop().time()+2)
        return result, adapter, fake
    return asyncio.run(scenario())


@pytest.mark.parametrize('options', [dict(mode='other'), dict(mode=True), dict(identifiers=1),
    dict(allow_degraded=1), dict(embedder=Embedder()), dict(mode='dense'),
    dict(mode='dense', embedder=Embedder(), allow_degraded=True)])
def test_invalid_trusted_configuration(options):
    with pytest.raises(InvalidRequest):
        PostgresRetriever(None, **options)


def test_hybrid_order_budgets_accounting_and_unknown_coverage():
    result, adapter, session = run(limits={'max_candidates': 8})
    assert session.calls == [('dense', 3), ('lexical', 3), ('identifier', 2)]
    assert session.token == 'ERR_CONN-42' and adapter.calls == 1 and session.transactions == 1
    assert result.status == 'insufficient' and result.execution == 'complete'
    assert result.usage.provider_calls == 1 and result.usage.provider_input_tokens == 3
    assert result.usage.provider_output_tokens == 0 and result.usage.cost_usd == 0
    assert result.versions.index == 'hybrid_rrf.v1'
    assert [stage.stage for stage in result.usage.stage_durations] == ['embedding_complete', 'dense_complete', 'lexical_complete', 'identifier_complete']
    assert [item.code for item in result.limitations] == ['coverage_unknown']


def test_dense_has_one_bounded_family():
    result, _, session = run(mode='dense', limits={'max_candidates': 100})
    assert session.calls == [('dense', 40)] and result.versions.index == 'dense_fake.v1'


@pytest.mark.parametrize('limits', [{'max_candidates': 2}, {'max_provider_calls': 0}])
def test_limits_fail_before_embedding_and_lease(limits):
    adapter = Embedder(); session = Session()
    with pytest.raises(InvalidRequest):
        run(embedder=adapter, session=session, limits=limits)
    assert adapter.calls == session.transactions == 0


def test_unprovisioned_profile_is_preprovider_and_prelease():
    adapter = Embedder(); adapter.profile = OPENAI_PROFILE; session = Session()
    with pytest.raises(EmbeddingProfileMismatch): run(embedder=adapter, session=session)
    assert adapter.calls == session.transactions == 0


def test_explicit_embedding_fallback_keeps_planned_budgets():
    result, _, session = run(degraded=True, embedder=Embedder(ProviderUnavailable()), limits={'max_candidates': 8})
    assert session.calls == [('lexical', 3), ('identifier', 2)]
    assert result.execution == 'degraded' and result.usage.provider_input_tokens is None
    assert 'degraded_search' in [item.code for item in result.limitations]


def test_empty_success_is_preserved_but_all_failed_raises():
    result, _, _ = run(degraded=True, session=Session({'dense': ProviderUnavailable(), 'identifier': ProviderUnavailable()}))
    assert result.execution == 'degraded'
    with pytest.raises(ProviderUnavailable):
        run(degraded=True, session=Session({name: ProviderUnavailable() for name in ('dense', 'lexical', 'identifier')}))


@pytest.mark.parametrize('degraded', [False, True])
def test_fatal_scope_failures_never_recover(degraded):
    with pytest.raises(UnauthorizedScope): run(degraded=degraded, session=Session({'dense': UnauthorizedScope()}))


def test_default_fail_closed_and_malformed_usage_is_fatal():
    with pytest.raises(ProviderUnavailable): run(embedder=Embedder(ProviderUnavailable()))
    with pytest.raises(InvalidRequest):
        run(degraded=True, embedder=Embedder(usage=EmbeddingUsage(prompt_tokens=-1, total_tokens=0, cost_usd=0., cost_kind='known')))


def test_provider_ignoring_deadline_is_bounded_without_fallback():
    from cragkit.errors import DeadlineExceeded
    class Slow(Embedder):
        async def embed_query(self, text, *, deadline):
            await asyncio.sleep(.03)
            return await super().embed_query(text, deadline=deadline)
    session = Session()
    with pytest.raises(DeadlineExceeded):
        run(degraded=True, embedder=Slow(), session=session, limits={'deadline_ms':1})
    assert session.transactions == 0


@pytest.mark.parametrize('failure', [IntegrityViolation(), UnauthorizedScope()])
def test_fatal_branch_failures_remain_fatal(failure):
    with pytest.raises(type(failure)):
        run(degraded=True, session=Session({'lexical':failure}))


def test_source_operational_failure_is_not_a_search_fallback():
    from cragkit._postgres_session import DenseCandidate
    from hashlib import sha256
    class Sources(Session):
        @asynccontextmanager
        async def transaction(self, *args, **kwargs):
            async with super().transaction(*args, **kwargs) as handle:
                async def dense(batch, *, limit):
                    return (DenseCandidate(tenant_id='tenant',collection='docs',document_id='doc',revision_id='rev',
                        generation_id='generation',chunk_id='chunk',start_byte=0,end_byte=4,
                        text_sha256=sha256(b'text').hexdigest(),score=0.),)
                async def source(*args, **kwargs): raise ProviderUnavailable()
                handle.dense_candidates=dense
                handle.fetch_evidence=source
                yield handle
    with pytest.raises(ProviderUnavailable): run(degraded=True,session=Sources())
