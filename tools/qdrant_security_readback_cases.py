"""Native document readback mechanics with synthetic vectors and no SQL authority."""
from __future__ import annotations

from copy import deepcopy

CHECKS = (
    'multiple_generations_report_missing_and_stale_mutable_fields',
    'strict_current_readback_requires_every_current_member',
    'immutable_dense_sparse_and_payload_corruption_rejected',
    'unexpected_generation_visible_in_full_document_scope',
    'get_scroll_membership_and_mutable_payload_drift_rejected',
    'tombstone_requires_exact_ids_absent_and_full_document_empty',
    'empty_inventory_still_enumerates_explicit_scope',
    'shared_actual_response_bytes_and_request_calls_across_passes',
)
ERRORS = frozenset(('InvalidRequest','ProviderUnavailable','UnsupportedCapability','DeadlineExceeded',
    'IndexNotReady','IntegrityViolation','UnauthorizedScope','CancelledError','AbortError','internal'))


class NativeSecurityReadbackFailure(RuntimeError):
    def __init__(self, observation):
        super().__init__('security_readback_native_case_failed')
        self.observation = observation


def security_readback_input():
    from cragkit._qdrant_contract import point_id
    from qdrant_supervisor_cases import supervisor_input
    value = supervisor_input()
    originals = deepcopy(value['points'])
    other = deepcopy(originals)
    for point in other:
        payload = point['payload']
        payload['revision_id'] += '-security-other'
        payload['generation_id'] += '-security-other'
        point['id'] = point_id(['cragkit.qdrant.point.v1', *[payload[key] for key in (
            'backend_namespace','physical_collection','collection_incarnation','tenant_id','collection',
            'document_id','revision_id','generation_id','chunk_id','dense_profile_id','sparse_profile_id')]])
    points = originals + other
    for point in points:
        point['payload'].update(authorization_revision='auth-2',principal_ids=[],grant_ids=[],language='de',tag='current-security')
    value['points'] = sorted(points,key=lambda point:point['id'])
    sample = value['points'][0]['payload']
    value['context'] = dict(scope=dict(tenant_id=sample['tenant_id'],principal_id='fixture-reader',grant_ids=[],
        authorization_revision='auth-2'),collection=sample['collection'],document_id=sample['document_id'],
        intent_id='native-security-readback',owner_token='00000000-0000-4000-8000-000000000001')
    return value


