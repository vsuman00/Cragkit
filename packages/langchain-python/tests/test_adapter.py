"""AD-r1 boundary checks against the real optional LangChain SDK."""
import asyncio
from copy import deepcopy
from hashlib import sha256
import json
import os
from pathlib import Path
import socket

import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import StructuredTool
from langsmith import tracing_context
from langsmith.run_helpers import get_tracing_context

from cragkit.context import Cl100kCounter
from cragkit.contracts import RetrievalResult
from cragkit.errors import (ContextBudgetTooSmall, DeadlineExceeded, IntegrityViolation,
    InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)
from cragkit_langchain import create_tool

ROOT = next((parent for parent in Path(__file__).resolve().parents if (parent/'contracts/fixtures').is_dir()),Path.cwd())
FIXTURES = Path(os.environ.get('CRAGKIT_FIXTURES',str(ROOT/'contracts/fixtures')))
TOKENIZER = Path(os.environ.get('CRAGKIT_TOKENIZER',str(ROOT/'artifacts/tokenizers/cl100k_base.tiktoken')))
SCOPE = dict(tenant_id='tenant',principal_id='principal',authorization_revision='1',grant_ids=['grant'])
TEMPLATE = dict(collection='collection',required_filters=[dict(field='document_id',op='eq',value='document')],
    limits=dict(deadline_ms=1000,max_candidates=12,max_attempts=3,max_subqueries=3,max_provider_calls=8,max_context_tokens=20000),
    output_profile=dict(renderer='cragkit.context.v2',counting_mode='estimated',tokenizer=None,envelope_reserve_tokens=17))
ARGS = dict(request_id='request',query='ERR-17 café "quoted" 🙂',collection='collection')


def wire(value):
    return value.model_dump(mode='json') if hasattr(value,'model_dump') else deepcopy(value)


def result(request_id='request',status='partial',execution='complete'):
    text='ERR-17 café "quoted" 🙂'
    digest=sha256(text.encode()).hexdigest()
    evidence=dict(evidence_id='evidence',collection='collection',document_id='document',revision_id='revision',chunk_id='chunk',
        source_locator='synthetic:source',start_byte=0,end_byte=len(text.encode()),text=text,source_sha256=digest,text_sha256=digest)
    value=dict(request_id=request_id,status=status,execution=execution,evidence=[] if status=='insufficient' else [evidence],
        limitations=[dict(code='degraded_search')] if execution=='degraded' else [],context='[]',
        usage=dict(attempt_count=1,provider_calls=0,provider_input_tokens=0,provider_output_tokens=0,cost_usd=0,cost_kind='known',context_tokens=1,context_counting='estimated'))
    if status=='sufficient':
        value['facets']=[dict(facet_id='facet',question='What applies?',state='supported',evidence_ids=['evidence'],assessment_method='fixture',assessment_version='1')]
        value['versions']=dict(policy='reviewed.fixture.v1')
    return RetrievalResult.model_validate(value).model_dump(mode='json')


class Engine:
    def __init__(self,status='partial',execution='complete'):
        self.calls=[]
        self.status,self.execution=status,execution
    async def retrieve(self,request,*,scope,deadline):
        request,scope=wire(request),wire(scope)
        self.calls.append((request,scope,deadline))
        value=result(request['request_id'],self.status,self.execution)
        for item in value['evidence']:item['collection']=request['collection']
        return dict(result=value,diagnostics={'not_model_content':'private-canary'})


def serializer(value):
    if isinstance(value,ToolMessage):
        return json.dumps(dict(role='tool',name=value.name,tool_call_id=value.tool_call_id,content=value.content),ensure_ascii=False,separators=(',',':'))
    assert isinstance(value,str)
    return json.dumps(dict(role='tool',content=value),ensure_ascii=False,separators=(',',':'))


def tool(engine=None,**kwargs):
    return create_tool(engine or Engine(),template=deepcopy(TEMPLATE),scope=deepcopy(SCOPE),final_serializer=serializer,**kwargs)


def native(args=None,call_id='call-1'):
    return dict(type='tool_call',id=call_id,name='cragkit_retrieve',args=deepcopy(args or ARGS))


