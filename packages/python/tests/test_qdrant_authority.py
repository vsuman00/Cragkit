import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import cragkit._qdrant_authority as implementation
from cragkit._postgres_pool import PoolConfig, PoolResource
from cragkit._qdrant_contract import parse_model, QdrantConfig
from cragkit._qdrant_source import validate_nomination
from cragkit.contracts import RetrievalRequest, TrustedScope
from cragkit.errors import DeadlineExceeded, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability
from test_qdrant_source import CONFIG, FIXTURE, expand


class Cursor:
    def __init__(self, rows): self.rows=rows
    async def fetchall(self): return self.rows


class Connection:
    def __init__(self):
        self.info=SimpleNamespace(transaction_status=0)
        self.calls=[]; self.closed=False; self.rollbacks=0
        self.role=[(True,)];self.catalog=[(True,)];self.publication_catalog=[(True,)]
        self.history=list(implementation.EXPECTED_HISTORY)
        self.failure=None;self.rollback_failure=False;self.rows=[]
        self.fingerprint=[(implementation.EXPECTED_CATALOG_FINGERPRINT,)]
    def transaction(self, *, force_rollback):
        assert force_rollback
        owner=self
        class Transaction:
            async def __aenter__(self): owner.info.transaction_status=2
            async def __aexit__(self,*args):
                if owner.rollback_failure: raise RuntimeError('PRIVATE_ROLLBACK')
                owner.info.transaction_status=0;owner.rollbacks+=1
        return Transaction()
    async def execute(self, sql, params=None):
        self.calls.append((sql,params))
        if 'statement_timeout' in sql or sql.startswith('SET '): return Cursor([])
        if self.failure is not None: raise self.failure
        if sql==implementation._ROLE_SQL:return Cursor(self.role)
        if sql==implementation._CATALOG_SQL:return Cursor(self.catalog)
        if sql==implementation._PUBLICATION_CATALOG_SQL:return Cursor(self.publication_catalog)
        if sql==implementation._HISTORY_SQL:return Cursor(self.history)
        if sql==implementation._CATALOG_FINGERPRINT_SQL:return Cursor(self.fingerprint)
        if sql==implementation._SCOPE_SQL:return Cursor([(None,)*5])
        if sql.startswith('SELECT '+implementation._SELECTION):return Cursor(self.rows)
        raise AssertionError('unknown query')
    async def close(self):self.closed=True;self.info.transaction_status=4


class Pool:
    def __init__(self, connection):self.connection=connection;self.borrowed=0;self.returned=0;self.closed=False
    async def getconn(self, **kwargs):self.borrowed+=1;return self.connection
    async def putconn(self, connection):self.returned+=1
    async def close(self, **kwargs):self.closed=True


def authority():
    connection=Connection();pool=Pool(connection)
    config=PoolConfig(host='example.invalid',dbname='test',user='reader',sslrootcert=Path('/tmp/cert'),passfile=Path('/tmp/pass'))
    return implementation.PostgresQdrantAuthority(PoolResource(config,pool=pool)),connection,pool


def test_initialization_uses_own_history_catalog_readonly_transactions_and_borrowed_pool():
    async def scenario():
        reader,conn,pool=authority()
        await reader.initialize(deadline=asyncio.get_running_loop().time()+2)
        assert conn.rollbacks==1 and conn.info.transaction_status==0
        assert any(sql=='SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY' for sql,_ in conn.calls)
        assert any(sql==implementation._HISTORY_SQL for sql,_ in conn.calls)
        assert all('FROM cragkit.' not in sql for sql,_ in conn.calls)
        assert pool.borrowed==pool.returned==1 and not pool.closed
    asyncio.run(scenario())


@pytest.mark.parametrize('field,error',[('role',UnauthorizedScope),('catalog',UnsupportedCapability),('history',UnsupportedCapability)])
def test_incompatible_role_schema_history_are_typed_and_rolled_back(field,error):
    async def scenario():
        reader,conn,pool=authority();setattr(conn,field,[(False,)])
        with pytest.raises(error):await reader.initialize(deadline=asyncio.get_running_loop().time()+2)
        assert conn.rollbacks==1 and pool.returned==1
    asyncio.run(scenario())


