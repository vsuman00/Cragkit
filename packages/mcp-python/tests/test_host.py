"""MT-r1 native host and pinned official SDK client checks; no live providers."""
import asyncio
from contextlib import asynccontextmanager, suppress
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import socket

import anyio
from mcp import ClientSession, types
import pytest

from cragkit.context import Cl100kCounter
from cragkit.contracts import RetrievalResult
from cragkit.errors import (ContextBudgetTooSmall, DeadlineExceeded, IntegrityViolation,
    InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)
from cragkit_mcp import create_server
from cragkit_mcp import _BoundedText, _SafeWrite
from mcp.shared.message import SessionMessage
from mcp.shared.exceptions import MCPError

ROOT = Path(__file__).resolve().parents[3]
SCOPE = dict(tenant_id='tenant', principal_id='principal', authorization_revision='1', grant_ids=['grant'])
TEMPLATE = dict(collection='collection', required_filters=[dict(field='document_id', op='eq', value='document')],
    limits=dict(deadline_ms=1000, max_candidates=12, max_attempts=3, max_subqueries=3, max_provider_calls=8, max_context_tokens=20000),
    output_profile=dict(renderer='cragkit.context.v2', counting_mode='estimated', tokenizer=None, envelope_reserve_tokens=17))
ARGS = dict(request_id='request', query='ERR-17 café "quoted" 🙂', collection='collection')


def result(request_id='request', status='partial', execution='complete'):
    text=ARGS['query']; digest=sha256(text.encode()).hexdigest()
    evidence=dict(evidence_id='evidence', collection='collection', document_id='document', revision_id='revision', chunk_id='chunk',
        source_locator='synthetic:source', start_byte=0, end_byte=len(text.encode()), text=text, source_sha256=digest, text_sha256=digest)
    value=dict(request_id=request_id, status=status, execution=execution, evidence=[] if status=='insufficient' else [evidence],
        limitations=[dict(code='degraded_search')] if execution=='degraded' else [], context='[]',
        usage=dict(attempt_count=1,provider_calls=0,provider_input_tokens=0,provider_output_tokens=0,cost_usd=0,cost_kind='known',context_tokens=1,context_counting='estimated'))
    if status=='sufficient':
        value['facets']=[dict(facet_id='facet',question='What applies?',state='supported',evidence_ids=['evidence'],assessment_method='fixture',assessment_version='1')]
        value['versions']=dict(policy='reviewed.fixture.v1')
    return RetrievalResult.model_validate(value).model_dump(mode='json')


class Engine:
    def __init__(self,status='partial',execution='complete',wrapped=True):
        self.calls=[]; self.status=status; self.execution=execution; self.wrapped=wrapped
    async def retrieve(self,request,*,scope,deadline):
        self.calls.append((request.model_dump(mode='json'),scope.model_dump(mode='json'),deadline))
        value=result(request.request_id,self.status,self.execution)
        return dict(result=value,diagnostics={'secret':'private-canary'}) if self.wrapped else RetrievalResult.model_validate(value)


def serializer(value):
    assert isinstance(value,types.CallToolResult)
    return json.dumps(dict(role='tool',result=value.model_dump(mode='json',by_alias=True,exclude_unset=True)),ensure_ascii=False,separators=(',',':'))


def host(engine=None,**kwargs):
    values=dict(template=deepcopy(TEMPLATE),scope=deepcopy(SCOPE),final_serializer=serializer)
    values.update(kwargs)
    return create_server(engine or Engine(),**values)


@asynccontextmanager
async def sdk_client(target):
    to_server,server_read=anyio.create_memory_object_stream(0)
    server_write,to_client=anyio.create_memory_object_stream(0)
    task=asyncio.create_task(target.run_streams(server_read,server_write))
    try:
        async with ClientSession(to_client,to_server) as client:
            await client.initialize()
            yield client
    finally:
        await to_server.aclose()
        await target.close()
        with suppress(asyncio.CancelledError):
            await task
        await to_client.aclose(); await server_read.aclose(); await server_write.aclose()


