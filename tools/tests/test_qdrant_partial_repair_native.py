"""Bound partial-stage fixture and diagnostic claims before native execution."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_qdrant_partial_repair import failure_observation, validate_result
from qdrant_partial_repair_cases import CHECKS, ERRORS, partial_repair_input


def test_nine_member_successors_are_valid_chained_and_globally_distinct():
    from cragkit._qdrant_writer_contract import prepare_stage

    value = partial_repair_input()
    base = value['stage']['manifest']
    previous = base['generation_id']
    all_ids = [member['point_id'] for member in base['members']]
    assert tuple(value['stages']) == ('partial', 'unknown', 'corrupt', 'foreign')
    for stage in value['stages'].values():
        manifest = stage['manifest']
        assert prepare_stage(stage).member_count == 9
        assert len(stage['dense_vectors']) == len(stage['sparse_vectors']) == 9
        assert stage['intent']['expected_active_generation_id'] == previous
        assert manifest['document_id'] == base['document_id']
        assert manifest['chunker_profile'] == 'fixture-nine-shared-spans-v1'
        assert len({member['chunk_id'] for member in manifest['members']}) == 9
        assert len({(member['start_byte'], member['end_byte'], member['text_sha256'])
                    for member in manifest['members']}) == 1
        ids = sorted(member['point_id'] for member in manifest['members'])
        # The ordinary writer's bounded first dispatch can persist eight points.
        # Losing its reply must leave a genuinely missing ninth member.
        first_batch = ids[:8]
        assert len(first_batch) == 8
        assert set(ids) - set(first_batch) == {ids[8]}
        assert ids[8] == max(ids)
        all_ids.extend(ids)
        previous = manifest['generation_id']
    second = value['second_stage']
    assert prepare_stage(second).member_count == 2
    assert second['manifest']['document_id'] != base['document_id']
    all_ids.extend(member['point_id'] for member in second['manifest']['members'])
    assert len(all_ids) == len(set(all_ids)) == 40


def test_partial_fixture_calls_do_not_share_mutable_manifests_or_vectors():
    first, second = partial_repair_input(), partial_repair_input()
    first['stages']['partial']['manifest']['members'][0]['chunk_id'] = 'changed'
    first['stages']['partial']['dense_vectors'][0][0] = -1.0
    assert second['stages']['partial']['manifest']['members'][0]['chunk_id'] == 'fixture-part-00'
    assert second['stages']['partial']['dense_vectors'][0][0] == 1.0
    assert first['stages']['unknown']['dense_vectors'][0][0] == 1.0


def test_exact_eight_case_scope_is_not_full_g1b_or_release_acceptance():
    assert CHECKS == (
        'partial_nine_point_write_preserves_previous_active',
        'callback_denial_after_reservation_preserves_gate_and_pointer',
        'recovery_sql_ack_loss_confirms_without_http_resend',
        'same_intent_nine_point_publication_with_one_attempt',
        'unknown_recovery_write_cannot_settle_current_credential',
        'actual_refence_rejects_old_key_and_resumes_without_duplicate_recovery_write',
        'corrupt_and_extra_members_rejected_before_recovery_write',
        'foreign_uncertainty_preserved_and_global_reopen_blocked',
    )
    for runtime in ('python', 'typescript'):
        value = dict(runtime=runtime, checks=list(CHECKS), proof_scope='native_partial_repair_only')
        assert validate_result(value, runtime) == value
        for changed in (
            dict(value, runtime='other'), dict(value, proof_scope='full_g1b'),
            dict(value, checks=list(CHECKS)[:-1]), dict(value, checks=list(reversed(CHECKS))),
            dict(value, checks=[CHECKS[0]] * len(CHECKS)), dict(value, checks=tuple(CHECKS)),
            dict(value, private='credential'), None,
        ):
            with pytest.raises(RuntimeError, match='partial_repair_native_result_shape'):
                validate_result(changed, runtime)


def test_closed_failure_errors_and_step_boundaries():
    for error in ERRORS:
        for step in (0, len(CHECKS)):
            value = dict(ok=False, step=step, error=error)
            assert failure_observation(value) == value
    for changed in (
        dict(ok=False, step=True, error='internal'),
        dict(ok=False, step=-1, error='internal'),
        dict(ok=False, step=len(CHECKS) + 1, error='internal'),
        dict(ok=False, step=0.0, error='internal'),
        dict(ok=True, step=0, error='internal'),
        dict(ok=False, step=0, error='private-error-text'),
        dict(ok=False, step=0, error='internal', message='private'),
        dict(ok=False, step=0, error=['internal']),
        None,
    ):
        with pytest.raises(RuntimeError, match='partial_repair_native_failure_shape'):
            failure_observation(changed)


def test_cleanup_failures_preserve_primary_and_independent_records_without_aliasing():
    value = dict(ok=False, step=4, error='cleanup_failed', primary='IntegrityViolation',
                 cleanup=[dict(operation='writer_close', outcome='DeadlineExceeded'),
                          dict(operation='controller_close', outcome='internal')])
    result = failure_observation(value)
    value['cleanup'][0]['outcome'] = 'internal'
    value['cleanup'].clear()
    assert result['primary'] == 'IntegrityViolation'
    assert result['cleanup'] == [dict(operation='writer_close', outcome='DeadlineExceeded'),
                                 dict(operation='controller_close', outcome='internal')]
    assert failure_observation(dict(result, primary=None))['primary'] is None
    for changed in (
        dict(result, primary='private'), dict(result, primary=True),
        dict(result, cleanup=[]), dict(result, cleanup=tuple(result['cleanup'])),
        dict(result, cleanup=result['cleanup'] * 33),
        dict(result, cleanup=[dict(operation='private', outcome='internal')]),
        dict(result, cleanup=[dict(operation='writer_close', outcome='private')]),
        dict(result, cleanup=[dict(operation='writer_close', outcome='internal', message='private')]),
        dict(result, cleanup=[None]), dict(result, message='private'),
    ):
        with pytest.raises(RuntimeError, match='partial_repair_native_failure_shape'):
            failure_observation(deepcopy(changed))
