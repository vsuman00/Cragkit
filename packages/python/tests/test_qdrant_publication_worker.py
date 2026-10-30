"""Worker protocol/lifetime unit checks; actual process acceptance is separate."""
import asyncio
import copy
import contextvars
import hashlib
import json
from pathlib import Path
import struct
from types import MappingProxyType

import pytest

import cragkit._qdrant_publication_worker as worker
import cragkit._qdrant_publication_verification as verification
from cragkit._qdrant_supervisor import ManagedQdrantSupervisor
from cragkit.contracts import Limits, TrustedScope
from cragkit.errors import DeadlineExceeded, InvalidRequest, ProviderUnavailable, UnsupportedCapability
from cragkit.execution import BudgetExhausted, ExecutionLedger
from test_qdrant_reconciliation import run_async
from test_qdrant_writer import config, ctx


def identity():
    return dict(instance_id='instance', backend_namespace='namespace', storage_identity='storage',
        supervisor_id='supervisor', epoch=1, credential_generation='credential', recovery=None, sealed=False, alive=True)


def job():
    return dict(writer_pool=dict(host='localhost', dbname='test', user='writer', sslrootcert='/tmp/ca', passfile='/tmp/pass', max_size=1),
        config=config(), scope=ctx()['scope'], reference={key: ctx()[key] for key in ('collection', 'document_id', 'intent_id')},
        limits=Limits().model_dump(mode='json'))


class Stream:
    def __init__(self):
        self.data = bytearray()
        self.closed = False
    def write(self, raw):
        self.data.extend(raw)
    async def drain(self):
        pass
    def close(self):
        self.closed = True
    async def wait_closed(self):
        pass


def channel(raw=b''):
    reader = asyncio.StreamReader()
    if raw:
        reader.feed_data(raw)
    reader.feed_eof()
    return worker._Channel(reader, Stream())


def frame(value):
    raw = worker._bytes(value)
    return struct.pack('!I', len(raw)) + raw


def deadline():
    return asyncio.get_running_loop().time() + 5


@run_async
async def test_finalization_requires_helper_exact_controller_task_and_original_budget(tmp_path):
    supervisor = ManagedQdrantSupervisor(tmp_path/'binary', tmp_path/'work', 'instance', config())
    foreign = ManagedQdrantSupervisor(tmp_path/'other', tmp_path/'other-work', 'other', config())
    end = deadline()
    with pytest.raises(InvalidRequest):
        worker.require_publication_finalization(supervisor, deadline=end)
    async with supervisor.control_session():
        with pytest.raises(InvalidRequest):
            worker.require_publication_finalization(supervisor, deadline=end)
    async with worker.controller_finalization(supervisor, object(), deadline=end):
        copied = contextvars.copy_context()
        worker.require_publication_finalization(supervisor, deadline=end - 1)
        with pytest.raises(InvalidRequest):
            worker.require_publication_finalization(supervisor, deadline=end + 1)
        with pytest.raises(InvalidRequest):
            worker.require_publication_finalization(foreign, deadline=end)
        async def inherited():
            with pytest.raises(InvalidRequest):
                worker.require_publication_finalization(supervisor, deadline=end)
        await asyncio.create_task(inherited())
        with pytest.raises(InvalidRequest):
            async with worker.controller_finalization(supervisor, object(), deadline=end):
                pytest.fail('nested context admitted')
    assert supervisor._control_token is None
    with pytest.raises(InvalidRequest):
        worker.require_publication_finalization(supervisor, deadline=end)
    with pytest.raises(InvalidRequest):
        copied.run(worker.require_publication_finalization, supervisor, deadline=end)