def test_exact_parameterized_scope_and_source_filters():
    async def scenario():
        reader,conn,pool=authority()
        req=parse_model(RetrievalRequest,FIXTURE['request']);scope=parse_model(TrustedScope,FIXTURE['scope']);cfg=parse_model(QdrantConfig,CONFIG)
        nom=validate_nomination(expand(FIXTURE['nomination']),req,scope,cfg)
        row=expand(FIXTURE['base_row']);conn.rows=[tuple(row[key] for key in implementation.SOURCE_ROW_FIELDS)]
        result=await reader.read(nom,req,scope,cfg,retained=False,max_source_bytes=13,deadline=asyncio.get_running_loop().time()+2)
        assert result==[row]
        scope_call=next(params for sql,params in conn.calls if sql==implementation._SCOPE_SQL)
        assert scope_call==('tenant-a','docs','reader-a','["grant-a"]','auth-1')
        sql,args=next((sql,params) for sql,params in conn.calls if sql.startswith('SELECT '+implementation._SELECTION))
        assert 'g.published AND d.active_generation_id=g.generation_id' in sql
        assert 'd.kind = %s' in sql and args[-1]=='guide'
        assert args[:2]==(13,13) and 'LIMIT 2' in sql
        assert pool.borrowed==pool.returned==1
    asyncio.run(scenario())


def test_parameterized_filter_groups_do_not_allow_injection():
    request=parse_model(RetrievalRequest,{'query':'test','collection':'docs','required_filters':[{'op':'or','filters':[
        {'op':'eq','field':'tag','value':"' OR TRUE --"},{'op':'in','field':'language','values':['en','雪']}]}]})
    sql,params=implementation.compile_filters(request)
    assert sql=='(d.tag = %s OR d.language = ANY(%s::text[]))'
    assert params==("' OR TRUE --",['en','雪'])


def test_cleanup_failure_closes_connection_and_preserves_operational_failure():
    async def scenario():
        reader,conn,pool=authority();conn.rollback_failure=True
        with pytest.raises(ProviderUnavailable):await reader.initialize(deadline=asyncio.get_running_loop().time()+2)
        assert conn.closed and pool.returned==1
        reader2,conn2,pool2=authority();conn2.failure=RuntimeError('PRIVATE_CONNECTION_URI');conn2.rollback_failure=True
        with pytest.raises(ProviderUnavailable) as caught:await reader2.initialize(deadline=asyncio.get_running_loop().time()+2)
        assert 'PRIVATE' not in str(caught.value) and caught.value.__suppress_context__
        assert conn2.closed and pool2.returned==1
    asyncio.run(scenario())


def test_dirty_connection_is_closed_before_pool_return_and_expiry_has_no_borrow():
    async def scenario():
        reader,conn,pool=authority();conn.info.transaction_status=2
        with pytest.raises(ProviderUnavailable):await reader.initialize(deadline=asyncio.get_running_loop().time()+2)
        assert conn.closed and pool.returned==1
        reader2,_,pool2=authority()
        with pytest.raises(DeadlineExceeded):await reader2.initialize(deadline=asyncio.get_running_loop().time()-1)
        assert pool2.borrowed==0
    asyncio.run(scenario())


def test_revision_filter_uses_generation_column_and_all_fields_are_allowlisted():
    request=parse_model(RetrievalRequest,{'query':'test','collection':'docs','required_filters':[
        {'op':'eq','field':field,'value':'x'} for field in ('document_id','revision_id','language','kind','tag')]})
    sql,values=implementation.compile_filters(request)
    assert sql=='d.document_id = %s AND g.revision_id = %s AND d.language = %s AND d.kind = %s AND d.tag = %s'
    assert values==('x',)*5


@pytest.mark.parametrize('state,error',[('42P01',UnsupportedCapability),('42703',UnsupportedCapability),('42883',UnsupportedCapability),('57014',ProviderUnavailable),('08006',ProviderUnavailable)])
def test_sqlstate_schema_failures_do_not_become_missing_evidence(state,error):
    async def scenario():
        reader,conn,pool=authority()
        failure=RuntimeError('PRIVATE_DRIVER_DETAIL');failure.sqlstate=state;conn.failure=failure
        with pytest.raises(error) as caught:await reader.initialize(deadline=asyncio.get_running_loop().time()+2)
        assert 'PRIVATE' not in str(caught.value) and caught.value.__suppress_context__
        assert conn.rollbacks==1 and pool.returned==1
    asyncio.run(scenario())



