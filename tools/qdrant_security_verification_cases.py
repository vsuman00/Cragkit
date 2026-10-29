"""Actual source/proof/security receipts; no recovery dispatch or settlement claim."""
from __future__ import annotations

from copy import deepcopy
from qdrant_writer_cases import writer_input, successor_stage
from qdrant_supervisor_cases import supervisor_input
from qdrant_recovery_cases import ERRORS as RECOVERY_ERRORS

ERRORS = RECOVERY_ERRORS | {'AbortError'}

CHECKS = (
    'actual_current_authority_two_generations_binds_historical_owner',
    'missing_or_stale_replicas_cannot_mint_security_receipt',
    'exact_current_readback_mints_same_session_receipt',
    'copied_wrong_issuer_and_wrong_facade_receipts_rejected',
    'subsequent_session_attempt_or_http_invalidates_receipt',
    'session_exit_expires_receipt_and_new_session_requires_fresh_readback',
    'superseding_source_authority_invalidates_receipt_projection',
    'tombstone_receipt_requires_exact_scoped_absence',
)


GUARD_CHECKS=(
 'guard_source_grant_refused_before_backend_binding',
 'guard_login_refused_before_backend_binding',
 'fifth_history_refused_before_backend_binding',
 'extra_definer_refused_before_backend_binding',
)

GRAPH_CHECKS=(
 'actual_guard_nonlocking_full_graph',
 'document_lock_wait_observed_until_guard_commit',
 'late_canonical_drift_refused',
 'late_vector_drift_refused',
 'late_manifest_drift_refused',
 'extra_raw_claim_refused',
 'post_wait_authority_mismatch_refused',
 'supervisor_connection_loss_releases_document_without_commit',
 'late_callback_retains_control_and_writer_until_drained',
)


SETTLEMENT_CHECKS=(
 'retired_unknown_settled_with_genuine_current_security_receipt',
 'lost_commit_confirmed_once_after_authority_advance_without_dml_retry',
 'fresh_repeat_preserves_historical_completion_and_returns_zero',
 'current_credential_unknown_preserves_rows_and_closed_admission',
)


class NativeSecurityVerificationFailure(RuntimeError):
    def __init__(self, observation):
        super().__init__('security_verification_native_case_failed')
        self.observation = observation


def security_verification_input():
    value = writer_input()
    value['collection_config'] = supervisor_input()['collection_config']
    value['second_stage'] = successor_stage(value,'security-receipt-second',None)
    initial = deepcopy(value['stage']['intent']['initial_authorization'])
    initial.update(authorization_revision='auth-2',principal_ids=[],grant_ids=[],language='de',tag='current-security')
    value['security'] = dict(action='update_authorization',intent_id='native-security-receipt-update',
        tenant_id=value['scope']['tenant_id'],collection=value['stage']['manifest']['collection'],
        document_id=value['stage']['manifest']['document_id'],expected_authorization_revision='auth-1',
        expected_mutation_epoch=1,authorization=initial)
    value['tombstone'] = dict(value['security'],action='tombstone',intent_id='native-security-receipt-tombstone',
        expected_authorization_revision='auth-2',expected_mutation_epoch=2,
        authorization=dict(initial,authorization_revision='auth-3',tombstoned=True))
    return value


