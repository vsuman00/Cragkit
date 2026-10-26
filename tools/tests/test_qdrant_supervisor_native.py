"""Native controller checker boundaries, without services or credentials."""
import json
from pathlib import Path
import sys
from types import MappingProxyType
import urllib.error

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_qdrant_supervisor import EXPECTED_CHECKS, failure_observation, validate_result
import qdrant_supervisor_cases as cases


def test_native_input_is_small_synthetic_and_explicit_replay_configuration():
    value = cases.supervisor_input()
    assert value['config']['dense_profile']['provider'] == 'fake'
    assert value['collection_config']['optimizers_config']['prevent_unoptimized'] is False
    assert len(value['points']) == 2
    assert all(len(point['vector']['dense']) == 1536 for point in value['points'])
    assert len(cases.request_bytes(value)) < 262144


def test_immutable_probe_spec_is_copied_without_changing_fixture_values():
    value = MappingProxyType({'vector': (1.0,), 'payload': MappingProxyType({'kind': 'control'})})
    assert json.loads(cases.request_bytes(value)) == {'vector': [1.0], 'payload': {'kind': 'control'}}
    with pytest.raises(RuntimeError, match='supervisor_fixture_metadata_shape'):
        cases.plain(object())
    with pytest.raises(ValueError):
        cases.request_bytes(float('nan'))


def test_success_requires_all_nine_actual_cases_and_physical_scope_only():
    value = dict(runtime='python', checks=list(EXPECTED_CHECKS), proof_scope='process_credentials_profiles_only')
    assert validate_result(value, 'python') == value
    for malformed in [dict(value, checks=value['checks'][:-1]), dict(value, checks=value['checks'][::-1]),
        dict(value, runtime='typescript'), dict(value, proof_scope='sql_settlement'), dict(value, credential='private')]:
        with pytest.raises(RuntimeError, match='supervisor_native_result_shape'):
            validate_result(malformed, 'python')


def test_failure_envelope_has_closed_labels_and_keeps_both_cleanup_outcomes():
    value = dict(ok=False, phase='physical_recovery', error='cleanup_failed', primary='ProviderUnavailable',
        cleanup=[dict(operation='controller_close', outcome='internal'),
                 dict(operation='listener_close', outcome='DeadlineExceeded')])
    observed = failure_observation(value)
    value['cleanup'].clear()
    assert len(observed['cleanup']) == 2
    for malformed in [dict(ok=False, phase='private_endpoint', error='internal'),
        dict(ok=False, phase='input', error='private key'),
        dict(ok=False, phase='input', error='internal', message='private provider detail'),
        dict(ok=False, phase='input', error='cleanup_failed', primary='internal', cleanup=[])]:
        with pytest.raises(RuntimeError, match='supervisor_child_failure_shape'):
            failure_observation(malformed)


def test_old_key_probe_is_limited_to_owned_loopback_and_reports_only_status(monkeypatch):
    touched = []
    class Client:
        def open(self, request, timeout):
            touched.append((request.full_url, timeout))
            raise urllib.error.HTTPError(request.full_url, 401, 'private provider detail', {}, None)
    monkeypatch.setattr(cases.urllib.request, 'build_opener', lambda *args: Client())
    credential = dict(endpoint='http://127.0.0.1:12345', api_key='synthetic-not-a-real-key')
    assert cases.old_key_mutation_status(credential, '/collections/owned/points?wait=true', b'{"points":[]}') == 401
    assert touched == [('http://127.0.0.1:12345/collections/owned/points?wait=true', 3)]
    with pytest.raises(RuntimeError, match='supervisor_fixture_endpoint'):
        cases.old_key_mutation_status(dict(credential, endpoint='https://example.invalid'), '/points', b'{}')
    assert len(touched) == 1


def test_python_case_diagnostics_never_copy_exception_messages():
    error = cases.SupervisorCaseFailure('physical_recovery', RuntimeError('private_key_and_provider_detail'))
    assert error.observation == {'phase': 'physical_recovery', 'error': 'internal'}
    assert 'private' not in str(error)
