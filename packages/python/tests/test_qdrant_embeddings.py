"""Full-profile binding of existing embedding batches; all transports are spies."""
import asyncio
import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cragkit.embeddings import EmbeddingBatch, EmbeddingProfile, FAKE_PROFILE, OPENAI_PROFILE
from cragkit.errors import CragkitError, EmbeddingProfileMismatch, InvalidRequest, UnsupportedCapability
from cragkit.execution import ExecutionLedger
from cragkit.qdrant import QdrantSearchStore, SPARSE_PROFILE, bind_embedding_batch, point_id

VECTOR = [1.0] + [0.0] * 1535


def batch(profile=FAKE_PROFILE, *, count=1):
    fake = profile.provider == 'fake'
    return {'profile': profile.model_dump(), 'vectors': [VECTOR.copy() for _ in range(count)],
            'usage': {'prompt_tokens': 2, 'total_tokens': 2, 'cost_usd': 0.0 if fake else .00001,
                      'cost_kind': 'known' if fake else 'estimated'},
            'provider_calls': 1, 'synthetic': fake}


def config(profile=FAKE_PROFILE, sparse=None):
    return {'backend_namespace': 'binding-test', 'physical_collection': 'binding_test',
            'collection_incarnation': 'inc-1', 'dense_profile': profile.model_dump(), 'sparse_profile': sparse}


class Spy:
    bounded_responses = True
    cancellation_safe = True

    def __init__(self):
        self.calls = []
        self.points = []

    async def request(self, method, path, *, body=None, **kwargs):
        self.calls.append((method, path, json.loads(body) if body else None))
        if path == '/': return b'{"version":"1.20.0"}'
        result = ({'status': 'disabled'} if path == '/cluster' else
                  {'config': {'params': {'vectors': {'dense': {'size': 1536, 'distance': 'Cosine'}},
                    'sparse_vectors': None, 'replication_factor': 1, 'write_consistency_factor': 1}}}
                  if method == 'GET' else {'points': self.points})
        return json.dumps({'result': result, 'status': 'ok'}).encode()


def test_binding_snapshots_full_batch_and_supports_eight_vectors():
    original = batch(count=8)
    result = bind_embedding_batch(original, FAKE_PROFILE, expected_items=8)
    assert type(result) is EmbeddingBatch
    assert result.model_dump(mode='json') == original
    original['vectors'][0][0] = 0
    original['profile']['model'] = 'changed'
    original['usage']['prompt_tokens'] = 99
    assert result.vectors[0][0] == 1
    assert result.profile == FAKE_PROFILE
    assert result.usage.prompt_tokens == 2
    with pytest.raises(ValidationError):
        result.synthetic = False
    with pytest.raises(TypeError):
        result.vectors[0][0] = 0
    with pytest.raises(ValidationError):
        result.usage.cost_kind = 'unknown'
    assert bind_embedding_batch(result, FAKE_PROFILE).model_dump(mode='json') == result.model_dump(mode='json')


@pytest.mark.parametrize('path,value', [('profile.model', 'different'), ('profile.dimensions', 768),
    ('profile.provider', 'other'), ('synthetic', False)])
def test_full_profile_and_synthetic_mismatch(path, value):
    original = batch()
    parts = path.split('.')
    target = original if len(parts) == 1 else original[parts[0]]
    target[parts[-1]] = value
    with pytest.raises(EmbeddingProfileMismatch):
        bind_embedding_batch(original, FAKE_PROFILE)


