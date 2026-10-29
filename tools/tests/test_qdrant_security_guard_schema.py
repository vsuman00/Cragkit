"""Security-guard contract/probe tests; recorded SQL is not PostgreSQL evidence."""
import asyncio
from dataclasses import FrozenInstanceError
from hashlib import sha256
from pathlib import Path
import re
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qdrant_security_guard_schema as guard

ROOT = Path(__file__).resolve().parents[2]
ROLE = 'cragkit_qdrant_security_guard'
ARGUMENTS = (
    ('p_instance_id','text'),('p_backend_namespace','text'),('p_storage_identity','text'),
    ('p_supervisor_id','text'),('p_recovery_id','text'),('p_backend_epoch','bigint'),
    ('p_tenant_id','text'),('p_collection','text'),('p_document_id','text'),
    ('p_owner_intent_id','text'),('p_owner_token','uuid'),('p_security_intent_id','text'),
    ('p_security_payload_sha256','text'),('p_active_generation_id','text'),
    ('p_authorization_revision','text'),('p_mutation_epoch','bigint'),('p_principal_ids','text[]'),
    ('p_grant_ids','text[]'),('p_language','text'),('p_kind','text'),('p_tag','text'),('p_tombstoned','boolean'),
)
SELECT_COLUMNS = {
    'backend_instances': {'instance_id','backend_namespace','storage_identity','supervisor_id','epoch','state','recovery_id'},
    'document_owners': {'tenant_id','collection','document_id','instance_id','intent_id','owner_token','backend_epoch'},
    'documents': {'tenant_id','collection','document_id','active_generation_id','authorization_revision','mutation_epoch',
                  'principal_ids','grant_ids','language','kind','tag','tombstoned'},
    'publication_intents': {'tenant_id','collection','document_id','intent_id','instance_id','action','payload_sha256',
                            'expected_mutation_epoch','authority_committed'},
}


def sql_source():
    return guard.migration().sql


def compact(value):
    return re.sub(r'\s+', ' ', re.sub(r'--[^\n]*', '', value)).strip()


def function_parts():
    source = sql_source()
    signature = re.search(r'CREATE\s+FUNCTION\s+cragkit_qdrant\.lock_current_security\s*\((.*?)\)\s*RETURNS\s+void\b', source, re.I|re.S)
    assert signature is not None
    start = signature.end()
    body_start = re.search(r'\bAS\s+(\$[A-Za-z_0-9]*\$)', source[start:], re.I)
    assert body_start is not None
    delimiter = body_start[1]
    offset = start + body_start.end()
    end = source.index(delimiter, offset)
    return signature[1], compact(source[start:start+body_start.start()]), source[offset:end]


def test_guard_migration_parser_binds_exact_additive_version_and_bytes(tmp_path):
    path = tmp_path/'0004_security_settlement_guard.sql'
    raw = b'CREATE TABLE cragkit_qdrant.fixture_only(id integer);\n'
    path.write_bytes(raw)
    item = guard.migration(path)
    assert item.version == '0004_security_settlement_guard'
    assert item.checksum == sha256(raw).hexdigest()
    assert item.sql.encode('utf-8') == raw
    with pytest.raises(FrozenInstanceError): item.version = 'other'
    with pytest.raises(ValueError): guard.migration(tmp_path/'0003_preparation_attestations.sql')


@pytest.mark.parametrize('raw', [b'', b'BEGIN;\n', b'COMMIT;\n', b'ROLLBACK;\n', b'\\include private.sql\n',
                                  b'-- windows\r\n', b'\xff', b'x'*1048577])
def test_guard_loader_rejects_transaction_escape_invalid_encoding_and_oversize(tmp_path, raw):
    path = tmp_path/'0004_security_settlement_guard.sql';path.write_bytes(raw)
    with pytest.raises((ValueError,UnicodeError)): guard.migration(path)


def test_exact_guard_signature_and_safe_function_attributes_are_frozen():
    signature, attributes, body = function_parts()
    actual = tuple(tuple(compact(part).lower().split()) for part in signature.split(','))
    assert actual == ARGUMENTS
    attributes = re.sub(r'\s*=\s*','=',attributes.upper())
    for required in ('LANGUAGE PLPGSQL','SECURITY DEFINER','VOLATILE','PARALLEL UNSAFE','CALLED ON NULL INPUT',
                     'SEARCH_PATH=PG_CATALOG','ROW_SECURITY=ON'):
        assert required in attributes
    assert not re.search(r'(?<!NOT )\bLEAKPROOF\b', attributes)
    assert not re.search(r'\bSTRICT\b', attributes)
    assert not re.search(r'(?:^|;)\s*EXECUTE\b|EXCEPTION\s+WHEN|\b(?:COMMIT|ROLLBACK)\b', body, re.I)
    assert not re.search(r'\b(?:INSERT|DELETE|UPDATE)\s+(?:INTO\s+)?cragkit_qdrant\.', body, re.I)
    assert 'request_bytes' not in body and 'canonical_utf8' not in body and 'dense_blob' not in body


