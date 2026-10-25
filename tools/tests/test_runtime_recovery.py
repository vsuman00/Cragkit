"""Private journal and recovery state tests without database connections."""

import asyncio
from dataclasses import FrozenInstanceError
import json
import os
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runtime_diagnostics import CleanupFailure
from runtime_recovery import Journal, Manifest, RecoveryRefused, recover, target_fingerprint


RUN = 'a' * 16
DIGEST = 'b' * 64


def create(tmp_path, **updates):
    values = dict(run_id=RUN, target_sha256=DIGEST, ingestion=True, vectors=False,
                  lifecycle=False, allow_schema_restore=True,
                  migration_sha256=DIGEST, vector_sha256=None, root=tmp_path / 'private')
    values.update(updates)
    return Journal.create(**values)


def test_round_trip_private_immutable_and_derived(tmp_path):
    journal = create(tmp_path)
    manifest = journal.manifest
    assert manifest.role == 'cragkit_probe_' + RUN
    assert manifest.collection == 'probe_' + RUN
    assert manifest.tenants == ('probe_a_' + RUN, 'probe_b_' + RUN)
    assert manifest.policy == manifest.role + '_select'
    assert manifest.owner_marker == 'cragkit-runtime-v1:' + manifest.owner_nonce
    assert manifest.selected == manifest.tables + ('migration_history',)
    assert len(manifest.tables) == 8
    assert (tmp_path / 'private').stat().st_mode & 0o777 == 0o700
    path = tmp_path / 'private' / (RUN + '.json')
    assert path.stat().st_mode & 0o777 == 0o600
    assert Journal.load(RUN, target_sha256=DIGEST, root=path.parent).manifest == manifest
    with pytest.raises(FrozenInstanceError):
        manifest.run_id = 'c' * 16
    snapshot = manifest.to_dict()
    snapshot['run_id'] = 'c' * 16
    assert manifest.run_id == RUN
    journal.remove()
    assert not path.exists()


def test_vectors_and_exclusive_creation(tmp_path):
    journal = create(tmp_path, vectors=True, vector_sha256=DIGEST)
    assert journal.manifest.tables[-1] == 'chunk_vectors_fake_1536'
    assert journal.manifest.selected[-1] == 'embedding_profiles'
    with pytest.raises(RecoveryRefused):
        create(tmp_path)


@pytest.mark.parametrize(('key', 'value'), [
    ('version', True), ('run_id', '../escape'), ('owner_nonce', 'A' * 64),
    ('target_sha256', 'z' * 64), ('migration_sha256', None), ('ingestion', 1),
    ('vectors', 'false'), ('lifecycle', None), ('allow_schema_restore', 0),
    ('vector_sha256', DIGEST),
])
def test_manifest_shape_rejected(tmp_path, key, value):
    data = create(tmp_path).manifest.to_dict()
    data[key] = value
    with pytest.raises(RecoveryRefused) as caught:
        Manifest(**data)
    assert caught.value.reason == 'invalid_manifest'
    assert str(caught.value) == 'recovery_refused'


@pytest.mark.parametrize('body', [b'{}', b'[]', b'null', b'\xff', b'{',
                                 b'{"version":1,"version":1}', b'[' * 2000])
def test_invalid_and_duplicate_json_refused(tmp_path, body):
    create(tmp_path)
    path = tmp_path / 'private' / (RUN + '.json')
    path.write_bytes(body)
    with pytest.raises(RecoveryRefused):
        Journal.load(RUN, target_sha256=DIGEST, root=path.parent)


def test_target_and_exact_shape_refused(tmp_path):
    journal = create(tmp_path)
    path = tmp_path / 'private' / (RUN + '.json')
    with pytest.raises(RecoveryRefused) as caught:
        Journal.load(RUN, target_sha256='c' * 64, root=path.parent)
    assert caught.value.reason == 'target_mismatch'
    data = journal.manifest.to_dict()
    data['role'] = 'unrelated'
    path.write_text(json.dumps(data))
    with pytest.raises(RecoveryRefused):
        Journal.load(RUN, target_sha256=DIGEST, root=path.parent)


@pytest.mark.parametrize('fault', ['directory_mode', 'file_mode', 'symlink', 'hardlink',
                                  'oversize', 'replacement', 'changed', 'directory_swap'])