def test_embedded_catalog_query_is_exact_and_runtime_needs_no_repo_read():
    frozen=(Path(__file__).resolve().parents[3]/'contracts/QDRANT_AUTHORITY_CATALOG_V5.sql').read_text()
    assert implementation._CATALOG_FINGERPRINT_SQL==frozen


@pytest.mark.parametrize('value',[[],[('tampered',)],[(implementation.EXPECTED_CATALOG_FINGERPRINT,)]*2])
def test_catalog_fingerprint_missing_changed_or_multiple_rejects(value):
    async def scenario():
        reader,conn,pool=authority();conn.fingerprint=value
        with pytest.raises(UnsupportedCapability):await reader.initialize(deadline=asyncio.get_running_loop().time()+2)
        assert conn.rollbacks==1 and pool.returned==1
    asyncio.run(scenario())


def test_publication_profile_matches_captured_history_and_fingerprint():
    root = Path(__file__).resolve().parents[3]
    fixture = json.loads((root / 'contracts/fixtures/qdrant_publication_catalog.json').read_text())
    assert implementation.EXPECTED_PUBLICATION_HISTORY == tuple(tuple(row) for row in fixture['history'])
    assert implementation.EXPECTED_PUBLICATION_CATALOG_FINGERPRINT == fixture['catalog_fingerprint']
    assert implementation.EXPECTED_PUBLICATION_HISTORY[0] == implementation.EXPECTED_HISTORY[0]


@pytest.mark.parametrize('publication', [False, True])
def test_exact_profile_selected_from_history_before_structural_or_role_checks(publication):
    async def scenario():
        reader, conn, pool = authority()
        expected_catalog = implementation._CATALOG_SQL
        if publication:
            conn.history = list(implementation.EXPECTED_PUBLICATION_HISTORY)
            conn.fingerprint = [(implementation.EXPECTED_PUBLICATION_CATALOG_FINGERPRINT,)]
            conn.catalog = [(False,)]  # Never run the source-only structural check for publication.
            expected_catalog = implementation._PUBLICATION_CATALOG_SQL
        else:
            conn.publication_catalog = [(False,)]
        await reader.initialize(deadline=asyncio.get_running_loop().time() + 2)
        queries = [sql for sql, _ in conn.calls if sql in (
            implementation._HISTORY_SQL, implementation._CATALOG_SQL,
            implementation._PUBLICATION_CATALOG_SQL, implementation._ROLE_SQL,
            implementation._CATALOG_FINGERPRINT_SQL)]
        assert queries == [implementation._HISTORY_SQL, expected_catalog,
                           implementation._ROLE_SQL, implementation._CATALOG_FINGERPRINT_SQL]
        assert 'LIMIT 3' in implementation._HISTORY_SQL
        assert conn.rollbacks == 1 and pool.borrowed == pool.returned == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('history', [
    [], [('0001_authority', '0' * 64)], [('0002_publication', '0' * 64)],
    list(implementation.EXPECTED_PUBLICATION_HISTORY) + [('0003_unknown', '0' * 64)],
    list(reversed(implementation.EXPECTED_PUBLICATION_HISTORY)),
    [implementation.EXPECTED_HISTORY[0], ('0002_publication', '0' * 64)],
    [(False,)], [('0001_authority', None)], [('0001_authority', b'checksum')],
    [('0001_authority', 'hash', 'extra')], [list(implementation.EXPECTED_HISTORY[0])],
])
def test_unknown_extra_malformed_or_crossed_history_rejects_before_catalog(history):
    async def scenario():
        reader, conn, pool = authority()
        conn.history = history
        with pytest.raises(UnsupportedCapability):
            await reader.initialize(deadline=asyncio.get_running_loop().time() + 2)
        queries = [sql for sql, _ in conn.calls]
        assert implementation._HISTORY_SQL in queries
        assert implementation._CATALOG_SQL not in queries
        assert implementation._PUBLICATION_CATALOG_SQL not in queries
        assert implementation._CATALOG_FINGERPRINT_SQL not in queries
        assert implementation._ROLE_SQL not in queries
        assert conn.rollbacks == 1 and pool.returned == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('publication', [False, True])
