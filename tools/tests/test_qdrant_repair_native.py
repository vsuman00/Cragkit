"""Keep native managed repair evidence bounded and distinct from complete repair."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from check_qdrant_repair import validate_result, failure_observation
from qdrant_repair_cases import CHECKS, repair_input


def test_same_document_successors_preserve_pointer_chain_and_global_identity():
    from cragkit._qdrant_writer_contract import prepare_stage
    value=repair_input()
    base,prepared,revoked=[value['stage'],value['stages']['prepared'],value['stages']['cross']]
    assert all(prepare_stage(stage).member_count==2 for stage in (base,prepared,revoked,value['second_stage']))
    assert prepared['intent']['expected_active_generation_id']==base['manifest']['generation_id']
    assert revoked['intent']['expected_active_generation_id']==prepared['manifest']['generation_id']
    assert prepared['manifest']['document_id']==base['manifest']['document_id']==revoked['manifest']['document_id']
    assert value['second_stage']['manifest']['document_id']!=base['manifest']['document_id']
    assert len({member['point_id'] for stage in (base,prepared,revoked,value['second_stage']) for member in stage['manifest']['members']})==8


def test_success_cannot_claim_full_repair_or_incomplete_checks():
    result=dict(runtime='python',checks=list(CHECKS),proof_scope='native_managed_repair_g1a_only')
    assert len(CHECKS)==len(set(CHECKS))==10
    assert CHECKS[-1]=='source_authority_outage_fails_repair_authorization'
    assert validate_result(result,'python')==result
    for changed in (dict(result,runtime='typescript'),dict(result,proof_scope='full_repair'),
                    dict(result,checks=list(CHECKS)[:-1]),dict(result,private='credential')):
        with pytest.raises(RuntimeError,match='repair_native_result_shape'):
            validate_result(changed,'python')


def test_failure_diagnostics_refuse_secret_text_and_unknown_cleanup_actions():
    result=dict(ok=False,step=8,error='cleanup_failed',primary='IntegrityViolation',
                cleanup=[dict(operation='writer_close',outcome='DeadlineExceeded')])
    copy=failure_observation(result)
    result['cleanup'].clear()
    assert len(copy['cleanup'])==1
    for changed in (dict(ok=False,step=True,error='internal'),dict(ok=False,step=99,error='internal'),
                    dict(ok=False,step=0,error='ProviderUnavailable',message='private'),
                    dict(copy,cleanup=[dict(operation='private',outcome='internal')])):
        with pytest.raises(RuntimeError,match='repair_native_failure_shape'):
            failure_observation(deepcopy(changed))
