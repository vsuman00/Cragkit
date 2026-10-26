"""Native-controller unit doubles; actual process/key evidence belongs to root."""
import asyncio
from functools import wraps
import json
from pathlib import Path
import pickle
from types import SimpleNamespace

import pytest

import cragkit._qdrant_supervisor as implementation
from cragkit._qdrant_supervisor import ManagedQdrantSupervisor
from cragkit.embeddings import FAKE_PROFILE
from cragkit.errors import IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability, UnauthorizedScope


CONFIG={'backend_namespace':'fixture','physical_collection':'docs','collection_incarnation':'inc-1',
        'dense_profile':FAKE_PROFILE.model_dump(),'sparse_profile':None}
BINDING={'intent_id':'intent-1','owner_token':'11111111-1111-4111-8111-111111111111',
         'epoch':1,'dispatch_id':'dispatch-1'}


def run_async(function):
    @wraps(function)
    def run(*args,**kwargs):return asyncio.run(function(*args,**kwargs))
    return run


class Process:
    def __init__(self,pid=12):self.pid=pid;self.returncode=None;self.terminated=False;self.killed=False
    def terminate(self):self.terminated=True
    def kill(self):self.killed=True;self.returncode=-9
    async def wait(self):self.returncode=-15;return self.returncode


def supervisor(tmp_path,monkeypatch):
    owner=ManagedQdrantSupervisor(Path('/fixture/qdrant'),tmp_path/'owned','instance-1',CONFIG)
    owner._key='OLD_SECRET';owner._credential_generation='credential-1'
    owner._storage_id='storage-1';owner._supervisor_id='supervisor-1';owner._endpoint='http://127.0.0.1:12345'
    owner._probe={'collection':'control_probe','collection_config':{},'point':{
        'id':'11111111-1111-4111-8111-111111111112','vector':{'control':[1.0]},
        'payload':{'storage_identity':'storage-1','supervisor_id':'supervisor-1'}}}
    owner._owned=(1,2);owner._initialized=True;owner._gate=True;owner._process=Process()
    monkeypatch.setattr(owner,'_assert_owner',lambda:None)
    return owner