@run_async
async def test_finalization_expiry_and_cancellation_keep_session_until_body_unwinds(tmp_path):
    supervisor = ManagedQdrantSupervisor(tmp_path/'binary', tmp_path/'work', 'instance', config())
    end = asyncio.get_running_loop().time() + .01
    async with worker.controller_finalization(supervisor, object(), deadline=end):
        await asyncio.sleep(.02)
        with pytest.raises(DeadlineExceeded):
            worker.require_publication_finalization(supervisor, deadline=end)
    entered, unwinding, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    async def body():
        end = deadline()
        async with worker.controller_finalization(supervisor, object(), deadline=end):
            entered.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                assert supervisor._control_token is not None and worker._FINALIZATION.get().active
                with pytest.raises(asyncio.CancelledError):
                    worker.require_publication_finalization(supervisor, deadline=end)
                unwinding.set()
                await release.wait()
                assert worker._FINALIZATION.get().active
                raise
    task = asyncio.create_task(body())
    await entered.wait()
    task.cancel()
    await unwinding.wait()
    assert supervisor._control_token is not None and not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert supervisor._control_token is None


@run_async
async def test_worker_finalization_context_uses_actual_ipc_begin_end():
    selected_job = worker._job(job())
    rpc = RPC([{}, {}, {}, {}])
    controller = worker.OrdinaryWorkerController(worker._BOOT_TOKEN, rpc, selected_job, identity(), deadline())
    attempt = worker._Attempt()
    worker._CONTROLLERS[controller].attempts[attempt] = {'attempt_id': 1}
    end = deadline()
    async with controller.finalization(attempt, deadline=end):
        with pytest.raises(InvalidRequest):
            worker.require_publication_finalization(controller, deadline=end)
    async with worker.controller_finalization(controller, attempt, deadline=end):
        worker.require_publication_finalization(controller, deadline=end)
        assert [call[0] for call in rpc.calls] == ['finalize_begin', 'finalize_end', 'finalize_begin']
    assert [call[0] for call in rpc.calls] == ['finalize_begin', 'finalize_end', 'finalize_begin', 'finalize_end']
    with pytest.raises(InvalidRequest):
        worker.require_publication_finalization(controller, deadline=end)


@pytest.mark.parametrize('changes', [dict(state='prepared', published=False),
    dict(published=False), dict(revision_id=None), dict(generation_id=None)])
def test_terminal_result_rejects_contradictory_or_missing_identity(changes):
    result = dict(intent_id='intent', operation='publish', state='published',
        revision_id='revision', generation_id='generation', authority_committed=True,
        replica_complete=True, published=True, purge_complete=False)
    with pytest.raises(InvalidRequest):
        worker._public_result(dict(result, **changes), 'intent')


@run_async
async def test_channel_close_failure_is_redacted_after_child_has_exited(tmp_path):
    from types import SimpleNamespace
    actual = ManagedQdrantSupervisor(tmp_path/'qdrant', tmp_path/'work', 'instance', config())
    async def authorize(*args):
        return True
    host = worker.ManagedQdrantPublicationWorkerHost(actual, authorize)
    async def broken_close():
        raise ConnectionResetError('PRIVATE_CHANNEL_CLEANUP_DETAIL')
    worker._HOSTS[host].channel = SimpleNamespace(close=broken_close)
    with pytest.raises(ProviderUnavailable) as failure:
        await host.close()
    assert 'PRIVATE_CHANNEL_CLEANUP_DETAIL' not in str(failure.value)


