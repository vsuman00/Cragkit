"""Operator admission failures must precede any database process."""
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_postgres_profiles as operator


def copied_inputs(tmp_path):
    for name in ('storage/postgres/setup', 'storage/postgres/migrations', 'contracts/fixtures'):
        shutil.copytree(operator.ROOT / name, tmp_path / name)
    return tmp_path


@pytest.mark.parametrize('name', ['0001_pgvector', '0002_vector_profiles', '0003_openai_te3small_1536'])
def test_changed_setup_artifact_refuses_without_connection(tmp_path, name):
    root = copied_inputs(tmp_path)
    path = root / f'storage/postgres/setup/{name}.sql'
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(operator.PostgresCheckError, match='profile_setup_artifact_drift'):
        operator.profile_upgrade_script(apply=True, root=root)


def test_catalog_reference_drift_is_not_treated_as_database_repair(tmp_path):
    root = copied_inputs(tmp_path)
    path = root / 'contracts/fixtures/postgres_openai_catalog_v6.json'
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(operator.PostgresCheckError, match='profile_catalog_artifact_drift'):
        operator.profile_upgrade_script(apply=True, root=root)


def test_check_mode_contains_no_mutation_and_checks_complete_storage():
    script = operator.profile_upgrade_script(apply=False)
    assert 'SET TRANSACTION READ ONLY' in script
    assert all(word not in script for word in ('CREATE TABLE', 'ALTER TABLE', 'INSERT INTO', 'UPDATE ', 'DELETE FROM'))
    assert 'profile_upgrade_pending' in script
    assert 'profile_setup_history_drift' in script
    assert 'profile_openai_catalog_drift' in script
    assert 'profile_registry_drift' in script


def test_apply_is_one_locked_transaction_and_never_rewrites_old_history():
    script = operator.profile_upgrade_script(apply=True)
    sql = (operator.ROOT / 'storage/postgres/setup/0003_openai_te3small_1536.sql').read_text()
    assert script.index('BEGIN;') < script.index(operator.LOCK) < script.index('profile_setup_history_drift')
    assert script.index('profile_legacy_registry_drift') < script.index(sql) < script.index('COMMIT;')
    assert script.count('INSERT INTO cragkit_vector.setup_history') == 1
    assert 'profile_prior_history_changed' in script
    assert 'INSERT INTO cragkit.migration_history' not in script
    assert 'DROP EXTENSION' not in script and 'GRANT ' not in script
    assert 'statement_timeout' in script and 'lock_timeout' in script


def test_cli_requires_dedicated_target_confirmation(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['check_postgres_profiles', '--apply'])
    monkeypatch.setattr(operator, 'execute', lambda *a, **k: pytest.fail('unconfirmed database process'))
    with pytest.raises(SystemExit) as error:
        operator.main()
    assert error.value.code == 2


def test_cli_sanitizes_database_failure(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['check_postgres_profiles', '--check', '--confirm-dedicated-target'])
    monkeypatch.setattr(operator, 'connection_environment', lambda *a, **k: {})
    def fail(*args, **kwargs):
        raise operator.PostgresCheckError('private-password-and-query')
    monkeypatch.setattr(operator, 'execute', fail)
    assert operator.main() == 1
    assert capsys.readouterr().out == '{"state": "failed", "code": "postgres_profile_check_failed"}\n'


def test_cli_checks_success_marker_and_forwards_fixed_mode(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['check_postgres_profiles', '--check', '--confirm-dedicated-target'])
    monkeypatch.setattr(operator, 'connection_environment', lambda *a, **k: {})
    calls = []
    monkeypatch.setattr(operator, 'execute', lambda script, environment, **kwargs: calls.append((script, kwargs)))
    assert operator.main() == 0
    assert len(calls) == 1 and calls[0][1]['marker'] == operator.MARKER
    assert 'SET TRANSACTION READ ONLY' in calls[0][0]
    assert '"mode": "check"' in capsys.readouterr().out
