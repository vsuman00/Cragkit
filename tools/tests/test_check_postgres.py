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


def test_vector_setup_is_separate_locked_transaction_and_checksum_guard():
    item = PG.Migration('0001_pgvector', 'b' * 64, 'SELECT 918273;')
    script = PG.vector_setup_script(item, apply=True)
    assert script.index('BEGIN;') < script.index(PG.LOCK) < script.index(item.sql) < script.index('COMMIT;')
    assert item.checksum in script and item.version in script
    assert 'cragkit_vector.setup_history' in script
    assert 'INSERT INTO cragkit.migration_history' not in script
    assert 'UPDATE cragkit.migration_history' not in script
    assert 'DELETE FROM cragkit.migration_history' not in script
    assert 'lexical_history_changed' in script
    assert 'IF NOT EXISTS' in script
    assert 'statement_timeout' in script and 'lock_timeout' in script
    assert 'idle_in_transaction_session_timeout' in script
    assert 'ENABLE ROW LEVEL SECURITY' in script
    assert 'REVOKE ALL' in script
    assert 'UPDATE cragkit_vector.setup_history' not in script
    assert 'DROP EXTENSION' not in script and 'ALTER EXTENSION' not in script


def test_vector_check_is_read_only_and_never_executes_setup_artifact():
    item = PG.Migration('0001_pgvector', 'c' * 64, 'SELECT 918273;')
    script = PG.vector_setup_script(item, apply=False)
    assert 'SET TRANSACTION READ ONLY' in script
    assert item.sql not in script
    assert 'CREATE ' not in script
    assert 'cragkit_vector.setup_history' in script
    assert item.checksum in script
    assert '0.8.0' in script and 'cragkit_vector' in script
    assert 'CV001' in script and 'CV002' in script


def test_vector_install_requires_apply_before_any_connection(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['check_postgres', '--check', '--install-vector', '--confirm-dedicated-target'])
    connect = lambda *args, **kwargs: pytest.fail('invalid vector flags reached connection setup')
    monkeypatch.setattr(PG, 'connection_environment', connect)
    assert PG.main() == 2


@pytest.mark.parametrize('state,code', [('CV001', 'vector_capability_missing'),
                                      ('CV002', 'vector_capability_unsupported'),
                                      ('CV003', 'vector_version_unavailable')])
def test_vector_compatibility_failures_are_typed_and_redacted(monkeypatch, state, code):
    error = PG.vector_compatibility_error(state)
    assert isinstance(error, PG.VectorCompatibilityError)
    assert str(error) == code
    monkeypatch.setattr(PG.subprocess, 'run', lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 1, stdout='private source',
                                                    stderr=f'psql:<stdin>:12: ERROR:  {state}\nprivate password'))
    with pytest.raises(PG.VectorCompatibilityError, match=code) as caught:
        PG.execute('SELECT 1;', {})
    assert 'private' not in str(caught.value)
    assert PG.vector_compatibility_error('42501') is None


def test_vector_inspection_distinguishes_available_from_installed_and_checks_identity():
    import json
    observed = dict(database='cragkit', user='admin', server_version='17.11',
                    available_version='0.8.0', installed_version=None, installed_schema=None)
    line = 'cragkit_vector_inspection:' + json.dumps(observed)
    assert PG.parse_vector_inspection([line], database='cragkit', user='admin') == observed
    with pytest.raises(PG.PostgresCheckError):
        PG.parse_vector_inspection([line], database='other', user='admin')
    with pytest.raises(PG.PostgresCheckError):
        PG.parse_vector_inspection([line], database='cragkit', user='other')
    for value in ([line, line], ['cragkit_vector_inspection:{}'],
                  ['cragkit_vector_inspection:' + json.dumps({**observed, 'password': 'secret'})],
                  ['cragkit_vector_inspection:' + json.dumps({**observed, 'available_version': 800})]):
        with pytest.raises(PG.PostgresCheckError):
            PG.parse_vector_inspection(value, database='cragkit', user='admin')
    script = PG.vector_inspection_script()
    assert 'pg_available_extension_versions' in script or 'pg_available_extensions' in script
    assert 'pg_extension' in script
    assert 'current_database()' in script and 'current_user' in script
    assert 'CREATE ' not in script and 'DROP ' not in script


def test_managed_vector_primitive_exception_requires_vector_operation(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['check_postgres', '--check', '--confirm-dedicated-target',
                                    '--allow-managed-vector-primitives'])
    monkeypatch.setattr(PG, 'connection_environment', lambda *args, **kwargs:
                        pytest.fail('unbound managed exception reached connection setup'))
    assert PG.main() == 2


def test_managed_vector_profile_preserves_strict_default_and_security_guards():
    item = PG.Migration('0001_pgvector', 'd' * 64, 'SELECT 918273;')
    strict = PG.vector_setup_script(item, apply=False)
    assert strict == PG.vector_setup_script(item, apply=False, allow_managed_primitives=False)
    managed = PG.vector_setup_script(item, apply=False, allow_managed_primitives=True)
    assert managed != strict
    assert 'cloud_admin' in managed and 'cloud_admin' not in strict
    assert 'a.grantee=0' in strict and 'a.grantee=0' not in managed
    assert 'a.grantee NOT IN (0,p.proowner)' in managed
    assert 'extowner=current_user::regrole' in managed
    for script in (strict, managed):
        assert 'SET TRANSACTION READ ONLY' in script
        assert 'pg_depend' in script and 'vector_dims' in script
        assert 'prosecdef' in script
        assert 'nspowner' in script and 'relowner' in script
        assert 'relrowsecurity' in script and 'pg_policy' in script
        assert 'aclexplode' in script
        assert 'CV002' in script
        assert item.sql not in script


