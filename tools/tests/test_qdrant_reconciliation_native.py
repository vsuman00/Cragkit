"""Bounded E2a harness evidence and private synthetic input admission."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_qdrant_reconciliation import reconciliation_input, validate_result, failure_observation
from qdrant_reconciliation_cases import CHECKS, ReconciliationCaseFailure
from cragkit._qdrant_writer_contract import prepare_stage


def test_native_conflicting_manifest_is_valid_input_with_same_generation_and_new_members():
    value = reconciliation_input()
    original, conflict = value['stage'], value['conflicting_stage']
    assert prepare_stage(original).member_count == prepare_stage(conflict).member_count == 2
    assert original['manifest']['generation_id'] == conflict['manifest']['generation_id']
    assert original['manifest']['revision_id'] == conflict['manifest']['revision_id']
    assert original['intent']['manifest_sha256'] != conflict['intent']['manifest_sha256']
    assert not {m['point_id'] for m in original['manifest']['members']} & {
        m['point_id'] for m in conflict['manifest']['members']}
    assert len(json.dumps(value).encode()) < 524288
    assert value['collection_config']['optimizers_config']['prevent_unoptimized'] is False


def test_native_success_requires_all_actual_cases_and_never_claims_sql_settlement():
    value = dict(runtime='python', checks=list(CHECKS), proof_scope='authority_bound_readback_only',
        normalized_witness_sha256='a'*64)
    assert validate_result(value, 'python') == value
    for changed in [dict(value, runtime='typescript'), dict(value, checks=value['checks'][:-1]),
            dict(value, proof_scope='sql_settlement'), dict(value, source='private'),
            dict(value, normalized_witness_sha256='not-a-digest')]:
        with pytest.raises(RuntimeError, match='reconciliation_native_result_shape'):
            validate_result(changed, 'python')


def test_native_failure_envelope_is_closed_and_preserves_all_cleanup_outcomes():
    value = dict(ok=False, step=3, error='cleanup_failed', primary='IntegrityViolation',
        cleanup=[dict(operation='controller_close', outcome='ProviderUnavailable'),
                 dict(operation='listener_close', outcome='internal')])
    observed = failure_observation(value)
    value['cleanup'].clear()
    assert len(observed['cleanup']) == 2
    for changed in [dict(ok=False, step=True, error='internal'),
            dict(ok=False, step=len(CHECKS)+1, error='internal'), dict(ok=False, step=0, error='private'),
            dict(ok=False, step=0, error='internal', message='private'),
            dict(observed, primary=[]), dict(observed, cleanup=[dict(operation=[], outcome='internal')])]:
        with pytest.raises(RuntimeError, match='reconciliation_native_failure_shape'):
            failure_observation(changed)


def test_python_failure_observation_never_copies_exception_content():
    failure = ReconciliationCaseFailure(2, RuntimeError('private_source_or_credential'))
    assert failure.observation == {'step': 2, 'error': 'internal'}
    assert 'private' not in str(failure)