@pytest.mark.parametrize('mutation', [
    lambda x: x.update(provider_calls=True), lambda x: x.update(provider_calls=2),
    lambda x: x.update(extra='forbidden'), lambda x: x.update(synthetic='true'),
    lambda x: x['usage'].update(prompt_tokens=None), lambda x: x['usage'].update(total_tokens=1),
    lambda x: x['usage'].update(prompt_tokens=True), lambda x: x['usage'].update(total_tokens=2147483648),
    lambda x: x['usage'].update(cost_usd=.1), lambda x: x['usage'].update(cost_kind='estimated'),
    lambda x: x['usage'].update(extra='unknown'), lambda x: x['vectors'][0].__setitem__(0, float('nan')),
    lambda x: x['vectors'][0].__setitem__(0, True), lambda x: x['vectors'][0].__setitem__(0, 0),
    lambda x: x.update(vectors=[]), lambda x: x.update(vectors=[VECTOR] * 9),
])
def test_malformed_batch_rejected(mutation):
    original = batch()
    mutation(original)
    with pytest.raises(InvalidRequest):
        bind_embedding_batch(original, FAKE_PROFILE)


def test_wrong_dimension_and_expected_count_are_distinct_failures():
    value = batch()
    value['vectors'][0].pop()
    with pytest.raises(EmbeddingProfileMismatch):
        bind_embedding_batch(value, FAKE_PROFILE)
    with pytest.raises(InvalidRequest):
        bind_embedding_batch(batch(count=2), FAKE_PROFILE, expected_items=1)
    for expected in (0, 9, True, '1'):
        with pytest.raises(InvalidRequest):
            bind_embedding_batch(batch(), FAKE_PROFILE, expected_items=expected)


def test_unchecked_models_are_revalidated():
    bound = bind_embedding_batch(batch(), FAKE_PROFILE)
    for mutated in (bound.model_copy(update={'synthetic': False}),
                    bound.model_copy(update={'profile': EmbeddingProfile.model_construct(**(FAKE_PROFILE.model_dump() | {'model': 'other'}))})):
        with pytest.raises(EmbeddingProfileMismatch):
            bind_embedding_batch(mutated, FAKE_PROFILE)
    with pytest.raises(InvalidRequest):
        bind_embedding_batch(bound.model_copy(update={'provider_calls': 2}), FAKE_PROFILE)


def test_cycles_depth_and_node_limits_fail_before_copy():
    cycle = batch()
    cycle['vectors'][0] = cycle
    with pytest.raises(InvalidRequest):
        bind_embedding_batch(cycle, FAKE_PROFILE)
    deep = batch()
    deep['vectors'] = [[[[[[[[[1]]]]]]]]]
    with pytest.raises(InvalidRequest):
        bind_embedding_batch(deep, FAKE_PROFILE)
    oversized = batch()
    oversized['vectors'] = [[0] * 16385]
    with pytest.raises(InvalidRequest):
        bind_embedding_batch(oversized, FAKE_PROFILE)


def test_real_usage_keeps_estimated_and_unknown_separate():
    estimated = bind_embedding_batch(batch(OPENAI_PROFILE), OPENAI_PROFILE)
    assert estimated.usage.cost_kind == 'estimated' and estimated.usage.cost_usd == .00001
    unknown = batch(OPENAI_PROFILE)
    unknown['usage'] = {'prompt_tokens': None, 'total_tokens': None, 'cost_usd': None, 'cost_kind': 'unknown'}
    assert bind_embedding_batch(unknown, OPENAI_PROFILE).usage.model_dump() == unknown['usage']
    for usage in ({'cost_kind': 'known'}, {'cost_kind': 'unknown'}, {'cost_usd': None}, {'cost_usd': -1}, {'cost_usd': 1000001}):
        value = batch(OPENAI_PROFILE)
        value['usage'].update(usage)
        with pytest.raises(InvalidRequest):
            bind_embedding_batch(value, OPENAI_PROFILE)


