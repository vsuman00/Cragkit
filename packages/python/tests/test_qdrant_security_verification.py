"""Receipt wiring doubles; no SQL metadata or fabricated proof is native evidence."""
import asyncio
import copy
from hashlib import sha256
import json
from pathlib import Path
import pickle
from types import MappingProxyType, SimpleNamespace

import pytest

import cragkit._qdrant_security_verification as implementation
from cragkit._qdrant_security_readback import SecurityReadbackBudget
from cragkit._qdrant_security_verification import (QdrantSecurityVerifier, SecurityReceipt,
    security_receipt_data, security_verifier_binding)
from cragkit._qdrant_supervisor import ManagedQdrantSupervisor, _ControlSession, _Proof
from cragkit._qdrant_writer import SecurityProjection, security_projection_data
from cragkit.errors import DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability
from test_qdrant_reconciliation import Handle
from test_qdrant_writer import config, run_async, security_projection_writer


def deadline():return asyncio.get_running_loop().time()+5


async def setup(monkeypatch,tmp_path,*,tombstoned=False,empty=False):
    writer,state,connections,security = security_projection_writer(monkeypatch,tombstone=tombstoned)
    if empty:state['claims'] = [];state['replays'] = []
    projection = await writer.project_security(security,deadline=deadline())
    data = security_projection_data(projection,writer)
    observed = [dict(id=point.point_id,payload=point.payload.model_dump(mode='json'),
        vector=dict(dense=list(point.dense.values),sparse=dict(indices=list(point.sparse.indices),values=list(point.sparse.values))))
        for point in data['points']]
    handle = Handle([] if tombstoned else observed)
    supervisor = ManagedQdrantSupervisor(Path('/fixture/qdrant'),tmp_path/'controller','instance-1',config())
    supervisor._owned = (1,2);supervisor._initialized = True;supervisor._gate = False;supervisor._epoch = 2
    supervisor._storage_id = 'storage-1';supervisor._supervisor_id = 'supervisor-1'
    supervisor._credential_generation = 'credential-2';supervisor._key = 'PRIVATE_FIXTURE_KEY'
    supervisor._process = SimpleNamespace(returncode=None)
    monkeypatch.setattr(supervisor,'_assert_owner',lambda:None)
    physical = dict(instance_id='instance-1',storage_identity='storage-1',supervisor_id='supervisor-1',
        recovery_id='fixture-recovery',old_epoch=1,new_epoch=2,credential_generation='credential-2')
    proof = _Proof();supervisor._proofs[proof] = physical
    supervisor._recovery = dict(recovery_id=physical['recovery_id'],old_epoch=1,new_epoch=2,proof=proof)
    async def http(key,method,path,body,limit,maximum,transport_state):
        if method == 'GET':return 200,b'{}'
        return 200,await handle.request(method,path,body=body,deadline=limit,max_response_bytes=maximum)
    monkeypatch.setattr(supervisor,'_http',http)
    owner = copy.deepcopy(security);owner['intent_id'] = 'historical-denied-stage'
    owner['owner_token'] = '22222222-2222-4222-8222-222222222222'
    return QdrantSecurityVerifier(writer,supervisor),writer,supervisor,proof,owner,security,state,connections,handle


