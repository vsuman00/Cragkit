import asyncio
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
        self.role=[(True,)];self.catalog=[(True,)];self.history=list(implementation.EXPECTED_HISTORY)
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
