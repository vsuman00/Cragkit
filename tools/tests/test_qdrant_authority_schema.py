"""Pure probe construction and failure cleanup; no database is contacted."""
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qdrant_authority_schema as schema
import check_qdrant_authority_schema as checker
from runtime_diagnostics import CleanupFailure


def test_migration_binds_actual_bytes_and_rejects_transaction_commands(tmp_path):
    path = tmp_path / '0001_authority.sql'
    path.write_bytes(b'CREATE SCHEMA cragkit_qdrant;\n')
    item = schema.migration(path)
    assert item.version == '0001_authority'
    assert item.checksum == sha256(path.read_bytes()).hexdigest()
    assert item.sql == path.read_text()
    for raw in (b'COMMIT;\n', b'ROLLBACK;\n', b'BEGIN;\n', b'\\include file\n', b'-- $qdauth_probe$\n', b'-- crlf\r\n'):
        path.write_bytes(raw)
        with pytest.raises(ValueError): schema.migration(path)
    path = tmp_path / 'other.sql'
    path.write_text('SELECT 1;')
    with pytest.raises(ValueError): schema.migration(path)


@pytest.mark.parametrize('value,expected', [(None,'NULL'), (True,'true'), (False,'false'), (7,'7'),
    (b'A\0B',"decode('410042','hex')"), ("a'; SELECT 'b", "E'a''; SELECT ''b'")])
def test_synthetic_sql_literals_preserve_values_without_injection(value, expected):
    assert schema.literal(value) == expected


@pytest.mark.parametrize('value', [1.5, {}, [], 'a\0b'])
def test_unsupported_fixture_literals_fail(value):
    with pytest.raises(ValueError): schema.literal(value)


def test_fixture_expansion_preserves_byte_digests_and_exact_span():
    row = schema.fixture_row()
    assert row['canonical_utf8'][row['start_byte']:row['end_byte']] == row['excerpt_utf8']
    assert sha256(row['canonical_utf8']).hexdigest() == row['source_sha256']
    assert sha256(row['excerpt_utf8']).hexdigest() == row['text_sha256']
    assert len(row['canonical_utf8']) == row['source_bytes'] == 13
    assert len(row['excerpt_utf8']) == row['excerpt_bytes'] == 9
    statements = schema.seed_statements(row)
    assert len(statements) == 6 and all(statement.endswith(';') for statement in statements)
    assert 'cragkit_qdrant.members' in statements[3] and 'point_id' in statements[3]
    assert statements[2].find('published') == -1  # Staging precedes member writes.
    assert 'published=true,ever_published=true' in statements[4]
    assert 'active_generation_id' in statements[5]
    assert schema.seed_sql(row) == '\n'.join(statements)


def test_probe_labels_cannot_inject_sql():
    assert 'IS DISTINCT FROM true' in schema.assert_sql('NULL', 'scope_denied')
    for label in ('bad-label', "x';COMMIT;--", 'x'*81):
        with pytest.raises(ValueError): schema.assert_sql('true', label)


def test_source_sql_is_isolated_and_adds_no_runtime_writer_or_definer():
    sql = schema.migration().sql
    assert 'CREATE SCHEMA cragkit_qdrant;' in sql and 'IF NOT EXISTS' not in sql.replace('-- No IF NOT EXISTS:', '--')
    assert 'CREATE EXTENSION' not in sql and 'SECURITY DEFINER' not in sql
    assert 'CREATE ROLE' not in sql and 'FOR ALL' not in sql
    assert 'cragkit.migration_history' not in sql and 'cragkit_vector.' not in sql
    assert sql.count('FORCE ROW LEVEL SECURITY') == 4
    assert sql.count('FOR SELECT TO PUBLIC') == 4
    assert 'octet_length(excerpt_utf8) BETWEEN 1 AND 32768' in sql
    assert 'octet_length(encoded) > 131072' in sql
    assert 'convert_from' not in sql
    assert 'numeric_value_out_of_range OR program_limit_exceeded' in sql
    assert 'WHEN OTHERS' not in sql


