"""Pure publication-probe construction checks; no database or process starts."""
from hashlib import sha256
import asyncio
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qdrant_publication_schema as schema


def test_migration_reads_exact_additive_bytes(tmp_path):
    path = tmp_path / '0002_publication.sql'
    path.write_bytes(b'CREATE TABLE cragkit_qdrant.probe(id integer);\n')
    item = schema.migration(path)
    assert item.version == '0002_publication'
    assert item.checksum == sha256(path.read_bytes()).hexdigest()
    assert item.sql == path.read_text()
    assert schema.CAPABILITY_ROLES == ('cragkit_qdrant_writer', 'cragkit_qdrant_supervisor')


@pytest.mark.parametrize('raw', [b'BEGIN;\n', b'COMMIT;\n', b'ROLLBACK;\n',
    b'\\include other.sql\n', b'-- windows\r\n', b'-- $qw_probe$\n', b'\xff'])
def test_migration_cannot_escape_caller_transaction(tmp_path, raw):
    path = tmp_path / '0002_publication.sql'
    path.write_bytes(raw)
    with pytest.raises((ValueError, UnicodeError)):
        schema.migration(path)


def test_migration_rejects_wrong_identity(tmp_path):
    path = tmp_path / '0001_authority.sql'
    path.write_text('SELECT 1;')
    with pytest.raises(ValueError, match='publication_migration_identity'):
        schema.migration(path)


def test_assertions_treat_null_as_failure_and_validate_fixed_labels():
    statement = schema.assert_sql('NULL', 'publication_scope_denied')
    assert 'IS DISTINCT FROM true' in statement
    assert "RAISE EXCEPTION 'publication_scope_denied'" in statement
    for label in ['bad-label', "x';COMMIT;--", 'x' * 81, None]:
        with pytest.raises(ValueError):
            schema.assert_sql('true', label)
    with pytest.raises(ValueError):
        schema.assert_sql('$qw_probe$', 'valid_label')


def test_negative_probe_catches_only_expected_state():
    statement = schema.rejected_sql('UPDATE synthetic SET value=1;', '23514')
    assert "WHEN SQLSTATE '23514' THEN observed := true" in statement
    assert 'WHEN OTHERS' not in statement
    assert 'publication_invalid_write_accepted' in statement
    for state in ['2351', '235140', "x';--", 'xxxxx', None]:
        with pytest.raises(ValueError):
            schema.rejected_sql('SELECT 1;', state)
    with pytest.raises(ValueError):
        schema.rejected_sql('$qw_probe$', '23514')
    user_exception = schema.rejected_sql('SELECT 1;', 'P0001')
    assert user_exception.index('END; IF NOT observed') < user_exception.index("RAISE EXCEPTION 'publication_invalid_write_accepted'")


def test_publication_fixture_exact_sources_and_original_replay_goldens():
    fixture = schema.publication_fixture()
    for row in fixture['replay_goldens']:
        if row['kind'] == 'dense':
            spec = row['original_encoding']
            values = [0.0] * spec['dimensions']
            for index, value in spec['nonzero']:
                values[index] = value
            if 'negative_zero_index' in spec:
                values[spec['negative_zero_index']] = -0.0
            blob = schema.replay_blob('dense', values)
        else:
            blob = schema.replay_blob('sparse', row['values'], row['indices'])
        assert len(blob) == row['blob_bytes']
        assert sha256(blob).hexdigest() == row['blob_sha256']


def test_synthetic_insert_quotes_values_and_rejects_identifier_injection():
    statement = schema.insert_sql('probe', {'value': "a';COMMIT;--", 'bytes': b'A\0B',
        'profile': {'model': 'fixture'}, 'principals': ['reader-a']})
    assert "E'a'';COMMIT;--'" in statement
    assert "decode('410042','hex')" in statement
    assert '::jsonb' in statement and '::text[]' in statement
    for table, record in [('x;COMMIT', {'value': 1}), ('valid', {'x)': 1}), ('valid', {})]:
        with pytest.raises(ValueError):
            schema.insert_sql(table, record)


