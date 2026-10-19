import hashlib
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

SPEC = importlib.util.spec_from_file_location('check_postgres', Path(__file__).resolve().parents[1] / 'check_postgres.py')
assert SPEC and SPEC.loader
PG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PG
SPEC.loader.exec_module(PG)


def test_migrations_hash_exact_bytes_and_reject_gaps_or_psql_commands(tmp_path):
    path = tmp_path / '0001_initial.sql'
    source = b'CREATE TABLE cragkit.fixture(id text);\n'
    path.write_bytes(source)
    item = PG.migrations(tmp_path)[0]
    assert item.checksum == hashlib.sha256(source).hexdigest()
    path.write_bytes(source + b'\n')
    assert PG.migrations(tmp_path)[0].checksum != item.checksum
    path.write_text('\\! unsafe')
    with pytest.raises(PG.PostgresCheckError, match='unsafe_migration_script'):
        PG.migrations(tmp_path)
    path.unlink()
    (tmp_path / '0002_gap.sql').write_text('SELECT 1;')
    with pytest.raises(PG.PostgresCheckError, match='migration_sequence'):
        PG.migrations(tmp_path)


def test_explicit_target_and_remote_certificate_are_required(tmp_path):
    env = {'PGHOST': 'development.invalid', 'PGDATABASE': 'dev', 'PGUSER': 'admin'}
    with pytest.raises(PG.PostgresCheckError, match='confirmation'):
        PG.connection_environment(env, confirmed=False)
    with pytest.raises(PG.PostgresCheckError, match='certificate'):
        PG.connection_environment(env, confirmed=True)
    cert = tmp_path / 'ca.crt'; cert.write_text('fake test CA, not used for connection')
    env.update(PGSSLMODE='verify-full', PGSSLROOTCERT=str(cert))
    result = PG.connection_environment(env, confirmed=True)
    assert result['PGCONNECT_TIMEOUT'] == '10'
    assert 'lock_timeout=5000' in result['PGOPTIONS']
    assert env.get('PGOPTIONS') is None


def test_unix_socket_mode_is_explicit_and_cannot_fall_back_to_tcp(tmp_path):
    env = {'PGHOST': str(tmp_path), 'PGDATABASE': 'test', 'PGUSER': 'admin'}
    result = PG.connection_environment(env, confirmed=True, local_socket=tmp_path)
    assert result['PGSSLMODE'] == 'disable'
    for change in ({'PGHOST': 'localhost'}, {'PGHOSTADDR': '127.0.0.1'}, {'PGSERVICE': 'remote'}):
        with pytest.raises(PG.PostgresCheckError):
            PG.connection_environment({**env, **change}, confirmed=True, local_socket=tmp_path)


def test_runner_wraps_raw_migrations_in_one_locked_checksummed_transaction():
    first = PG.Migration('0001_initial', 'a' * 64, 'CREATE TABLE cragkit.test(id text);')
    script = PG.migration_script([first], apply=True)
    assert script.index('BEGIN;') < script.index(PG.LOCK) < script.index('migration_history_drift') < script.index(first.sql) < script.index('COMMIT;')
    assert first.checksum in script
    assert 'migration_history_gap' in script
    assert 'IF NOT EXISTS (SELECT 1 FROM cragkit.migration_history' in script
    assert 'unmanaged_schema' in script
    check = PG.migration_script([first], apply=False)
    assert first.sql not in check
    assert 'CREATE SCHEMA' not in check
    assert 'pending_migrations' in check


@pytest.mark.parametrize('outcome', ['failure', 'timeout', 'incomplete'])
def test_psql_errors_are_redacted_and_credentials_never_enter_argv(monkeypatch, outcome):
    observed = {}
    def fake(command, **kwargs):
        observed.update(command=command, **kwargs)
        if outcome == 'timeout':
            raise subprocess.TimeoutExpired(command, 120, stderr='private-password')
        return subprocess.CompletedProcess(command, 1 if outcome == 'failure' else 0,
                                           stdout='private-source', stderr='private-password')
    monkeypatch.setattr(PG.subprocess, 'run', fake)
    with pytest.raises(PG.PostgresCheckError) as caught:
        PG.execute('SELECT 1;', {'PGPASSWORD': 'private-password'})
    assert 'private' not in str(caught.value)
    assert 'private-password' not in observed['command']
    assert observed['timeout'] == 120
    assert observed['input'] == 'SELECT 1;'
    assert observed['env']['PGPASSWORD'] == 'private-password'


def test_remote_transport_check_and_success_marker(monkeypatch):
    def fake(command, **kwargs):
        assert 'pg_stat_ssl' in kwargs['input']
        assert '--no-password' in command and '-X' in command
        return subprocess.CompletedProcess(command, 0, stdout='cragkit_migration_ok\n', stderr='')
    monkeypatch.setattr(PG.subprocess, 'run', fake)
    PG.execute('SELECT 1;', {'PGSSLMODE': 'verify-full'})


@pytest.mark.parametrize('override', [
    {'PGSERVICE': 'redirect'}, {'PGSERVICEFILE': '/private/service.conf'},
    {'PGHOSTADDR': '127.0.0.1'}, {'PGHOST': 'remote.invalid,localhost'},
    {'PGHOST': '/tmp'}, {'PGDATABASE': 'postgresql://private:secret@other/db'},
    {'PGDATABASE': 'dbname=other sslmode=disable'}, {'PGUSER': 'admin\nother'},
])
def test_remote_connection_redirection_is_rejected(tmp_path, override):
    cert = tmp_path / 'ca.crt'; cert.touch()
    env = {'PGHOST': 'dedicated.invalid', 'PGDATABASE': 'dev', 'PGUSER': 'admin',
           'PGSSLMODE': 'verify-full', 'PGSSLROOTCERT': str(cert)}
    with pytest.raises(PG.PostgresCheckError):
        PG.connection_environment({**env, **override}, confirmed=True)


def test_local_socket_rejects_database_conninfo(tmp_path):
    with pytest.raises(PG.PostgresCheckError):
        PG.connection_environment({'PGHOST': str(tmp_path), 'PGDATABASE': 'host=elsewhere', 'PGUSER': 'admin'},
                                  confirmed=True, local_socket=tmp_path)
