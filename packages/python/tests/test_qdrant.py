"""QC-r1 native boundary checks using deterministic bytes, never a live backend."""
import asyncio
import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cragkit.embeddings import FAKE_PROFILE
from cragkit.errors import DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability
from cragkit.execution import BudgetExhausted, ExecutionLedger
from cragkit.qdrant import QdrantSearchStore, SPARSE_PROFILE, compile_filter, point_id

FIXTURE = json.loads((Path(__file__).resolve().parents[3] / 'contracts/fixtures/qdrant_candidates.json').read_text())
CONFIG = dict(backend_namespace='fixture-local', physical_collection='cragkit_qc_r1',
              collection_incarnation='inc-1', dense_profile=FAKE_PROFILE.model_dump(),
              sparse_profile=SPARSE_PROFILE.model_dump())
SCOPE = FIXTURE['trusted_scope']
REQUEST = {'query': 'synthetic', 'collection': 'docs'}
DENSE = [1.0] + [0.0] * 1535
SPARSE = {'indices': [2, 7], 'values': [1.0, 0.5]}


def resolve(value):
    if isinstance(value, str) and value.startswith('$ref:'):
        result = FIXTURE
        for part in value[5:].split('.'):
            result = next(item for item in result if item['id'] == part) if isinstance(result, list) else result[part]
        return resolve(result)
    if isinstance(value, dict):
        return {key: resolve(item) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item) for item in value]
    return value


def base_point():
    return resolve(FIXTURE['base_point'])


def wire(result):
    return json.dumps({'result': result, 'status': 'ok'}, separators=(',', ':')).encode()


class FakeTransport:
    bounded_responses = True
    cancellation_safe = True

    def __init__(self, points=None):
        self.points = [base_point()] if points is None else points
        self.calls = []
        self.hook = None
        self.closed = False
        self.root = {'version': '1.20.0'}
        self.cluster = {'status': 'disabled'}
        self.params = {'vectors': {'dense': {'size': 1536, 'distance': 'Cosine'}},
                       'sparse_vectors': {'sparse': {}}, 'replication_factor': 1, 'write_consistency_factor': 1}

    async def request(self, method, path, *, body=None, deadline, max_response_bytes):
        self.calls.append((method, path, json.loads(body) if body else None))
        if self.hook is not None:
            return await self.hook(method, path, body)
        if path == '/':
            return json.dumps(self.root).encode()
        if path == '/cluster':
            return wire(self.cluster)
        if method == 'GET':
            return wire({'config': {'params': self.params}})
        return wire({'points': copy.deepcopy(self.points)})

    async def close(self):
        self.closed = True


async def ready(points=None, config=None):
    transport = FakeTransport(points)
    store = QdrantSearchStore(CONFIG if config is None else config, transport)
    end = asyncio.get_running_loop().time() + 5
    await store.initialize(deadline=end)
    return store, transport, end


async def search(store, end, *, request=None, scope=None, ledger=None, **kwargs):
    return await store.search_candidates(REQUEST if request is None else request,
        scope=SCOPE if scope is None else scope, ledger=ledger or ExecutionLedger({}, deadline=end),
        deadline=end, **({'dense': DENSE, 'branch_limits': {'dense': 1}} | kwargs))


@pytest.mark.parametrize('case', FIXTURE['point_id_cases'], ids=lambda c: c['id'])
def test_point_ids_shared(case):
    assert point_id(case['tuple']) == case['expected_uuid']


@pytest.mark.parametrize('value', [None, [], [1] * 12, ['wrong'] * 12, ['cragkit.qdrant.point.v1'] + ['\ud800'] * 11])
def test_point_identity_invalid(value):
    with pytest.raises(InvalidRequest):
        point_id(value)


@pytest.mark.parametrize('case', [c for c in FIXTURE['filter_cases'] if 'expected' in c], ids=lambda c: c['id'])
def test_filter_mapping_shared(case):
    request = dict(REQUEST, required_filters=[case['input']])
    assert compile_filter(request, SCOPE)['must'][-1] == case['expected']
    assert compile_filter(request, SCOPE)['must'][:3] == FIXTURE['scope_filter']['must']


