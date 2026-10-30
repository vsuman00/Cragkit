"""Actual partial-stage recovery; all vectors and source spans are synthetic."""
from __future__ import annotations

from copy import deepcopy
from qdrant_recovery_cases import recovery_input
from qdrant_supervisor_cases import supervisor_input
from qdrant_writer_cases import successor_stage
from qdrant_repair_cases import ERRORS

CHECKS=(
    'partial_nine_point_write_preserves_previous_active',
    'callback_denial_after_reservation_preserves_gate_and_pointer',
    'recovery_sql_ack_loss_confirms_without_http_resend',
    'same_intent_nine_point_publication_with_one_attempt',
    'unknown_recovery_write_cannot_settle_current_credential',
    'actual_refence_rejects_old_key_and_resumes_without_duplicate_recovery_write',
    'corrupt_and_extra_members_rejected_before_recovery_write',
    'foreign_uncertainty_preserved_and_global_reopen_blocked',
)

class NativePartialRepairFailure(RuntimeError):
    def __init__(self,observation):
        super().__init__('partial_repair_native_case_failed')
        self.observation=observation


def partial_repair_input():
    from cragkit._qdrant_contract import point_id
    from cragkit._qdrant_manifest import encode_manifest
    from cragkit._qdrant_vectors import encode_dense,encode_sparse
    value=recovery_input()
    value['collection_config']=supervisor_input()['collection_config']
    previous=value['stage']['manifest']['generation_id']
    stages={}
    for name in ('partial','unknown','corrupt','foreign'):
        stage=successor_stage(value,'partial-repair-'+name,previous)
        manifest=stage['manifest']
        manifest['chunker_profile']='fixture-nine-shared-spans-v1'
        original=deepcopy(manifest['members'][0])
        manifest['members']=[];stage['dense_vectors']=[];stage['sparse_vectors']=[]
        for index in range(9):
            member=deepcopy(original)
            member['chunk_id']=f'fixture-part-{index:02d}'
            member['point_id']=point_id(['cragkit.qdrant.point.v1',manifest['backend_namespace'],
                manifest['physical_collection'],manifest['collection_incarnation'],manifest['tenant_id'],
                manifest['collection'],manifest['document_id'],manifest['revision_id'],manifest['generation_id'],
                member['chunk_id'],manifest['dense_profile']['profile_id'],manifest['sparse_profile']['profile_id']])
            dense=[0.0]*1536;dense[index]=1.0
            sparse=dict(indices=[index],values=[1.0])
            member['dense_input_sha256']=encode_dense(dense,manifest['dense_profile']).input_sha256
            member['sparse_input_sha256']=encode_sparse(sparse['indices'],sparse['values'],manifest['sparse_profile']).input_sha256
            manifest['members'].append(member);stage['dense_vectors'].append(dense);stage['sparse_vectors'].append(sparse)
        stage['intent']['manifest_sha256']=encode_manifest(manifest,stage['canonical_text']).sha256
        stages[name]=stage;previous=manifest['generation_id']
    value['stages']=stages
    return value


class _JournalAckConnection:
    """Withhold a real supervisor COMMIT reply, never the mutation itself."""
    def __init__(self,connection,observations):
        self.connection,self.observations=connection,observations
        self.phase=None
    def __getattr__(self,key):return getattr(self.connection,key)
    def transaction(self):
        owner,transaction=self,self.connection.transaction()
        class Transaction:
            async def __aenter__(self):
                owner.phase=None
                await transaction.__aenter__()
                return self
            async def __aexit__(self,kind,error,traceback):
                result=await transaction.__aexit__(kind,error,traceback)
                if kind is None:owner._withhold_commit_ack()
                return result
        return Transaction()
    def _withhold_commit_ack(self):
        if self.phase in self.observations['armed']:
            phase,self.phase=self.phase,None
            self.observations['armed'].remove(phase);self.observations['fired'].append(phase)
            raise ConnectionError('injected_native_recovery_commit_ack_loss')
    async def execute(self,statement,params=None,**options):
        text=statement if type(statement) is str else ''
        if text.startswith(('BEGIN','ROLLBACK')):self.phase=None
        if text.startswith('INSERT INTO cragkit_qdrant.dispatch_journal '):self.phase='reserve'
        elif text.startswith('UPDATE cragkit_qdrant.dispatch_journal SET state='):
            self.phase=next((value for value in (params or ()) if type(value) is str and value in ('dispatched','settled')),None)
        result=await self.connection.execute(statement,params,**options)
        if text=='COMMIT':self._withhold_commit_ack()
        return result


