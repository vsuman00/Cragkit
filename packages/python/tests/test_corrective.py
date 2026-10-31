import asyncio
import copy
import hashlib

import pytest

from cragkit.corrective import CorrectiveRetriever
from cragkit.errors import DeadlineExceeded, IntegrityViolation, UnsupportedCapability
from cragkit.planning import PlannerAdapter


def fixture(name, text):
    digest = hashlib.sha256(text.encode()).hexdigest()
    source = dict(collection='c', document_id=name, revision_id='r', text=text, source_sha256=digest)
    evidence = dict(**source, evidence_id=name, chunk_id=name, source_locator='fixture', start_byte=0,
                    end_byte=len(text.encode()), text_sha256=digest)
    candidate = dict(tenant_id='t', collection='c', document_id=name, revision_id='r', generation_id='g',
                     chunk_id=name, start_byte=0, end_byte=len(text.encode()), text_sha256=digest, score=1.0)
    return candidate, evidence, source


A, B = fixture('a', 'first fact'), fixture('b', 'second fact')
SCOPE = dict(tenant_id='t', principal_id='p', authorization_revision='1')
REQUEST = dict(request_id='req', query='question', collection='c',
               output_profile=dict(renderer='cragkit.context.v2', envelope_reserve_tokens=0))


def test_native_backend_candidate_accounting_is_charged_once():
    class Charged(Backend):
        candidate_accounting='backend'
        async def search(self,request,*,scope,deadline,limit,ledger):
            token=ledger.reserve(candidates=limit);ledger.dispatch(token);ledger.reconcile(token)
            return await super().search(request,scope=scope,deadline=deadline,limit=limit,ledger=ledger)
    async def scenario():
        backend=Charged();engine=CorrectiveRetriever(backend,batch_size=1)
        result=await engine.retrieve(dict(REQUEST,limits=dict(max_candidates=1,max_attempts=1)),scope=SCOPE,
            deadline=asyncio.get_running_loop().time()+2)
        assert result['diagnostics']['candidate_work']==1
        assert result['result']['evidence']
    asyncio.run(scenario())


def test_backend_candidate_undercharge_fails_integrity():
    class Uncharged(Backend):candidate_accounting='backend'
    async def scenario():
        with pytest.raises(IntegrityViolation):
            await CorrectiveRetriever(Uncharged(),batch_size=1).retrieve(REQUEST,scope=SCOPE,
                deadline=asyncio.get_running_loop().time()+2)
    asyncio.run(scenario())


def test_backend_accounting_snapshot_preserves_retry_charges():
    from cragkit.errors import ProviderUnavailable,InvalidRequest
    class Charged(Backend):
        candidate_accounting='backend'
        attempts=0
        async def search(self,request,*,scope,deadline,limit,ledger):
            token=ledger.reserve(candidates=limit);ledger.dispatch(token);ledger.reconcile(token)
            self.attempts+=1
            if self.attempts==1:raise ProviderUnavailable()
            return await super().search(request,scope=scope,deadline=deadline,limit=limit,ledger=ledger)
    async def scenario():
        backend=Charged();engine=CorrectiveRetriever(backend,batch_size=1,max_retries=1)
        backend.candidate_accounting='outer'
        result=await engine.retrieve(dict(REQUEST,limits=dict(max_candidates=2,max_attempts=2)),scope=SCOPE,
            deadline=asyncio.get_running_loop().time()+2)
        assert result['diagnostics']['candidate_work']==2 and backend.attempts==2
        assert result['result']['evidence']
    asyncio.run(scenario())
    for invalid in ('invalid',None,True):
        backend=Backend();backend.candidate_accounting=invalid
        with pytest.raises(InvalidRequest):CorrectiveRetriever(backend)


def policy():
    facets = []
    for name, item in [('first', A[1]), ('second', B[1])]:
        anchor = {key: item[key] for key in ('collection', 'document_id', 'revision_id', 'source_sha256', 'start_byte', 'end_byte', 'text')}
        facets.append(dict(facet_id=name, question=name, required=True, absence='missing', anchors=[dict(claim_id=name, **anchor)]))
    return dict(policy_id='review', version='1', query_sha256=hashlib.sha256(b'question').hexdigest(), facets=facets)


