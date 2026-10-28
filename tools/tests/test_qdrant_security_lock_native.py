"""Counterexample wiring tests; doubles do not establish PostgreSQL lock behavior."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
import json
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qdrant_security_lock_cases as cases
import check_qdrant_security_lock as checker


def test_lock_counterexample_check_sequence_is_finite_unique_and_sql_only():
    assert type(cases.CHECKS) is tuple and len(cases.CHECKS) == 8
    assert len(set(cases.CHECKS)) == 8
    assert all(type(value) is str and re.fullmatch('[a-z][a-z0-9_]{0,127}', value) for value in cases.CHECKS)
    assert checker.PROOF_SCOPE == 'two_connection_guard_counterexample_sql_only'


def test_lock_cli_requires_explicit_local_process_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(checker, 'PostgresSourceFixture', lambda *args, **kwargs: pytest.fail('unexpected fixture'))
    with pytest.raises(SystemExit) as caught:
        checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(tmp_path/'new')])
    assert caught.value.code == 2


def test_lock_cli_preserves_existing_artifacts_and_never_starts_fixture(tmp_path, monkeypatch, capsys):
    original = b'{"original":"counterexample evidence"}\n'
    retained = tmp_path/'results.json';retained.write_bytes(original)
    monkeypatch.setattr(checker, 'PostgresSourceFixture', lambda *args, **kwargs: pytest.fail('unexpected fixture'))
    assert checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(tmp_path), '--allow-local-processes']) == 1
    assert retained.read_bytes() == original
    assert json.loads(capsys.readouterr().out)['ok'] is False


@pytest.mark.parametrize('outcome', ['success','wrong_checks','probe','fixture_cleanup'])
def test_lock_cli_writes_success_only_after_exact_probe_and_fixture_cleanup(tmp_path, monkeypatch, capsys, outcome):
    events = []
    class Fixture:
        def __init__(self, postgres_bin, directory, *, max_connections):
            assert max_connections == 6
            events.append('fixture_create')
        def __enter__(self): events.append('fixture_start');return self
        def __exit__(self, *args):
            events.append('fixture_cleanup')
            if outcome == 'fixture_cleanup': raise ConnectionError('PRIVATE CLEANUP')
    class Database:
        def __init__(self, fixture, *, with_attestations):
            assert with_attestations is True
        async def __aenter__(self): events.append('database_open');return self
        async def __aexit__(self, *args): events.append('database_close')
    async def run(database):
        events.append('probe')
        if outcome == 'probe': raise RuntimeError('PRIVATE PROBE')
        return list(reversed(cases.CHECKS)) if outcome == 'wrong_checks' else list(cases.CHECKS)
    monkeypatch.setattr(checker, 'PostgresSourceFixture', Fixture)
    monkeypatch.setattr(checker, 'PublicationDatabase', Database)
    monkeypatch.setattr(checker, 'run_security_lock_cases', run)
    directory = tmp_path/'new'
    code = checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(directory), '--allow-local-processes'])
    assert events == ['fixture_create','fixture_start','database_open','probe','database_close','fixture_cleanup']
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output
    assert code == (0 if outcome == 'success' else 1)
    assert json.loads(output)['ok'] is (outcome == 'success')
    artifact = directory/'results.json'
    assert artifact.exists() is (outcome == 'success')
    if artifact.exists():
        result = json.loads(artifact.read_text())
        assert set(result) == {'ok','checks','proof_scope','counterexample_observed','cleanup_verified'}
        assert result['checks'] == list(cases.CHECKS)
        assert result['proof_scope'] == checker.PROOF_SCOPE
        assert result['counterexample_observed'] is True and result['cleanup_verified'] is True


class Cursor:
    def __init__(self, rows): self.rows = rows
    async def fetchall(self): return self.rows


class RecordingAdmin:
    """Returns observations supplied by the test; never evaluates SQL locks."""
    def __init__(self, observations):
        self.observations = iter(observations)
        self.queries = []
    async def execute(self, statement, params=(), **options):
        self.queries.append((statement, params, options))
        return Cursor(next(self.observations))


def test_wait_observation_requires_actual_positive_rows_not_elapsed_polling(monkeypatch):
    async def run():
        admin = RecordingAdmin([[(False,)], [(True,)]])
        sleeps = []
        async def yield_once(delay): sleeps.append(delay)
        monkeypatch.setattr(cases.asyncio, 'sleep', yield_once)
        await cases._wait_observation(admin, 'SELECT actual_lock_wait', ('supervisor-pid',),
                                      deadline=asyncio.get_running_loop().time()+1)
        assert len(admin.queries) == 2
        assert all(query == 'SELECT actual_lock_wait' and params == ('supervisor-pid',)
                   for query, params, _ in admin.queries)
        assert sleeps and all(0 <= delay <= .1 for delay in sleeps)
    asyncio.run(run())


@pytest.mark.parametrize('done', ['success','failure'])
def test_wait_observation_cannot_claim_barrier_after_commit_task_already_finished(done):
    async def run():
        admin = RecordingAdmin([[(False,)]])
        pending = asyncio.get_running_loop().create_future()
        if done == 'failure': pending.set_exception(RuntimeError('PRIVATE COMMIT FAILURE'))
        else: pending.set_result(None)
        try:
            with pytest.raises(RuntimeError):
                await cases._wait_observation(admin, 'SELECT actual_commit_advisory_wait', (),
                                              deadline=asyncio.get_running_loop().time()+1, pending=pending)
        finally:
            if done == 'failure': pending.exception()
    asyncio.run(run())


def test_wait_observation_expired_deadline_refuses_without_waiting():
    async def run():
        admin = RecordingAdmin([[(False,)]])
        with pytest.raises((RuntimeError, TimeoutError)):
            await cases._wait_observation(admin, 'SELECT actual_lock_wait', (),
                                          deadline=asyncio.get_running_loop().time()-1)
        assert len(admin.queries) <= 1
    asyncio.run(run())


def test_native_lock_failure_protocol_is_closed_copied_and_redacted():
    assert type(cases.ERRORS) is tuple and len(set(cases.ERRORS)) == len(cases.ERRORS)
    for error in (value for value in cases.ERRORS if value != 'cleanup_failed'):
        original = dict(ok=False, step=0, error=error)
        failure = cases.NativeSecurityLockFailure(original)
        original['error'] = 'PRIVATE MUTATION'
        assert failure.observation == dict(ok=False, step=0, error=error)
        assert 'PRIVATE' not in str(failure)
        assert cases.NativeSecurityLockFailure(dict(ok=False,step=8,error=error)).observation['step'] == 8
    for primary in (None,'internal','ProviderUnavailable'):
        original = dict(ok=False,step=3,error='cleanup_failed',primary=primary)
        failure = cases.NativeSecurityLockFailure(original)
        original['primary'] = 'PRIVATE'
        assert failure.observation == dict(ok=False,step=3,error='cleanup_failed',primary=primary)
    for value in (dict(ok=False,step=True,error='internal'),dict(ok=False,step=-1,error='internal'),
                  dict(ok=False,step=9,error='internal'),dict(ok=False,step=0,error='PRIVATE'),
                  dict(ok=False,step=0,error='internal',sql='PRIVATE'),
                  dict(ok=False,step=0,error='cleanup_failed'),
                  dict(ok=False,step=0,error='cleanup_failed',primary='PRIVATE'),
                  dict(ok=False,step=0,error='cleanup_failed',primary='cleanup_failed'),None):
        with pytest.raises((ValueError, TypeError)):
            cases.NativeSecurityLockFailure(value)


def test_cli_reports_only_closed_native_failure_without_source_or_connection_details(tmp_path, monkeypatch, capsys):
    class Fixture:
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): return False
    async def check(fixture):
        raise cases.NativeSecurityLockFailure(dict(ok=False,step=3,error='internal')) from RuntimeError('PRIVATE SOURCE AND CREDENTIALS')
    monkeypatch.setattr(checker, 'PostgresSourceFixture', Fixture)
    monkeypatch.setattr(checker, 'check', check)
    assert checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(tmp_path/'new'), '--allow-local-processes']) == 1
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output
    assert json.loads(output)['native'] == dict(ok=False,step=3,error='internal')
    assert not (tmp_path/'new'/'results.json').exists()


def test_snapshot_digest_is_closed_scoped_and_never_returns_source_rows():
    from qdrant_writer_cases import writer_input
    async def run():
        inputs = writer_input()
        admin = RecordingAdmin([[('a'*64,)]])
        assert await cases._snapshot(admin, inputs) == 'a'*64
        assert len(admin.queries) == 1
        query, params, _ = admin.queries[0]
        assert query.startswith('SELECT encode(sha256(convert_to(jsonb_build_object(')
        assert 'point_claims' in query and 'generations' in query and 'publication_intents' in query
        # Every original fact lookup retains the synthetic document identity.
        assert 'tenant_id' in query and 'collection' in query and 'document_id' in query
        for malformed in ([],[(None,)], [('PRIVATE SOURCE',)], [('a'*64,'extra')]):
            with pytest.raises((RuntimeError, ValueError)):
                await cases._snapshot(RecordingAdmin([malformed]), inputs)
    asyncio.run(run())


def test_security_change_fixture_binds_expected_and_new_revision_without_mutating_inputs():
    from qdrant_writer_cases import writer_input
    inputs = writer_input()
    original = json.dumps(inputs, sort_keys=True)
    change = cases._security_change(inputs,'replacement-security','auth-2',2,'auth-3')
    assert change['action'] == 'update_authorization'
    assert change['intent_id'] == 'replacement-security'
    assert change['expected_authorization_revision'] == 'auth-2' and change['expected_mutation_epoch'] == 2
    assert change['authorization']['authorization_revision'] == 'auth-3'
    assert change['tenant_id'] == inputs['scope']['tenant_id']
    assert change['collection'] == inputs['stage']['intent']['collection']
    assert change['document_id'] == inputs['stage']['intent']['document_id']
    assert json.dumps(inputs, sort_keys=True) == original


@pytest.mark.parametrize('fault', [None,'barrier_install','guard_close','replacement','cleanup_drop','replacement_and_cleanup'])
def test_fake_database_enforces_guard_loss_replacement_and_retained_control_order(monkeypatch, fault):
    """Exercise orchestration/custody only; SQL observations are supplied doubles."""
    from qdrant_writer_cases import writer_input
    inputs = writer_input()
    authorization = inputs['stage']['intent']['initial_authorization']
    events = []
    class State:
        revision = 'auth-1'
        epoch = 1
        live = 0
        maximum = 0
        next_pid = 100
        guard = None
        barrier = False
        journal = 'unknown'
        completion = None
        denied = False
        def __init__(self):
            self.barrier_release = asyncio.Event()
            self.guard_release = asyncio.Event()
            self.authorization = json.loads(json.dumps(authorization))
    async def run():
        state = State()
        def opened():
            state.live += 1;state.maximum = max(state.maximum,state.live)
            assert state.live <= 2  # The separate admin is the third client.
        class Connection:
            def __init__(self, kind):
                opened();self.kind = kind;self.closed = False
                state.next_pid += 1;self.info = type('Info',(),{'backend_pid':state.next_pid})()
            @asynccontextmanager
            async def transaction(self): yield
            async def execute(self, query, params=(), **kwargs):
                events.append((self.kind,query))
                if query.startswith('BEGIN') and self.kind == 'writer': state.guard = self;state.guard_release = asyncio.Event()
                if "SET state='settled'" in query: state.completion = params[0]
                if query == 'COMMIT':
                    events.append(('commit','submitted'))
                    await state.barrier_release.wait()
                    state.journal = 'settled';events.append(('commit','completed'))
                if query == 'ROLLBACK' and self.kind == 'writer': state.guard_release.set()
                return Cursor([])
            async def close(self):
                if self.closed:return
                self.closed = True;state.live -= 1;events.append(('close',self.kind))
                if state.guard is self: state.guard = None;state.guard_release.set()
                if fault == 'guard_close' and self.kind == 'writer' and 'guard_close_failed' not in events:
                    events.append('guard_close_failed');raise ConnectionError('PRIVATE GUARD CLOSE')
        class Admin:
            async def execute(self, query, params=(), **kwargs):
                events.append(('admin',query))
                if 'pg_advisory_lock(' in query:state.barrier = True
                if 'pg_advisory_unlock(' in query:state.barrier = False;state.barrier_release.set()
                if query.startswith('DROP SCHEMA') and fault in ('cleanup_drop','replacement_and_cleanup'):raise RuntimeError('PRIVATE CLEANUP')
                return Cursor([])
        class Database:
            admin = Admin()
            with_attestations = True
            def config(self, kind):return {'user':'restricted-'+kind}
        class Resource:
            def __init__(self):self.connection = Connection('pool-writer')
            @asynccontextmanager
            async def lease(self, **kwargs):yield self.connection
            async def close(self):await self.connection.close()
        class Writer:
            async def stage(self, *args, **kwargs):events.append(('writer','stage'))
            async def admit_publication(self, *args, **kwargs):return {'intent':{'state':'denied' if state.denied else 'writing'}}
            async def reserve_dispatch(self, *args, **kwargs):events.append(('writer','reserve'))
            async def mark_dispatched(self, *args, **kwargs):pass
            async def mark_unknown(self, *args, **kwargs):pass
            async def apply_security(self, change, *args, **kwargs):
                desired = change['authorization']['authorization_revision']
                if desired == 'auth-3':
                    assert state.guard is None and state.barrier and state.journal == 'unknown'
                    if fault in ('replacement','replacement_and_cleanup'):raise RuntimeError('PRIVATE REPLACEMENT')
                if desired == 'auth-4':
                    events.append(('authority','control_started'))
                    assert state.guard is not None
                    await state.guard_release.wait()
                state.revision = desired;state.epoch += 1;state.denied = True
                state.authorization = change['authorization']
                events.append(('authority',desired));return {'authority_committed':True}
            async def close(self):events.append(('writer','closed'))
        async def writer(database, selected):return Writer(),Resource()
        async def connect(database, kind):return Connection(kind)
        async def install(admin, login, key):
            events.append(('barrier','install'))
            assert login == 'restricted-supervisor'
            assert type(key) is int and 1 <= key < 2147483647
            if fault == 'barrier_install':raise RuntimeError('PRIVATE PARTIAL INSTALL')
        async def snapshot(admin, selected):
            assert state.denied
            events.append(('snapshot','immutable-denied-history'));return 'a'*64
        async def rows(connection, query, params=()):
            if query == 'SELECT pg_backend_pid()':return [(connection.info.backend_pid,)]
            if query.startswith('SELECT authorization_revision,mutation_epoch,principal_ids'):
                current = state.authorization
                return [(state.revision,state.epoch,current['principal_ids'],current['grant_ids'],
                         current['language'],current['kind'],current['tag'],False,None)]
            if query.startswith('SELECT authorization_revision,mutation_epoch FROM'):return [(state.revision,state.epoch)]
            if query.startswith('SELECT state,completion_sha256 FROM'):return [(state.journal,state.completion)]
            return [('unchanged-production-catalog',)]
        async def wait(admin, query, params, *, deadline, pending=None):
            await asyncio.sleep(0)
            if "a.query='COMMIT'" in query:
                assert pending is not None and not pending.done() and state.barrier
                events.append(('observation','actual-commit-wait'))
            elif "locktype IN ('transactionid','tuple')" in query:
                assert pending is not None and not pending.done() and state.guard is not None
                assert params[1] == state.guard.info.backend_pid and 'pg_blocking_pids' in query
                events.append(('observation','replacement-writer-wait'))
            elif 'pid=ANY' in query:assert state.live == 0
            else:assert state.guard is None
        monkeypatch.setattr(cases,'_writer',writer)
        monkeypatch.setattr(cases,'_connect',connect)
        monkeypatch.setattr(cases,'_install_barrier',install)
        monkeypatch.setattr(cases,'_snapshot',snapshot)
        monkeypatch.setattr(cases,'_rows',rows)
        monkeypatch.setattr(cases,'_wait_observation',wait)
        if fault is None:
            assert await cases.run_security_lock_cases(Database()) == list(cases.CHECKS)
            assert events.index(('authority','auth-3')) < events.index(('commit','completed'))
            assert events.index(('observation','replacement-writer-wait')) < events.index(('authority','auth-4'))
            assert state.revision == 'auth-4' and state.journal == 'settled'
        else:
            with pytest.raises(cases.NativeSecurityLockFailure) as caught:
                await cases.run_security_lock_cases(Database())
            assert caught.value.observation['error'] in cases.ERRORS
            assert 'PRIVATE' not in str(caught.value)
            if fault == 'replacement_and_cleanup':
                assert caught.value.observation['error'] == 'cleanup_failed'
                assert caught.value.observation['primary'] == 'internal'
        assert state.live == 0
        assert state.maximum <= 2
        dropped = any(isinstance(event,tuple) and str(event[1]).startswith('DROP SCHEMA IF EXISTS cragkit_security_lock_fixture') for event in events)
        assert dropped is (fault != 'barrier_install')
    asyncio.run(run())


def test_fixture_barrier_is_deferred_and_privileges_stay_in_disposable_namespace():
    async def run():
        class Admin:
            def __init__(self): self.statements = []
            @asynccontextmanager
            async def transaction(self): yield
            async def execute(self, query, params=(), **options):
                self.statements.append(query if type(query) is str else query.as_string(None))
                return Cursor([])
        admin = Admin()
        await cases._install_barrier(admin, 'disposable_supervisor_login', 4123)
        statements = admin.statements
        combined = '\n'.join(statements)
        assert 'DEFERRABLE INITIALLY DEFERRED' in combined
        assert 'pg_catalog.pg_advisory_xact_lock(4123)' in combined
        assert 'CHECK(lock_key=4123)' in combined
        assert 'SECURITY DEFINER SET search_path=pg_catalog' in combined
        assert any(query.startswith('REVOKE ALL ON FUNCTION cragkit_security_lock_fixture.') and query.endswith(' FROM PUBLIC') for query in statements)
        grants = [query for query in statements if query.startswith('GRANT ')]
        assert len(grants) == 2
        assert any(query.startswith('GRANT USAGE ON SCHEMA cragkit_security_lock_fixture ') for query in grants)
        assert any(query.startswith('GRANT INSERT ON cragkit_security_lock_fixture.commit_barrier ') for query in grants)
        assert all('disposable_supervisor_login' in query for query in grants)
        assert not any(re.search(r'\b(?:ON|TABLE|FUNCTION)\s+cragkit_qdrant\.', query) for query in statements)
        assert 'GRANT EXECUTE' not in combined
        for invalid in (True,0,-1,2147483647,'4123'):
            before = len(admin.statements)
            with pytest.raises(ValueError): await cases._install_barrier(admin,'disposable_supervisor_login',invalid)
            assert len(admin.statements) == before
    asyncio.run(run())


@pytest.mark.parametrize('role_rows', [[(True,True)],[(True,False)],[(False,True)],[]])
def test_runtime_connection_admission_refuses_role_drift_and_closes_rejected_client(role_rows):
    async def run():
        class Connection(RecordingAdmin):
            def __init__(self): super().__init__([role_rows]);self.closed = False
            async def close(self): self.closed = True
        connection = Connection()
        class Database:
            def config(self, kind): assert kind == 'supervisor';return {'user':'restricted-login'}
            async def _connect(self, config): assert config == {'user':'restricted-login'};return connection
        if role_rows == [(True,True)]:
            assert await cases._connect(Database(),'supervisor') is connection
            assert connection.closed is False
        else:
            with pytest.raises(RuntimeError): await cases._connect(Database(),'supervisor')
            assert connection.closed is True
    asyncio.run(run())
