import asyncio
from contextlib import asynccontextmanager
import hashlib
import json
from pathlib import Path

import pytest

from cragkit._postgres_session import LexicalCandidate
from cragkit._postgres_source import verify_source
from cragkit.contracts import parse_request, parse_scope
from cragkit.context import Cl100kCounter
from cragkit.errors import DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability
from cragkit.reranking import FAKE_RERANK_PROFILE, RerankingAdapter
from cragkit.retrieval import PostgresRetriever


def setup(**request_changes):
    text = 'Café 🙂 evidence'
    digest = hashlib.sha256(text.encode()).hexdigest()
    size = len(text.encode())
    candidate = LexicalCandidate(tenant_id='tenant', collection='docs', document_id='doc',
        revision_id='rev', generation_id='gen', chunk_id='chunk', start_byte=0,
        end_byte=size, text_sha256=digest, score=1.0)
    row = ('tenant', 'docs', 'doc', 'rev', 'gen', 'chunk', digest, size, text,
           0, size, size, text, digest, 'fixture', 'native_fts.v1', True)
    request = dict(request_id='request', query='Café', collection='docs',
        required_filters=[dict(op='eq', field='document_id', value='doc')],
        output_profile=dict(renderer='cragkit.context.v2', envelope_reserve_tokens=0))
    request.update(request_changes)
    scope = parse_scope(dict(tenant_id='tenant', principal_id='principal', authorization_revision='auth'))
    return Session(candidate, row), parse_request(request), scope


class Session:
    def __init__(self, candidate, row):
        self.candidate, self.row = candidate, row
        self.active = self.transactions = 0
        self.revoked = False
        self.fetches = []
        self.bound = []

    @asynccontextmanager
    async def transaction(self, request, *, scope, deadline):
        self.transactions += 1
        self.active += 1
        self.bound.append((request, scope))
        parent = self
        class Handle:
            async def lexical_candidates(self, *, limit): return (parent.candidate,)[:limit]
            async def fetch_evidence(self, candidate, *, max_source_bytes, include_source=False):
                assert include_source is True
                parent.fetches.append(max_source_bytes)
                return verify_source(candidate, [] if parent.revoked else [parent.row],
                                     max_source_bytes, include_source=include_source)
        try: yield Handle()
        finally: self.active -= 1


async def retrieve(session, request, scope, options):
    retriever = PostgresRetriever(None, evidence_options=options)
    retriever._session = session
    return await retriever.retrieve(request, scope=scope, deadline=asyncio.get_running_loop().time() + 2)


@pytest.mark.parametrize('allow_fallback', [False, True])
def test_unknown_reranker_failure_is_redacted_through_retrieval(allow_fallback):
    import traceback
    marker = 'private-reranker-orchestration-diagnostic'

    async def check():
        session, request, scope = setup()
        calls = 0

        async def failed(body, **kwargs):
            nonlocal calls
            calls += 1
            assert session.active == 0
            raise RuntimeError(marker) from ValueError(marker)

        with pytest.raises(ProviderUnavailable) as caught:
            await retrieve(session, request, scope, dict(
                reranker=RerankingAdapter(failed), rerank_fallback=allow_fallback))
        assert calls == 1 and session.active == 0
        assert str(caught.value) == 'Provider is unavailable.'
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        assert marker not in ''.join(traceback.format_exception(caught.value))
        assert all(bound_scope == scope and bound_request.required_filters == request.required_filters
                   for bound_request, bound_scope in session.bound)

    asyncio.run(check())


def test_fresh_post_model_authorization_no_held_lease_and_shared_source_budget():
    async def check():
        for revoke in [False, True]:
            session, request, scope = setup()
            async def transport(body, **kwargs):
                assert session.active == 0
                session.revoked = revoke
                return json.dumps([dict(candidate_id=row['candidate_id'], raw_score=1)
                                   for row in json.loads(body)['candidates']]).encode()
            adapter = RerankingAdapter(transport)
            result = await retrieve(session, request, scope, dict(reranker=adapter))
            assert session.active == 0 and session.transactions == 3
            assert session.fetches == [16777216, 16777216 - session.row[7]]
            assert all(bound_scope == scope and bound_request.required_filters == request.required_filters
                       for bound_request, bound_scope in session.bound)
            assert bool(result.evidence) is not revoke
            assert result.usage.provider_calls == 1 and result.usage.provider_input_tokens is None
            assert result.usage.provider_output_tokens is None and result.usage.cost_usd == 0
            assert result.versions.model == FAKE_RERANK_PROFILE.profile_id
            if revoke: assert 'stale_evidence' in [l.code for l in result.limitations]
    asyncio.run(check())


def test_policy_profile_budget_calls_and_live_spend_reject_before_effects():
    async def check():
        async def transport(*args, **kwargs): raise AssertionError('provider must not run')
        live_profile = FAKE_RERANK_PROFILE.model_copy(update=dict(provider='hosted'))
        cases = [
            (dict(limits=dict(max_provider_calls=0)), dict(reranker=RerankingAdapter(transport)), InvalidRequest),
            (dict(limits=dict(max_spend_usd=0)), dict(reranker=RerankingAdapter(transport, profile=live_profile, allow_live=True)), UnsupportedCapability),
            (dict(output_profile=dict(renderer='cragkit.context.v1')), {}, UnsupportedCapability),
            ({}, dict(policy=dict(policy_id='p', version='1', query_sha256='0' * 64, facets=[dict(
                facet_id='f', question='q', required=True, absence='unknown', anchors=[])])), InvalidRequest),
        ]
        for changes, options, error in cases:
            session, request, scope = setup(**changes)
            with pytest.raises(error): await retrieve(session, request, scope, options)
            assert session.transactions == 0
    asyncio.run(check())