class Backend:
    def __init__(self):
        self.calls = []
        self.captures = 0
        self.revoke = False
    async def search(self, request, *, scope, deadline, limit, ledger):
        self.calls.append((request.model_dump(mode='json'), scope.model_dump(mode='json'), limit))
        return {'candidates': [copy.deepcopy(A[0] if len(self.calls) == 1 else B[0])], 'degraded': False}
    async def capture(self, candidates, *, request, scope, deadline, max_source_bytes, ledger):
        self.captures += 1
        rows = [row for row in (A, B) if any(c.document_id == row[0]['document_id'] for c in candidates)]
        if self.revoke and self.captures > 1:
            rows = [row for row in rows if row[0]['document_id'] != 'a']
        return dict(evidence=[copy.deepcopy(row[1]) for row in rows], sources=[copy.deepcopy(row[2]) for row in rows],
                    source_bytes=sum(len(row[2]['text'].encode()) for row in rows), stale=self.revoke and self.captures > 1,
                    budget_exhausted=False)


async def planner(payload, *, deadline):
    return dict(plan={'queries': [{'facet_id': 'second', 'variant_id': 'v'}]},
                usage=dict(input_tokens=1, output_tokens=1, cost_usd=0))


def retriever(backend, **extra):
    return CorrectiveRetriever(backend, policy=policy(), planner=PlannerAdapter(planner),
        variants=[dict(facet_id='second', variant_id='v', query='targeted question')], **extra)


def run(retriever, request=REQUEST):
    async def scenario():
        return await retriever.retrieve(request, scope=SCOPE, deadline=asyncio.get_running_loop().time() + 1)
    return asyncio.run(scenario())


def test_targeted_recovery_retains_and_reassesses_original_question():
    backend = Backend()
    output = run(retriever(backend))
    assert output['result']['status'] == 'sufficient'
    assert {item['document_id'] for item in output['result']['evidence']} == {'a', 'b'}
    assert output['diagnostics']['queries_executed'] == 2
    assert output['diagnostics']['ledger']['attempts'] == 2
    assert output['diagnostics']['candidate_work'] == 32
    assert backend.captures == 3
    assert backend.calls[0][0]['query'] == 'question' and backend.calls[1][0]['query'] == 'targeted question'
    assert backend.calls[0][1] == backend.calls[1][1] == dict(SCOPE, grant_ids=[])
    assert 'question' not in str(output['diagnostics'])


def test_fresh_capture_revocation_removes_earlier_support():
    backend = Backend()
    backend.revoke = True
    output = run(retriever(backend))
    assert output['result']['status'] == 'partial'
    assert [item['document_id'] for item in output['result']['evidence']] == ['b']
    assert {'code': 'stale_evidence', 'facet_ids': [], 'evidence_ids': []} in output['result']['limitations']


def test_unknown_policy_stops_without_planning_and_strict_preflight():
    backend = Backend()
    output = run(CorrectiveRetriever(backend))
    assert output['diagnostics']['stop_reason'] == 'coverage_unknown'
    assert len(backend.calls) == 1
    request = copy.deepcopy(REQUEST)
    request['output_profile'].update(counting_mode='strict', tokenizer='cl100k_base')
    backend = Backend()
    with pytest.raises(UnsupportedCapability):
        run(CorrectiveRetriever(backend), request)
    assert backend.calls == []


def test_budget_stop_before_planning_preserves_fresh_evidence_and_limitation():
    backend = Backend()
    request = dict(REQUEST, limits={'max_candidates': 16})
    output = run(retriever(backend), request)
    assert output['diagnostics']['stop_reason'] == 'budget_exhausted'
    assert backend.captures == 1
    assert any(item['code'] == 'budget_exhausted' for item in output['result']['limitations'])


def test_malformed_candidate_and_source_membership_fail_closed():
    class Wrong(Backend):
        async def search(self, request, **options):
            return {'candidates': [dict(A[0], tenant_id='other')], 'degraded': False}
    with pytest.raises(IntegrityViolation):
        run(CorrectiveRetriever(Wrong()))
    class WrongSource(Backend):
        async def capture(self, candidates, **options):
            return dict(evidence=[B[1]], sources=[B[2]], source_bytes=len(B[2]['text']), stale=False, budget_exhausted=False)
    with pytest.raises(IntegrityViolation):
        run(CorrectiveRetriever(WrongSource()))


