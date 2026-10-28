"""Pure B0 probe safety checks; these doubles are not PostgreSQL evidence."""
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qdrant_attestation_schema as attestation
import qdrant_recovery_dispatch_sql as probe
import check_qdrant_recovery_dispatch_sql as checker
from runtime_diagnostics import CleanupFailure

ROOT = Path(__file__).resolve().parents[2]


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchall(self):
        return self.rows


class RecordingConnection:
    """Record statements without pretending to enforce SQL constraints or RLS."""
    def __init__(self, failures=()):
        self.queries = []
        self.failures = tuple(failures)
        self.snapshot = (('synthetic-canonical-hex', 'synthetic-generation-json', 'synthetic-preparation-json'),)

    async def execute(self, query, params=None, *, prepare=False):
        assert type(query) is str and prepare is False
        self.queries.append((query, params))
        for predicate, error in self.failures:
            if predicate(query):
                raise error
        rows = self.snapshot if query.startswith('SELECT (SELECT encode(canonical_utf8') else ()
        return Cursor(rows)


def state(connection):
    prefix = 'qa_probe_0123456789ab_'
    return attestation.AttestationProbeState(attestation.seed_records(),
        {kind: prefix + kind for kind in ('writer', 'reader', 'supervisor')}, connection.snapshot)


def normalized_sql():
    source = (ROOT/'storage/qdrant/postgres/migrations/0002_publication.sql').read_text()
    return re.sub(r'\s+', ' ', re.sub(r'--[^\n]*', '', source))


def test_existing_supervisor_grant_is_metadata_only_and_recovery_insert_remains_separate():
    """Independent schema boundary: insertion never implies reading request bodies."""
    sql = normalized_sql()
    journal = re.search(r'GRANT SELECT\s*\(([^)]+)\), INSERT, UPDATE\(([^)]+)\) ON '
        r'cragkit_qdrant\.dispatch_journal TO cragkit_qdrant_supervisor;', sql)
    assert journal is not None
    selected = {name.strip() for name in journal[1].split(',')}
    assert selected == {'tenant_id', 'collection', 'document_id', 'intent_id', 'dispatch_id',
        'instance_id', 'sequence', 'owner_token', 'backend_epoch', 'credential_generation',
        'operation', 'recovery', 'request_sha256', 'state', 'completion_sha256', 'created_xid'}
    assert {name.strip() for name in journal[2].split(',')} == {'state', 'completion_sha256'}
    assert not selected & {'request_bytes', 'payload_bytes', 'manifest_bytes', 'canonical_utf8', 'dense_blob', 'sparse_blob'}
    insert = re.search(r'CREATE POLICY supervisor_dispatch_insert\b(.*?);', sql)
    assert insert and 'FOR INSERT TO cragkit_qdrant_supervisor' in insert[1]
    assert 'cragkit_qdrant.supervisor_instance(instance_id) AND recovery' in insert[1]
    supervisor_grants = re.findall(r'GRANT\b[^;]+TO cragkit_qdrant_supervisor;', sql)
    assert not any(re.search(r'\b(?:document_revisions|vector_replays)\b', item) for item in supervisor_grants)


def test_probe_has_finite_distinct_metadata_checks():
    assert type(probe.CHECKS) is tuple and 4 <= len(probe.CHECKS) <= 24
    assert len(set(probe.CHECKS)) == len(probe.CHECKS)
    assert all(type(item) is str and re.fullmatch('[a-z][a-z0-9_]{0,127}', item) for item in probe.CHECKS)


def test_probe_owns_no_outer_commit_migration_or_grant_and_rolls_back_every_case():
    async def run():
        connection = RecordingConnection()
        result = await probe.run_probes(connection, state(connection))
        assert result == list(probe.CHECKS)
        statements = [query for query, _ in connection.queries]
        assert not any(re.match(r'^\s*(?:COMMIT|ROLLBACK)\s*;?\s*$', query) for query in statements)
        assert not any(re.match(r'^\s*(?:CREATE|ALTER|DROP|GRANT|REVOKE)\b', query) for query in statements)
        saves = [query for query in statements if query.startswith('SAVEPOINT ')]
        assert saves
        for save in saves:
            name = save.removeprefix('SAVEPOINT ')
            assert statements.count('ROLLBACK TO SAVEPOINT ' + name) == statements.count(save)
            assert statements.count('RELEASE SAVEPOINT ' + name) == statements.count(save)
        combined = '\n'.join(statements)
        assert len(combined.encode()) <= 262144
        assert 'WHEN OTHERS' not in combined and 'SECURITY DEFINER' not in combined
    asyncio.run(run())