@pytest.mark.parametrize('status,execution',[('sufficient','complete'),('partial','complete'),('insufficient','complete'),('partial','degraded')])
def test_real_sdk_plain_and_native_results_preserve_citations_and_status(status,execution):
    async def scenario():
        engine=Engine(status,execution)
        target=tool(engine)
        assert isinstance(target,StructuredTool)
        assert set(target.args)=={'schema_version','request_id','query','collection','search_hints'}
        plain=await target.ainvoke(deepcopy(ARGS))
        message=await target.ainvoke(native(call_id='call-"escaped"-🙂'))
        assert type(plain) is str and isinstance(message,ToolMessage)
        assert message.tool_call_id=='call-"escaped"-🙂' and message.name=='cragkit_retrieve'
        assert json.loads(plain)==json.loads(message.content)==result('request',status,execution)
        assert 'private-canary' not in plain
        assert json.loads(await target.arun(deepcopy(ARGS)))==json.loads(plain)
        for request,scope,deadline in engine.calls:
            assert request['required_filters']==TEMPLATE['required_filters']
            assert request['limits']['max_provider_calls']==8 and request['limits']['max_candidates']==12
            assert request['output_profile']==TEMPLATE['output_profile']
            assert scope==SCOPE
            assert asyncio.get_running_loop().time()<deadline+1
    asyncio.run(scenario())


@pytest.mark.parametrize('field,value',[('scope',SCOPE),('tenant_id','forged'),('grant_ids',['admin']),('limits',{'max_provider_calls':1000}),('required_filters',[]),('output_profile',{'renderer':'forged'}),('collection','wrong')])
def test_forged_tool_authority_rejected_before_engine(field,value):
    async def scenario():
        engine=Engine();target=tool(engine);args={**ARGS,field:value}
        with pytest.raises(InvalidRequest) as error:
            await target.ainvoke(args)
        assert engine.calls==[] and ARGS['query'] not in str(error.value)
    asyncio.run(scenario())


@pytest.mark.parametrize('input_value',[None,[], 'ERR-17',{'query':'ERR-17','collection':'collection','search_hints':['hint']*9},
    {**ARGS,'query':' '},{**ARGS,'query':'bad\x00text'},{**native(),'name':'other'},
    {**native(),'id':''},{**native(),'scope':SCOPE},{**native(),'args':{**ARGS,'limits':{}}}])
def test_malformed_requests_and_native_envelopes_fail_closed(input_value):
    async def scenario():
        engine=Engine()
        with pytest.raises(InvalidRequest):await tool(engine).ainvoke(deepcopy(input_value))
        assert engine.calls==[]
    asyncio.run(scenario())


@pytest.mark.parametrize('config',[{'callbacks':[]},{'callbacks':[object()]},{'tags':['secret']},{'metadata':{'query':'secret'}},{'configurable':{'scope':SCOPE}},{'run_name':'unsafe'},{'recursion_limit':10}])
def test_caller_configuration_is_not_merged(config):
    async def scenario():
        engine=Engine();target=tool(engine)
        with pytest.raises(InvalidRequest):await target.ainvoke(deepcopy(ARGS),config=config)
        assert engine.calls==[]
        assert isinstance(await target.ainvoke(deepcopy(ARGS),config={}),str)
    asyncio.run(scenario())


@pytest.mark.parametrize('kwargs',[{'callbacks':[]},{'verbose':True},{'scope':SCOPE},{'tool_call_id':'forged'},{'config':{'metadata':{'query':'secret'}}}])
def test_arun_rejects_unguarded_sdk_options(kwargs):
    async def scenario():
        engine=Engine()
        with pytest.raises(InvalidRequest):await tool(engine).arun(deepcopy(ARGS),**kwargs)
        assert engine.calls==[]
    asyncio.run(scenario())


@pytest.mark.parametrize('failure',[ProviderUnavailable,UnauthorizedScope,IntegrityViolation,DeadlineExceeded])
def test_operational_errors_preserve_type(failure):
    class Failing(Engine):
        async def retrieve(self,*args,**kwargs):raise failure()
    async def scenario():
        with pytest.raises(failure):await tool(Failing()).ainvoke(deepcopy(ARGS))
    asyncio.run(scenario())


def test_invalid_engine_result_is_not_model_content():
    class Malformed(Engine):
        async def retrieve(self,*args,**kwargs):return {'result':{'request_id':'request','status':'sufficient','private':'secret'}}
    async def scenario():
        with pytest.raises(IntegrityViolation) as error:await tool(Malformed()).ainvoke(deepcopy(ARGS))
        assert 'secret' not in str(error.value)
    asyncio.run(scenario())


