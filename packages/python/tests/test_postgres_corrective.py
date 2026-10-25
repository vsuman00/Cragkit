import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import pytest
from cragkit.contracts import parse_request, parse_scope
from cragkit.execution import ExecutionLedger
from cragkit.errors import IntegrityViolation
from cragkit.postgres_corrective import PostgresCorrectiveBackend
from cragkit._postgres_session import LexicalCandidate
from cragkit._postgres_source import verify_source


def setup():
    request = parse_request(dict(request_id='request', query='Café', collection='collection'))
    scope = parse_scope(dict(tenant_id='tenant', principal_id='principal', authorization_revision='auth', grant_ids=['grant']))
    text = 'Café🙂'
    digest = sha256(text.encode()).hexdigest()
    size = len(text.encode())
    candidate = LexicalCandidate(tenant_id='tenant', collection='collection', document_id='document', revision_id='revision', generation_id='generation', chunk_id='chunk', start_byte=0, end_byte=size, text_sha256=digest, score=1.0)
    rows = [('tenant','collection','document','revision','generation','chunk',digest,size,text,0,size,size,text,digest,'synthetic:source','native_fts.v1',True)]
    return request, scope, candidate, rows


class Session:
    def __init__(self, candidate, rows):
        self.candidate, self.rows = candidate, rows
        self.leases = 0
        self.fetches = 0
        self.limits = []
    @asynccontextmanager
    async def transaction(self, request, *, scope, deadline):
        self.leases += 1
        try:
            yield self
        finally:
            self.leases -= 1
    async def lexical_candidates(self, *, limit):
        self.limits.append(limit)
        return (self.candidate,)
    async def fetch_evidence(self, candidate, *, max_source_bytes, include_source):
        self.fetches += 1
        return verify_source(candidate, self.rows, max_source_bytes, include_source=include_source)


def test_lexical_fresh_capture_and_zero_provider_calls():
    async def scenario():
        request, scope, candidate, rows = setup()
        backend = PostgresCorrectiveBackend(object())
        session = Session(candidate, rows)
        backend._session = session
        deadline = asyncio.get_running_loop().time() + 2
        ledger = ExecutionLedger(request.limits, deadline=deadline)
        found = await backend.search(request, scope=scope, deadline=deadline, limit=2, ledger=ledger)
        assert found == dict(candidates=[candidate], degraded=False)
        assert session.limits == [2]
        first = await backend.capture(found['candidates'], request=request, scope=scope, deadline=deadline, max_source_bytes=100, ledger=ledger)
        assert first['sources'][0]['text'] == 'Café🙂'
        assert first['source_bytes'] == len('Café🙂'.encode())
        session.rows = []
        second = await backend.capture(found['candidates'], request=request, scope=scope, deadline=deadline, max_source_bytes=100, ledger=ledger)
        assert second['evidence'] == [] and second['stale']
        assert ledger.snapshot()['provider_calls'] == 0
        assert session.leases == 0
    asyncio.run(scenario())


def test_capture_budget_and_scope_injection_fail_closed():
    async def scenario():
        request, scope, candidate, rows = setup()
        backend = PostgresCorrectiveBackend(object())
        backend._session = Session(candidate, rows)
        deadline = asyncio.get_running_loop().time() + 2
        ledger = ExecutionLedger(request.limits, deadline=deadline)
        result = await backend.capture([candidate], request=request, scope=scope, deadline=deadline, max_source_bytes=0, ledger=ledger)
        assert result['budget_exhausted'] and result['source_bytes'] == 0
        forged = candidate.model_copy(update={'tenant_id':'other'})
        with pytest.raises(IntegrityViolation):
            await backend.capture([forged], request=request, scope=scope, deadline=deadline, max_source_bytes=100, ledger=ledger)
        assert backend._session.fetches == 0
    asyncio.run(scenario())


def test_dense_selection_reserves_call_and_divides_admitted_work(monkeypatch):
    from cragkit.embeddings import EmbeddingAdapter, FAKE_PROFILE
    import cragkit.postgres_corrective as module

    async def scenario():
        request, scope, candidate, _ = setup()
        # Selection is replaced at the existing boundary; no provider runs.
        class Embedder(EmbeddingAdapter):
            def __init__(self):
                self.profile = FAKE_PROFILE
        backend = PostgresCorrectiveBackend(object(), mode='hybrid', embedder=Embedder())
        deadline = asyncio.get_running_loop().time() + 2
        ledger = ExecutionLedger(request.limits, deadline=deadline)
        async def select(session, selected, selected_scope, selected_deadline, **kwargs):
            assert selected.limits.max_candidates == 3
            assert selected.required_filters == request.required_filters
            assert selected_scope == scope
            assert ledger.snapshot()['provider_calls'] == 1
            assert ledger.snapshot()['pending'] == 1
            assert kwargs['allow_degraded'] is False
            return (candidate,), False, 7, []
        monkeypatch.setattr(module, 'select', select)
        result = await backend.search(request, scope=scope, deadline=deadline, limit=3, ledger=ledger)
        assert result['candidates'] == [candidate]
        assert ledger.snapshot()['input_tokens'] == 7
        assert ledger.snapshot()['pending'] == 0
    asyncio.run(scenario())


