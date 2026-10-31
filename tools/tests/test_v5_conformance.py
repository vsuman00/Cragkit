"""Common native fixture and closed evidence protocol guards."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_v5_conformance import validate_result
from v5_conformance_fixture import conformance_input,cases,point


def test_common_fixture_has_valid_exact_baseline_and_distinct_partial_inventory():
    from cragkit._qdrant_writer_contract import prepare_stage
    value=conformance_input()
    assert prepare_stage(value['base']).member_count==1
    assert prepare_stage(value['foreign']).member_count==1
    assert prepare_stage(value['pending']).member_count==9
    base=value['base']['manifest'];pending=value['pending']['manifest']
    assert base['document_id']==pending['document_id'] and base['revision_id']!=pending['revision_id']
    assert value['pending']['intent']['expected_active_generation_id']==base['generation_id']
    assert value['foreign']['manifest']['tenant_id']!=base['tenant_id']
    partial=point(value['pending'],0,value['base']['intent']['initial_authorization'])
    assert partial['payload']['generation_id']==pending['generation_id']
    assert partial['vector']['dense'][1]==1 and len(pending['members'])==9
    assert [row['id'] for row in cases(value)]==['unknown','sufficient','partial','no_match','foreign_document','partial_generation','provider_budget']
    value['base']['manifest']['members'].clear()
    assert len(conformance_input()['base']['manifest']['members'])==1


@pytest.mark.parametrize('value',[{},dict(runtime='python',checks=[],route_calls=42,boundary_refusals=8,observations=[],cleanup_verified=True),
    dict(runtime='python',checks=[],route_calls=42,boundary_refusals=8,observations=[],cleanup_verified=True,credential='private')])
def test_incomplete_or_open_evidence_cannot_claim_matrix_completion(value):
    with pytest.raises(RuntimeError):validate_result(deepcopy(value),'python')