def test_substitution_and_permissions_fail_closed(tmp_path, fault):
    journal = create(tmp_path)
    root = tmp_path / 'private'
    path = root / (RUN + '.json')
    if fault == 'directory_mode':
        root.chmod(0o755)
    elif fault == 'file_mode':
        path.chmod(0o644)
    elif fault == 'symlink':
        saved = tmp_path / 'saved'
        path.rename(saved)
        path.symlink_to(saved)
    elif fault == 'hardlink':
        os.link(path, tmp_path / 'linked')
    elif fault == 'oversize':
        path.write_bytes(b' ' * 8193)
    elif fault == 'replacement':
        body = path.read_bytes()
        path.rename(tmp_path / 'saved')
        path.write_bytes(body)
        path.chmod(0o600)
    elif fault == 'changed':
        path.write_bytes(path.read_bytes() + b' ')
    else:
        root.rename(tmp_path / 'old')
        root.symlink_to(tmp_path / 'old', target_is_directory=True)
    with pytest.raises(RecoveryRefused):
        journal.remove()
    assert path.exists()


def test_existing_unsafe_directory_is_not_repaired(tmp_path):
    root = tmp_path / 'private'
    root.mkdir(mode=0o755)
    root.chmod(0o755)
    with pytest.raises(RecoveryRefused):
        create(tmp_path)
    assert root.stat().st_mode & 0o777 == 0o755


def test_fingerprint_is_deterministic_bounded_and_identity_sensitive():
    original = target_fingerprint('host', 5432, 'database', 'admin')
    assert len(original) == 64
    assert original == target_fingerprint('host', 5432, 'database', 'admin')
    assert original != target_fingerprint('host', 5433, 'database', 'admin')
    for values in [('host', True, 'db', 'user'), ('x' * 1025, 5432, 'db', 'user'),
                   ('host', 0, 'db', 'user'), ('host', 5432, '', 'user')]:
        with pytest.raises(RecoveryRefused):
            target_fingerprint(*values)


class Transport:
    operation = 'fixture_transaction'

    def __init__(self, error=None, close_error=None):
        self.error, self.close_error = error, close_error
        self.closed = 0
        self.cleaned = 0

    async def clean(self, manifest, *, deadline):
        self.cleaned += 1
        if self.error:
            raise self.error

    async def close(self):
        self.closed += 1
        if self.close_error:
            raise self.close_error


def test_success_closes_then_removes_journal(tmp_path):
    async def run():
        journal = create(tmp_path)
        transport = Transport()
        async def connect(deadline):
            assert (tmp_path / 'private' / (RUN + '.json')).exists()
            return transport
        result = await recover(journal, connect=connect, deadline=asyncio.get_running_loop().time() + 1)
        assert result == dict(state='passed', cleanup_verified=True, attempts=1, recovered=False, failures=[])
        assert transport.closed == transport.cleaned == 1
        assert not (tmp_path / 'private' / (RUN + '.json')).exists()
    asyncio.run(run())


def test_repeated_verified_transport_cleanup_before_journal_removal(tmp_path):
    async def run():
        original = Transport()
        class Repeated(Transport):
            async def clean(self, manifest, *, deadline):
                await original.clean(manifest, deadline=deadline)
                await original.clean(manifest, deadline=deadline)
        wrapper = Repeated()
        async def connect(deadline):
            return wrapper
        await recover(create(tmp_path), connect=connect, deadline=asyncio.get_running_loop().time() + 1)
        assert original.cleaned == 2 and wrapper.closed == 1
        with pytest.raises(RecoveryRefused):
            Journal.load(RUN, target_sha256=DIGEST, root=tmp_path / 'private')
    asyncio.run(run())


def test_connection_failure_retries_fresh_connector(tmp_path):
    async def run():
        calls = []
        transport = Transport()
        async def connect(deadline):
            calls.append(1)
            if len(calls) == 1:
                raise ConnectionError('private-canary')
            return transport
        result = await recover(create(tmp_path), connect=connect,
                               deadline=asyncio.get_running_loop().time() + 1)
        assert result['attempts'] == 2 and len(calls) == 2
        assert result['failures'][0]['operation'] == 'admin_connect'
    asyncio.run(run())


@pytest.mark.parametrize('sqlstate', ['08006', '40001', '40P01', '55P03'])
def test_only_declared_transient_failures_retry_serially(tmp_path, sqlstate):
    async def run():
        error = RuntimeError('private-canary')
        error.sqlstate = sqlstate
        first, second = Transport(error), Transport()
        calls = []
        async def connect(deadline):
            if calls:
                assert first.closed == 1
            calls.append(1)
            return first if len(calls) == 1 else second
        result = await recover(create(tmp_path), connect=connect,
                               deadline=asyncio.get_running_loop().time() + 1)
        assert result['attempts'] == 2 and result['recovered'] is True
        assert 'private-canary' not in json.dumps(result)
    asyncio.run(run())


@pytest.mark.parametrize('error', [RecoveryRefused('ownership_mismatch'),
                                  PermissionError('private-canary'), asyncio.CancelledError()])
