"""Bounded query-constant transport and grant cleanup without native services."""
import asyncio
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import qdrant_source_privileges as module
from runtime_diagnostics import CleanupFailure


@pytest.mark.parametrize('value',[{'role':'SELECT true','catalog':'SELECT true'},[],{'role':None,'catalog':'query'},
    {'role':'query','catalog':'query','extra':'private'}, {'role':'x'*32769,'catalog':'query'}])
def test_node_query_constants_accept_only_bounded_expected_strings(monkeypatch,value):
    class Child:
        returncode=0
        async def communicate(self):return json.dumps(value).encode(),b''
    async def create(*args,**kwargs):
        assert args[:3]==('node','--input-type=module','-e')
        assert 'passfile' not in args[3] and 'connect(' not in args[3]
        return Child()
    monkeypatch.setattr(module.asyncio,'create_subprocess_exec',create)
    if value=={'role':'SELECT true','catalog':'SELECT true'}:
        assert asyncio.run(module.node_reader_queries())==value
    else:
        with pytest.raises(RuntimeError):asyncio.run(module.node_reader_queries())


def test_node_query_child_timeout_closes_owned_process_without_stderr_reflection(monkeypatch):
    events=[]
    class Child:
        returncode=None
        async def communicate(self):raise TimeoutError('PRIVATE CHILD DETAIL')
        def terminate(self):events.append('terminate')
        async def wait(self):self.returncode=0;events.append('wait')
    async def create(*args,**kwargs):return Child()
    monkeypatch.setattr(module.asyncio,'create_subprocess_exec',create)
    with pytest.raises(TimeoutError):asyncio.run(module.node_reader_queries())
    assert events==['terminate','wait']


@pytest.mark.parametrize('fail_after_grant',[False,True])
@pytest.mark.parametrize('revoke_fails',[False,True])
def test_noninherited_grants_are_revoked_and_reader_connection_closed(monkeypatch,fail_after_grant,revoke_fails):
    psycopg=pytest.importorskip('psycopg')
    events=[]
    class Cursor:
        async def fetchall(self):return [(not admin.unsafe,)]
    class Admin:
        unsafe=False
        async def execute(self,query):
            query=query.as_string()
            events.append(query)
            if query.startswith('GRANT '):self.unsafe=True
            if query.startswith('REVOKE '):
                if revoke_fails:raise ConnectionError('PRIVATE REVOKE DETAIL')
                self.unsafe=False
    admin=Admin()
    class Connection:
        pgconn=SimpleNamespace(ssl_in_use=True)
        async def execute(self,*args,**kwargs):
            if admin.unsafe and fail_after_grant:raise ConnectionError('PRIVATE SQL DETAIL')
            return Cursor()
        async def close(self):events.append('close')
    async def connect(**kwargs):
        assert kwargs['sslmode']=='verify-full' and kwargs['connect_timeout']==3
        return Connection()
    async def node():return {'role':'node-role','catalog':'node-catalog'}
    monkeypatch.setattr(psycopg.AsyncConnection,'connect',connect)
    monkeypatch.setattr(module,'node_reader_queries',node)
    config={'host':'127.0.0.1','port':1234,'dbname':'fixture','user':'reader',
        'passfile':'private-file','sslrootcert':'private-ca'}
    async def run():return await module.check_reader_privileges(admin,config,publication=False)
    if revoke_fails:
        with pytest.raises(CleanupFailure) as error:asyncio.run(run())
        record=error.value.to_dict()
        assert (record['primary'] is not None)==fail_after_grant
        assert record['cleanup'][0]['operation']=='privilege_revoke'
        assert 'PRIVATE' not in json.dumps(record)
    elif fail_after_grant:
        with pytest.raises(ConnectionError):asyncio.run(run())
    else:assert len(asyncio.run(run()))==1
    assert admin.unsafe==revoke_fails and events[-1]=='close'
    assert any(query.startswith('REVOKE ') for query in events)
