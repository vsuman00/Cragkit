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


def security_result():
    result, migrations = valid_result()
    result.update(checks=list(probe.SECURITY_CHECKS) + ['tls_verified', 'complete_schema_roles_memberships_defaults_rollback'],
                  proof_scope=probe.SECURITY_PROOF_SCOPE)
    return result, migrations


def test_security_owner_scope_is_finite_and_explicitly_not_physical_proof():
    assert probe.SECURITY_PROOF_SCOPE == 'security_owner_recovery_sql_synthetic_metadata_only'
    assert type(probe.SECURITY_CHECKS) is tuple and 6 <= len(probe.SECURITY_CHECKS) <= 24
    assert len(set(probe.SECURITY_CHECKS)) == len(probe.SECURITY_CHECKS)
    assert all(type(item) is str and re.fullmatch('[a-z][a-z0-9_]{0,127}', item) for item in probe.SECURITY_CHECKS)
    assert probe.PROOF_SCOPE == 'recovery_dispatch_sql_synthetic_metadata_only'


def test_security_owner_mode_result_requires_exact_checks_scope_and_closed_fields():
    result, migrations = security_result()
    checker.validate_result(result, expected_migrations=migrations, expected_fingerprint='d' * 64, security_owner=True)
    for change in ('default_scope', 'physical_scope', 'missing', 'reordered', 'duplicate', 'extra'):
        altered = dict(result)
        if change == 'default_scope': altered['proof_scope'] = probe.PROOF_SCOPE
        elif change == 'physical_scope': altered['proof_scope'] = 'actual_physical_security_recovery'
        elif change == 'missing': altered['checks'] = result['checks'][:-1]
        elif change == 'reordered': altered['checks'] = list(reversed(result['checks']))
        elif change == 'duplicate': altered['checks'] = [result['checks'][0]] * len(result['checks'])
        else: altered['canonical_utf8'] = 'PRIVATE SOURCE'
        with pytest.raises(ValueError):
            checker.validate_result(altered, expected_migrations=migrations, expected_fingerprint='d' * 64, security_owner=True)
    with pytest.raises(ValueError):
        checker.validate_result(result, expected_migrations=migrations, expected_fingerprint='d' * 64)
    default, _ = valid_result()
    with pytest.raises(ValueError):
        checker.validate_result(default, expected_migrations=migrations, expected_fingerprint='d' * 64, security_owner=True)


@pytest.mark.parametrize('failure', ['none', 'probe', 'cleanup'])
def test_security_owner_cli_selects_mode_and_emits_artifact_only_after_cleanup(tmp_path, monkeypatch, capsys, failure):
    events = []
    class Fixture:
        checks = ['owned_process_stopped', 'owned_storage_removed']
        def __init__(self, *args, **kwargs): events.append('create')
        def __enter__(self): events.append('start'); return self
        def __exit__(self, *args):
            events.append('cleanup')
            if failure == 'cleanup': raise ConnectionError('PRIVATE CLEANUP')
    async def check(fixture, *, security_owner=False):
        assert security_owner is True
        events.append('security_probe')
        if failure == 'probe': raise RuntimeError('PRIVATE PROBE')
        return security_result()[0]
    monkeypatch.setattr(checker, 'PostgresSourceFixture', Fixture)
    monkeypatch.setattr(checker, 'check', check)
    directory = tmp_path/'security'
    code = checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(directory),
                         '--allow-local-processes', '--security-owner'])
    assert events == ['create', 'start', 'security_probe', 'cleanup']
    output = capsys.readouterr().out
    assert 'PRIVATE' not in output
    assert json.loads(output)['ok'] is (failure == 'none')
    assert code == (0 if failure == 'none' else 1)
    artifact = directory/'recovery-dispatch-sql-results.json'
    assert artifact.exists() is (failure == 'none')
    if artifact.exists():
        value = json.loads(artifact.read_text())
        assert value['proof_scope'] == probe.SECURITY_PROOF_SCOPE
        assert value['checks'] == security_result()[0]['checks']
        assert value['fixture_checks'] == Fixture.checks


def test_security_owner_mode_still_requires_process_opt_in_and_preserves_prior_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(checker, 'PostgresSourceFixture', lambda *args, **kwargs: pytest.fail('unexpected fixture'))
    with pytest.raises(SystemExit) as caught:
        checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(tmp_path/'new'), '--security-owner'])
    assert caught.value.code == 2
    retained = tmp_path/'retained.json';retained.write_text('original evidence')
    assert checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(tmp_path),
                         '--allow-local-processes', '--security-owner']) == 1
    assert retained.read_text() == 'original evidence'


