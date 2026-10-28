"""Closed native receipt evidence protocol and synthetic source fixtures."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_qdrant_security_verification import validate_result,failure_observation
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


def test_native_receipt_failure_details_are_closed_and_copied():
    for name in ERRORS:assert failure_observation(dict(ok=False,step=0,error=name))['error']==name
    value=dict(ok=False,step=8,error='cleanup_failed',primary=None,cleanup=[dict(operation='verifier_close',outcome='ProviderUnavailable')])
    copied=failure_observation(value);value['cleanup'][0]['outcome']='internal'
    assert copied['cleanup'][0]['outcome']=='ProviderUnavailable'
    for change in (dict(ok=False,step=True,error='internal'),dict(ok=False,step=9,error='internal'),
            dict(ok=False,step=0,error='private'),dict(ok=False,step=0,error='internal',message='private'),
            dict(copied,cleanup=[dict(operation='unknown',outcome='internal')])):
        with pytest.raises(RuntimeError):failure_observation(deepcopy(change))