@pytest.fixture(scope='module')
def counter():
    return Cl100kCounter.from_file(TOKENIZER)


def strict_template(max_tokens=20000,reserve=17):
    value=deepcopy(TEMPLATE);value['limits']['max_context_tokens']=max_tokens
    value['output_profile'].update(counting_mode='strict',tokenizer='cl100k_base',envelope_reserve_tokens=reserve)
    return value


def test_strict_counter_and_tokenizer_required_before_engine():
    async def scenario():
        for options in ({},{'counter':object()}):
            engine=Engine()
            with pytest.raises(UnsupportedCapability):
                target=create_tool(engine,template=strict_template(),scope=SCOPE,final_serializer=serializer,**options)
                await target.ainvoke(deepcopy(ARGS))
            assert engine.calls==[]
    asyncio.run(scenario())


def test_final_sdk_object_is_counted_after_wrapper_with_real_id_and_reserve(counter):
    async def scenario():
        seen=[]
        def wrapped(value):
            seen.append(value)
            assert isinstance(value,ToolMessage) and value.tool_call_id=='actual-"id"-🙂'
            return serializer(value)+' padding'*500
        engine=Engine()
        target=create_tool(engine,template=strict_template(200,17),scope=SCOPE,final_serializer=wrapped,counter=counter)
        with pytest.raises(ContextBudgetTooSmall):await target.ainvoke(native(call_id='actual-"id"-🙂'))
        assert len(engine.calls)==1 and len(seen)==1
        accepted=create_tool(Engine(),template=strict_template(),scope=SCOPE,final_serializer=serializer,counter=counter)
        output=await accepted.ainvoke(native())
        assert isinstance(output,ToolMessage)
    asyncio.run(scenario())


def test_estimated_output_byte_ceiling_includes_final_wrapper():
    async def scenario():
        target=create_tool(Engine(),template=TEMPLATE,scope=SCOPE,final_serializer=lambda value:'🙂'*65537)
        with pytest.raises(ContextBudgetTooSmall):await target.ainvoke(native())
    asyncio.run(scenario())


@pytest.mark.parametrize('bad',[None,{},123,b'bytes'])
def test_nonstring_final_serializer_output_fails_closed(bad):
    async def scenario():
        target=create_tool(Engine(),template=TEMPLATE,scope=SCOPE,final_serializer=lambda value:bad)
        with pytest.raises(InvalidRequest):await target.ainvoke(deepcopy(ARGS))
    asyncio.run(scenario())


def test_factory_and_request_snapshots_and_concurrent_ids_are_isolated():
    async def scenario():
        entered=asyncio.Event();release=asyncio.Event();seen=[]
        class Concurrent(Engine):
            async def retrieve(self,request,*,scope,deadline):
                value=wire(request);seen.append((value,wire(scope)))
                if len(seen)==2:entered.set()
                await release.wait()
                return {'result':result(value['request_id'])}
        template=deepcopy(TEMPLATE);scope=deepcopy(SCOPE)
        target=create_tool(Concurrent(),template=template,scope=scope,final_serializer=serializer)
        template['limits']['max_provider_calls']=999;scope['tenant_id']='forged'
        first=native({**ARGS,'request_id':'first','query':'first'},'id-first')
        second=native({**ARGS,'request_id':'second','query':'second'},'id-second')
        tasks=[asyncio.create_task(target.ainvoke(first)),asyncio.create_task(target.ainvoke(second))]
        try:
            await asyncio.wait_for(entered.wait(),.5)
            first['args']['request_id']='mutated';second['id']='mutated'
            release.set();outputs=await asyncio.gather(*tasks)
            assert [(x.tool_call_id,json.loads(x.content)['request_id']) for x in outputs]==[('id-first','first'),('id-second','second')]
            assert {x[0]['query'] for x in seen}=={'first','second'}
            assert all(x[0]['limits']['max_provider_calls']==8 and x[1]['tenant_id']=='tenant' for x in seen)
        finally:
            release.set()
            for task in tasks:
                if not task.done():task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    asyncio.run(scenario())


def test_pre_dispatch_cancellation_never_calls_engine():
    async def scenario():
        engine=Engine();task=asyncio.create_task(tool(engine).ainvoke(deepcopy(ARGS)));task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert engine.calls==[]
    asyncio.run(scenario())


