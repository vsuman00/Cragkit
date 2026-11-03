"""RST-r1 harness doubles only; root separately owns actual PostgreSQL runs."""
import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import resource_workload as W
from cragkit.errors import ProviderUnavailable

CONFIG=dict(reader_config=dict(host='localhost',dbname='synthetic',user='reader',
    sslrootcert='/tmp/fake-cert',passfile='/tmp/fake-pass'),
    writer_config=dict(host='localhost',dbname='synthetic',user='writer',
    sslrootcert='/tmp/fake-cert',passfile='/tmp/fake-pass'), tokenizer_path='/tmp/fake-tokenizer',sdk_root='/tmp/fake-sdk')


class Counter:
    def count(self,text):return len(text)


class Cursor:
    async def fetchone(self):return (1,)
    async def close(self):pass


class Connection:
    def __init__(self):self.pgconn=SimpleNamespace(transaction_status=0,is_busy=lambda:self.pgconn.transaction_status==1)
    async def execute(self,statement):
        if statement=='SELECT pg_sleep(2)':
            self.pgconn.transaction_status=1
            try:await asyncio.Event().wait()
            finally:self.pgconn.transaction_status=0
        else:assert statement=='SELECT 1'
        return Cursor()
    async def rollback(self):pass


class Resource:
    instances=[]
    def __init__(self,config):
        self.config=config;self._users=set();self._leases={};self.lock=asyncio.Lock()
        self.closed=False;self.opened=False;self.connection=Connection()
        self.__class__.instances.append(self)
    async def open(self):self.opened=True
    async def close(self):self.closed=True
    @asynccontextmanager
    async def lease(self,*,deadline):
        task=asyncio.current_task()
        if len(self._users)>=2:raise ProviderUnavailable()
        self._users.add(task)
        try:
            async with self.lock:
                self._leases[task]=self.connection
                try:yield self.connection
                finally:self._leases.pop(task,None)
        finally:self._users.discard(task)


class Indexer:
    rows={}
    def __init__(self,writer,*,authorize_write,embedder,embedding_profile):
        self.writer=writer;self.authorize=authorize_write
    async def ingest(self,text,**kwargs):
        assert await self.authorize(kwargs['scope'],kwargs['collection'],kwargs['document_id'])
        assert not await self.authorize(kwargs['scope'],'wrong',kwargs['document_id'])
        assert not await self.authorize(kwargs['scope'],kwargs['collection'],'wrong')
        assert self.writer.opened
        receipt=SimpleNamespace(canonical_sha256=sha256(text.encode()).hexdigest(),
            embedding_profile=W.FAKE_PROFILE.profile_id,revision_id=kwargs['document_id']+'-revision',
            tenant_id=kwargs['scope'].tenant_id,collection=kwargs['collection'],document_id=kwargs['document_id'])
        self.rows[kwargs['document_id']]=(text,receipt)
        return receipt


class Retriever:
    active=0;peak=0;calls=0
    def __init__(self,reader,**kwargs):self.reader=reader
    async def retrieve(self,request,*,scope,deadline):
        assert scope.tenant_id=='resource-tenant' and request.collection=='resource-tests'
        assert request.required_filters[0].value=='resource-0'
        cls=self.__class__;cls.calls+=1;cls.active+=1;cls.peak=max(cls.peak,cls.active)
        try:
            await asyncio.sleep(0)
            text,receipt=Indexer.rows['resource-0']
            evidence=SimpleNamespace(document_id='resource-0',collection='resource-tests',
                revision_id=receipt.revision_id,source_sha256=receipt.canonical_sha256,
                start_byte=0,end_byte=len(text.encode()),text=text,text_sha256=sha256(text.encode()).hexdigest())
            return SimpleNamespace(execution='complete',evidence=[evidence],context='[]',
                usage=SimpleNamespace(context_counting='strict',context_tokens=2,attempt_count=1,
                    provider_calls=1,cost_kind='known',cost_usd=0))
        finally:cls.active-=1


@pytest.fixture
def doubles(monkeypatch):
    Resource.instances=[];Indexer.rows={};Retriever.calls=Retriever.active=Retriever.peak=0
    monkeypatch.setattr(W,'PoolResource',Resource)
    monkeypatch.setattr(W,'PostgresVectorIndexer',Indexer)
    monkeypatch.setattr(W,'PostgresRetriever',Retriever)
    monkeypatch.setattr(W.Cl100kCounter,'from_file',lambda path:Counter())
    return Resource


