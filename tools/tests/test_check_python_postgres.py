"""Synthetic checks for explicit Neon fixture transport and secret handling."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import sys

import pytest

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
