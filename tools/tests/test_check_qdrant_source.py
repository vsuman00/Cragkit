"""Parent/child privilege boundary tests, without processes or databases."""
import asyncio
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_qdrant_source as implementation


@pytest.mark.parametrize('publication',[False,True])
@pytest.mark.parametrize('failure',[False,True])
def test_administrative_source_seed_restores_exact_triggers_before_commit(publication,failure):
    events=[]
    class Transaction:
        async def __aenter__(self):events.append('begin')
        async def __aexit__(self,kind,*args):events.append('rollback' if kind else 'commit')
    class Admin:
        def transaction(self):return Transaction()
    async def command(query):events.append(query)
    async def run():
        async with implementation.source_fixture_transaction(Admin(),command,publication=publication):
            events.append('seed')
            if failure:raise ValueError('fixture interrupted')
    if failure:
        with pytest.raises(ValueError):asyncio.run(run())
    else:asyncio.run(run())
    assert events[0]=='begin' and events[-1]==('rollback' if failure else 'commit')
    if publication:
        assert events[1:3]==['ALTER TABLE cragkit_qdrant.documents DISABLE TRIGGER publication_document_commit',
            'ALTER TABLE cragkit_qdrant.generations DISABLE TRIGGER publication_generation_commit']
        if not failure:
            assert events[-4:-1]==['SET CONSTRAINTS ALL IMMEDIATE',
                'ALTER TABLE cragkit_qdrant.documents ENABLE TRIGGER publication_document_commit',
                'ALTER TABLE cragkit_qdrant.generations ENABLE TRIGGER publication_generation_commit']
    else:assert events==['begin','seed',events[-1]]


class Writer:
    def __init__(self):
        self.frames = []
        self.closed = False
    def write(self, raw):
        self.frames.append(json.loads(raw))
    async def drain(self):
        pass
    def close(self):
        self.closed = True


class Reader:
    def __init__(self, frames):
        self.frames = list(frames)
    async def readline(self):
        return (json.dumps(self.frames.pop(0)) + '\n').encode() if self.frames else b''


class ErrorReader:
    def __init__(self, text):
        self.text = text
    async def read(self, limit):
        return self.text[:limit]


class Child:
    def __init__(self, frames, stderr=b''):
        self.stdin = Writer()
        self.stdout = Reader(frames)
        self.stderr = ErrorReader(stderr)
        self.returncode = None
        self.terminated = False
    async def wait(self):
        self.returncode = 0
        return 0
    def terminate(self):
        self.terminated = True
    def kill(self):
        self.terminated = True


def install(monkeypatch, child):
    async def create(*args, **kwargs):
        assert args[0] == 'node'
        assert kwargs['limit'] == 65536
        assert not any(key.startswith('PG') for key in kwargs['env'])
        return child
    monkeypatch.setattr(implementation.asyncio, 'create_subprocess_exec', create)


def test_whitelisted_action_is_acknowledged_and_reader_only_input_is_forwarded(monkeypatch):
    child = Child([{'type': 'mutation', 'action': 'reset_active'}, {'type': 'result', 'cases': [{'id': 'active'}]}])
    install(monkeypatch, child)
    actions = []
    async def mutate(action):
        actions.append(action)
    value = {'postgres_config': {'user': 'reader'}, 'qdrant': {'api_key': 'synthetic_read_only'}}
    assert asyncio.run(implementation.node_cases(value, mutate)) == [{'id': 'active'}]
    assert actions == ['reset_active']
    assert child.stdin.frames == [{'type': 'init', 'data': value}, {'type': 'mutation_result', 'action': 'reset_active', 'ok': True}]
    assert child.stdin.closed


@pytest.mark.parametrize('frames', [
    [{'type': 'mutation', 'action': 'arbitrary_sql'}],
    [{'type': 'mutation', 'action': 'reset_active', 'sql': 'PRIVATE_SQL'}],
    [{'type': 'result', 'cases': []}, {'type': 'mutation', 'action': 'revoke'}],
    [{'type': 'result', 'cases': []}, {'type': 'result', 'cases': []}],
    ['PRIVATE_SOURCE_TEXT'],
])
def test_unknown_or_out_of_order_frames_never_reach_admin_and_child_is_closed(monkeypatch, frames):
    child = Child(frames)
    install(monkeypatch, child)
    actions = []
    async def mutate(action):
        actions.append(action)
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(implementation.node_cases({}, mutate))
    assert actions == [] and child.terminated and child.stdin.closed
    assert 'PRIVATE' not in str(caught.value)