@pytest.mark.parametrize('managed', [False, True])
def test_postgres_cli_forwards_managed_exception_only_when_explicit(monkeypatch, managed):
    argv = ['check_postgres', '--check', '--confirm-dedicated-target', '--vector']
    if managed:
        argv.append('--allow-managed-vector-primitives')
    monkeypatch.setattr(sys, 'argv', argv)
    monkeypatch.setattr(PG, 'connection_environment', lambda *args, **kwargs:
                        {'PGDATABASE': 'cragkit', 'PGUSER': 'admin'})
    item = PG.Migration('0001_pgvector', 'e' * 64, 'SELECT 918273;')
    storage = PG.Migration('0002_vector_profiles', 'f' * 64, 'SELECT 2;')
    monkeypatch.setattr(PG, 'migrations', lambda path: [item, storage])
    monkeypatch.setattr(PG, 'execute', lambda *args, **kwargs: [])
    monkeypatch.setattr(PG, 'parse_vector_inspection', lambda *args, **kwargs: {})
    observed = []
    def setup(item, *, apply, allow_managed_primitives=False, storage=None):
        observed.append((apply, allow_managed_primitives))
        return 'synthetic SQL'
    monkeypatch.setattr(PG, 'vector_setup_script', setup)
    assert PG.main() == 0
    assert observed == [(False, managed)]


def test_vector_artifact_uses_effective_owner_revokes_and_global_defaults():
    # Per-schema REVOKE cannot subtract PostgreSQL's global PUBLIC defaults.
    item = PG.migrations(PG.VECTOR_SETUP_DIRECTORY)[0]
    assert item.version == '0001_pgvector'
    assert "VERSION '0.8.0'" in item.sql
    assert "pg_has_role(current_user,p.proowner,'USAGE')" in item.sql
    assert "pg_has_role(current_user,t.typowner,'USAGE')" in item.sql
    for kind in ('TABLES', 'SEQUENCES', 'FUNCTIONS', 'TYPES'):
        assert f'ALTER DEFAULT PRIVILEGES REVOKE ALL ON {kind} FROM PUBLIC;' in item.sql
    assert 'ALTER DEFAULT PRIVILEGES IN SCHEMA' not in item.sql
    for managed in (False, True):
        script = PG.vector_setup_script(item, apply=False, allow_managed_primitives=managed)
        assert 'd.defaclnamespace=0' in script
        assert "to_regnamespace('cragkit_vector')" in script


def test_optional_storage_uses_existing_ledger_and_never_runs_on_check():
    item = PG.migrations(PG.VECTOR_SETUP_DIRECTORY)[1]
    apply = PG.vector_storage_script(item, apply=True)
    check = PG.vector_storage_script(item, apply=False)
    assert apply.index(PG.LOCK) < apply.index(item.sql) < apply.index('INSERT INTO cragkit_vector.setup_history') < apply.index('COMMIT;')
    assert 'SET TRANSACTION READ ONLY' in check and item.sql not in check
    assert item.checksum in check and 'CV002' in check
    assert 'INSERT INTO cragkit.migration_history' not in apply


def test_vector_capability_accepts_only_known_optional_history_prefix():
    items = PG.migrations(PG.VECTOR_SETUP_DIRECTORY)
    script = PG.vector_setup_script(items[0], apply=False, storage=items[1])
    assert 'NOT BETWEEN 1 AND 2' in script
    assert items[1].checksum in script and 'e.version IS NULL OR e.checksum<>h.checksum' in script


@pytest.mark.parametrize('managed', [False, True])
def test_security_script_checks_effective_defaults_and_optional_vector_surfaces(managed):
    script = PG.security_script(allow_managed_primitives=managed)
    profile = 'neon-managed' if managed else 'strict'
    assert f"SET LOCAL cragkit.security_vector_profile = '{profile}';" in script
    assert 'pg_default_acl' in script and 'acldefault(kind.object_type, creator.owner)' in script
    assert 'defaults.defaclnamespace = 0' in script
    assert 'vector_schema_id' in script and 'setup_history' in script
    assert "e.extowner=n.nspowner" in script and 'relrowsecurity' in script
    assert "acl.privilege_type='EXECUTE' AND NOT acl.is_grantable" in script
    assert "r.rolname='cloud_admin'" in script and "d.deptype='e'" in script
    assert "coalesce(current_setting('cragkit.security_vector_profile',true),'strict')" in script
    assert 'ALTER DEFAULT PRIVILEGES' not in script
    assert script.count('BEGIN;') == 1 and script.count('ROLLBACK;') == 1


def test_security_cli_requires_explicit_probe_authorization(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['check_postgres', '--check', '--confirm-dedicated-target', '--security'])
    monkeypatch.setattr(PG, 'connection_environment', lambda *a, **kw: pytest.fail('must not connect'))
    assert PG.main() == 2


@pytest.mark.parametrize('managed', [False, True])
def test_security_cli_runs_separate_gate_and_explicit_vector_exception(monkeypatch, managed):
    argv = ['check_postgres', '--check', '--confirm-dedicated-target', '--security', '--allow-test-writes']
    if managed:
        argv.append('--allow-managed-vector-primitives')
    monkeypatch.setattr(sys, 'argv', argv)
    monkeypatch.setattr(PG, 'connection_environment', lambda *a, **kw: {})
    calls = []
    monkeypatch.setattr(PG, 'execute', lambda script, env, **kw: calls.append((script, kw)))
    assert PG.main() == 0
    assert len(calls) == 2
    assert calls[-1] == (PG.security_script(allow_managed_primitives=managed), {'marker': 'cragkit_security_probe_ok'})