@pytest.mark.parametrize('termination',['cancel','deadline'])
def test_uncooperative_engine_cannot_delay_termination_or_leak_late_failure(termination):
    async def scenario():
        entered=asyncio.Event();release=asyncio.Event();finished=asyncio.Event();unhandled=[]
        loop=asyncio.get_running_loop();original_handler=loop.get_exception_handler()
        loop.set_exception_handler(lambda loop,context:unhandled.append(context))
        class IgnoresCancellation(Engine):
            async def retrieve(self,*args,**kwargs):
                entered.set()
                try:await release.wait()
                except asyncio.CancelledError:await release.wait()
                finally:finished.set()
                raise RuntimeError('late-private-canary')
        template=deepcopy(TEMPLATE);template['limits']['deadline_ms']=30 if termination=='deadline' else 1000
        target=create_tool(IgnoresCancellation(),template=template,scope=SCOPE,final_serializer=serializer)
        task=asyncio.create_task(target.ainvoke(deepcopy(ARGS)))
        try:
            await asyncio.wait_for(entered.wait(),.5)
            if termination=='cancel':task.cancel()
            with pytest.raises(asyncio.CancelledError if termination=='cancel' else DeadlineExceeded):
                await asyncio.wait_for(task,.25)
            release.set();await asyncio.wait_for(finished.wait(),.5)
            for _ in range(4):await asyncio.sleep(0)
            assert unhandled==[]
        finally:
            release.set()
            if not task.done():task.cancel()
            await asyncio.gather(task,return_exceptions=True)
            loop.set_exception_handler(original_handler)
    asyncio.run(scenario())


def test_alternate_sdk_paths_cannot_release_uncounted_content():
    async def scenario():
        engine=Engine();target=tool(engine)
        for name,args in [('invoke',(ARGS,)),('run',(ARGS,)),('_run',()),('batch',([ARGS],))]:
            with pytest.raises(UnsupportedCapability):getattr(target,name)(*args)
        with pytest.raises(UnsupportedCapability):await target._arun()
        with pytest.raises(UnsupportedCapability):await target.abatch([ARGS])
        for name,args in [('stream',(ARGS,)),('batch_as_completed',([ARGS],)),('transform',(iter([ARGS]),))]:
            with pytest.raises(UnsupportedCapability):list(getattr(target,name)(*args))
        with pytest.raises(UnsupportedCapability):
            async for _ in target.abatch_as_completed([ARGS]):pass
        for method in ('astream','astream_events','astream_log'):
            with pytest.raises(UnsupportedCapability):
                async for _ in getattr(target,method)(ARGS):pass
        for method in ('func','coroutine'):
            callback=getattr(target,method,None)
            if callback is not None:
                with pytest.raises(UnsupportedCapability):
                    value=callback(**ARGS)
                    if hasattr(value,'__await__'):await value
        assert engine.calls==[]
    asyncio.run(scenario())


def test_ambient_tracing_enabled_is_locally_disabled_without_network_or_secret_output(monkeypatch,capsys):
    attempts=[];secret='AD-r1-tracing-credential-canary'
    for name in ('LANGSMITH_TRACING','LANGCHAIN_TRACING_V2','LANGCHAIN_TRACING','LANGCHAIN_VERBOSE'):
        monkeypatch.setenv(name,'true')
    for name in ('LANGSMITH_API_KEY','LANGCHAIN_API_KEY'):monkeypatch.setenv(name,secret)
    def deny(*args,**kwargs):attempts.append('network');raise AssertionError('network denied')
    monkeypatch.setattr(socket.socket,'connect',deny)
    monkeypatch.setattr(socket,'getaddrinfo',deny)
    import httpx
    import requests
    monkeypatch.setattr(httpx.Client,'send',deny)
    monkeypatch.setattr(httpx.AsyncClient,'send',deny)
    monkeypatch.setattr(requests.Session,'request',deny)
    class Traced(Engine):
        async def retrieve(self,*args,**kwargs):
            assert get_tracing_context()['enabled'] is False
            return await super().retrieve(*args,**kwargs)
    async def scenario():
        with tracing_context(enabled=True):
            assert get_tracing_context()['enabled'] is True
            output=await tool(Traced()).ainvoke(native())
            assert get_tracing_context()['enabled'] is True
            assert secret not in serializer(output)
    asyncio.run(scenario())
    captured=capsys.readouterr()
    assert secret not in captured.out+captured.err and attempts==[]