async def python_security_verification_cases(value):
    import asyncio
    import hashlib
    import inspect
    import json
    import struct
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig,PoolResource,_owned_pool
    from cragkit._qdrant_writer import PostgresQdrantWriter,security_projection_data
    from cragkit._qdrant_writer_contract import prepare_stage
    from cragkit._qdrant_reconciliation import QdrantReconciliationVerifier
    from cragkit._qdrant_recovery import PostgresQdrantRecovery,validate_security_guarded,settle_security_guarded
    from cragkit._qdrant_supervisor import ManagedQdrantSupervisor
    from cragkit._qdrant_security_verification import QdrantSecurityVerifier,security_receipt_data
    from cragkit.errors import (InvalidRequest,IntegrityViolation,UnsupportedCapability,UnauthorizedScope,
                               ProviderUnavailable,DeadlineExceeded)
    from qdrant_supervisor_cases import plain,request_bytes,observed_listener

    inputs=value['inputs']
    def pool_config(raw):
        raw=dict(raw)
        for field in ('passfile','sslrootcert'):raw[field]=Path(raw[field])
        result=PoolConfig.model_validate(raw)
        if result.max_size!=1:raise RuntimeError('security_receipt_pool_bound')
        return result
    graph_mode='guard_graph_config' in value
    settlement_mode='settlement_config' in value
    settlement=dict(armed=False,fired=False,monitor=False,confirmations=0,confirmation_writes=0,
        confirmation_http=0,confirmation_guards=0,confirmation_writer_queries=0,confirmation_reads=0,
        attempted=[],updates=0,completion=None,advance=None)
    class SettlementConnection:
        def __init__(self,actual,role):self.actual,self.role,self.readonly,self.updated=actual,role,False,False
        def __getattr__(self,name):return getattr(self.actual,name)
        def transaction(self,*args,**kwargs):
            transaction=self.actual.transaction(*args,**kwargs);connection=self
            class Transaction:
                async def __aenter__(self):
                    connection.readonly=False;connection.updated=False
                    return await transaction.__aenter__()
                async def __aexit__(self,kind,error,traceback):
                    try:
                        result=await transaction.__aexit__(kind,error,traceback)
                        if kind is None and connection.role=='supervisor' and connection.updated and settlement['armed']:
                            settlement['armed']=False;settlement['fired']=True
                            await settlement['advance']()
                            settlement['monitor']=True
                            lost=ConnectionError('native_settlement_commit_reply_withheld');lost.sqlstate='08006'
                            raise lost
                        return result
                    finally:
                        if connection.readonly:settlement['monitor']=False
            return Transaction()
        async def execute(self,statement,params=None,**options):
            nonlocal guard_count
            sql=statement if type(statement) is str else ''
            if self.role=='supervisor' and "set_config('cragkit_qdrant.backend_instance_id'" in sql:guard_count+=1
            if settlement['monitor']:
                if self.role=='writer':settlement['confirmation_writer_queries']+=1
                if sql.startswith(('INSERT ','UPDATE ','DELETE ')):settlement['confirmation_writes']+=1
                if sql.startswith('SELECT true FROM cragkit_qdrant.lock_current_security('):settlement['confirmation_guards']+=1
            if self.role=='supervisor' and sql.endswith('READ COMMITTED READ ONLY'):
                self.readonly=True;settlement['confirmations']+=1
            if self.readonly and sql.startswith('SELECT dispatch_id,') and ' FROM cragkit_qdrant.dispatch_' in sql:
                if ('dispatch_id=ANY' not in sql or 'FOR UPDATE' in sql or 'FOR SHARE' in sql
                        or list(params[-1])!=settlement['attempted']):
                    raise RuntimeError('security_settlement_confirmation_not_exact')
                settlement['confirmation_reads']+=1
            if self.role=='supervisor' and sql.startswith('UPDATE cragkit_qdrant.dispatch_journal SET state=\'settled\''):
                self.updated=True;settlement['updates']+=1;settlement['completion']=params[0]
            return await self.actual.execute(statement,params,**options)
    class SettlementPool:
        def __init__(self,configuration,role):self.actual,self.role=_owned_pool(configuration),role
        def __getattr__(self,name):return getattr(self.actual,name)
        async def getconn(self,**options):return SettlementConnection(await self.actual.getconn(**options),self.role)
        async def putconn(self,connection):await self.actual.putconn(connection.actual)
    graph=dict(before=None,after=None,reply=None,contender_reply=None,active=False,reads=0,
               denied_commits=0,deny_commit=False,sup_pid=None,commits=0,tasks=[],gates=[])
    class GraphConnection:
        # ponytail: wrap the existing real pool; only controlled callback timing changes.
        def __init__(self,actual,role):self.actual,self.role,self.guarded,self.denied=actual,role,False,False
        def __getattr__(self,name):return getattr(self.actual,name)
        def transaction(self,*args,**kwargs):
            transaction=self.actual.transaction(*args,**kwargs);connection=self
            class Transaction:
                async def __aenter__(self):
                    connection.guarded=False;connection.denied=False
                    return await transaction.__aenter__()
                async def __aexit__(self,kind,error,traceback):
                    if connection.guarded and kind is None:
                        graph['commits']+=1
                        if connection.denied:graph['denied_commits']+=1
                    try:return await transaction.__aexit__(kind,error,traceback)
                    finally:
                        if connection.guarded:graph['active']=False
            return Transaction()
        async def execute(self,statement,params=None,**options):
            nonlocal guard_count
            sql=statement if type(statement) is str else ''
            if self.role=='supervisor' and "set_config('cragkit_qdrant.backend_instance_id'" in sql:guard_count+=1
            guard=self.role=='supervisor' and sql.startswith('SELECT true FROM cragkit_qdrant.lock_current_security(')
            if guard:
                self.guarded=True;self.denied=graph['deny_commit'];graph['active']=True;graph['sup_pid']=self.actual.info.backend_pid
                if graph['before'] is not None:await graph['before'](self)
            cursor=await self.actual.execute(statement,params,**options)
            if guard and graph['after'] is not None:await graph['after'](self)
            document=sql.startswith('SELECT active_generation_id,authorization_revision,mutation_epoch,principal_ids')
            if self.role=='writer' and document and graph['active']:
                if 'FOR UPDATE' in sql or 'FOR SHARE' in sql:raise RuntimeError('security_graph_document_lock')
                graph['reads']+=1
                if graph['reply'] is not None:await graph['reply'](self)
            if self.role=='contender' and document and 'FOR UPDATE' in sql and graph['contender_reply'] is not None:
                await graph['contender_reply'](self)
            return cursor
    class GraphPool:
        def __init__(self,configuration,role):self.actual,self.role=_owned_pool(configuration),role
        def __getattr__(self,name):return getattr(self.actual,name)
        async def getconn(self,**options):return GraphConnection(await self.actual.getconn(**options),self.role)
        async def putconn(self,connection):await self.actual.putconn(connection.actual)
    resource=PoolResource(pool_config(value['writer_config']),**({'factory':lambda cfg:GraphPool(cfg,'writer')} if graph_mode else
        {'factory':lambda cfg:SettlementPool(cfg,'writer')} if settlement_mode else {}))
    guard_mode='guard_operator_config' in value
    guard_count=0
    class GuardConnection:
        def __init__(self,actual):self.actual=actual
        def __getattr__(self,name):return getattr(self.actual,name)
        async def execute(self,statement,params=None,**options):
            nonlocal guard_count
            if type(statement) is str and "set_config('cragkit_qdrant.backend_instance_id'" in statement:guard_count+=1
            return await self.actual.execute(statement,params,**options)
    class GuardPool:
        def __init__(self,configuration):self.actual=_owned_pool(configuration)
        def __getattr__(self,name):return getattr(self.actual,name)
        async def getconn(self,**options):return GuardConnection(await self.actual.getconn(**options))
        async def putconn(self,connection):await self.actual.putconn(connection.actual)
    supervisor_resource=PoolResource(pool_config(value['supervisor_config']),
        **({'factory':lambda cfg:GraphPool(cfg,'supervisor')} if graph_mode else
           {'factory':lambda cfg:SettlementPool(cfg,'supervisor')} if settlement_mode else {'factory':GuardPool} if guard_mode else {}))
    operator=PoolResource(pool_config(value['guard_operator_config'])) if guard_mode else None
    guard_checks=[];guard_denied_queries=0;guard_restore=None
    graph_checks=[];admin=None;contender_resource=None;contender=None;graph_restore=None
    settlement_checks=[]
    supervisor=ManagedQdrantSupervisor(Path(value['binary']),Path(value['work_dir']),inputs['instance_id'],inputs['config'])
    writer=PostgresQdrantWriter(resource,inputs['config'],inputs['instance_id'])
    stage_verifier=QdrantReconciliationVerifier(writer,supervisor)
    recovery=PostgresQdrantRecovery(supervisor_resource,inputs['config'],supervisor,stage_verifier)
    verifier=QdrantSecurityVerifier(writer,supervisor)
    wrong_verifier=QdrantSecurityVerifier(writer,supervisor)
    original_http=supervisor._http
    if settlement_mode:
        async def observed_http(*args,**kwargs):
            if settlement['monitor']:settlement['confirmation_http']+=1
            return await original_http(*args,**kwargs)
        supervisor._http=observed_http
    deadline=asyncio.get_running_loop().time()+120
    checks=[]
    endpoint=primary=None
    target='/collections/'+inputs['config']['physical_collection']
    token='00000000-0000-4000-8000-000000000001'
    def ctx(intent,scope,owner=token):
        return dict(scope=scope,collection=inputs['security']['collection'],document_id=inputs['security']['document_id'],
            intent_id=intent,owner_token=owner)
    original_scope=inputs['scope']
    current_scope=dict(original_scope,authorization_revision='auth-2')
    owner=ctx(inputs['stage']['intent']['intent_id'],current_scope)
    security=ctx(inputs['security']['intent_id'],current_scope,'00000000-0000-4000-8000-000000000002')
    async def expect(kinds,operation):
        try:
            result=operation()
            if inspect.isawaitable(result):await result
        except kinds:return
        raise RuntimeError('security_receipt_expected_refusal_missing')
    async def provision(admin,probe):
        await admin.request('PUT',target,body=request_bytes(inputs['collection_config']),deadline=deadline)
        probe=plain(probe);path='/collections/'+probe['collection']
        await admin.request('PUT',path,body=request_bytes(probe['collection_config']),deadline=deadline)
        await admin.request('PUT',path+'/points?wait=true&ordering=strong',body=request_bytes(dict(points=[probe['point']])),deadline=deadline)
    async def mutate(handle,path,body,method='PUT'):
        response=json.loads(await handle.request(method,path,body=request_bytes(body),deadline=deadline))
        if response.get('status')!='ok' or response.get('result',{}).get('status')!='completed':
            raise RuntimeError('security_receipt_mutation_ack')
    def points(data):
        return [dict(id=point.point_id,payload=point.payload.model_dump(mode='json',exclude_none=True),
            vector=dict(dense=point.dense.values,sparse=dict(indices=point.sparse.indices,values=point.sparse.values)))
            for point in data['points']]
    def received(receipt,control):return security_receipt_data(receipt,verifier,control,deadline=deadline)
    def verify(proof,control,selected_owner=owner,selected_security=security):
        return verifier.verify(proof,control,selected_owner,selected_security,deadline=deadline)
    document_key=(inputs['security']['tenant_id'],inputs['security']['collection'],inputs['security']['document_id'])
    document_where='tenant_id=%s AND collection=%s AND document_id=%s'
    async def admin_query(sql,params=(),*,replica=False):
        async with admin.lease(deadline=deadline) as connection:
            async with connection.transaction():
                await connection.execute("SET LOCAL statement_timeout='5000ms'")
                if replica:await connection.execute('SET LOCAL session_replication_role=replica')
                cursor=await connection.execute(sql,params)
                return await cursor.fetchall() if cursor.description is not None else []
    async def observe(sql,params=(),*,source=False,pending=None):
        end=min(deadline,asyncio.get_running_loop().time()+3)
        while asyncio.get_running_loop().time()<end:
            if pending is not None and pending.done():raise RuntimeError('security_graph_wait_finished_early')
            selected=resource if source else admin
            async with selected.lease(deadline=end) as connection:
                async with connection.transaction(force_rollback=True):
                    rows=await (await connection.execute(sql,params)).fetchall()
            if rows==[(True,)]:return
            await asyncio.sleep(.02)
        raise RuntimeError('security_graph_wait_not_observed')
    def owned_task(operation):
        task=asyncio.create_task(operation);graph['tasks'].append(task);return task
    def owned_gate():
        gate=asyncio.Event();graph['gates'].append(gate);return gate
    async def guarded(selected_owner=owner,selected_security=security,*,limit=None):
        return await validate_security_guarded(recovery,verifier,proof,selected_owner,selected_security,
                                              deadline=deadline if limit is None else limit)
    async def live_graph_cases():
        nonlocal graph_restore
        before=graph['reads'];await guarded()
        if graph['reads']!=before+1:raise RuntimeError('security_graph_missing_nonlocking_read')
        graph_checks.append(GRAPH_CHECKS[0])
        waiter=None
        async def wait_document(connection):
            nonlocal waiter
            waiting=owned_gate();observed={}
            async def lock():
                async with admin.lease(deadline=deadline) as client:
                    async with client.transaction(force_rollback=True):
                        await client.execute("SET LOCAL lock_timeout='5000ms'")
                        observed['pid']=client.info.backend_pid;waiting.set()
                        await client.execute('SELECT document_id FROM cragkit_qdrant.documents WHERE '+document_where+' FOR UPDATE',document_key)
                        observed['acquired']=True
            waiter=owned_task(lock());await waiting.wait()
            await observe('SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=%s AND NOT granted '
                "AND locktype IN ('transactionid','tuple') AND %s=ANY(pg_blocking_pids(pid)))",
                (observed['pid'],graph['sup_pid']),source=True,pending=waiter)
            if observed.get('acquired'):raise RuntimeError('security_graph_lock_not_held')
        graph['after']=wait_document
        try:await guarded();await waiter
        finally:graph['after']=None
        graph_checks.append(GRAPH_CHECKS[1])
        canonical=(await admin_query('SELECT revision_id,canonical_utf8,source_sha256 FROM cragkit_qdrant.document_revisions WHERE '+document_where+' ORDER BY revision_id LIMIT 1',document_key))[0]
        replay=(await admin_query('SELECT revision_id,generation_id,chunk_id,dense_blob,dense_blob_sha256 FROM cragkit_qdrant.vector_replays WHERE '+document_where+' ORDER BY revision_id,generation_id,chunk_id LIMIT 1',document_key))[0]
        manifest=(await admin_query("SELECT intent_id,manifest_bytes,manifest_sha256 FROM cragkit_qdrant.publication_intents WHERE "+document_where+" AND action='stage' ORDER BY intent_id LIMIT 1",document_key))[0]
        import uuid
        orphan=str(uuid.uuid5(uuid.NAMESPACE_URL,'cragkit-security-graph-orphan'))
        corrupted=bytes(replay[3][:-8])+struct.pack('<d',.01)
        faults=(
            ('UPDATE cragkit_qdrant.document_revisions SET canonical_utf8=%s,source_sha256=%s WHERE '+document_where+' AND revision_id=%s',
             (bytes(canonical[1])+b' ',hashlib.sha256(bytes(canonical[1])+b' ').hexdigest(),*document_key,canonical[0]),
             (canonical[1],canonical[2],*document_key,canonical[0])),
            ('UPDATE cragkit_qdrant.vector_replays SET dense_blob=%s,dense_blob_sha256=%s WHERE '+document_where+' AND revision_id=%s AND generation_id=%s AND chunk_id=%s',
             (corrupted,hashlib.sha256(corrupted).hexdigest(),*document_key,*replay[:3]),
             (replay[3],replay[4],*document_key,*replay[:3])),
            ('UPDATE cragkit_qdrant.publication_intents SET manifest_bytes=%s,manifest_sha256=%s WHERE '+document_where+' AND intent_id=%s',
             (bytes(manifest[1])+b' ',hashlib.sha256(bytes(manifest[1])+b' ').hexdigest(),*document_key,manifest[0]),
             (manifest[1],manifest[2],*document_key,manifest[0])),
        )
        for index,(sql,changed,original) in enumerate(faults):
            async def inject(connection,sql=sql,changed=changed):await admin_query(sql,changed,replica=True)
            graph['after']=inject;graph['deny_commit']=True;graph_restore=(sql,original)
            try:await expect(IntegrityViolation,guarded)
            finally:
                graph['after']=None;await admin_query(sql,original,replica=True);graph_restore=None;graph['deny_commit']=False
            graph_checks.append(GRAPH_CHECKS[index+2])
        columns=('backend_namespace,physical_collection,collection_incarnation,point_id,instance_id,tenant_id,collection,document_id,'
            'revision_id,generation_id,chunk_id,source_sha256,text_sha256,start_byte,end_byte,dense_profile,sparse_profile,dense_input_sha256,sparse_input_sha256')
        insert='INSERT INTO cragkit_qdrant.point_claims('+columns+') SELECT backend_namespace,physical_collection,collection_incarnation,%s::uuid,instance_id,tenant_id,collection,document_id,'\
            'revision_id,generation_id,%s,source_sha256,text_sha256,start_byte,end_byte,dense_profile,sparse_profile,dense_input_sha256,sparse_input_sha256 FROM cragkit_qdrant.point_claims WHERE '+document_where+' LIMIT 1'
        undo='DELETE FROM cragkit_qdrant.point_claims WHERE '+document_where+' AND point_id=%s::uuid'
        async def inject_orphan(connection):await admin_query(insert,(orphan,'security-graph-extra-claim',*document_key),replica=True)
        graph['after']=inject_orphan;graph['deny_commit']=True;graph_restore=(undo,(*document_key,orphan))
        try:await expect(IntegrityViolation,guarded)
        finally:
            graph['after']=None;await admin_query(undo,(*document_key,orphan),replica=True);graph_restore=None;graph['deny_commit']=False
        graph_checks.append(GRAPH_CHECKS[5])
    async def late_graph_cases():
        nonlocal contender_resource,contender
        contender_resource=PoolResource(pool_config(value['writer_config']),factory=lambda cfg:GraphPool(cfg,'contender'))
        contender=PostgresQdrantWriter(contender_resource,inputs['config'],inputs['instance_id'])
        await contender_resource.open();await contender.initialize(deadline=deadline)
        async def advance(old,epoch,new):
            record=deepcopy(inputs['tombstone'])
            record.update(intent_id='native-security-graph-'+new,expected_authorization_revision=old,
                          expected_mutation_epoch=epoch)
            record['authorization'].update(authorization_revision=new,tag='guarded-graph-'+new,tombstoned=True)
            result=await contender.apply_security(record,dict(original_scope,authorization_revision=old),
                owner_token=security['owner_token'],deadline=deadline)
            if not result['authority_committed']:raise RuntimeError('security_graph_contender_not_committed')
            return ctx(record['intent_id'],dict(original_scope,authorization_revision=new),security['owner_token'])
        locked=owned_gate();release=owned_gate();observed={};authority_task=observer_task=None
        async def contender_locked(connection):
            observed['pid']=connection.actual.info.backend_pid;locked.set();await release.wait()
        async def before_guard(connection):
            nonlocal authority_task,observer_task
            authority_task=owned_task(advance('auth-3',3,'auth-4'))
            await asyncio.wait_for(locked.wait(),3)
            async def watch():
                await observe('SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=%s AND NOT granted '
                    "AND locktype IN ('transactionid','tuple') AND %s=ANY(pg_blocking_pids(pid)))",
                    (graph['sup_pid'],observed['pid']),pending=stale_task)
                observed['wait']=True;release.set()
            observer_task=owned_task(watch())
        graph['before']=before_guard;graph['contender_reply']=contender_locked;graph['deny_commit']=True
        before=graph['reads']
        old_owner=ctx(owner['intent_id'],dict(original_scope,authorization_revision='auth-3'))
        old_security=ctx(inputs['tombstone']['intent_id'],dict(original_scope,authorization_revision='auth-3'),security['owner_token'])
        stale_task=owned_task(guarded(old_owner,old_security))
        try:
            await expect(UnauthorizedScope,lambda:stale_task)
            await observer_task;next_security=await authority_task
            if not observed.get('wait') or graph['reads']!=before:raise RuntimeError('security_graph_stale_guard_ran_graph')
        finally:
            release.set();graph['before']=None;graph['contender_reply']=None;graph['deny_commit']=False
        graph_checks.append(GRAPH_CHECKS[6])
        entered=owned_gate();gate=owned_gate();waiter=owned_task(gate.wait())
        async def held_reply(connection):
            entered.set()
            while not gate.is_set():
                try:await asyncio.shield(waiter)
                except asyncio.CancelledError:pass
        graph['reply']=held_reply;graph['deny_commit']=True
        current_owner=ctx(owner['intent_id'],dict(original_scope,authorization_revision='auth-4'))
        loss_task=owned_task(guarded(current_owner,next_security,limit=min(deadline,asyncio.get_running_loop().time()+7)))
        try:
            await asyncio.wait_for(entered.wait(),5)
            actual_inner=recovery._active
            if actual_inner is None:raise RuntimeError('security_graph_missing_owned_callback')
            graph['tasks'].append(actual_inner)
            closing=owned_task(supervisor_resource.close())
            await observe('SELECT NOT EXISTS(SELECT 1 FROM pg_stat_activity WHERE pid=%s)',(graph['sup_pid'],))
            await advance('auth-4',4,'auth-5')
            await asyncio.gather(closing,return_exceptions=True)
            await expect((ProviderUnavailable,DeadlineExceeded,asyncio.CancelledError),
                lambda:asyncio.wait_for(asyncio.shield(loss_task),10))
            if gate.is_set() or recovery._active is not actual_inner or writer._active is not actual_inner:
                raise RuntimeError('security_graph_callback_ownership_lost')
            async def raw_control():
                async with supervisor.control_session():pass
            await expect(ProviderUnavailable,raw_control)
            await expect(ProviderUnavailable,lambda:writer.inspect(next_security,deadline=deadline))
            graph_checks.append(GRAPH_CHECKS[7])
            gate.set()
            done,pending=await asyncio.wait({actual_inner},timeout=5)
            if pending:raise RuntimeError('security_graph_callback_drain_failed')
            await asyncio.gather(*done,return_exceptions=True)
            if recovery._active is not None or writer._active is not None or graph['denied_commits']:
                raise RuntimeError('security_graph_late_commit_or_owner')
            async with supervisor.control_session():pass
            if (supervisor_resource._state!='closed' or not supervisor_resource._driver_closed
                    or not supervisor_resource._driver_close_ok or supervisor_resource._users or supervisor_resource._leases):
                raise RuntimeError('security_graph_fault_close_not_drained')
            graph['sup_close_verified']=True
            graph_checks.append(GRAPH_CHECKS[8])
        finally:gate.set();graph['reply']=None;graph['deny_commit']=False
    async def settlement_cases():
        advanced={}
        async def advance_authority():
            record=deepcopy(inputs['tombstone'])
            record.update(intent_id='native-security-settlement-auth-4',expected_authorization_revision='auth-3',expected_mutation_epoch=3)
            record['authorization'].update(authorization_revision='auth-4',tag='settlement-confirmation-authority',tombstoned=True)
            result=await writer.apply_security(record,dict(original_scope,authorization_revision='auth-3'),
                owner_token=security['owner_token'],deadline=deadline)
            if not result['authority_committed']:raise RuntimeError('security_settlement_authority_advance')
            advanced['security']=ctx(record['intent_id'],dict(original_scope,authorization_revision='auth-4'),security['owner_token'])
        columns=('dispatch_id,instance_id,sequence,owner_token::text,backend_epoch,credential_generation,operation,'
                 'recovery,request_sha256,created_xid::text,state,completion_sha256')
        async def headers():
            return await admin_query('SELECT '+columns+' FROM cragkit_qdrant.dispatch_journal WHERE '+document_where+
                ' AND intent_id=%s ORDER BY sequence',(*document_key,owner['intent_id']))
        original=await headers()
        if len(original)!=1 or original[0][10:]!=('unknown',None):raise RuntimeError('security_settlement_retired_fixture')
        settlement['advance']=advance_authority;settlement['armed']=True
        old_owner=ctx(owner['intent_id'],dict(original_scope,authorization_revision='auth-3'))
        old_security=ctx(inputs['tombstone']['intent_id'],dict(original_scope,authorization_revision='auth-3'),security['owner_token'])
        result=await settle_security_guarded(recovery,verifier,proof,old_owner,old_security,deadline=deadline)
        settled=await headers()
        if (dict(result)!=dict(settled_count=1) or len(settled)!=1 or settled[0][:10]!=original[0][:10]
                or settled[0][10:]!=('settled',settlement['completion']) or settlement['completion'] is None):
            raise RuntimeError('security_settlement_exact_terminal_row')
        settlement_checks.append(SETTLEMENT_CHECKS[0])
        if (not settlement['fired'] or settlement['confirmations']!=1 or settlement['confirmation_reads']!=2 or settlement['updates']!=1
                or settlement['confirmation_writes'] or settlement['confirmation_guards'] or settlement['confirmation_http']
                or settlement['confirmation_writer_queries']
                or await admin_query('SELECT authorization_revision,mutation_epoch FROM cragkit_qdrant.documents WHERE '+document_where,document_key)!=[('auth-4',4)]):
            raise RuntimeError('security_settlement_commit_confirmation')
        settlement_checks.append(SETTLEMENT_CHECKS[1])
        current_owner=ctx(owner['intent_id'],dict(original_scope,authorization_revision='auth-4'))
        repeat=await settle_security_guarded(recovery,verifier,proof,current_owner,advanced['security'],deadline=deadline)
        if dict(repeat)!=dict(settled_count=0) or await headers()!=settled or settlement['updates']!=1:
            raise RuntimeError('security_settlement_repeat_rewrote_history')
        settlement_checks.append(SETTLEMENT_CHECKS[2])
        physical=dict(supervisor.recovery_binding(proof))
        synthetic='native-security-current-credential-synthetic'
        request=b'{"synthetic_current_security_recovery_unknown":true}'
        async with supervisor_resource.lease(deadline=deadline) as connection:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                await connection.execute('SET LOCAL search_path=pg_catalog')
                await connection.execute("SELECT set_config('cragkit_qdrant.backend_instance_id',%s,true)",(inputs['instance_id'],))
                await connection.execute('INSERT INTO cragkit_qdrant.dispatch_journal '
                    '(tenant_id,collection,document_id,intent_id,dispatch_id,instance_id,sequence,owner_token,backend_epoch,'
                    'credential_generation,operation,recovery,request_bytes,request_sha256) '
                    'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (*document_key,owner['intent_id'],synthetic,inputs['instance_id'],2,token,physical['new_epoch'],
                     physical['credential_generation'],'complete_point_upsert',True,request,hashlib.sha256(request).hexdigest()))
                for point in data['point_ids']:
                    await connection.execute('INSERT INTO cragkit_qdrant.dispatch_points '
                        '(tenant_id,collection,document_id,intent_id,dispatch_id,backend_namespace,physical_collection,collection_incarnation,point_id) '
                        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)',(*document_key,owner['intent_id'],synthetic,
                        inputs['config']['backend_namespace'],inputs['config']['physical_collection'],inputs['config']['collection_incarnation'],point))
                await connection.execute("UPDATE cragkit_qdrant.dispatch_journal SET state='unknown' WHERE "+document_where+
                    ' AND intent_id=%s AND dispatch_id=%s',(*document_key,owner['intent_id'],synthetic))
                await connection.execute('SET CONSTRAINTS ALL IMMEDIATE')
        before=await headers()
        memberships=await admin_query('SELECT dispatch_id,point_id::text FROM cragkit_qdrant.dispatch_points WHERE '+document_where+
            ' AND intent_id=%s ORDER BY dispatch_id,point_id',(*document_key,owner['intent_id']))
        await expect(ProviderUnavailable,lambda:settle_security_guarded(recovery,verifier,proof,current_owner,advanced['security'],deadline=deadline))
        await expect(ProviderUnavailable,lambda:recovery.reopen(proof,deadline=deadline))
        after_members=await admin_query('SELECT dispatch_id,point_id::text FROM cragkit_qdrant.dispatch_points WHERE '+document_where+
            ' AND intent_id=%s ORDER BY dispatch_id,point_id',(*document_key,owner['intent_id']))
        if (await headers()!=before or memberships!=after_members or settlement['updates']!=1
                or await admin_query('SELECT state FROM cragkit_qdrant.backend_instances WHERE instance_id=%s',(inputs['instance_id'],))!=[('recovery_blocked',)]
                or await admin_query('SELECT state FROM cragkit_qdrant.publication_intents WHERE '+document_where+' AND intent_id=%s',
                    (*document_key,owner['intent_id']))!=[('denied',)]):
            raise RuntimeError('security_settlement_current_unknown_changed')
        settlement_checks.append(SETTLEMENT_CHECKS[3])
    try:
        await supervisor.initialize(deadline=deadline,provision=provision)
        endpoint=supervisor.identity()['endpoint'];await observed_listener(endpoint)
        await resource.open();await supervisor_resource.open()
        await recovery.initialize(deadline=deadline);await writer.initialize(deadline=deadline)
        for stage in (inputs['stage'],inputs['second_stage']):
            await writer.stage(prepare_stage(stage),original_scope,owner_token=token,deadline=deadline)
        await writer.admit_publication(ctx(inputs['stage']['intent']['intent_id'],original_scope),deadline=deadline)
        old_owner=dict((await writer.manager_snapshot(ctx(owner['intent_id'],original_scope),deadline=deadline))['owner'])
        if settlement_mode:
            old_dispatch='native-security-retired-unknown'
            settlement['attempted']=[old_dispatch]
            attempt=supervisor.issue_attempt(dict(intent_id=owner['intent_id'],owner_token=token,epoch=1,dispatch_id=old_dispatch),deadline=deadline)
            await writer.reserve_dispatch(ctx(owner['intent_id'],original_scope),dict(dispatch_id=old_dispatch,sequence=1,
                credential_generation=supervisor.attempt_binding(attempt)['credential_generation'],operation='complete_point_upsert',
                point_ids=[point['id'] for point in inputs['expected_points']]),deadline=deadline)
            await writer.mark_dispatched(ctx(owner['intent_id'],original_scope),old_dispatch,deadline=deadline)
            # Synthetic unknown-effect metadata: no old HTTP acknowledgment is invented.
            await writer.mark_unknown(ctx(owner['intent_id'],original_scope),old_dispatch,deadline=deadline)
        result=await writer.apply_security(inputs['security'],original_scope,owner_token=security['owner_token'],deadline=deadline)
        if not result['authority_committed']:raise RuntimeError('security_receipt_authority_not_committed')
        if settlement_mode:
            denied=await writer.admit_publication(owner,deadline=deadline)
            if denied['intent']['state']!='denied':raise RuntimeError('security_settlement_original_stage_not_denied')
        projection=await writer.project_security(security,deadline=deadline)
        data=security_projection_data(projection,writer)
        snapshot=await writer.manager_snapshot(owner,deadline=deadline)
        if (len(data['point_ids'])!=4 or len(data['generations'])!=2 or snapshot['owner']!=old_owner
                or any(point.payload.authorization_revision!='auth-2' for point in data['points'])):
            raise RuntimeError('security_receipt_current_projection')
        checks.append(CHECKS[0])
        proof=await recovery.recover('security-receipt-native',deadline=deadline)
        if operator is not None:
            await operator.open()
            async def execute_guard(statement):
                async with operator.lease(deadline=deadline) as connection:
                    async with connection.transaction():await connection.execute(statement)
            mutations=(
                ('GRANT SELECT(canonical_utf8) ON cragkit_qdrant.document_revisions TO cragkit_qdrant_security_guard',
                 'REVOKE SELECT(canonical_utf8) ON cragkit_qdrant.document_revisions FROM cragkit_qdrant_security_guard'),
                ('ALTER ROLE cragkit_qdrant_security_guard LOGIN','ALTER ROLE cragkit_qdrant_security_guard NOLOGIN'),
                ("INSERT INTO cragkit_qdrant.schema_migrations(version,checksum_sha256) VALUES('9999_native_recovery_guard_probe',repeat('0',64))",
                 "DELETE FROM cragkit_qdrant.schema_migrations WHERE version='9999_native_recovery_guard_probe'"),
                ("CREATE FUNCTION cragkit_qdrant.native_recovery_guard_probe() RETURNS boolean LANGUAGE sql SECURITY DEFINER AS 'SELECT true'",
                 'DROP FUNCTION cragkit_qdrant.native_recovery_guard_probe()'),
            )
            for index,(apply,undo) in enumerate(mutations):
                await execute_guard(apply);guard_restore=undo;before=guard_count
                await expect(UnsupportedCapability,lambda:recovery.advance_owner(proof,owner,deadline=deadline))
                guard_denied_queries+=guard_count-before
                if guard_count!=before:raise RuntimeError('security_guard_drift_reached_backend_binding')
                await execute_guard(undo);guard_restore=None
                advanced=await recovery.advance_owner(proof,owner,deadline=deadline)
                if dict(advanced)!=dict(owner_token=token,backend_epoch=2):raise RuntimeError('security_guard_owner_advance')
                guard_checks.append(GUARD_CHECKS[index])
        if graph_mode or settlement_mode:
            if operator is None:raise RuntimeError('security_graph_requires_profile_four')
            await operator.close();operator=None
            selected=value['guard_graph_config'] if graph_mode else value['settlement_config']
            admin=PoolResource(pool_config(selected['admin_config']))
            await admin.open()
        async with supervisor.control_session() as control:
            await expect(IntegrityViolation,lambda:verify(proof,control))
            attempt=control.issue_recovery_attempt(proof,dict(intent_id=owner['intent_id'],owner_token=token,
                epoch=2,dispatch_id='security-receipt-fixture-mutations',recovery_id='security-receipt-native'),deadline=deadline)
            mutation=control.recovery_transport_for(attempt)
            current=points(data);stale=deepcopy(current)
            for point in stale:point['payload']['authorization_revision']='auth-1'
            await mutate(mutation,target+'/points?wait=true&ordering=strong',dict(points=stale))
            await expect(IntegrityViolation,lambda:verify(proof,control))
            checks.append(CHECKS[1])
            await mutate(mutation,target+'/points?wait=true&ordering=strong',dict(points=current))
            receipt=await verify(proof,control);observed=received(receipt,control)
            expected_fields={'projection','owner_context','security_context','physical_binding','attempt_binding','activity',
                'intent_sha256','inventory_sha256','point_ids','readback_sha256','witness','encoded_bytes','sha256'}
            if (set(observed)!=expected_fields or tuple(observed['point_ids'])!=data['point_ids']
                    or observed['owner_context'].intent_id==observed['security_context'].intent_id
                    or observed['sha256']!=hashlib.sha256(observed['encoded_bytes']).hexdigest()
                    or observed['readback_sha256']!=observed['sha256']
                    or observed['witness'][0]!='cragkit.qdrant.security-readback.v1'):
                raise RuntimeError('security_receipt_bound_data')
            semantic_sha256=hashlib.sha256(json.dumps([observed['witness'][0],*observed['witness'][4:]],
                ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
            checks.append(CHECKS[2])
            for forged in ({},dict(observed)):
                await expect(InvalidRequest,lambda forged=forged:received(forged,control))
            await expect(InvalidRequest,lambda:security_receipt_data(receipt,wrong_verifier,control,deadline=deadline))
            await expect(InvalidRequest,lambda:received(receipt,{}))
            checks.append(CHECKS[3])
            await mutation.request('GET','/',deadline=deadline)
            await expect((InvalidRequest,UnsupportedCapability),lambda:received(receipt,control))
            receipt=await verify(proof,control)
            control.issue_recovery_attempt(proof,dict(intent_id=owner['intent_id'],owner_token=token,
                epoch=2,dispatch_id='security-receipt-later-attempt',recovery_id='security-receipt-native'),deadline=deadline)
            await expect((InvalidRequest,UnsupportedCapability),lambda:received(receipt,control))
            receipt=await verify(proof,control);received(receipt,control)
            await mutation.close()
            escaped_control=control
        await expect(InvalidRequest,lambda:received(receipt,escaped_control))
        checks.append(CHECKS[4])
        if graph_mode:await live_graph_cases()
        async with supervisor.control_session() as control:
            await expect((InvalidRequest,UnsupportedCapability),lambda:received(receipt,control))
            fresh=await verify(proof,control);fresh_data=received(fresh,control)
            checks.append(CHECKS[5])
            tomb_scope=dict(current_scope,authorization_revision='auth-3')
            tomb_owner=ctx(owner['intent_id'],tomb_scope)
            tomb_security=ctx(inputs['tombstone']['intent_id'],tomb_scope,security['owner_token'])
            result=await writer.apply_security(inputs['tombstone'],current_scope,
                owner_token=security['owner_token'],deadline=deadline)
            if not result['authority_committed']:raise RuntimeError('security_receipt_tombstone_not_committed')
            await expect(UnauthorizedScope,lambda:writer.validate_security_projection(fresh_data['projection'],deadline=deadline))
            checks.append(CHECKS[6])
            await expect(IntegrityViolation,lambda:verify(proof,control,tomb_owner,tomb_security))
            attempt=control.issue_recovery_attempt(proof,dict(intent_id=owner['intent_id'],owner_token=token,
                epoch=2,dispatch_id='security-receipt-fixture-delete',recovery_id='security-receipt-native'),deadline=deadline)
            deletion=control.recovery_transport_for(attempt)
            await mutate(deletion,target+'/points/delete?wait=true&ordering=strong',dict(points=data['point_ids']),method='POST')
            await deletion.close()
            final=received(await verify(proof,control,tomb_owner,tomb_security),control)
            if not security_projection_data(final['projection'],writer)['tombstoned']:
                raise RuntimeError('security_receipt_tombstone_projection')
            checks.append(CHECKS[7])
        if graph_mode:await late_graph_cases()
        if settlement_mode:await settlement_cases()
        result=dict(runtime='python',checks=checks,proof_scope='native_security_receipt_only',semantic_witness_sha256=semantic_sha256)
        if guard_mode:result['guard_admission']=dict(checks=guard_checks,denied_backend_queries=guard_denied_queries)
        if graph_mode:
            if graph_checks!=list(GRAPH_CHECKS) or graph['denied_commits']:
                raise RuntimeError('security_graph_case_scope')
            result['guarded_graph']=dict(checks=graph_checks,denied_commits=graph['denied_commits'])
        if settlement_mode:
            if settlement_checks!=list(SETTLEMENT_CHECKS):raise RuntimeError('security_settlement_case_scope')
            result['security_settlement']=dict(checks=settlement_checks,confirmation_writes=settlement['confirmation_writes'])
        return result
    except BaseException as error:
        primary=error
        name=type(error).__name__
        failure=NativeSecurityVerificationFailure(dict(ok=False,step=len(checks),error=name if name in ERRORS else 'internal'))
        failure.primary=error
        raise failure from None
    finally:
        if settlement_mode:supervisor._http=original_http
        failures=[]
        cleanup_deadline=asyncio.get_running_loop().time()+12
        if graph_mode:
            for gate in graph['gates']:gate.set()
            for task in graph['tasks']:
                if not task.done():task.cancel()
            if graph['tasks']:
                done,pending=await asyncio.wait(graph['tasks'],timeout=min(4,max(.001,cleanup_deadline-asyncio.get_running_loop().time())))
                await asyncio.gather(*done,return_exceptions=True)
                if pending:failures.append(dict(operation='guard_graph_drain',outcome='internal'))
            if graph_restore is not None and admin is not None:
                try:
                    async with asyncio.timeout_at(cleanup_deadline):
                        await admin_query(*graph_restore,replica=True)
                except BaseException as error:
                    failures.append(dict(operation='guard_graph_restore',outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if guard_restore is not None and operator is not None:
            try:
                async with asyncio.timeout_at(cleanup_deadline):
                    async with operator.lease(deadline=cleanup_deadline) as connection:
                        async with connection.transaction():await connection.execute(guard_restore)
            except BaseException as error:failures.append(dict(operation='catalog_restore',outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        for operation,close in ([('contender_writer_close',contender.close)] if contender is not None else [])+\
            ([('contender_pool_close',contender_resource.close)] if contender_resource is not None else [])+\
            ([('admin_pool_close',admin.close)] if admin is not None else [])+\
            ([('operator_pool_close',operator.close)] if operator is not None else [])+[('verifier_close',verifier.close),('wrong_verifier_close',wrong_verifier.close),
            ('recovery_close',recovery.close),('writer_close',writer.close),
            ('resource_close',resource.close),('supervisor_resource_close',supervisor_resource.close),('controller_close',supervisor.close)]:
            if operation=='supervisor_resource_close' and graph_mode and graph.get('sup_close_verified'):
                if supervisor_resource._state=='closed' and supervisor_resource._driver_close_ok and not supervisor_resource._users and not supervisor_resource._leases:
                    continue
            try:await asyncio.wait_for(close(),min(8,max(.001,cleanup_deadline-asyncio.get_running_loop().time())))
            except BaseException as error:failures.append(dict(operation=operation,outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if endpoint is not None:
            try:await observed_listener(endpoint,allow_absent=True)
            except BaseException as error:failures.append(dict(operation='listener_close',outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if failures:
            name=type(primary).__name__ if primary is not None else None
            raise NativeSecurityVerificationFailure(dict(ok=False,step=len(checks),error='cleanup_failed',
                primary=name if name in ERRORS else 'internal' if primary is not None else None,cleanup=failures)) from None