def test_probe_rejects_missing_preupgrade_state_before_sql():
    async def run():
        connection = RecordingConnection()
        with pytest.raises((ValueError, TypeError)):
            await probe.run_probes(connection, attestation.AttestationProbeState({}, {}, ()))
        assert connection.queries == []
    asyncio.run(run())


def test_probe_primary_failure_preserves_savepoint_cleanup_and_no_completion_claim():
    async def run():
        primary = RuntimeError('PRIVATE PRIMARY SQL CANARY')
        armed = {'savepoint': False}
        def first_body(query):
            if query.startswith('SAVEPOINT '):
                armed['savepoint'] = True
                return False
            return armed['savepoint'] and not query.startswith(('ROLLBACK TO SAVEPOINT ', 'RELEASE SAVEPOINT ', 'RESET ROLE'))
        connection = RecordingConnection([(first_body, primary)])
        with pytest.raises(RuntimeError) as caught:
            await probe.run_probes(connection, state(connection))
        assert caught.value is primary
        statements = [query for query, _ in connection.queries]
        save = next(query.removeprefix('SAVEPOINT ') for query in statements if query.startswith('SAVEPOINT '))
        assert statements[-3:] == ['ROLLBACK TO SAVEPOINT ' + save, 'RELEASE SAVEPOINT ' + save, 'RESET ROLE']
        assert 'COMMIT' not in statements and 'ROLLBACK' not in statements
    asyncio.run(run())


def test_probe_reports_primary_and_cleanup_failures_without_private_content():
    async def run():
        armed = {'savepoint': False}
        def body(query):
            if query.startswith('SAVEPOINT '):
                armed['savepoint'] = True
                return False
            return armed['savepoint'] and not query.startswith(('ROLLBACK TO SAVEPOINT ', 'RELEASE SAVEPOINT ', 'RESET ROLE'))
        connection = RecordingConnection([(body, RuntimeError('PRIVATE SOURCE CANARY')),
            (lambda query: query.startswith('ROLLBACK TO SAVEPOINT '), ConnectionError('PRIVATE CONNECTION CANARY'))])
        with pytest.raises(CleanupFailure) as caught:
            await probe.run_probes(connection, state(connection))
        safe = json.dumps(caught.value.to_dict())
        assert 'PRIVATE' not in safe and 'CANARY' not in safe
        assert any(query.startswith('RELEASE SAVEPOINT ') for query, _ in connection.queries)
    asyncio.run(run())


def test_cli_requires_explicit_local_process_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(checker, 'PostgresSourceFixture', lambda *args, **kwargs: pytest.fail('unexpected process'))
    with pytest.raises(SystemExit) as caught:
        checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(tmp_path/'new')])
    assert caught.value.code == 2


def test_cli_preserves_existing_artifacts_before_process_admission(tmp_path, monkeypatch, capsys):
    existing = tmp_path/'previous-result.json'
    existing.write_text('retained evidence')
    monkeypatch.setattr(checker, 'PostgresSourceFixture', lambda *args, **kwargs: pytest.fail('unexpected process'))
    result = checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(tmp_path), '--allow-local-processes'])
    assert result == 1 and json.loads(capsys.readouterr().out)['ok'] is False
    assert existing.read_text() == 'retained evidence'


def test_synthetic_recovery_fixture_is_bounded_and_digest_bound_without_http_proof():
    connection = RecordingConnection()
    item = probe.recovery_record(state(connection))
    assert item['recovery'] is True and item['backend_epoch'] == 2 and item['sequence'] == 2
    assert type(item['request_bytes']) is bytes and 1 <= len(item['request_bytes']) <= 1048576
    assert item['request_sha256'] == sha256(item['request_bytes']).hexdigest()
    assert 'synthetic' in item['credential_generation']
    assert 'completion_sha256' not in item
    with pytest.raises(ValueError):
        probe.recovery_record(state(connection), source_text='PRIVATE')
    assert 'source_text' not in item


@pytest.mark.parametrize('membership', ['empty', 'oversized', 'duplicate'])
def test_membership_bound_fails_before_sql(membership):
    async def run():
        connection = RecordingConnection()
        current = state(connection)
        claims = current.records['claims']
        current.records['claims'] = ([] if membership == 'empty' else
            [claims[0]] * (9 if membership == 'oversized' else 2))
        with pytest.raises(ValueError):
            await probe.run_probes(connection, current)
        assert connection.queries == []
    asyncio.run(run())


