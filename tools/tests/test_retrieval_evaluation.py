"""Worker packet/flow tests; fake native boundaries are not native-quality proof."""
import asyncio
import copy
from hashlib import sha256
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import retrieval_evaluation as E
from cragkit.contracts import parse_result
from cragkit.errors import ProviderUnavailable

PACKET=json.loads((Path(__file__).resolve().parents[2]/'contracts/fixtures/retrieval_evaluation.json').read_text())
CONFIG=dict(host='localhost',port=5432,dbname='mechanics',user='mechanics',
            sslrootcert='/tmp/explicit-cert',passfile='/tmp/explicit-passfile')


@pytest.mark.parametrize('mutation', ['labels','document_extra','question_extra','hash','active','duplicate','unknown_location','long_query','surrogate','wrong_type','filters_tuple'])
def test_malformed_packet_rejects_before_any_resource_or_tokenizer(monkeypatch,mutation):
    packet=copy.deepcopy(PACKET)
    if mutation=='labels':packet['labels']=[]
    elif mutation=='document_extra':packet['documents'][0]['facets']=[]
    elif mutation=='question_extra':packet['queries'][0]['answerability']='answerable'
    elif mutation=='hash':packet['documents'][0]['canonical_sha256']='0'*64
    elif mutation=='active':packet['documents'][0]['active']=True
    elif mutation=='duplicate':packet['queries'].append(copy.deepcopy(packet['queries'][0]))
    elif mutation=='unknown_location':packet['queries'][0]['tenant_id']='missing'
    elif mutation=='long_query':packet['queries'][0]['query']='x'*8193
    elif mutation=='surrogate':packet['documents'][0]['text']='bad\ud800'
    elif mutation=='filters_tuple':packet['queries'][0]['required_filters']=()
    else:packet['documents'][0]['active']=1
    def forbidden(*args,**kwargs):pytest.fail('prevalidation touched a resource')
    monkeypatch.setattr(E,'_Resource',forbidden)
    monkeypatch.setattr(E.Cl100kCounter,'from_file',forbidden)
    with pytest.raises(E.EvaluationExecutionError,match='invalid_evaluation_packet'):
        asyncio.run(E.run_evaluation(packet,reader_config=None,writer_config=None,tokenizer_path='unused'))


def test_packet_snapshot_order_and_query_only_variants():
    packet=copy.deepcopy(PACKET)
    snapshot=E.validate_packet(packet)
    packet['documents'][0]['text']='changed'
    assert snapshot['documents'][0]['text']==PACKET['documents'][0]['text']
    documents=sorted(snapshot['documents'],key=E.document_order)
    retry=[row for row in documents if row['document_id']=='retry-policy']
    assert [row['active'] for row in retry]==[False,True]
    assert E.query_variants('  ERR-17\t retries  ')==[
        dict(facet_id='query-intent',variant_id='normalized',query='ERR-17 retries'),
        dict(facet_id='query-intent',variant_id='identifiers',query='ERR-17')]
    assert E.query_variants('café 😀')==[]
    assert E.query_variants('ERR-17')==[]


def test_revision_alias_union_negation_membership_and_unknowns():
    receipts=[dict(tenant_id='a',collection='c',logical_revision_id='r1',revision_id='native-b'),
              dict(tenant_id='a',collection='c',logical_revision_id='r1',revision_id='native-a'),
              dict(tenant_id='other',collection='c',logical_revision_id='r1',revision_id='foreign')]
    filters=[dict(op='and',filters=[dict(op='eq',field='revision_id',value='r1'),
        dict(op='ne',field='revision_id',value='r1'),dict(op='not',filter=dict(op='in',field='revision_id',values=['r1','unknown']))])]
    changed=E.translate_filters(filters,receipts,'a','c')[0]['filters']
    assert changed[0]==dict(op='in',field='revision_id',values=['native-a','native-b'])
    assert changed[1]==dict(op='not',filter=changed[0])
    assert changed[2]['filter']['values']==['native-a','native-b','unknown']
    assert filters[0]['filters'][0]['op']=='eq'


def test_large_alias_union_preserves_membership_in_bounded_or_chunks():
    receipts=[dict(tenant_id='a',collection='c',logical_revision_id='r1',revision_id=str(index)) for index in range(32)]
    result=E.translate_filters([dict(op='in',field='revision_id',values=['r1']+[f'unknown-{i}' for i in range(31)])],receipts,'a','c')[0]
    assert result['op']=='or' and [len(row['values']) for row in result['filters']]==[32,31]
    assert len({value for row in result['filters'] for value in row['values']})==63


