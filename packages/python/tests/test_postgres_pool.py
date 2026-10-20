import asyncio
import importlib.abc
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

import pytest
from pydantic import ValidationError

from cragkit._postgres_pool import PoolConfig, PoolResource, parse_pool_config
from cragkit.errors import DeadlineExceeded, InvalidRequest, ProviderUnavailable, UnsupportedCapability


CONFIG_PATHS = {}


@pytest.fixture(autouse=True)
def isolated_fake_configuration(monkeypatch, tmp_path):
    for name in tuple(os.environ):
        if name.startswith('PG'):
            monkeypatch.delenv(name)
    ca = tmp_path / 'fake-ca.crt'
    password = tmp_path / 'fake.pgpass'
    ca.write_text('synthetic CA placeholder, never used for network')
    password.write_text('synthetic password fixture, never used for network')
    ca.chmod(0o600)
    password.chmod(0o600)
    monkeypatch.setitem(CONFIG_PATHS, 'sslrootcert', ca)
    monkeypatch.setitem(CONFIG_PATHS, 'passfile', password)


def config(**changes):
    return parse_pool_config({
        'host': 'dedicated.example.invalid', 'dbname': 'postgres', 'user': 'runtime',
        'sslrootcert': CONFIG_PATHS['sslrootcert'], 'passfile': CONFIG_PATHS['passfile'],
        'startup_timeout': 0.2, 'acquire_timeout': 0.2, 'close_timeout': 0.2,
        'release_timeout': 0.05, **changes,
    })


class FakeConnection:
    def __init__(self):
        self.closes = 0

    async def close(self):
        self.closes += 1


class FakePool:
    def __init__(self, size=1):
        self.connections = [FakeConnection() for _ in range(size)]
        self.available = asyncio.Queue()
        for connection in self.connections:
            self.available.put_nowait(connection)
        self.opens = []
        self.waits = []
        self.gets = []
        self.returned = []
        self.closes = []
        self.wait_started = asyncio.Event()
        self.wait_gate = None
        self.return_gate = None
        self.close_gate = None
        self.failure = None
        self.get_started = asyncio.Event()

    async def open(self, *, wait=False, timeout=30.0):
        self.opens.append((wait, timeout))

    async def wait(self, timeout=30.0):
        self.waits.append(timeout)
        self.wait_started.set()
        if self.wait_gate is not None:
            await self.wait_gate.wait()

    async def getconn(self, timeout=30.0):
        self.gets.append(timeout)
        self.get_started.set()
        if self.failure is not None:
            raise self.failure
        return await asyncio.wait_for(self.available.get(), timeout)

    async def putconn(self, connection):
        if self.return_gate is not None:
            await self.return_gate.wait()
        self.returned.append(connection)
        self.available.put_nowait(connection)

    async def close(self, timeout=5.0):
        self.closes.append(timeout)
        if self.close_gate is not None:
            await self.close_gate.wait()


async def spin_until(predicate):
    for _ in range(100):
        if predicate():
            return
        await asyncio.sleep(0)
    pytest.fail('Expected scheduled operation did not start')


def test_configuration_is_strict_frozen_and_has_finite_bounds():
    parsed = config()
    assert isinstance(parsed, PoolConfig)
    assert parsed.max_size == 2 and parsed.max_waiting == 4
    with pytest.raises(ValidationError):
        parsed.max_size = 1
    invalid = [
        {'host': '/tmp/socket'}, {'host': 'db.invalid,other.invalid'},
        {'host': 'postgresql://host.invalid/db'}, {'dbname': 'host=other'},
        {'dbname': 'postgresql://host/db'}, {'user': 'runtime\nother'},
        {'sslrootcert': Path('relative')}, {'passfile': Path('relative')},
        {'sslmode': 'disable'}, {'password': 'private-secret'},
        {'max_size': 0}, {'max_size': 3}, {'max_size': True},
        {'max_waiting': -1}, {'max_waiting': 17}, {'port': False}, {'port': 65536},
        {'startup_timeout': float('nan')}, {'acquire_timeout': float('inf')},
        {'close_timeout': 0}, {'release_timeout': -1},
        {'release_timeout': 0.3, 'close_timeout': 0.2},
    ]
    for changes in invalid:
        with pytest.raises(InvalidRequest):
            config(**changes)


