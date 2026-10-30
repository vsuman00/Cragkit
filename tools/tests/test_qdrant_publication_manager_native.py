"""Bounded public-manager fixture admission and content-free evidence protocol."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_qdrant_publication_manager import failure_observation, validate_result
from qdrant_publication_manager_cases import CHECKS, publication_manager_input


def test_input_generations_preserve_original_fences_and_bounded_valid_plans():
    from cragkit._qdrant_writer_contract import prepare_stage
    value = publication_manager_input()
    base, stages = value['stage'], value['stages']
    assert len(json.dumps(value).encode()) < 1048576
    assert prepare_stage(base).member_count == 2
    for stage in stages.values():
        assert prepare_stage(stage).member_count == 2
        assert stage['intent']['initial_authorization'] is None
    assert stages['loser']['intent']['expected_active_generation_id'] == base['manifest']['generation_id']
    assert stages['winner']['intent']['expected_active_generation_id'] == base['manifest']['generation_id']
    for key in ('stage_rollback', 'stage_ack_loss'):
        assert stages[key]['intent']['expected_active_generation_id'] == base['manifest']['generation_id']
        assert stages[key]['intent']['intent_id'] != base['intent']['intent_id']
    previous = stages['winner']['manifest']['generation_id']
    for key in ('prepared', 'commit', 'session', 'revoked'):
        assert stages[key]['intent']['expected_active_generation_id'] == previous
        previous = stages[key]['manifest']['generation_id']
    assert stages['lost_ack']['intent']['expected_active_generation_id'] == stages['session']['manifest']['generation_id']
    assert stages['lost_ack']['intent']['expected_authorization_revision'] == 'auth-manager-2'
    assert stages['lost_ack']['intent']['expected_mutation_epoch'] == 2


def test_stage_fault_fixture_describes_one_atomic_stage_boundary():
    cases = json.loads((Path(__file__).resolve().parents[2] / 'contracts/fixtures/qdrant_publication.json').read_text())['cases']
    by_id = {case['id']: case for case in cases}
    rollback = by_id['source_commit_failed']['expected']
    assert rollback['intent'] == rollback['source_revision'] == rollback['members'] == rollback['claims'] == 'absent'
    assert by_id['source_ack_lost']['inject'] == 'atomic stage commit succeeds but acknowledgment is lost'
    assert by_id['claim_ack_lost']['inject'] == 'atomic stage commit acknowledgment is lost after reserving claims'


def test_success_requires_complete_public_cases_and_cannot_claim_process_recovery():
    value = dict(runtime='python', checks=list(CHECKS), proof_scope='public_stage_publish_only',
        public_snapshots_sha256='a' * 64)
    assert validate_result(value, 'python') == value
    for changed in [dict(value, checks=value['checks'][:-1]), dict(value, runtime='typescript'),
            dict(value, proof_scope='process_crash_recovery'), dict(value, source='private'),
            dict(value, public_snapshots_sha256='not-a-digest')]:
        with pytest.raises(RuntimeError, match='publication_manager_native_result_shape'):
            validate_result(changed, 'python')


def test_wrong_dense_mode_has_its_own_closed_evidence_scope():
    value = dict(runtime='python', checks=['wrong_dense_vector_public_publish_rejected'],
        proof_scope='public_corruption_only', public_snapshots_sha256='a' * 64)
    assert validate_result(value, 'python', 'wrong-dense') == value
    for changed in (dict(value, checks=[]), dict(value, proof_scope='public_stage_publish_only'),
            dict(value, runtime='typescript')):
        with pytest.raises(RuntimeError, match='publication_manager_native_result_shape'):
            validate_result(changed, 'python', 'wrong-dense')
    with pytest.raises(RuntimeError, match='publication_manager_native_result_shape'):
        validate_result(value, 'python')
    with pytest.raises(RuntimeError, match='publication_manager_native_scenario'):
        validate_result(value, 'python', 'other')
    with pytest.raises(RuntimeError, match='publication_manager_native_failure_shape'):
        failure_observation(dict(ok=False, step=2, error='internal'), 'wrong-dense')


def test_closed_failure_protocol_preserves_primary_and_cleanup_without_error_text():
    value = dict(ok=False, step=9, error='cleanup_failed', primary='ProviderUnavailable',
        cleanup=[dict(operation='manager_close', outcome='DeadlineExceeded'),
                 dict(operation='controller_close', outcome='internal')])
    observed = failure_observation(value)
    value['cleanup'].clear()
    assert len(observed['cleanup']) == 2
    variants = [dict(ok=False, step=True, error='internal'),
        dict(ok=False, step=len(CHECKS) + 1, error='internal'),
        dict(ok=False, step=0, error='private'),
        dict(ok=False, step=0, error='ProviderUnavailable', message='private'),
        dict(observed, cleanup=[dict(operation='private-source', outcome='internal')]),
        dict(observed, primary=[])]
    for changed in variants:
        with pytest.raises(RuntimeError, match='publication_manager_native_failure_shape'):
            failure_observation(deepcopy(changed))