SHARED_TOOL_CASES=[case for case in json.loads((FIXTURES/'requests.json').read_text())['cases'] if case['kind']=='tool']
@pytest.mark.parametrize('case',SHARED_TOOL_CASES,ids=lambda case:case['id'])
def test_shared_tool_contract_cases(case):
    async def scenario():
        engine=Engine();template=deepcopy(TEMPLATE)
        collection=case['input'].get('collection')
        if type(collection) is str and collection and '\x00' not in collection:
            template['collection']=collection
        target=create_tool(engine,template=template,scope=SCOPE,final_serializer=serializer)
        if case['valid']:
            output=await target.ainvoke(deepcopy(case['input']))
            assert json.loads(output)['request_id']==case['input']['request_id']
            assert len(engine.calls)==1
        else:
            with pytest.raises(InvalidRequest):await target.ainvoke(deepcopy(case['input']))
            assert engine.calls==[]
    asyncio.run(scenario())


def test_strict_guard_counts_exact_serializer_tokens_plus_bound_reserve(counter):
    async def scenario():
        representation='provider wrapper: '+('é "escaped" 🙂 '*20)
        tokens=counter.count(representation);reserve=17
        accepted=create_tool(Engine(),template=strict_template(tokens+reserve,reserve),scope=SCOPE,
            final_serializer=lambda actual:representation,counter=counter)
        assert isinstance(await accepted.ainvoke(native()),ToolMessage)
        rejected=create_tool(Engine(),template=strict_template(tokens+reserve-1,reserve),scope=SCOPE,
            final_serializer=lambda actual:representation,counter=counter)
        with pytest.raises(ContextBudgetTooSmall):await rejected.ainvoke(native())
    asyncio.run(scenario())


def test_engine_request_id_cannot_be_replaced():
    class WrongIdentity(Engine):
        async def retrieve(self,*args,**kwargs):return {'result':result('wrong-request')}
    async def scenario():
        with pytest.raises(IntegrityViolation):await tool(WrongIdentity()).ainvoke(deepcopy(ARGS))
    asyncio.run(scenario())


SHARED_RESULT_CASES=[case for case in json.loads((FIXTURES/'results.json').read_text())['cases'] if case['kind']=='result' and case['valid']]
@pytest.mark.parametrize('case',SHARED_RESULT_CASES,ids=lambda case:case['id'])
def test_shared_full_engine_results_equal_direct_validated_results(case):
    from cragkit.contracts import parse_result
    async def scenario():
        expected=parse_result(deepcopy(case['input'])).model_dump(mode='json')
        collection=expected['evidence'][0]['collection'] if expected['evidence'] else 'collection'
        template=deepcopy(TEMPLATE);template['collection']=collection
        template['limits'].update(max_context_tokens=1000000,max_provider_calls=1000,max_attempts=10)
        calls=[]
        class SharedResultEngine:
            async def retrieve(self,request,*,scope,deadline):
                calls.append(wire(request))
                return {'result':deepcopy(case['input']),'diagnostics':{'private_canary':'not_model_content'}}
        args=dict(request_id=expected['request_id'],query='shared engine fixture',collection=collection)
        target=create_tool(SharedResultEngine(),template=template,scope=SCOPE,final_serializer=serializer)
        plain=await target.ainvoke(args)
        message=await target.ainvoke(native(args,'shared-fixture-call'))
        assert json.loads(plain)==expected==json.loads(message.content)
        assert isinstance(message,ToolMessage) and message.tool_call_id=='shared-fixture-call'
        assert 'not_model_content' not in plain
        assert all(call['limits']['max_provider_calls']==1000 and call['required_filters']==template['required_filters'] for call in calls)
    asyncio.run(scenario())


