"""Explicit process admission and honest success/cleanup records for G0 SQL."""
import asyncio
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_qdrant_attestation_schema as checker


def test_native_process_opt_in_is_required(tmp_path, monkeypatch):
    monkeypatch.setattr(checker, 'PostgresSourceFixture', lambda *args: pytest.fail('unexpected service'))
    with pytest.raises(SystemExit) as failure:
        checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(tmp_path/'new')])
    assert failure.value.code == 2


def test_existing_artifacts_are_preserved_without_starting_a_service(tmp_path, monkeypatch, capsys):
    old = tmp_path/'attestation-schema-results.json'
    old.write_text('previous evidence')
    monkeypatch.setattr(checker, 'PostgresSourceFixture', lambda *args: pytest.fail('unexpected service'))
    assert checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(tmp_path), '--allow-local-processes']) == 1
    assert json.loads(capsys.readouterr().out)['ok'] is False
    assert old.read_text() == 'previous evidence'


@pytest.mark.parametrize('failure', ['none', 'probe', 'cleanup'])
def test_success_requires_both_actual_probe_and_fixture_cleanup(tmp_path, monkeypatch, capsys, failure):
    events = []
    class Fixture:
        checks = ['stopped', 'owned_data_removed']
        def __init__(self, *args):
            events.append('create')
        def __enter__(self):
            events.append('start')
            return self
        def __exit__(self, *args):
            events.append('cleanup')
            if failure == 'cleanup':
                raise RuntimeError('PRIVATE CLEANUP CANARY')
    async def check(fixture):
        events.append('probe')
        if failure == 'probe':
            raise RuntimeError('PRIVATE PROBE CANARY')
        return dict(checks=['append_only', 'rollback'], proof_scope='attestation_sql_schema_only')
    monkeypatch.setattr(checker, 'PostgresSourceFixture', Fixture)
    monkeypatch.setattr(checker, 'check', check)
    directory = tmp_path/'run'
    result = checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(directory), '--allow-local-processes'])
    assert events == ['create', 'start', 'probe', 'cleanup']
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output
    assert json.loads(output)['ok'] == (failure == 'none')
    assert result == (0 if failure == 'none' else 1)
    path = directory/'attestation-schema-results.json'
    assert path.exists() == (failure == 'none')
    if path.exists():
        assert json.loads(path.read_text())['fixture_checks'] == Fixture.checks
