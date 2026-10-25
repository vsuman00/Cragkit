"""Synthetic checks for explicit Neon fixture transport and secret handling."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SPEC = importlib.util.spec_from_file_location('check_python_postgres', Path(__file__).resolve().parents[1] / 'check_python_postgres.py')
assert SPEC and SPEC.loader
PG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PG
SPEC.loader.exec_module(PG)

HOST = 'ep-plain-queen-b37i9a2b.c-4.ap-southeast-1.aws.neon.tech'


def test_explicit_neon_mode_requires_direct_neon_dns():
    PG.require_neon_host(HOST)
    for host in (HOST.replace('.c-4', '-pooler.c-4'), 'localhost', '127.0.0.1',
                 HOST + '.attacker.invalid', 'postgresql://' + HOST, 'other.neon.tech'):
        with pytest.raises(PG.RuntimeCheckError, match='direct_neon_host_required'):
            PG.require_neon_host(host)


@pytest.mark.parametrize('state', [False, None, 'true', 1])
def test_plaintext_password_refused_without_actual_client_tls(state):
    encrypt_calls = []
    connection = SimpleNamespace(pgconn=SimpleNamespace(
        ssl_in_use=state, encrypt_password=lambda *args: encrypt_calls.append(args)))
    with pytest.raises(PG.RuntimeCheckError, match='client_tls_required'):
        PG.fixture_password(connection, 'synthetic-secret', 'probe', neon=True)
    assert encrypt_calls == []


def test_default_preserves_scram_and_explicit_neon_uses_verified_tls_plain_password():
    calls = []
    def encrypt(*args):
        calls.append(args)
        return b'synthetic-scram-verifier'
    connection = SimpleNamespace(pgconn=SimpleNamespace(ssl_in_use=True, encrypt_password=encrypt))
    assert PG.fixture_password(connection, 'synthetic-secret', 'probe') == 'synthetic-scram-verifier'
    assert calls == [(b'synthetic-secret', b'probe', b'scram-sha-256')]
    calls.clear()
    assert PG.fixture_password(connection, 'synthetic-secret', 'probe', neon=True) == 'synthetic-secret'
    assert calls == []


def test_no_pgconn_cannot_establish_tls():
    with pytest.raises(PG.RuntimeCheckError, match='client_tls_required'):
        PG.require_client_tls(SimpleNamespace())


@pytest.mark.parametrize('error', [RuntimeError("CREATE ROLE PASSWORD 'synthetic-secret'"),
                                 PG.RuntimeCheckError("synthetic-secret")])
def test_cli_exception_output_never_prints_password_or_rendered_sql(monkeypatch, capsys, error):
    monkeypatch.setattr(sys, 'argv', ['check_python_postgres.py', '--config', '/unused/private.json',
                                    '--allow-test-writes', '--neon'])
    check = AsyncMock(side_effect=error)
    monkeypatch.setattr(PG, 'check', check)
    assert PG.main() == 1
    output = capsys.readouterr().out
    assert 'synthetic-secret' not in output
    assert 'CREATE ROLE' not in output
    assert check.call_args.kwargs['neon'] is True


def test_fixture_allows_declared_cleanup_after_request_expiry_without_second_cancel():
    async def run():
        async def completed_after_cleanup():
            await asyncio.sleep(0.03)
            raise PG.RuntimeCheckError('synthetic_request_expired')
        task = asyncio.create_task(completed_after_cleanup())
        # An already-expired request can still finish its two cleanup phases.
        with pytest.raises(PG.RuntimeCheckError, match='synthetic_request_expired'):
            await PG.await_fixture_completion(task, deadline=asyncio.get_running_loop().time() - 0.01,
                                             release_timeout=0.05)
        assert not task.cancelled()
    asyncio.run(run())


def test_fixture_does_not_wait_beyond_request_and_declared_cleanup_budgets():
    async def run():
        stopped = asyncio.Event()
        async def hung():
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        task = asyncio.create_task(hung())
        with pytest.raises(TimeoutError):
            await PG.await_fixture_completion(task, deadline=asyncio.get_running_loop().time(),
                                             release_timeout=0.01)
        assert task.cancelled() and stopped.is_set()
    asyncio.run(run())


def test_dense_cli_remains_explicit_and_rejects_staging_only_mode(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['check_python_postgres.py', '--config', '/unused/private.json', '--dense'])
    check = AsyncMock(return_value={'state': 'passed'})
    monkeypatch.setattr(PG, 'check', check)
    assert PG.main() == 2
    assert not check.called
    monkeypatch.setattr(sys, 'argv', ['check_python_postgres.py', '--config', '/unused/private.json',
                                    '--allow-test-writes', '--dense', '--typescript'])
    assert PG.main() == 0
    assert check.call_args.kwargs['dense'] is True
    assert check.call_args.kwargs['typescript'] is True
    check.reset_mock()
    monkeypatch.setattr(sys, 'argv', ['check_python_postgres.py', '--config', '/unused/private.json',
                                    '--allow-test-writes', '--dense', '--vector-stage-only', '--vectors', '--typescript'])
    assert PG.main() == 2
    assert not check.called


def test_hybrid_cli_is_explicit_and_cannot_mix_staging_or_dense_modes(monkeypatch, capsys):
    check = AsyncMock(return_value={'state':'passed'})
    monkeypatch.setattr(PG,'check',check)
    base=['check_python_postgres.py','--config','/unused/private.json','--hybrid']
    monkeypatch.setattr(sys,'argv',base)
    assert PG.main()==2 and not check.called
    for extra in (['--dense'],['--vector-stage-only']):
        monkeypatch.setattr(sys,'argv',[*base,'--allow-test-writes',*extra])
        assert PG.main()==2 and not check.called
    monkeypatch.setattr(sys,'argv',[*base,'--allow-test-writes','--typescript'])
    assert PG.main()==0
    assert check.call_args.kwargs['hybrid'] is True


def test_base_child_fixture_contains_only_synthetic_scope_data():
    import json
    fixture = PG.base_child_fixture('synthetic', ['tenant-a', 'tenant-b'],
                                    ['principal-a', 'principal-b'], neon=True)
    serialized = json.dumps(fixture)
    assert set(fixture) == {'collection', 'scopes', 'expected_documents', 'neon'}
    assert 'admin' not in serialized
    assert 'passfile' not in serialized
    assert 'password' not in serialized
    assert fixture['expected_documents'] == [['document-0', 'revision-0'],
                                              ['document-1', 'revision-1']]


def test_base_parent_serializes_allowlisted_fixture_and_child_never_reads_admin_config():
    import inspect
    parent = inspect.getsource(PG.check)
    child = Path(PG.__file__).with_name('check_typescript_postgres.mjs').read_text()
    assert 'fixture = base_child_fixture(collection, tenants, principals, neon=neon)' in parent
    assert "'admin_config'" not in parent
    assert 'adminResource' not in child
    assert 'admin_config' not in child
    assert 'unsafe_admin_rejected' not in child
    assert 'parent_unsafe_administrator_role_rejected' in parent
    assert "'checks': completed + result.get('checks', [])" in parent


@pytest.mark.parametrize('result', [[(False,)], [(True,)], [], [(None,)], [(False,), (False,)]])
def test_parent_admin_role_check_uses_existing_connection_and_requires_explicit_false(result):
    connection = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(
        fetchall=AsyncMock(return_value=result))))
    if result == [(False,)]:
        asyncio.run(PG.require_parent_admin_role_rejected(connection, 'synthetic role guard'))
    else:
        with pytest.raises(PG.RuntimeCheckError, match='unsafe_administrator_accepted'):
            asyncio.run(PG.require_parent_admin_role_rejected(connection, 'synthetic role guard'))
    connection.execute.assert_awaited_once_with('synthetic role guard')


def test_parent_admin_guard_failure_is_reported_without_child_success(monkeypatch, capsys):
    monkeypatch.setattr(sys, 'argv', ['check_python_postgres.py', '--config', '/unused/private.json',
                                    '--allow-test-writes', '--typescript'])
    monkeypatch.setattr(PG, 'check', AsyncMock(
        side_effect=PG.RuntimeCheckError('unsafe_administrator_accepted')))
    assert PG.main() == 1
    output = capsys.readouterr().out
    assert 'unsafe_administrator_accepted' in output
    assert 'unsafe_admin_rejected' not in output
    assert '"state": "passed"' not in output


def test_evidence_cli_requires_hybrid_and_test_write_authorization(monkeypatch):
    check = AsyncMock(return_value={'state':'passed'})
    monkeypatch.setattr(PG,'check',check)
    base=['check_python_postgres.py','--config','/unused/private.json','--evidence']
    for extra in ([],['--allow-test-writes'],['--hybrid']):
        monkeypatch.setattr(sys,'argv',[*base,*extra])
        assert PG.main()==2 and not check.called
    monkeypatch.setattr(sys,'argv',[*base,'--hybrid','--allow-test-writes','--typescript'])
    assert PG.main()==0
    assert check.call_args.kwargs['evidence'] is True
    assert check.call_args.kwargs['hybrid'] is True


def test_installed_origin_guard_rejects_checkout_and_wrong_interpreter(tmp_path):
    prefix=tmp_path/'installed'
    module=prefix/'lib'/'cragkit'/'__init__.py'
    PG.require_installed_origin(str(prefix),str(module),str(prefix))
    PG.require_installed_origin(None,str(tmp_path/'checkout/cragkit.py'),str(tmp_path))
    with pytest.raises(PG.RuntimeCheckError,match='installed_product_origin_required'):
        PG.require_installed_origin(str(prefix),str(tmp_path/'checkout/cragkit.py'),str(prefix))
    with pytest.raises(PG.RuntimeCheckError,match='installed_product_origin_required'):
        PG.require_installed_origin(str(prefix),str(module),str(tmp_path/'other'))


@pytest.mark.parametrize('rows', [[(False,)], [], [(True,), (True,)]])
def test_unsupported_lexical_fixture_behavior_fails_before_mutation(rows):
    cursor = SimpleNamespace(fetchall=AsyncMock(return_value=rows))
    connection = SimpleNamespace(execute=AsyncMock(return_value=cursor))
    with pytest.raises(PG.RuntimeCheckError, match='lexical_fixture_locale_unsupported'):
        asyncio.run(PG.require_lexical_fixture_behavior(connection))
    connection.execute.assert_awaited_once_with(
        "SELECT to_tsvector('pg_catalog.simple', %s) @@ websearch_to_tsquery('pg_catalog.simple', %s)",
        ('Café🙂', 'Café'))


def test_supported_lexical_fixture_behavior_is_read_only():
    cursor = SimpleNamespace(fetchall=AsyncMock(return_value=[(True,)]))
    connection = SimpleNamespace(execute=AsyncMock(return_value=cursor))
    asyncio.run(PG.require_lexical_fixture_behavior(connection))
    assert connection.execute.await_count == 1


def test_corrective_cli_requires_hybrid_and_explicit_writes(monkeypatch):
    check = AsyncMock(return_value={'state': 'passed'})
    monkeypatch.setattr(PG, 'check', check)
    base = ['check_python_postgres', '--config', '/unused/private.json', '--corrective']
    for extra in ([], ['--allow-test-writes'], ['--hybrid']):
        monkeypatch.setattr(sys, 'argv', [*base, *extra])
        assert PG.main() == 2
    monkeypatch.setattr(sys, 'argv', [*base, '--hybrid', '--typescript', '--allow-test-writes'])
    assert PG.main() == 0
    assert check.call_args.kwargs['corrective'] is True


def test_cli_preserves_redacted_original_and_cleanup_diagnostics(monkeypatch, capsys):
    import json
    secret = "postgresql://private:password@host/db SELECT private_source"
    class DatabaseFault(Exception):
        sqlstate = '08006'
    failure = PG.CleanupFailure([('row_delete', DatabaseFault(secret)), ('admin_close', TimeoutError(secret))],
        primary=RuntimeError(secret), stage='hybrid_evaluation')
    monkeypatch.setattr(sys, 'argv', ['check_python_postgres.py', '--config', '/unused/private.json', '--allow-test-writes'])
    monkeypatch.setattr(PG, 'check', AsyncMock(side_effect=failure))
    assert PG.main() == 1
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    value = json.loads(output.out)
    assert value['state'] == 'failed' and value['code'] == 'cleanup_failed'
    assert value['primary']['stage'] == 'hybrid_evaluation'
    assert value['primary']['category'] == 'operation'
    assert value['cleanup'][0]['operation'] == 'row_delete'
    assert value['cleanup'][0]['sqlstate'] == '08006'
    assert value['cleanup'][1]['category'] == 'timeout'


def test_cli_diagnostic_category_preserves_cancellation_without_raw_reason(monkeypatch, capsys):
    import json
    failure = PG.CleanupFailure([('cleanup_budget', TimeoutError('private-timeout'))],
        primary=asyncio.CancelledError('private-cancel'), stage='hybrid_evaluation')
    monkeypatch.setattr(sys, 'argv', ['check_python_postgres.py', '--config', '/unused/private.json', '--allow-test-writes'])
    monkeypatch.setattr(PG, 'check', AsyncMock(side_effect=failure))
    assert PG.main() == 1
    output = capsys.readouterr().out
    assert 'private' not in output
    assert json.loads(output)['primary']['category'] == 'cancelled'


def test_cli_cannot_report_success_when_only_cleanup_fails(monkeypatch, capsys):
    import json
    failure = PG.CleanupFailure([('role_drop', ConnectionError('private-cleanup'))], stage='hybrid_evaluation')
    monkeypatch.setattr(sys, 'argv', ['check_python_postgres.py', '--config', '/unused/private.json', '--allow-test-writes'])
    monkeypatch.setattr(PG, 'check', AsyncMock(side_effect=failure))
    assert PG.main() == 1
    value = json.loads(capsys.readouterr().out)
    assert value['state'] == 'failed' and value['primary'] is None
    assert value['cleanup'][0]['category'] == 'connection'


def test_recovery_cli_requires_explicit_writes_and_rejects_fixture_modes(monkeypatch, capsys):
    recovery = AsyncMock(return_value={'state': 'passed', 'cleanup_verified': True})
    monkeypatch.setattr(PG, 'recover_run', recovery)
    base = ['check_python_postgres.py', '--config', '/unused/private.json', '--recover', 'a' * 16]
    monkeypatch.setattr(sys, 'argv', base)
    assert PG.main() == 2 and not recovery.called
    for mode in ('--hybrid', '--typescript', '--lifecycle', '--corrective', '--evidence'):
        monkeypatch.setattr(sys, 'argv', [*base, '--allow-test-writes', mode])
        assert PG.main() == 2 and not recovery.called
    monkeypatch.setattr(sys, 'argv', [*base, '--allow-test-writes', '--neon'])
    assert PG.main() == 0
    recovery.assert_awaited_once_with(Path('/unused/private.json'), 'a' * 16, neon=True)


def test_recovery_refusal_cli_is_closed_and_has_no_false_success(monkeypatch, capsys):
    monkeypatch.setattr(PG, 'recover_run', AsyncMock(side_effect=PG.RecoveryRefused('ownership_mismatch')))
    monkeypatch.setattr(sys, 'argv', ['check_python_postgres.py', '--config', '/unused/private.json',
                                    '--recover', 'a' * 16, '--allow-test-writes'])
    assert PG.main() == 1
    assert __import__('json').loads(capsys.readouterr().out) == {
        'state': 'failed', 'code': 'recovery_refused', 'reason': 'ownership_mismatch'}


def test_cleanup_cli_exposes_only_validated_run_id_and_closed_refusal(monkeypatch, capsys):
    error = PG.CleanupFailure([('admin_connect', ConnectionError('private credential'))])
    error.recovery_id = 'a' * 16
    error.refusal_reason = 'history_mismatch'
    monkeypatch.setattr(PG, 'check', AsyncMock(side_effect=error))
    monkeypatch.setattr(sys, 'argv', ['check_python_postgres.py', '--config', '/unused/private.json',
                                    '--allow-test-writes'])
    assert PG.main() == 1
    output = __import__('json').loads(capsys.readouterr().out)
    assert output['recovery_id'] == 'a' * 16 and output['recovery_required'] is True
    assert output['refusal_reason'] == 'history_mismatch'
    assert 'private credential' not in str(output)


def test_quiescence_closes_child_then_old_admin_then_runtime():
    async def run():
        seen = []
        class Child:
            returncode = None
            def kill(self): seen.append('kill')
            async def wait(self): seen.append('wait')
        async def admin_close(): seen.append('admin')
        async def runtime_close(): seen.append('runtime')
        await PG.quiesce_clients(admin=SimpleNamespace(close=admin_close),
                                 runtime=SimpleNamespace(close=runtime_close), child=Child(),
                                 deadline=asyncio.get_running_loop().time() + 1)
        assert seen == ['kill', 'wait', 'admin', 'runtime']
    asyncio.run(run())


def test_quiescence_failure_is_distinct_and_stops_before_fresh_recovery():
    async def run():
        runtime = AsyncMock()
        admin = SimpleNamespace(close=AsyncMock(side_effect=ConnectionError('private credential')))
        with pytest.raises(PG.CleanupFailure) as captured:
            await PG.quiesce_clients(admin=admin, runtime=runtime, child=None,
                                     deadline=asyncio.get_running_loop().time() + 1,
                                     primary=ValueError('private query'), stage='fixture_setup')
        detail = captured.value.to_dict()
        assert detail['primary']['category'] == 'validation'
        assert detail['cleanup'][0]['operation'] == 'admin_close'
        assert 'private' not in str(detail)
        runtime.close.assert_awaited_once()
    asyncio.run(run())


def test_quiescence_timeout_has_no_success_and_observes_cancelled_task():
    async def run():
        stopped = asyncio.Event()
        async def close():
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        with pytest.raises(PG.CleanupFailure) as captured:
            await PG.quiesce_clients(admin=SimpleNamespace(close=close), runtime=None,
                                     child=None, deadline=asyncio.get_running_loop().time() + .01)
        assert captured.value.to_dict()['cleanup'][0]['category'] == 'timeout'
        await asyncio.sleep(0)
        assert stopped.is_set()
    asyncio.run(run())



def test_generic_cli_failure_does_not_read_hostile_error_text_or_class_name(monkeypatch, capsys):
    class PrivateQueryName(Exception):
        @property
        def sqlstate(self): raise RuntimeError('private SQL text')
        def __str__(self): raise RuntimeError('private credential')
    monkeypatch.setattr(PG, 'check', AsyncMock(side_effect=PrivateQueryName()))
    monkeypatch.setattr(sys, 'argv', ['check_python_postgres.py', '--config', '/unused/private.json',
                                    '--allow-test-writes'])
    assert PG.main() == 1
    output = capsys.readouterr().out
    assert 'private' not in output and 'PrivateQueryName' not in output
    assert __import__('json').loads(output)['error']['sqlstate'] is None



@pytest.mark.parametrize('value', [True, False, 0, 24, 26, 60.0, '60', None, float('inf')])
def test_evaluation_profile_exact_choices_only(value):
    with pytest.raises(PG.RuntimeCheckError, match='invalid_evaluation_profile'):
        PG.require_evaluation_profile(value, hybrid=True)


def test_evaluation_profile_cannot_silently_change_other_modes():
    PG.require_evaluation_profile(25, hybrid=False)
    for value in (25, 60): PG.require_evaluation_profile(value, hybrid=True)
    with pytest.raises(PG.RuntimeCheckError, match='evaluation_profile_requires_hybrid'):
        PG.require_evaluation_profile(60, hybrid=False)


def test_evaluation_cli_profile_is_explicit_forwarded_and_needs_writes(monkeypatch, capsys):
    check = AsyncMock(return_value={'state': 'passed'})
    monkeypatch.setattr(PG, 'check', check)
    base = ['check_python_postgres.py', '--config', '/unused/private.json',
            '--evaluation-deadline-seconds', '60']
    for extra in ([], ['--allow-test-writes'], ['--hybrid']):
        monkeypatch.setattr(sys, 'argv', [*base, *extra])
        assert PG.main() == 2 and not check.called
    monkeypatch.setattr(sys, 'argv', [*base, '--hybrid', '--allow-test-writes'])
    assert PG.main() == 0
    assert check.call_args.kwargs['evaluation_deadline_seconds'] == 60
    monkeypatch.setattr(sys, 'argv', ['check_python_postgres.py', '--config', '/unused/private.json',
                                    '--hybrid', '--allow-test-writes'])
    assert PG.main() == 0
    assert check.call_args.kwargs['evaluation_deadline_seconds'] == 25



def test_temporary_role_expiry_covers_only_the_selected_bounded_admin_run():
    assert PG.fixture_role_lifetime_seconds(25) == 600
    assert PG.fixture_role_lifetime_seconds(60) == 1800 + 120
    for value in (True, '60', 61):
        with pytest.raises(PG.RuntimeCheckError, match='invalid_evaluation_profile'):
            PG.fixture_role_lifetime_seconds(value)
