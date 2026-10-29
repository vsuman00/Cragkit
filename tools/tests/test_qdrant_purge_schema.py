"""QP-r1 loader/ABI/protocol regressions; doubles do not establish SQL acceptance."""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import qdrant_purge_schema as purge
from runtime_diagnostics import CleanupFailure


def arguments():
    inventory = b'["synthetic-sql-only-inventory"]'
    return ('instance-fixture','fixture-local','storage-fixture','supervisor-fixture',1,
        'physical_fixture','incarnation-fixture','tenant-a','docs','doc-1','purge-1','a'*64,
        '00000000-0000-4000-8000-000000000001','b'*64,'auth-2',2,inventory,
        sha256(inventory).hexdigest(),purge.POLICY,'c'*64)


def test_exact_loader_identity_size_bytes_and_frozen_metadata(tmp_path):
    path = tmp_path/purge.MIGRATION.name
    raw = b'CREATE TABLE cragkit_qdrant.fixture_only(id integer);\n'
    path.write_bytes(raw)
    value = purge.migration(path)
    assert value.version=='0005_security_owners_and_erasure'
    assert value.checksum==sha256(raw).hexdigest()
    assert value.sql.encode()==raw
    with pytest.raises(FrozenInstanceError):value.version='0004_security_settlement_guard'
    with pytest.raises(ValueError,match='identity'):
        purge.migration(tmp_path/'0004_security_settlement_guard.sql')


@pytest.mark.parametrize('raw',[b'',b'x'*1048577,b'\xff',b'-- comment\r\n',b'\xef\xbb\xbfSELECT 1;',
    b'SELECT 1;\x00',b'BEGIN;',b'SELECT 1; COMMIT;',b'END;',b'ABORT;',b'START TRANSACTION;',
    b'ROLLBACK TO SAVEPOINT foo;',b"PREPARE TRANSACTION 'x';",b'\\include private.sql\n',
    b'/* comment */ COMMIT;',b'-- comment\nBEGIN;',b'/* unterminated',b"SELECT 'unterminated",
    b'DO $body$ BEGIN NULL; END;',b'DO $qw_probe$ BEGIN NULL; END $qw_probe$;',
    b'DO $$ BEGIN COMMIT; END $$;',b'DO $body$ BEGIN ROLLBACK; END $body$;'])
def test_loader_refuses_transaction_escape_and_malformed_encoding(tmp_path,raw):
    path=tmp_path/purge.MIGRATION.name;path.write_bytes(raw)
    with pytest.raises((ValueError,UnicodeError)):purge.migration(path)


@pytest.mark.parametrize('source',[
    "DO $migration$ BEGIN PERFORM 1; END $migration$;",
    "DO $$ BEGIN PERFORM 'COMMIT;'; END $$;",
    "CREATE FUNCTION f() RETURNS void LANGUAGE plpgsql AS $f$ BEGIN NULL; END $f$;",
    "SELECT 'BEGIN; COMMIT;'; -- ROLLBACK;\n",
    "/* outer /* BEGIN; */ COMMIT; */ SELECT 1;",
    'CREATE TABLE "BEGIN" ("COMMIT" text);',
    "SELECT E'back\\\\slash and \\'quote';",
])
def test_loader_preserves_procedural_bodies_comments_and_literal_words(tmp_path,source):
    path=tmp_path/purge.MIGRATION.name;path.write_text(source,encoding='utf-8')
    assert purge.migration(path).sql==source


def test_twenty_argument_boundary_matches_qp_r1_exact_order_and_types():
    assert purge.ARGUMENTS==('p_instance_id','p_backend_namespace','p_storage_identity','p_supervisor_id',
        'p_backend_epoch','p_physical_collection','p_collection_incarnation','p_tenant_id','p_collection',
        'p_document_id','p_purge_intent_id','p_purge_payload_sha256','p_owner_token','p_tombstone_payload_sha256',
        'p_authorization_revision','p_mutation_epoch','p_inventory_bytes','p_inventory_sha256','p_policy_id','p_absence_sha256')
    assert purge.TYPES==('text','text','text','text','bigint','text','text','text','text','text',
        'text','text','uuid','text','text','bigint','bytea','text','text','text')
    statement=purge.erase_statement(arguments())
    assert statement.startswith('SELECT cragkit_qdrant.erase_purged_document(')
    assert "decode('"+arguments()[16].hex()+"','hex')::bytea" in statement
    assert purge.SIGNATURE=='cragkit_qdrant.erase_purged_document('+','.join(purge.TYPES)+')'
    assert purge.POLICY=='erase_managed_source_and_replay_v1'


@pytest.mark.parametrize('value',[None,{},'x',[],arguments()[:-1],arguments()+(None,)])
def test_boundary_refuses_wrong_shape(value):
    with pytest.raises(ValueError,match='argument_shape'):purge.erase_statement(value)


def test_literal_escaping_and_nulls_are_bound_to_exact_typed_argument_positions():
    changed=list(arguments());changed[9]="doc'); COMMIT; --\\x"
    result=purge.erase_statement(changed)
    assert "E'doc''); COMMIT; --\\\\x'::text" in result
    changed[9]=None
    assert 'NULL::text' in purge.erase_statement(changed)
    changed[9]=object()
    with pytest.raises(ValueError):purge.erase_statement(changed)