def test_configuration_performs_no_file_or_environment_access(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Configuration inspected private state')
    monkeypatch.setattr(Path, 'is_file', forbidden)
    monkeypatch.setattr(Path, 'read_text', forbidden)
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    monkeypatch.setenv('PGDATABASE', 'private-secret-redirect')
    assert config().dbname == 'postgres'


def test_owned_startup_and_close_are_explicit_idempotent_and_terminal():
    async def scenario():
        pool = FakePool()
        factories = []
        def factory(value):
            factories.append(value)
            return pool
        resource = PoolResource(config(), factory=factory)
        assert not factories and not pool.opens
        with pytest.raises(ProviderUnavailable):
            async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
                pytest.fail('Lease before owned startup')
        await resource.open()
        await resource.open()
        assert len(factories) == len(pool.opens) == len(pool.waits) == 1
        async with resource.lease(deadline=asyncio.get_running_loop().time() + 1) as connection:
            assert connection is pool.connections[0]
        assert pool.returned == [connection]
        await resource.close()
        await resource.close()
        assert len(pool.closes) == 1
        with pytest.raises(ProviderUnavailable):
            await resource.open()
        with pytest.raises(ProviderUnavailable):
            async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
                pytest.fail('Lease after close')
    asyncio.run(scenario())


def test_borrowed_pool_is_never_opened_or_closed_and_unrelated_lease_survives():
    async def scenario():
        pool = FakePool(size=2)
        unrelated = await pool.getconn()
        resource = PoolResource(config(), pool=pool)
        await resource.open()
        async with resource.lease(deadline=asyncio.get_running_loop().time() + 1) as wrapped:
            assert wrapped is not unrelated
        await resource.close()
        assert not pool.opens and not pool.waits and not pool.closes
        assert unrelated not in pool.returned and unrelated.closes == 0
        await pool.putconn(unrelated)
        assert pool.available.qsize() == 2
    asyncio.run(scenario())


def test_close_before_open_does_not_construct_a_driver():
    async def scenario():
        def factory(value):
            pytest.fail('Driver constructed after close')
        resource = PoolResource(config(), factory=factory)
        await resource.close()
        with pytest.raises(ProviderUnavailable):
            await resource.open()
    asyncio.run(scenario())


def test_owned_open_rejects_libpq_environment_redirect_without_factory(monkeypatch):
    async def scenario():
        for name in ('PGSERVICE', 'PGDATABASE', 'PGHOSTADDR', 'PGOPTIONS', 'PGPASSWORD'):
            monkeypatch.setenv(name, 'synthetic-private-redirect')
            called = []
            resource = PoolResource(config(), factory=lambda value: called.append(value))
            with pytest.raises(InvalidRequest):
                await resource.open()
            assert not called
            monkeypatch.delenv(name)
    asyncio.run(scenario())


def test_startup_wait_has_a_deadline_and_cleans_owned_pool():
    async def scenario():
        pool = FakePool(); pool.wait_gate = asyncio.Event()
        resource = PoolResource(config(startup_timeout=0.02), factory=lambda value: pool)
        with pytest.raises(ProviderUnavailable):
            await asyncio.wait_for(resource.open(), 0.5)
        assert len(pool.closes) == 1
        await resource.close()
        assert len(pool.closes) == 1
    asyncio.run(scenario())


def test_expired_request_and_shorter_configured_acquisition_limits_are_distinct():
    async def scenario():
        pool = FakePool()
        resource = PoolResource(config(acquire_timeout=0.02), pool=pool)
        loop = asyncio.get_running_loop()
        with pytest.raises(DeadlineExceeded):
            async with resource.lease(deadline=loop.time() - 1):
                pytest.fail('Expired request entered')
        assert not pool.gets
        external = await pool.getconn()
        with pytest.raises(ProviderUnavailable):
            async with resource.lease(deadline=loop.time() + 1):
                pytest.fail('Configured acquisition deadline ignored')
        with pytest.raises(DeadlineExceeded):
            async with resource.lease(deadline=loop.time() + 0.01):
                pytest.fail('Absolute request deadline ignored')
        await pool.putconn(external)
        await resource.close()
    asyncio.run(scenario())


def test_zero_waiting_is_bounded_not_driver_unlimited_queue():
    async def scenario():
        pool = FakePool()
        resource = PoolResource(config(max_size=1, max_waiting=0), pool=pool)
        async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
            before = len(pool.gets)
            async def overflow():
                with pytest.raises(ProviderUnavailable):
                    async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
                        pytest.fail('Saturated request entered')
            await asyncio.create_task(overflow())
            assert len(pool.gets) == before
        await resource.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('request_expires', [False, True])
def test_late_driver_return_is_released_before_the_body_can_run(request_expires):
    async def scenario():
        class LateReturn(FakePool):
            async def getconn(self, timeout=30.0):
                connection = await super().getconn(timeout)
                # Model an event-loop stall: the timeout callback cannot run yet.
                time.sleep(0.025)
                return connection
        pool = LateReturn()
        resource = PoolResource(config(acquire_timeout=0.01), pool=pool)
        deadline = asyncio.get_running_loop().time() + (0.01 if request_expires else 1)
        expected = DeadlineExceeded if request_expires else ProviderUnavailable
        with pytest.raises(expected):
            async with resource.lease(deadline=deadline):
                pytest.fail('Expired acquisition reached the caller body')
        assert pool.returned == pool.connections and pool.available.qsize() == 1
        await resource.close()
    asyncio.run(scenario())


def test_body_error_and_cancellation_return_lease_without_rewriting_exception():
    async def scenario():
        pool = FakePool()
        resource = PoolResource(config(), pool=pool)
        sentinel = RuntimeError('body-error')
        with pytest.raises(RuntimeError) as caught:
            async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
                raise sentinel
        assert caught.value is sentinel and len(pool.returned) == 1
        entered = asyncio.Event()
        async def body():
            async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
                entered.set()
                await asyncio.Event().wait()
        task = asyncio.create_task(body())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(pool.returned) == 2
        await resource.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('owned', [False, True])
def test_close_cancels_only_wrapper_active_and_queued_work(owned):
    async def scenario():
        pool = FakePool()
        resource = (PoolResource(config(max_size=1, max_waiting=1), factory=lambda value: pool)
                    if owned else PoolResource(config(max_size=1, max_waiting=1), pool=pool))
        if owned:
            await resource.open()
        entered = asyncio.Event()
        async def body():
            async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
                entered.set()
                await asyncio.Event().wait()
        active = asyncio.create_task(body())
        await entered.wait()
        queued = asyncio.create_task(body())
        await asyncio.sleep(0)
        await asyncio.wait_for(resource.close(), 0.5)
        results = await asyncio.gather(active, queued, return_exceptions=True)
        assert all(isinstance(value, asyncio.CancelledError) for value in results)
        assert len(pool.returned) == 1
        assert len(pool.closes) == int(owned)
        assert pool.available.qsize() == 1
    asyncio.run(scenario())


def test_close_from_inside_lease_is_rejected_without_losing_connection():
    async def scenario():
        pool = FakePool()
        resource = PoolResource(config(), pool=pool)
        async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
            with pytest.raises(InvalidRequest):
                await resource.close()
        assert len(pool.returned) == 1
        await resource.close()
    asyncio.run(scenario())


def test_driver_acquisition_errors_are_fixed_and_redacted():
    async def scenario():
        pool = FakePool(); pool.failure = RuntimeError('credential-secret-source')
        resource = PoolResource(config(), pool=pool)
        with pytest.raises(ProviderUnavailable) as caught:
            async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
                pytest.fail('Failed driver entered body')
        error = caught.value
        assert error.to_dict() == {'code': 'provider_unavailable', 'message': 'Provider is unavailable.', 'retryable': True}
        assert 'credential-secret-source' not in ''.join(traceback.format_exception(error))
        assert error.__cause__ is None
        await resource.close()
    asyncio.run(scenario())


def test_release_and_owned_close_are_bounded_even_when_driver_hangs():
    async def scenario():
        pool = FakePool(); pool.return_gate = asyncio.Event(); pool.close_gate = asyncio.Event()
        resource = PoolResource(config(close_timeout=0.05, release_timeout=0.02), factory=lambda value: pool)
        await resource.open()
        with pytest.raises(ProviderUnavailable):
            async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
                pass
        assert pool.connections[0].closes == 1
        try:
            await asyncio.wait_for(resource.close(), 0.3)
        except ProviderUnavailable:
            pass
        assert len(pool.closes) == 1
        with pytest.raises(ProviderUnavailable):
            await resource.close()
        assert len(pool.closes) == 1
    asyncio.run(scenario())


def test_internal_import_does_not_load_driver_and_missing_extra_is_safe():
    script = r'''
import asyncio, importlib.abc, sys, traceback
from pathlib import Path
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'psycopg', 'psycopg_pool'}:
            raise ModuleNotFoundError('synthetic-driver-secret')
sys.meta_path.insert(0, Block())
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)
def audit(event, args):
    if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.mkdir'):
        raise AssertionError('Internal import attempted external I/O')
sys.addaudithook(audit)
from cragkit._postgres_pool import PoolResource, parse_pool_config
from cragkit.errors import UnsupportedCapability
assert 'psycopg' not in sys.modules and 'psycopg_pool' not in sys.modules
config = parse_pool_config(dict(host='db.invalid',dbname='postgres',user='runtime',sslrootcert=Path(sys.argv[1]),passfile=Path(sys.argv[2])))
async def probe():
    try:
        await PoolResource(config).open()
    except UnsupportedCapability as error:
        assert 'synthetic-driver-secret' not in ''.join(traceback.format_exception(error))
    else:
        raise AssertionError('Missing extra accepted')
try:
    loop.run_until_complete(probe())
finally:
    loop.close()
    asyncio.set_event_loop(None)
'''
    result = subprocess.run([sys.executable, '-I', '-B', '-c', script, str(config().sslrootcert), str(config().passfile)], capture_output=True, text=True, timeout=5, check=False)
    assert result.returncode == 0, result.stderr


def test_total_wrapper_admission_is_active_plus_configured_waiters():
    async def scenario():
        pool = FakePool()
        resource = PoolResource(config(max_size=1, max_waiting=1), pool=pool)
        async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
            started = asyncio.Event()
            async def wait_for_lease():
                started.set()
                async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
                    pytest.fail('Queued task should be cancelled')
            waiting = asyncio.create_task(wait_for_lease())
            await started.wait()
            await asyncio.sleep(0)
            before = len(pool.gets)
            async def overflow():
                with pytest.raises(ProviderUnavailable):
                    async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
                        pytest.fail('Admission exceeded active plus waiting cap')
            await asyncio.create_task(overflow())
            assert len(pool.gets) == before
            waiting.cancel()
            with pytest.raises(asyncio.CancelledError):
                await waiting
            assert not pool.returned
        await resource.close()
        assert pool.available.qsize() == 1
    asyncio.run(scenario())


def test_cancelled_driver_acquisition_releases_wrapper_admission():
    async def scenario():
        pool = FakePool()
        external = await pool.getconn()
        pool.get_started.clear()
        resource = PoolResource(config(max_size=1, max_waiting=0), pool=pool)
        async def acquire():
            async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
                pytest.fail('Empty driver pool unexpectedly leased')
        task = asyncio.create_task(acquire())
        await pool.get_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not pool.returned
        await pool.putconn(external)
        async with resource.lease(deadline=asyncio.get_running_loop().time() + 1) as connection:
            assert connection is external
        await resource.close()
    asyncio.run(scenario())


def test_owned_startup_checks_private_file_permissions_without_reading_contents(monkeypatch, tmp_path):
    async def scenario():
        private_file = tmp_path / 'unsafe.pgpass'
        private_file.write_text('synthetic-only')
        private_file.chmod(0o644)
        made = []
        resource = PoolResource(config(passfile=private_file), factory=lambda value: made.append(value))
        with pytest.raises(InvalidRequest):
            await resource.open()
        assert not made
        private_file.chmod(0o600)
        resource = PoolResource(config(sslrootcert=tmp_path / 'missing-ca'), factory=lambda value: made.append(value))
        with pytest.raises(InvalidRequest):
            await resource.open()
        assert not made
    asyncio.run(scenario())


def test_close_during_owned_startup_cannot_reopen_the_resource():
    async def scenario():
        pool = FakePool(); pool.wait_gate = asyncio.Event()
        resource = PoolResource(config(startup_timeout=0.2), factory=lambda value: pool)
        opening = asyncio.create_task(resource.open())
        await pool.wait_started.wait()
        await asyncio.wait_for(resource.close(), 0.5)
        pool.wait_gate.set()
        outcome = await asyncio.gather(opening, return_exceptions=True)
        assert isinstance(outcome[0], (ProviderUnavailable, asyncio.CancelledError))
        assert len(pool.closes) == 1
        with pytest.raises(ProviderUnavailable):
            await resource.open()
        await resource.close()
    asyncio.run(scenario())


def test_driver_close_failure_is_redacted_and_not_silently_successful():
    async def scenario():
        class BrokenClose(FakePool):
            async def close(self, timeout=5.0):
                self.closes.append(timeout)
                raise RuntimeError('private-close-secret')
        pool = BrokenClose()
        resource = PoolResource(config(), factory=lambda value: pool)
        await resource.open()
        for _ in range(2):
            with pytest.raises(ProviderUnavailable) as caught:
                await resource.close()
            assert 'private-close-secret' not in ''.join(traceback.format_exception(caught.value))
        assert len(pool.closes) == 1
    asyncio.run(scenario())


def test_close_uses_one_overall_budget_even_with_uncooperative_lease_and_driver():
    async def scenario():
        pool = FakePool(); pool.close_gate = asyncio.Event()
        resource = PoolResource(config(close_timeout=0.2, release_timeout=0.02), factory=lambda value: pool)
        await resource.open()
        entered, finish = asyncio.Event(), asyncio.Event()
        async def stubborn_body():
            async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
                entered.set()
                try:
                    await finish.wait()
                except asyncio.CancelledError:
                    await finish.wait()
        active = asyncio.create_task(stubborn_body())
        await entered.wait()
        try:
            with pytest.raises(ProviderUnavailable):
                await asyncio.wait_for(resource.close(), 0.32)
            assert len(pool.closes) == 1
        finally:
            finish.set()
            await asyncio.wait_for(active, 0.5)
    asyncio.run(scenario())


def test_owned_startup_rejects_symlink_password_file(tmp_path):
    async def scenario():
        link = tmp_path / 'linked.pgpass'
        link.symlink_to(config().passfile)
        made = []
        resource = PoolResource(config(passfile=link), factory=lambda value: made.append(value))
        with pytest.raises(InvalidRequest):
            await resource.open()
        assert not made
    asyncio.run(scenario())


def test_borrowed_resource_ignores_owned_target_files_and_libpq_environment(monkeypatch):
    async def scenario():
        pool = FakePool()
        monkeypatch.setenv('PGSERVICE', 'caller-owned-private-service')
        resource = PoolResource(config(passfile=Path('/absent/caller-file'), sslrootcert=Path('/absent/caller-ca')), pool=pool)
        await resource.open()
        async with resource.lease(deadline=asyncio.get_running_loop().time() + 1):
            pass
        await resource.close()
        assert not pool.opens and not pool.closes
    asyncio.run(scenario())


def test_lease_deadline_must_be_finite_numeric():
    async def scenario():
        pool = FakePool()
        resource = PoolResource(config(), pool=pool)
        for value in (True, None, float('nan'), float('inf'), -float('inf')):
            with pytest.raises(InvalidRequest):
                async with resource.lease(deadline=value):
                    pytest.fail('Malformed deadline accepted')
        assert not pool.gets
        await resource.close()
    asyncio.run(scenario())