def test_refused_existing_directory_preserves_failure_locations_and_never_starts_fixture(tmp_path, monkeypatch, capsys):
    original = b'{"retained":"original failure evidence"}\n'
    locations = tmp_path/'recovery-dispatch-sql-failure-locations.json';locations.write_bytes(original)
    monkeypatch.setattr(checker, 'PostgresSourceFixture', lambda *args, **kwargs: pytest.fail('unexpected fixture'))
    assert checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(tmp_path),
                         '--allow-local-processes', '--security-owner']) == 1
    assert locations.read_bytes() == original
    assert json.loads(capsys.readouterr().out)['ok'] is False


def test_auxiliary_failure_location_write_does_not_replace_primary_diagnostic(tmp_path, monkeypatch, capsys):
    class Fixture:
        def __init__(self, postgres_bin, directory): self.directory = directory
        def __enter__(self): self.directory.mkdir();return self
        def __exit__(self, *args): return False
    async def fail_check(fixture, *, security_owner=False):
        raise RuntimeError('PRIVATE ORIGINAL FAILURE')
    real_write = Path.write_text
    def write(self, *args, **kwargs):
        if self.name == 'recovery-dispatch-sql-failure-locations.json':
            raise PermissionError('PRIVATE AUXILIARY FAILURE')
        return real_write(self, *args, **kwargs)
    monkeypatch.setattr(checker, 'PostgresSourceFixture', Fixture)
    monkeypatch.setattr(checker, 'check', fail_check)
    monkeypatch.setattr(Path, 'write_text', write)
    assert checker.main(['--postgres-bin', str(tmp_path), '--artifacts-dir', str(tmp_path/'owned'),
                         '--allow-local-processes', '--security-owner']) == 1
    output = capsys.readouterr().out
    assert json.loads(output)['ok'] is False
    assert 'PRIVATE' not in output


class SecurityRecordingConnection(RecordingConnection):
    """Only supplies stable synthetic snapshots; never simulates SQL permission proof."""
    def __init__(self, failures=(), inventory_mismatch=False):
        super().__init__(failures)
        self.inventory_reads = 0
        self.inventory_mismatch = inventory_mismatch

    async def execute(self, query, params=None, *, prepare=False):
        result = await super().execute(query, params, prepare=prepare)
        if query.startswith('SELECT encode(sha256(convert_to(jsonb_build_object('):
            self.inventory_reads += 1
            return Cursor([(('b' if self.inventory_mismatch and self.inventory_reads > 1 else 'a') * 64,)])
        return result


def test_security_probe_preserves_original_snapshot_and_rolls_back_all_owned_cases():
    async def run():
        connection = SecurityRecordingConnection()
        current = state(connection)
        assert await probe.run_security_probes(connection, current) == list(probe.SECURITY_CHECKS)
        statements = [query for query, _ in connection.queries]
        assert connection.inventory_reads >= 2
        assert not any(re.match(r'^\s*(?:COMMIT|ROLLBACK)\s*;?\s*$', query) for query in statements)
        assert not any(re.match(r'^\s*(?:CREATE|ALTER|DROP|GRANT|REVOKE)\b', query) for query in statements)
        for save in [query for query in statements if query.startswith('SAVEPOINT ')]:
            name = save.removeprefix('SAVEPOINT ')
            assert statements.count('ROLLBACK TO SAVEPOINT ' + name) == statements.count(save)
            assert statements.count('RELEASE SAVEPOINT ' + name) == statements.count(save)
        snapshots = [query for query in statements if query.startswith('SELECT (SELECT encode(canonical_utf8')]
        assert snapshots
        assert all('revision_id=' in query and 'generation_id=' in query for query in snapshots)
        combined = '\n'.join(statements)
        assert len(combined.encode()) <= 524288
        assert 'WHEN OTHERS' not in combined and 'SECURITY DEFINER' not in combined
    asyncio.run(run())


