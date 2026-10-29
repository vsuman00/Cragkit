"""Native writer evidence boundaries; PostgreSQL runs are separate."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import check_qdrant_guard_writer as checker
from qdrant_guard_writer_cases import CHECKS,NativeGuardWriterFailure,failure_observation


def test_result_cannot_claim_settlement_or_hide_denied_business_queries():
    for runtime in ('python','typescript'):
        value=dict(runtime=runtime,checks=list(CHECKS),proof_scope='profile4_writer_admission_only',scope_queries=6,denied_scope_queries=0)
        accepted=checker.validate_result(value,runtime)
        for change in (dict(value,proof_scope='settled'),dict(value,denied_scope_queries=1),
                dict(value,scope_queries=True),dict(value,checks=list(reversed(CHECKS))),dict(value,private='source')):
            with pytest.raises(RuntimeError):checker.validate_result(change,runtime)
        value['checks'].clear()
        assert accepted['checks']==list(CHECKS)


def test_closed_failure_retains_primary_and_owns_nested_cleanup():
    value=dict(ok=False,step=4,error='cleanup_failed',primary='UnsupportedCapability',
        cleanup=[dict(operation='writer_close',outcome='ProviderUnavailable')])
    original=deepcopy(value);error=NativeGuardWriterFailure(value)
    value['cleanup'][0]['outcome']='private'
    assert error.observation==original
    for change in (dict(original,primary='cleanup_failed'),dict(original,step=True),
            dict(original,cleanup=[dict(operation='unowned_cleanup',outcome='internal')]),dict(original,sql='private')):
        with pytest.raises(RuntimeError):failure_observation(change)


def test_existing_artifacts_are_never_modified(tmp_path,monkeypatch,capsys):
    evidence=tmp_path/'failure-locations.json';evidence.write_text('original')
    monkeypatch.setattr(checker,'PostgresSourceFixture',lambda *args,**kwargs:pytest.fail('unexpected server'))
    assert checker.main(['--postgres-bin',str(tmp_path/'bin'),'--artifacts-dir',str(tmp_path),
        '--allow-local-processes'])==1
    assert json.loads(capsys.readouterr().out)['ok'] is False
    assert list(tmp_path.iterdir())==[evidence] and evidence.read_text()=='original'