class Cursor:
    def __init__(self,rows):self.rows=rows
    async def fetchall(self):return self.rows


class Connection:
    def __init__(self,fail=None):self.statements=[];self.fail=fail
    async def execute(self,statement,params=None,*,prepare=False):
        assert prepare is False
        self.statements.append((statement,params))
        if self.fail and self.fail(statement):raise RuntimeError('synthetic_failure')
        return Cursor([])


def test_savepoint_case_always_rolls_back_and_releases_even_after_body_failure():
    async def run():
        connection=Connection()
        with pytest.raises(ValueError,match='synthetic'):
            async with purge._case(connection):raise ValueError('synthetic')
        assert [statement for statement,_ in connection.statements]==[
            'SAVEPOINT qa_purge_probe','ROLLBACK TO SAVEPOINT qa_purge_probe','RELEASE SAVEPOINT qa_purge_probe']
    asyncio.run(run())


def test_savepoint_cleanup_error_preserves_primary_and_attempts_both_cleanup_steps():
    async def run():
        connection=Connection(lambda statement:statement.startswith('ROLLBACK TO '))
        primary=ValueError('synthetic_primary')
        with pytest.raises(CleanupFailure) as caught:
            async with purge._case(connection):raise primary
        assert connection.statements[-1][0]=='RELEASE SAVEPOINT qa_purge_probe'
        assert caught.value.to_dict()['primary']['category']=='validation'
    asyncio.run(run())


def test_scope_uses_only_fixed_parameterized_settings():
    async def run():
        connection=Connection();value=arguments()
        await purge._bind(connection,value)
        assert all(statement=='SELECT set_config(%s,%s,true)' for statement,_ in connection.statements)
        settings=dict(params for _,params in connection.statements)
        assert settings['cragkit_qdrant.backend_instance_id']==value[0]
        assert settings['cragkit_qdrant.writer_document_id']==value[9]
        assert settings['cragkit_qdrant.writer_intent_id']==value[10]
        assert settings['cragkit_qdrant.writer_owner_token']==value[12]
        assert settings['cragkit_qdrant.authorization_revision']==value[14]
    asyncio.run(run())


def test_effective_profile_queries_exclude_every_managed_body_and_check_force_rls():
    queries=' '.join(purge._profile_queries())
    for table,columns in purge.BODY_COLUMNS.items():
        for column in columns:
            assert "'cragkit_qdrant."+table+"','"+column+"','SELECT')" in queries
    for clause in ('relrowsecurity AND c.relforcerowsecurity','p.pronargs=20',
        "p.prorettype='boolean'::regtype",'p.prosecdef','NOT p.proisstrict','NOT p.proleakproof',
        "'search_path=pg_catalog','row_security=on'",'pg_catalog.aclexplode','a.is_grantable'):
        assert clause in queries


def test_admin_fault_cleanup_runs_after_writer_failure():
    class Admin(Connection):
        @asynccontextmanager
        async def transaction(self):yield
    class Database:
        def __init__(self):self.admin=Admin()
        @asynccontextmanager
        async def connection(self,kind):
            assert kind=='writer'
            raise RuntimeError('synthetic_connect_failure')
            yield
    async def run():
        database=Database()
        with pytest.raises(RuntimeError,match='synthetic_connect_failure'):
            await purge._rollback_fault(database,arguments(),purge.erase_statement(arguments()),())
        statements=[statement for statement,_ in database.admin.statements]
        assert statements[-2:]==[
            'DROP TRIGGER qa_purge_intermediate_failure ON cragkit_qdrant.dispatch_journal',
            'DROP FUNCTION cragkit_qdrant.qa_purge_intermediate_failure()']
        database=Database()
        with pytest.raises(RuntimeError,match='synthetic_connect_failure'):
            await purge._permission_fault(database,arguments(),purge.erase_statement(arguments()))
        assert database.admin.statements[-1][0].startswith('REVOKE SELECT(canonical_utf8)')
    asyncio.run(run())


def test_historical_confirmation_failure_does_not_start_fresh_replay_lease(monkeypatch):
    class Database:
        def __init__(self):self.opens=0;self.connection_handle=Connection()
        @asynccontextmanager
        async def connection(self,kind):
            self.opens+=1
            yield self.connection_handle
    @asynccontextmanager
    async def transaction():yield
    async def snapshot(connection,args,*,immutable=False):return ()
    async def rows(connection,statement,params=None):
        if statement.startswith('SELECT cragkit_qdrant.erase_purged_document('):return [(False,)]
        return []
    async def run():
        database=Database();database.connection_handle.transaction=transaction
        monkeypatch.setattr(purge,'_snapshot',snapshot)
        monkeypatch.setattr(purge,'_rows',rows)
        with pytest.raises(RuntimeError,match='purge_committed_result'):
            await purge.run_historical_confirmation(database,dict(arguments=arguments(),records={}))
        assert database.opens==1
    asyncio.run(run())