def fake_native(monkeypatch,*,failure=False,cancel=False,mutate=None,cleanup_failure=False):
    resources,ingestions,requests,targets=[],[],[],[]
    class Resource:
        def __init__(self,config):
            assert config.max_size==1
            self.active=0;self.closed=False
            resources.append(self)
        async def open(self):
            if mutate is not None:mutate()
        async def close(self):
            self.closed=True
            if cleanup_failure:raise RuntimeError('private cleanup')
    class Counter:
        @staticmethod
        def from_file(path):return SimpleNamespace(count=lambda text:len(text.encode()))
    class Indexer:
        def __init__(self,resource,**options):
            assert options['embedding_profile']==E.FAKE_PROFILE
        async def ingest(self,text,**options):
            ingestions.append((text,options))
            revision=sha256(E._compact([text,options['source_locator']])).hexdigest()
            return SimpleNamespace(revision_id=revision,generation_id='generation-'+revision,
                canonical_sha256=sha256(text.encode()).hexdigest(),embedding_profile=E.FAKE_PROFILE.profile_id)
    def result(request):
        return parse_result(dict(request_id=request.request_id,status='insufficient',
            usage=dict(context_counting='strict',context_tokens=0),versions=dict(tokenizer='cl100k_base')))
    class Retriever:
        def __init__(self,resource,**options):
            assert resources[1].closed
            self.mode=options['mode'];targets.append(options)
        async def retrieve(self,request,**options):
            requests.append((request,options))
            if cancel:raise asyncio.CancelledError()
            if failure and self.mode=='dense':raise ProviderUnavailable()
            return result(request)
    class Backend:
        def __init__(self,resource,**options):targets.append(options)
    class Corrective:
        def __init__(self,backend,**options):
            assert options['batch_size']==15 and options['max_retries']==0
        async def retrieve(self,request,**options):
            requests.append((request,options))
            return dict(result=result(request).model_dump(mode='json'))
    monkeypatch.setattr(E,'_Resource',Resource)
    monkeypatch.setattr(E,'Cl100kCounter',Counter)
    monkeypatch.setattr(E,'PostgresVectorIndexer',Indexer)
    monkeypatch.setattr(E,'PostgresRetriever',Retriever)
    monkeypatch.setattr(E,'PostgresCorrectiveBackend',Backend)
    monkeypatch.setattr(E,'CorrectiveRetriever',Corrective)
    return resources,ingestions,requests,targets


def test_five_mode_worker_snapshots_before_io_cas_receipts_and_failure_denominators(monkeypatch):
    packet=copy.deepcopy(PACKET)
    def mutate():packet['queries'][0]['query']='mutated after I/O'
    resources,ingestions,requests,targets=fake_native(monkeypatch,failure=True,mutate=mutate)
    output=asyncio.run(E.run_evaluation(packet,reader_config=CONFIG,writer_config=CONFIG,tokenizer_path='mock'))
    assert set(output)=={'revision','runtime','kind','receipts','rows','cleanup_verified'}
    assert output['runtime']=='python' and output['kind']=='mechanics' and output['cleanup_verified']
    assert len(output['rows'])==30 and len(output['receipts'])==4
    assert [row['mode'] for row in output['rows'][:5]]==list(E.MODES)
    assert output['rows'][1]['result']==dict(operational_failure=True,error_code='provider_unavailable')
    assert all(row['latency_ms']>=0 for row in output['rows'])
    assert requests[0][0].query=='ERR-17 retries'
    assert all(resource.closed for resource in resources)
    retry=[row for row in ingestions if row[1]['document_id']=='retry-policy']
    assert retry[0][1]['expected_generation_id'] is None
    assert retry[1][1]['expected_generation_id'] is not None
    for text,options in ingestions:
        assert options['canonical_options']==dict(target_bytes=2048,max_chunk_bytes=4096)
        assert options['scope'].principal_id=='v6-evaluation' and options['scope'].grant_ids==()
    for request,_ in requests:
        assert request.limits.max_provider_calls==8 and request.output_profile.counting_mode=='strict'
        assert request.request_id.startswith('eval-') and len(request.request_id)==69
    assert all('policy' not in options for options in targets)


def test_worker_preserves_cancellation_and_closes_both_pools(monkeypatch):
    resources,*_=fake_native(monkeypatch,cancel=True)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(E.run_evaluation(PACKET,reader_config=CONFIG,writer_config=CONFIG,tokenizer_path='mock'))
    assert len(resources)==2 and all(resource.closed for resource in resources)


def test_rerank_audit_captures_request_local_hashes_without_mutating_transport(monkeypatch):
    fake_native(monkeypatch)
    original = E.PostgresRetriever
    class AuditedRetriever(original):
        def __init__(self, resource, **options):
            super().__init__(resource, **options)
            self.reranker = options['evidence_options'].get('reranker')
        async def retrieve(self, request, **options):
            if self.reranker is not None:
                ranked = await self.reranker.rank(request.query,
                    [dict(candidate_id='evidence-1', text='authorized synthetic source')],
                    deadline=options['deadline'], max_provider_calls=1)
                assert ranked['order'] == ['evidence-1']
            return await super().retrieve(request, **options)
    monkeypatch.setattr(E, 'PostgresRetriever', AuditedRetriever)
    events = []
    def audit(event):
        events.append(copy.deepcopy(event))
        event['candidates'].clear()
    output = asyncio.run(E.run_evaluation(PACKET, reader_config=CONFIG, writer_config=CONFIG,
        tokenizer_path='mock', on_rerank_input=audit))
    assert len(events) == len(PACKET['queries'])
    assert all(event['mode'] == 'reranked_hybrid' for event in events)
    for event, query in zip(events, PACKET['queries'], strict=True):
        assert set(event) == {'question_id', 'mode', 'query_sha256', 'profile_id', 'candidates'}
        assert event['question_id'] == query['question_id']
        assert event['query_sha256'] == sha256(query['query'].encode()).hexdigest()
        assert event['candidates'] == [dict(candidate_id='evidence-1',
            text_sha256=sha256(b'authorized synthetic source').hexdigest())]
        assert 'authorized synthetic source' not in json.dumps(event)
    assert not any(row['result'].get('operational_failure') for row in output['rows'])