def test_backend_ignoring_deadline_is_bounded():
    class Slow(Backend):
        async def search(self, request, **options):
            await asyncio.Event().wait()
    request = dict(REQUEST, limits={'deadline_ms': 1})
    with pytest.raises(DeadlineExceeded):
        run(CorrectiveRetriever(Slow()), request)


def test_late_backend_cannot_dispatch_after_cancellation():
    async def scenario():
        started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
        blocked = []
        class Ignores(Backend):
            async def search(self, request, *, scope, deadline, limit, ledger):
                started.set()
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
                try:
                    ledger.reserve(provider_calls=1)
                except Exception as error:
                    blocked.append(error)
                finally:
                    finished.set()
                return {'candidates': [], 'degraded': False}
        retriever = CorrectiveRetriever(Ignores())
        task = asyncio.create_task(retriever.retrieve(REQUEST, scope=SCOPE,
                                  deadline=asyncio.get_running_loop().time() + 1))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        await finished.wait()
        from cragkit.errors import InvalidRequest
        assert len(blocked) == 1 and isinstance(blocked[0], InvalidRequest)
    asyncio.run(scenario())


def test_normalized_query_repeat_stops_before_backend_dispatch():
    async def repeated(payload, *, deadline):
        return dict(plan={'queries': [{'facet_id': 'second', 'variant_id': 'same'}]},
                    usage=dict(input_tokens=0, output_tokens=0, cost_usd=0))
    backend = Backend()
    core = CorrectiveRetriever(backend, policy=policy(), planner=PlannerAdapter(repeated),
        variants=[dict(facet_id='second', variant_id='same', query='  QUESTION\t')])
    output = run(core)
    assert output['diagnostics']['stop_reason'] == 'repeated_query'
    assert len(backend.calls) == 1
    assert output['result']['status'] == 'partial'


def test_identical_candidate_set_recaptures_before_stop():
    class Repeated(Backend):
        async def search(self, request, **options):
            self.calls.append(request)
            return {'candidates': [A[0]], 'degraded': False}
    backend = Repeated()
    backend.revoke = True
    output = run(retriever(backend))
    assert output['diagnostics']['stop_reason'] == 'repeated_candidates'
    assert backend.captures == 3
    assert output['result']['evidence'] == []
    assert output['result']['status'] == 'insufficient'


def test_no_progress_distinct_candidates_stop_after_configured_rounds():
    extra = [fixture('unused1', 'unreviewed one'), fixture('unused2', 'unreviewed two')]
    class Unhelpful(Backend):
        async def search(self, request, **options):
            self.calls.append(request)
            return {'candidates': [(A, *extra)[len(self.calls) - 1][0]], 'degraded': False}
        async def capture(self, candidates, **options):
            self.captures += 1
            rows = [row for row in (A, *extra) if any(c.document_id == row[0]['document_id'] for c in candidates)]
            return dict(evidence=[row[1] for row in rows], sources=[row[2] for row in rows],
                        source_bytes=sum(len(row[2]['text']) for row in rows), stale=False, budget_exhausted=False)
    async def selected(payload, *, deadline):
        return dict(plan={'queries': [{'facet_id': 'second', 'variant_id': 'v1'}, {'facet_id': 'second', 'variant_id': 'v2'}]},
                    usage=dict(input_tokens=0, output_tokens=0, cost_usd=0))
    backend = Unhelpful()
    core = CorrectiveRetriever(backend, policy=policy(), planner=PlannerAdapter(selected), no_progress_limit=2,
        variants=[dict(facet_id='second', variant_id='v1', query='first alternative'),
                  dict(facet_id='second', variant_id='v2', query='second alternative')])
    output = run(core)
    assert output['diagnostics']['stop_reason'] == 'no_progress'
    assert output['diagnostics']['queries_executed'] == 3
    assert backend.captures == 4