def test_seed_records_bind_full_two_member_manifest_claims_and_replay_bytes():
    fixture = schema.publication_fixture()
    records = schema.seed_records(fixture)
    assert records['intent']['expected_active_generation_id'] is None
    assert sha256(records['intent']['payload_bytes']).hexdigest() == records['intent']['payload_sha256']
    assert sha256(records['intent']['manifest_bytes']).hexdigest() == fixture['intent']['manifest_sha256']
    assert records['generation']['expected_member_count'] == 2
    assert len(records['members']) == len(records['claims']) == len(records['replays']) == 2
    for member, claim, replay in zip(records['members'], records['claims'], records['replays']):
        assert member['point_id'] == claim['point_id'] == replay['point_id']
        assert member['chunk_id'] == claim['chunk_id'] == replay['chunk_id']
        assert sha256(replay['dense_blob']).hexdigest() == replay['dense_blob_sha256']
        assert sha256(replay['sparse_blob']).hexdigest() == replay['sparse_blob_sha256']
        assert len(replay['dense_blob']) == 12326
        assert claim['backend_namespace'] == records['backend']['backend_namespace']
        assert sha256(member['excerpt_utf8']).hexdigest() == claim['text_sha256']


def test_every_seed_record_constructs_quoted_insert_with_digest_columns():
    records = schema.seed_records()
    for table, key in [('backend_instances', 'backend'), ('publication_intents', 'intent'),
        ('documents', 'document'), ('document_revisions', 'revision'), ('generations', 'generation')]:
        statement = schema.insert_sql(table, records[key])
        assert statement.startswith(f'INSERT INTO cragkit_qdrant.{table} (')
        assert statement.endswith(';')
    for table, key in [('members', 'members'), ('point_claims', 'claims'), ('vector_replays', 'replays')]:
        for record in records[key]:
            assert schema.insert_sql(table, record).startswith(f'INSERT INTO cragkit_qdrant.{table} (')
    assert 'payload_sha256' in schema.insert_sql('publication_intents', records['intent'])
    assert 'dense_blob_sha256' in schema.insert_sql('vector_replays', records['replays'][0])
    for identifier in ['1column', 'x;COMMIT', 'x' * 64, 'x.y', 'x-y']:
        with pytest.raises(ValueError):
            schema.insert_sql('safe', {identifier: 1})


def test_probe_borrows_transaction_and_connection_without_owning_cleanup():
    pytest.importorskip('psycopg')
    failure = RuntimeError('synthetic probe failure')
    queries = []

    class Connection:
        async def execute(self, query, params=None, **options):
            queries.append((query, params, options))
            raise failure

        def transaction(self, **options):
            raise AssertionError('the parent owns the rollback transaction')

        async def close(self):
            raise AssertionError('the parent owns the borrowed connection')

    with pytest.raises(RuntimeError) as caught:
        asyncio.run(schema.run_probes(Connection()))
    assert caught.value is failure
    assert len(queries) == 1
    assert queries[0][2] == {'prepare': False}


def test_successful_case_uses_subtransaction_rollback_without_outer_commit():
    statement = schema.rolled_back_case_sql(['SELECT 1;'])
    assert "RAISE SQLSTATE 'QW001'" in statement
    assert "WHEN SQLSTATE 'QW001' THEN NULL" in statement
    assert 'COMMIT' not in statement and 'ROLLBACK' not in statement
    inner = schema.rejected_block('SELECT 1;', 'P0001')
    assert schema.DELIMITER not in inner
    assert 'IF NOT observed' in inner
    assert schema.rolled_back_case_sql([inner])
    with pytest.raises(ValueError):
        schema.rolled_back_case_sql([schema.DELIMITER])


def test_publication_artifact_is_additive_and_declares_managed_mutation_isolation():
    sql = schema.migration().sql
    assert 'CREATE SCHEMA' not in sql
    assert 'CREATE ROLE' not in sql
    assert 'SECURITY DEFINER' not in sql
    assert 'cragkit_vector.' not in sql
    assert 'DROP TABLE' not in sql and 'DROP SCHEMA' not in sql
    for table in ('backend_instances', 'publication_intents', 'document_owners', 'point_claims',
        'vector_replays', 'dispatch_journal', 'dispatch_points', 'preparations'):
        assert f'CREATE TABLE cragkit_qdrant.{table}' in sql
    assert "current_setting('transaction_isolation')" in sql
    assert "'read committed'" in sql
    assert 'DEFERRABLE INITIALLY DEFERRED' in sql
    assert 'FORCE ROW LEVEL SECURITY' in sql
