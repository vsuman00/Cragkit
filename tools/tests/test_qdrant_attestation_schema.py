"""Pure probe/loader checks. Recorded SQL is not database acceptance evidence."""
import asyncio
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qdrant_attestation_schema as schema


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def fetchall(self):
        return self.rows


class RecordingConnection:
    """A supplied connection records construction only, without evaluating SQL."""
    def __init__(self, fail=None):
        self.queries = []
        self.fail = fail
        self.snapshot = [('synthetic-canonical-hex', 'synthetic-generation-json', 'synthetic-preparation-json')]

    async def execute(self, query, params=None, *, prepare):
        assert prepare is False
        assert type(query) is str
        self.queries.append((query, params))
        if self.fail is not None and self.fail(query):
            raise RuntimeError('injected_connection_failure')
        return Cursor(self.snapshot if query.startswith('SELECT (SELECT encode(canonical_utf8') else [])


def test_migration_binds_exact_version_bytes_and_immutable_metadata(tmp_path):
    path = tmp_path / '0003_preparation_attestations.sql'
    raw = b'CREATE TABLE cragkit_qdrant.probe(id integer);\n'
    path.write_bytes(raw)
    item = schema.migration(path)
    assert item.version == '0003_preparation_attestations'
    assert item.checksum == sha256(raw).hexdigest()
    assert item.sql.encode() == raw
    with pytest.raises(FrozenInstanceError):
        item.checksum = 'changed'


@pytest.mark.parametrize('raw', [b'', b'BEGIN;\n', b'COMMIT;\n', b'ROLLBACK;\n',
    b'\\include hidden.sql\n', b'-- windows\r\n', b'-- $qw_probe$\n', b'\xff', b'x' * 1048577])
def test_loader_rejects_transaction_escape_invalid_encoding_and_unbounded_input(tmp_path, raw):
    path = tmp_path / '0003_preparation_attestations.sql'
    path.write_bytes(raw)
    with pytest.raises((ValueError, UnicodeError)):
        schema.migration(path)


def test_loader_rejects_other_migration_identity_before_reading(tmp_path):
    with pytest.raises(ValueError, match='attestation_migration_identity'):
        schema.migration(tmp_path / '0002_publication.sql')


def test_attestation_tuple_is_exact_and_key_excludes_mutable_or_ordering_columns():
    records = schema.seed_records()
    state = schema.AttestationProbeState(records, {}, ())
    row = schema.attestation_record(state)
    assert tuple(row) == schema.ATTESTATION_COLUMNS
    assert len(row) == 14
    assert schema.ATTESTATION_KEY == ('tenant_id', 'collection', 'document_id', 'intent_id', 'backend_epoch', 'owner_token')
    assert row['backend_epoch'] == 2 and row['owner_token'] == schema.OWNER_CURRENT
    assert row['expected_active_generation_id'] is None
    assert row['manifest_sha256'] == records['intent']['manifest_sha256']
    assert row['readback_sha256'] == sha256(b'G0 SQL-only synthetic current readback').hexdigest()
    with pytest.raises(ValueError, match='attestation_probe_field'):
        schema.attestation_record(state, source_text='not-an-attestation-field')
    changed = schema.attestation_record(state, backend_epoch=3)
    assert changed['backend_epoch'] == 3
    assert row['backend_epoch'] == 2


def test_preupgrade_seeding_is_restricted_role_sql_only_and_leaves_no_commit_or_temp_objects():
    async def run():
        connection = RecordingConnection()
        state = await schema.seed_pre_upgrade(connection)
        assert state.legacy_snapshot == tuple(tuple(row) for row in connection.snapshot)
        assert len(state.roles) == 3
        assert len(set(state.roles.values())) == 3
        for name in state.roles.values():
            assert re.fullmatch(r'qa_probe_[0-9a-f]{12}_(?:writer|reader|supervisor)', name)
        statements = [query for query, _ in connection.queries]
        assert sum(query.startswith('CREATE ROLE ') for query in statements) == 3
        assert not any(re.match(r'^(?:COMMIT|ROLLBACK|CREATE TEMP|BEGIN)\b', query) for query in statements)
        assert not any('preparation_attestations' in query for query in statements)
        preparation_index = next(index for index, query in enumerate(statements) if query.startswith('INSERT INTO cragkit_qdrant.preparations'))
        selected = next(query for query in reversed(statements[:preparation_index]) if query.startswith('SET LOCAL ROLE '))
        assert selected == 'SET LOCAL ROLE ' + state.roles['writer']
        assert any("SET state='settled',completion_sha256=" in query for query in statements)
        assert any("SET state='prepared'" in query for query in statements)
    asyncio.run(run())


