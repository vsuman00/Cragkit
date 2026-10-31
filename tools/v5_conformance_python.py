"""Native direct/LangChain/MCP conformance over disposable backend profiles."""
import asyncio
from contextlib import asynccontextmanager,suppress
from pathlib import Path
import json

CHECKS=('common_native_data_ready','postgres_routes_match','qdrant_routes_match',
        'source_identity_status_match','provider_budget_difference_explicit',
        'partial_generation_never_released','forged_input_refused','owned_cleanup_verified')


async def run(value):
    import anyio
    from mcp import ClientSession
    from cragkit_langchain import create_tool
    from cragkit_mcp import create_server
    from cragkit._postgres_pool import PoolConfig,PoolResource
    from cragkit.contracts import Limits,parse_request,parse_scope
    from cragkit.corrective import CorrectiveRetriever
    from cragkit.postgres_corrective import PostgresCorrectiveBackend
    from cragkit.qdrant_corrective import QdrantCorrectiveBackend
    from cragkit.qdrant import QdrantSearchStore,HttpxQdrantTransport
    from cragkit.qdrant_source import PostgresQdrantSourceStore
    from cragkit.execution import ExecutionLedger
    from cragkit.errors import InvalidRequest,ProviderUnavailable
    from cragkit.qdrant_publication import (ManagedQdrantSupervisor,PostgresQdrantWriter,
        QdrantReconciliationVerifier,PostgresQdrantRecovery,PostgresQdrantPublicationAuthority,
        ManagedQdrantPublicationTransport,QdrantPublicationManager)
    from qdrant_supervisor_cases import plain,request_bytes,observed_listener
    from v5_conformance_fixture import cases
    inputs=value['inputs'];end=asyncio.get_running_loop().time()+120
    scope=parse_scope(inputs['scope']);objects=[];pools=[];address=None
    def pool(raw):
        raw=dict(raw)
        for key in ('sslrootcert','passfile'):raw[key]=Path(raw[key])
        config=PoolConfig.model_validate(raw)
        if config.max_size!=1:raise RuntimeError('conformance_pool_bound')
        item=PoolResource(config);pools.append(item);return item
    writer_pool=pool(value['writer_config']);supervisor_pool=pool(value['supervisor_config'])
    supervisor=ManagedQdrantSupervisor(Path(value['binary']),Path(value['work_dir']),inputs['instance_id'],inputs['config'])
    writer=PostgresQdrantWriter(writer_pool,inputs['config'],inputs['instance_id'])
    verifier=QdrantReconciliationVerifier(writer,supervisor)
    recovery=PostgresQdrantRecovery(supervisor_pool,inputs['config'],supervisor,verifier)
    authority=PostgresQdrantPublicationAuthority(writer,recovery)
    transport=ManagedQdrantPublicationTransport(supervisor)
    permitted={(stage['manifest']['tenant_id'],stage['manifest']['document_id']) for stage in (inputs['base'],inputs['foreign'])}
    async def authorize(selected,collection,document):return collection==inputs['base']['manifest']['collection'] and (selected.tenant_id,document) in permitted
    manager=QdrantPublicationManager(authority,transport,inputs['config'],supervisor,authorize)
    objects.extend((manager,transport,authority,recovery,verifier,writer))
    target='/collections/'+inputs['config']['physical_collection'];credential={}
    async def provision(admin,probe):
        await admin.request('PUT',target,body=request_bytes(inputs['collection_config']),deadline=end)
        probe=plain(probe);path='/collections/'+probe['collection']
        await admin.request('PUT',path,body=request_bytes(probe['collection_config']),deadline=end)
        await admin.request('PUT',path+'/points?wait=true&ordering=strong',body=request_bytes(dict(points=[probe['point']])),deadline=end)
    def ledger():return ExecutionLedger(Limits(deadline_ms=60000,max_provider_calls=0),deadline=end)
    reference=lambda stage:{key:stage['intent'][key] for key in ('collection','document_id','intent_id')}
    async def sink(raw):credential.update(raw)
    class Counter:
        name='fake-byte-v1'
        def count(self,text):return len(text.encode())
    async def embedding(body,**options):
        query=json.loads(body)['input'][0];index=1 if query=='pending' else 0
        vector=[0.]*1536;vector[index]=1.
        return json.dumps(dict(model=inputs['config']['dense_profile']['model'],data=[dict(index=0,embedding=vector)],
            usage=dict(prompt_tokens=len(query.encode()),total_tokens=len(query.encode())))).encode()
    @asynccontextmanager
    async def client_session(host):
        to_server,server_read=anyio.create_memory_object_stream(0);server_write,to_client=anyio.create_memory_object_stream(0)
        job=asyncio.create_task(host.run_streams(server_read,server_write))
        try:
            async with ClientSession(to_client,to_server) as client:
                await client.initialize();yield client
        finally:
            await to_server.aclose();await host.close()
            with suppress(asyncio.CancelledError):await job
            for stream in (to_client,server_read,server_write):await stream.aclose()
    observations=[];route_calls=0;checks=[]
    try:
        await supervisor.initialize(deadline=end,provision=provision);address=supervisor.identity()['endpoint']
        for item in (writer_pool,supervisor_pool):await item.open()
        await manager.initialize(deadline=end)
        for stage in (inputs['base'],inputs['foreign']):
            selected=parse_scope(dict(inputs['scope'],tenant_id=stage['manifest']['tenant_id']))
            await manager.stage(stage,selected,ledger(),deadline=end)
            if not (await manager.publish(reference(stage),selected,ledger(),deadline=end))['published']:raise RuntimeError('conformance_publication')
        await manager.stage(inputs['pending'],scope,ledger(),deadline=end)
        original_http=supervisor._http;partial_batches=[]
        async def partial_http(*args,**options):
            if args[1:3]==('PUT',target+'/points?wait=true&ordering=strong'):
                batch=json.loads(args[3])['points'];partial_batches.append([item['id'] for item in batch])
                if len(partial_batches)==2:raise ProviderUnavailable()
            return await original_http(*args,**options)
        supervisor._http=partial_http
        try:
            try:await manager.publish(reference(inputs['pending']),scope,ledger(),deadline=end)
            except ProviderUnavailable:pass
            else:raise RuntimeError('conformance_partial_write_not_interrupted')
        finally:supervisor._http=original_http
        if [len(batch) for batch in partial_batches]!=[8,1]:raise RuntimeError('conformance_partial_batches')
        context=dict(**reference(inputs['pending']),scope=scope,owner_token='00000000-0000-4000-8000-000000000087')
        snapshot=await writer.manager_snapshot(context,deadline=end)
        if not snapshot['pending'] or snapshot['document']['active_generation_id']!=inputs['base']['manifest']['generation_id']:
            raise RuntimeError('conformance_partial_publication')
        async with supervisor_pool.lease(deadline=end) as connection:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION READ ONLY')
                await connection.execute("SELECT set_config('cragkit_qdrant.backend_instance_id',%s,true)",(inputs['instance_id'],))
                cursor=await connection.execute('SELECT state,sequence::text FROM cragkit_qdrant.dispatch_journal WHERE instance_id=%s AND intent_id=%s ORDER BY sequence',
                    (inputs['instance_id'],inputs['pending']['intent']['intent_id']))
                if await cursor.fetchall()!=[('settled','1'),('unknown','2')]:raise RuntimeError('conformance_partial_journal')
        capability=supervisor.issue_attempt(dict(intent_id='conformance-fixture',owner_token='00000000-0000-4000-8000-000000000087',epoch=1,dispatch_id='conformance-fixture'),deadline=end)
        await supervisor.deliver_worker_credential(capability,sink,deadline=end)
        handle=supervisor.transport_for(capability)
        try:
            found=[]
            for batch in partial_batches:
                response=json.loads(await handle.request('POST',target+'/points',body=request_bytes(dict(ids=batch,with_payload=True,with_vector=True)),deadline=end))
                found.extend(response['result'])
            if len(found)!=8 or {item['id'] for item in found}!=set(partial_batches[0]):raise RuntimeError('conformance_partial_readback')
        finally:await handle.close()
        await writer_pool.close();await supervisor_pool.close()
        pg=pool(value['postgres_config']);reader=pool(value['reader_config'])
        await pg.open();await reader.open()
        candidate_transport=HttpxQdrantTransport(credential['endpoint'],api_key=credential['api_key'],allow_loopback_http=True)
        candidates=QdrantSearchStore(inputs['config'],candidate_transport);sources=PostgresQdrantSourceStore(reader,inputs['config'])
        objects.extend((candidate_transport,candidates,sources))
        await candidates.initialize(deadline=end);await sources.initialize(deadline=end)
        backends=dict(postgres_lexical=PostgresCorrectiveBackend(pg),qdrant_dense=QdrantCorrectiveBackend(candidates,sources,embedding_transport=embedding,token_counter=Counter()))
        checks.append(CHECKS[0])
        for profile,backend in backends.items():
            for case in cases(inputs):
                engine=CorrectiveRetriever(backend,policy=case['policy'],batch_size=1)
                parsed=parse_request(dict(case['template'],request_id=case['id'],query=case['query']))
                args=dict(request_id=case['id'],query=case['query'],collection=parsed.collection)
                direct=(await engine.retrieve(parsed,scope=scope,deadline=end))['result']
                tool=create_tool(engine,template=case['template'],scope=inputs['scope'],
                    final_serializer=lambda actual:json.dumps(dict(role='tool',content=actual),ensure_ascii=False,separators=(',',':')))
                wrapped=json.loads(await tool.ainvoke(args))
                if wrapped!=direct:raise RuntimeError('conformance_tool_result')
                host=create_server(engine,template=case['template'],scope=inputs['scope'],
                    final_serializer=lambda actual:json.dumps(dict(role='tool',result=actual.model_dump(mode='json',by_alias=True,exclude_unset=True)),ensure_ascii=False,separators=(',',':')))
                async with client_session(host) as client:
                    answer=await client.call_tool('cragkit_retrieve',args)
                    if answer.is_error or len(answer.content)!=1 or json.loads(answer.content[0].text)!=direct:raise RuntimeError('conformance_mcp_result')
                expected='insufficient' if profile=='qdrant_dense' and case['id']=='provider_budget' else case['expected_status']
                if direct['status']!=expected or direct['execution']!='complete':raise RuntimeError('conformance_status')
                if direct['usage']['provider_calls']!=(1 if profile=='qdrant_dense' and case['id']!='provider_budget' else 0):raise RuntimeError('conformance_usage')
                if direct['usage']['attempt_count']!=1:raise RuntimeError('conformance_attempt')
                if expected=='insufficient' and direct['evidence']:raise RuntimeError('conformance_unexpected_evidence')
                observations.append(dict(profile=profile,case=case['id'],result=direct));route_calls+=3
            checks.append(CHECKS[1 if profile=='postgres_lexical' else 2])
        by_key={(row['profile'],row['case']):row['result'] for row in observations}
        for case in cases(inputs):
            left=by_key['postgres_lexical',case['id']];right=by_key['qdrant_dense',case['id']]
            if case['id']=='provider_budget':continue
            for key in ('request_id','status','execution','evidence','context','facets','versions'):
                if left[key]!=right[key]:raise RuntimeError('conformance_backend_'+key)
        checks.extend(CHECKS[3:6])
        # Boundary tests use the real engines; forged fields must fail before any backend work.
        guard=CorrectiveRetriever(backends['qdrant_dense'],batch_size=1);template=cases(inputs)[0]['template']
        class Guard:
            calls=0
            async def retrieve(self,*args,**options):
                self.calls+=1
                return await guard.retrieve(*args,**options)
        observed=Guard()
        tool=create_tool(observed,template=template,scope=inputs['scope'],final_serializer=lambda actual:json.dumps(actual))
        for extra in ('scope','tenant_id','limits','required_filters'):
            try:await tool.ainvoke(dict(request_id='forged',query='café',collection=template['collection'],**{extra:{}}))
            except InvalidRequest:pass
            else:raise RuntimeError('conformance_forged_tool')
        host=create_server(observed,template=template,scope=inputs['scope'],
            final_serializer=lambda actual:json.dumps(actual.model_dump(mode='json',by_alias=True,exclude_unset=True)))
        async with client_session(host) as client:
            for extra in ('scope','tenant_id','limits','required_filters'):
                answer=await client.call_tool('cragkit_retrieve',dict(request_id='forged',query='café',collection=template['collection'],**{extra:{}}))
                if not answer.is_error or answer.content[0].text!='invalid_request':raise RuntimeError('conformance_forged_mcp')
        if observed.calls:raise RuntimeError('conformance_forged_engine_called')
        checks.append(CHECKS[6])
    finally:
        failures=[]
        for item in objects+pools+[supervisor]:
            close=getattr(item,'close',None)
            if callable(close):
                try:await asyncio.wait_for(close(),5)
                except BaseException:failures.append(type(item).__name__)
        if address is not None:await observed_listener(address,allow_absent=True)
        for item in pools:
            if item._state!='closed' or item._users or item._leases or not item._driver_close_ok:failures.append('pool_close_verification')
        if failures:raise RuntimeError('conformance_cleanup_failed')
    checks.append(CHECKS[7])
    return dict(runtime='python',checks=checks,route_calls=route_calls,boundary_refusals=8,observations=observations,cleanup_verified=True)


if __name__=='__main__':
    import sys,traceback
    value=json.loads(sys.stdin.buffer.read(1048577))
    try:print(json.dumps(asyncio.run(run(value)),ensure_ascii=False))
    except BaseException as error:
        locations=[dict(file=Path(frame.filename).name,line=frame.lineno) for frame in traceback.extract_tb(error.__traceback__)
            if '/tools/' in frame.filename or '/cragkit/' in frame.filename]
        print(json.dumps(dict(ok=False,error=type(error).__name__,locations=locations)))
        raise SystemExit(1)
