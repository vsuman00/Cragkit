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
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig,PoolResource
    from cragkit._qdrant_writer import PostgresQdrantWriter,security_projection_data
    from cragkit._qdrant_writer_contract import prepare_stage
    from cragkit._qdrant_reconciliation import QdrantReconciliationVerifier
    from cragkit._qdrant_recovery import PostgresQdrantRecovery
    from cragkit._qdrant_supervisor import ManagedQdrantSupervisor
    from cragkit._qdrant_security_verification import QdrantSecurityVerifier,security_receipt_data
    from cragkit.errors import InvalidRequest,IntegrityViolation,UnsupportedCapability,UnauthorizedScope
    from qdrant_supervisor_cases import plain,request_bytes,observed_listener

    inputs=value['inputs']
    def pool_config(raw):
        raw=dict(raw)
        for field in ('passfile','sslrootcert'):raw[field]=Path(raw[field])
        result=PoolConfig.model_validate(raw)
        if result.max_size!=1:raise RuntimeError('security_receipt_pool_bound')
        return result
    resource=PoolResource(pool_config(value['writer_config']))
    supervisor_resource=PoolResource(pool_config(value['supervisor_config']))
    supervisor=ManagedQdrantSupervisor(Path(value['binary']),Path(value['work_dir']),inputs['instance_id'],inputs['config'])
    writer=PostgresQdrantWriter(resource,inputs['config'],inputs['instance_id'])
    stage_verifier=QdrantReconciliationVerifier(writer,supervisor)
    recovery=PostgresQdrantRecovery(supervisor_resource,inputs['config'],supervisor,stage_verifier)
    verifier=QdrantSecurityVerifier(writer,supervisor)
    wrong_verifier=QdrantSecurityVerifier(writer,supervisor)
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
    try:
        await supervisor.initialize(deadline=deadline,provision=provision)
        endpoint=supervisor.identity()['endpoint'];await observed_listener(endpoint)
        await resource.open();await supervisor_resource.open()
        await recovery.initialize(deadline=deadline);await writer.initialize(deadline=deadline)
        for stage in (inputs['stage'],inputs['second_stage']):
            await writer.stage(prepare_stage(stage),original_scope,owner_token=token,deadline=deadline)
        await writer.admit_publication(ctx(inputs['stage']['intent']['intent_id'],original_scope),deadline=deadline)
        old_owner=dict((await writer.manager_snapshot(ctx(owner['intent_id'],original_scope),deadline=deadline))['owner'])
        result=await writer.apply_security(inputs['security'],original_scope,owner_token=security['owner_token'],deadline=deadline)
        if not result['authority_committed']:raise RuntimeError('security_receipt_authority_not_committed')
        projection=await writer.project_security(security,deadline=deadline)
        data=security_projection_data(projection,writer)
        snapshot=await writer.manager_snapshot(owner,deadline=deadline)
        if (len(data['point_ids'])!=4 or len(data['generations'])!=2 or snapshot['owner']!=old_owner
                or any(point.payload.authorization_revision!='auth-2' for point in data['points'])):
            raise RuntimeError('security_receipt_current_projection')
        checks.append(CHECKS[0])
        proof=await recovery.recover('security-receipt-native',deadline=deadline)
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
        return dict(runtime='python',checks=checks,proof_scope='native_security_receipt_only',semantic_witness_sha256=semantic_sha256)
    except BaseException as error:
        primary=error
        name=type(error).__name__
        raise NativeSecurityVerificationFailure(dict(ok=False,step=len(checks),error=name if name in ERRORS else 'internal')) from None
    finally:
        failures=[]
        cleanup_deadline=asyncio.get_running_loop().time()+12
        for operation,close in [('verifier_close',verifier.close),('wrong_verifier_close',wrong_verifier.close),
            ('recovery_close',recovery.close),('writer_close',writer.close),
            ('resource_close',resource.close),('supervisor_resource_close',supervisor_resource.close),('controller_close',supervisor.close)]:
            try:await asyncio.wait_for(close(),min(8,max(.001,cleanup_deadline-asyncio.get_running_loop().time())))
            except BaseException as error:failures.append(dict(operation=operation,outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if endpoint is not None:
            try:await observed_listener(endpoint,allow_absent=True)
            except BaseException as error:failures.append(dict(operation='listener_close',outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if failures:
            name=type(primary).__name__ if primary is not None else None
            raise NativeSecurityVerificationFailure(dict(ok=False,step=len(checks),error='cleanup_failed',
                primary=name if name in ERRORS else 'internal' if primary is not None else None,cleanup=failures)) from None
