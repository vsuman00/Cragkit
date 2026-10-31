"""Native worker evidence has a closed scope and content-free diagnostics."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_qdrant_publication_worker import failure_observation, validate_result
from qdrant_publication_worker_cases import CHECKS, publication_worker_input


def test_crash_and_eof_targets_are_independent_immutable_documents():
    from cragkit._qdrant_writer_contract import prepare_stage
    inputs = publication_worker_input()
    stages = [inputs[key] for key in ('stage', 'successor', 'second_stage', 'eof_stage')]
    assert len(json.dumps(inputs).encode()) < 1048576
    assert all(prepare_stage(stage).member_count == 2 for stage in stages)
    base, successor, second, eof = stages
    assert successor['intent']['expected_active_generation_id'] == base['manifest']['generation_id']
    assert successor['intent']['initial_authorization'] is None
    assert len({s['manifest']['document_id'] for s in (base, second, eof)}) == 3
    assert len({m['point_id'] for s in stages for m in s['manifest']['members']}) == 8
    assert all(s['canonical_text'] == base['canonical_text'] for s in stages)
    assert eof['intent']['tenant_id'] == inputs['eof_scope']['tenant_id']
    assert {p['id'] for p in inputs['eof_points']} == {m['point_id'] for m in eof['manifest']['members']}


def test_success_cannot_claim_repair_or_full_fault_completion():
    value = dict(runtime='python', checks=list(CHECKS), proof_scope='ordinary_worker_process_only',
        public_results_sha256='b' * 64)
    assert validate_result(value, 'python') == value
    for changed in (dict(value, checks=value['checks'][:-1]), dict(value, runtime='typescript'),
            dict(value, proof_scope='full_H_matrix'), dict(value, credential='private'),
            dict(value, public_results_sha256='not-a-digest')):
        with pytest.raises(RuntimeError, match='publication_worker_native_result_shape'):
            validate_result(changed, 'python')


def test_failure_keeps_primary_and_cleanup_codes_without_raw_error_text():
    value = dict(ok=False, step=6, error='cleanup_failed', primary='UnauthorizedScope',
        cleanup=[dict(operation='worker_drain', outcome='DeadlineExceeded'),
                 dict(operation='host_close', outcome='ProviderUnavailable')])
    observed = failure_observation(value)
    value['cleanup'].clear()
    assert len(observed['cleanup']) == 2
    for changed in (dict(ok=False, step=True, error='internal'),
            dict(ok=False, step=len(CHECKS) + 1, error='internal'),
            dict(ok=False, step=0, error='ProviderUnavailable', stderr='private'),
            dict(observed, primary={}),
            dict(observed, cleanup=[dict(operation='raw-secret', outcome='internal')])):
        with pytest.raises(RuntimeError, match='publication_worker_native_failure_shape'):
            failure_observation(deepcopy(changed))


def test_supervisor_pause_evidence_has_its_own_closed_scope():
    from qdrant_supervisor_pause_cases import CHECKS as PAUSE_CHECKS, PROOF_SCOPE
    assert len(PAUSE_CHECKS)==len(set(PAUSE_CHECKS))==7
    value=dict(runtime='python',checks=list(PAUSE_CHECKS),proof_scope=PROOF_SCOPE,
        public_results_sha256='c'*64)
    assert validate_result(value,'python',scenario='supervisor_pause')==value
    for changed in (dict(value,checks=list(PAUSE_CHECKS[:-1])),dict(value,private='data'),
                    dict(value,proof_scope='full_H_matrix'),dict(value,runtime='typescript')):
        with pytest.raises(RuntimeError):validate_result(changed,'python',scenario='supervisor_pause')
    with pytest.raises(RuntimeError):validate_result(value,'python')
    assert failure_observation(dict(ok=False,step=7,error='ProviderUnavailable'),scenario='supervisor_pause')['step']==7
    with pytest.raises(RuntimeError):
        failure_observation(dict(ok=False,step=8,error='ProviderUnavailable'),scenario='supervisor_pause')
