"""Branch-capacity admission must precede every provider/DB dispatch."""
import asyncio
from hashlib import sha256

import pytest

from cragkit.contracts import parse_request, parse_scope
from cragkit.corrective import CorrectiveRetriever
from cragkit.embeddings import EmbeddingAdapter, FAKE_PROFILE
from cragkit.errors import InvalidRequest
from cragkit.execution import BudgetExhausted, ExecutionLedger
from cragkit.planning import PlannerAdapter
from cragkit.postgres_corrective import PostgresCorrectiveBackend

SCOPE = parse_scope(dict(tenant_id='t', principal_id='reader', authorization_revision='acl'))


def forbidden_backend():
    counts = dict(embeddings=0, sessions=0)

    class Embedder(EmbeddingAdapter):
        def __init__(self):
            self.profile = FAKE_PROFILE

        async def embed_query(self, *args, **kwargs):
            counts['embeddings'] += 1
            raise AssertionError('unexpected model call')

    class Session:
        def transaction(self, *args, **kwargs):
            counts['sessions'] += 1
            raise AssertionError('unexpected database lease')

    backend = PostgresCorrectiveBackend(object(), mode='hybrid', embedder=Embedder())
    backend._session = Session()
    return backend, counts


@pytest.mark.parametrize('query,minimum', [('ordinary query', 2), ('API-42 query', 3)])
def test_original_hybrid_request_below_branch_floor_is_invalid_without_dispatch(query, minimum):
    async def scenario():
        backend, counts = forbidden_backend()
        request = parse_request(dict(query=query, collection='c', limits=dict(max_candidates=minimum - 1)))
        deadline = asyncio.get_running_loop().time() + 1
        ledger = ExecutionLedger(request.limits, deadline=deadline)
        with pytest.raises(InvalidRequest):
            await backend.search(request, scope=SCOPE, deadline=deadline, ledger=ledger, limit=minimum - 1)
        assert counts == dict(embeddings=0, sessions=0)
        assert ledger.snapshot()['provider_calls'] == 0
        assert ledger.snapshot()['pending'] == 0
    asyncio.run(scenario())


@pytest.mark.parametrize('query,limit', [('ordinary query', 1), ('API-42 query', 1), ('API-42 query', 2)])
def test_remaining_hybrid_work_below_branch_floor_exhausts_budget_before_dispatch(query, limit):
    async def scenario():
        backend, counts = forbidden_backend()
        request = parse_request(dict(query=query, collection='c', limits=dict(max_candidates=5)))
        deadline = asyncio.get_running_loop().time() + 1
        ledger = ExecutionLedger(request.limits, deadline=deadline)
        previous = ledger.reserve(candidates=5 - limit)
        ledger.dispatch(previous)
        ledger.reconcile(previous)
        with pytest.raises(BudgetExhausted):
            await backend.search(request, scope=SCOPE, deadline=deadline, ledger=ledger, limit=limit)
        assert counts == dict(embeddings=0, sessions=0)
        snapshot = ledger.snapshot()
        assert snapshot['provider_calls'] == 0 and snapshot['cost_usd'] == 0
        assert snapshot['pending'] == 0 and snapshot['candidates'] == 5 - limit
    asyncio.run(scenario())


def test_core_keeps_fresh_useful_evidence_when_targeted_hybrid_branches_cannot_fit():
    async def scenario():
        query, text = 'API-42 query', 'Known retry count.'
        digest, size = sha256(text.encode()).hexdigest(), len(text.encode())
        limited, counts = forbidden_backend()
        candidate = dict(tenant_id='t', collection='c', document_id='d', revision_id='r', generation_id='g',
                         chunk_id='chunk', start_byte=0, end_byte=size, text_sha256=digest, score=1)
        evidence = dict(evidence_id='e', collection='c', document_id='d', revision_id='r', chunk_id='chunk',
                        source_locator='source:d', start_byte=0, end_byte=size, text=text,
                        source_sha256=digest, text_sha256=digest)
        source = dict(collection='c', document_id='d', revision_id='r', source_sha256=digest, text=text)
        policy = dict(policy_id='reviewed', version='1', query_sha256=sha256(query.encode()).hexdigest(), facets=[
            dict(facet_id='known', question='Known count?', required=True, absence='missing', anchors=[dict(
                claim_id='a', collection='c', document_id='d', revision_id='r', source_sha256=digest,
                start_byte=0, end_byte=size, text=text)]),
            dict(facet_id='missing', question='Missing delay?', required=True, absence='missing', anchors=[])])
        calls = dict(searches=0, captures=0)

        class Bridge:
            async def search(self, request, **options):
                calls['searches'] += 1
                if calls['searches'] == 1:
                    return dict(candidates=[candidate], degraded=False)
                assert options['limit'] == 1
                return await limited.search(request, **options)

            async def capture(self, candidates, **options):
                calls['captures'] += 1
                return dict(evidence=[evidence], sources=[source], source_bytes=size,
                            stale=False, budget_exhausted=False)

        async def plan(payload, *, deadline):
            return dict(plan=dict(queries=[dict(facet_id='missing', variant_id='v')]),
                        usage=dict(input_tokens=0, output_tokens=0, cost_usd=0))

        output = await CorrectiveRetriever(Bridge(), policy=policy,
            variants=[dict(facet_id='missing', variant_id='v', query='API-42 delay')],
            planner=PlannerAdapter(plan, cost_upper_usd=0), batch_size=4).retrieve(
                dict(query=query, collection='c', limits=dict(max_candidates=5),
                     output_profile=dict(renderer='cragkit.context.v2')),
                scope=SCOPE, deadline=asyncio.get_running_loop().time() + 1)
        assert output['diagnostics']['stop_reason'] == 'budget_exhausted'
        assert output['result']['status'] == 'partial' and output['result']['evidence'][0]['text'] == text
        assert output['diagnostics']['candidate_work'] == 5
        assert output['result']['usage']['provider_calls'] == 1 and output['result']['usage']['cost_usd'] == 0
        assert calls == dict(searches=2, captures=3)
        assert counts == dict(embeddings=0, sessions=0)
    asyncio.run(scenario())