def test_real_dense_search_spy_binds_before_io_and_does_not_recharge_embedding():
    async def scenario():
        transport = Spy()
        store = QdrantSearchStore(config(OPENAI_PROFILE), transport)
        deadline = asyncio.get_running_loop().time() + 3
        await store.initialize(deadline=deadline)
        request = {'query': 'SYNTHETIC QUERY', 'collection': 'docs'}
        scope = {'tenant_id': 'tenant', 'principal_id': 'principal', 'authorization_revision': 'auth'}
        ledger = ExecutionLedger({}, deadline=deadline)
        # This is a routing spy only. No real-profile vectors are persisted.
        output = await store.search_candidates(request, scope=scope, dense=batch(OPENAI_PROFILE),
                branch_limits={'dense': 1}, ledger=ledger, deadline=deadline)
        assert output == ()
        assert transport.calls[-1][2]['query'] == VECTOR
        assert ledger.snapshot()['candidates'] == 1 and ledger.snapshot()['provider_calls'] == 0
        before = len(transport.calls)
        for value in (VECTOR, batch(FAKE_PROFILE), batch(OPENAI_PROFILE, count=2)):
            with pytest.raises((EmbeddingProfileMismatch, InvalidRequest)):
                await store.search_candidates(request, scope=scope, dense=value,
                    branch_limits={'dense': 1}, ledger=ledger, deadline=deadline)
        assert len(transport.calls) == before
        assert ledger.snapshot()['candidates'] == 1
    asyncio.run(scenario())


def test_real_sparse_config_fails_before_transport_and_fake_batch_search_works():
    transport = Spy()
    with pytest.raises(UnsupportedCapability):
        QdrantSearchStore(config(OPENAI_PROFILE, SPARSE_PROFILE.model_dump()), transport)
    assert transport.calls == []
    async def scenario():
        store = QdrantSearchStore(config(), transport)
        deadline = asyncio.get_running_loop().time() + 2
        await store.initialize(deadline=deadline)
        assert await store.search_candidates({'query': 'fake', 'collection': 'docs'},
            scope={'tenant_id': 'tenant', 'principal_id': 'principal', 'authorization_revision': 'a'},
            dense=bind_embedding_batch(batch(), FAKE_PROFILE), branch_limits={'dense': 1},
            ledger=ExecutionLedger({}, deadline=deadline), deadline=deadline) == ()
    asyncio.run(scenario())


def test_real_profile_nominations_keep_full_descriptor_and_bound_identity():
    async def scenario():
        transport = Spy()
        store = QdrantSearchStore(config(OPENAI_PROFILE), transport)
        payload = config(OPENAI_PROFILE) | {'tenant_id': 'tenant', 'collection': 'docs', 'document_id': 'doc',
            'revision_id': 'revision', 'generation_id': 'generation', 'chunk_id': 'chunk', 'start_byte': 0,
            'end_byte': 4, 'source_sha256': 'a' * 64, 'text_sha256': 'b' * 64,
            'dense_profile_id': OPENAI_PROFILE.profile_id, 'sparse_profile_id': '', 'authorization_revision': 'auth',
            'principal_ids': ['principal'], 'grant_ids': []}
        identity = ['cragkit.qdrant.point.v1', 'binding-test', 'binding_test', 'inc-1', 'tenant', 'docs',
                    'doc', 'revision', 'generation', 'chunk', OPENAI_PROFILE.profile_id, '']
        transport.points = [{'id': point_id(identity), 'score': .75, 'payload': payload}]
        deadline = asyncio.get_running_loop().time() + 2
        await store.initialize(deadline=deadline)
        result = await store.search_candidates({'query': 'spy only', 'collection': 'docs'},
            scope={'tenant_id': 'tenant', 'principal_id': 'principal', 'authorization_revision': 'auth'},
            dense=batch(OPENAI_PROFILE), branch_limits={'dense': 1}, ledger=ExecutionLedger({}, deadline=deadline),
            deadline=deadline)
        assert result[0].payload.dense_profile.model_dump() == OPENAI_PROFILE.model_dump()
        assert result[0].point_id == point_id(identity)
        fake_identity = identity.copy()
        fake_identity[10] = FAKE_PROFILE.profile_id
        assert point_id(fake_identity) != result[0].point_id
        assert result[0].verification == 'UNVERIFIED'
    asyncio.run(scenario())


@pytest.mark.parametrize('value', ['x' * 1025, '雪' * 342])
def test_batch_and_expected_profile_strings_are_bounded_before_validation(value):
    malformed = batch()
    malformed['vectors'][0][0] = value
    with pytest.raises(InvalidRequest):
        bind_embedding_batch(malformed, FAKE_PROFILE)
    expected = FAKE_PROFILE.model_dump() | {'model': value}
    with pytest.raises(InvalidRequest):
        bind_embedding_batch(batch(), expected)