def test_crossed_catalog_hash_pair_is_never_accepted(publication):
    async def scenario():
        reader, conn, _ = authority()
        if publication:
            conn.history = list(implementation.EXPECTED_PUBLICATION_HISTORY)
        conn.fingerprint = [(implementation.EXPECTED_CATALOG_FINGERPRINT if publication
                             else implementation.EXPECTED_PUBLICATION_CATALOG_FINGERPRINT,)]
        with pytest.raises(UnsupportedCapability):
            await reader.initialize(deadline=asyncio.get_running_loop().time() + 2)
    asyncio.run(scenario())


@pytest.mark.parametrize('field', ['publication_catalog', 'fingerprint'])
def test_publication_structural_or_complete_fingerprint_drift_rejects(field):
    async def scenario():
        reader, conn, _ = authority()
        conn.history = list(implementation.EXPECTED_PUBLICATION_HISTORY)
        conn.fingerprint = [(implementation.EXPECTED_PUBLICATION_CATALOG_FINGERPRINT,)]
        setattr(conn, field, [(False,)])
        with pytest.raises(UnsupportedCapability):
            await reader.initialize(deadline=asyncio.get_running_loop().time() + 2)
    asyncio.run(scenario())


def test_role_guard_denies_operational_select_capability_membership_and_extra_helpers():
    sql = implementation._ROLE_SQL
    for name in ('cragkit_qdrant_writer', 'cragkit_qdrant_supervisor'):
        assert name in sql
    assert "pg_has_role(current_user,r.oid,'MEMBER')" in sql
    assert "has_any_column_privilege(current_user,c.oid,'SELECT')" in sql
    assert "has_function_privilege(current_user,p.oid,'EXECUTE')" in sql
    assert 'p.oid IS DISTINCT FROM to_regprocedure' in sql
    assert "has_any_column_privilege(current_user,c.oid,'INSERT,UPDATE,REFERENCES')" in sql


def test_fresh_lease_role_rejection_precedes_scope_and_source_queries():
    async def scenario():
        reader, conn, _ = authority()
        conn.history = list(implementation.EXPECTED_PUBLICATION_HISTORY)
        conn.fingerprint = [(implementation.EXPECTED_PUBLICATION_CATALOG_FINGERPRINT,)]
        await reader.initialize(deadline=asyncio.get_running_loop().time() + 2)
        conn.role = [(False,)]
        conn.calls.clear()
        request = parse_model(RetrievalRequest, FIXTURE['request'])
        scope = parse_model(TrustedScope, FIXTURE['scope'])
        config = parse_model(QdrantConfig, CONFIG)
        nomination = validate_nomination(expand(FIXTURE['nomination']), request, scope, config)
        with pytest.raises(UnauthorizedScope):
            await reader.read(nomination, request, scope, config, retained=False,
                              max_source_bytes=13, deadline=asyncio.get_running_loop().time() + 2)
        assert any(sql == implementation._ROLE_SQL for sql, _ in conn.calls)
        assert all(sql != implementation._SCOPE_SQL and not sql.startswith('SELECT ' + implementation._SELECTION)
                   for sql, _ in conn.calls)
    asyncio.run(scenario())


def test_publication_structural_guard_is_separate_and_requires_complete_rls_profile():
    sql = implementation._PUBLICATION_CATALOG_SQL
    assert 'count(*)=13' in sql and 'count(*)=12' in sql
    assert "c.relname<>'schema_migrations'" in sql
    assert 'c.relrowsecurity AND c.relforcerowsecurity' in sql
    assert 'NOT x.convalidated' in sql and 'p.prosecdef' in sql
    assert "t.tgenabled<>'O'" in sql
    assert 't.tgisinternal' not in sql
    assert 'count(*)=5' in implementation._CATALOG_SQL
