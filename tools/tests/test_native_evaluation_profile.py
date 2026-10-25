"""Administrative timing profiles never alter the production retrieval contract."""
import asyncio
import importlib
from pathlib import Path
import subprocess
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
HYBRID = importlib.import_module('check_hybrid')


@pytest.mark.parametrize('value', [None, True, False, '25', 25.0, 60.0, 0, 24, 26, 61, float('inf')])
def test_python_profile_rejects_non_native_or_unlisted_values_before_optional_work(value):
    for name, arguments in (
        ('check_hybrid', (None, None, None)),
        ('check_evidence_native', (None,) * 8),
        ('check_corrective_native', (None,) * 8),
    ):
        module = importlib.import_module(name)
        with pytest.raises(HYBRID.HybridCheckError, match='invalid_evaluation_deadline_seconds'):
            asyncio.run(module.run(*arguments, evaluation_deadline_seconds=value))


def test_python_profile_defaults_and_fixed_choices():
    import inspect
    assert HYBRID.evaluation_profile(25) == 'default'
    assert HYBRID.evaluation_profile(60) == 'high_latency_admin'
    for name in ('check_hybrid', 'check_evidence_native', 'check_corrective_native'):
        assert inspect.signature(importlib.import_module(name).run).parameters['evaluation_deadline_seconds'].default == 25


def test_node_corrective_profile_rejects_malformed_values_before_resource_access():
    subprocess.run(['npm', '--prefix', 'packages/typescript', 'run', 'build'],
                   cwd=TOOLS.parent, capture_output=True, text=True, timeout=60, check=True)
    script = """
import assert from 'node:assert/strict';
import {runCorrective} from './tools/check_typescript_corrective_native.mjs';
const resource=new Proxy({}, {get(){throw Error('resource_touched');}});
for(const value of [null,true,false,'25',0,24,26,61,Infinity,NaN,25.5]) {
  await assert.rejects(runCorrective(resource,[],null,null,value), error=>
    error.code==='ERR_ASSERTION' && error.message.includes('Number.isInteger'));
}
for(const value of [25,60]) {
  await assert.rejects(runCorrective(resource,[],null,null,value), error=>
    error.code==='ERR_ASSERTION' && !error.message.includes('Number.isInteger'));
}
const mismatched=Array.from({length:18},()=>({kind:'labelled',configuration:{mode:'lexical'},
  request:{query:'synthetic',collection:'test'},
  scope:{tenant_id:'tenant',principal_id:'reader',authorization_revision:'rev',grant_ids:[]}}));
await assert.rejects(runCorrective(resource,mismatched,null,null,60),error=>
  error.code==='ERR_ASSERTION' && error.actual===10000 && error.expected===60000);
console.log('profile_validation_passed');
"""
    result = subprocess.run(['node', '--input-type=module', '-e', script],
                            cwd=TOOLS.parent, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'profile_validation_passed'


def test_effective_request_limit_changes_only_in_explicit_high_profile():
    from cragkit.contracts import parse_request
    original = {'max_candidates': 15, 'max_provider_calls': 8, 'max_attempts': 3}
    high = HYBRID.evaluation_limits(60, original)
    default = HYBRID.evaluation_limits(25, original)
    assert original == default and 'deadline_ms' not in original
    assert high == {**original, 'deadline_ms': 60000}
    for selected, expected in ((default, 10000), (high, 60000)):
        request = parse_request({'query': 'synthetic', 'collection': 'test', 'limits': selected})
        assert request.limits.deadline_ms == expected
        assert request.limits.max_candidates == 15 and request.limits.max_attempts == 3
        assert request.limits.max_provider_calls == 8


def test_parent_rejects_inconsistent_effective_fixture_before_child_work():
    with pytest.raises(HYBRID.HybridCheckError, match='node_evaluation_profile_mismatch'):
        asyncio.run(HYBRID.run_node(None, {'evaluation_deadline_seconds': 60,
                                         'effective_evaluation_deadline_ms': 10000}, None))


def test_parent_rejects_child_effective_deadline_mismatch(monkeypatch):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    child = SimpleNamespace(
        stdout=SimpleNamespace(readline=AsyncMock(return_value=json.dumps({
            'state': 'passed', 'acceptance_profile': 'high_latency_admin',
            'evaluation_deadline_seconds': 60, 'effective_evaluation_deadline_ms': 10000}).encode() + b'\n')),
        returncode=None, kill=Mock(), wait=AsyncMock(return_value=0))
    spawn = AsyncMock(return_value=child)
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', spawn)
    fixture = {'evaluation_deadline_seconds': 60, 'effective_evaluation_deadline_ms': 60000,
               'scopes': [{'tenant_id': 'synthetic'}], 'collection': 'synthetic'}
    with pytest.raises(HYBRID.HybridCheckError, match='node_evaluation_profile_mismatch'):
        asyncio.run(HYBRID.run_node(SimpleNamespace(model_dump=lambda **kwargs: {}), fixture,
                                   SimpleNamespace(execute=AsyncMock())))
    spawn.assert_awaited_once()
    child.kill.assert_called_once()
    child.wait.assert_awaited_once()