def test_security_probe_restricted_role_seed_denied_owner_and_cross_generation_reservation_order():
    async def run():
        connection = SecurityRecordingConnection();current = state(connection)
        await probe.run_security_probes(connection, current)
        role = 'admin';records = []
        for query, params in connection.queries:
            if query == 'RESET ROLE': role = 'admin'
            elif query.startswith('SET LOCAL ROLE '): role = query.removeprefix('SET LOCAL ROLE ')
            records.append((role, query))
        writer = current.roles['writer'];supervisor = current.roles['supervisor']
        claim_inserts = [(index, query) for index, (selected, query) in enumerate(records)
                         if selected == writer and query.startswith('INSERT INTO cragkit_qdrant.point_claims ')]
        assert len(claim_inserts) == 2
        denial = next(index for index, (_, query) in enumerate(records)
                      if query.startswith('UPDATE cragkit_qdrant.publication_intents ') and "state='denied'" in query)
        reservation = next(index for index, (selected, query) in enumerate(records)
                           if selected == supervisor and query.startswith('INSERT INTO cragkit_qdrant.dispatch_journal '))
        assert max(index for index, _ in claim_inserts) < denial < reservation
        point_inserts = [query for selected, query in records
                         if selected == supervisor and query.startswith('INSERT INTO cragkit_qdrant.dispatch_points ')]
        assert len(point_inserts) == 4
        second = probe._security_second_generation(current)
        expected = {claim['point_id'] for claim in current.records['claims']} | {claim['point_id'] for claim in second['claims']}
        assert len(expected) == 4
        assert all(sum(identity in query for query in point_inserts) == 1 for identity in expected)
        assert any(query == 'SET CONSTRAINTS ALL IMMEDIATE' for _, query in records[reservation:])
        assert any(selected == supervisor and "state='settled'" in query for selected, query in records)
    asyncio.run(run())


def test_security_second_generation_preserves_original_seals_and_derives_distinct_exact_claims():
    connection = SecurityRecordingConnection();current = state(connection)
    before = json.dumps(current.records, sort_keys=True, default=lambda item: item.hex() if type(item) is bytes else item)
    second = probe._security_second_generation(current)
    assert before == json.dumps(current.records, sort_keys=True, default=lambda item: item.hex() if type(item) is bytes else item)
    assert second['generation']['generation_id'] != current.records['generation']['generation_id']
    assert second['generation']['revision_id'] == current.records['generation']['revision_id']
    assert second['intent']['manifest_sha256'] == sha256(second['intent']['manifest_bytes']).hexdigest()
    assert second['intent']['payload_sha256'] == sha256(second['intent']['payload_bytes']).hexdigest()
    assert {item['point_id'] for item in second['claims']}.isdisjoint(item['point_id'] for item in current.records['claims'])
    assert {item['point_id'] for item in second['claims']} == {item['point_id'] for item in second['members']} == {item['point_id'] for item in second['replays']}
    for original, copied in zip(current.records['replays'], second['replays'], strict=True):
        assert copied['dense_blob'] == original['dense_blob']
        assert copied['dense_blob_sha256'] == original['dense_blob_sha256']
        assert copied['sparse_blob'] == original['sparse_blob']
    assert second['revision'] == current.records['revision']


def test_security_probe_supervisor_reads_only_metadata_and_explicitly_rejects_sensitive_queries():
    async def run():
        connection = SecurityRecordingConnection();current = state(connection)
        await probe.run_security_probes(connection, current)
        role = 'admin';denied = set()
        for query, _ in connection.queries:
            if query == 'RESET ROLE': role = 'admin'
            elif query.startswith('SET LOCAL ROLE '): role = query.removeprefix('SET LOCAL ROLE ')
            if role != current.roles['supervisor']: continue
            sensitive = re.findall(r'SELECT\s+(request_bytes|payload_bytes|canonical_utf8|dense_blob|sparse_blob)\s+FROM\s+cragkit_qdrant\.', query)
            if sensitive:
                assert "SQLSTATE '42501'" in query
                denied.update(sensitive)
            assert not re.match(r'^\s*SELECT\s+\*\s+FROM\s+cragkit_qdrant\.', query)
        assert {'request_bytes','payload_bytes','canonical_utf8','dense_blob'} <= denied
        assert probe.SECURITY_PROOF_SCOPE.endswith('_sql_synthetic_metadata_only')
        assert any('synthetic' in label and 'settlement' in label for label in probe.SECURITY_CHECKS)
    asyncio.run(run())


@pytest.mark.parametrize('cleanup_failure', [False, True])
def test_security_probe_preserves_primary_failure_and_attempts_all_cleanup(cleanup_failure):
    async def run():
        armed = {'saved': False}
        def body(query):
            if query.startswith('SAVEPOINT '): armed['saved'] = True;return False
            return armed['saved'] and not query.startswith(('ROLLBACK TO SAVEPOINT ', 'RELEASE SAVEPOINT ', 'RESET ROLE'))
        primary = RuntimeError('PRIVATE PRIMARY SECURITY SQL')
        failures = [(body, primary)]
        if cleanup_failure: failures.append((lambda query: query.startswith('ROLLBACK TO SAVEPOINT '), ConnectionError('PRIVATE CLEANUP')))
        connection = SecurityRecordingConnection(failures)
        with pytest.raises(CleanupFailure if cleanup_failure else RuntimeError) as caught:
            await probe.run_security_probes(connection, state(connection))
        if cleanup_failure:
            assert 'PRIVATE' not in json.dumps(caught.value.to_dict())
        else: assert caught.value is primary
        statements = [query for query, _ in connection.queries]
        save = next(query.removeprefix('SAVEPOINT ') for query in statements if query.startswith('SAVEPOINT '))
        assert 'ROLLBACK TO SAVEPOINT '+save in statements
        assert 'RELEASE SAVEPOINT '+save in statements
        assert statements[-1] == 'RESET ROLE'
        assert 'COMMIT' not in statements and 'ROLLBACK' not in statements
    asyncio.run(run())