def test_guard_role_column_privileges_exclude_source_journal_and_mutation_authority():
    source = compact(sql_source())
    role = re.search(r'CREATE ROLE '+ROLE+r'\s+([^;]+);', source, re.I)
    assert role is not None
    for attribute in ('NOLOGIN','NOSUPERUSER','NOBYPASSRLS','NOCREATEDB','NOCREATEROLE','NOREPLICATION','NOINHERIT'):
        assert attribute in role[1].upper()
    table_grants = re.findall(r'GRANT\s+([^;]+?)\s+ON\s+cragkit_qdrant\.(\w+)\s+TO\s+'+ROLE+r'\s*;', source, re.I)
    selected,updated = {},set()
    for privileges,table in table_grants:
        columns = re.search(r'\bSELECT\s*\(([^)]+)\)',privileges,re.I)
        assert columns is not None
        selected[table] = {column.strip() for column in columns[1].split(',')}
        update = re.search(r'\bUPDATE\s*\(([^)]+)\)',privileges,re.I)
        if update: updated.add((table,update[1].strip()))
    assert selected == SELECT_COLUMNS
    assert updated == {
        ('backend_instances','epoch'),('document_owners','backend_epoch'),('documents','mutation_epoch')}
    assert not re.search(r'GRANT\s+(?:SELECT|UPDATE|INSERT|DELETE|TRUNCATE|REFERENCES|TRIGGER)\s+ON\b[^;]+TO\s+'+ROLE, source, re.I)
    assert not re.search(r'ALTER\s+(?:TABLE|SCHEMA|DATABASE|TYPE)\b[^;]*OWNER\s+TO\s+'+ROLE, source, re.I)


def test_seven_guard_only_rls_policies_do_not_enable_updates_or_recursive_document_reads():
    source = compact(sql_source())
    policies = re.findall(r'CREATE POLICY\s+(\w+)\s+ON\s+cragkit_qdrant\.(\w+)\s+(.*?);', source, re.I)
    assert len(policies) == 7
    kinds = set()
    for name,table,definition in policies:
        assert re.search(r'\bTO\s+'+ROLE+r'\b', definition, re.I)
        operation = re.search(r'\bFOR\s+(SELECT|UPDATE)\b', definition, re.I)
        assert operation is not None
        kinds.add((table,operation[1].upper()))
        if operation[1].upper() == 'UPDATE': assert re.search(r'WITH CHECK\s*\(\s*false\s*\)', definition, re.I)
        assert 'cragkit_qdrant.backend_instance_id' in definition
        if table == 'documents':
            assert 'cragkit_qdrant.document_owners' in definition
            for key in ('tenant_id','collection','document_id'): assert key in definition
        else: assert 'FROM cragkit_qdrant.documents' not in definition
    assert kinds == {(table,operation) for table in ('backend_instances','document_owners','documents') for operation in ('SELECT','UPDATE')} | {('publication_intents','SELECT')}


def test_helper_argument_names_and_signature_match_the_frozen_call_boundary():
    assert tuple(guard.ARGUMENTS) == tuple(name for name,_ in ARGUMENTS)
    signature = guard.SIGNATURE
    assert type(signature) is str
    parameters = signature[signature.index('(')+1:signature.rindex(')')] if '(' in signature else signature
    assert tuple(part.strip().lower() for part in parameters.split(',')) == tuple(kind for _,kind in ARGUMENTS)
    assert type(guard.CHECKS) is tuple and len(set(guard.CHECKS)) == len(guard.CHECKS)
    assert 6 <= len(guard.CHECKS) <= 32
    assert all(type(label) is str and re.fullmatch('[a-z][a-z0-9_]{0,127}', label) for label in guard.CHECKS)


