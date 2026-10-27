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
    previous = stages['winner']['manifest']['generation_id']
    for key in ('prepared', 'commit', 'session', 'revoked'):
        assert stages[key]['intent']['expected_active_generation_id'] == previous
        previous = stages[key]['manifest']['generation_id']
    assert stages['lost_ack']['intent']['expected_active_generation_id'] == stages['session']['manifest']['generation_id']
    assert stages['lost_ack']['intent']['expected_authorization_revision'] == 'auth-manager-2'
    assert stages['lost_ack']['intent']['expected_mutation_epoch'] == 2


def test_success_requires_complete_public_cases_and_cannot_claim_process_recovery():
    value = dict(runtime='python', checks=list(CHECKS), proof_scope='public_stage_publish_only',
        public_snapshots_sha256='a' * 64)
    assert validate_result(value, 'python') == value
    for changed in [dict(value, checks=value['checks'][:-1]), dict(value, runtime='typescript'),
            dict(value, proof_scope='process_crash_recovery'), dict(value, source='private'),
            dict(value, public_snapshots_sha256='not-a-digest')]:
        with pytest.raises(RuntimeError, match='publication_manager_native_result_shape'):
            validate_result(changed, 'python')


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