def test_terminal_failure_keeps_journal_and_original_separate(tmp_path, error):
    async def run():
        transport = Transport(error)
        calls = []
        async def connect(deadline):
            calls.append(1)
            return transport
        with pytest.raises(CleanupFailure) as caught:
            await recover(create(tmp_path), connect=connect,
                          deadline=asyncio.get_running_loop().time() + 1,
                          primary=ValueError('original-canary'))
        payload = caught.value.to_dict()
        assert payload['primary']['category'] == 'validation'
        assert len(calls) == 1 and transport.closed == 1
        assert (tmp_path / 'private' / (RUN + '.json')).exists()
        assert 'canary' not in json.dumps(payload)
        if type(error) is RecoveryRefused:
            assert caught.value.refusal_reason == 'ownership_mismatch'
    asyncio.run(run())


def test_close_failure_is_terminal_and_journal_retained(tmp_path):
    async def run():
        transport = Transport(close_error=ConnectionError())
        calls = []
        async def connect(deadline):
            calls.append(1)
            return transport
        with pytest.raises(CleanupFailure) as caught:
            await recover(create(tmp_path), connect=connect,
                          deadline=asyncio.get_running_loop().time() + 1)
        assert len(calls) == 1
        assert caught.value.to_dict()['cleanup'][0]['operation'] == 'admin_close'
        assert (tmp_path / 'private' / (RUN + '.json')).exists()
    asyncio.run(run())


def test_late_connector_is_closed_without_second_attempt(tmp_path):
    async def run():
        release = asyncio.Event()
        transport = Transport()
        calls = []
        async def connect(deadline):
            calls.append(1)
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return transport
        with pytest.raises(CleanupFailure):
            await recover(create(tmp_path), connect=connect,
                          deadline=asyncio.get_running_loop().time() + 0.01)
        assert len(calls) == 1 and transport.closed == 0
        release.set()
        for _ in range(6):
            await asyncio.sleep(0)
        assert transport.closed == 1
        assert (tmp_path / 'private' / (RUN + '.json')).exists()
    asyncio.run(run())


def test_late_clean_is_not_closed_or_retried_until_settled(tmp_path):
    async def run():
        release = asyncio.Event()
        class Late(Transport):
            async def clean(self, manifest, *, deadline):
                try:
                    await release.wait()
                except asyncio.CancelledError:
                    await release.wait()
        transport = Late()
        calls = []
        async def connect(deadline):
            calls.append(1)
            return transport
        with pytest.raises(CleanupFailure):
            await recover(create(tmp_path), connect=connect,
                          deadline=asyncio.get_running_loop().time() + 0.01)
        assert len(calls) == 1 and transport.closed == 0
        release.set()
        for _ in range(6):
            await asyncio.sleep(0)
        assert transport.closed == 1
    asyncio.run(run())


def test_external_cancellation_keeps_journal_and_closes_late_handle(tmp_path):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        transport = Transport()
        async def connect(deadline):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return transport
        task = asyncio.create_task(recover(create(tmp_path), connect=connect,
                                          deadline=asyncio.get_running_loop().time() + 1))
        await entered.wait()
        task.cancel()
        with pytest.raises(CleanupFailure) as caught:
            await task
        assert caught.value.to_dict()['cleanup'][0]['category'] == 'cancelled'
        release.set()
        for _ in range(6):
            await asyncio.sleep(0)
        assert transport.closed == 1
        assert (tmp_path / 'private' / (RUN + '.json')).exists()
    asyncio.run(run())


def test_journal_revalidation_prevents_database_dispatch(tmp_path):
    async def run():
        journal = create(tmp_path)
        (tmp_path / 'private' / (RUN + '.json')).chmod(0o644)
        async def connect(deadline):
            pytest.fail('invalid journal must not reach connector')
        with pytest.raises(CleanupFailure) as caught:
            await recover(journal, connect=connect, deadline=asyncio.get_running_loop().time() + 1)
        assert caught.value.refusal_reason == 'unsafe_path'
    asyncio.run(run())


@pytest.mark.parametrize(('deadline', 'attempts'), [(float('inf'), 2), (float('nan'), 2),
                                                   (True, 2), (1, 0), (1, 3), (1, True)])
def test_invalid_recovery_budget_rejected_before_dispatch(tmp_path, deadline, attempts):
    async def run():
        async def connect(deadline):
            pytest.fail('invalid budget must not reach connector')
        with pytest.raises(RecoveryRefused):
            await recover(create(tmp_path), connect=connect, deadline=deadline, max_attempts=attempts)
    asyncio.run(run())