@pytest.mark.parametrize('status,execution',[('sufficient','complete'),('partial','complete'),('insufficient','complete'),('partial','degraded')])
@pytest.mark.parametrize('wrapped',[True,False])
def test_pinned_sdk_discovery_roundtrip_preserves_native_result(status,execution,wrapped):
    async def scenario():
        engine=Engine(status,execution,wrapped); target=host(engine)
        assert target.server.middleware==[] and not engine.calls
        async with sdk_client(target) as client:
            listing=await client.list_tools()
            assert [item.name for item in listing.tools]==['cragkit_retrieve']
            assert listing.tools[0].input_schema['additionalProperties'] is False
            assert set(listing.tools[0].input_schema['properties'])=={'schema_version','request_id','query','collection','search_hints'}
            answer=await client.call_tool('cragkit_retrieve',deepcopy(ARGS))
            assert answer.is_error is False and len(answer.content)==1
            assert json.loads(answer.content[0].text)==result('request',status,execution)
            assert 'private-canary' not in answer.model_dump_json()
        assert engine.calls[0][0]['required_filters']==TEMPLATE['required_filters']
        assert engine.calls[0][0]['limits']['max_candidates']==12 and engine.calls[0][1]==SCOPE
        await target.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('extra',[{'scope':SCOPE},{'tenant_id':'forged'},{'required_filters':[]},{'limits':{'max_candidates':1000}},
    {'output_profile':{}},{'collection':'wrong'},{'query':''},{'unknown':'credential-canary'}])
def test_sdk_rejects_forged_input_without_engine_call(extra):
    async def scenario():
        engine=Engine();target=host(engine)
        async with sdk_client(target) as client:
            answer=await client.call_tool('cragkit_retrieve',{**ARGS,**extra})
            assert answer.is_error and answer.content[0].text=='invalid_request'
            assert 'credential-canary' not in answer.model_dump_json() and not engine.calls
    asyncio.run(scenario())


def test_snapshots_binding_and_actual_wrapper_overflow():
    async def scenario():
        template=deepcopy(TEMPLATE);scope=deepcopy(SCOPE);engine=Engine();seen=[]
        def wrapped(actual):
            seen.append(actual)
            return serializer(actual)
        target=host(engine,template=template,scope=scope,final_serializer=wrapped)
        template['required_filters'].clear();scope['grant_ids'].append('forged')
        actual=await target.retrieve(ARGS)
        assert seen==[actual] and engine.calls[0][1]==SCOPE
        assert engine.calls[0][0]['required_filters']==TEMPLATE['required_filters']
        await target.close()
        target=host(final_serializer=lambda actual:'x'*262145)
        with pytest.raises(ContextBudgetTooSmall):await target.retrieve(ARGS)
        await target.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('error,code',[(UnauthorizedScope(),'unauthorized_scope'),(RuntimeError('SECRET password sql query'),'provider_unavailable')])
def test_expected_and_unexpected_errors_are_code_only(error,code):
    class Broken:
        async def retrieve(self,*args,**kwargs):raise error
    async def scenario():
        async with sdk_client(host(Broken())) as client:
            answer=await client.call_tool('cragkit_retrieve',ARGS)
            assert answer.is_error and answer.content[0].text==code
            assert 'SECRET' not in answer.model_dump_json()
    asyncio.run(scenario())


@pytest.mark.parametrize('mode',['bytes','tokens','exception'])
def test_error_wrapper_uses_same_ceiling_and_falls_back_to_sanitized_protocol_error(mode):
    class Broken:
        async def retrieve(self,*args,**kwargs):raise UnauthorizedScope()
    def oversized(actual):
        assert actual.is_error
        if mode=='exception':raise RuntimeError('SECRET serializer')
        return 'x'*(262145 if mode=='bytes' else 100000)
    async def scenario():
        async with sdk_client(host(Broken(),final_serializer=oversized)) as client:
            with pytest.raises(MCPError) as caught:await client.call_tool('cragkit_retrieve',ARGS)
            assert caught.value.code==-32603 and caught.value.message=='invalid_request'
            assert caught.value.data is None and 'SECRET' not in str(caught.value)
    asyncio.run(scenario())


def test_identity_and_serialization_failures():
    class Wrong:
        async def retrieve(self,*args,**kwargs):return result('different')
    async def scenario():
        target=host(Wrong())
        with pytest.raises(IntegrityViolation):await target.retrieve(ARGS)
        await target.close()
        target=host(final_serializer=lambda actual:None)
        with pytest.raises(InvalidRequest):await target.retrieve(ARGS)
        await target.close()
    asyncio.run(scenario())


def test_valid_native_result_content_limit_and_sdk_protocol_error_sanitization():
    class Large:
        async def retrieve(self,*args,**kwargs):return {**result(), 'context':'x'*262144}
    async def scenario():
        target=host(Large())
        with pytest.raises(ContextBudgetTooSmall):await target.retrieve(ARGS)
        await target.close()
        writer,reader=anyio.create_memory_object_stream(1)
        safe=_SafeWrite(writer)
        await safe.send(SessionMessage(types.JSONRPCError(jsonrpc='2.0',id=1,
            error=types.ErrorData(code=-32602,message='SECRET input',data={'query':'PRIVATE'}))))
        message=(await reader.receive()).message
        assert message.error.code==-32602 and message.error.message=='invalid_request'
        assert message.error.data is None and 'SECRET' not in message.model_dump_json()
        await safe.aclose();await reader.aclose()
    asyncio.run(scenario())


