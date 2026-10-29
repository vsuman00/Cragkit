"""Native guard fixture admission and output privacy; real SQL uses the opt-in CLI."""
from contextlib import contextmanager
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import check_qdrant_security_guard as checker
from qdrant_security_guard_native import guard_inputs,NAMES


def test_guard_documents_have_separate_canonical_claims_without_changing_source():
    from cragkit._qdrant_writer_contract import prepare_stage
    seen=set();sources=set()
    for name in NAMES:
        inputs,records=guard_inputs(name)
        prepare_stage(inputs['stage'])
        identities={row['point_id'] for row in records['claims']}
        assert len(identities)==2 and not (identities&seen)
        assert identities=={row['point_id'] for row in inputs['stage']['manifest']['members']}
        assert records['document']['document_id']==inputs['stage']['manifest']['document_id']
        seen|=identities;sources.add(inputs['stage']['canonical_text'])
    assert len(seen)==10 and len(sources)==1


def test_guard_cli_refuses_existing_artifacts_without_fixture_or_overwrite(tmp_path,monkeypatch,capsys):
    artifact=tmp_path/'existing';artifact.mkdir();sentinel=artifact/'failure-locations.json';sentinel.write_text('preserved')
    def forbidden(*args,**kwargs):pytest.fail('unowned fixture started')
    monkeypatch.setattr(checker,'PostgresSourceFixture',forbidden)
    assert checker.main(['--postgres-bin',str(tmp_path),'--artifacts-dir',str(artifact),'--allow-local-processes'])==1
    assert sentinel.read_text()=='preserved' and not (artifact/'results.json').exists()
    assert json.loads(capsys.readouterr().out)['ok'] is False


@pytest.mark.parametrize('failure',[None,'body','cleanup'])
def test_guard_cli_closes_fixture_before_success_and_redacts_failures(tmp_path,monkeypatch,capsys,failure):
    events=[]
    @contextmanager
    def fixture(binary,work,*,max_connections):
        assert max_connections==6
        events.append('opened')
        try:yield object()
        finally:
            events.append('closed')
            if failure=='cleanup':raise RuntimeError('PRIVATE DATABASE DETAILS')
    async def check(instance,progress):
        events.append('checked');progress['stage']='restricted_sql_probes'
        if failure=='body':raise RuntimeError('PRIVATE QUERY TEXT')
        return dict(checks=list(checker.SETUP_CHECKS)+list(checker.CHECKS)+list(checker.RACE_CHECKS),
            proof_scope=checker.PROOF_SCOPE,migration={},history=[],catalog_fingerprint='a'*64,query_sha256='b'*64,catalog={})
    monkeypatch.setattr(checker,'PostgresSourceFixture',fixture)
    monkeypatch.setattr(checker,'check',check)
    artifact=tmp_path/'new'
    result=checker.main(['--postgres-bin',str(tmp_path),'--artifacts-dir',str(artifact),'--allow-local-processes'])
    assert events==['opened','checked','closed']
    output=capsys.readouterr().out
    assert 'PRIVATE' not in output and 'QUERY TEXT' not in output
    assert result==(0 if failure is None else 1)
    assert (artifact/'results.json').exists() is (failure is None)
    if failure is None:assert json.loads((artifact/'results.json').read_text())['cleanup_verified'] is True


def test_guard_cli_requires_explicit_process_opt_in(tmp_path):
    with pytest.raises(SystemExit):checker.main(['--postgres-bin',str(tmp_path),'--artifacts-dir',str(tmp_path/'new')])
