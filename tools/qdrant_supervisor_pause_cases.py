"""Native supervisor process suspension with independent admission checks."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import sys

CHECKS = (
    'actual_capability_and_dispatch_before_pause',
    'supervisor_process_stopped_server_preserved',
    'competing_supervisor_refused_without_start',
    'independent_successor_owner_refused',
    'durable_uncertainty_and_pointer_preserved',
    'repeat_refusal_while_supervisor_stopped',
    'same_owner_resumed_for_verified_cleanup',
)
PROOF_SCOPE = 'native_supervisor_pause_blocks_only'


def configuration(raw):
    from cragkit._postgres_pool import PoolConfig
    value = dict(raw)
    for key in ('sslrootcert', 'passfile'): value[key] = Path(value[key])
    config = PoolConfig.model_validate(value)
    if config.max_size != 1: raise RuntimeError('pause_pool_bound')
    return config


async def child(value):
    from cragkit._postgres_pool import PoolResource
    from cragkit.contracts import Limits, TrustedScope
    from cragkit.execution import ExecutionLedger
    from cragkit.errors import ProviderUnavailable
    from cragkit.qdrant_publication import (ManagedQdrantSupervisor, PostgresQdrantWriter,
        QdrantReconciliationVerifier, PostgresQdrantRecovery, PostgresQdrantPublicationAuthority,
        ManagedQdrantPublicationTransport, QdrantPublicationManager, ManagedQdrantPublicationWorkerHost)
    from qdrant_supervisor_cases import plain, request_bytes, observed_listener
    inputs=value['inputs']; deadline=asyncio.get_running_loop().time()+120
    scope=TrustedScope.model_validate(inputs['scope'])
    writer_pool=PoolResource(configuration(value['writer_config']))
    supervisor_pool=PoolResource(configuration(value['supervisor_config']))
    supervisor=ManagedQdrantSupervisor(Path(value['binary']),Path(value['work_dir']),inputs['instance_id'],inputs['config'])
    writer=PostgresQdrantWriter(writer_pool,inputs['config'],inputs['instance_id'])
    verifier=QdrantReconciliationVerifier(writer,supervisor)
    recovery=PostgresQdrantRecovery(supervisor_pool,inputs['config'],supervisor,verifier)
    authority=PostgresQdrantPublicationAuthority(writer,recovery)
    transport=ManagedQdrantPublicationTransport(supervisor)
    async def authorize(selected,collection,document):
        return selected==scope and collection==inputs['stage']['manifest']['collection'] and document==inputs['stage']['manifest']['document_id']
    manager=QdrantPublicationManager(authority,transport,inputs['config'],supervisor,authorize)
    host=ManagedQdrantPublicationWorkerHost(supervisor,authorize)
    endpoint=None
    def ledger(): return ExecutionLedger(Limits(deadline_ms=60000,max_provider_calls=0),deadline=deadline)
    async def provision(admin,probe):
        target='/collections/'+inputs['config']['physical_collection']
        await admin.request('PUT',target,body=request_bytes(inputs['collection_config']),deadline=deadline)
        probe=plain(probe); target='/collections/'+probe['collection']
        await admin.request('PUT',target,body=request_bytes(probe['collection_config']),deadline=deadline)
        await admin.request('PUT',target+'/points?wait=true&ordering=strong',body=request_bytes(dict(points=[probe['point']])),deadline=deadline)
    try:
        await supervisor.initialize(deadline=deadline,provision=provision)
        endpoint=supervisor.identity()['endpoint']
        await writer_pool.open()
        await supervisor_pool.open()
        await manager.initialize(deadline=deadline)
        await manager.stage(inputs['stage'],scope,ledger(),deadline=deadline)
        reference=lambda stage:{key:stage['intent'][key] for key in ('collection','document_id','intent_id')}
        if not (await manager.publish(reference(inputs['stage']),scope,ledger(),deadline=deadline))['published']:
            raise RuntimeError('pause_baseline')
        for key in ('successor','competing_successor'):
            await manager.stage(inputs[key],scope,ledger(),deadline=deadline)
        # Stage setup no longer needs SQL connections while the worker runs.
        await writer_pool.close(); await supervisor_pool.close()
        async def observe(event,worker):
            if event['kind']!='before_write': return
            print(json.dumps(dict(kind='barrier',endpoint=endpoint,server_pid=supervisor._process.pid,
                dispatch_id=event['dispatch_id'],request_sha256=event['request_sha256'])),flush=True)
            line=await asyncio.to_thread(sys.stdin.readline)
            if line.strip()!='cleanup': raise RuntimeError('pause_child_command')
            await worker.terminate(deadline=asyncio.get_running_loop().time()+5)
            raise ProviderUnavailable()
        job=dict(writer_pool=value['writer_config'],config=inputs['config'],scope=inputs['scope'],
            reference=reference(inputs['successor']),limits=Limits(deadline_ms=60000,max_provider_calls=0).model_dump(mode='json'))
        try: await host.publish(job,ledger(),deadline=deadline,observer=observe)
        except ProviderUnavailable: pass
        else: raise RuntimeError('pause_old_worker_published')
    finally:
        failures=[]
        for item in (host,manager,transport,authority,recovery,verifier,writer,writer_pool,supervisor_pool,supervisor):
            action=getattr(item,'close',None)
            if callable(action):
                try: await asyncio.wait_for(action(),5)
                except BaseException: failures.append(type(item).__name__)
        if endpoint is not None: await observed_listener(endpoint,allow_absent=True)
        if failures: raise RuntimeError('pause_child_cleanup_failed')
    print(json.dumps(dict(kind='cleaned')),flush=True)


async def python_supervisor_pause_cases(value):
    from cragkit._postgres_pool import PoolResource
    from cragkit.contracts import TrustedScope
    from cragkit.errors import ProviderUnavailable,UnsupportedCapability
    from cragkit.qdrant_publication import ManagedQdrantSupervisor,PostgresQdrantWriter
    from qdrant_supervisor_cases import observed_listener,plain,request_bytes
    from qdrant_publication_worker_cases import NativePublicationWorkerFailure,ERRORS
    checks=[]; rows=[]; inputs=value['inputs']; deadline=asyncio.get_running_loop().time()+145
    process=None; stopped=False; notice=None; primary=None
    resource=PoolResource(configuration(value['writer_config']))
    observer=PoolResource(configuration(value['observer_config']))
    writer=PostgresQdrantWriter(resource,inputs['config'],inputs['instance_id'])
    competitor=ManagedQdrantSupervisor(Path(value['binary']),Path(value['work_dir']),inputs['instance_id'],inputs['config'])
    scope=TrustedScope.model_validate(inputs['scope'])
    stage=inputs['competing_successor']
    context=dict(collection=stage['intent']['collection'],document_id=stage['intent']['document_id'],
        intent_id=stage['intent']['intent_id'],scope=scope,owner_token='00000000-0000-4000-8000-000000000090')
    async def query(sql,params=()):
        async with observer.lease(deadline=deadline) as connection:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION READ ONLY')
                return await (await connection.execute(sql,params)).fetchall()
    async def snapshot():
        return plain(await writer.manager_snapshot(context,deadline=deadline))
    async def process_state(pid):
        task=await asyncio.create_subprocess_exec('/bin/ps','-o','stat=','-p',str(pid),stdout=asyncio.subprocess.PIPE)
        output,_=await task.communicate(); return output.decode().strip()
    async def refuse_owner():
        try: await writer.acquire_owner(context,deadline=deadline)
        except ProviderUnavailable: return
        raise RuntimeError('pause_successor_admitted')
    try:
        process=await asyncio.create_subprocess_exec(sys.executable,str(Path(__file__).resolve()),'--child',
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,start_new_session=True)
        process.stdin.write(json.dumps(value).encode()+b'\n'); await process.stdin.drain()
        line=await asyncio.wait_for(process.stdout.readline(),30)
        notice=json.loads(line)
        if notice.get('kind')=='failed':
            (Path(value['work_dir']).parent/'pause-child-failure.json').write_text(json.dumps(notice)+'\n')
        if set(notice)!={'kind','endpoint','server_pid','dispatch_id','request_sha256'} or notice['kind']!='barrier':
            raise RuntimeError('pause_barrier_shape')
        await resource.open(); await observer.open(); await writer.initialize(deadline=deadline)
        before=await snapshot()
        async def journals():
            return await query('SELECT intent_id,dispatch_id,state,request_sha256 FROM cragkit_qdrant.dispatch_journal WHERE instance_id=%s ORDER BY intent_id,sequence',(inputs['instance_id'],))
        journal=await journals()
        matching=[row for row in journal if row[1]==notice['dispatch_id']]
        if len(matching)!=1 or matching[0][2:]!=('dispatched',notice['request_sha256']): raise RuntimeError('pause_dispatch')
        checks.append(CHECKS[0]);rows.append(['capability','dispatched',1])
        os.kill(process.pid,signal.SIGSTOP);stopped=True
        for _ in range(100):
            if 'T' in await process_state(process.pid): break
            await asyncio.sleep(.01)
        else: raise RuntimeError('pause_not_stopped')
        if await observed_listener(notice['endpoint'])!=notice['server_pid']:
            raise RuntimeError('pause_server_identity_changed')
        os.kill(notice['server_pid'],0)
        checks.append(CHECKS[1]);rows.append(['pause',True,True])
        provisioned=[]
        async def provision(*args): provisioned.append(True)
        try: await competitor.initialize(deadline=deadline,provision=provision)
        except (UnsupportedCapability,ProviderUnavailable): pass
        else: raise RuntimeError('pause_competitor_admitted')
        if provisioned: raise RuntimeError('pause_competitor_started')
        checks.append(CHECKS[2]);rows.append(['competitor','refused',0])
        await refuse_owner();checks.append(CHECKS[3]);rows.append(['successor','ProviderUnavailable',0])
        if await snapshot()!=before or await journals()!=journal: raise RuntimeError('pause_state_changed')
        checks.append(CHECKS[4]);rows.append(['preserved',True,True,True])
        for _ in range(2):
            if 'T' not in await process_state(process.pid): raise RuntimeError('pause_owner_resumed')
            await refuse_owner()
            if await snapshot()!=before or await journals()!=journal: raise RuntimeError('pause_repeat_changed')
        checks.append(CHECKS[5]);rows.append(['repeat',2,0])
        os.kill(process.pid,signal.SIGCONT);stopped=False
        process.stdin.write(b'cleanup\n');await process.stdin.drain()
        cleaned=json.loads(await asyncio.wait_for(process.stdout.readline(),20))
        await asyncio.wait_for(process.wait(),10)
        if cleaned!={'kind':'cleaned'} or process.returncode!=0 or await process.stderr.read(): raise RuntimeError('pause_child_cleanup')
        await observed_listener(notice['endpoint'],allow_absent=True)
        final=await snapshot()
        if final['document']['active_generation_id']!=inputs['stage']['manifest']['generation_id']: raise RuntimeError('pause_pointer')
        checks.append(CHECKS[6]);rows.append(['cleanup',True,True,True])
    except BaseException as error: primary=error
    finally:
        if process is not None and process.returncode is None:
            if stopped: os.kill(process.pid,signal.SIGCONT)
            try:
                process.stdin.write(b'cleanup\n');await process.stdin.drain()
                await asyncio.wait_for(process.wait(),15)
            except BaseException:
                process.kill();await process.wait()
        failures=[]
        for item in (competitor,writer,resource,observer):
            try: await asyncio.wait_for(item.close(),5)
            except BaseException: failures.append(type(item).__name__)
        for pool in (resource,observer):
            if pool._state!='closed' or pool._users or pool._leases or not pool._driver_close_ok:
                failures.append('pool_close_verification')
        if failures:
            raise NativePublicationWorkerFailure(dict(ok=False,step=len(checks),error='cleanup_failed',
                primary=type(primary).__name__ if type(primary).__name__ in ERRORS else 'internal' if primary else None,
                cleanup=[dict(operation='resource_close',outcome='internal')])) from None
    if primary is not None:
        name=type(primary).__name__
        failure=NativePublicationWorkerFailure(dict(ok=False,step=len(checks),error=name if name in ERRORS else 'internal'))
        failure.primary=primary;raise failure from None
    return dict(runtime='python',checks=checks,proof_scope=PROOF_SCOPE,
        public_results_sha256=hashlib.sha256(request_bytes(['cragkit.qdrant.supervisor-pause.v1',rows])).hexdigest())


if __name__=='__main__':
    try: asyncio.run(child(json.loads(sys.stdin.readline())))
    except BaseException as error:
        import traceback
        print(json.dumps(dict(kind='failed',error=type(error).__name__,locations=[dict(file=Path(frame.filename).name,line=frame.lineno)
            for frame in traceback.extract_tb(error.__traceback__) if '/tools/' in frame.filename or '/cragkit/' in frame.filename])),flush=True)
        raise SystemExit(1)