def test_actual_strict_counter_and_budget_uses_final_representation():
    async def scenario():
        counter=Cl100kCounter.from_file(ROOT/'artifacts/tokenizers/cl100k_base.tiktoken')
        template=deepcopy(TEMPLATE);template['output_profile'].update(counting_mode='strict',tokenizer='cl100k_base')
        captured=[]
        def wrapped(actual):
            text=serializer(actual);captured.append(text);return text
        target=host(template=template,counter=counter,final_serializer=wrapped)
        await target.retrieve(ARGS);await target.close()
        template['limits']['max_context_tokens']=counter.count(captured[0])+16
        target=host(template=template,counter=counter)
        with pytest.raises(ContextBudgetTooSmall):await target.retrieve(ARGS)
        await target.close()
        with pytest.raises(UnsupportedCapability):host(template=template)
    asyncio.run(scenario())


@pytest.mark.parametrize('stop',['deadline','cancel','close'])
def test_noncooperative_work_keeps_slot_until_drain_and_has_no_late_result(stop):
    async def scenario():
        started=asyncio.Event();release=asyncio.Event();cancelled=asyncio.Event();calls=[]
        class Slow:
            async def retrieve(self,request,**kwargs):
                calls.append(request);started.set()
                try:await release.wait()
                except asyncio.CancelledError:
                    cancelled.set();await release.wait()
                return result(request.request_id)
        template=deepcopy(TEMPLATE);template['limits']['deadline_ms']=10 if stop=='deadline' else 1000
        target=host(Slow(),template=template);pending=asyncio.create_task(target.retrieve(ARGS));await started.wait()
        if stop=='cancel':pending.cancel()
        if stop=='close':await target.close();await target.close()
        with pytest.raises(DeadlineExceeded if stop=='deadline' else asyncio.CancelledError):await pending
        await cancelled.wait()
        with pytest.raises(ProviderUnavailable):await target.retrieve(ARGS)
        assert len(calls)==1
        release.set();await asyncio.sleep(0);await asyncio.sleep(0)
        if stop!='close':assert (await target.retrieve(ARGS)).is_error is False
        await target.close()
    asyncio.run(scenario())


def test_competing_call_and_sdk_disconnect_abort_owned_work():
    async def scenario():
        started=asyncio.Event();cancelled=asyncio.Event()
        class Slow:
            async def retrieve(self,*args,**kwargs):
                started.set()
                try:await asyncio.Event().wait()
                finally:cancelled.set()
        target=host(Slow());pending=None
        async with sdk_client(target) as client:
            pending=asyncio.create_task(client.call_tool('cragkit_retrieve',ARGS))
            await started.wait()
            answer=await client.call_tool('cragkit_retrieve',ARGS)
            assert answer.is_error and answer.content[0].text=='provider_unavailable'
        await cancelled.wait()
        with suppress(BaseException):await pending
        await target.close()
    asyncio.run(scenario())


class Bytes:
    def __init__(self,chunks):self.chunks=iter(chunks)
    async def receive(self,size):return next(self.chunks,b'')


@pytest.mark.parametrize('chunks',[[b'x'*65536],[b'x'*40000,b'x'*25536],[b'\xff\n'],[b'{bad secret\n'],[b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'],[b'{}']])
def test_stdio_rejects_oversized_malformed_utf8_json_and_incomplete_frames(chunks):
    async def scenario():
        with pytest.raises(InvalidRequest) as caught:await anext(_BoundedText(Bytes(chunks)))
        assert str(caught.value)=='Invalid retrieval request.'
    asyncio.run(scenario())


def test_bound_frame_accepts_fragmented_initialize_and_blocks_network(monkeypatch):
    async def scenario():
        frame=b'{"jsonrpc":"2.0","method":"initialize","id":1,"params":{}}\n'
        source=_BoundedText(Bytes([frame[:11],frame[11:]]))
        assert await anext(source)==frame.decode()
        with pytest.raises(StopAsyncIteration):await anext(source)
        def blocked(*args,**kwargs):raise AssertionError('Unsolicited network')
        monkeypatch.setattr(socket.socket,'connect',blocked)
        target=host();await target.retrieve(ARGS);await target.close()
    asyncio.run(scenario())
