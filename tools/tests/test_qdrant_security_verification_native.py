"""Closed native receipt evidence protocol and synthetic source fixtures."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_qdrant_security_verification import validate_result,failure_observation,global_uuid_input
from qdrant_security_verification_cases import CHECKS,ERRORS,security_verification_input


def test_security_receipt_fixture_uses_two_distinct_complete_graphs_and_monotonic_authority():
    from cragkit._qdrant_manifest import encode_security_intent
    from cragkit._qdrant_writer_contract import prepare_stage
    value=security_verification_input()
    stages=[value['stage'],value['second_stage']]
    for stage in stages:prepare_stage(stage)
    ids=[member['point_id'] for stage in stages for member in stage['manifest']['members']]
    assert len(ids)==len(set(ids))==4
    assert len({stage['manifest']['generation_id'] for stage in stages})==2
    for name in ('security','tombstone'):encode_security_intent(value[name])
    prepare_stage(value['ownerless_stage'])
    encode_security_intent(value['ownerless_security'])
    assert value['ownerless_stage']['manifest']['document_id']!=value['stage']['manifest']['document_id']
    assert value['ownerless_security']['document_id']==value['ownerless_stage']['manifest']['document_id']
    assert value['security']['authorization']['authorization_revision']=='auth-2'
    assert not value['security']['authorization']['tombstoned']
    assert value['tombstone']['authorization']['authorization_revision']=='auth-3'
    assert value['tombstone']['authorization']['tombstoned']
    value['stage']['dense_vectors'][0][0]=99
    assert security_verification_input()['stage']['dense_vectors'][0][0]!=99


def test_native_receipt_protocol_never_claims_settlement_or_convergence():
    assert len(CHECKS)==len(set(CHECKS))==8
    for runtime in ('python','typescript'):
        value=dict(runtime=runtime,checks=list(CHECKS),proof_scope='native_security_receipt_only',semantic_witness_sha256='a'*64)
        assert validate_result(value,runtime)==value
        for change in (dict(value,proof_scope='settled'),dict(value,runtime='other'),dict(value,checks=[]),dict(value,private='data'),dict(value,semantic_witness_sha256='PRIVATE')):
            with pytest.raises(RuntimeError):validate_result(change,runtime)


def test_repetition_evidence_is_exclusive_and_cannot_be_receipt_or_purge_evidence():
    from qdrant_security_verification_cases import REPETITION_CHECKS,GUARD_CHECKS
    value=dict(runtime='python',checks=list(REPETITION_CHECKS),proof_scope='native_security_repetition_only',
        semantic_witness_sha256='a'*64,guard_admission=dict(checks=list(GUARD_CHECKS),denied_backend_queries=0))
    assert validate_result(value,'python',security_guard=True,security_repetition=True)==value
    for options in ({},{'security_repetition':True},{'security_guard':True,'security_repetition':True,'security_completion':True}):
        with pytest.raises(RuntimeError):validate_result(value,'python',**options)
    for changed in (dict(value,proof_scope='physical_purge'),dict(value,checks=[]),dict(value,private='text')):
        with pytest.raises(RuntimeError):validate_result(changed,'python',security_guard=True,security_repetition=True)


def test_public_security_evidence_has_its_own_complete_closed_observations():
    from qdrant_public_security_cases import CHECKS as PUBLIC_CHECKS
    value=dict(runtime='python',checks=list(PUBLIC_CHECKS),proof_scope='native_public_security_convergence_only',
        semantic_witness_sha256='a'*64)
    assert len(PUBLIC_CHECKS)==len(set(PUBLIC_CHECKS))==10
    assert PUBLIC_CHECKS[3]=='acl_replica_ack_lost_replays_current_revocation'
    assert PUBLIC_CHECKS[4]=='revocation_between_stages_denies_stale_publication'
    assert validate_result(value,'python',public_security=True)==value
    for changed in (dict(value,checks=[]),dict(value,proof_scope='native_security_repetition_only'),
                    dict(value,private='source'),dict(value,semantic_witness_sha256=True)):
        with pytest.raises(RuntimeError):validate_result(changed,'python',public_security=True)
    with pytest.raises(RuntimeError):validate_result(value,'python',public_security=True,security_repetition=True)
    with pytest.raises(RuntimeError):validate_result(value,'python')


def test_native_receipt_failure_details_are_closed_and_copied():
    for name in ERRORS:assert failure_observation(dict(ok=False,step=0,error=name))['error']==name
    value=dict(ok=False,step=8,error='cleanup_failed',primary=None,cleanup=[dict(operation='verifier_close',outcome='ProviderUnavailable')])
    copied=failure_observation(value);value['cleanup'][0]['outcome']='internal'
    assert copied['cleanup'][0]['outcome']=='ProviderUnavailable'
    for change in (dict(ok=False,step=True,error='internal'),dict(ok=False,step=9,error='internal'),
            dict(ok=False,step=0,error='private'),dict(ok=False,step=0,error='internal',message='private'),
            dict(copied,cleanup=[dict(operation='unknown',outcome='internal')])):
        with pytest.raises(RuntimeError):failure_observation(deepcopy(change))


def test_old_acl_late_result_is_closed_to_its_exact_native_scenario():
    from qdrant_old_acl_late_cases import CHECKS as OLD_ACL_CHECKS
    value=dict(runtime='python',checks=list(OLD_ACL_CHECKS),
        proof_scope='native_old_acl_late_upsert_only',semantic_witness_sha256='a'*64)
    assert validate_result(value,'python',security_guard=True,old_acl_late=True)==value
    for changed in (dict(value,checks=list(OLD_ACL_CHECKS[:-1])),
                    dict(value,proof_scope='native_public_security_convergence_only'),
                    dict(value,private_credential='secret'),
                    dict(value,semantic_witness_sha256='invalid')):
        with pytest.raises(RuntimeError,match='old_acl_late_native_result_shape'):
            validate_result(changed,'python',security_guard=True,old_acl_late=True)
    for options in ({'old_acl_late':True},
                    {'security_guard':True,'old_acl_late':True,'public_security':True}):
        with pytest.raises(RuntimeError,match='old_acl_late_native_result_shape'):
            validate_result(value,'python',**options)
    assert failure_observation(dict(ok=False,step=len(OLD_ACL_CHECKS),error='ProviderUnavailable'),
        max_checks=len(OLD_ACL_CHECKS))['step']==len(OLD_ACL_CHECKS)
    with pytest.raises(RuntimeError,match='security_verification_native_failure_shape'):
        failure_observation(dict(ok=False,step=len(OLD_ACL_CHECKS)+1,error='ProviderUnavailable'),
            max_checks=len(OLD_ACL_CHECKS))


def test_public_security_failure_step_accepts_its_ten_native_checks():
    from qdrant_public_security_cases import CHECKS as PUBLIC_CHECKS
    assert len(PUBLIC_CHECKS)==10
    value=dict(ok=False,step=len(PUBLIC_CHECKS),error='ProviderUnavailable')
    assert failure_observation(value,max_checks=len(PUBLIC_CHECKS))==value
    with pytest.raises(RuntimeError,match='security_verification_native_failure_shape'):
        failure_observation(dict(value,step=len(PUBLIC_CHECKS)+1),max_checks=len(PUBLIC_CHECKS))


def test_tombstone_repair_result_cannot_claim_other_security_scenarios():
    from qdrant_tombstone_repair_cases import CHECKS as TOMBSTONE_REPAIR_CHECKS
    value=dict(runtime='python',checks=list(TOMBSTONE_REPAIR_CHECKS),
        proof_scope='native_tombstone_during_repair_only',semantic_witness_sha256='b'*64)
    assert validate_result(value,'python',security_guard=True,tombstone_repair=True)==value
    for changed in (dict(value,checks=list(TOMBSTONE_REPAIR_CHECKS[:-1])),
                    dict(value,proof_scope='native_old_acl_late_upsert_only'),
                    dict(value,private_source='secret'),dict(value,semantic_witness_sha256='bad')):
        with pytest.raises(RuntimeError,match='tombstone_repair_native_result_shape'):
            validate_result(changed,'python',security_guard=True,tombstone_repair=True)
    for options in ({'tombstone_repair':True},
                    {'security_guard':True,'tombstone_repair':True,'old_acl_late':True}):
        with pytest.raises(RuntimeError,match='tombstone_repair_native_result_shape'):
            validate_result(value,'python',**options)
    assert failure_observation(dict(ok=False,step=len(TOMBSTONE_REPAIR_CHECKS),error='ProviderUnavailable'),
        max_checks=len(TOMBSTONE_REPAIR_CHECKS))['step']==len(TOMBSTONE_REPAIR_CHECKS)


def test_global_uuid_collision_fixture_targets_one_distinct_document_identity():
    from cragkit._qdrant_contract import point_id
    from cragkit._qdrant_writer_contract import prepare_stage
    value=global_uuid_input()
    for key in ('baseline_a','baseline_b','successor_a'):
        prepare_stage(value[key])
    a,b=value['successor_a'],value['successor_b']
    assert a['manifest']['document_id']!=b['manifest']['document_id']
    assert a['manifest']['members'][0]['point_id']==b['manifest']['members'][0]['point_id']==value['collision_uuid']
    assert point_id(value['collision_tuple'])!=value['collision_uuid']
    assert b['manifest']['members'][1]['point_id']!=value['collision_uuid']


def test_global_uuid_result_is_closed_to_exact_collision_scenario():
    from qdrant_global_uuid_cases import CHECKS as GLOBAL_UUID_CHECKS
    value=dict(runtime='python',checks=list(GLOBAL_UUID_CHECKS),
        proof_scope='native_global_uuid_collision_only',semantic_witness_sha256='a'*64)
    assert validate_result(value,'python',global_uuid=True)==value
    for changed in (dict(value,checks=list(GLOBAL_UUID_CHECKS[:-1])),
                    dict(value,proof_scope='native_tombstone_during_repair_only'),
                    dict(value,private_source='secret'),dict(value,semantic_witness_sha256='bad')):
        with pytest.raises(RuntimeError,match='global_uuid_native_result_shape'):
            validate_result(changed,'python',global_uuid=True)
    for flags in ({},{'global_uuid':True,'security_guard':True},{'global_uuid':True,'tombstone_repair':True}):
        with pytest.raises(RuntimeError):validate_result(value,'python',**flags)
    assert failure_observation(dict(ok=False,step=len(GLOBAL_UUID_CHECKS),error='IntegrityViolation'),
        max_checks=len(GLOBAL_UUID_CHECKS))['step']==len(GLOBAL_UUID_CHECKS)


def test_guard_mode_evidence_requires_its_closed_checks_without_claiming_settlement():
    from qdrant_security_verification_cases import GUARD_CHECKS
    baseline=dict(runtime='python',checks=list(CHECKS),proof_scope='native_security_receipt_only',semantic_witness_sha256='a'*64)
    guarded=dict(baseline,guard_admission=dict(checks=list(GUARD_CHECKS),denied_backend_queries=0))
    accepted=validate_result(guarded,'python',security_guard=True)
    with pytest.raises(RuntimeError):validate_result(guarded,'python')
    with pytest.raises(RuntimeError):validate_result(baseline,'python',security_guard=True)
    for change in (dict(checks=[],denied_backend_queries=0),dict(checks=list(GUARD_CHECKS),denied_backend_queries=True),
            dict(checks=list(GUARD_CHECKS),denied_backend_queries=1),dict(checks=list(GUARD_CHECKS),denied_backend_queries=0,private='source')):
        with pytest.raises(RuntimeError):validate_result(dict(baseline,guard_admission=change),'python',security_guard=True)
    guarded['guard_admission']['checks'].clear()
    assert accepted['guard_admission']['checks']==list(GUARD_CHECKS)


def test_guarded_graph_mode_keeps_closed_evidence_and_requires_guard_admission():
    from check_qdrant_security_verification import GRAPH_CHECKS
    from qdrant_security_verification_cases import GUARD_CHECKS
    baseline=dict(runtime='python',checks=list(CHECKS),proof_scope='native_security_receipt_only',semantic_witness_sha256='a'*64)
    baseline['guard_admission']=dict(checks=list(GUARD_CHECKS),denied_backend_queries=0)
    value=dict(baseline,guarded_graph=dict(checks=list(GRAPH_CHECKS),denied_commits=0))
    accepted=validate_result(value,'python',security_guard=True,guarded_graph=True)
    with pytest.raises(RuntimeError):validate_result(value,'python',security_guard=True)
    for graph in (dict(checks=list(GRAPH_CHECKS),denied_commits=True),dict(checks=list(GRAPH_CHECKS),denied_commits=1),
            dict(checks=[],denied_commits=0),dict(checks=list(GRAPH_CHECKS),denied_commits=0,source='private')):
        with pytest.raises(RuntimeError):validate_result(dict(baseline,guarded_graph=graph),'python',security_guard=True,guarded_graph=True)
    value['guarded_graph']['checks'].clear()
    assert accepted['guarded_graph']['checks']==list(GRAPH_CHECKS)


def test_security_settlement_evidence_is_closed_and_requires_exclusive_guard_profile():
    from qdrant_security_verification_cases import GUARD_CHECKS, SETTLEMENT_CHECKS
    baseline=dict(runtime='python',checks=list(CHECKS),proof_scope='native_security_receipt_only',semantic_witness_sha256='a'*64,
        guard_admission=dict(checks=list(GUARD_CHECKS),denied_backend_queries=0))
    value=dict(baseline,security_settlement=dict(checks=list(SETTLEMENT_CHECKS),confirmation_writes=0))
    accepted=validate_result(value,'python',security_guard=True,security_settlement=True)
    for flags in ({},{'security_guard':True},{'security_settlement':True},
            {'security_guard':True,'security_settlement':True,'guarded_graph':True}):
        with pytest.raises(RuntimeError):validate_result(value,'python',**flags)
    for settlement in (dict(checks=[],confirmation_writes=0),dict(checks=list(SETTLEMENT_CHECKS),confirmation_writes=True),
            dict(checks=list(SETTLEMENT_CHECKS),confirmation_writes=1),
            dict(checks=list(SETTLEMENT_CHECKS),confirmation_writes=0,private='data')):
        with pytest.raises(RuntimeError):
            validate_result(dict(baseline,security_settlement=settlement),'python',security_guard=True,security_settlement=True)
    value['security_settlement']['checks'].clear()
    assert accepted['security_settlement']['checks']==list(SETTLEMENT_CHECKS)


def test_security_dispatch_evidence_requires_its_own_exclusive_native_scope():
    from qdrant_security_verification_cases import GUARD_CHECKS, DISPATCH_CHECKS
    value=dict(runtime='python',checks=list(DISPATCH_CHECKS),proof_scope='native_security_dispatch_only',semantic_witness_sha256='a'*64,
        guard_admission=dict(checks=list(GUARD_CHECKS),denied_backend_queries=0))
    assert validate_result(value,'python',security_guard=True,security_dispatch=True)==value
    for flags in ({},{'security_guard':True},{'security_dispatch':True},
            {'security_guard':True,'security_dispatch':True,'security_settlement':True},
            {'security_guard':True,'security_dispatch':True,'guarded_graph':True}):
        with pytest.raises(RuntimeError):validate_result(value,'python',**flags)
    for change in (dict(value,checks=list(CHECKS)),dict(value,proof_scope='native_security_receipt_only'),dict(value,checks=[])):
        with pytest.raises(RuntimeError):validate_result(change,'python',security_guard=True,security_dispatch=True)


def test_security_completion_protocol_is_exclusive_and_has_a_separate_proof_scope():
    from qdrant_security_verification_cases import GUARD_CHECKS, COMPLETION_CHECKS
    value=dict(runtime='python',checks=list(COMPLETION_CHECKS),proof_scope='native_security_completion_only',semantic_witness_sha256='a'*64,
        guard_admission=dict(checks=list(GUARD_CHECKS),denied_backend_queries=0))
    assert validate_result(value,'python',security_guard=True,security_completion=True)==value
    for flags in ({},{'security_completion':True},{'security_guard':True},
            {'security_guard':True,'security_completion':True,'security_dispatch':True},
            {'security_guard':True,'security_completion':True,'guarded_graph':True},
            {'security_guard':True,'security_completion':True,'security_settlement':True}):
        with pytest.raises(RuntimeError):validate_result(value,'python',**flags)
    with pytest.raises(RuntimeError):
        validate_result(dict(value,proof_scope='native_security_dispatch_only'),'python',security_guard=True,security_completion=True)