def test_constructor_is_io_free_and_rejects_bad_configuration(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('constructor I/O')
    monkeypatch.setattr(Path,'stat',forbidden)
    owner=ManagedQdrantSupervisor(Path('/fixture/qdrant'),tmp_path/'owned','instance-1',CONFIG)
    assert repr(owner)=='ManagedQdrantSupervisor()'
    with pytest.raises(InvalidRequest):ManagedQdrantSupervisor('binary',tmp_path,'instance',CONFIG)
    with pytest.raises(InvalidRequest):ManagedQdrantSupervisor(Path('/fixture/qdrant'),tmp_path,'x'*257,CONFIG)


@run_async
async def test_capabilities_are_issuer_bound_nonserializable_and_secret_free(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch);other=supervisor(tmp_path,monkeypatch)
    cap=owner.issue_attempt(BINDING,deadline=asyncio.get_running_loop().time()+1)
    metadata=owner.attempt_binding(cap)
    assert metadata['epoch']==1 and metadata['credential_generation']=='credential-1'
    assert 'SECRET' not in repr(cap)+repr(metadata)+repr(owner.transport_for(cap))
    with pytest.raises(TypeError):metadata['epoch']=2
    with pytest.raises(TypeError):pickle.dumps(cap)
    for forged in (dict(metadata),True,implementation._Attempt(),cap):
        target=other if forged is cap else owner
        with pytest.raises(InvalidRequest):target.attempt_binding(forged)


@run_async
async def test_ordinary_credential_delivery_is_explicit_and_captures_old_key(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch);seen=[]
    cap=owner.issue_attempt(BINDING,deadline=asyncio.get_running_loop().time()+1)
    async def sink(value):seen.append(dict(value))
    await owner.deliver_worker_credential(cap,sink,deadline=asyncio.get_running_loop().time()+1)
    assert seen==[{'endpoint':owner._endpoint,'api_key':'OLD_SECRET','epoch':1,'instance_id':'instance-1'}]
    owner._key='NEW_SECRET';owner._epoch=2;owner._gate=False
    with pytest.raises(ProviderUnavailable):await owner.deliver_worker_credential(cap,sink,deadline=asyncio.get_running_loop().time()+1)
    assert len(seen)==1


@run_async
async def test_invalid_recovery_epoch_does_not_close_healthy_admission(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch)
    with pytest.raises(InvalidRequest):
        await owner.recover({'recovery_id':'wrong-epoch','old_epoch':2,'new_epoch':3},
            deadline=asyncio.get_running_loop().time()+1)
    assert owner._gate and owner._recovery is None
    assert owner.issue_attempt(BINDING,deadline=asyncio.get_running_loop().time()+1) is not None


@run_async
async def test_retained_closed_transports_do_not_exhaust_live_handle_slots(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch)
    capability=owner.issue_attempt(BINDING,deadline=asyncio.get_running_loop().time()+1)
    retained=[]
    for _ in range(257):
        handle=owner.transport_for(capability)
        retained.append(handle)
        await handle.close()
    assert len(owner._transports)==0 and len(retained)==257


@run_async
async def test_known_dead_child_blocks_capability_delivery_and_all_http(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch)
    deadline=asyncio.get_running_loop().time()+1
    capability=owner.issue_attempt(BINDING,deadline=deadline)
    handle=owner.transport_for(capability)
    owner._process.returncode=0
    sent=[]
    async def sink(value):sent.append(value)
    async def forbidden(*args,**kwargs):raise AssertionError('dead child must not receive HTTP')
    monkeypatch.setattr(owner,'_http',forbidden)
    for operation in (lambda:owner.issue_attempt(BINDING,deadline=deadline),
                      lambda:owner.transport_for(capability),lambda:owner.attempt_binding(capability)):
        with pytest.raises(ProviderUnavailable):operation()
    with pytest.raises(ProviderUnavailable):
        await owner.deliver_worker_credential(capability,sink,deadline=deadline)
    with pytest.raises(ProviderUnavailable):
        await handle.request('GET','/',deadline=deadline)
    assert sent==[]


async def recovery_doubles(owner,monkeypatch,*,old_status=401,probe_failure=False):
    events=[]
    async def stop():events.append('exit');owner._process.returncode=0
    async def spawn():events.append('restart');owner._process=Process(13)
    async def ready(deadline):events.append('listener_version_cluster')
    async def verify(deadline):events.append('profiles')
    async def read(deadline):
        events.append('probe_read')
        if probe_failure:raise IntegrityViolation()
    async def http(key,method,path,body,deadline,*args,**kwargs):
        events.append(('old_key',key));return old_status,b'{}'
    async def request(method,path,deadline,body=None):
        events.append('new_key_completed');return {'result':{'status':'completed'}}
    for name,value in (('_stop',stop),('_spawn',spawn),('_ready',ready),('_verify_profiles',verify),
                       ('_probe_read',read),('_http',http),('_json',request)):
        monkeypatch.setattr(owner,name,value)
    return events


@run_async
async def test_recovery_observations_issue_private_proof_but_never_reopen_sql_or_ordinary_gate(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch)
    oldcap=owner.issue_attempt(BINDING,deadline=asyncio.get_running_loop().time()+1)
    oldhandle=owner.transport_for(oldcap)
    events=await recovery_doubles(owner,monkeypatch)
    request={'recovery_id':'recovery-1','old_epoch':1,'new_epoch':2}
    proof=await owner.recover(request,deadline=asyncio.get_running_loop().time()+2)
    assert events[:5]==['exit','restart','listener_version_cluster','profiles','probe_read']
    assert events[5]==('old_key','OLD_SECRET') and events[6:] == ['new_key_completed','probe_read']
    assert owner._transports[oldhandle].key=='OLD_SECRET'
    assert owner.recovery_binding(proof)['new_epoch']==2 and not owner._gate
    assert not hasattr(owner,'reopen')
    with pytest.raises(ProviderUnavailable):owner.issue_attempt({**BINDING,'epoch':2},deadline=asyncio.get_running_loop().time()+1)
    with pytest.raises(ProviderUnavailable):owner.transport_for(oldcap)
    cap=owner.issue_recovery_attempt(proof,{**BINDING,'epoch':2,'recovery_id':'recovery-1'},deadline=asyncio.get_running_loop().time()+1)
    assert owner.attempt_binding(cap)['recovery_id']=='recovery-1'
    async def forbidden_sink(value):raise AssertionError('recovery key must not leave the host')
    with pytest.raises(UnsupportedCapability):await owner.deliver_worker_credential(cap,forbidden_sink,deadline=asyncio.get_running_loop().time()+1)
    with pytest.raises(UnsupportedCapability):owner.recovery_binding(dict(owner.recovery_binding(proof)))
    generation=owner.recovery_binding(proof)['credential_generation']
    replacement=await owner.recover(request,deadline=asyncio.get_running_loop().time()+1)
    assert replacement is not proof and owner.recovery_binding(replacement)['credential_generation']!=generation
    assert events.count('restart')==2
    with pytest.raises(UnsupportedCapability):owner.recovery_binding(proof)
    with pytest.raises(ProviderUnavailable):owner.transport_for(cap)


@pytest.mark.parametrize('status',[200,201,301,302,307,403,404,500])
@run_async
async def test_only_actual_old_key_401_can_complete_recovery(tmp_path,monkeypatch,status):
    owner=supervisor(tmp_path,monkeypatch);events=await recovery_doubles(owner,monkeypatch,old_status=status)
    with pytest.raises(IntegrityViolation):await owner.recover({'recovery_id':'r','old_epoch':1,'new_epoch':2},deadline=asyncio.get_running_loop().time()+1)
    assert not owner._gate and 'new_key_completed' not in events and not owner._proofs


@run_async
async def test_foreign_or_changed_probe_is_never_overwritten_during_recovery(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch);events=await recovery_doubles(owner,monkeypatch,probe_failure=True)
    with pytest.raises(IntegrityViolation):await owner.recover({'recovery_id':'r','old_epoch':1,'new_epoch':2},deadline=asyncio.get_running_loop().time()+1)
    assert not owner._proofs and not any(isinstance(event,tuple) for event in events)


@pytest.mark.parametrize('status',[401,403])
@run_async
async def test_old_transport_never_refreshes_its_captured_key(tmp_path,monkeypatch,status):
    owner=supervisor(tmp_path,monkeypatch);keys=[]
    cap=owner.issue_attempt(BINDING,deadline=asyncio.get_running_loop().time()+1);handle=owner.transport_for(cap)
    owner._key='NEW_SECRET';owner._epoch=2;owner._gate=False
    async def http(key,*args,**kwargs):keys.append(key);return status,b'{}'
    monkeypatch.setattr(owner,'_http',http)
    with pytest.raises(UnauthorizedScope):await handle.request('PUT','/collections/docs/points?wait=true',body=b'{"points":[]}',deadline=asyncio.get_running_loop().time()+1)
    assert keys==['OLD_SECRET']
    with pytest.raises(AttributeError):handle._controller=None


@run_async
async def test_transport_paths_and_ordinary_probe_access_are_bounded(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch)
    cap=owner.issue_attempt(BINDING,deadline=asyncio.get_running_loop().time()+1);handle=owner.transport_for(cap)
    for path in ('https://foreign/','//foreign','/collections/foreign/points?wait=true',
                 '/collections/control_probe/points?wait=true','/collections/docs/../points',
                 '/collections/docs/points','/collections/docs/points?wait=false',
                 '/collections/docs/points?wait=true&ordering=weak','/collections/docs/points?wait=true&wait=true'):
        with pytest.raises(InvalidRequest):await handle.request('PUT',path,body=b'{}',deadline=asyncio.get_running_loop().time()+1)


@run_async
async def test_profile_verification_refuses_null_wal_and_unexpected_collections(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch)
    async def query(method,path,deadline,body=None):
        if path=='/collections':return {'result':{'collections':[{'name':'docs'},{'name':'control_probe'}]}}
        return {'result':{'config':{'params':{'replication_factor':1,'write_consistency_factor':1,
            'vectors':{'dense':{'size':1536,'distance':'Cosine'}}},'optimizer_config':{'prevent_unoptimized':None}}}}
    monkeypatch.setattr(owner,'_json',query)
    with pytest.raises(UnsupportedCapability):await owner._verify_profiles(asyncio.get_running_loop().time()+1)
    async def unexpected(*args,**kwargs):return {'result':{'collections':[{'name':'foreign'}]}}
    monkeypatch.setattr(owner,'_json',unexpected)
    with pytest.raises(UnsupportedCapability):await owner._verify_profiles(asyncio.get_running_loop().time()+1)


def test_existing_private_marker_is_not_a_takeover_lease(tmp_path,monkeypatch):
    binary=tmp_path/'qdrant';binary.write_bytes(b'fixture')
    work=tmp_path/'work';work.mkdir(mode=0o700);(work/'.cragkit-supervisor.lock').mkdir(mode=0o700)
    owner=ManagedQdrantSupervisor(binary,work,'instance',CONFIG)
    monkeypatch.setattr(implementation.sys,'platform','darwin');monkeypatch.setattr(implementation.platform,'machine',lambda:'arm64')
    monkeypatch.setattr(implementation,'_BINARY_SHA256',implementation.hashlib.sha256(b'fixture').hexdigest())
    original=Path.is_file
    monkeypatch.setattr(Path,'is_file',lambda path:True if str(path)=='/usr/sbin/lsof' else original(path))
    async def check():
        with pytest.raises(ProviderUnavailable):owner._claim(asyncio.get_running_loop().time()+1)
    asyncio.run(check())
    assert (work/'.cragkit-supervisor.lock').exists() and owner._owned is None


@run_async
async def test_explicit_provision_callback_is_not_accepted_as_configuration_proof(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch);owner._owned=None;owner._initialized=False;owner._gate=False
    events=[]
    def claim(deadline):owner._owned=(1,2);events.append('claim')
    async def spawn():events.append('spawn')
    async def ready(deadline):events.append('listener')
    async def provision(admin,probe):
        events.append('caller_provision');assert probe==owner._probe
        return True
    async def verify(deadline):events.append('independent_verify');raise UnsupportedCapability()
    async def close():events.append('cleanup');owner._closed=True
    for name,value in (('_claim',claim),('_spawn',spawn),('_ready',ready),('_verify_profiles',verify),('close',close)):
        monkeypatch.setattr(owner,name,value)
    with pytest.raises(UnsupportedCapability):await owner.initialize(deadline=asyncio.get_running_loop().time()+1,provision=provision)
    assert events==['claim','spawn','listener','caller_provision','independent_verify','cleanup']
    assert not owner._gate and not owner._initialized


@run_async
async def test_listener_verifier_uses_owned_child_and_exact_loopback_port(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch);calls=[]
    class Output:
        async def read(self,maximum):
            assert maximum==16385
            return b'p12\nn127.0.0.1:12345\n'
    class Verifier(Process):
        stdout=Output()
        async def wait(self):self.returncode=0;return 0
    async def spawn(*args,**kwargs):calls.append((args,kwargs));return Verifier()
    monkeypatch.setattr(implementation.asyncio,'create_subprocess_exec',spawn)
    assert await owner._listener(asyncio.get_running_loop().time()+1)
    assert calls[0][0]==('/usr/sbin/lsof','-nP','-a','-p','12','-iTCP@127.0.0.1:12345','-sTCP:LISTEN','-Fpn')
    assert 'SECRET' not in repr(calls)


@run_async
async def test_spawn_private_configuration_has_no_secret_argv_environment_or_logs(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch);owner._work=tmp_path
    calls=[]
    async def spawn(*args,**kwargs):calls.append((args,kwargs));return Process()
    monkeypatch.setattr(implementation.asyncio,'create_subprocess_exec',spawn)
    owner._process=None
    await owner._spawn()
    raw=json.loads((tmp_path/'config.yaml').read_bytes())
    assert raw['service']['api_key']=='OLD_SECRET'
    assert raw['storage']['optimizers']['prevent_unoptimized'] is False
    assert (tmp_path/'config.yaml').stat().st_mode & 0o777==0o600
    assert 'SECRET' not in repr(calls)
    assert calls[0][1]['stdout']==asyncio.subprocess.DEVNULL
    assert calls[0][1]['stderr']==asyncio.subprocess.DEVNULL
    assert calls[0][1]['start_new_session'] is True


@run_async
async def test_active_recovery_request_prevents_proof_handoff(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch);await recovery_doubles(owner,monkeypatch)
    proof=await owner.recover({'recovery_id':'r','old_epoch':1,'new_epoch':2},deadline=asyncio.get_running_loop().time()+1)
    task=asyncio.current_task();owner._requests.add(task)
    try:
        with pytest.raises(ProviderUnavailable):owner.recovery_binding(proof)
    finally:owner._requests.discard(task)


@run_async
async def test_close_cancels_tracked_work_and_stops_only_owned_child(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch);events=[]
    async def work():await asyncio.Event().wait()
    task=asyncio.create_task(work());await asyncio.sleep(0);owner._requests.add(task)
    async def stop():events.append('stop_owned');owner._process.returncode=0
    monkeypatch.setattr(owner,'_stop',stop)
    # Exercise bounded cancellation before filesystem cleanup independently.
    owner._owned=None
    await owner.close()
    assert task.cancelled() and owner._closed and owner._cleaned
    assert events==[]


@run_async
async def test_control_metadata_closes_admission_without_claiming_physical_fencing(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch)
    metadata=owner.control_binding()
    assert metadata['epoch']==1 and metadata['alive'] and not metadata['sealed']
    assert metadata['recovery'] is None and 'SECRET' not in repr(metadata)
    owner.block_ordinary()
    with pytest.raises(ProviderUnavailable):
        owner.issue_attempt(BINDING,deadline=asyncio.get_running_loop().time()+1)
    assert owner._process.returncode is None
    owner._process.returncode=-9
    assert owner.control_binding()['alive'] is False


@run_async
async def test_recovery_barrier_seals_handles_and_requires_private_committed_settlement(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch)
    await recovery_doubles(owner,monkeypatch)
    request={'recovery_id':'r','old_epoch':1,'new_epoch':2}
    deadline=asyncio.get_running_loop().time()+2
    proof=await owner.recover(request,deadline=deadline)
    cap=owner.issue_recovery_attempt(proof,{**BINDING,'epoch':2,'recovery_id':'r'},deadline=deadline)
    handle=owner.transport_for(cap)
    physical=dict(owner.recovery_binding(proof))
    barrier=await owner.seal_recovery(proof,deadline=deadline)
    assert dict(owner.barrier_binding(barrier))==physical
    assert owner.control_binding()['sealed'] and not owner._transports
    assert await owner.seal_recovery(proof,deadline=deadline) is barrier
    with pytest.raises(UnsupportedCapability):owner.recovery_binding(proof)
    with pytest.raises(UnsupportedCapability):owner.barrier_binding(dict(physical))
    with pytest.raises(ProviderUnavailable):
        await handle.request('GET','/',deadline=deadline)
    with pytest.raises(UnsupportedCapability):owner.finish_recovery(barrier,{},deadline=deadline)
    assert owner.control_binding()['sealed'] and not owner._gate
    replacement=await owner.recover(request,deadline=deadline)
    assert owner.recovery_binding(replacement)['credential_generation']!=physical['credential_generation']
    with pytest.raises(UnsupportedCapability):owner.barrier_binding(barrier)
    assert not owner.control_binding()['sealed'] and not owner._gate


@run_async
async def test_seal_refuses_inflight_work_and_preserves_failed_cleanup_as_closed(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch)
    await recovery_doubles(owner,monkeypatch)
    deadline=asyncio.get_running_loop().time()+2
    proof=await owner.recover({'recovery_id':'r','old_epoch':1,'new_epoch':2},deadline=deadline)
    task=asyncio.current_task();owner._requests.add(task)
    try:
        with pytest.raises(ProviderUnavailable):await owner.seal_recovery(proof,deadline=deadline)
        assert not owner.control_binding()['sealed']
    finally:owner._requests.discard(task)
    cap=owner.issue_recovery_attempt(proof,{**BINDING,'epoch':2,'recovery_id':'r'},deadline=deadline)
    handle=owner.transport_for(cap)
    async def fail_close(value):raise RuntimeError('PRIVATE_CLOSE')
    monkeypatch.setattr(owner,'_close_transport',fail_close)
    with pytest.raises(ProviderUnavailable) as caught:
        await owner.seal_recovery(proof,deadline=deadline)
    assert 'PRIVATE' not in str(caught.value)
    assert owner._active is None and owner.control_binding()['sealed'] and owner._barrier is None
    with pytest.raises(UnsupportedCapability):owner.recovery_binding(proof)


@run_async
async def test_control_session_is_exclusive_and_raw_calls_do_not_inherit_its_permission(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch)
    deadline=asyncio.get_running_loop().time()+2
    cap=owner.issue_attempt(BINDING,deadline=deadline)
    handle=owner.transport_for(cap)
    async with owner.control_session() as control:
        with pytest.raises(ProviderUnavailable):
            async with owner.control_session():pass
        with pytest.raises(ProviderUnavailable):owner.block_ordinary()
        with pytest.raises(ProviderUnavailable):owner.issue_attempt(BINDING,deadline=deadline)
        with pytest.raises(ProviderUnavailable):owner.transport_for(cap)
        with pytest.raises(ProviderUnavailable):await owner.close()
        with pytest.raises(ProviderUnavailable):await handle.request('GET','/',deadline=deadline)
        async def raw():
            with pytest.raises(ProviderUnavailable):
                await owner.recover({'recovery_id':'r','old_epoch':1,'new_epoch':2},deadline=deadline)
        await raw()
        await asyncio.create_task(raw())
        control.block_ordinary()
        assert not owner._gate
    with pytest.raises(ProviderUnavailable):control.block_ordinary()
    async with owner.control_session():pass
    await handle.close()


@run_async
async def test_existing_raw_lifecycle_cannot_be_joined_by_a_control_session(tmp_path,monkeypatch):
    owner=supervisor(tmp_path,monkeypatch)
    await recovery_doubles(owner,monkeypatch)
    started,released=asyncio.Event(),asyncio.Event()
    stop=owner._stop
    async def paused_stop():
        started.set();await released.wait();await stop()
    monkeypatch.setattr(owner,'_stop',paused_stop)
    task=asyncio.create_task(owner.recover({'recovery_id':'r','old_epoch':1,'new_epoch':2},
        deadline=asyncio.get_running_loop().time()+2))
    await started.wait()
    try:
        with pytest.raises(ProviderUnavailable):
            async with owner.control_session():pass
    finally:
        released.set();await task


@pytest.mark.parametrize('cancel',[False,True])
@run_async
async def test_control_session_drains_started_facade_work_before_expiring(tmp_path,monkeypatch,cancel):
    owner=supervisor(tmp_path,monkeypatch)
    await recovery_doubles(owner,monkeypatch)
    started,released=asyncio.Event(),asyncio.Event()
    stop=owner._stop
    async def paused_stop():
        started.set();await released.wait();await stop()
    monkeypatch.setattr(owner,'_stop',paused_stop)
    escaped=[]
    async def operation():
        async with owner.control_session() as control:
            escaped.append(control)
            asyncio.create_task(control.recover({'recovery_id':'r','old_epoch':1,'new_epoch':2},
                deadline=asyncio.get_running_loop().time()+2))
            await started.wait()
            if cancel:await asyncio.Event().wait()
    task=asyncio.create_task(operation())
    await started.wait();await asyncio.sleep(0)
    if cancel:task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    with pytest.raises(ProviderUnavailable):
        async with owner.control_session():pass
    released.set()
    if cancel:
        with pytest.raises(asyncio.CancelledError):await task
    else:await task
    assert owner._active is None and owner._control_token is None
    with pytest.raises(ProviderUnavailable):escaped[0].block_ordinary()
