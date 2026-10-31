"""Example composition checks: fake inference, real-profile spies and no network."""
import asyncio
from functools import wraps
import importlib.util
import json
from pathlib import Path

import pytest

from cragkit.embeddings import FAKE_PROFILE, OPENAI_PROFILE, EmbeddingPolicy
from cragkit.errors import ProviderUnavailable, UnsupportedCapability
from cragkit.execution import BudgetExhausted, ExecutionLedger
from cragkit.qdrant import QdrantSearchStore

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location('qdrant_dense_example', ROOT / 'examples/qdrant_dense.py')
example = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(example)


def run_async(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


class Counter:
    def __init__(self, name): self.name = name
    def count(self, text): return len(text.encode())


class Backend:
    bounded_responses = cancellation_safe = True
    def __init__(self): self.calls = []
    async def request(self, method, path, **options):
        self.calls.append((method, path, options))
        if path == '/': value = {'version': '1.20.0'}
        elif path == '/cluster': value = {'status': 'ok', 'result': {'status': 'disabled'}}
        elif method == 'GET':
            value = {'status': 'ok', 'result': {'config': {'params': {
                'vectors': {'dense': {'size': 1536, 'distance': 'Cosine'}},
                'replication_factor': 1, 'write_consistency_factor': 1}}}}
        else: value = {'status': 'ok', 'result': {'points': []}}
        return json.dumps(value).encode()


async def setup(profile=FAKE_PROFILE, limits=None):
    f = json.loads((ROOT / 'contracts/fixtures/qdrant_candidates.json').read_text())
    cfg = dict(backend_namespace='fixture-local', physical_collection='cragkit_qc_r1',
               collection_incarnation='inc-1', dense_profile=profile.model_dump(), sparse_profile=None)
    backend = Backend()
    store = QdrantSearchStore(cfg, backend)
    deadline = asyncio.get_running_loop().time() + 2
    await store.initialize(deadline=deadline)
    request = dict(request_id='example', query='fixture', collection='docs', required_filters=[],
                   limits=limits or {'max_candidates': 2, 'max_provider_calls': 1})
    ledger = ExecutionLedger(request['limits'], deadline=deadline)
    return store, backend, request, f['trusted_scope'], ledger, deadline


def response(body, usage=True):
    req = json.loads(body)
    value = {'model': req['model'], 'data': [{'index': 0, 'embedding': [1.0] + [0.0]*1535}]}
    if usage: value['usage'] = {'prompt_tokens': 7, 'total_tokens': 7}
    return json.dumps(value).encode()


@run_async
async def test_fake_success_separates_provider_and_candidate_accounting():
    store, backend, request, scope, ledger, deadline = await setup()
    calls = []
    async def transport(body, **options): calls.append(options); return response(body)
    try:
        result = await example.retrieve_candidates(store, request, scope=scope, transport=transport,
            token_counter=Counter(FAKE_PROFILE.tokenizer), ledger=ledger, deadline=deadline)
        assert result['nominations'] == () and len(calls) == 1
        assert result['ledger'] == dict(provider_calls=1, candidates=2, attempts=0,
            input_tokens=7, output_tokens=0, cost_usd=0.0, cost_kind='known', pending=0)
        assert calls[0]['deadline'] == backend.calls[-1][2]['deadline']
        assert result['embedding_usage'].cost_kind == 'known'
    finally: await store.close()


@run_async
@pytest.mark.parametrize('usage', [True, False])
async def test_real_profile_spy_estimate_or_unknown_never_becomes_known_billing(usage):
    store, backend, request, scope, ledger, deadline = await setup(OPENAI_PROFILE)
    sent = []
    async def transport(body, **options): sent.append(json.loads(body)); return response(body, usage)
    try:
        result = await example.retrieve_candidates(store, request, scope=scope, transport=transport,
            token_counter=Counter(OPENAI_PROFILE.tokenizer), ledger=ledger, deadline=deadline,
            policy=EmbeddingPolicy(allow_live=True, max_cost_usd=0.01, usd_per_million_tokens=0.02))
        assert sent[0]['model'] == OPENAI_PROFILE.model and sent[0]['dimensions'] == 1536
        assert result['embedding_usage'].cost_kind == ('estimated' if usage else 'unknown')
        assert result['ledger']['cost_usd'] is None and result['ledger']['cost_kind'] == 'unknown'
        assert result['ledger']['input_tokens'] == (7 if usage else None)
        assert result['ledger']['provider_calls'] == 1 and result['ledger']['candidates'] == 2
        assert len(backend.calls) == 4  # In-memory routing spy only; no backend persistence.
    finally: await store.close()


@run_async
async def test_live_default_denied_before_provider_or_query_dispatch():
    store, backend, request, scope, ledger, deadline = await setup(OPENAI_PROFILE)
    calls = []
    async def transport(*args, **kwargs): calls.append(True); raise AssertionError()
    try:
        with pytest.raises(UnsupportedCapability):
            await example.retrieve_candidates(store, request, scope=scope, transport=transport,
                token_counter=Counter(OPENAI_PROFILE.tokenizer), ledger=ledger, deadline=deadline)
        assert not calls and len(backend.calls) == 3
        assert ledger.snapshot()['provider_calls'] == ledger.snapshot()['candidates'] == 0
    finally: await store.close()


@run_async
async def test_budget_refusal_keeps_budget_signal_and_zero_dispatched_calls():
    store, backend, request, scope, ledger, deadline = await setup(limits={'max_candidates': 2, 'max_provider_calls': 0})
    calls = []
    async def transport(*args, **kwargs): calls.append(True); raise AssertionError()
    try:
        with pytest.raises(BudgetExhausted):
            await example.retrieve_candidates(store, request, scope=scope, transport=transport,
                token_counter=Counter(FAKE_PROFILE.tokenizer), ledger=ledger, deadline=deadline)
        assert not calls and ledger.snapshot()['provider_calls'] == 0 and len(backend.calls) == 3
    finally: await store.close()


@run_async
@pytest.mark.parametrize('failure', ['transport', 'malformed', 'cancel'])
async def test_failed_or_cancelled_dispatched_inference_retains_unknown_work(failure):
    store, backend, request, scope, ledger, deadline = await setup()
    started = asyncio.Event()
    async def transport(*args, **kwargs):
        started.set()
        if failure == 'cancel': await asyncio.Event().wait()
        if failure == 'transport': raise RuntimeError('PRIVATE TRANSPORT CANARY')
        return b'not-json'
    try:
        task = asyncio.create_task(example.retrieve_candidates(store, request, scope=scope,
            transport=transport, token_counter=Counter(FAKE_PROFILE.tokenizer), ledger=ledger, deadline=deadline))
        await started.wait()
        if failure == 'cancel': task.cancel()
        with pytest.raises(asyncio.CancelledError if failure == 'cancel' else ProviderUnavailable) as error:
            await task
        assert 'PRIVATE' not in str(error.value)
        snap = ledger.snapshot()
        assert snap['provider_calls'] == 1 and snap['candidates'] == snap['pending'] == 0
        assert snap['input_tokens'] is None and snap['cost_usd'] is None
        assert len(backend.calls) == 3
    finally: await store.close()