@pytest.mark.parametrize('close_fails', [False, True])
def test_primary_failure_rolls_back_and_closes_without_losing_cleanup_error(tmp_path, monkeypatch, close_fails):
    events = []
    class Cursor:
        description = None
        def nextset(self): return False
    class Transaction:
        async def __aenter__(self): events.append('transaction')
        async def __aexit__(self, kind, value, trace): events.append(('rollback', kind))
    class Connection:
        pgconn = SimpleNamespace(ssl_in_use=True)
        async def execute(self, query, params=None, **kwargs):
            if type(query) is str and 'CREATE SCHEMA cragkit_qdrant;' in query:
                raise ValueError('PRIVATE SOURCE AND CREDENTIAL CANARY')
            return Cursor()
        def transaction(self, *, force_rollback):
            assert force_rollback is True
            return Transaction()
        async def close(self):
            events.append('close')
            if close_fails: raise ConnectionError('PRIVATE CLOSE CANARY')
    async def connect(**kwargs): return Connection()
    fake = SimpleNamespace(AsyncConnection=SimpleNamespace(connect=connect), sql=SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'psycopg', fake)
    import cragkit._postgres_pool as pool
    monkeypatch.setattr(pool.PoolResource, '_check_owned_configuration', lambda self: None)
    monkeypatch.setattr(checker, 'load_config', lambda path: dict(host='ep-fixture-cold.c-1.ap-southeast-1.aws.neon.tech',
        dbname='fixture', user='fixture', passfile=tmp_path/'pass', sslrootcert=tmp_path/'ca'))
    with pytest.raises(CleanupFailure if close_fails else ValueError) as error:
        asyncio.run(checker.check(tmp_path/'unused', tmp_path/'artifacts'))
    assert events[0] == 'transaction' and events[1] == ('rollback', ValueError) and events[2] == 'close'
    assert not (tmp_path/'artifacts/schema-results.json').exists()
    if close_fails:
        record = error.value.to_dict()
        assert record['primary']['category'] == 'validation' and record['cleanup'][0]['category'] == 'connection'
        assert 'PRIVATE' not in json.dumps(record)


def test_force_rls_resolves_deferred_fk_events_before_table_alteration():
    commands = schema.force_rls_sql().splitlines()
    assert commands[0] == 'SET CONSTRAINTS ALL IMMEDIATE;'
    assert len(commands) == 5
    assert commands[1:] == [f'ALTER TABLE cragkit_qdrant.{table} FORCE ROW LEVEL SECURITY;'
                            for table in checker.TABLES]


@pytest.mark.parametrize('primary_error', [None, ValueError('PRIVATE PRIMARY CANARY')])
def test_rollback_failure_keeps_original_primary_separate(primary_error):
    failures = []
    class Transaction:
        async def __aenter__(self): pass
        async def __aexit__(self, *args): raise ConnectionError('PRIVATE ROLLBACK CANARY')
    class Connection:
        def transaction(self, *, force_rollback): return Transaction()
    async def run():
        async with checker.rollback_only(Connection(), failures):
            if primary_error is not None: raise primary_error
    with pytest.raises(ValueError if primary_error is not None else checker._RollbackIncomplete):
        asyncio.run(run())
    assert len(failures) == 1 and failures[0][0] == 'fixture_transaction'
    report = CleanupFailure(failures, primary=primary_error).to_dict()
    assert report['primary'] is None if primary_error is None else report['primary']['category'] == 'validation'
    assert report['cleanup'][0]['category'] == 'connection' and 'PRIVATE' not in json.dumps(report)


def test_hung_rollback_is_bounded_and_connection_owner_can_close():
    failures = []
    class Transaction:
        async def __aenter__(self): pass
        async def __aexit__(self, *args): await asyncio.Event().wait()
    class Connection:
        def transaction(self, *, force_rollback): return Transaction()
    async def run():
        async with checker.rollback_only(Connection(), failures, cleanup_timeout=0.01): pass
    with pytest.raises(checker._RollbackIncomplete): asyncio.run(run())
    assert len(failures) == 1 and isinstance(failures[0][1], TimeoutError)
