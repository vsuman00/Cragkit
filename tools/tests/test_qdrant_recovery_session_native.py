"""Keep recovery facade evidence limited to actual native transport behavior."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from check_qdrant_recovery_session import validate_result,failure_observation
from qdrant_recovery_session_cases import CHECKS


def test_transport_success_cannot_claim_sql_or_full_partial_repair():
    value=dict(runtime='python',checks=list(CHECKS),proof_scope='recovery_session_transport_only')
    assert validate_result(value,'python')==value
    for changed in (dict(value,proof_scope='complete_repair'),dict(value,checks=list(CHECKS)[:-1]),
                    dict(value,runtime='typescript'),dict(value,key='private')):
        with pytest.raises(RuntimeError,match='recovery_session_native_result_shape'):
            validate_result(changed,'python')


def test_failure_is_closed_and_preserves_independent_cleanup_observations():
    value=dict(ok=False,step=4,error='cleanup_failed',primary='ProviderUnavailable',
        cleanup=[dict(operation='controller_close',outcome='DeadlineExceeded')])
    result=failure_observation(value)
    value['cleanup'].clear()
    assert len(result['cleanup'])==1
    for changed in (dict(ok=False,step=True,error='internal'),dict(ok=False,step=9,error='internal'),
                    dict(ok=False,step=0,error='internal',message='private'),
                    dict(result,cleanup=[dict(operation='manager_close',outcome='internal')])):
        with pytest.raises(RuntimeError,match='recovery_session_native_failure_shape'):
            failure_observation(deepcopy(changed))