def test_guard_body_authenticates_session_principal_and_rechecks_after_lock_waits():
    _,_,raw = function_parts();body = compact(raw)
    assert 'session_user' in body
    assert re.search(r"current_setting\(\s*'role'\s*,\s*true\s*\)\s*(?:<>|IS DISTINCT FROM|!=)\s*'none'", body, re.I)
    for required in ('pg_catalog.pg_roles','pg_catalog.pg_auth_members','pg_catalog.pg_namespace',
                     'pg_catalog.pg_database','pg_catalog.pg_has_role'):
        assert required in body
    assert "cragkit_qdrant.backend_instance_id" in body
    assert "'42501'" in body and "'22023'" in body and "'23514'" in body
    assert 'array_lower' in body and ('array_ndims' in body or 'array_dims' in body)
    assert 'convert_to' in body and 'UTF8' in body
    backend = re.search(r'FROM cragkit_qdrant\.backend_instances\b[^;]*FOR SHARE',body,re.I)
    owner = re.search(r'FROM cragkit_qdrant\.document_owners\b[^;]*FOR UPDATE',body,re.I)
    document = re.search(r'FROM cragkit_qdrant\.documents\b[^;]*FOR UPDATE',body,re.I)
    assert backend and owner and document and backend.start() < owner.start() < document.start()
    after_document = body[document.end():]
    assert 'FROM cragkit_qdrant.backend_instances' in after_document
    assert 'FROM cragkit_qdrant.document_owners' in after_document
    assert 'FROM cragkit_qdrant.documents' in after_document
    assert 'IS DISTINCT FROM' in after_document
    assert 'payload_sha256' in after_document and 'expected_mutation_epoch' in after_document
    assert 'authority_committed' in after_document


def test_guard_install_transfers_only_function_ownership_and_revokes_transient_create():
    source = compact(sql_source())
    assert len(re.findall(r'CREATE FUNCTION\b',source,re.I)) == 1
    assert not re.search(r'CREATE (?:TABLE|TYPE|SCHEMA)\b',source,re.I)
    assert not re.search(r'(?:^|;)\s*(?:DROP|TRUNCATE)\b',source,re.I)
    assert 'createrole_self_grant' in source
    assert 'INHERIT FALSE' in source and 'SET TRUE' in source
    ownership = re.search(r'ALTER FUNCTION cragkit_qdrant\.lock_current_security\b[^;]+OWNER TO '+ROLE,source,re.I)
    assert ownership is not None
    create_grant = re.search(r'GRANT\b[^;]*\bCREATE\b[^;]*ON SCHEMA cragkit_qdrant TO '+ROLE,source,re.I)
    create_revoke = re.search(r'REVOKE CREATE ON SCHEMA cragkit_qdrant FROM '+ROLE,source,re.I)
    assert create_grant and create_revoke and create_grant.start() < ownership.start() < create_revoke.start()
    assert re.search(r'REVOKE\s+(?:ALL|EXECUTE)\b[^;]*ON FUNCTION cragkit_qdrant\.lock_current_security\b[^;]*FROM PUBLIC',source,re.I)
    assert re.search(r'GRANT EXECUTE ON FUNCTION cragkit_qdrant\.lock_current_security\b[^;]*TO cragkit_qdrant_supervisor\s*;',source,re.I)
    assert not re.search(r'WITH GRANT OPTION',source,re.I)


class Cursor:
    def __init__(self, rows): self.rows = rows
    async def fetchall(self): return self.rows


def example_arguments():
    return ('instance-1','fixture-local','storage-1','supervisor-1','recovery-1',2,'tenant-a','docs','doc-1',
            'old-stage','00000000-0000-4000-8000-000000000001','security-2','a'*64,None,'auth-2',2,
            [],[],None,None,None,False)


def test_guard_install_requires_exact_prior_history_and_refuses_adopting_existing_role():
    source = compact(sql_source())
    for version in ('0001_authority','0002_publication','0003_preparation_attestations'):
        checksum = sha256((ROOT/'storage/qdrant/postgres/migrations'/f'{version}.sql').read_bytes()).hexdigest()
        assert f"version='{version}'" in source
        assert f"checksum_sha256='{checksum}'" in source
    assert re.search(r'count\(\*\) FROM cragkit_qdrant\.schema_migrations\)\s*<>\s*3',source)
    existing_role = re.search(r"EXISTS\(SELECT 1 FROM pg_catalog\.pg_roles WHERE rolname='"+ROLE+r"'\)",source)
    created_role = source.index('CREATE ROLE '+ROLE)
    assert existing_role and existing_role.start() < created_role
    assert 'current_user=session_user' in source[:created_role]
    assert 'nspowner' in source[:created_role] and 'relowner' in source[:created_role]