def test_security_probe_rejects_changed_original_or_rollback_inventory_without_completion():
    async def run():
        connection = SecurityRecordingConnection(inventory_mismatch=True)
        with pytest.raises(CleanupFailure):
            await probe.run_security_probes(connection, state(connection))
        assert connection.inventory_reads >= 2
        statements = [query for query, _ in connection.queries]
        assert any(query.startswith('ROLLBACK TO SAVEPOINT ') for query in statements)
        assert any(query.startswith('RELEASE SAVEPOINT ') for query in statements)
    asyncio.run(run())


def test_security_probe_records_exact_rejection_classes_before_synthetic_settlement(monkeypatch):
    inserted = []
    original_insert = probe.insert_sql
    def record_insert(table, record):
        inserted.append((table, dict(record)))
        return original_insert(table, record)
    monkeypatch.setattr(probe, 'insert_sql', record_insert)
    async def run():
        connection = SecurityRecordingConnection();current = state(connection)
        await probe.run_security_probes(connection, current)
        role = 'admin';refusals = []
        for query, _ in connection.queries:
            if query == 'RESET ROLE': role = 'admin'
            elif query.startswith('SET LOCAL ROLE '): role = query.removeprefix('SET LOCAL ROLE ')
            if 'DECLARE observed boolean' in query:
                refusals.append((role, query))
        writer = current.roles['writer'];supervisor = current.roles['supervisor']
        assert sum(role == writer and 'INSERT INTO cragkit_qdrant.dispatch_journal ' in query
                   and "SQLSTATE '23514'" in query for role, query in refusals) >= 2
        bad_dispatches = [query for role, query in refusals if role == supervisor
                          and 'INSERT INTO cragkit_qdrant.dispatch_journal ' in query]
        assert len(bad_dispatches) >= 5
        assert any(attestation.OWNER_CURRENT in query for query in bad_dispatches)
        assert any('g2-security-sql-authority' in query for query in bad_dispatches)
        journal_records = [record for table, record in inserted if table == 'dispatch_journal']
        assert {record['backend_epoch'] for record in journal_records} >= {1, 2, 3}
        assert any(record['owner_token'] == attestation.OWNER_CURRENT for record in journal_records)
        assert any(record['recovery'] is False for record in journal_records)
        bad_members = [query for role, query in refusals if role == supervisor
                       and 'INSERT INTO cragkit_qdrant.dispatch_points ' in query]
        assert len(bad_members) >= 3
        assert any('foreign_physical_collection' in query for query in bad_members)
        assert any('foreign-incarnation' in query for query in bad_members)
        assert any('00000000-0000-4000-8000-000000000099' in query for query in bad_members)
        takeovers = [(role, query) for role, query in refusals if 'UPDATE cragkit_qdrant.document_owners ' in query]
        assert any(role == supervisor and "SQLSTATE '42501'" in query for role, query in takeovers)
        assert any(role == writer and "SQLSTATE '23514'" in query for role, query in takeovers)
        statements = [query for query, _ in connection.queries]
        takeover_index = next(index for index, query in enumerate(statements)
                              if 'DECLARE observed boolean' in query and 'UPDATE cragkit_qdrant.document_owners ' in query)
        settled_index = next(index for index, query in enumerate(statements)
                             if query.startswith('UPDATE cragkit_qdrant.dispatch_journal ') and "state='settled'" in query)
        assert takeover_index < settled_index
    asyncio.run(run())


def test_security_original_fact_mismatch_is_primary_and_restores_all_cases():
    async def run():
        connection = SecurityRecordingConnection();current = state(connection)
        connection.snapshot = (('changed original bytes', 'generation', 'preparation'),)
        with pytest.raises(RuntimeError, match='security_recovery_changed_original_facts'):
            await probe.run_security_probes(connection, current)
        statements = [query for query, _ in connection.queries]
        assert 'ROLLBACK TO SAVEPOINT qa_security_owner_recovery' in statements
        assert 'RELEASE SAVEPOINT qa_security_owner_recovery' in statements
        assert 'RESET ROLE' in statements
    asyncio.run(run())