def test_probe_plan_covers_exact_fences_legacy_preservation_and_rollback_cases():
    async def run():
        connection = RecordingConnection()
        state = await schema.seed_pre_upgrade(connection)
        connection.queries.clear()
        checks = await schema.run_probes(connection, state)
        assert checks == list(schema.CHECKS)
        statements = [query for query, _ in connection.queries]
        assert statements[-1] == 'SET CONSTRAINTS ALL IMMEDIATE'
        saves = statements.count('SAVEPOINT qa_case')
        assert saves >= 14
        assert saves == statements.count('ROLLBACK TO SAVEPOINT qa_case') == statements.count('RELEASE SAVEPOINT qa_case')
        assert not any(re.match(r'^(?:COMMIT|ROLLBACK)(?:\s*;)?$', query) for query in statements)
        combined = '\n'.join(statements)
        for fragment in ['relforcerowsecurity', 'NOT prosecdef', 'aclexplode', 'writer_attestation_read',
            'writer_attestation_insert', "SQLSTATE '23505'", "SQLSTATE '42501'", "SQLSTATE '23514'",
            "state='recovery_blocked'", "state='unknown'", 'tombstoned=true',
            "authorization_revision='changed'", 'SET backend_epoch=2', 'DELETE FROM cragkit_qdrant.members',
            'DELETE FROM cragkit_qdrant.point_claims', 'DELETE FROM cragkit_qdrant.vector_replays',
            'DELETE FROM cragkit_qdrant.dispatch_points', 'attestation_exact_tuple_with_decoys']:
            assert fragment in combined
        assert 'WHEN OTHERS' not in combined
        assert 'SECURITY DEFINER' not in combined
        # The ordinary positive attestation must run as the nonowner writer.
        positive = 'INSERT INTO cragkit_qdrant.preparation_attestations '
        positive_index = next(index for index, query in enumerate(statements) if query.startswith(positive))
        selected = next(query for query in reversed(statements[:positive_index]) if query.startswith('SET LOCAL ROLE '))
        assert selected == 'SET LOCAL ROLE ' + state.roles['writer']
    asyncio.run(run())


def test_changed_preupgrade_facts_fail_before_any_epoch_advance():
    async def run():
        connection = RecordingConnection()
        state = await schema.seed_pre_upgrade(connection)
        connection.queries.clear()
        connection.snapshot = [('changed-source', 'synthetic-generation-json', 'synthetic-preparation-json')]
        with pytest.raises(RuntimeError, match='attestation_upgrade_changed_legacy_facts'):
            await schema.run_probes(connection, state)
        assert not any('SET epoch=2' in query for query, _ in connection.queries)
    asyncio.run(run())


def test_case_failure_rolls_back_and_releases_its_savepoint_without_owning_outer_transaction():
    async def run():
        connection = RecordingConnection()
        state = await schema.seed_pre_upgrade(connection)
        connection.queries.clear()
        connection.fail = lambda query: query.startswith('UPDATE cragkit_qdrant.publication_intents SET state=\'writing\'')
        with pytest.raises(RuntimeError, match='injected_connection_failure'):
            await schema.run_probes(connection, state)
        statements = [query for query, _ in connection.queries]
        assert statements[-2:] == ['ROLLBACK TO SAVEPOINT qa_case', 'RELEASE SAVEPOINT qa_case']
        assert not any(query == 'ROLLBACK' or query == 'COMMIT' for query in statements)
    asyncio.run(run())


def test_run_requires_preupgrade_state_and_validates_generated_role_names():
    async def run():
        connection = RecordingConnection()
        with pytest.raises(ValueError, match='attestation_probe_preupgrade_state'):
            await schema.run_probes(connection, schema.AttestationProbeState({}, {}, ()))
        state = schema.AttestationProbeState(schema.seed_records(), {'writer': 'x;COMMIT'}, (('fixture',),))
        with pytest.raises(ValueError, match='attestation_probe_role'):
            await schema._role(connection, state, 'writer')
        assert connection.queries == [('RESET ROLE', None)]
    asyncio.run(run())