def test_bounded_workload_and_deterministic_queue_cancellation_cleanup(doubles):
    result=asyncio.run(W.run_resource_workload(CONFIG))
    assert result['revision']=='RST-r1' and result['runtime']=='python'
    assert len(result['ingestion_ms'])==3 and Retriever.calls==40 and Retriever.peak==2
    assert result['provider_http_calls']==0 and result['peak_rss_bytes']>0
    assert set(result['checks'])==set(W._CHECKS) and all(result['checks'].values())
    for expected,stage in zip((1,2),result['retrieval'],strict=True):
        assert stage['concurrency']==expected and stage['elapsed_ms']>0 and stage['throughput_per_second']>0
        assert len(stage['latency_ms'])==len(stage['context_tokens'])==len(stage['attempts'])==len(stage['provider_calls'])==20
    assert all(r.config.max_size==r.config.max_waiting==1 and r.closed for r in doubles.instances)
    assert all(not r._users and not r._leases for r in doubles.instances)
    assert 'fake-pass' not in str(result) and 'Resource handbook' not in str(result)


@pytest.mark.parametrize('mutation',['extra','missing','badpool','wrongtokenizer'])
def test_invalid_configuration_fails_fixed_and_closes_created_resources(doubles,mutation):
    config=dict(CONFIG)
    if mutation=='extra':config['private']='private-marker'
    elif mutation=='missing':config.pop('sdk_root')
    elif mutation=='badpool':config['writer_config']={}
    else:config['tokenizer_path']=False
    with pytest.raises(W.ResourceWorkloadError,match='^resource_workload_failed$') as error:
        asyncio.run(W.run_resource_workload(config))
    assert error.value.__context__ is None
    assert all(r.closed for r in doubles.instances)


@pytest.mark.parametrize('fault',['source','scope','tokens','calls','execution'])
def test_result_invariant_faults_never_return_success(doubles,monkeypatch,fault):
    original=Retriever.retrieve
    async def broken(self,*args,**kwargs):
        result=await original(self,*args,**kwargs)
        if fault=='source':result.evidence[0].text='changed-private-source'
        elif fault=='scope':result.evidence[0].document_id='foreign'
        elif fault=='tokens':result.usage.context_tokens=99
        elif fault=='calls':result.usage.provider_calls=9
        else:result.execution='degraded'
        return result
    monkeypatch.setattr(Retriever,'retrieve',broken)
    with pytest.raises(W.ResourceWorkloadError,match='^resource_workload_failed$') as error:
        asyncio.run(W.run_resource_workload(CONFIG))
    assert error.value.__context__ is None
    assert all(r.closed and not r._users for r in doubles.instances)


def test_unobserved_dispatch_cannot_be_reported_as_active_cancellation(doubles,monkeypatch):
    async def finished(self,statement):return Cursor()
    monkeypatch.setattr(Connection,'execute',finished)
    with pytest.raises(W.ResourceWorkloadError,match='^resource_workload_failed$'):
        asyncio.run(W.run_resource_workload(CONFIG))
    assert all(r.closed and not r._users for r in doubles.instances)


def test_private_driver_failure_sanitized_and_cleanup_attempted(doubles,monkeypatch):
    async def broken(self):raise RuntimeError('private connection detail')
    monkeypatch.setattr(Resource,'open',broken)
    with pytest.raises(W.ResourceWorkloadError,match='^resource_workload_failed$') as error:
        asyncio.run(W.run_resource_workload(CONFIG))
    assert error.value.__context__ is None and error.value.__cause__ is None
    assert all(r.closed for r in doubles.instances)


def test_external_cancellation_closes_all_resources_and_propagates(doubles,monkeypatch):
    entered=asyncio.Event()
    async def held(self,*args,**kwargs):
        entered.set();await asyncio.Event().wait()
    monkeypatch.setattr(Retriever,'retrieve',held)
    async def run():
        task=asyncio.create_task(W.run_resource_workload(CONFIG))
        await entered.wait();task.cancel('private cancellation marker')
        with pytest.raises(asyncio.CancelledError) as error:await task
        assert error.value.args==()
    asyncio.run(run())
    assert all(r.closed for r in doubles.instances)


def test_bad_ingestion_identity_and_late_measurement_fail(doubles,monkeypatch):
    original=Indexer.ingest
    async def foreign(self,*args,**kwargs):
        receipt=await original(self,*args,**kwargs)
        receipt.tenant_id='foreign-tenant'
        return receipt
    monkeypatch.setattr(Indexer,'ingest',foreign)
    with pytest.raises(W.ResourceWorkloadError):asyncio.run(W.run_resource_workload(CONFIG))
    assert all(r.closed for r in doubles.instances)
    monkeypatch.setattr(Indexer,'ingest',original)
    monkeypatch.setattr(W,'_milliseconds',lambda started:25000)
    with pytest.raises(W.ResourceWorkloadError):asyncio.run(W.run_resource_workload(CONFIG))
    assert all(r.closed for r in doubles.instances)


def test_fake_embedding_is_bounded_and_does_not_use_http(doubles):
    async def run():
        reader=Resource(None);writer=Resource(None)
        adapter=W._embedder(reader,writer)
        batch=await adapter.embed_query('support route queue',deadline=asyncio.get_running_loop().time()+1)
        assert len(batch.vectors)==1 and len(batch.vectors[0])==1536
        assert batch.vectors[0][0]==1 and sum(batch.vectors[0][1:])==0
    asyncio.run(run())