def test_invalid_audit_callback_is_refused_before_resources(monkeypatch):
    monkeypatch.setattr(E, '_Resource', lambda *args:pytest.fail('Unexpected resource'))
    with pytest.raises(E.EvaluationExecutionError, match='configuration'):
        asyncio.run(E.run_evaluation(PACKET, reader_config=None, writer_config=None,
            tokenizer_path='unused', on_rerank_input=object()))


def test_audit_failure_keeps_mode_denominators_and_closes_callback_coroutines(monkeypatch):
    fake_native(monkeypatch)
    original = E.PostgresRetriever
    class AuditedRetriever(original):
        def __init__(self, resource, **options):
            super().__init__(resource, **options)
            self.reranker = options['evidence_options'].get('reranker')
        async def retrieve(self, request, **options):
            if self.reranker is not None:
                await self.reranker.rank(request.query, [dict(candidate_id='evidence', text='public')],
                    deadline=options['deadline'], max_provider_calls=1)
            return await super().retrieve(request, **options)
    monkeypatch.setattr(E, 'PostgresRetriever', AuditedRetriever)
    returned = []
    async def callback_result():
        raise AssertionError('Async callback must not run')
    def audit(event):
        result = callback_result();returned.append(result)
        return result
    output = asyncio.run(E.run_evaluation(PACKET, reader_config=CONFIG, writer_config=CONFIG,
        tokenizer_path='mock', on_rerank_input=audit))
    assert len(output['rows']) == 30
    assert all(row['result'].get('operational_failure')
               for row in output['rows'] if row['mode'] == 'reranked_hybrid')
    assert all(E.inspect.getcoroutinestate(value) == 'CORO_CLOSED' for value in returned)


def test_cleanup_failure_cannot_claim_verified_completion(monkeypatch):
    resources,*_=fake_native(monkeypatch,cleanup_failure=True)
    with pytest.raises(E.EvaluationExecutionError):
        asyncio.run(E.run_evaluation(PACKET,reader_config=CONFIG,writer_config=CONFIG,tokenizer_path='mock'))
    assert all(resource.closed for resource in resources)


@pytest.mark.parametrize('kind,send',[('live',None),('provider',None),('mechanics',lambda:None)])
def test_kind_requires_explicit_provider_sender_and_forbids_fake_real_mix(kind,send):
    with pytest.raises(E.EvaluationExecutionError,match='configuration'):
        asyncio.run(E.run_evaluation(PACKET,reader_config=None,writer_config=None,tokenizer_path='unused',kind=kind,send=send))


def test_mixed_revision_membership_translates_strings_without_bool_numeric_collapse():
    receipts=[dict(tenant_id='a',collection='c',logical_revision_id='r1',revision_id='native')]
    result=E.translate_filters([dict(op='in',field='revision_id',values=['r1',True,1,False,0,'unknown',1.0])],receipts,'a','c')[0]
    assert result['values'][:2]==['native','unknown']
    values=result['values'][2:]
    assert len(values)==4
    assert {(type(value).__name__,str(value)) for value in values}=={('bool','True'),('bool','False'),('int','1'),('int','0')}


def test_query_cancellation_wins_secondary_cleanup_failure(monkeypatch):
    resources,*_=fake_native(monkeypatch,cancel=True)
    original=E._Resource.close
    async def close(self):
        await original(self)
        if self is resources[0]:raise RuntimeError('private secondary cleanup')
    monkeypatch.setattr(E._Resource,'close',close)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(E.run_evaluation(PACKET,reader_config=CONFIG,writer_config=CONFIG,tokenizer_path='mock'))
    assert all(resource.closed for resource in resources)


def test_repeated_cancellation_during_pool_cleanup_still_waits_both_closes(monkeypatch):
    resources,*_=fake_native(monkeypatch,cancel=True)
    original=E._Resource.close
    async def run():
        entered,release=asyncio.Event(),asyncio.Event()
        async def close(self):
            await original(self)
            if self is resources[0]:
                entered.set()
                await release.wait()
        monkeypatch.setattr(E._Resource,'close',close)
        task=asyncio.create_task(E.run_evaluation(PACKET,reader_config=CONFIG,writer_config=CONFIG,tokenizer_path='mock'))
        await entered.wait()
        task.cancel();await asyncio.sleep(0);task.cancel();await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):await task
        assert all(resource.closed for resource in resources)
    asyncio.run(run())