def test_valid_dual_branch_immutable_serialization_and_work_accounting():
    async def scenario():
        store, transport, end = await ready()
        ledger = ExecutionLedger({}, deadline=end)
        result = await search(store, end, ledger=ledger, sparse=SPARSE, branch_limits={'dense': 2, 'sparse': 1})
        assert [item.branch for item in result] == ['dense', 'sparse']
        serialized = result[0].model_dump(mode='json')
        assert serialized['verification'] == 'UNVERIFIED'
        assert serialized['score_direction'] == 'higher_is_better'
        assert serialized['payload'] == resolve(FIXTURE['base_payload'])
        assert ledger.snapshot()['candidates'] == 3
        assert ledger.snapshot()['provider_calls'] == 0
        assert ledger.snapshot()['pending'] == 0
        assert [call[2]['using'] for call in transport.calls[3:]] == ['dense', 'sparse']
        for call in transport.calls[3:]:
            assert call[2]['filter'] == FIXTURE['scope_filter']
            assert call[2]['with_payload'] == FIXTURE['payload_projection']
            assert call[2]['with_vector'] is False
        with pytest.raises(ValidationError):
            result[0].payload.document_id = 'mutated'
        with pytest.raises(TypeError):
            store.capabilities()['candidate_replica_only'] = False
        await store.close()
        assert not transport.closed
    asyncio.run(scenario())


REJECTIONS = [c for c in FIXTURE['response_cases'] if c.get('expected_error') == 'IntegrityViolation' and 'set' in c]


@pytest.mark.parametrize('case', REJECTIONS, ids=lambda c: c['id'])
def test_response_rejections_shared(case):
    async def scenario():
        point = base_point()
        for path, value in case['set'].items():
            target = point
            parts = path.split('.')
            for name in parts[:-1]:
                target = target[name]
            target[parts[-1]] = value
        store, _, end = await ready([point])
        with pytest.raises(IntegrityViolation):
            await search(store, end)
    asyncio.run(scenario())


@pytest.mark.parametrize('points', [[], [resolve(FIXTURE['base_point']), resolve(FIXTURE['base_point'])]])
def test_empty_and_duplicate(points):
    async def scenario():
        store, _, end = await ready(points)
        if not points:
            assert await search(store, end) == ()
        else:
            with pytest.raises(IntegrityViolation):
                await search(store, end, branch_limits={'dense': 2})
    asyncio.run(scenario())


@pytest.mark.parametrize('raw', [b'{"status":"ok","result":{"points":[]},"result":{"points":[]}}',
    b'{"status":"ok","result":{"points":[]},"x":1e9999}', b'\xff', b'[' * 40 + b']' * 40,
    b'x' * 1048577, b'{"status":"ok","result":{"points":{} }}'])
def test_malformed_raw_response(raw):
    async def scenario():
        store, transport, end = await ready()
        async def hook(*_):
            return raw
        transport.hook = hook
        with pytest.raises(IntegrityViolation):
            await search(store, end)
    asyncio.run(scenario())


@pytest.mark.parametrize('change', [
    {'required_filters': [{'op': 'ne', 'field': 'tag', 'value': 'x'}]},
    {'required_filters': [{'op': 'eq', 'field': 'tag', 'value': True}]},
    {'required_filters': [{'op': 'in', 'field': 'tag', 'values': [1]}]},
    {'required_filters': [{'op': 'not', 'filter': {'op': 'eq', 'field': 'tag', 'value': 'x'}}]},
])
def test_unsupported_filters_before_io(change):
    async def scenario():
        store, transport, end = await ready()
        with pytest.raises(UnsupportedCapability):
            await search(store, end, request=REQUEST | change)
        assert len(transport.calls) == 3
    asyncio.run(scenario())


@pytest.mark.parametrize('sparse', [c for c in FIXTURE['admission_cases'] if c['id'] == 'sparse_invalid'][0]['variants'] +
    [{'indices': [2], 'values': [1e-99]}, {'indices': [2], 'values': [1e99]}, {'indices': [True], 'values': [1]}])
def test_sparse_invalid_before_io(sparse):
    async def scenario():
        store, transport, end = await ready()
        with pytest.raises(InvalidRequest):
            await search(store, end, sparse=sparse, branch_limits={'dense': 1, 'sparse': 1})
        assert len(transport.calls) == 3
    asyncio.run(scenario())


@pytest.mark.parametrize('dense', [[0.] * 1536, [True] + [0.] * 1535, [float('nan')] + [0.] * 1535, [1.0]])
def test_dense_invalid_before_io(dense):
    async def scenario():
        store, transport, end = await ready()
        with pytest.raises(InvalidRequest):
            await search(store, end, dense=dense)
        assert len(transport.calls) == 3
    asyncio.run(scenario())


def test_budget_admission_does_not_dispatch_or_double_charge():
    async def scenario():
        store, transport, end = await ready()
        ledger = ExecutionLedger({'max_candidates': 1}, deadline=end)
        with pytest.raises(BudgetExhausted):
            await search(store, end, ledger=ledger, branch_limits={'dense': 2})
        assert len(transport.calls) == 3
        assert ledger.snapshot()['candidates'] == 0
        with pytest.raises(InvalidRequest):
            await search(store, end, request=REQUEST | {'limits': {'max_candidates': 1}}, branch_limits={'dense': 2})
        assert len(transport.calls) == 3
    asyncio.run(scenario())