def test_successful_supervisor_queries_do_not_select_source_or_request_bodies():
    async def run():
        connection = RecordingConnection()
        current = state(connection)
        await probe.run_probes(connection, current)
        selected_role = None
        denials = set()
        for query, params in connection.queries:
            if query == 'RESET ROLE':
                selected_role = 'admin'
            elif query.startswith('SET LOCAL ROLE '):
                selected_role = query.removeprefix('SET LOCAL ROLE ')
            if selected_role != current.roles['supervisor']:
                continue
            forbidden = re.findall(r'SELECT\s+(request_bytes|canonical_utf8|dense_blob)\s+FROM\s+cragkit_qdrant\.', query)
            if forbidden:
                assert "SQLSTATE '42501'" in query
                denials.update(forbidden)
            assert not re.match(r'^\s*SELECT\s+\*\s+FROM\s+cragkit_qdrant\.', query)
        assert denials == {'request_bytes', 'canonical_utf8', 'dense_blob'}
    asyncio.run(run())


def test_legacy_snapshot_mismatch_fails_and_still_restores_case():
    async def run():
        connection = RecordingConnection()
        current = state(connection)
        connection.snapshot = (('changed-source', 'generation', 'preparation'),)
        with pytest.raises(RuntimeError, match='recovery_dispatch_changed_legacy_facts'):
            await probe.run_probes(connection, current)
        statements = [query for query, _ in connection.queries]
        assert statements[-3:] == ['ROLLBACK TO SAVEPOINT qa_recovery_dispatch',
            'RELEASE SAVEPOINT qa_recovery_dispatch', 'RESET ROLE']
    asyncio.run(run())


def test_inventory_guard_requires_exact_native_string_equality():
    digest = 'a' * 64
    checker.assert_rollback_inventory(digest, digest)
    for before, after in [(digest, 'b' * 64), (None, None), ([digest], [digest])]:
        with pytest.raises(RuntimeError):
            checker.assert_rollback_inventory(before, after)


def valid_result():
    migrations = [['0001_source', 'a' * 64], ['0002_publication', 'b' * 64], ['0003_attestation', 'c' * 64]]
    result = dict(checks=list(probe.CHECKS) + ['tls_verified', 'complete_schema_roles_memberships_defaults_rollback'],
        migrations=migrations, catalog_fingerprint='d' * 64, proof_scope=probe.PROOF_SCOPE)
    return result, migrations


@pytest.mark.parametrize('change', ['secret_extra', 'physical_scope', 'missing_check', 'wrong_catalog', 'extra_migration'])
def test_artifact_validation_refuses_open_data_physical_claims_and_profile_drift(change):
    result, migrations = valid_result()
    expected = [list(item) for item in migrations]
    if change == 'secret_extra':
        result['request_bytes'] = 'PRIVATE SOURCE CANARY'
    elif change == 'physical_scope':
        result['proof_scope'] = 'actual_fenced_and_verified'
    elif change == 'missing_check':
        result['checks'] = result['checks'][:-1]
    elif change == 'wrong_catalog':
        result['catalog_fingerprint'] = 'e' * 64
    else:
        result['migrations'] = migrations + [['0004_unapproved', 'f' * 64]]
    with pytest.raises(ValueError):
        checker.validate_result(result, expected_migrations=expected, expected_fingerprint='d' * 64)


def test_artifact_validation_accepts_only_declared_sql_metadata_scope():
    result, migrations = valid_result()
    checker.validate_result(result, expected_migrations=migrations, expected_fingerprint='d' * 64)
    assert result['proof_scope'] == 'recovery_dispatch_sql_synthetic_metadata_only'


@pytest.mark.parametrize('failure', ['none', 'probe', 'cleanup'])
def test_cli_success_requires_probe_and_owned_fixture_stop(tmp_path, monkeypatch, capsys, failure):
    events = []
    class Fixture:
        checks = ['owned_process_stopped', 'owned_storage_removed']
        def __init__(self, *args, **kwargs): events.append('create')
        def __enter__(self): events.append('start'); return self
        def __exit__(self, *args):
            events.append('cleanup')
            if failure == 'cleanup': raise ConnectionError('PRIVATE CLEANUP CANARY')
    async def check(fixture):
        events.append('probe')
        if failure == 'probe': raise RuntimeError('PRIVATE QUERY CANARY')
        return valid_result()[0]
    monkeypatch.setattr(checker, 'PostgresSourceFixture', Fixture)
    monkeypatch.setattr(checker, 'check', check)
    directory = tmp_path/'new'
    code = checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(directory), '--allow-local-processes'])
    assert events == ['create', 'start', 'probe', 'cleanup']
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output and 'CANARY' not in output
    assert json.loads(output)['ok'] == (failure == 'none')
    assert code == (0 if failure == 'none' else 1)
    artifact = directory/'recovery-dispatch-sql-results.json'
    assert artifact.exists() == (failure == 'none')
    if artifact.exists():
        result = json.loads(artifact.read_text())
        assert result['fixture_checks'] == Fixture.checks
        assert result['proof_scope'] == probe.PROOF_SCOPE