def test_strict_counter_empty_envelope_and_budget_omission():
    async def check():
        pytest.importorskip('tiktoken')
        asset = Path(__file__).resolve().parents[3] / 'artifacts/tokenizers/cl100k_base.tiktoken'
        if not asset.exists(): pytest.skip('explicit tokenizer asset not provisioned')
        counter = Cl100kCounter.from_file(asset)
        session, request, scope = setup(limits=dict(max_context_tokens=1), output_profile=dict(
            renderer='cragkit.context.v2', counting_mode='strict', tokenizer='cl100k_base', envelope_reserve_tokens=0))
        result = await retrieve(session, request, scope, dict(counter=counter))
        assert result.context == '[]' and result.status == 'insufficient'
        assert result.usage.context_tokens == 1 and result.versions.tokenizer == 'cl100k_base'
        assert 'budget_exhausted' in [l.code for l in result.limitations]
    asyncio.run(check())


def test_recognized_fallback_visible_and_malformed_override_fatal():
    async def check():
        async def failed(*args, **kwargs): raise ProviderUnavailable()
        session, request, scope = setup()
        result = await retrieve(session, request, scope, dict(reranker=RerankingAdapter(failed), rerank_fallback=True))
        assert result.execution == 'degraded' and result.usage.provider_calls == 1
        assert 'degraded_search' in [l.code for l in result.limitations]
        class Malformed(RerankingAdapter):
            async def rank(self, *args, **kwargs): return {}
        session, request, scope = setup()
        with pytest.raises(IntegrityViolation):
            await retrieve(session, request, scope, dict(reranker=Malformed(failed)))
        assert session.transactions == 2 and session.active == 0
    asyncio.run(check())


def test_deadline_and_cancellation_bound_overridden_adapter():
    async def check():
        entered = asyncio.Event()
        class Slow(RerankingAdapter):
            async def rank(self, *args, **kwargs):
                entered.set()
                await asyncio.Event().wait()
        async def unused(*args, **kwargs): raise AssertionError()
        session, request, scope = setup(limits=dict(deadline_ms=10))
        with pytest.raises(DeadlineExceeded):
            await retrieve(session, request, scope, dict(reranker=Slow(unused)))
        assert session.active == 0
        session, request, scope = setup()
        entered.clear()
        task = asyncio.create_task(retrieve(session, request, scope, dict(reranker=Slow(unused))))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
        assert session.active == 0
    asyncio.run(check())


@pytest.mark.parametrize('options', [dict(extra=True), dict(rebalance=1), dict(rerank_limit=0),
                                    dict(rerank_limit=True), dict(rerank_limit=41), dict(policy=[]), dict(counter=object())])
def test_malformed_trusted_options(options):
    with pytest.raises(InvalidRequest): PostgresRetriever(None, evidence_options=options)


def test_large_seed_union_omits_whole_items_before_internal_renderer_boundary():
    async def check():
        text = 'x' * 32768
        digest = hashlib.sha256(text.encode()).hexdigest()
        session, request, scope = setup(limits=dict(max_context_tokens=1000000))
        candidates = [session.candidate.model_copy(update=dict(document_id=f'doc-{i}',
            start_byte=0,end_byte=len(text),text_sha256=digest)) for i in range(12)]
        @asynccontextmanager
        async def transaction(parsed, *, scope, deadline):
            class Handle:
                async def lexical_candidates(self, *, limit): return tuple(candidates[:limit])
                async def fetch_evidence(self, candidate, *, max_source_bytes, include_source=False):
                    row=('tenant','docs',candidate.document_id,'rev','gen','chunk',digest,len(text),text,
                         0,len(text),len(text),text,digest,'fixture','native_fts.v1',True)
                    return verify_source(candidate,[row],max_source_bytes,include_source=include_source)
            yield Handle()
        session.transaction=transaction
        result=await retrieve(session,request,scope,{})
        assert 0 < len(result.evidence) < 12
        assert len(result.context.encode()) <= 262144
        assert {'truncated_evidence','budget_exhausted'} <= {item.code for item in result.limitations}
    asyncio.run(check())


def test_reranker_finite_scores_above_safe_integer_range_remain_raw_scores():
    async def check():
        async def unused(*args, **kwargs): raise AssertionError()
        class WideScore(RerankingAdapter):
            async def rank(self, query, views, **kwargs):
                ids=[row['candidate_id'] for row in views]
                return dict(profile=self.profile.model_dump(),order=ids,
                    scores=[dict(candidate_id=ref,raw_score=1e100) for ref in reversed(ids)],
                    truncations=[],degraded=False,provider_calls=1,synthetic=True)
        session,request,scope=setup()
        result=await retrieve(session,request,scope,dict(reranker=WideScore(unused)))
        assert result.evidence and result.usage.provider_calls==1
    asyncio.run(check())
