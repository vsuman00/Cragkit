"""Harness ownership, parity and combined-failure regressions; no server starts."""
from hashlib import sha256
import json
from pathlib import Path
import sys
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_qdrant as checker
import qdrant_native as native
from runtime_diagnostics import CleanupFailure


def fixture(tmp_path):
    binary = tmp_path / 'binary'
    binary.write_bytes(b'fixture-not-executed')
    return native.QdrantFixture(binary, tmp_path / 'artifacts', sha256(binary.read_bytes()).hexdigest())


def test_binary_identity_required_before_process_start(tmp_path):
    binary = tmp_path / 'binary'
    binary.write_bytes(b'fixture-not-executed')
    with pytest.raises(ValueError, match='qdrant_binary_identity'):
        native.QdrantFixture(binary, tmp_path / 'artifacts', '0' * 64)
    assert not (tmp_path / 'artifacts').exists()


def test_startup_failure_always_closes_owned_state(tmp_path, monkeypatch):
    target = fixture(tmp_path)
    events = []
    def fail():
        raise RuntimeError('synthetic primary')
    monkeypatch.setattr(target, '_start', fail)
    monkeypatch.setattr(target, 'close', lambda: events.append('closed'))
    with pytest.raises(RuntimeError, match='synthetic primary'):
        target.__enter__()
    assert events == ['closed']


def test_startup_and_cleanup_failure_preserve_redacted_categories(tmp_path, monkeypatch):
    target = fixture(tmp_path)
    def fail(): raise TimeoutError('PRIVATE KEY CANARY')
    def close(): raise ConnectionError('PRIVATE KEY CANARY')
    monkeypatch.setattr(target, '_start', fail)
    monkeypatch.setattr(target, 'close', close)
    with pytest.raises(CleanupFailure) as error:
        target.__enter__()
    report = error.value.to_dict()
    assert report['primary']['category'] == 'timeout'
    assert report['cleanup'][0]['category'] == 'connection'
    assert 'PRIVATE' not in json.dumps(report)


def test_exit_preserves_both_failures_and_close_is_idempotent(tmp_path, monkeypatch):
    target = fixture(tmp_path)
    target.close()
    target.close()
    assert 'PRIVATE' not in repr(target)
    def fail(): raise ConnectionError('PRIVATE KEY CANARY')
    monkeypatch.setattr(target, 'close', fail)
    with pytest.raises(CleanupFailure) as error:
        target.__exit__(TimeoutError, TimeoutError('PRIVATE KEY CANARY'), None)
    assert error.value.to_dict()['primary']['category'] == 'timeout'


def test_native_identity_and_parity_are_scope_sensitive():
    data = json.loads((native.ROOT / 'contracts/fixtures/qdrant_candidates.json').read_text())
    payload = data['base_payload']
    assert native.point_identity(payload) == data['point_id_cases'][0]['expected_uuid']
    assert native.point_identity(payload | {'tenant_id': 'other'}) != native.point_identity(payload)
    assert checker.compare({'x': [1.0, 'a']}, {'x': [1.0000001, 'a']})
    assert not checker.compare({'x': True}, {'x': 1})
    assert not checker.compare({'x': 1}, {'x': 1, 'unexpected': 2})
    cases = native.native_cases()
    assert len({c['id'] for c in cases}) == len(cases) == 12


def test_explicit_python_candidate_import_has_no_driver_or_io():
    script = '''
import importlib.abc,sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in ('httpx','psycopg','qdrant_client'):
            raise RuntimeError('optional driver imported')
sys.meta_path.insert(0,Guard())
def audit(event,args):
    if event in ('socket.connect','subprocess.Popen'):
        raise RuntimeError('import I/O')
sys.addaudithook(audit)
import cragkit.qdrant
assert 'httpx' not in sys.modules
print('guarded')
'''
    child = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=5)
    assert child.returncode == 0 and child.stdout.strip() == 'guarded'


def test_explicit_node_candidate_import_has_no_driver_or_io():
    module = (native.ROOT / 'packages/typescript/dist/qdrant.js').as_uri()
    if not (native.ROOT / 'packages/typescript/dist/qdrant.js').exists():
        pytest.skip('Node build is required for guarded optional entrypoint acceptance')
    script = '''
import {registerHooks} from 'node:module';
import net from 'node:net';
registerHooks({resolve(specifier,context,next){
 if(specifier==='pg'||specifier.startsWith('@qdrant/'))throw new Error('optional driver imported');
 return next(specifier,context);
}});
net.Socket.prototype.connect=function(){throw new Error('import socket I/O');};
globalThis.fetch=()=>{throw new Error('import fetch I/O');};
await import(MODULE);
console.log('guarded');
'''.replace('MODULE', json.dumps(module))
    child = subprocess.run(['node', '--input-type=module', '-e', script],
                           capture_output=True, text=True, timeout=5)
    assert child.returncode == 0 and child.stdout.strip() == 'guarded'


def test_dense_only_fixture_cases_keep_scope_failures_and_single_branch_counts():
    cases = native.native_cases(dense_only=True)
    assert len(cases) == 12
    assert all(case.get('count') in (None, 0, 1) for case in cases)
    assert {case['id'] for case in cases} == {case['id'] for case in native.native_cases()}