def test_child_stderr_is_not_reflected_in_parent_exception(monkeypatch):
    child = Child([{'type': 'result', 'cases': []}], stderr=b'PRIVATE_CREDENTIAL_CANARY')
    install(monkeypatch, child)
    async def mutate(action):
        raise AssertionError('no admin action expected')
    with pytest.raises(RuntimeError, match='node_source_child_failed') as caught:
        asyncio.run(implementation.node_cases({}, mutate))
    assert 'PRIVATE' not in str(caught.value)


def test_native_scenarios_are_unique_bounded_and_source_outage_is_last():
    fixture = json.loads((implementation.ROOT / 'contracts/fixtures/qdrant_source_native.json').read_text())
    assert fixture['revision'] == 'QS-native-r1'
    assert len(fixture['cases']) == len({case['id'] for case in fixture['cases']}) == 14
    assert fixture['cases'][-1]['id'] == 'source_outage'
    assert all(case['setup'] in ('active', 'staging', 'invalid_utf8') for case in fixture['cases'])
    assert all(case['provider_spy_calls'] in (0, 1) for case in fixture['cases'])


def test_child_failure_envelope_accepts_only_fixed_stage_and_error_names(monkeypatch):
    child = Child([{'type': 'failure', 'stage': 'reader_pool_open', 'outcome': 'ProviderUnavailable'}])
    install(monkeypatch, child)
    async def mutate(action):
        raise AssertionError('no admin action expected')
    with pytest.raises(implementation.NodeCaseFailure) as caught:
        asyncio.run(implementation.node_cases({}, mutate))
    assert caught.value.observation == {'stage': 'reader_pool_open', 'outcome': 'ProviderUnavailable'}
    assert child.terminated and child.stdin.closed


def test_private_child_failure_stage_is_rejected_without_reflection(monkeypatch):
    child = Child([{'type': 'failure', 'stage': 'PRIVATE_CREDENTIAL_CANARY', 'outcome': 'ProviderUnavailable'}])
    install(monkeypatch, child)
    async def mutate(action):
        raise AssertionError('no admin action expected')
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(implementation.node_cases({}, mutate))
    assert not isinstance(caught.value, implementation.NodeCaseFailure)
    assert 'PRIVATE' not in str(caught.value)


def test_fixed_handshake_phase_and_error_class_are_preserved(monkeypatch):
    child = Child([{'type': 'failure', 'stage': 'reader_preflight_connect',
                    'outcome': 'tls_error', 'phase': 'tcp_connected', 'error_class': 'TypeError'}])
    install(monkeypatch, child)
    async def mutate(action):
        raise AssertionError('no admin action expected')
    with pytest.raises(implementation.NodeCaseFailure) as caught:
        asyncio.run(implementation.node_cases({}, mutate))
    assert caught.value.observation == {'stage': 'reader_preflight_connect', 'outcome': 'tls_error',
                                         'phase': 'tcp_connected', 'error_class': 'TypeError'}


@pytest.mark.parametrize('change', [{'phase': 'PRIVATE_CREDENTIAL_CANARY'}, {'error_class': 'PRIVATE_SOURCE_TEXT'}])
def test_private_handshake_diagnostic_fields_are_not_reflected(monkeypatch, change):
    frame = {'type': 'failure', 'stage': 'reader_preflight_connect', 'outcome': 'tls_error',
             'phase': 'tcp_connected', 'error_class': 'TypeError'} | change
    child = Child([frame])
    install(monkeypatch, child)
    async def mutate(action):
        raise AssertionError('no admin action expected')
    with pytest.raises(RuntimeError) as caught:
        asyncio.run(implementation.node_cases({}, mutate))
    assert not isinstance(caught.value, implementation.NodeCaseFailure)
    assert 'PRIVATE' not in str(caught.value) and child.terminated and child.stdin.closed
