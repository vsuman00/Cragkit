"""Native missing-only inspection and shared bytes; no receipt or SQL authority."""
from __future__ import annotations

CHECKS=(
    'missing_expected_ids_reported',
    'wrong_vectors_and_foreign_payload_rejected',
    'unexpected_scoped_member_rejected',
    'get_scroll_membership_drift_rejected',
    'complete_readback_shares_actual_byte_budget',
)
ERRORS=frozenset(('InvalidRequest','ProviderUnavailable','UnsupportedCapability','DeadlineExceeded',
    'IndexNotReady','IntegrityViolation','UnauthorizedScope','CancelledError','AbortError','internal'))

class NativeMissingFailure(RuntimeError):
    def __init__(self,observation):
        super().__init__('missing_readback_native_case_failed')
        self.observation=observation

async def python_missing_readback_cases(value):
    import asyncio
    from copy import deepcopy
    import inspect
    import json
    from pathlib import Path
    from cragkit._qdrant_supervisor import ManagedQdrantSupervisor
    from cragkit.errors import IntegrityViolation
    from cragkit._qdrant_contract import CandidatePayload
    from cragkit._qdrant_vectors import encode_dense,encode_sparse
    from cragkit._qdrant_reconciliation import ExpectedPoint,VerificationBudget,_Readback,inspect_missing_readback,_verify_readback
    from qdrant_supervisor_cases import plain,request_bytes,observed_listener
    inputs=value['inputs']
    controller=ManagedQdrantSupervisor(Path(value['binary']),Path(value['work_dir']),
        inputs['instance_id'],inputs['config'])
    deadline=asyncio.get_running_loop().time()+55
    checks=[]
    endpoint=primary=None
    target='/collections/'+inputs['config']['physical_collection']
    binding=dict(intent_id='session-native-intent',owner_token='00000000-0000-4000-8000-000000000001',
        epoch=2,dispatch_id='session-native-dispatch',recovery_id='session-native')
    async def provision(admin,probe):
        await admin.request('PUT',target,body=request_bytes(inputs['collection_config']),deadline=deadline)
        probe=plain(probe)
        path='/collections/'+probe['collection']
        await admin.request('PUT',path,body=request_bytes(probe['collection_config']),deadline=deadline)
        await admin.request('PUT',path+'/points?wait=true&ordering=strong',
            body=request_bytes(dict(points=[probe['point']])),deadline=deadline)
    async def expect(kinds,operation):
        try:
            value=operation()
            if inspect.isawaitable(value):await value
        except kinds:return
        raise RuntimeError('recovery_session_expected_refusal_missing')
    expected=tuple(ExpectedPoint(point['id'],CandidatePayload.model_validate(point['payload']),
        encode_dense(point['vector']['dense'],inputs['config']['dense_profile']),
        encode_sparse(point['vector']['sparse']['indices'],point['vector']['sparse']['values'],inputs['config']['sparse_profile']))
        for point in inputs['points'])
    data=dict(points=expected,tombstoned=False)
    async def put(handle,points):
        value=json.loads(await handle.request('PUT',target+'/points?wait=true&ordering=strong',body=request_bytes(dict(points=points)),deadline=deadline))
        if value.get('status')!='ok' or value.get('result',{}).get('status')!='completed':raise RuntimeError('missing_readback_mutation_ack')
    async def remove(handle,ids):
        value=json.loads(await handle.request('POST',target+'/points/delete?wait=true&ordering=strong',body=request_bytes(dict(points=ids)),deadline=deadline))
        if value.get('status')!='ok' or value.get('result',{}).get('status')!='completed':raise RuntimeError('missing_readback_delete_ack')
    async def missing(handle,budget=None):
        return await inspect_missing_readback(_Readback(handle,deadline,budget),target+'/points',data)
    try:
        await controller.initialize(deadline=deadline,provision=provision)
        endpoint=controller.identity()['endpoint'];await observed_listener(endpoint)
        controller.block_ordinary()
        proof=await controller.recover(dict(recovery_id='session-native',old_epoch=1,new_epoch=2),deadline=deadline)
        async with controller.control_session() as facade:
            attempt=facade.issue_recovery_attempt(proof,binding,deadline=deadline)
            handle=facade.recovery_transport_for(attempt)
            mutation=facade.recovery_transport_for(attempt)
            await put(mutation,inputs['points'][:1])
            if await missing(handle)!=(inputs['points'][1]['id'],):raise RuntimeError('missing_readback_wrong_deficit')
            checks.append(CHECKS[0])
            wrong=deepcopy(inputs['points'][0]);wrong['vector']['dense']=[-value for value in wrong['vector']['dense']]
            await put(mutation,[wrong]);await expect(IntegrityViolation,lambda:missing(handle))
            wrong=deepcopy(inputs['points'][0]);wrong['payload']['tenant_id']='foreign-native-tenant'
            await put(mutation,[wrong]);await expect(IntegrityViolation,lambda:missing(handle))
            await put(mutation,inputs['points'][:1]);checks.append(CHECKS[1])
            extra=deepcopy(inputs['points'][0]);extra['id']='00000000-0000-4000-8000-000000000099'
            await put(mutation,[extra]);await expect(IntegrityViolation,lambda:missing(handle))
            checks.append(CHECKS[2])
            await remove(mutation,[extra['id'],inputs['points'][1]['id']])
            class Drift:
                fired=False
                async def request(self,method,path,**options):
                    if path.endswith('/scroll') and not self.fired:
                        self.fired=True
                        await put(mutation,inputs['points'][1:])
                    return await handle.request(method,path,**options)
            await expect(IntegrityViolation,lambda:missing(Drift()));checks.append(CHECKS[3])
            class Meter:
                observed=0
                async def request(self,method,path,**options):
                    raw=await handle.request(method,path,**options)
                    self.observed+=len(raw)
                    return raw
            meter=Meter();budget=VerificationBudget()
            if await missing(meter,budget)!=() or await missing(meter,budget)!=():raise RuntimeError('missing_readback_false_deficit')
            await _verify_readback(_Readback(meter,deadline,budget),target+'/points',data)
            if budget.remaining_bytes!=8388608-meter.observed or meter.observed<=0:raise RuntimeError('missing_readback_budget_reset')
            checks.append(CHECKS[4])
        return dict(runtime='python',checks=checks,proof_scope='missing_only_inspection_and_budget_only')
    except BaseException as error:
        primary=error
        name=type(error).__name__
        raise NativeMissingFailure(dict(ok=False,step=len(checks),error=name if name in ERRORS else 'internal')) from None
    finally:
        failures=[]
        for operation,owned in [('controller_close',controller)]:
            try:await asyncio.wait_for(owned.close(),8)
            except BaseException as error:failures.append(dict(operation=operation,outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if endpoint is not None:
            try:await observed_listener(endpoint,allow_absent=True)
            except BaseException as error:failures.append(dict(operation='listener_close',outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if failures:
            name=type(primary).__name__ if primary is not None else None
            raise NativeMissingFailure(dict(ok=False,step=len(checks),error='cleanup_failed',
                primary=name if name in ERRORS else ('internal' if name else None),cleanup=failures)) from None
