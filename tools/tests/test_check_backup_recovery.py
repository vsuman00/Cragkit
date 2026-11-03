"""MRR-r1 authority, quarantine and owned-backup failures without services."""
import asyncio
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import check_backup_recovery as recovery


def document(name, revision='1', *, tombstoned=False, grants=True):
    return dict(tenant_id='fixture-tenant', collection_id='fixture-collection', document_id=name,
        authorization_revision=revision, tombstoned=tombstoned,
        grants=[dict(grant_id='read', principal_id='fixture-reader', authorization_revision=revision)] if grants else [])


@pytest.fixture
def authority_pair():
    old = [document('allowed'), document('revoked'), document('deleted')]
    latest = [document('allowed', '2'), document('revoked', '2', grants=False),
        document('deleted', '2', tombstoned=True, grants=False)]
    return old, latest


def test_current_authority_preserves_revocation_and_tombstone(authority_pair):
    old, current = authority_pair
    expected = deepcopy(current)
    admitted = recovery.validate_authority(old, current, recovery.authority_digest(current))
    assert len(admitted) == 3
    assert admitted[('fixture-tenant', 'fixture-collection', 'revoked')]['grants'] == []
    assert admitted[('fixture-tenant', 'fixture-collection', 'deleted')]['tombstoned'] is True
    assert current == expected


@pytest.mark.parametrize('failure', ['missing', 'incomplete', 'extra', 'duplicate', 'identity',
    'stale', 'bad_revision', 'grant_revision', 'duplicate_grant', 'untombstone', 'changed_snapshot'])
def test_current_authority_refuses_unsafe_recovery(authority_pair, failure):
    old, current = authority_pair
    digest = recovery.authority_digest(current)
    if failure == 'missing': current = None
    if failure == 'incomplete': current.pop()
    if failure == 'extra': current.append(document('unexpected', '2'))
    if failure == 'duplicate': current.append(deepcopy(current[0]))
    if failure == 'identity': current[0]['tenant_id'] = 'another-tenant'
    if failure == 'stale': current[0] = document('allowed', '0')
    if failure == 'bad_revision': current[0] = document('allowed', '02')
    if failure == 'grant_revision': current[0]['grants'][0]['authorization_revision'] = '1'
    if failure == 'duplicate_grant': current[0]['grants'] *= 2
    if failure == 'untombstone': old[2]['tombstoned'] = True; current[2]['tombstoned'] = False
    if failure == 'changed_snapshot': current[1]['grants'] = deepcopy(current[0]['grants'])
    # Exercise identity/completeness/revision independently of the trusted digest.
    if failure != 'changed_snapshot': digest = recovery.authority_digest(current)
    with pytest.raises(ValueError, match='backup_recovery_invalid'):
        recovery.validate_authority(old, current, digest)


def test_failed_authority_gate_never_mutates_or_releases_runtime(authority_pair, monkeypatch):
    old, current = authority_pair
    executed = []
    class Transaction:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
    class Admin:
        def transaction(self): return Transaction()
        async def execute(self, statement, values=None): executed.append(statement)
    async def original(_): return old
    monkeypatch.setattr(recovery, 'authority', original)
    with pytest.raises(ValueError):
        asyncio.run(recovery.reconcile(Admin(), current[:-1], recovery.authority_digest(current)))
    assert executed == []


@pytest.fixture
def owned_backup(tmp_path):
    path = tmp_path/'source.dump'
    path.write_bytes(b'PGDMPsynthetic-owned-backup')
    path.chmod(0o600)
    return path, sha256(path.read_bytes()).hexdigest()


def test_owned_backup_checks_bytes_and_permissions(owned_backup):
    recovery.verify_backup(*owned_backup)


@pytest.mark.parametrize('failure', ['missing', 'digest', 'changed', 'permissions', 'symlink', 'format'])
def test_bad_backup_is_refused(owned_backup, failure):
    path, digest = owned_backup
    if failure == 'missing': path.unlink()
    if failure == 'digest': digest = '0' * 64
    if failure == 'changed': path.write_bytes(path.read_bytes() + b'changed')
    if failure == 'permissions': path.chmod(0o644)
    if failure == 'symlink':
        original = path.with_suffix('.original')
        path.rename(original)
        path.symlink_to(original)
    if failure == 'format':
        path.write_bytes(b'not-custom-archive')
        digest = sha256(path.read_bytes()).hexdigest()
    with pytest.raises((ValueError, OSError)):
        recovery.verify_backup(path, digest)


@pytest.mark.parametrize('failure', [None, 'startup_no_sqlstate', 'login', 'sessions', 'connects',
    'unhealthy_admin', 'no_pgconn', 'not_bad', 'unrelated_error', 'network_timeout'])
def test_quarantine_requires_disabled_roles_zero_sessions_and_real_refusal(monkeypatch, failure):
    import psycopg
    configs = [dict(user='reader', dbname=recovery.DATABASE), dict(user='writer', dbname=recovery.DATABASE)]
    class Refusal(psycopg.OperationalError):
        @property
        def sqlstate(self):
            return '28000' if failure not in ('startup_no_sqlstate', 'no_pgconn', 'not_bad') else None
        class Pgconn:
            status = 0 if failure == 'not_bad' else 1
        pgconn = None if failure == 'no_pgconn' else Pgconn()
    class Connection:
        async def close(self): pass
    async def connect(_):
        if failure == 'connects': return Connection()
        if failure == 'network_timeout': raise TimeoutError('synthetic-private-detail')
        if failure == 'unrelated_error': raise RuntimeError('synthetic-private-detail')
        raise Refusal('synthetic-private-detail')
    async def rows(_, query, parameters=None):
        if 'current_database' in query:
            return [('wrong_database' if failure == 'unhealthy_admin' else recovery.DATABASE, 1)]
        if 'pg_roles' in query:
            return [('reader', failure == 'login'), ('writer', False)]
        return [(1 if failure == 'sessions' else 0,)]
    monkeypatch.setattr(recovery, 'connect', connect)
    monkeypatch.setattr(recovery, 'rows', rows)
    if failure in (None, 'startup_no_sqlstate'):
        asyncio.run(recovery.assert_quarantine(object(), configs))
    else:
        with pytest.raises(ValueError, match='backup_recovery_invalid'):
            asyncio.run(recovery.assert_quarantine(object(), configs))


def test_cross_database_passfile_is_private_and_stays_with_fixture(tmp_path):
    source = tmp_path/'fixture.pgpass'
    original = b'127.0.0.1:5432:postgres:fixture:synthetic-password\n'
    source.write_bytes(original)
    source.chmod(0o600)
    configuration = dict(dbname='postgres', passfile=str(source), user='fixture')
    restored = recovery.database_config(configuration)
    destination = Path(restored['passfile'])
    assert destination.parent == source.parent
    assert destination.stat().st_mode & 0o777 == 0o600
    assert destination.read_bytes() == original.replace(b':postgres:', b':cragkit_restore:')
    assert source.read_bytes() == original
    assert configuration['dbname'] == 'postgres'
    assert restored['dbname'] == 'cragkit_restore'


def test_quarantine_rejects_target_admin_configuration_mismatch_before_connect():
    expected = dict(host='127.0.0.1', port=5432, dbname=recovery.DATABASE,
        sslrootcert='/synthetic/fixture.crt')
    roles = [dict(expected, user='reader'), dict(expected, user='writer', port=5433)]
    with pytest.raises(ValueError, match='backup_recovery_invalid'):
        asyncio.run(recovery.assert_quarantine(object(), roles, expected))
