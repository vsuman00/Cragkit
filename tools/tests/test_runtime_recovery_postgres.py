"""Fake SQL transport checks; native PostgreSQL acceptance runs separately."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
import runtime_recovery_postgres as PG
import runtime_recovery as RECOVERY
HISTORY = [('0001', 'a' * 64, '1234.000000')]


def digest(rows):
    return hashlib.sha256(json.dumps(sorted([list(row) for row in rows]),
        ensure_ascii=True, separators=(',', ':')).encode('ascii')).hexdigest()


def manifest(**changes):
    value = RECOVERY.Manifest(1, '0123456789abcdef', 'b' * 64, 'c' * 64,
                              True, False, False, True, digest(HISTORY), None)
    return replace(value, **changes)


class Query(str):
    def format(self, *args):
        return Query(str(self).format(*args))

    def join(self, parts):
        return Query(str(self).join(parts))

    def __add__(self, other):
        return Query(str(self) + str(other))


SQL = SimpleNamespace(SQL=Query,
    Identifier=lambda value: Query('"' + value.replace('"', '""') + '"'),
    Literal=lambda value: Query("'" + value.replace("'", "''") + "'"))


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, value):
        self.manifest = value
        self.calls = []
        self.role = [(123, False, False, False, False, False, False, 1,
                      value.owner_marker, False)]
        self.policies = [('cragkit', 'documents', value.policy, '*', True, [123])]
        self.schema = [('authorization_revision', True, True)]
        self.count = 1
        self.lock = True
        self.unlock = True
        self.extra = None
        self.safe_graph = True
        self.history = HISTORY
        self.closed = False
        self.mutated = False

    async def execute(self, query, params=None):
        text = str(query)
        self.calls.append((text, params))
        if 'recovery:history' in text:
            return Cursor(self.history)
        if 'recovery:lock ' in text or 'recovery:lock */' in text:
            return Cursor([(self.lock,)])
        if 'recovery:unlock' in text:
            return Cursor([(self.unlock,)])
        if 'recovery:role' in text:
            return Cursor(self.role)
        if 'recovery:policies' in text:
            return Cursor(self.policies)
        if 'recovery:schema' in text:
            return Cursor(self.schema)
        if 'recovery:extra' in text:
            return Cursor([(self.extra,)])
        if 'recovery:cascade' in text:
            return Cursor([(self.safe_graph,)])
        if 'recovery:inventory' in text:
            return Cursor([(table, self.count) for table in self.manifest.tables])
        if 'recovery:terminate' in text:
            return Cursor([(True,)])
        if text.startswith('ALTER TABLE'):
            self.schema = [('authorization_revision', True, True)]
        if text.startswith('DROP ROLE'):
            self.role, self.policies, self.count = [], [], 0
        self.mutated = True
        return Cursor([])

    @asynccontextmanager
    async def transaction(self):
        self.calls.append(('BEGIN', None))
        yield
        self.calls.append(('COMMIT', None))

    @asynccontextmanager
    async def pipeline(self):
        self.calls.append(('PIPELINE', None))
        yield

    async def close(self):
        self.closed = True


def run_clean(connection, value=None):
    async def run():
        transport = PG.PostgresTransport(connection, SQL, connection.manifest.target_sha256)
        await transport.clean(value or connection.manifest,
                              deadline=asyncio.get_running_loop().time() + 5)
        return transport
    return asyncio.run(run())


def test_history_snapshot_is_deterministic_and_changes_with_epoch():
    async def run():
        connection = FakeConnection(manifest())
        connection.history = [HISTORY[0], ('0002', 'd' * 64, '1235')]
        first = await PG.snapshot_histories(connection, vectors=True)
        connection.history.reverse()
        assert await PG.snapshot_histories(connection, vectors=True) == first
        connection.history[0] = ('0002', 'd' * 64, '9999')
        assert await PG.snapshot_histories(connection, vectors=True) != first
        assert all('SELECT version,checksum,extract(epoch FROM applied_at)::text' in query
                   for query, _ in connection.calls)
    asyncio.run(run())


@pytest.mark.parametrize('rows', [[], [('version', 'checksum')], [('v', 3, 'epoch')],
                                  [('v', 'c', 'e')] * 257])
def test_malformed_or_unbounded_history_is_refused(rows):
    async def run():
        connection = FakeConnection(manifest())
        connection.history = rows
        with pytest.raises(RECOVERY.RecoveryRefused) as caught:
            await PG.snapshot_histories(connection, vectors=False)
        assert caught.value.reason == 'history_mismatch'
    asyncio.run(run())


def test_exact_cleanup_checks_ownership_before_mutation_and_batches_transaction():
    value = manifest()
    connection = FakeConnection(value)
    transport = run_clean(connection)
    queries = [query for query, _ in connection.calls]
    first_mutation = next(index for index, query in enumerate(queries) if query.startswith('ALTER ROLE'))
    assert all(any(tag in query for query in queries[:first_mutation]) for tag in (
        'recovery:history', 'recovery:role', 'recovery:policies', 'recovery:schema',
        'recovery:inventory', 'recovery:extra'))
    assert queries.index('BEGIN') < queries.index('PIPELINE') < queries.index('COMMIT')
    assert transport.operation == 'lock_release'
    assert not transport._locked
    assert 'recovery:unlock' in queries[-1]
    for query, params in connection.calls:
        assert 'DROP OWNED' not in query and 'CASCADE' not in query and ' LIKE ' not in query
        if query.startswith('DELETE') or 'recovery:inventory' in query:
            assert params == (list(value.tenants), value.collection)
            assert 'collection_id' in query and 'tenant_id' in query
        if query.startswith('DROP ROLE'):
            assert query == 'DROP ROLE "' + value.role + '"'
    assert sum(query.startswith('DROP ROLE') for query in queries) == 1


@pytest.mark.parametrize(('attribute', 'replacement', 'reason'), [
    ('lock', False, 'lock_busy'),
    ('history', [('0001', 'f' * 64, '1234')], 'history_mismatch'),
    ('role', [(123, False, False, False, False, False, False, 1, 'forged', False)], 'ownership_mismatch'),
    ('role', [(123, True, False, False, False, False, False, 1,
               manifest().owner_marker, False)], 'unsafe_role'),
    ('role', [(123, False, False, False, False, False, False, 1,
               manifest().owner_marker, True)], 'unsafe_role'),
    ('schema', [('probe_hidden_authorization_revision', False, True)], 'schema_mismatch'),
    ('extra', 'unowned-table-canary', 'schema_mismatch'),
])
def test_ownership_history_role_and_schema_refusals_precede_mutation(attribute, replacement, reason):
    connection = FakeConnection(manifest())
    setattr(connection, attribute, replacement)
    with pytest.raises(RECOVERY.RecoveryRefused) as caught:
        run_clean(connection)
    assert caught.value.reason == reason
    assert str(caught.value) == 'recovery_refused'
    assert not connection.mutated


@pytest.mark.parametrize('policy', [
    ('cragkit', 'documents', manifest().policy, '*', True, [999]),
    ('foreign', 'documents', manifest().policy, '*', True, [123]),
    ('cragkit', 'documents', manifest().policy, 'r', True, [123]),
    ('cragkit', 'documents', manifest().policy, '*', False, [123]),
    ('cragkit', 'documents', 'foreign-policy-canary', '*', True, [123]),
    ('cragkit', 'documents', manifest().policy, '*', True, [123, 0]),
])
def test_foreign_or_forged_policy_is_never_dropped(policy):
    connection = FakeConnection(manifest())
    connection.policies = [policy]
    with pytest.raises(RECOVERY.RecoveryRefused) as caught:
        run_clean(connection)
    assert caught.value.reason == 'unexpected_policy'
    assert not connection.mutated


def test_proven_hidden_fixture_column_restored_within_cleanup_transaction():
    connection = FakeConnection(manifest())
    connection.schema = [('probe_hidden_authorization_revision', True, True)]
    run_clean(connection)
    queries = [query for query, _ in connection.calls]
    restore = next(index for index, query in enumerate(queries) if query.startswith('ALTER TABLE'))
    assert queries.index('BEGIN') < restore < queries.index('COMMIT')
    assert connection.schema == [('authorization_revision', True, True)]


def test_hidden_column_without_explicit_restore_authorization_is_refused():
    connection = FakeConnection(manifest(allow_schema_restore=False))
    connection.schema = [('probe_hidden_authorization_revision', True, True)]
    with pytest.raises(RECOVERY.RecoveryRefused) as caught:
        run_clean(connection)
    assert caught.value.reason == 'schema_mismatch'
    assert not connection.mutated


def test_already_absent_role_with_residual_inventory_is_refused():
    connection = FakeConnection(manifest())
    connection.role, connection.policies = [], []
    with pytest.raises(RECOVERY.RecoveryRefused) as caught:
        run_clean(connection)
    assert caught.value.reason == 'fixture_remaining'
    assert not connection.mutated


def test_repeated_verified_cleanup_does_not_mutate_absent_resources():
    connection = FakeConnection(manifest())
    run_clean(connection)
    connection.calls.clear()
    connection.mutated = False
    run_clean(connection)
    assert not connection.mutated
    assert not any(query.startswith(('ALTER ', 'DELETE ', 'DROP ', 'REVOKE '))
                   for query, _ in connection.calls)
    # Missing roles must not be represented by PostgreSQL's PUBLIC oid=0,
    # which would accidentally select unrelated PUBLIC policies.
    policy_calls = [(query, params) for query, params in connection.calls
                    if 'recovery:policies' in query]
    assert policy_calls
    assert all(params[1:] == (None, None) and 'IS NOT NULL' in query
               for query, params in policy_calls)


def test_target_mismatch_is_refused_before_any_sql():
    connection = FakeConnection(manifest())
    with pytest.raises(RECOVERY.RecoveryRefused) as caught:
        run_clean(connection, manifest(target_sha256='d' * 64))
    assert caught.value.reason == 'target_mismatch'
    assert connection.calls == []


def test_expired_or_invalid_deadline_never_runs_sql():
    async def run():
        for deadline in (float('inf'), float('nan'), -1):
            connection = FakeConnection(manifest())
            transport = PG.PostgresTransport(connection, SQL, connection.manifest.target_sha256)
            with pytest.raises((TimeoutError, RECOVERY.RecoveryRefused)):
                await transport.clean(connection.manifest, deadline=deadline)
            assert connection.calls == []
    asyncio.run(run())


def private_config(tmp_path):
    certificate = tmp_path / 'ca.pem'
    password = tmp_path / 'pgpass'
    certificate.write_text('synthetic-public-ca')
    password.write_text('synthetic-private-passfile-canary')
    password.chmod(0o600)
    return SimpleNamespace(host='direct.example', port=5432, dbname='fixture', user='admin',
                           sslrootcert=certificate, passfile=password)


def test_explicit_connect_defers_driver_and_requires_tls_and_exact_identity(tmp_path, monkeypatch):
    config = private_config(tmp_path)
    calls = []
    connection = FakeConnection(manifest())
    connection.pgconn = SimpleNamespace(ssl_in_use=True)
    connection.info = SimpleNamespace(host=config.host, port=config.port,
                                      dbname=config.dbname, user=config.user)

    async def connect(**kwargs):
        calls.append(kwargs)
        return connection

    monkeypatch.setattr(PG, '_driver', lambda: SimpleNamespace(
        sql=SQL, OperationalError=ConnectionError, AsyncConnection=SimpleNamespace(connect=connect)))

    async def run():
        transport = await PG.connect_transport(config, asyncio.get_running_loop().time() + 5)
        assert transport.target_sha256 == RECOVERY.target_fingerprint(
            config.host, config.port, config.dbname, config.user)
        assert transport.connection is connection
        await transport.close()
    asyncio.run(run())
    assert calls[0]['sslmode'] == 'verify-full'
    assert calls[0]['passfile'] == str(config.passfile)
    assert calls[0]['sslrootcert'] == str(config.sslrootcert)
    assert 'password' not in calls[0]
    assert 'statement_timeout=5000' in calls[0]['options']
    assert connection.closed


@pytest.mark.parametrize('defect', ['tls', 'identity', 'passfile', 'pooler', 'environment'])
def test_connect_configuration_or_tls_failure_never_reaches_cleanup(tmp_path, monkeypatch, defect):
    config = private_config(tmp_path)
    connection = FakeConnection(manifest())
    connection.pgconn = SimpleNamespace(ssl_in_use=defect != 'tls')
    connection.info = SimpleNamespace(host='foreign.example' if defect == 'identity' else config.host,
        port=config.port, dbname=config.dbname, user=config.user)
    driver_calls = []
    async def connect(**kwargs):
        driver_calls.append(kwargs)
        return connection
    monkeypatch.setattr(PG, '_driver', lambda: SimpleNamespace(
        sql=SQL, OperationalError=ConnectionError, AsyncConnection=SimpleNamespace(connect=connect)))
    if defect == 'passfile':
        config.passfile.chmod(0o644)
    elif defect == 'pooler':
        config.host = 'direct-pooler.example'
    elif defect == 'environment':
        monkeypatch.setenv('PGPASSWORD', 'synthetic-password-canary')
    async def run():
        with pytest.raises(RECOVERY.RecoveryRefused) as caught:
            await PG.connect_transport(config, asyncio.get_running_loop().time() + 5)
        assert str(caught.value) == 'recovery_refused'
    asyncio.run(run())
    assert connection.calls == []
    if defect in ('tls', 'identity'):
        assert connection.closed
    else:
        assert driver_calls == []


def test_late_cancellation_ignoring_connect_is_closed_before_timeout(tmp_path, monkeypatch):
    config = private_config(tmp_path)
    connection = FakeConnection(manifest())
    async def connect(**kwargs):
        try:
            await asyncio.sleep(1)
        except asyncio.CancelledError:
            return connection
    monkeypatch.setattr(PG, '_driver', lambda: SimpleNamespace(
        sql=SQL, OperationalError=ConnectionError, AsyncConnection=SimpleNamespace(connect=connect)))
    async def run():
        with pytest.raises(TimeoutError):
            await PG.connect_transport(config, asyncio.get_running_loop().time() + 0.01)
        assert connection.closed
    asyncio.run(run())


def test_role_membership_check_rejects_authority_but_allows_only_current_creator_admin():
    connection = FakeConnection(manifest())
    run_clean(connection)
    query = next(query for query, _ in connection.calls if 'recovery:role' in query)
    assert 'm.member=r.oid' in query
    assert 'm.roleid=r.oid AND m.member<>current_user::regrole::oid' in query


@pytest.mark.parametrize(('closed', 'sqlstate', 'mapped'), [(True, None, True), (False, None, False), (True, '28P01', False)])
def test_only_actual_driver_type_and_lost_handle_map_sqlstateless_failure(closed, sqlstate, mapped):
    class DriverFailure(Exception):
        pass
    async def run():
        connection = FakeConnection(manifest())
        connection.closed = closed
        error = DriverFailure('private raw driver message')
        error.sqlstate = sqlstate
        async def fail(*args): raise error
        connection.execute = fail
        handle = PG.PostgresTransport(connection, SQL, connection.manifest.target_sha256,
                                      operational_error=DriverFailure)
        with pytest.raises(ConnectionError if mapped else DriverFailure) as captured:
            await handle.clean(connection.manifest, deadline=asyncio.get_running_loop().time() + 1)
        if mapped:
            assert str(captured.value) == 'recovery_connection_lost'
    asyncio.run(run())



def test_unexpected_delete_graph_refused_before_nologin_or_row_mutation():
    connection = FakeConnection(manifest())
    connection.safe_graph = False
    with pytest.raises(RECOVERY.RecoveryRefused) as caught:
        run_clean(connection)
    assert caught.value.reason == 'schema_mismatch'
    assert not connection.mutated
    assert not any(query.startswith(('ALTER ROLE', 'DELETE', 'DROP')) for query, _ in connection.calls)


def test_delete_graph_checks_collections_and_optional_vector_even_for_base_run():
    connection = FakeConnection(manifest(vectors=False))
    run_clean(connection)
    query, params = next(call for call in connection.calls if 'recovery:cascade' in call[0])
    assert 'chunk_vectors_fake_1536' in params[0]
    assert "c.confrelid='cragkit.collections'::regclass" in query
    assert '(SELECT count(*) FROM collection_edges)=1' in query
    assert 'i.inhrelid=c.oid OR i.inhparent=c.oid' in query
    assert "r.ev_type='4'" in query and '(t.tgtype::int & 8)<>0' in query