async def python_partial_repair_cases(value):
    import asyncio
    from contextlib import asynccontextmanager
    import json
    import os
    from pathlib import Path
    import stat
    import urllib.error
    import urllib.request
    from cragkit._postgres_pool import PoolConfig,PoolResource
    from cragkit.contracts import Limits,TrustedScope
    from cragkit.execution import ExecutionLedger
    from cragkit.errors import IntegrityViolation,ProviderUnavailable,UnauthorizedScope
    from cragkit.qdrant_publication import (ManagedQdrantSupervisor,PostgresQdrantWriter,
        PostgresQdrantRecovery,QdrantReconciliationVerifier,QdrantPublicationManager,
        PostgresQdrantPublicationAuthority,ManagedQdrantPublicationTransport)
    from qdrant_publication_manager_cases import _PreparationAckPool
    from qdrant_supervisor_cases import plain,request_bytes,observed_listener

    class AckPool(_PreparationAckPool):
        async def getconn(self,**options):return _JournalAckConnection(await self.pool.getconn(**options),self.observations)
    inputs=value['inputs']
    def config(raw):
        raw=dict(raw)
        for key in ('sslrootcert','passfile'):raw[key]=Path(raw[key])
        return PoolConfig.model_validate(raw)
    writer_config,supervisor_config=config(value['writer_config']),config(value['supervisor_config'])
    if writer_config.max_size!=1 or supervisor_config.max_size!=1:raise RuntimeError('partial_repair_two_clients')
    faults=dict(armed=set(),fired=[])
    resource=PoolResource(writer_config)
    supervisor_resource=PoolResource(supervisor_config,factory=lambda cfg:AckPool(cfg,faults))
    work=Path(value['work_dir'])
    supervisor=ManagedQdrantSupervisor(Path(value['binary']),work,inputs['instance_id'],inputs['config'])
    writer=PostgresQdrantWriter(resource,inputs['config'],inputs['instance_id'])
    verifier=QdrantReconciliationVerifier(writer,supervisor)
    recovery=PostgresQdrantRecovery(supervisor_resource,inputs['config'],supervisor,verifier)
    authority=PostgresQdrantPublicationAuthority(writer,recovery)
    transport=ManagedQdrantPublicationTransport(supervisor)
    scope=TrustedScope.model_validate(inputs['scope'])
    other_scope=TrustedScope.model_validate(inputs['second_scope'])
    deadline=asyncio.get_running_loop().time()+240
    checks,handles=[],[]
    mode=dict(drop_ordinary=False,drop_recovery=False,deny_reserved=False)
    network=dict(ordinary=0,recovery=0)
    recovery_members=[];ordinary_members=[]
    captured=dict(proof=None,key=None)
    manager=endpoint=primary=None
    target='/collections/'+inputs['config']['physical_collection']
    def reference(stage):return {key:stage['intent'][key] for key in ('collection','document_id','intent_id')}
    def context(stage,selected_scope=scope,token='00000000-0000-4000-8000-000000000099'):
        return dict(scope=selected_scope,**reference(stage),owner_token=token)
    def book():return ExecutionLedger(Limits(deadline_ms=240000,max_attempts=1,max_provider_calls=0),deadline=deadline)
    async def snapshot(stage,selected_scope=scope):return await writer.manager_snapshot(context(stage,selected_scope),deadline=deadline)
    async def owned_context(stage,selected_scope=scope):
        state=await snapshot(stage,selected_scope)
        return context(stage,selected_scope,state['owner']['owner_token'])
    def usage(ledger):
        actual=ledger.snapshot()
        if (actual['attempts'],actual['provider_calls'],actual['candidates'],actual['pending'])!=(1,0,0,0):
            raise RuntimeError('partial_repair_usage')
    async def repair(stage):
        ledger=book();result=await manager.repair(reference(stage),scope,ledger,deadline=deadline);usage(ledger);return result
    async def expect(kind,operation):
        try:await operation()
        except kind:return
        raise RuntimeError('partial_repair_expected_refusal_missing')
    async def authorize(selected,collection,document):
        if mode['deny_reserved'] and selected==scope:
            state=await snapshot(inputs['stages']['partial'])
            if state['backend']['state']=='recovery_blocked' and state['max_sequence']>=2:return False
        return True
    def private_key():
        path=work/'config.yaml';info=path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1
                or stat.S_IMODE(info.st_mode)!=0o600 or not 1<=info.st_size<=65536):
            raise RuntimeError('partial_repair_private_config')
        key=json.loads(path.read_bytes())['service']['api_key']
        if type(key) is not str or len(key)!=64 or any(char not in '0123456789abcdef' for char in key):
            raise RuntimeError('partial_repair_private_key_shape')
        return key
    async def raw(method,path,body,key=None):
        selected=private_key() if key is None else key
        def request():
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            request=urllib.request.Request(endpoint+path,data=request_bytes(body),method=method,
                headers={'api-key':selected,'Content-Type':'application/json'})
            try:
                with opener.open(request,timeout=3) as response:
                    data=response.read(65537)
                    if len(data)>65536:raise RuntimeError('partial_repair_raw_response_bound')
                    return response.status
            except urllib.error.HTTPError as error:
                try:error.read(65537)
                finally:error.close()
                return error.code
        return await asyncio.wait_for(asyncio.to_thread(request),4)
    def stage_points(stage):
        manifest=stage['manifest'];result=[]
        for index,member in enumerate(manifest['members']):
            payload=deepcopy(inputs['expected_points'][0]['payload'])
            for key in ('backend_namespace','physical_collection','collection_incarnation','tenant_id','collection',
                        'document_id','revision_id','generation_id','source_sha256','dense_profile','sparse_profile'):
                payload[key]=deepcopy(manifest[key])
            for key in ('chunk_id','start_byte','end_byte','text_sha256'):payload[key]=member[key]
            result.append(dict(id=member['point_id'],payload=payload,
                vector=dict(dense=stage['dense_vectors'][index],sparse=stage['sparse_vectors'][index])))
        return sorted(result,key=lambda point:point['id'])
    class Handle:
        def __init__(self,actual,kind):self.actual,self.kind=actual,kind
        async def request(self,method,path,**options):
            mutation=method=='PUT' and '/points?' in path
            if mutation:
                network[self.kind]+=1
                if self.kind=='recovery':
                    recovery_members.append(sorted(point['id'] for point in json.loads(bytes(options['body']))['points']))
                else:
                    ordinary_members.append(sorted(point['id'] for point in json.loads(bytes(options['body']))['points']))
            response=await self.actual.request(method,path,**options)
            if mutation and mode['drop_'+self.kind]:
                completed=json.loads(bytes(response))
                if completed.get('status')!='ok' or completed.get('result',{}).get('status')!='completed':
                    raise RuntimeError('partial_repair_injected_ack_not_completed')
                mode['drop_'+self.kind]=False
                if self.kind=='recovery':captured['key']=private_key()
                raise ProviderUnavailable()
            return response
        async def close(self):await self.actual.close()
    async def lose_ordinary(stage,selected_scope=scope):
        await manager.stage(stage,selected_scope,book(),deadline=deadline)
        mode['drop_ordinary']=True
        await expect(ProviderUnavailable,lambda:manager.publish(reference(stage),selected_scope,book(),deadline=deadline))
        state=await snapshot(stage,selected_scope)
        if not state['pending'] or state['intent']['state']!='writing':raise RuntimeError('partial_repair_unknown_missing')
    async def provision(admin,probe):
        await admin.request('PUT',target,body=request_bytes(inputs['collection_config']),deadline=deadline)
        probe=plain(probe);path='/collections/'+probe['collection']
        await admin.request('PUT',path,body=request_bytes(probe['collection_config']),deadline=deadline)
        await admin.request('PUT',path+'/points?wait=true&ordering=strong',body=request_bytes(dict(points=[probe['point']])),deadline=deadline)
    try:
        await supervisor.initialize(deadline=deadline,provision=provision)
        endpoint=supervisor.identity()['endpoint'];await observed_listener(endpoint)
        original_transport=supervisor.transport_for
        def observed_transport(attempt,*,_control=None):
            actual=original_transport(attempt,_control=_control)
            if _control is not None:return actual
            handle=Handle(actual,'ordinary');handles.append(handle);return handle
        supervisor.transport_for=observed_transport
        original_control=supervisor.control_session
        class Control:
            def __init__(self,actual):self.actual=actual
            def __getattr__(self,name):return getattr(self.actual,name)
            def recovery_transport_for(self,attempt):
                handle=Handle(self.actual.recovery_transport_for(attempt),'recovery');handles.append(handle);return handle
        @asynccontextmanager
        async def observed_control():
            async with original_control() as control:yield Control(control)
        supervisor.control_session=observed_control
        original_recover=recovery.recover
        async def observed_recover(*args,**kwargs):
            proof=await original_recover(*args,**kwargs);captured['proof']=proof;return proof
        recovery.recover=observed_recover
        await resource.open();await supervisor_resource.open()
        manager=QdrantPublicationManager(authority,transport,inputs['config'],supervisor,authorize)
        await manager.initialize(deadline=deadline)
        base=inputs['stage'];partial,unknown,corrupt,foreign=[inputs['stages'][key] for key in ('partial','unknown','corrupt','foreign')]
        await manager.stage(base,scope,book(),deadline=deadline)
        await manager.publish(reference(base),scope,book(),deadline=deadline)
        ordinary_before_partial=network['ordinary']
        ordinary_batches_before_partial=len(ordinary_members)
        original_identity=(partial['intent']['intent_id'],partial['manifest']['revision_id'],partial['manifest']['generation_id'])
        point_ids=[point['id'] for point in stage_points(partial)]
        await lose_ordinary(partial)
        state=await snapshot(partial)
        original_seals=(state['intent']['payload_sha256'],state['intent']['manifest_sha256'])
        def same_stage_identity(state):
            return ((state['owner']['intent_id'],state['intent']['revision_id'],state['intent']['generation_id'])==original_identity
                and (state['intent']['payload_sha256'],state['intent']['manifest_sha256'])==original_seals)
        if (state['document']['active_generation_id']!=base['manifest']['generation_id']
                or not same_stage_identity(state) or len(point_ids)!=9 or len(set(point_ids))!=9
                or state['intent']['manifest_sha256']!=partial['intent']['manifest_sha256']
                or network['ordinary']!=ordinary_before_partial+1
                or ordinary_members[ordinary_batches_before_partial:]!=[point_ids[:8]]):raise RuntimeError('partial_repair_lost_prior')
        checks.append(CHECKS[0])
        faults['armed']={'reserve','dispatched','settled'}
        before=network['recovery'];mode['deny_reserved']=True
        await expect(UnauthorizedScope,lambda:repair(partial));mode['deny_reserved']=False
        state=await snapshot(partial)
        if (state['backend']['state']!='recovery_blocked' or network['recovery']!=before
                or state['document']['active_generation_id']!=base['manifest']['generation_id'] or not same_stage_identity(state)):
            raise RuntimeError('partial_repair_denial_did_not_preserve')
        checks.append(CHECKS[1])
        result=await repair(partial)
        if sorted(faults['fired'])!=['dispatched','reserve','settled'] or faults['armed'] or network['recovery']!=before+1 or recovery_members!=[[stage_points(partial)[-1]['id']]]:
            raise RuntimeError('partial_repair_sql_ack_replay')
        checks.append(CHECKS[2])
        state=await snapshot(partial)
        if (result['state']!='published'
                or (result['intent_id'],result['revision_id'],result['generation_id'])!=original_identity
                or not result['published'] or not result['replica_complete']
                or not same_stage_identity(state) or state['intent']['state']!='published' or not state['intent']['replica_complete']
                or state['document']['active_generation_id']!=original_identity[2]
                or state['pending'] or network['ordinary']!=ordinary_before_partial+3
                or ordinary_members[ordinary_batches_before_partial:]!=[point_ids[:8],point_ids[:8],point_ids[8:]]):
            raise RuntimeError('partial_repair_same_identity_failed')
        checks.append(CHECKS[3])
        await lose_ordinary(unknown);mode['drop_recovery']=True
        await expect(ProviderUnavailable,lambda:repair(unknown))
        state=await snapshot(unknown);epoch=state['backend']['epoch'];same_proof=captured['proof'];ctx=await owned_context(unknown)
        before=network['recovery']
        await expect(ProviderUnavailable,lambda:recovery.dispatch_stage_recovery(same_proof,ctx,authorize,deadline=deadline))
        receipt=await verifier.verify(same_proof,ctx,deadline=deadline)
        await expect(ProviderUnavailable,lambda:recovery.settle_retired(same_proof,receipt,deadline=deadline))
        if network['recovery']!=before or not (await snapshot(unknown))['pending']:raise RuntimeError('partial_repair_current_uncertainty_erased')
        checks.append(CHECKS[4])
        result=await repair(unknown)
        status=await raw('PUT',target+'/points?wait=true&ordering=strong',dict(points=[]),captured['key'])
        state=await snapshot(unknown)
        if (status!=401 or state['backend']['epoch']!=epoch or result['state']!='published'
                or network['recovery']!=before or state['pending']):raise RuntimeError('partial_repair_refence_failed')
        captured['key']=None;checks.append(CHECKS[5])
        await lose_ordinary(corrupt)
        point=stage_points(corrupt)[0];wrong=deepcopy(point);wrong['vector']['dense']=[-item for item in wrong['vector']['dense']]
        if await raw('PUT',target+'/points?wait=true&ordering=strong',dict(points=[wrong]))!=200:raise RuntimeError('partial_repair_fault_write')
        before=network['recovery'];await expect(IntegrityViolation,lambda:repair(corrupt))
        if network['recovery']!=before:raise RuntimeError('partial_repair_corruption_rewritten')
        extra=deepcopy(point);extra['id']='00000000-0000-4000-8000-000000000099'
        if await raw('PUT',target+'/points?wait=true&ordering=strong',dict(points=[point,extra]))!=200:raise RuntimeError('partial_repair_fault_restore')
        await expect(IntegrityViolation,lambda:repair(corrupt))
        if network['recovery']!=before:raise RuntimeError('partial_repair_extra_rewritten')
        if await raw('POST',target+'/points/delete?wait=true&ordering=strong',dict(points=[extra['id']]))!=200:raise RuntimeError('partial_repair_fault_remove')
        if (await repair(corrupt))['state']!='published':raise RuntimeError('partial_repair_fault_cleanup_resume')
        checks.append(CHECKS[6])
        await lose_ordinary(foreign)
        await lose_ordinary(inputs['second_stage'],other_scope)
        foreign_before=await snapshot(inputs['second_stage'],other_scope)
        await expect(ProviderUnavailable,lambda:repair(foreign))
        state=await snapshot(foreign);other=await snapshot(inputs['second_stage'],other_scope)
        if (state['backend']['state']!='recovery_blocked' or state['pending'] or not other['pending']
                or other['owner']!=foreign_before['owner']
                or state['document']['active_generation_id']!=corrupt['manifest']['generation_id']):raise RuntimeError('partial_repair_foreign_scope_touched')
        checks.append(CHECKS[7])
        return dict(runtime='python',checks=checks,proof_scope='native_partial_repair_only')
    except BaseException as error:
        primary=error
        import traceback,json
        locations=[]
        for frame in traceback.extract_tb(error.__traceback__):
            path=Path(frame.filename).resolve()
            try:relative=path.relative_to(Path(__file__).resolve().parents[1])
            except ValueError:continue
            if str(relative).startswith(('packages/python/src/','tools/')):locations.append(dict(path=str(relative),line=frame.lineno))
        (work.parent/'partial-failure-locations.json').write_text(json.dumps(locations)+'\n')
        name=type(error).__name__
        raise NativePartialRepairFailure(dict(ok=False,step=len(checks),error=name if name in ERRORS else 'internal')) from None
    finally:
        failures=[];cleanup_deadline=asyncio.get_running_loop().time()+15
        owned=([('manager_close',manager)] if manager is not None else [])+[('transport_close',handle) for handle in handles]
        owned += [('recovery_close',recovery),('writer_close',writer),('resource_close',resource),
            ('supervisor_resource_close',supervisor_resource),('controller_close',supervisor)]
        for operation,item in owned:
            try:await asyncio.wait_for(item.close(),max(.001,min(8,cleanup_deadline-asyncio.get_running_loop().time())))
            except BaseException as error:failures.append(dict(operation=operation,outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if endpoint is not None:
            try:await observed_listener(endpoint,allow_absent=True)
            except BaseException as error:failures.append(dict(operation='listener_close',outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if failures:
            name=type(primary).__name__ if primary is not None else None
            raise NativePartialRepairFailure(dict(ok=False,step=len(checks),error='cleanup_failed',
                primary=name if name in ERRORS else ('internal' if name else None),cleanup=failures)) from None
