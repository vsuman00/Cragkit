import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
SPEC = importlib.util.spec_from_file_location('check_neon_postgres', Path(__file__).resolve().parents[1] / 'check_neon_postgres.py')
assert SPEC and SPEC.loader
NEON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(NEON)


class Cursor:
    def __init__(self, results):
        self.results = iter(results)
        self.current = next(self.results)
        self.reads = 0
    @property
    def description(self):
        return None if self.current is None else ('column',)
    async def fetchall(self):
        self.reads += 1
        return self.current
    def nextset(self):
        try:
            self.current = next(self.results)
            return True
        except StopIteration:
            return None


def test_script_drains_results_and_requires_exact_marker():
    cursor = Cursor([None, [('marker', 'extra')], [('marker',)], [('other',)]])
    connection = SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=True), execute=AsyncMock(return_value=cursor))
    asyncio.run(NEON.execute_script(connection, 'synthetic SQL', 'marker'))
    assert cursor.reads == 3
    connection.execute.assert_awaited_once_with('synthetic SQL', prepare=False)


@pytest.mark.parametrize('rows', [[('wrong',)], [('marker', 'extra')], []])
def test_missing_exact_success_marker_fails(rows):
    connection = SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=True), execute=AsyncMock(return_value=Cursor([rows])))
    with pytest.raises(NEON.NeonCheckError, match='missing_success_marker'):
        asyncio.run(NEON.execute_script(connection, 'synthetic SQL', 'marker'))


def test_bad_tls_prevents_any_sql():
    connection = SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=False), execute=AsyncMock())
    with pytest.raises(Exception, match='client_tls_required'):
        asyncio.run(NEON.execute_script(connection, 'synthetic SQL', 'marker'))
    connection.execute.assert_not_awaited()


@pytest.mark.parametrize('flag', ['--integration', '--security'])
def test_test_writes_require_explicit_flag(monkeypatch, flag):
    monkeypatch.setattr(sys, 'argv', ['check_neon_postgres', '--config', '/synthetic.json', '--confirm-dedicated-target', '--check', flag])
    check = AsyncMock()
    monkeypatch.setattr(NEON, 'check', check)
    assert NEON.main() == 2
    check.assert_not_awaited()


def test_dedicated_target_confirmation_required(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['check_neon_postgres', '--config', '/synthetic.json', '--check'])
    with pytest.raises(SystemExit) as caught:
        NEON.main()
    assert caught.value.code == 2


def test_safe_errors_and_explicit_options(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['check_neon_postgres', '--config', '/synthetic.json', '--confirm-dedicated-target',
                                    '--apply', '--harden', '--integration', '--security', '--allow-test-writes'])
    check = AsyncMock(side_effect=RuntimeError('private password SQL rows dsn'))
    monkeypatch.setattr(NEON, 'check', check)
    assert NEON.main() == 1
    output = capsys.readouterr().out
    assert 'private' not in output and 'password' not in output and 'dsn' not in output
    assert check.call_args.kwargs == dict(apply=True, harden=True, integration=True, security=True, vector=False, install_vector=False, allow_managed_primitives=False)