def test_reranking_discloses_only_authorized_then_reauthorizes():
    from cragkit.reranking import RerankingAdapter, FAKE_RERANK_PROFILE

    async def scenario():
        request, scope, candidate, rows = setup()
        session = Session(candidate, rows)
        class Ranker(RerankingAdapter):
            def __init__(self):
                super().__init__(lambda *args, **kwargs: None)
            async def rank(self, query, views, **kwargs):
                assert session.leases == 0
                assert views[0]['text'] == 'Café🙂'
                session.rows = []
                return dict(profile=self.profile.model_dump(), order=[views[0]['candidate_id']], scores=[dict(candidate_id=views[0]['candidate_id'],raw_score=1.0)], truncations=[], degraded=False, provider_calls=1, synthetic=True)
        backend = PostgresCorrectiveBackend(object(), reranker=Ranker())
        backend._session = session
        deadline = asyncio.get_running_loop().time() + 2
        ledger = ExecutionLedger(request.limits, deadline=deadline)
        result = await backend.capture([candidate], request=request, scope=scope, deadline=deadline, max_source_bytes=100, ledger=ledger)
        assert result['evidence'] == [] and result['stale']
        assert session.fetches == 2
        assert ledger.snapshot()['provider_calls'] == 1
        assert ledger.snapshot()['cost_usd'] == 0
    asyncio.run(scenario())


@pytest.mark.parametrize('fault', ['scores', 'nonfinite', 'truncations', 'extra', 'cycle', 'duplicate', 'direction'])
def test_overridden_reranker_result_is_validated(fault):
    from cragkit.reranking import RerankingAdapter
    async def scenario():
        request, scope, candidate, rows = setup()
        session = Session(candidate, rows)
        class Ranker(RerankingAdapter):
            async def rank(self, query, views, **kwargs):
                key = views[0]['candidate_id']
                result = dict(profile=self.profile.model_dump(), order=[key], scores=[dict(candidate_id=key, raw_score=1.0)], truncations=[], degraded=False, provider_calls=1, synthetic=True)
                if fault == 'scores': result['scores'] = []
                if fault == 'nonfinite': result['scores'][0]['raw_score'] = float('nan')
                if fault == 'truncations': result['truncations'] = [dict(candidate_id=key, original_bytes=9, view_bytes=8)]
                if fault == 'extra': result['tenant_id'] = 'forged'
                if fault == 'cycle': result['scores'] = result
                if fault == 'duplicate': result['order'] = [key, key]
                if fault == 'direction': result['profile']['score_direction'] = 'lower_is_better'
                return result
        backend = PostgresCorrectiveBackend(object(), reranker=Ranker(lambda *args, **kwargs: None))
        backend._session = session
        deadline = asyncio.get_running_loop().time() + 2
        ledger = ExecutionLedger(request.limits, deadline=deadline)
        with pytest.raises(IntegrityViolation):
            await backend.capture([candidate], request=request, scope=scope, deadline=deadline, max_source_bytes=100, ledger=ledger)
        assert session.fetches == 1 and session.leases == 0
    asyncio.run(scenario())


def test_two_chunks_share_one_full_source_but_charge_each_fetch():
    async def scenario():
        request, scope, candidate, rows = setup()
        class MultiSession(Session):
            async def fetch_evidence(self, item, *, max_source_bytes, include_source):
                data = list(rows[0])
                data[5] = item.chunk_id
                return verify_source(item, [tuple(data)], max_source_bytes, include_source=True)
        backend = PostgresCorrectiveBackend(object())
        backend._session = MultiSession(candidate, rows)
        deadline = asyncio.get_running_loop().time() + 2
        ledger = ExecutionLedger(request.limits, deadline=deadline)
        second = candidate.model_copy(update={'chunk_id':'chunk-2'})
        result = await backend.capture([candidate, second], request=request, scope=scope, deadline=deadline, max_source_bytes=100, ledger=ledger)
        assert len(result['evidence']) == 2 and len(result['sources']) == 1
        assert result['source_bytes'] == 2 * len('Café🙂'.encode())
    asyncio.run(scenario())