def test_transient_retry_charges_attempts_candidates_and_provider_calls():
    from cragkit.errors import ProviderUnavailable
    class Transient(Backend):
        async def search(self, request, *, ledger, **options):
            token = ledger.reserve(provider_calls=1)
            ledger.dispatch(token)
            if not self.calls:
                self.calls.append('failed')
                ledger.abandon(token)
                raise ProviderUnavailable()
            ledger.reconcile(token, input_tokens=1, output_tokens=0, cost_usd=0)
            return await super().search(request, ledger=ledger, **options)
    backend = Transient()
    output = run(CorrectiveRetriever(backend, max_retries=1))
    state = output['diagnostics']['ledger']
    assert state['attempts'] == 2 and state['candidates'] == 32 and state['provider_calls'] == 2
    assert state['input_tokens'] is None and state['cost_usd'] is None
    assert output['diagnostics']['queries_executed'] == 1


def test_fault_matrix_permanent_and_retry_budget_exhaustion():
    from cragkit.errors import InvalidRequest, ProviderUnavailable, UnauthorizedScope
    for error in (InvalidRequest, IntegrityViolation, UnauthorizedScope, ProviderUnavailable):
        class Failed(Backend):
            async def search(self, request, **options):
                self.calls.append(request)
                raise error()
        backend = Failed()
        request = dict(REQUEST, limits={'max_attempts': 1})
        with pytest.raises(error):
            run(CorrectiveRetriever(backend, max_retries=2), request)
        assert len(backend.calls) == 1


def test_backoff_cancellation_and_concurrent_request_state():
    from cragkit.errors import ProviderUnavailable
    async def scenario():
        failed = asyncio.Event()
        class Failed(Backend):
            async def search(self, request, **options):
                failed.set()
                raise ProviderUnavailable()
        core = CorrectiveRetriever(Failed(), max_retries=1, backoff_ms=1000)
        task = asyncio.create_task(core.retrieve(REQUEST, scope=SCOPE, deadline=asyncio.get_running_loop().time() + 2))
        await failed.wait()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        class Stable(Backend):
            async def search(self, request, **options):
                await asyncio.sleep(0)
                return {'candidates': [A[0]], 'degraded': False}
        core = CorrectiveRetriever(Stable())
        first, second = await asyncio.gather(*(core.retrieve(dict(REQUEST, request_id=rid), scope=SCOPE,
            deadline=asyncio.get_running_loop().time() + 1) for rid in ('one', 'two')))
        assert first['result']['request_id'] == 'one' and second['result']['request_id'] == 'two'
        assert first['diagnostics']['ledger']['attempts'] == second['diagnostics']['ledger']['attempts'] == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['empty', 'fallback', 'repeat'])
def test_planner_revocation_is_captured_before_any_final_release(kind):
    from cragkit.errors import ProviderUnavailable
    backend = Backend()
    async def revoke(payload, *, deadline):
        backend.revoke = True
        if kind == 'fallback':
            raise ProviderUnavailable()
        selections = [] if kind == 'empty' else [{'facet_id': 'second', 'variant_id': 'same'}]
        return dict(plan={'queries': selections}, usage=dict(input_tokens=1, output_tokens=0, cost_usd=0))
    core = CorrectiveRetriever(backend, policy=policy(), planner=PlannerAdapter(revoke, allow_fallback=True),
        variants=[dict(facet_id='second', variant_id='same', query=' QUESTION ')])
    output = run(core)
    assert backend.captures == 2 and len(backend.calls) == 1
    assert output['result']['evidence'] == []
    assert output['result']['status'] == 'insufficient'
    assert output['diagnostics']['stop_reason'] == ('repeated_query' if kind == 'repeat' else 'no_plan')
    assert output['diagnostics']['ledger']['provider_calls'] == 1
    assert output['diagnostics']['planning_fallback'] == (kind == 'fallback')


def test_integer_valued_json_options_and_capture_bytes_match_integer_forms():
    class JsonCounts(Backend):
        async def capture(self, candidates, **options):
            result = await super().capture(candidates, **options)
            result['source_bytes'] = float(result['source_bytes'])
            return result
    output = run(CorrectiveRetriever(JsonCounts(), batch_size=16.0, max_retries=0.0,
                                    backoff_ms=0.0, no_progress_limit=1.0))
    assert output['diagnostics']['candidate_work'] == 16
    from cragkit.errors import InvalidRequest
    for value in (True, 1.5, float('inf')):
        with pytest.raises(InvalidRequest):
            CorrectiveRetriever(Backend(), batch_size=value)