async def python_security_readback_cases(value):
    import asyncio
    import inspect
    import json
    from pathlib import Path
    from cragkit._qdrant_supervisor import ManagedQdrantSupervisor, control_session_binding
    from cragkit._qdrant_contract import CandidatePayload
    from cragkit._qdrant_vectors import encode_dense, encode_sparse
    from cragkit._qdrant_reconciliation import ExpectedPoint
    from cragkit._qdrant_security_readback import (SecurityReadbackBudget,inspect_security_readback,
        verify_security_readback)
    from cragkit.errors import IntegrityViolation
    from qdrant_supervisor_cases import plain,request_bytes,observed_listener

    inputs = value['inputs']
    controller = ManagedQdrantSupervisor(Path(value['binary']),Path(value['work_dir']),
        inputs['instance_id'],inputs['config'])
    deadline = asyncio.get_running_loop().time()+100
    checks = []
    endpoint = primary = None
    target = '/collections/'+inputs['config']['physical_collection']
    expected = tuple(ExpectedPoint(point['id'],CandidatePayload.model_validate(point['payload']),
        encode_dense(point['vector']['dense'],inputs['config']['dense_profile']),
        encode_sparse(point['vector']['sparse']['indices'],point['vector']['sparse']['values'],inputs['config']['sparse_profile']))
        for point in inputs['points'])
    data = dict(context=inputs['context'],points=expected,point_ids=tuple(point.point_id for point in expected),tombstoned=False)
    binding = dict(intent_id='native-security-readback',owner_token=inputs['context']['owner_token'],epoch=2,
        dispatch_id='native-security-readback-attempt',recovery_id='native-security-readback')

    async def provision(admin,probe):
        await admin.request('PUT',target,body=request_bytes(inputs['collection_config']),deadline=deadline)
        probe = plain(probe)
        path = '/collections/'+probe['collection']
        await admin.request('PUT',path,body=request_bytes(probe['collection_config']),deadline=deadline)
        await admin.request('PUT',path+'/points?wait=true&ordering=strong',body=request_bytes(dict(points=[probe['point']])),deadline=deadline)

    async def expect_refusal(operation):
        try:
            result = operation()
            if inspect.isawaitable(result):
                await result
        except IntegrityViolation:
            return
        raise RuntimeError('security_readback_expected_refusal_missing')

    async def mutate(handle,method,path,body):
        result = json.loads(await handle.request(method,path,body=request_bytes(body),deadline=deadline))
        if result.get('status')!='ok' or result.get('result',{}).get('status')!='completed':
            raise RuntimeError('security_readback_mutation_ack')

    async def put(handle,points):
        await mutate(handle,'PUT',target+'/points?wait=true&ordering=strong',dict(points=points))

    async def remove(handle,ids):
        await mutate(handle,'POST',target+'/points/delete?wait=true&ordering=strong',dict(points=ids))

    async def inspect_set(handle,selected=data,budget=None):
        return await inspect_security_readback(handle,inputs['config'],selected,deadline=deadline,budget=budget)

    async def verify(handle,selected=data,budget=None):
        await verify_security_readback(handle,inputs['config'],selected,deadline=deadline,budget=budget)

    try:
        await controller.initialize(deadline=deadline,provision=provision)
        endpoint = controller.identity()['endpoint']
        await observed_listener(endpoint)
        controller.block_ordinary()
        proof = await controller.recover(dict(recovery_id='native-security-readback',old_epoch=1,new_epoch=2),deadline=deadline)
        async with controller.control_session() as facade:
            attempt = facade.issue_recovery_attempt(proof,binding,deadline=deadline)
            handle,mutation = facade.recovery_transport_for(attempt),facade.recovery_transport_for(attempt)
            partial = deepcopy(inputs['points'][:-1])
            partial[0]['payload'].update(authorization_revision='auth-1',principal_ids=['old-reader'],grant_ids=['old-grant'],language='en')
            await put(mutation,partial)
            actual = await inspect_set(handle)
            if (tuple(actual['present_ids'])!=tuple(point['id'] for point in partial)
                    or tuple(actual['missing_ids'])!=(inputs['points'][-1]['id'],)
                    or tuple(actual['stale_ids'])!=(partial[0]['id'],)):
                raise RuntimeError('security_readback_wrong_diagnostics')
            checks.append(CHECKS[0])
            await expect_refusal(lambda:verify(handle))
            await put(mutation,inputs['points'])
            await verify(handle)
            checks.append(CHECKS[1])
            for kind in ('dense','sparse','payload'):
                wrong = deepcopy(inputs['points'][0])
                if kind=='dense':
                    wrong['vector']['dense'] = [-item for item in wrong['vector']['dense']]
                elif kind=='sparse':
                    wrong['vector']['sparse']['values'][0] += 1
                else:
                    wrong['payload']['tenant_id'] = 'foreign-native-tenant'
                await put(mutation,[wrong])
                await expect_refusal(lambda:inspect_set(handle))
                await put(mutation,inputs['points'][:1])
            checks.append(CHECKS[2])
            extra = deepcopy(inputs['points'][0])
            extra['id'] = '00000000-0000-4000-8000-000000000099'
            extra['payload']['generation_id'] = 'unexpected-native-generation'
            await put(mutation,[extra])
            await expect_refusal(lambda:inspect_set(handle))
            await remove(mutation,[extra['id']])
            checks.append(CHECKS[3])
            class Drift:
                def __init__(self,mode):
                    self.mode,self.fired = mode,False
                async def request(self,method,path,**options):
                    if path.endswith('/scroll') and not self.fired:
                        self.fired = True
                        if self.mode=='membership':
                            await remove(mutation,[inputs['points'][-1]['id']])
                        else:
                            changed = deepcopy(inputs['points'][0])
                            changed['payload']['tag'] = 'changed-between-reads'
                            await put(mutation,[changed])
                    return await handle.request(method,path,**options)
            for mode in ('membership','payload'):
                await expect_refusal(lambda:inspect_set(Drift(mode)))
                await put(mutation,inputs['points'])
            checks.append(CHECKS[4])
            tombstone = dict(data,tombstoned=True)
            await expect_refusal(lambda:verify(handle,tombstone))
            await remove(mutation,list(data['point_ids']))
            await verify(handle,tombstone)
            checks.append(CHECKS[5])
            empty = dict(data,points=(),point_ids=())
            await put(mutation,inputs['points'][:1])
            await expect_refusal(lambda:inspect_set(handle,empty))
            await remove(mutation,[inputs['points'][0]['id']])
            if dict(await inspect_set(handle,empty))!=dict(present_ids=(),missing_ids=(),stale_ids=()):
                raise RuntimeError('security_readback_empty_scope')
            await verify(handle,empty)
            checks.append(CHECKS[6])
            await put(mutation,inputs['points'])
            class Meter:
                observed_bytes = 0
                calls = 0
                async def request(self,method,path,**options):
                    self.calls += 1
                    body = json.loads(options['body'])
                    if path.endswith('/scroll'):
                        keys = {item['key'] for item in body['filter']['must']}
                        if keys!={'backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id'}:
                            raise RuntimeError('security_readback_hidden_scope')
                    raw = await handle.request(method,path,**options)
                    self.observed_bytes += len(raw)
                    return raw
            initial_activity=control_session_binding(facade,controller,proof)['activity']
            meter,budget = Meter(),SecurityReadbackBudget()
            for _ in range(2):
                actual = await inspect_set(meter,budget=budget)
                if actual['missing_ids'] or actual['stale_ids']:
                    raise RuntimeError('security_readback_complete_diagnostics')
            await verify(meter,budget=budget)
            if (budget.remaining_bytes!=8388608-meter.observed_bytes or budget.remaining_calls!=513-meter.calls
                    or meter.calls<=0 or meter.observed_bytes<=0):
                raise RuntimeError('security_readback_budget_reset')
            if control_session_binding(facade,controller,proof)['activity']!=initial_activity+meter.calls:
                raise RuntimeError('security_session_activity_mismatch')
            checks.append(CHECKS[7])
        return dict(runtime='python',checks=checks,proof_scope='security_document_readback_diagnostics_only')
    except BaseException as error:
        primary = error
        name = type(error).__name__
        raise NativeSecurityReadbackFailure(dict(ok=False,step=len(checks),error=name if name in ERRORS else 'internal')) from None
    finally:
        failures = []
        try:
            await asyncio.wait_for(controller.close(),8)
        except BaseException as error:
            failures.append(dict(operation='controller_close',outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if endpoint is not None:
            try:
                await observed_listener(endpoint,allow_absent=True)
            except BaseException as error:
                failures.append(dict(operation='listener_close',outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if failures:
            name = type(primary).__name__ if primary is not None else None
            raise NativeSecurityReadbackFailure(dict(ok=False,step=len(checks),error='cleanup_failed',
                primary=name if name in ERRORS else ('internal' if name else None),cleanup=failures)) from None
