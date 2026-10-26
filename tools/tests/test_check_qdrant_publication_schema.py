"""CLI admission and cleanup reporting without starting a native service."""
import asyncio
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import check_qdrant_publication_schema as checker
from runtime_diagnostics import CleanupFailure


@pytest.mark.parametrize('primary_fails',[False,True])
@pytest.mark.parametrize('close_fails',[False,True])
def test_owned_connection_preserves_primary_and_cleanup_failures(primary_fails,close_fails):
    events=[]
    class Connection:
        async def close(self):
            events.append('close')
            if close_fails: raise ConnectionError('PRIVATE CLOSE CANARY')
    async def run():
        async with checker.owned_connection(Connection()):
            if primary_fails: raise ValueError('PRIVATE PRIMARY CANARY')
    if close_fails or primary_fails:
        with pytest.raises(CleanupFailure if close_fails else ValueError) as error:
            asyncio.run(run())
        if close_fails:
            record=error.value.to_dict()
            assert (record['primary'] is not None)==primary_fails
            assert record['cleanup'][0]['category']=='connection'
            assert 'PRIVATE' not in json.dumps(record)
    else:
        asyncio.run(run())
    assert events==['close']


def test_local_process_opt_in_is_required(tmp_path,monkeypatch):
    monkeypatch.setattr(checker,'PostgresSourceFixture',lambda *args: pytest.fail('unexpected service'))
    with pytest.raises(SystemExit) as error:
        checker.main(['--postgres-bin',str(tmp_path),'--artifacts-dir',str(tmp_path)])
    assert error.value.code == 2


def test_existing_success_artifact_is_preserved_and_cannot_be_reused(tmp_path,monkeypatch,capsys):
    path=tmp_path/'publication-schema-results.json'
    path.write_text('previous result')
    monkeypatch.setattr(checker,'PostgresSourceFixture',lambda *args: pytest.fail('unexpected service'))
    assert checker.main(['--postgres-bin',str(tmp_path),'--artifacts-dir',str(tmp_path), '--allow-local-processes'])==1
    assert json.loads(capsys.readouterr().out)['ok'] is False
    assert path.read_text()=='previous result'


@pytest.mark.parametrize('failure',['none','probe','cleanup'])
def test_success_is_recorded_only_after_probe_and_cleanup(tmp_path,monkeypatch,capsys,failure):
    events=[]
    class Fixture:
        checks=['stopped','private_data_removed']
        def __init__(self,*args): events.append('create')
        def __enter__(self): events.append('start');return self
        def __exit__(self,*args):
            events.append('cleanup')
            if failure=='cleanup': raise RuntimeError('PRIVATE CLEANUP CANARY')
    async def check(fixture):
        events.append('probe')
        if failure=='probe': raise RuntimeError('PRIVATE PROBE CANARY')
        return {'checks':['rls','rollback']}
    monkeypatch.setattr(checker,'PostgresSourceFixture',Fixture)
    monkeypatch.setattr(checker,'check',check)
    result=checker.main(['--postgres-bin',str(tmp_path),'--artifacts-dir',str(tmp_path), '--allow-local-processes'])
    assert events==['create','start','probe','cleanup']
    output=capsys.readouterr().out
    assert 'PRIVATE' not in output
    assert json.loads(output)['ok']==(failure=='none')
    path=tmp_path/'publication-schema-results.json'
    assert path.exists()==(failure=='none')
    assert result==(0 if failure=='none' else 1)
    if path.exists(): assert json.loads(path.read_text())['fixture_checks']==Fixture.checks
