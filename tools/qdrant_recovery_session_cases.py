"""Native recovery facade transport checks; no SQL settlement is asserted."""
from __future__ import annotations

CHECKS=(
    'real_recovery_session_writes_and_reads',
    'raw_and_foreign_attempts_cannot_join_session',
    'eight_live_handles_close_reuses_slot',
    'expired_facade_and_handles_reject_requests',
    'borrowed_handle_survives_owned_cleanup',
)
ERRORS=frozenset(('InvalidRequest','ProviderUnavailable','UnsupportedCapability','DeadlineExceeded',
    'IndexNotReady','IntegrityViolation','UnauthorizedScope','CancelledError','AbortError','internal'))

class NativeSessionFailure(RuntimeError):
    def __init__(self,observation):
        super().__init__('recovery_session_native_case_failed')
        self.observation=observation

async def python_recovery_session_cases(value):
    import asyncio
    from copy import deepcopy
    import inspect
    import json
    from pathlib import Path
    from cragkit._qdrant_supervisor import ManagedQdrantSupervisor
    from cragkit.errors import InvalidRequest,ProviderUnavailable,UnsupportedCapability
    from qdrant_supervisor_cases import plain,request_bytes,observed_listener
    inputs=value['inputs']
    controller=ManagedQdrantSupervisor(Path(value['binary']),Path(value['work_dir']),
        inputs['instance_id'],inputs['config'])
    deadline=asyncio.get_running_loop().time()+55
    checks=[]
    borrowed=endpoint=primary=None
    target='/collections/'+inputs['config']['physical_collection']
    binding=dict(intent_id='session-native-intent',owner_token='00000000-0000-4000-8000-000000000001',
        epoch=2,dispatch_id='session-native-dispatch',recovery_id='session-native')
    body=request_bytes(dict(points=inputs['points']))
    read=request_bytes(dict(ids=[point['id'] for point in inputs['points']],with_payload=True,with_vector=True))
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
    async def readback(handle):
        raw=await handle.request('POST',target+'/points',body=read,deadline=deadline)
        result=json.loads(raw)
        expected=sorted(deepcopy(inputs['points']),key=lambda point:point['id'])
        actual=sorted(result['result'],key=lambda point:point['id'])
        if result['status']!='ok' or actual!=expected:raise RuntimeError('recovery_session_readback_mismatch')
    try:
        await controller.initialize(deadline=deadline,provision=provision)
        endpoint=controller.identity()['endpoint'];await observed_listener(endpoint)
        controller.block_ordinary()
        proof=await controller.recover(dict(recovery_id='session-native',old_epoch=1,new_epoch=2),deadline=deadline)
        raw_attempt=controller.issue_recovery_attempt(proof,dict(binding,dispatch_id='session-raw'),deadline=deadline)
        borrowed=controller.transport_for(raw_attempt)
        async with controller.control_session() as facade:
            attempt=facade.issue_recovery_attempt(proof,binding,deadline=deadline)
            handle=facade.recovery_transport_for(attempt)
            response=json.loads(await handle.request('PUT',target+'/points?wait=true&ordering=strong',body=body,deadline=deadline))
            if response.get('status')!='ok' or response.get('result',{}).get('status')!='completed':
                raise RuntimeError('recovery_session_incomplete_ack')
            await readback(handle);checks.append(CHECKS[0])
            await expect(UnsupportedCapability,lambda:facade.issue_recovery_attempt(dict(controller.recovery_binding(proof)),binding,deadline=deadline))
            await expect(ProviderUnavailable,lambda:controller.issue_recovery_attempt(proof,binding,deadline=deadline))
            await expect(ProviderUnavailable,lambda:controller.transport_for(raw_attempt))
            await expect(InvalidRequest,lambda:facade.recovery_transport_for(raw_attempt))
            checks.append(CHECKS[1])
            owned=[handle]
            for index in range(1,8):
                capability=facade.issue_recovery_attempt(proof,dict(binding,dispatch_id=f'session-{index}'),deadline=deadline)
                owned.append(facade.recovery_transport_for(capability))
            extra=facade.issue_recovery_attempt(proof,dict(binding,dispatch_id='session-extra'),deadline=deadline)
            await expect(ProviderUnavailable,lambda:facade.recovery_transport_for(extra))
            await owned[0].close()
            replacement=facade.recovery_transport_for(extra)
            await readback(replacement);checks.append(CHECKS[2])
        await expect(ProviderUnavailable,lambda:facade.issue_recovery_attempt(proof,binding,deadline=deadline))
        await expect(ProviderUnavailable,lambda:facade.recovery_transport_for(extra))
        await expect(ProviderUnavailable,lambda:replacement.request('POST',target+'/points',body=read,deadline=deadline))
        checks.append(CHECKS[3])
        await readback(borrowed);checks.append(CHECKS[4])
        return dict(runtime='python',checks=checks,proof_scope='recovery_session_transport_only')
    except BaseException as error:
        primary=error
        name=type(error).__name__
        raise NativeSessionFailure(dict(ok=False,step=len(checks),error=name if name in ERRORS else 'internal')) from None
    finally:
        failures=[]
        for operation,owned in ([('transport_close',borrowed)] if borrowed is not None else [])+[('controller_close',controller)]:
            try:await asyncio.wait_for(owned.close(),8)
            except BaseException as error:failures.append(dict(operation=operation,outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if endpoint is not None:
            try:await observed_listener(endpoint,allow_absent=True)
            except BaseException as error:failures.append(dict(operation='listener_close',outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if failures:
            name=type(primary).__name__ if primary is not None else None
            raise NativeSessionFailure(dict(ok=False,step=len(checks),error='cleanup_failed',
                primary=name if name in ERRORS else ('internal' if name else None),cleanup=failures)) from None