def test_shared_corrective_targeted_recovery_matches_direct_core_and_keeps_constraints():
    from cragkit.contracts import parse_request,parse_scope
    from cragkit.corrective import CorrectiveRetriever
    from cragkit.planning import PlannerAdapter
    fixture=json.loads((FIXTURES/'corrective.json').read_text())
    case=next(case for case in fixture['cases'] if case['id']=='targeted-recovery')
    parsed=parse_request(fixture['request']);trusted=parse_scope(fixture['scope'])
    expected_request=parsed.model_dump(mode='json');expected_scope=trusted.model_dump(mode='json')
    class FixtureBackend:
        def __init__(self):self.searches=[];self.captures=[]
        async def search(self,request,*,scope,deadline,limit,ledger):
            snapshot=wire(request);self.searches.append(snapshot)
            assert wire(scope)==expected_scope
            assert {k:v for k,v in snapshot.items() if k!='query'}=={k:v for k,v in expected_request.items() if k!='query'}
            assert limit<=expected_request['limits']['max_candidates']
            index=len(self.searches)-1
            return {'candidates':[deepcopy(fixture['rows'][key]['candidate']) for key in case['searches'][index]['ids']],'degraded':False}
        async def capture(self,candidates,*,request,scope,deadline,max_source_bytes,ledger):
            assert wire(request)==expected_request and wire(scope)==expected_scope
            keys=[wire(candidate)['document_id'] for candidate in candidates]
            self.captures.append(keys)
            rows=[fixture['rows'][key] for key in keys]
            loaded=sum(len(row['source']['text'].encode()) for row in rows)
            assert loaded<=max_source_bytes
            return dict(evidence=[deepcopy(row['evidence']) for row in rows],sources=[deepcopy(row['source']) for row in rows],source_bytes=loaded,stale=False,budget_exhausted=False)
    async def plan(payload,*,deadline):
        assert payload['query']==fixture['request']['query'] and payload['missing_facets']==['second']
        return dict(plan={'queries':[{'facet_id':'second','variant_id':'v'}]},usage=dict(input_tokens=0,output_tokens=0,cost_usd=0))
    def engine(backend):
        return CorrectiveRetriever(backend,policy=fixture['policy'],variants=[dict(facet_id='second',variant_id='v',query=case['queries'][0])],planner=PlannerAdapter(plan,cost_upper_usd=0))
    async def scenario():
        direct_backend=FixtureBackend()
        direct=await engine(direct_backend).retrieve(parsed,scope=trusted,deadline=asyncio.get_running_loop().time()+2)
        tool_backend=FixtureBackend()
        template={key:deepcopy(value) for key,value in fixture['request'].items() if key in ('collection','required_filters','limits','output_profile')}
        target=create_tool(engine(tool_backend),template=template,scope=fixture['scope'],final_serializer=serializer)
        args={key:deepcopy(value) for key,value in fixture['request'].items() if key in ('schema_version','request_id','query','collection','search_hints')}
        output=await target.ainvoke(native(args,'corrective-fixture-call'))
        assert json.loads(output.content)==direct['result']
        assert direct['result']['status']==case['expected_status']=='sufficient'
        assert direct['diagnostics']['queries_executed']==2
        assert [item['document_id'] for item in json.loads(output.content)['evidence']]==['a','b']
        assert tool_backend.searches==direct_backend.searches
        assert tool_backend.captures==direct_backend.captures
        assert len(tool_backend.captures)>=2 and set(tool_backend.captures[-1])=={'a','b'}
        assert 'diagnostics' not in json.loads(output.content)
    asyncio.run(scenario())


@pytest.mark.parametrize('boundary',['engine','serializer'])
def test_arbitrary_private_exceptions_are_redacted(boundary):
    secret='private-credential-and-source-canary'
    class SecretFailure(Engine):
        async def retrieve(self,*args,**kwargs):raise RuntimeError(secret)
    def bad_serializer(actual):raise RuntimeError(secret)
    async def scenario():
        target=create_tool(SecretFailure() if boundary=='engine' else Engine(),template=TEMPLATE,scope=SCOPE,
            final_serializer=bad_serializer if boundary=='serializer' else serializer)
        with pytest.raises(ProviderUnavailable if boundary=='engine' else InvalidRequest) as error:
            await target.ainvoke(deepcopy(ARGS))
        assert secret not in str(error.value)
        assert error.value.__suppress_context__ is True
    asyncio.run(scenario())


def test_mutating_issued_counter_instance_method_cannot_bypass_strict_guard(counter,monkeypatch):
    calls=[]
    def forged_count(value):calls.append(value);return 0
    monkeypatch.setattr(counter,'count',forged_count)
    async def scenario():
        target=create_tool(Engine(),template=strict_template(200),scope=SCOPE,
            final_serializer=lambda actual:' padding'*500,counter=counter)
        with pytest.raises(ContextBudgetTooSmall):await target.ainvoke(native())
        assert calls==[]
    asyncio.run(scenario())