def test_native_wrapper_pins_tls_and_orders_explicit_scripts(monkeypatch, tmp_path):
    config = SimpleNamespace(host='ep-synthetic.c-4.ap-southeast-1.aws.neon.tech', port=5432,
                             dbname='cragkit', user='admin', sslrootcert=Path('/synthetic/ca'),
                             passfile=Path('/synthetic/pass'))
    connection = SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=True), close=AsyncMock())
    connect = AsyncMock(return_value=connection)
    monkeypatch.setitem(sys.modules, 'psycopg', SimpleNamespace(AsyncConnection=SimpleNamespace(connect=connect)))
    checked = []
    monkeypatch.setitem(sys.modules, 'cragkit._postgres_pool', SimpleNamespace(
        parse_pool_config=lambda value: config,
        PoolResource=lambda value: SimpleNamespace(_check_owned_configuration=lambda: checked.append(True))))
    monkeypatch.setattr(NEON, 'load_config', lambda path: {})
    execute = AsyncMock()
    monkeypatch.setattr(NEON, 'execute_script', execute)
    asyncio.run(NEON.check(tmp_path / 'synthetic', apply=True, harden=True, integration=True, security=True))
    assert checked == [True]
    kwargs = connect.call_args.kwargs
    assert kwargs['sslmode'] == 'verify-full' and kwargs['autocommit'] is True
    assert kwargs['connect_timeout'] == 5 and kwargs['sslrootcert'] == '/synthetic/ca'
    assert [call.args[2] for call in execute.call_args_list] == [
        'cragkit_migration_ok', 'cragkit_neon_hardening_ok', 'cragkit_migration_ok', 'cragkit_security_probe_ok']
    assert execute.call_args_list[0].args[1] == NEON.migration_script(
        NEON.migrations(NEON.ROOT / 'storage/postgres/migrations'), apply=True)
    connection.close.assert_awaited_once()
    execute.reset_mock()
    connection.pgconn.ssl_in_use = False
    with pytest.raises(Exception, match='client_tls_required'):
        asyncio.run(NEON.check(tmp_path / 'synthetic', apply=False))
    execute.assert_not_awaited()


def test_vector_install_requires_apply_before_native_dependencies(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['check_neon_postgres', '--config', '/synthetic.json',
                                    '--confirm-dedicated-target', '--check', '--install-vector'])
    check = AsyncMock()
    monkeypatch.setattr(NEON, 'check', check)
    assert NEON.main() == 2
    check.assert_not_awaited()


def test_vector_opt_in_is_forwarded_explicitly(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['check_neon_postgres', '--config', '/synthetic.json',
                                    '--confirm-dedicated-target', '--apply', '--install-vector'])
    check = AsyncMock()
    monkeypatch.setattr(NEON, 'check', check)
    assert NEON.main() == 0
    assert check.call_args.kwargs['vector'] is True
    assert check.call_args.kwargs['install_vector'] is True
    assert check.call_args.kwargs['allow_managed_primitives'] is False


@pytest.mark.parametrize('failure', [RuntimeError('private SQL'), asyncio.CancelledError()])
def test_native_wrapper_closes_connection_after_script_failure(monkeypatch, tmp_path, failure):
    config = SimpleNamespace(host='ep-synthetic.c-4.ap-southeast-1.aws.neon.tech', port=5432,
                             dbname='cragkit', user='admin', sslrootcert=Path('/synthetic/ca'),
                             passfile=Path('/synthetic/pass'))
    connection = SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=True), close=AsyncMock())
    monkeypatch.setitem(sys.modules, 'psycopg', SimpleNamespace(
        AsyncConnection=SimpleNamespace(connect=AsyncMock(return_value=connection))))
    monkeypatch.setitem(sys.modules, 'cragkit._postgres_pool', SimpleNamespace(
        parse_pool_config=lambda value: config,
        PoolResource=lambda value: SimpleNamespace(_check_owned_configuration=lambda: None)))
    monkeypatch.setattr(NEON, 'load_config', lambda path: {})
    execute = AsyncMock(side_effect=failure)
    monkeypatch.setattr(NEON, 'execute_script', execute)
    with pytest.raises(type(failure)):
        asyncio.run(NEON.check(tmp_path / 'synthetic', apply=False))
    connection.close.assert_awaited_once()


@pytest.mark.parametrize('state,code', [('CV001', 'vector_capability_missing'),
                                      ('CV002', 'vector_capability_unsupported'),
                                      ('CV003', 'vector_version_unavailable')])
def test_native_vector_capability_error_preserves_typed_safe_code(state, code):
    class DatabaseError(Exception):
        sqlstate = state
    connection = SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=True),
                                 execute=AsyncMock(side_effect=DatabaseError('private password SQL')))
    with pytest.raises(NEON.VectorCompatibilityError, match=code) as caught:
        asyncio.run(NEON.execute_script(connection, 'synthetic SQL', 'marker'))
    assert 'private' not in str(caught.value)