@pytest.mark.parametrize('tombstoned,empty',[(False,False),(True,False),(False,True),(True,True)])
@run_async
async def test_same_session_receipt_has_exact_witness_and_borrowed_lifetime(monkeypatch,tmp_path,tombstoned,empty):
    verifier,writer,supervisor,proof,owner,security,state,connections,handle = await setup(monkeypatch,tmp_path,tombstoned=tombstoned,empty=empty)
    budget = SecurityReadbackBudget();limit = deadline()
    async with supervisor.control_session() as control:
        receipt = await verifier.verify(proof,control,owner,security,deadline=limit,budget=budget)
        data = security_receipt_data(receipt,verifier,control,deadline=limit)
        assert set(data) == {'projection','owner_context','security_context','physical_binding','attempt_binding','activity',
            'intent_sha256','inventory_sha256','point_ids','readback_sha256','witness','encoded_bytes','sha256'}
        source = security_projection_data(data['projection'],writer)
        physical,attempt = data['physical_binding'],data['attempt_binding']
        assert attempt['intent_id'] == owner['intent_id'] and attempt['owner_token'] == owner['owner_token']
        assert attempt['dispatch_id'].startswith('security-readback-')
        assert data['activity'] == 1+len(handle.calls)
        expected = ['cragkit.qdrant.security-readback.v1',
            [physical[key] for key in ('instance_id','storage_identity','supervisor_id','recovery_id')]
                +['1','2',physical['credential_generation']],
            [owner['intent_id'],owner['owner_token'],'2',attempt['dispatch_id'],physical['recovery_id']],str(data['activity']),
            ['tenant-a','docs','doc-1',owner['intent_id'],owner['owner_token']],
            ['tenant-a','reader-a',['grant-a'],'auth-2'],
            ['acl-2',security['owner_token'],source['intent_sha256'],'auth-2','2',source['active_generation_id'],
             'true' if tombstoned else 'false',list(source['principal_ids']),list(source['grant_ids']),source['language'],source['kind'],source['tag']],
            [source['inventory_sha256'],[[group['revision_id'],group['generation_id'],group['manifest_sha256'],list(group['point_ids'])]
                for group in source['generations']]],
            [[point.point_id,point.dense.input_sha256,point.sparse.input_sha256] for point in source['points']]]
        assert json.loads(data['encoded_bytes']) == expected
        assert data['encoded_bytes'] == json.dumps(expected,ensure_ascii=False,separators=(',',':')).encode()
        assert data['sha256'] == data['readback_sha256'] == sha256(data['encoded_bytes']).hexdigest()
        assert budget.remaining_calls == 513-len(handle.calls)
        assert not supervisor._transports
        security_verifier_binding(verifier,writer,supervisor)
        with pytest.raises(TypeError):data['activity'] = 0
        with pytest.raises(TypeError):pickle.dumps(receipt)
        for forged in (SecurityReceipt(),{},dict(data)):
            with pytest.raises(InvalidRequest):security_receipt_data(forged,verifier,control,deadline=limit)
        with pytest.raises(InvalidRequest):security_receipt_data(receipt,QdrantSecurityVerifier(writer,supervisor),control,deadline=limit)
        with pytest.raises(InvalidRequest):security_receipt_data(receipt,verifier,control,deadline=limit+1)
    with pytest.raises(InvalidRequest):security_receipt_data(receipt,verifier,control,deadline=limit)
    await verifier.close()
    assert not writer._closed and not supervisor._closed


@run_async
async def test_fake_facades_wrong_scope_and_fake_budget_fail_before_source_or_http(monkeypatch,tmp_path):
    verifier,writer,supervisor,proof,owner,security,state,connections,handle = await setup(monkeypatch,tmp_path)
    before = len(connections)
    async with supervisor.control_session() as control:
        for facade in (object(),{},_ControlSession(supervisor,control._token)):
            with pytest.raises(InvalidRequest):await verifier.verify(proof,facade,owner,security,deadline=deadline())
        wrong = copy.deepcopy(owner);wrong['scope']['authorization_revision'] = 'old-auth'
        with pytest.raises(InvalidRequest):await verifier.verify(proof,control,wrong,security,deadline=deadline())
        with pytest.raises(InvalidRequest):await verifier.verify(proof,control,owner,security,deadline=deadline(),budget=object())
        with pytest.raises(UnsupportedCapability):await verifier.verify(dict(supervisor.recovery_binding(proof)),control,owner,security,deadline=deadline())
    assert len(connections) == before and handle.calls == []


