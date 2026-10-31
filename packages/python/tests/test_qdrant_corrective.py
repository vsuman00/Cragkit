"""Actual optional adapters over deterministic boundary fixtures."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import pytest

from cragkit._postgres_pool import PoolConfig,PoolResource
from cragkit.contracts import parse_request,parse_scope
from cragkit.corrective import CorrectiveRetriever
from cragkit.errors import EmbeddingProfileMismatch,ProviderUnavailable,UnsupportedCapability
from cragkit.execution import ExecutionLedger
from cragkit.embeddings import OPENAI_PROFILE
from cragkit.qdrant import QdrantSearchStore
from cragkit.qdrant_source import PostgresQdrantSourceStore
from cragkit.qdrant_corrective import QdrantCorrectiveBackend

FIXTURE=json.loads((Path(__file__).resolve().parents[3]/'contracts/fixtures/qdrant_sources.json').read_text())


def expand(value):
    if isinstance(value,str) and value.startswith('$ref:'):
        target=FIXTURE
        for key in value[5:].split('.'):target=target[key]
        return expand(target)
    if isinstance(value,dict):
        if value.get('encoding')=='utf8':return value['value'].encode()
        if value.get('encoding')=='hex':return bytes.fromhex(value['value'])
        return {key:expand(item) for key,item in value.items()}
    if isinstance(value,list):return [expand(item) for item in value]
    return value


CONFIG={key:expand(FIXTURE['base_row'][key]) for key in ('backend_namespace','physical_collection','collection_incarnation','dense_profile','sparse_profile')}
REQUEST=dict(FIXTURE['request'],request_id='qcc',output_profile=dict(renderer='cragkit.context.v2'),
    limits=dict(max_candidates=1,max_attempts=1,max_provider_calls=1))


class Counter:
    name='fake-byte-v1'
    def count(self,text):return len(text.encode())


class CandidateTransport:
    bounded_responses=True
    cancellation_safe=True
    def __init__(self):self.searches=0;self.closed=False
    async def request(self,method,path,*,body=None,**options):
        if path=='/':return b'{"version":"1.20.0"}'
        if path=='/cluster':result=dict(status='disabled')
        elif method=='GET':result=dict(config=dict(params=dict(vectors=dict(dense=dict(size=1536,distance='Cosine')),
            sparse_vectors=dict(sparse={}),replication_factor=1,write_consistency_factor=1)))
        else:
            self.searches+=1;n=expand(FIXTURE['nomination'])
            result=dict(points=[dict(id=n['point_id'],score=n['score'],payload=n['payload'])])
        return json.dumps(dict(result=result,status='ok')).encode()
    async def close(self):self.closed=True


class Authority:
    def __init__(self):self.row=expand(FIXTURE['base_row']);self.calls=0;self.failure=False;self.revoke=False;self.block=None;self.entered=asyncio.Event()
    async def initialize(self,**options):pass
    async def read(self,*args,max_source_bytes,**options):
        self.calls+=1;self.entered.set()
        if self.block:await self.block.wait()
        if self.failure:raise RuntimeError('private source connection details')
        row=deepcopy(self.row)
        if self.revoke and self.calls>1:row.update(principal_ids=[],grant_ids=[])
        if row['source_bytes']>max_source_bytes:row['canonical_utf8']=row['excerpt_utf8']=None
        return [row]


async def setup():
    end=asyncio.get_running_loop().time()+5
    transport=CandidateTransport();candidates=QdrantSearchStore(CONFIG,transport)
    await candidates.initialize(deadline=end)
    resource=PoolResource(PoolConfig(host='example.invalid',dbname='fixture',user='reader',
        sslrootcert=Path('/tmp/cert'),passfile=Path('/tmp/pass')),pool=object())
    sources=PostgresQdrantSourceStore(resource,CONFIG);authority=Authority();sources._authority=authority
    await sources.initialize(deadline=end)
    calls=[]
    async def embedding(body,**options):
        calls.append(json.loads(body))
        return json.dumps(dict(model=CONFIG['dense_profile']['model'],data=[dict(index=0,embedding=[1.]+[0.]*1535)],
            usage=dict(prompt_tokens=len(REQUEST['query'].encode()),total_tokens=len(REQUEST['query'].encode())))).encode()
    backend=QdrantCorrectiveBackend(candidates,sources,embedding_transport=embedding,token_counter=Counter())
    return backend,candidates,sources,transport,authority,calls,end


def test_native_engine_composition_accounts_once_and_keeps_stores_borrowed():
    async def scenario():
        backend,candidates,sources,transport,authority,calls,end=await setup()
        result=await CorrectiveRetriever(backend,batch_size=1).retrieve(REQUEST,scope=FIXTURE['scope'],deadline=end)
        assert result['result']['status']=='partial' and len(result['result']['evidence'])==1
        item=result['result']['evidence'][0];canonical=expand(FIXTURE['base_row']['canonical_utf8'])
        assert item['text']==canonical[item['start_byte']:item['end_byte']].decode()
        usage=result['diagnostics']['ledger']
        assert usage['candidates']==usage['attempts']==usage['provider_calls']==len(calls)==transport.searches==1
        assert authority.calls==2 and sources._handle is None and not transport.closed
        assert 'nomination' not in json.dumps(result['result']) and 'private_source' not in json.dumps(result['result'])
        await sources.close();await candidates.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('mode',['lexical','hybrid'])
def test_unsupported_modes_refuse_before_model_work(mode):
    async def scenario():
        backend,candidates,sources,transport,authority,calls,end=await setup()
        with pytest.raises(UnsupportedCapability):QdrantCorrectiveBackend(candidates,sources,embedding_transport=backend._transport,token_counter=Counter(),mode=mode)
        assert not calls and transport.searches==0 and authority.calls==0
        await sources.close();await candidates.close()
    asyncio.run(scenario())


def test_provider_budget_refuses_before_transport_and_candidate_dispatch():
    async def scenario():
        backend,candidates,sources,transport,authority,calls,end=await setup()
        request=dict(REQUEST,limits=dict(REQUEST['limits'],max_provider_calls=0))
        result=await CorrectiveRetriever(backend,batch_size=1).retrieve(request,scope=FIXTURE['scope'],deadline=end)
        assert result['result']['status']=='insufficient' and not calls and not transport.searches and authority.calls==0
        assert result['diagnostics']['ledger']['candidates']==result['diagnostics']['ledger']['provider_calls']==0
        await sources.close();await candidates.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('fault',['revoked','outage','bytes'])
def test_capture_rechecks_authority_and_never_disguises_failures(fault):
    async def scenario():
        backend,candidates,sources,transport,authority,calls,end=await setup()
        request=parse_request(REQUEST);scope=parse_scope(FIXTURE['scope']);ledger=ExecutionLedger(request.limits,deadline=end)
        selected=(await backend.search(request,scope=scope,deadline=end,limit=1,ledger=ledger))['candidates']
        authority.revoke=fault=='revoked';authority.failure=fault=='outage'
        amount=authority.row['source_bytes'] if fault=='bytes' else 16777216
        if fault=='outage':
            with pytest.raises(ProviderUnavailable):await backend.capture(selected,request=request,scope=scope,deadline=end,max_source_bytes=amount,ledger=ledger)
        else:
            result=await backend.capture(selected,request=request,scope=scope,deadline=end,max_source_bytes=amount,ledger=ledger)
            assert result['evidence']==[] and result['sources']==[]
            assert result['stale'] if fault=='revoked' else result['budget_exhausted']
        assert sources._handle is None
        await sources.close();await candidates.close()
    asyncio.run(scenario())


def test_profile_mismatch_refuses_before_any_model_or_search_request():
    async def scenario():
        backend,candidates,sources,transport,authority,calls,end=await setup()
        other=QdrantSearchStore(dict(CONFIG,dense_profile=OPENAI_PROFILE.model_dump(),sparse_profile=None),transport)
        with pytest.raises(EmbeddingProfileMismatch):
            QdrantCorrectiveBackend(other,sources,embedding_transport=backend._transport,token_counter=Counter())
        assert not calls and transport.searches==0 and authority.calls==0
        await sources.close();await candidates.close()
    asyncio.run(scenario())


def test_capture_cancellation_closes_its_request_without_closing_borrowed_stores():
    async def scenario():
        backend,candidates,sources,transport,authority,calls,end=await setup()
        request=parse_request(REQUEST);scope=parse_scope(FIXTURE['scope']);ledger=ExecutionLedger(request.limits,deadline=end)
        selected=(await backend.search(request,scope=scope,deadline=end,limit=1,ledger=ledger))['candidates']
        authority.block=asyncio.Event()
        task=asyncio.create_task(backend.capture(selected,request=request,scope=scope,deadline=end,max_source_bytes=16777216,ledger=ledger))
        await authority.entered.wait();task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert sources._handle is None and not sources._closed and not transport.closed
        await sources.close();await candidates.close()
    asyncio.run(scenario())


def test_dispatched_provider_failure_retains_one_unknown_usage_charge():
    async def scenario():
        backend,candidates,sources,transport,authority,calls,end=await setup()
        async def broken(*args,**options):raise RuntimeError('private provider failure')
        backend._transport=broken
        request=parse_request(REQUEST);ledger=ExecutionLedger(request.limits,deadline=end)
        with pytest.raises(ProviderUnavailable):
            await backend.search(request,scope=parse_scope(FIXTURE['scope']),deadline=end,limit=1,ledger=ledger)
        usage=ledger.snapshot()
        assert usage['provider_calls']==1 and usage['pending']==0 and usage['input_tokens'] is None
        assert transport.searches==authority.calls==0
        await sources.close();await candidates.close()
    asyncio.run(scenario())