def test_authorization_and_required_metadata_defensively_checked():
    async def scenario():
        store, _, end = await ready()
        scope = SCOPE | {'principal_id': 'other', 'grant_ids': []}
        with pytest.raises(IntegrityViolation):
            await search(store, end, scope=scope)
        request = REQUEST | {'required_filters': [{'op': 'eq', 'field': 'tag', 'value': 'missing'}]}
        with pytest.raises(IntegrityViolation):
            await search(store, end, request=request)
    asyncio.run(scenario())


def test_snapshot_before_await_and_cross_branch_contradiction():
    async def scenario():
        store, transport, end = await ready()
        request = copy.deepcopy(REQUEST)
        scope = copy.deepcopy(SCOPE)
        count = 0
        async def hook(*_):
            nonlocal count
            count += 1
            request['collection'] = 'evil'
            scope['tenant_id'] = 'evil'
            point = base_point()
            if count == 2:
                point['payload']['authorization_revision'] = 'auth-other'
            return wire({'points': [point]})
        transport.hook = hook
        with pytest.raises(IntegrityViolation):
            await search(store, end, request=request, scope=scope, sparse=SPARSE, branch_limits={'dense': 1, 'sparse': 1})
        assert count == 2
    asyncio.run(scenario())


@pytest.mark.parametrize('kind', ['version', 'cluster', 'metric', 'replication', 'idf'])
def test_initialize_rejects_unsupported_profiles(kind):
    async def scenario():
        transport = FakeTransport()
        if kind == 'version': transport.root['version'] = '1.19.0'
        if kind == 'cluster': transport.cluster['status'] = 'enabled'
        if kind == 'metric': transport.params['vectors']['dense']['distance'] = 'Dot'
        if kind == 'replication': transport.params['replication_factor'] = 2
        if kind == 'idf': transport.params['sparse_vectors']['sparse']['modifier'] = 'idf'
        store = QdrantSearchStore(CONFIG, transport)
        with pytest.raises(UnsupportedCapability):
            await store.initialize(deadline=asyncio.get_running_loop().time() + 1)
        with pytest.raises(IndexNotReady):
            await search(store, asyncio.get_running_loop().time() + 1)
    asyncio.run(scenario())


def test_deadline_cancellation_concurrency_and_close():
    async def scenario():
        store, transport, end = await ready()
        entered = asyncio.Event()
        settled = asyncio.Event()
        async def block(*_):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                settled.set()
        transport.hook = block
        task = asyncio.create_task(search(store, end))
        await entered.wait()
        with pytest.raises(ProviderUnavailable):
            await search(store, end)
        await store.close()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert settled.is_set() and not transport.closed
        await store.close()
        with pytest.raises((InvalidRequest, IndexNotReady)):
            await search(store, end)
        store2, transport2, end2 = await ready()
        transport2.hook = block
        ledger = ExecutionLedger({}, deadline=end2)
        with pytest.raises(DeadlineExceeded):
            await store2.search_candidates(REQUEST, scope=SCOPE, dense=DENSE, branch_limits={'dense': 1},
                ledger=ledger, deadline=asyncio.get_running_loop().time() + .01)
        assert ledger.snapshot()['pending'] == 0
        assert ledger.snapshot()['candidates'] == 1
    asyncio.run(scenario())


def test_dense_only_optional_metadata_and_stale_acl_stay_unverified():
    async def scenario():
        cfg = CONFIG | {'sparse_profile': None}
        point = base_point()
        point['payload']['sparse_profile'] = None
        point['payload']['sparse_profile_id'] = ''
        point['payload']['authorization_revision'] = 'stale'
        for key in ('language', 'kind', 'tag'):
            point['payload'].pop(key)
        point['id'] = FIXTURE['point_id_cases'][1]['expected_uuid']
        transport = FakeTransport([point])
        transport.params['sparse_vectors'] = None
        store = QdrantSearchStore(cfg, transport)
        end = asyncio.get_running_loop().time() + 2
        await store.initialize(deadline=end)
        result = await search(store, end)
        output = result[0].model_dump(mode='json')
        assert output['payload']['sparse_profile'] is None
        assert output['payload']['sparse_profile_id'] == ''
        assert 'language' not in output['payload']
        assert output['verification'] == 'UNVERIFIED'
    asyncio.run(scenario())