def test_import_constructor_and_forged_handles_are_inert(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError('unexpected_io')
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', forbidden)
    supervisor = ManagedQdrantSupervisor(tmp_path / 'binary', tmp_path / 'work', 'instance', config())
    host = worker.ManagedQdrantPublicationWorkerHost(supervisor, forbidden)
    assert worker._HOSTS[host].process is None and worker._HOSTS[host].active is None and not supervisor._initialized
    for value in (None, object(), {}, type('Lookalike', (), {})()):
        assert not worker.is_worker(value)
        with pytest.raises(InvalidRequest):
            worker.ManagedQdrantPublicationWorkerHost(value, forbidden)
    with pytest.raises(InvalidRequest):
        worker.OwnedPublicationWorker(object(), object())
    with pytest.raises(InvalidRequest):
        worker.OrdinaryWorkerController(object(), None, {}, {}, 1)
    forged = object.__new__(worker.OwnedPublicationWorker)
    with pytest.raises(InvalidRequest):
        forged._process()


@pytest.mark.parametrize('raw', [b'{"a":1,"a":2}', b'NaN', b'Infinity', b'1e999', b'{}{}', b'\xff'])
def test_strict_json_rejects_duplicates_nonfinite_trailing_invalid_utf8(raw):
    with pytest.raises(InvalidRequest):
        worker._decode(raw)


def test_job_exact_snapshot_paths_scope_and_secret_surface():
    original = job()
    frozen = worker._job(original)
    original['scope']['grant_ids'].append('changed')
    assert 'changed' not in frozen['scope']['grant_ids']
    for extra in ('executable', 'environment', 'code', 'password', 'supervisor_pool'):
        with pytest.raises(InvalidRequest):
            worker._job(dict(job(), **{extra: 'forbidden'}))
    bad = job()
    bad['writer_pool']['passfile'] = '/' + 'x' * 4096
    with pytest.raises(InvalidRequest):
        worker._job(bad)
    bad = job()
    bad['reference']['owner_token'] = 'untrusted'
    with pytest.raises(InvalidRequest):
        worker._job(bad)


@run_async
async def test_fragmented_frame_and_oversize_checked_before_body():
    reader = asyncio.StreamReader()
    stream = Stream()
    selected = worker._Channel(reader, stream)
    encoded = frame({'v': 1, 'data': 'café 雪'})
    async def feed():
        for part in (encoded[:1], encoded[1:3], encoded[3:7], encoded[7:]):
            reader.feed_data(part)
            await asyncio.sleep(0)
    feeding = asyncio.create_task(feed())
    assert await selected.receive(deadline()) == {'v': 1, 'data': 'café 雪'}
    await feeding
    for length in (0, 65537, 4294967295):
        with pytest.raises(InvalidRequest):
            await channel(struct.pack('!I', length)).receive(deadline())


@run_async
async def test_total_direction_bounds_and_duplicate_out_of_order_reply():
    selected = channel()
    selected.sent = worker._MAX_TOTAL - 4
    with pytest.raises(InvalidRequest):
        await selected.send({}, deadline())
    for reply in ({'v': 1, 'id': 2, 'ok': True, 'data': {}},
                  {'v': 1, 'id': True, 'ok': True, 'data': {}},
                  {'v': 1, 'id': 1, 'ok': True, 'data': {}, 'extra': 1},
                  {'v': 1, 'id': 1, 'ok': False, 'error': 'secret'}):
        with pytest.raises(InvalidRequest):
            await channel(frame(reply)).rpc('profile', {}, deadline())
    selected = channel(frame({'v': 1, 'id': 1, 'ok': True, 'data': {}}))
    selected.pending = True
    with pytest.raises(ProviderUnavailable):
        await selected.rpc('profile', {}, deadline())


@run_async
async def test_large_valid_bootstrap_and_invalid_offsets_digest():
    value = {'v': 1, 'job': job(), 'identity': identity(), 'remaining_ms': 1000}
    value['job']['scope']['grant_ids'] = ['\x01' * 250 + str(index).zfill(2) for index in range(64)]
    # The unchanged trusted-scope contract admits this payload larger than one frame.
    parsed = worker._job(value['job'])
    assert len(worker._bytes(parsed)) > 65536
    outbound = channel()
    await worker._send_boot(outbound, value, deadline())
    assert await worker._read_boot(channel(bytes(outbound.writer.data)), deadline()) == value
    messages = []
    data = bytes(outbound.writer.data)
    while data:
        length = struct.unpack('!I', data[:4])[0]
        messages.append(worker._decode(data[4:4 + length]))
        data = data[4 + length:]
    for mutation in ('offset', 'digest', 'duplicate', 'oversize'):
        damaged = copy.deepcopy(messages)
        if mutation == 'offset':
            damaged[1]['offset'] = 1
        elif mutation == 'digest':
            damaged[0]['sha256'] = '0' * 64
        elif mutation == 'duplicate':
            damaged.insert(2, copy.deepcopy(damaged[1]))
        else:
            damaged[0]['total'] = worker._MAX_BOOT + 1
        with pytest.raises(InvalidRequest):
            await worker._read_boot(channel(b''.join(frame(item) for item in damaged)), deadline())


class RPC:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
    async def rpc(self, op, data, end):
        self.calls.append((op, copy.deepcopy(data)))
        return self.replies.pop(0)


@run_async
async def test_controller_immutable_once_credential_and_local_handle_close():
    from cragkit.qdrant_publication import ManagedQdrantPublicationTransport
    selected_job = worker._job(job())
    binding = {key: identity()[key] for key in ('instance_id', 'storage_identity', 'supervisor_id', 'epoch', 'credential_generation')}
    binding.update(intent_id=selected_job['reference']['intent_id'], owner_token=ctx()['owner_token'], dispatch_id='dispatch')
    rpc = RPC([dict(attempt_id=1, binding=binding, endpoint='http://127.0.0.1:6333', api_key='fixed-key'), {'binding': binding}, {'binding': binding}])
    controller = worker.OrdinaryWorkerController(worker._BOOT_TOKEN, rpc, selected_job, identity(), deadline())
    transport = ManagedQdrantPublicationTransport(controller)
    session = await transport._open({key: binding[key] for key in ('intent_id', 'owner_token', 'epoch', 'dispatch_id')}, deadline=deadline())
    await transport._close(session)
    # Closing a batch handle preserves its selected attempt for ordinary F1 readback.
    assert await worker.controller_attempt(controller, session.attempt, deadline=deadline()) == binding
    handle = controller.transport_for(session.attempt)
    assert worker._HTTP[handle].record['api_key'] == 'fixed-key'
    assert [op for op, _ in rpc.calls] == ['issue', 'validate', 'validate']
    await handle.close()
    await transport.close()
    await controller.close()
    assert not worker.is_worker(controller)


@run_async
async def test_authorizer_pinned_scope_target_and_current_receipt_validation():
    selected_job = worker._job(job())
    rpc = RPC([{'allowed': True}])
    controller = worker.OrdinaryWorkerController(worker._BOOT_TOKEN, rpc, selected_job, identity(), deadline())
    trusted = TrustedScope.model_validate(selected_job['scope'])
    assert await controller.authorize(trusted, selected_job['reference']['collection'], selected_job['reference']['document_id'])
    with pytest.raises(Exception):
        await controller.authorize(trusted, 'foreign', selected_job['reference']['document_id'])
    assert len(rpc.calls) == 1
    verifier = object.__new__(verification.QdrantPublicationVerifier)
    attempt = worker._Attempt()
    binding = {'current': 'binding'}
    worker._CONTROLLERS[controller].attempts[attempt] = {'attempt_id': 1, 'binding': binding}
    verification._VERIFIERS[verifier] = (object(), controller)
    receipt = verification.PublicationReadbackReceipt()
    verification._RECEIPTS[receipt] = (verifier, attempt, MappingProxyType({'attempt_binding': binding}))
    with pytest.raises(InvalidRequest):
        verification.publication_receipt_data(receipt, verifier)
    rpc.replies.append({'binding': binding})
    assert (await verification.validate_publication_receipt(receipt, verifier, deadline=deadline()))['attempt_binding'] == binding
    rpc.replies.append({'binding': {'current': 'changed'}})
    with pytest.raises(ProviderUnavailable):
        await verification.validate_publication_receipt(receipt, verifier, deadline=deadline())
    await controller.close()


@run_async
async def test_parent_ledger_exhaustion_precedes_spawn(monkeypatch, tmp_path):
    supervisor = ManagedQdrantSupervisor(tmp_path / 'binary', tmp_path / 'work', 'instance', config())
    monkeypatch.setattr(supervisor, 'profile_binding', lambda _: identity())
    async def forbidden(*args, **kwargs):
        raise AssertionError('spawned')
    host = worker.ManagedQdrantPublicationWorkerHost(supervisor, forbidden)
    monkeypatch.setattr(type(host), '_publish', forbidden)
    ledger = ExecutionLedger(Limits(max_attempts=1), deadline=deadline())
    reservation = ledger.reserve(attempts=1)
    ledger.dispatch(reservation)
    ledger.reconcile(reservation)
    with pytest.raises(BudgetExhausted):
        await host.publish(job(), ledger, deadline=deadline())
    assert worker._HOSTS[host].process is None and ledger.snapshot()['attempts'] == 1
    await host.close()
    assert not supervisor._closed


class Process:
    def __init__(self, fails=False):
        self.returncode = None
        self.fails = fails
        self.killed = 0
    def kill(self):
        self.killed += 1
        if self.fails:
            raise OSError('PRIVATE_KILL_FAILURE')
    async def wait(self):
        self.returncode = -9
        return -9


class Session:
    def __init__(self):
        self.released = False
    async def __aexit__(self, *args):
        self.released = True


@run_async
async def test_kill_failure_poison_retains_session_until_reap_retry(monkeypatch, tmp_path):
    supervisor = ManagedQdrantSupervisor(tmp_path / 'binary', tmp_path / 'work', 'instance', config())
    host = worker.ManagedQdrantPublicationWorkerHost(supervisor, lambda *args: None)
    worker._HOSTS[host].process = Process(fails=True)
    worker._HOSTS[host].held = held = Session()
    with pytest.raises(ProviderUnavailable):
        await host.close()
    assert worker._HOSTS[host].poisoned and host in worker._POISONED and worker._HOSTS[host].held is held and not held.released
    worker._HOSTS[host].process.fails = False
    await host.close()
    assert held.released and worker._HOSTS[host].held is None and host not in worker._POISONED
    assert not supervisor._closed


@run_async
async def test_cleanup_reaps_before_callback_drain_and_session_release(tmp_path):
    supervisor = ManagedQdrantSupervisor(tmp_path / 'binary', tmp_path / 'work', 'instance', config())
    host = worker.ManagedQdrantPublicationWorkerHost(supervisor, lambda *args: None)
    worker._HOSTS[host].process = Process()
    worker._HOSTS[host].held = held = Session()
    finished = []
    async def callback():
        try:
            await asyncio.Future()
        finally:
            finished.append(worker._HOSTS[host].process.returncode)
    worker._HOSTS[host].callback = asyncio.create_task(callback())
    await asyncio.sleep(0)
    await host.close()
    assert finished == [-9] and held.released


@run_async
async def test_parent_failure_abandons_attempt_without_provider_candidate_charge(monkeypatch, tmp_path):
    supervisor = ManagedQdrantSupervisor(tmp_path / 'binary', tmp_path / 'work', 'instance', config())
    monkeypatch.setattr(supervisor, 'profile_binding', lambda _: identity())
    host = worker.ManagedQdrantPublicationWorkerHost(supervisor, lambda *args: None)
    async def failed(*args):
        raise ProviderUnavailable()
    monkeypatch.setattr(type(host), '_publish', failed)
    accounting = ExecutionLedger(Limits(), deadline=deadline())
    with pytest.raises(ProviderUnavailable):
        await host.publish(job(), accounting, deadline=deadline())
    state = accounting.snapshot()
    assert state['attempts'] == 1 and state['provider_calls'] == state['candidates'] == state['pending'] == 0
    await host.close()


@run_async
async def test_fixed_key_http401_is_observed_without_validation_or_refresh(monkeypatch):
    import sys
    from types import SimpleNamespace
    from cragkit.errors import UnauthorizedScope
    calls = []
    class Response:
        status_code = 401
        headers = {}
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def aiter_raw(self, **kwargs):
            yield b'{}'
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        def stream(self, method, path, **kwargs):
            calls.append(('http', method, path, kwargs['headers']['api-key']))
            return Response()
        async def aclose(self):
            pass
    monkeypatch.setitem(sys.modules, 'httpx', SimpleNamespace(AsyncClient=Client,
        AsyncHTTPTransport=lambda **kwargs: None, Limits=lambda **kwargs: None))
    selected_job = worker._job(job())
    class ControlRPC(RPC):
        async def rpc(self, op, data, end):
            calls.append((op, data))
            return {}
    control = worker.OrdinaryWorkerController(worker._BOOT_TOKEN, ControlRPC([]), selected_job, identity(), deadline())
    attempt = worker._Attempt()
    record = dict(attempt_id=1, endpoint='http://127.0.0.1:6333', api_key='captured-old-key',
        binding={'dispatch_id': 'dispatch'})
    worker._CONTROLLERS[control].attempts[attempt] = record
    handle = control.transport_for(attempt)
    await control.before_write(attempt, {'dispatch_id': 'dispatch', 'sequence': 1, 'request_sha256': '0' * 64}, deadline=deadline())
    with pytest.raises(UnauthorizedScope):
        await handle.request('PUT', '/collections/' + selected_job['config']['physical_collection'] + '/points?wait=true&ordering=strong', body=b'{}', deadline=deadline())
    assert [call[0] for call in calls] == ['before_write', 'http', 'write_observed']
    assert calls[1][-1] == 'captured-old-key' and calls[2][1]['status'] == 401
    await handle.close()
    await control.close()


@run_async
async def test_worker_stage_is_unsupported_and_null_authority_requires_worker(monkeypatch, tmp_path):
    from cragkit.qdrant_publication import (QdrantPublicationManager, ManagedQdrantPublicationTransport,
        PostgresQdrantPublicationAuthority)
    from test_qdrant_publication_verification import setup
    from test_qdrant_writer import stage_input
    writer, supervisor, *_ = await setup(monkeypatch, tmp_path)
    authority = PostgresQdrantPublicationAuthority(writer, None)
    async def authorize(*args):
        return True
    with pytest.raises(InvalidRequest):
        QdrantPublicationManager(authority, ManagedQdrantPublicationTransport(supervisor), config(), supervisor, authorize)
    selected_job = worker._job(job())
    controller = worker.OrdinaryWorkerController(worker._BOOT_TOKEN, RPC([]), selected_job, identity(), deadline())
    manager = QdrantPublicationManager(authority, ManagedQdrantPublicationTransport(controller), config(), controller, authorize)
    with pytest.raises(UnsupportedCapability):
        await manager.stage(stage_input(), selected_job['scope'], ExecutionLedger(Limits(), deadline=deadline()), deadline=deadline())
    await manager.close()
    await controller.close()


@run_async
async def test_parent_success_reconciles_only_after_owned_cleanup(monkeypatch, tmp_path):
    supervisor = ManagedQdrantSupervisor(tmp_path / 'binary', tmp_path / 'work', 'instance', config())
    monkeypatch.setattr(supervisor, 'profile_binding', lambda _: identity())
    host = worker.ManagedQdrantPublicationWorkerHost(supervisor, lambda *args: None)
    events = []
    result = dict(intent_id=ctx()['intent_id'], operation='publish', state='published', revision_id='revision', generation_id='generation',
        authority_committed=True, replica_complete=True, published=True, purge_complete=False)
    async def finished(*args):
        events.append('reaped')
        return result
    async def cleanup(*args):
        events.append('cleanup')
    monkeypatch.setattr(type(host), '_publish', finished)
    monkeypatch.setattr(type(host), '_cleanup', cleanup)
    accounting = ExecutionLedger(Limits(), deadline=deadline())
    assert await host.publish(job(), accounting, deadline=deadline()) == result
    assert events[:2] == ['reaped', 'cleanup']
    assert accounting.snapshot()['attempts'] == 1 and accounting.snapshot()['pending'] == 0


@run_async
async def test_owned_diagnostics_use_only_owned_signals_and_reap(monkeypatch):
    class OwnedProcess(Process):
        pid = 123
        def __init__(self):
            super().__init__()
            self.signals = []
        def send_signal(self, selected):
            self.signals.append(selected)
    class Probe:
        returncode = 0
        async def communicate(self):
            return b'T\n', b''
    async def probe(*args, **kwargs):
        assert args == ('/bin/ps', '-o', 'stat=', '-p', '123')
        return Probe()
    monkeypatch.setattr(asyncio, 'create_subprocess_exec', probe)
    process = OwnedProcess()
    handle = worker.OwnedPublicationWorker(worker._BOOT_TOKEN, process)
    await handle.pause(deadline=deadline())
    await handle.resume(deadline=deadline())
    assert process.signals == [worker.signal.SIGSTOP, worker.signal.SIGCONT]
    await handle.terminate(deadline=deadline())
    assert process.returncode == -9 and process.killed == 1
    with pytest.raises(InvalidRequest):
        await handle.resume(deadline=deadline())


@run_async
async def test_cancellation_abandons_parent_budget_and_rejects_expiry(monkeypatch, tmp_path):
    from cragkit.errors import DeadlineExceeded
    supervisor = ManagedQdrantSupervisor(tmp_path / 'binary', tmp_path / 'work', 'instance', config())
    monkeypatch.setattr(supervisor, 'profile_binding', lambda _: identity())
    host = worker.ManagedQdrantPublicationWorkerHost(supervisor, lambda *args: None)
    started = asyncio.Event()
    async def pending(*args):
        started.set()
        await asyncio.Future()
    monkeypatch.setattr(type(host), '_publish', pending)
    accounting = ExecutionLedger(Limits(), deadline=deadline())
    task = asyncio.create_task(host.publish(job(), accounting, deadline=deadline()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert accounting.snapshot()['attempts'] == 1 and accounting.snapshot()['pending'] == 0
    with pytest.raises(DeadlineExceeded):
        await host.publish(job(), accounting, deadline=asyncio.get_running_loop().time() - 1)
    await host.close()


def test_job_rejects_custom_containers_and_huge_values_before_serialization(monkeypatch):
    class Custom(dict):
        def items(self):
            raise AssertionError('custom_hook_ran')
    with pytest.raises(InvalidRequest):
        worker._job(Custom(job()))
    for value in ({'nested': Custom()}, {'large': 'x' * (worker._MAX_BOOT + 1)}, {'integer': 10 ** 1000}):
        with pytest.raises(InvalidRequest):
            worker._native_bounds(value)
    cyclic = {}
    cyclic['itself'] = cyclic
    with pytest.raises(InvalidRequest):
        worker._native_bounds(cyclic)
    with pytest.raises(InvalidRequest):
        worker._identity(Custom(identity()))


@run_async
async def test_private_controller_origin_and_readonly_job_cannot_be_rebound():
    import copy
    original_job = worker._job(job())
    original_identity = identity()
    original_rpc = RPC([{'allowed': True}])
    controller = worker.OrdinaryWorkerController(worker._BOOT_TOKEN, original_rpc, original_job, original_identity, deadline())
    for name, value in (('channel', RPC([])), ('job', {}), ('identity', {}), ('deadline', 1), ('attempts', {}), ('closed', False)):
        with pytest.raises(AttributeError):
            setattr(controller, name, value)
    for copier in (copy.copy, copy.deepcopy):
        with pytest.raises(TypeError):
            copier(controller)
    # Mutating caller constructor objects or the property copy never changes the pinned state.
    original_job['scope']['tenant_id'] = 'foreign'
    original_identity['credential_generation'] = 'replacement'
    exposed = controller.job
    exposed['scope']['tenant_id'] = 'another-foreign'
    pinned = worker._CONTROLLERS[controller]
    assert pinned.identity['credential_generation'] == 'credential'
    assert pinned.job['scope']['tenant_id'] == ctx()['scope']['tenant_id']
    trusted = TrustedScope.model_validate(pinned.job['scope'])
    assert await controller.authorize(trusted, pinned.job['reference']['collection'], pinned.job['reference']['document_id'])
    assert len(original_rpc.calls) == 1
    forged = object.__new__(worker.OrdinaryWorkerController)
    with pytest.raises(InvalidRequest):
        await forged.issue_attempt({}, deadline=deadline())
    await controller.close()


@run_async
async def test_host_original_process_and_borrowed_dependencies_cannot_be_replaced(tmp_path):
    import copy
    original_supervisor = ManagedQdrantSupervisor(tmp_path / 'binary', tmp_path / 'work', 'instance', config())
    async def authorize(*args):
        return True
    host = worker.ManagedQdrantPublicationWorkerHost(original_supervisor, authorize)
    replacement = Process()
    for name, value in (('supervisor', object()), ('authorize_write', lambda *args: False),
            ('process', replacement), ('channel', object()), ('held', Session()), ('active', None), ('closed', False)):
        with pytest.raises(AttributeError):
            setattr(host, name, value)
    for copier in (copy.copy, copy.deepcopy):
        with pytest.raises(TypeError):
            copier(host)
    forged = object.__new__(worker.ManagedQdrantPublicationWorkerHost)
    with pytest.raises(InvalidRequest):
        await forged.close()
    assert worker._HOSTS[host].supervisor is original_supervisor
    assert worker._HOSTS[host].authorize_write is authorize
    await host.close()
    assert replacement.killed == 0 and not original_supervisor._closed


@run_async
async def test_http_handle_original_channel_and_key_are_not_caller_replaceable():
    selected = worker._job(job())
    controller = worker.OrdinaryWorkerController(worker._BOOT_TOKEN, RPC([]), selected, identity(), deadline())
    attempt = worker._Attempt()
    record = dict(attempt_id=1, endpoint='http://127.0.0.1:6333', api_key='original-key', binding={'dispatch_id': 'dispatch'})
    worker._CONTROLLERS[controller].attempts[attempt] = record
    handle = controller.transport_for(attempt)
    for name, value in (('controller', object()), ('record', {'api_key': 'replacement'}), ('client', object()), ('closed', False)):
        with pytest.raises(AttributeError):
            setattr(handle, name, value)
    forged = object.__new__(worker._WorkerHTTP)
    with pytest.raises(InvalidRequest):
        await forged.request('GET', '/collections/x', deadline=deadline())
    await handle.close()
    await controller.close()


@run_async
async def test_reserved_controller_uses_closed_rpc_and_rejects_foreign_attempt():
    rpc = RPC([{}])
    controller = worker.OrdinaryWorkerController(worker._BOOT_TOKEN, rpc, worker._job(job()), identity(), deadline())
    attempt = worker._Attempt()
    worker._CONTROLLERS[controller].attempts[attempt] = {'attempt_id': 1}
    payload = dict(dispatch_id='dispatch', sequence=1, request_sha256='a' * 64)
    await controller.reserved(attempt, payload, deadline=deadline())
    assert rpc.calls == [('reserved', dict(attempt_id=1, **payload))]
    with pytest.raises(InvalidRequest):
        await controller.reserved(worker._Attempt(), payload, deadline=deadline())
    await controller.close()


def test_reserved_barrier_requires_exact_order_identity_and_single_use():
    reservations, written = {}, set()
    payload = dict(attempt_id=1, dispatch_id='dispatch', sequence=3, request_sha256='a' * 64)
    binding = {'dispatch_id': 'dispatch'}
    with pytest.raises(InvalidRequest):
        worker._admit_barrier('before_write', payload, binding, reservations, written)
    for changes in ({'dispatch_id': 'forged'}, {'sequence': 0}, {'request_sha256': 'A' * 64}, {'extra': True}):
        with pytest.raises(InvalidRequest):
            worker._admit_barrier('reserved', dict(payload, **changes), binding, reservations, written)
    worker._admit_barrier('reserved', payload, binding, reservations, written)
    for op, changes in (('reserved', {}), ('before_write', {'request_sha256': 'b' * 64}),
                        ('before_write', {'sequence': 4}), ('reserved', {'attempt_id': 2, 'sequence': 2})):
        with pytest.raises(InvalidRequest):
            worker._admit_barrier(op, dict(payload, **changes), binding, reservations, written)
    worker._admit_barrier('before_write', payload, binding, reservations, written)
    with pytest.raises(InvalidRequest):
        worker._admit_barrier('before_write', payload, binding, reservations, written)
    assert written == {1} and reservations == {1: payload}
