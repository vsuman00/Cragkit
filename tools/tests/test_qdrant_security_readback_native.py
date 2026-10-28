"""Native harness contracts stay closed and synthetic before server execution."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_qdrant_security_readback import failure_observation,validate_result
from qdrant_security_readback_cases import CHECKS,ERRORS,security_readback_input


def test_fixture_has_two_generations_one_scope_current_payloads_and_no_shared_mutation():
    from cragkit._qdrant_contract import point_id
    value=security_readback_input()
    points=value['points']
    assert len(points)==4 and len({point['id'] for point in points})==4
    assert [point['id'] for point in points]==sorted(point['id'] for point in points)
    assert len({(point['payload']['revision_id'],point['payload']['generation_id']) for point in points})==2
    for point in points:
        payload=point['payload']
        assert payload['authorization_revision']=='auth-2' and payload['language']=='de'
        assert payload['principal_ids']==payload['grant_ids']==[]
        assert (payload['tenant_id'],payload['collection'],payload['document_id'])==(
            value['context']['scope']['tenant_id'],value['context']['collection'],value['context']['document_id'])
        assert point['id']==point_id(['cragkit.qdrant.point.v1',*[payload[key] for key in (
            'backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id',
            'revision_id','generation_id','chunk_id','dense_profile_id','sparse_profile_id')]])
        assert len(point['vector']['dense'])==1536
    value['points'][0]['vector']['dense'][0]=-9
    assert security_readback_input()['points'][0]['vector']['dense'][0]!=-9


def test_result_scope_is_exactly_eight_backend_observations_without_authority():
    assert len(CHECKS)==8 and len(set(CHECKS))==8
    for runtime in ('python','typescript'):
        value=dict(runtime=runtime,checks=list(CHECKS),proof_scope='security_document_readback_diagnostics_only')
        assert validate_result(value,runtime)==value
        for changed in (dict(value,runtime='other'),dict(value,proof_scope='physical_fencing'),
                dict(value,checks=list(reversed(CHECKS))),dict(value,checks=list(CHECKS[:-1])),
                dict(value,private='source'),None):
            with pytest.raises(RuntimeError,match='security_readback_native_result_shape'):
                validate_result(changed,runtime)


def test_failure_protocol_excludes_details_and_preserves_closed_cleanup_records():
    for name in ERRORS:
        assert failure_observation(dict(ok=False,step=0,error=name))['error']==name
    value=dict(ok=False,step=3,error='cleanup_failed',primary='IntegrityViolation',
        cleanup=[dict(operation='controller_close',outcome='DeadlineExceeded')])
    result=failure_observation(value)
    value['cleanup'][0]['outcome']='internal'
    assert result['cleanup'][0]['outcome']=='DeadlineExceeded'
    for changed in (dict(ok=False,step=True,error='internal'),dict(ok=False,step=9,error='internal'),
            dict(ok=False,step=0,error='private'),dict(ok=False,step=0,error='internal',message='private'),
            dict(result,primary='private'),dict(result,cleanup=[]),
            dict(result,cleanup=[dict(operation='unowned',outcome='internal')]),
            dict(result,cleanup=[dict(operation='controller_close',outcome='private')]),
            dict(result,cleanup=[dict(operation='controller_close',outcome='internal',message='private')])):
        with pytest.raises(RuntimeError,match='security_readback_native_failure_shape'):
            failure_observation(deepcopy(changed))