def test_semantic_json_integral_numbers_and_unsupported_multivectors():
    async def scenario():
        cfg = copy.deepcopy(CONFIG)
        cfg['dense_profile']['dimensions'] = 1536.0
        point = base_point()
        point['payload']['dense_profile']['dimensions'] = 1536.0
        point['payload']['start_byte'] = 0.0
        point['payload']['end_byte'] = 4.0
        transport = FakeTransport([point])
        transport.params['vectors']['dense']['size'] = 1536.0
        transport.params['replication_factor'] = 1.0
        transport.params['write_consistency_factor'] = 1.0
        store = QdrantSearchStore(cfg, transport)
        end = asyncio.get_running_loop().time() + 2
        await store.initialize(deadline=end)
        result = await search(store, end)
        assert type(result[0].payload.start_byte) is int
        assert type(result[0].payload.dense_profile.dimensions) is int
        transport.params['vectors']['dense']['multivector_config'] = {'comparator': 'max_sim'}
        with pytest.raises(UnsupportedCapability):
            await store.initialize(deadline=end)
        with pytest.raises(IndexNotReady):
            await search(store, end)
    asyncio.run(scenario())


@pytest.mark.parametrize('value', [True, 1536.5, float('inf'), 9007199254740992])
def test_invalid_profile_dimensions_cannot_be_coerced(value):
    cfg = copy.deepcopy(CONFIG)
    cfg['dense_profile']['dimensions'] = value
    with pytest.raises(InvalidRequest):
        QdrantSearchStore(cfg, FakeTransport())


@pytest.mark.parametrize('index,value', [(1, ''), (3, ' '), (4, 'a' * 257), (5, 'a' * 129),
    (9, 'nul\0'), (11, 'x' * 257), (11, '\ud800'), (11, ' ')])
def test_uuid_helper_enforces_scoped_identity_limits(index, value):
    identity = list(FIXTURE['point_id_cases'][0]['tuple'])
    identity[index] = value
    with pytest.raises(InvalidRequest):
        point_id(identity)


@pytest.mark.parametrize('path,value', [('dense_profile.model', 'another_model'),
    ('dense_profile.profile_id', 'another_profile'), ('sparse_profile.revision', '2')])
def test_well_formed_unsupported_profiles_have_capability_error(path, value):
    cfg = copy.deepcopy(CONFIG)
    outer, field = path.split('.')
    cfg[outer][field] = value
    with pytest.raises(UnsupportedCapability):
        QdrantSearchStore(cfg, FakeTransport())


def test_response_complexity_counts_values_not_object_keys():
    from cragkit._qdrant_contract import decode_response
    value = {str(i): 0 for i in range(20000)}
    assert decode_response(json.dumps(value).encode()) == value
    value = {str(i): 0 for i in range(32768)}
    with pytest.raises(IntegrityViolation):
        decode_response(json.dumps(value).encode())
    with pytest.raises(IntegrityViolation):
        decode_response(b'{"\\ud800":0}')


@pytest.mark.parametrize('error_class', [DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability])
def test_mutated_borrowed_transport_errors_are_recreated(error_class):
    async def scenario():
        store, transport, end = await ready()
        error = error_class()
        error.args = ('PRIVATE_ENDPOINT_QUERY',)
        error.code = 'PRIVATE_SCOPE'
        async def hook(*_):
            raise error
        transport.hook = hook
        with pytest.raises(error_class) as caught:
            await search(store, end)
        assert caught.value is not error
        assert caught.value.code == error_class.code
        assert 'PRIVATE' not in str(caught.value)
        assert caught.value.__suppress_context__ is True
        assert caught.value.__cause__ is None
    asyncio.run(scenario())


def test_unknown_transport_error_subclass_is_operational_and_redacted():
    class Unknown(InvalidRequest):
        pass
    async def scenario():
        store, transport, end = await ready()
        error = Unknown()
        error.args = ('PRIVATE_CANARY',)
        async def hook(*_):
            raise error
        transport.hook = hook
        with pytest.raises(ProviderUnavailable) as caught:
            await search(store, end)
        assert type(caught.value) is ProviderUnavailable
        assert 'PRIVATE' not in str(caught.value)
        assert caught.value.__suppress_context__ is True
    asyncio.run(scenario())


def test_response_numeric_lexeme_bound_matches_native_node_parser():
    from cragkit._qdrant_contract import decode_response
    assert decode_response(b'1' * 128) == int('1' * 128)
    assert decode_response(b'0.' + b'0' * 125 + b'1') == float('0.' + '0' * 125 + '1')
    for raw in (b'1' * 129, b'0.' + b'0' * 126 + b'1', b'-' + b'1' * 128):
        with pytest.raises(IntegrityViolation):
            decode_response(raw)