def test_guard_invoker_helper_execution_is_the_exact_public_policy_dependency_set():
    source = compact(sql_source())
    grants = re.findall(r'GRANT EXECUTE ON FUNCTION\s+([^;]+?)\s+TO\s+'+ROLE+r'\s*;',source,re.I)
    names = set()
    for grant in grants:
        names.update(re.findall(r'cragkit_qdrant\.(\w+)\s*\(',grant))
    assert names == {'valid_identity_array','scope_grants','scope_visible'}
    # Function-level grants only; no blanket schema helper execution.
    assert not re.search(r'GRANT EXECUTE ON ALL FUNCTIONS[^;]+TO\s+'+ROLE,source,re.I)
    assert 'SECURITY DEFINER' in source


class RecordingConnection:
    """Records scoped SQL and supplied rows; does not enforce ACLs or RLS."""
    def __init__(self, kind, database, fail=None):
        self.kind = kind;self.database = database;self.fail = fail
        self.role = kind
        self.save_roles = []
    async def execute(self, statement, params=None, *, prepare=False):
        assert prepare is False and type(statement) is str
        self.database.queries.append((self.kind,self.role,statement,params))
        if self.fail is not None and self.fail(statement):raise RuntimeError('PRIVATE INJECTED SQL')
        if statement.startswith('SAVEPOINT '):self.save_roles.append(self.role)
        if statement.startswith('ROLLBACK TO SAVEPOINT '):self.role = self.save_roles[-1]
        if statement.startswith('RELEASE SAVEPOINT '):self.save_roles.pop()
        if statement.startswith('SET LOCAL ROLE '):self.role = statement.removeprefix('SET LOCAL ROLE ')
        if statement.startswith('GRANT SELECT(canonical_utf8)'):self.database.drift = True
        if statement.startswith('REVOKE SELECT(canonical_utf8)'):self.database.drift = False
        if self.kind == 'supervisor' and self.database.drift and "SQLSTATE '22023'" in statement:
            self.database.events.append(('committed_fault_visible','supervisor'))
        if statement in guard._profile_queries():
            return Cursor([(not (self.database.drift and statement == guard._profile_queries()[2]),)])
        if statement.startswith('SELECT cragkit_qdrant.lock_current_security('):return Cursor([(None,)])
        if statement.startswith('SELECT mutation_epoch FROM cragkit_qdrant.documents '):return Cursor([(2,)])
        return Cursor([])
    def transaction(self, *, force_rollback=False):
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def transaction():
            original_role,original_drift = self.role,self.database.drift
            self.database.events.append(('transaction_enter',self.kind))
            try:yield
            finally:
                self.role = original_role
                if force_rollback:self.database.drift = original_drift
                self.database.events.append(('transaction_rollback' if force_rollback else 'transaction_commit',self.kind))
        return transaction()


class RecordingDatabase:
    def __init__(self, fail=None):
        self.queries = [];self.events = [];self.drift = False;self.fail = fail
        self.admin = RecordingConnection('admin',self,fail)
    def connection(self, kind):
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def connection():
            assert kind in ('supervisor','writer','reader')
            self.events.append(('connection_open',kind))
            try:yield RecordingConnection(kind,self,self.fail)
            finally:self.events.append(('connection_close',kind))
        return connection()


def test_sql_probe_protocol_is_bounded_scoped_and_restores_controlled_privilege_fault():
    async def run():
        database = RecordingDatabase()
        checks = await guard.run_sql_probes(database,example_arguments())
        assert checks == list(guard.CHECKS)
        statements = [statement for _,_,statement,_ in database.queries]
        assert not any(re.match(r'^\s*(?:COMMIT|ROLLBACK)\s*;?\s*$',statement) for statement in statements)
        assert not any(re.match(r'^\s*(?:CREATE|ALTER|DROP|TRUNCATE)\b',statement) for statement in statements)
        assert len('\n'.join(statements).encode()) < 524288
        assert statements.count('SAVEPOINT qa_security_guard_probe') == statements.count('ROLLBACK TO SAVEPOINT qa_security_guard_probe') == statements.count('RELEASE SAVEPOINT qa_security_guard_probe')
        assert database.events.count(('connection_open','supervisor')) == database.events.count(('connection_close','supervisor'))
        assert database.events.count(('transaction_enter','admin')) == database.events.count(('transaction_rollback','admin')) + database.events.count(('transaction_commit','admin'))
        assert database.drift is False
        assert database.events.count(('committed_fault_visible','supervisor')) == 1
        positive = [(kind,role) for kind,role,statement,_ in database.queries if statement.startswith('SELECT cragkit_qdrant.lock_current_security(')]
        assert positive == [('supervisor','supervisor')]
        rejected = [(kind,role,statement) for kind,role,statement,_ in database.queries if 'DECLARE observed boolean' in statement]
        assert any(kind == 'writer' and "SQLSTATE '42501'" in statement for kind,_,statement in rejected)
        assert any(kind == 'reader' and "SQLSTATE '42501'" in statement for kind,_,statement in rejected)
        assert any(kind == 'admin' and role == 'cragkit_qdrant_supervisor' and "SQLSTATE '42501'" in statement for kind,role,statement in rejected)
        assert any("SQLSTATE '22023'" in statement for _,_,statement in rejected)
        assert any("SQLSTATE '23514'" in statement for _,_,statement in rejected)
        assert any('[0:0]' in statement and "SQLSTATE '22023'" in statement for _,_,statement in rejected)
        assert any('ARRAY[[' in statement and "SQLSTATE '22023'" in statement for _,_,statement in rejected)
        for kind,_,statement,_ in database.queries:
            if kind != 'supervisor':continue
            if re.search(r'SELECT (?:authorization_revision|canonical_utf8|request_bytes|dense_blob) FROM cragkit_qdrant\.',statement):
                assert "SQLSTATE '42501'" in statement
    asyncio.run(run())