@pytest.mark.parametrize('fault',['stale','missing','corrupt','extra','drift','fake_projection','source_changed'])
@run_async
async def test_no_receipt_from_incomplete_or_changed_observations(monkeypatch,tmp_path,fault):
    verifier,writer,supervisor,proof,owner,security,state,connections,handle = await setup(monkeypatch,tmp_path)
    if fault == 'stale':handle.points[0]['payload']['authorization_revision'] = 'old-auth'
    elif fault == 'missing':handle.points.pop()
    elif fault == 'corrupt':handle.points[0]['vector']['dense'] = [-value for value in handle.points[0]['vector']['dense']]
    elif fault == 'extra':
        extra = copy.deepcopy(handle.points[0]);extra['id'] = '00000000-0000-4000-8000-000000000099';handle.points.append(extra)
    elif fault == 'drift':
        def patch(points):points[0]['payload']['tag'] = 'old';return points
        handle.get_patch = patch
    elif fault == 'fake_projection':
        async def fake(*args,**options):return SecurityProjection()
        monkeypatch.setattr(writer,'project_security',fake)
    else:
        original = writer.validate_security_projection
        async def changed(*args,**options):
            state['document']['mutation_epoch'] += 1
            await original(*args,**options)
        monkeypatch.setattr(writer,'validate_security_projection',changed)
    async with supervisor.control_session() as control:
        with pytest.raises(InvalidRequest if fault == 'fake_projection' else UnauthorizedScope if fault == 'source_changed' else IntegrityViolation):
            await verifier.verify(proof,control,owner,security,deadline=deadline())
        assert not supervisor._transports


async def interpose(control,proof,supervisor,owner,limit):
    attempt = control.issue_recovery_attempt(proof,dict(intent_id=owner['intent_id'],owner_token=owner['owner_token'],
        epoch=2,dispatch_id='interposed-native-get',recovery_id='fixture-recovery'),deadline=limit)
    handle = control.recovery_transport_for(attempt)
    await handle.request('GET','/',deadline=limit)
    await handle.close()


@pytest.mark.parametrize('phase',['close','source'])
@run_async
async def test_interposed_native_http_during_close_or_source_await_invalidates_snapshot(monkeypatch,tmp_path,phase):
    verifier,writer,supervisor,proof,owner,security,state,connections,handle = await setup(monkeypatch,tmp_path)
    limit = deadline()
    async with supervisor.control_session() as control:
        if phase == 'source':
            original = writer.validate_security_projection
            async def validate(*args,**options):
                await original(*args,**options)
                await interpose(control,proof,supervisor,owner,limit)
            monkeypatch.setattr(writer,'validate_security_projection',validate)
        else:
            original = supervisor._close_transport;armed = True
            async def close(owned_handle):
                nonlocal armed
                if armed:
                    armed = False
                    await interpose(control,proof,supervisor,owner,limit)
                await original(owned_handle)
            monkeypatch.setattr(supervisor,'_close_transport',close)
        with pytest.raises(UnsupportedCapability):await verifier.verify(proof,control,owner,security,deadline=limit)


@pytest.mark.parametrize('change',['attempt','get','rotation','closed_verifier'])
@run_async
async def test_accessor_rechecks_original_session_activity_proof_and_issuer(monkeypatch,tmp_path,change):
    verifier,writer,supervisor,proof,owner,security,state,connections,handle = await setup(monkeypatch,tmp_path)
    limit = deadline()
    async with supervisor.control_session() as control:
        receipt = await verifier.verify(proof,control,owner,security,deadline=limit)
        if change == 'get':await interpose(control,proof,supervisor,owner,limit)
        elif change == 'attempt':control.issue_recovery_attempt(proof,dict(intent_id=owner['intent_id'],owner_token=owner['owner_token'],epoch=2,
            dispatch_id='later-attempt',recovery_id='fixture-recovery'),deadline=limit)
        elif change == 'rotation':supervisor._proofs.clear()
        else:await verifier.close()
        with pytest.raises((InvalidRequest,UnsupportedCapability)):
            security_receipt_data(receipt,verifier,control,deadline=limit)


