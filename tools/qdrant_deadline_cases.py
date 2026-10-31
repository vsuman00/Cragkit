"""Native operation deadline with one independently delayed HTTP request."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path

CHECKS=(
    'admitted_same_request_before_deadline',
    'owner_authority_resource_closed',
    'deadline_expires_with_request_pending',
    'fresh_successor_refused_without_dispatch',
    'same_request_completes_without_settlement',
    'late_completion_still_blocks_successor',
    'managed_recovery_settles_before_publication',
)
PROOF_SCOPE='native_deadline_not_fencing_only'


async def python_deadline_cases(value):
    import httpx
    from cragkit._postgres_pool import PoolConfig,PoolResource
    from cragkit.contracts import Limits,TrustedScope
    from cragkit.execution import ExecutionLedger
    from cragkit.errors import ProviderUnavailable,DeadlineExceeded
    from cragkit.qdrant_publication import (ManagedQdrantSupervisor,PostgresQdrantWriter,
        QdrantReconciliationVerifier,PostgresQdrantRecovery,PostgresQdrantPublicationAuthority,
        ManagedQdrantPublicationTransport,QdrantPublicationManager)
    from qdrant_supervisor_cases import plain,request_bytes,observed_listener
    from qdrant_publication_worker_cases import NativePublicationWorkerFailure,ERRORS
    inputs=deepcopy(value['inputs']);base=inputs['stage'];old=inputs['successor'];next_stage=inputs['competing_successor']
    scope=TrustedScope.model_validate(inputs['scope']);end=asyncio.get_running_loop().time()+90
    def config(raw):
        raw=dict(raw)
        for key in ('sslrootcert','passfile'):raw[key]=Path(raw[key])
        result=PoolConfig.model_validate(raw)
        if result.max_size!=1:raise RuntimeError('deadline_pool_bound')
        return result
    pools=[PoolResource(config(value['writer_config'])) for _ in range(2)]
    supervisor_pool=PoolResource(config(value['supervisor_config']))
    observer=PoolResource(config(value['observer_config']))
    writers=[PostgresQdrantWriter(pool,inputs['config'],inputs['instance_id']) for pool in pools]
    supervisor=ManagedQdrantSupervisor(Path(value['binary']),Path(value['work_dir']),inputs['instance_id'],inputs['config'])
    objects=[];managers=[];checks=[];rows=[];entered=asyncio.Event();release=asyncio.Event()
    retained=None;publish=None;endpoint=None;primary=None;armed=False;captured=None
    original_http=supervisor._http
    target='/collections/'+inputs['config']['physical_collection']
    reference=lambda stage:{key:stage['intent'][key] for key in ('collection','document_id','intent_id')}
    def context(stage):return dict(**reference(stage),scope=scope,owner_token='00000000-0000-4000-8000-000000000088')
    async def authorize(selected,collection,document):
        return selected==scope and collection==base['manifest']['collection'] and document==base['manifest']['document_id']
    async def call(method,item,deadline=None):
        limit=end if deadline is None else deadline
        ledger=ExecutionLedger(Limits(deadline_ms=60000,max_provider_calls=0),deadline=limit)
        try:return plain(await method(item,scope,ledger,deadline=limit))
        finally:
            usage=ledger.snapshot()
            if (usage['attempts'],usage['provider_calls'],usage['pending'])!=(1,0,0):raise RuntimeError('deadline_usage')
    async def provision(admin,probe):
        await admin.request('PUT',target,body=request_bytes(inputs['collection_config']),deadline=end)
        probe=plain(probe);path='/collections/'+probe['collection']
        await admin.request('PUT',path,body=request_bytes(probe['collection_config']),deadline=end)
        await admin.request('PUT',path+'/points?wait=true&ordering=strong',body=request_bytes(dict(points=[probe['point']])),deadline=end)
    async def observed_http(*args,**kwargs):
        nonlocal armed,retained,captured
        if not armed or args[1:3]!=('PUT',target+'/points?wait=true&ordering=strong'):
            return await original_http(*args,**kwargs)
        armed=False;captured=args
        async def body():
            yield args[3][:-1]
            entered.set()
            await release.wait()
            yield args[3][-1:]
        async def delayed_request():
            async with httpx.AsyncClient(trust_env=False,timeout=20) as client:
                response=await client.put(endpoint+args[2],headers={'api-key':args[0],
                    'content-type':'application/json','content-length':str(len(args[3]))},content=body())
                if len(response.content)>65536:raise RuntimeError('deadline_response_bound')
                return response.status_code,response.content
        retained=asyncio.create_task(delayed_request())
        # The fixture owns delayed delivery independently of manager cancellation.
        # Product deadline behavior and acknowledgment handling remain unchanged.
        return await asyncio.shield(retained)
    async def snapshot(stage):return plain(await writers[1].manager_snapshot(context(stage),deadline=end))
    async def query(sql,params=()):
        async with observer.lease(deadline=end) as connection:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION READ ONLY')
                return await (await connection.execute(sql,params)).fetchall()
    async def journal():
        return await query('SELECT intent_id,dispatch_id,state,request_sha256,sequence FROM cragkit_qdrant.dispatch_journal WHERE instance_id=%s ORDER BY intent_id,sequence',(inputs['instance_id'],))
    async def refusal():
        try:await writers[1].acquire_owner(context(next_stage),deadline=end)
        except ProviderUnavailable:return
        raise RuntimeError('deadline_successor_admitted')
    async def read(ids):
        status,raw=await original_http(supervisor._key,'POST',target+'/points',request_bytes(dict(ids=ids,with_payload=True,with_vector=True)),end)
        if status!=200:raise RuntimeError('deadline_readback')
        return sorted(json.loads(raw)['result'],key=lambda point:point['id'])
    try:
        await supervisor.initialize(deadline=end,provision=provision);endpoint=supervisor.identity()['endpoint']
        for pool in pools+[supervisor_pool]:await pool.open()
        for writer in writers:
            verifier=QdrantReconciliationVerifier(writer,supervisor)
            recovery=PostgresQdrantRecovery(supervisor_pool,inputs['config'],supervisor,verifier)
            authority=PostgresQdrantPublicationAuthority(writer,recovery)
            transport=ManagedQdrantPublicationTransport(supervisor)
            manager=QdrantPublicationManager(authority,transport,inputs['config'],supervisor,authorize)
            objects.extend((manager,transport,authority,recovery,verifier));managers.append(manager)
            await manager.initialize(deadline=end)
        await call(managers[0].stage,base)
        if not (await call(managers[0].publish,reference(base)))['published']:raise RuntimeError('deadline_baseline')
        for stage in (old,next_stage):await call(managers[0].stage,stage)
        base_ids=[m['point_id'] for m in base['manifest']['members']];baseline=await read(base_ids)
        supervisor._http=observed_http;armed=True
        original_deadline=asyncio.get_running_loop().time()+5
        publish=asyncio.create_task(call(managers[0].publish,reference(old),original_deadline))
        await asyncio.wait_for(entered.wait(),4)
        if retained.done() or asyncio.get_running_loop().time()>=original_deadline:raise RuntimeError('deadline_request_not_pending')
        before=await snapshot(old)
        if not before['pending']:raise RuntimeError('deadline_dispatch_missing')
        checks.append(CHECKS[0]);rows.append(['request','dispatched',True])
        async with pools[0].lease(deadline=end) as connection:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION READ ONLY')
                owner_pid=(await (await connection.execute('SELECT pg_backend_pid()')).fetchall())[0][0]
        await pools[0].close();await observer.open()
        if await query('SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=%s)',(owner_pid,))!=[(False,)]:
            raise RuntimeError('deadline_authority_connection_alive')
        durable=await journal()
        dispatched=[row for row in durable if row[0]==old['intent']['intent_id']]
        if len(dispatched)!=1 or dispatched[0][2]!='dispatched' or dispatched[0][3]!=hashlib.sha256(captured[3]).hexdigest():
            raise RuntimeError('deadline_request_journal_binding')
        try:await writers[0].manager_snapshot(context(old),deadline=end)
        except ProviderUnavailable:pass
        else:raise RuntimeError('deadline_authority_reopened')
        checks.append(CHECKS[1]);rows.append(['authority','closed'])
        try:await publish
        except (DeadlineExceeded,ProviderUnavailable):pass
        else:raise RuntimeError('deadline_operation_succeeded')
        publish=None
        if asyncio.get_running_loop().time()<original_deadline or retained.done():raise RuntimeError('deadline_not_crossed')
        checks.append(CHECKS[2]);rows.append(['expiry',True,True])
        await refusal()
        if await snapshot(old)!=before or await journal()!=durable:raise RuntimeError('deadline_state_changed')
        checks.append(CHECKS[3]);rows.append(['successor','refused',0])
        release.set();status,raw=await asyncio.wait_for(retained,10)
        if status!=200 or json.loads(raw)['result']['status']!='completed':raise RuntimeError('deadline_late_completion')
        expected=json.loads(captured[3])['points'];actual=await read([point['id'] for point in expected])
        canonical=lambda points:sorted([{key:point[key] for key in ('id','payload','vector')} for point in points],key=lambda point:point['id'])
        if canonical(actual)!=canonical(expected):raise RuntimeError('deadline_late_readback')
        checks.append(CHECKS[4]);rows.append(['completion',200,True])
        await refusal()
        if await snapshot(old)!=before or await journal()!=durable:raise RuntimeError('deadline_completion_settled')
        checks.append(CHECKS[5]);rows.append(['uncertainty',True])
        supervisor._http=original_http
        result=await call(managers[1].repair,reference(old))
        final=await snapshot(old)
        if not result['published'] or final['pending'] or final['backend']['epoch']<=before['backend']['epoch']:
            raise RuntimeError('deadline_recovery_incomplete')
        status,_=await original_http(captured[0],'GET',target,None,end)
        if status!=401 or await read(base_ids)!=baseline:raise RuntimeError('deadline_fence_or_baseline')
        checks.append(CHECKS[6]);rows.append(['recovery',True,401,True])
    except BaseException as error:primary=error
    finally:
        release.set();supervisor._http=original_http
        failures=[]
        for task in (publish,retained):
            if task is not None and not task.done():task.cancel()
        try:await asyncio.wait_for(asyncio.gather(*[task for task in (publish,retained) if task is not None],return_exceptions=True),5)
        except BaseException:failures.append('request_drain')
        for item in objects+writers+pools+[supervisor_pool,observer,supervisor]:
            action=getattr(item,'close',None)
            if callable(action):
                try:await asyncio.wait_for(action(),5)
                except BaseException:failures.append(type(item).__name__)
        if endpoint is not None:await observed_listener(endpoint,allow_absent=True)
        for pool in pools+[supervisor_pool,observer]:
            if pool._state!='closed' or pool._users or pool._leases or not pool._driver_close_ok:failures.append('pool_close_verification')
        if failures:raise RuntimeError('deadline_cleanup_failed')
    if primary is not None:
        failure=NativePublicationWorkerFailure(dict(ok=False,step=len(checks),error=type(primary).__name__ if type(primary).__name__ in ERRORS else 'internal'))
        failure.primary=primary;raise failure from None
    return dict(runtime='python',checks=checks,proof_scope=PROOF_SCOPE,
        public_results_sha256=hashlib.sha256(request_bytes(['cragkit.qdrant.deadline.v1',rows])).hexdigest())