def test_guard_argument_encoder_bounds_and_quotes_input_without_evaluating_hooks():
    arguments = list(example_arguments());arguments[8] = "doc'; SELECT PRIVATE; --"
    statement = guard.guard_statement(arguments)
    assert "doc''; SELECT PRIVATE; --" in statement
    assert statement.startswith('SELECT cragkit_qdrant.lock_current_security(')
    for invalid in (None,{},example_arguments()[:-1],(*example_arguments(),'extra')):
        with pytest.raises(ValueError):guard.guard_statement(invalid)
    arguments = list(example_arguments());arguments[16] = ['x']*66
    with pytest.raises(ValueError):guard.guard_statement(arguments)
    class Hostile:
        def __str__(self):raise AssertionError('untrusted hook evaluated')
    arguments[16] = [Hostile()]
    with pytest.raises(ValueError):guard.guard_statement(arguments)


@pytest.mark.parametrize('cleanup_failure',[False,True])
def test_probe_primary_failure_attempts_savepoint_cleanup_and_closes_borrowed_contexts(cleanup_failure):
    from runtime_diagnostics import CleanupFailure
    async def run():
        def fail(statement):
            return statement.startswith('SELECT cragkit_qdrant.lock_current_security(') or cleanup_failure and statement.startswith('ROLLBACK TO SAVEPOINT ')
        database = RecordingDatabase(fail)
        with pytest.raises(CleanupFailure if cleanup_failure else RuntimeError) as caught:
            await guard.run_sql_probes(database,example_arguments())
        if cleanup_failure:
            assert 'PRIVATE' not in str(caught.value.to_dict())
        statements = [statement for _,_,statement,_ in database.queries]
        assert 'ROLLBACK TO SAVEPOINT qa_security_guard_probe' in statements
        assert 'RELEASE SAVEPOINT qa_security_guard_probe' in statements
        assert ('transaction_rollback','supervisor') in database.events
        assert ('connection_close','supervisor') in database.events
    asyncio.run(run())


def test_probe_rejects_malformed_arguments_before_any_database_use():
    async def run():
        database = RecordingDatabase()
        with pytest.raises(ValueError):await guard.run_sql_probes(database,('wrong',))
        assert database.queries == [] and database.events == []
    asyncio.run(run())


def test_committed_privilege_fault_cleanup_reports_primary_and_revoke_failure_separately():
    from runtime_diagnostics import CleanupFailure
    async def run():
        database = RecordingDatabase()
        def fail(statement):
            return (database.drift and "SQLSTATE '22023'" in statement
                    or statement.startswith('REVOKE SELECT(canonical_utf8)'))
        database.fail = fail
        database.admin.fail = fail
        with pytest.raises(CleanupFailure) as caught:
            await guard.run_sql_probes(database,example_arguments())
        diagnostic = caught.value.to_dict()
        assert diagnostic['primary'] is not None and diagnostic['cleanup']
        assert 'PRIVATE' not in str(diagnostic)
        assert any(statement.startswith('REVOKE SELECT(canonical_utf8)') for _,_,statement,_ in database.queries)
        assert database.events.count(('connection_open','supervisor')) == database.events.count(('connection_close','supervisor'))
    asyncio.run(run())