@run_async
async def test_overlap_cancel_suppression_and_close_retain_active_until_actual_unwind(monkeypatch,tmp_path):
    verifier,writer,supervisor,proof,owner,security,state,connections,handle = await setup(monkeypatch,tmp_path)
    original = writer.project_security;entered,cancelled,release = asyncio.Event(),asyncio.Event(),asyncio.Event()
    async def stalled(*args,**options):
        entered.set()
        try:await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set();await release.wait()
        return await original(*args,**options)
    monkeypatch.setattr(writer,'project_security',stalled)
    monkeypatch.setattr(implementation,'_CLEANUP_SECONDS',.02)
    async with supervisor.control_session() as control:
        task = asyncio.create_task(verifier.verify(proof,control,owner,security,deadline=deadline()))
        await entered.wait()
        with pytest.raises(ProviderUnavailable):await verifier.verify(proof,control,owner,security,deadline=deadline())
        task.cancel();await cancelled.wait()
        with pytest.raises(asyncio.CancelledError):await task
        assert verifier._active is not None and handle.calls == []
        active = verifier._active;release.set()
        await asyncio.gather(active,return_exceptions=True)
        await asyncio.sleep(0)
        assert verifier._active is None and handle.calls == []
    await verifier.close()
    assert not writer._closed and not supervisor._closed


@run_async
async def test_original_deadline_is_not_extended_and_unknown_failures_are_redacted(monkeypatch,tmp_path):
    verifier,writer,supervisor,proof,owner,security,state,connections,handle = await setup(monkeypatch,tmp_path)
    async with supervisor.control_session() as control:
        limit = asyncio.get_running_loop().time()+.1
        receipt = await verifier.verify(proof,control,owner,security,deadline=limit)
        await asyncio.sleep(.11)
        with pytest.raises(DeadlineExceeded):security_receipt_data(receipt,verifier,control,deadline=deadline())
        async def fail(*args,**options):raise RuntimeError('PRIVATE_SOURCE_SQL_TEXT')
        monkeypatch.setattr(writer,'project_security',fail)
        with pytest.raises(ProviderUnavailable) as error:
            await verifier.verify(proof,control,owner,security,deadline=deadline())
        assert 'PRIVATE' not in str(error.value)


@run_async
async def test_constructor_subclasses_and_changed_dependencies_are_rejected_locally(monkeypatch,tmp_path):
    verifier,writer,supervisor,proof,owner,security,state,connections,handle = await setup(monkeypatch,tmp_path)
    before = len(connections)
    class Subclass(QdrantSecurityVerifier):pass
    with pytest.raises(InvalidRequest):Subclass(writer,supervisor)
    with pytest.raises(InvalidRequest):QdrantSecurityVerifier(object(),supervisor)
    with pytest.raises(InvalidRequest):QdrantSecurityVerifier(writer,object())
    duplicate = QdrantSecurityVerifier(writer,supervisor)
    security_verifier_binding(duplicate,writer,supervisor)
    assert len(connections) == before and handle.calls == []
    async with supervisor.control_session() as control:
        receipt = await verifier.verify(proof,control,owner,security,deadline=deadline())
        verifier._writer = object()
        with pytest.raises(InvalidRequest):security_receipt_data(receipt,verifier,control,deadline=deadline())
        verifier._writer = writer
        original_resource = writer.resource
        writer.resource = object()
        with pytest.raises(InvalidRequest):security_receipt_data(receipt,verifier,control,deadline=deadline())
        writer.resource = original_resource


@run_async
async def test_owned_handle_cleanup_failure_mints_nothing_and_preserves_borrowed_dependencies(monkeypatch,tmp_path):
    verifier,writer,supervisor,proof,owner,security,state,connections,handle = await setup(monkeypatch,tmp_path)
    original = supervisor._close_transport;armed = True
    async def close(owned):
        nonlocal armed
        if armed:
            armed = False
            raise RuntimeError('PRIVATE_CLEANUP_FAILURE')
        await original(owned)
    monkeypatch.setattr(supervisor,'_close_transport',close)
    async with supervisor.control_session() as control:
        with pytest.raises(ProviderUnavailable) as error:
            await verifier.verify(proof,control,owner,security,deadline=deadline())
        assert 'PRIVATE' not in str(error.value) and not supervisor._transports
    assert not writer._closed and not supervisor._closed