def test_expired_bounded_callback_never_starts():
    from cragkit.corrective import _bounded
    async def scenario():
        started = []
        async def callback():
            started.append(True)
        with pytest.raises(DeadlineExceeded):
            await _bounded(callback(), asyncio.get_running_loop().time() - 1)
        await asyncio.sleep(0)
        assert started == []
    asyncio.run(scenario())


@pytest.mark.parametrize('failed_round', [1, 2, 3])
def test_capture_admission_failure_discards_old_evidence_and_is_terminal(failed_round):
    from cragkit.execution import BudgetExhausted
    class CaptureBudget(Backend):
        async def capture(self, candidates, *, ledger, **options):
            if self.captures + 1 == failed_round:
                self.captures += 1
                # A dispatched operation can have unknown billed usage before admission fails.
                token = ledger.reserve(provider_calls=1)
                ledger.dispatch(token)
                ledger.abandon(token)
                raise BudgetExhausted()
            return await super().capture(candidates, ledger=ledger, **options)
    backend = CaptureBudget()
    output = run(retriever(backend))
    assert backend.captures == failed_round
    assert len(backend.calls) == (2 if failed_round == 3 else 1)
    assert output['diagnostics']['stop_reason'] == 'budget_exhausted'
    assert output['result']['status'] == 'insufficient'
    assert output['result']['evidence'] == [] and output['result']['context'] == '[]'
    assert output['diagnostics']['ledger']['cost_usd'] is None
    assert output['diagnostics']['ledger']['input_tokens'] is None
    assert any(item['code'] == 'budget_exhausted' for item in output['result']['limitations'])
    assert 'source_bytes' not in output['diagnostics']


def test_preplanning_candidate_capacity_stop_keeps_current_fresh_evidence():
    backend = Backend()
    output = run(retriever(backend), dict(REQUEST, limits={'max_candidates': 16}))
    assert backend.captures == 1 and len(backend.calls) == 1
    assert output['diagnostics']['ledger']['provider_calls'] == 0
    assert output['diagnostics']['stop_reason'] == 'budget_exhausted'
    assert [item['document_id'] for item in output['result']['evidence']] == ['a']


@pytest.mark.parametrize('error_name', ['ProviderUnavailable', 'IntegrityViolation', 'UnsupportedCapability'])
def test_capture_operational_and_integrity_errors_never_become_empty_results(error_name):
    from cragkit import errors
    error_type = getattr(errors, error_name)
    class CaptureFailure(Backend):
        async def capture(self, candidates, **options):
            self.captures += 1
            raise error_type()
    backend = CaptureFailure()
    with pytest.raises(error_type):
        run(retriever(backend, max_retries=2))
    assert backend.captures == 1


def test_provider_budget_after_transient_keeps_operational_error():
    from cragkit.errors import ProviderUnavailable
    class ProviderBudget(Backend):
        async def search(self, request, *, ledger, **options):
            token = ledger.reserve(provider_calls=1)
            ledger.dispatch(token)
            ledger.abandon(token)
            self.calls.append(request)
            raise ProviderUnavailable()
    backend = ProviderBudget()
    with pytest.raises(ProviderUnavailable):
        run(CorrectiveRetriever(backend, max_retries=1), dict(REQUEST, limits={'max_provider_calls': 1}))
    assert len(backend.calls) == 1 and backend.captures == 0


def test_retained_candidate_ceiling_stops_before_planning():
    rows = [A, *(fixture(f'extra{index}', f'unreviewed {index}') for index in range(63))]
    class Full(Backend):
        async def search(self, request, **options):
            self.calls.append(request)
            return {'candidates': [row[0] for row in rows], 'degraded': False}
        async def capture(self, candidates, **options):
            self.captures += 1
            return dict(evidence=[row[1] for row in rows], sources=[row[2] for row in rows],
                        source_bytes=sum(len(row[2]['text']) for row in rows), stale=False, budget_exhausted=False)
    backend = Full()
    output = run(retriever(backend, batch_size=64), dict(REQUEST, limits={'max_context_tokens': 100000}))
    assert len(backend.calls) == backend.captures == 1
    assert output['diagnostics']['stop_reason'] == 'budget_exhausted'
    assert output['diagnostics']['ledger']['provider_calls'] == 0