@pytest.mark.parametrize('key', ['x' * 257, '雪' * 86])
def test_batch_keys_are_bounded_before_encoding(key):
    value = batch()
    value[key] = None
    with pytest.raises(InvalidRequest):
        bind_embedding_batch(value, FAKE_PROFILE)
    expected = FAKE_PROFILE.model_dump() | {key: None}
    with pytest.raises(InvalidRequest):
        bind_embedding_batch(batch(), expected)


def test_integral_json_numeric_semantics_and_unknown_fake_tokens():
    value = batch()
    value['provider_calls'] = 1.0
    value['profile']['dimensions'] = 1536.0
    value['usage'].update(prompt_tokens=2.0, total_tokens=2.0)
    result = bind_embedding_batch(value, FAKE_PROFILE, expected_items=1.0)
    assert type(result.provider_calls) is int
    assert type(result.usage.prompt_tokens) is int
    value['usage'].update(prompt_tokens=None, total_tokens=None)
    assert bind_embedding_batch(value, FAKE_PROFILE).usage.prompt_tokens is None


SHARED_BATCHES = json.loads((Path(__file__).resolve().parents[3] / 'contracts/fixtures/qdrant_embedding_batches.json').read_text())


@pytest.mark.parametrize('case', SHARED_BATCHES['cases'], ids=lambda case: case['id'])
def test_shared_qc_embedding_batch_cases(case):
    profile = copy.deepcopy(SHARED_BATCHES['profiles'][case['profile']])
    vector = [0.0] * SHARED_BATCHES['vector']['dimensions']
    vector[SHARED_BATCHES['vector']['basis_index']] = 1.0
    fake = profile['provider'] == 'fake'
    value = {'profile': copy.deepcopy(profile), 'vectors': [vector],
             'usage': {'prompt_tokens': 2, 'total_tokens': 2, 'cost_usd': 0.0,
                       'cost_kind': 'known' if fake else 'estimated'},
             'provider_calls': 1, 'synthetic': fake}
    for patch in case['patches']:
        target = value
        for component in patch['path'][:-1]:
            target = target[component]
        target[patch['path'][-1]] = copy.deepcopy(patch['value'])
    if 'error' in case:
        with pytest.raises(CragkitError) as caught:
            bind_embedding_batch(value, profile, expected_items=case['expected_items'])
        assert caught.value.code == case['error']
    else:
        result = bind_embedding_batch(value, profile, expected_items=case['expected_items'])
        assert result.profile.model_dump() == profile
        assert result.model_dump(mode='json') == value
        with pytest.raises(ValidationError):
            result.synthetic = not fake


@pytest.mark.parametrize('kind', ['integer', 'string', 'object', 'batch_subclass'])
def test_malformed_real_dense_shapes_fail_before_query_io(kind):
    class UnknownBatch(EmbeddingBatch):
        pass
    async def scenario():
        transport = Spy()
        store = QdrantSearchStore(config(OPENAI_PROFILE), transport)
        deadline = asyncio.get_running_loop().time() + 2
        await store.initialize(deadline=deadline)
        values = {'integer': 3, 'string': 'bad', 'object': object(),
                  'batch_subclass': UnknownBatch.model_construct(**batch(OPENAI_PROFILE))}
        ledger = ExecutionLedger({}, deadline=deadline)
        with pytest.raises(InvalidRequest):
            await store.search_candidates({'query': 'spy', 'collection': 'docs'},
                scope={'tenant_id': 'tenant', 'principal_id': 'principal', 'authorization_revision': 'auth'},
                dense=values[kind], branch_limits={'dense': 1}, ledger=ledger, deadline=deadline)
        assert len(transport.calls) == 3
        assert ledger.snapshot()['candidates'] == 0
    asyncio.run(scenario())