def test_vector_inspection_precedes_mutation_and_setup_precedes_security(monkeypatch, tmp_path):
    import json
    config = SimpleNamespace(host='ep-synthetic.c-4.ap-southeast-1.aws.neon.tech', port=5432,
                             dbname='cragkit', user='admin', sslrootcert=Path('/synthetic/ca'),
                             passfile=Path('/synthetic/pass'))
    connection = SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=True), close=AsyncMock())
    monkeypatch.setitem(sys.modules, 'psycopg', SimpleNamespace(
        AsyncConnection=SimpleNamespace(connect=AsyncMock(return_value=connection))))
    monkeypatch.setitem(sys.modules, 'cragkit._postgres_pool', SimpleNamespace(
        parse_pool_config=lambda value: config,
        PoolResource=lambda value: SimpleNamespace(_check_owned_configuration=lambda: None)))
    monkeypatch.setattr(NEON, 'load_config', lambda path: {})
    observation = dict(database='cragkit', user='admin', server_version='17.11',
                       available_version='0.8.0', installed_version=None, installed_schema=None)
    async def fake_execute(connection, script, marker):
        if marker == 'cragkit_vector_inspection_ok':
            return ['cragkit_vector_inspection:' + json.dumps(observation), marker]
        return [marker]
    execute = AsyncMock(side_effect=fake_execute)
    monkeypatch.setattr(NEON, 'execute_script', execute)
    asyncio.run(NEON.check(tmp_path / 'synthetic', apply=True, vector=True, install_vector=True, security=True))
    assert [call.args[2] for call in execute.call_args_list] == [
        'cragkit_vector_inspection_ok', 'cragkit_migration_ok', 'cragkit_vector_ok', 'cragkit_security_probe_ok']
    assert execute.call_args_list[2].args[1] == NEON.vector_setup_script(
        NEON.migrations(NEON.VECTOR_SETUP_DIRECTORY)[0], apply=True)
    connection.close.assert_awaited_once()


@pytest.mark.parametrize('failure_stage', ['fetchall', 'nextset'])
def test_deferred_vector_result_errors_are_typed(failure_stage):
    class DatabaseError(Exception):
        sqlstate = 'CV002'
    cursor = Cursor([[('marker',)]])
    if failure_stage == 'fetchall':
        cursor.fetchall = AsyncMock(side_effect=DatabaseError('private SQL'))
    else:
        def fail():
            raise DatabaseError('private SQL')
        cursor.nextset = fail
    connection = SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=True),
                                 execute=AsyncMock(return_value=cursor))
    with pytest.raises(NEON.VectorCompatibilityError, match='vector_capability_unsupported'):
        asyncio.run(NEON.execute_script(connection, 'synthetic SQL', 'marker'))


def test_managed_vector_primitive_exception_requires_vector_operation(monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['check_neon_postgres', '--config', '/synthetic.json',
                                    '--confirm-dedicated-target', '--check', '--allow-managed-vector-primitives'])
    check = AsyncMock()
    monkeypatch.setattr(NEON, 'check', check)
    assert NEON.main() == 2
    check.assert_not_awaited()


@pytest.mark.parametrize('operation', ['--vector', '--install-vector'])
def test_managed_vector_primitive_exception_is_forwarded_explicitly(monkeypatch, operation):
    monkeypatch.setattr(sys, 'argv', ['check_neon_postgres', '--config', '/synthetic.json',
                                    '--confirm-dedicated-target', '--apply', operation,
                                    '--allow-managed-vector-primitives'])
    check = AsyncMock()
    monkeypatch.setattr(NEON, 'check', check)
    assert NEON.main() == 0
    assert check.call_args.kwargs['allow_managed_primitives'] is True
    assert check.call_args.kwargs['vector'] is True
    assert check.call_args.kwargs['install_vector'] is (operation == '--install-vector')
