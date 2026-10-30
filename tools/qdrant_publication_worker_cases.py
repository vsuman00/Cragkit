"""Real native publication child acceptance; separate from the complete H matrix."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

CHECKS = (
    'actual_child_publish_and_exit_preserves_parent_supervisor',
    'historical_retry_runs_child_without_physical_rewrite',
    'exhausted_parent_ledger_preserves_durable_state',
    'committed_dispatch_then_owned_worker_sigkill_preserves_previous_generation',
    'fixed_child_channel_eof_preserves_uncertainty_without_http',
    'independent_document_worker_pauses_after_dispatch_before_http',
    'same_supervisor_durable_recovery_retires_paused_worker_key_with_actual_401',
    'retired_worker_cannot_refresh_credential_or_publish',
    'host_close_preserves_supervisor_and_reaps_owned_children',
)
ERRORS = frozenset(('IntegrityViolation', 'UnauthorizedScope', 'UnsupportedCapability',
    'InvalidRequest', 'ProviderUnavailable', 'DeadlineExceeded', 'IndexNotReady',
    'BudgetExhausted', 'CancelledError', 'AbortError', 'internal'))


class NativePublicationWorkerFailure(RuntimeError):
    def __init__(self, observation):
        super().__init__('publication_worker_native_case_failed')
        self.observation = observation


def publication_worker_input():
    from cragkit._qdrant_contract import point_id
    from cragkit._qdrant_manifest import encode_manifest
    from qdrant_recovery_cases import recovery_input
    from qdrant_writer_cases import successor_stage
    inputs = recovery_input()
    inputs['successor'] = successor_stage(inputs, 'worker-kill', inputs['stage']['manifest']['generation_id'])
    stage = deepcopy(inputs['second_stage'])
    manifest = stage['manifest']
    manifest.update(tenant_id='tenant-worker-eof', document_id='doc-worker-eof',
        revision_id='rev-worker-eof', generation_id='gen-worker-eof')
    for member in manifest['members']:
        member['point_id'] = point_id(['cragkit.qdrant.point.v1', manifest['backend_namespace'],
            manifest['physical_collection'], manifest['collection_incarnation'], manifest['tenant_id'],
            manifest['collection'], manifest['document_id'], manifest['revision_id'], manifest['generation_id'],
            member['chunk_id'], manifest['dense_profile']['profile_id'], manifest['sparse_profile']['profile_id']])
    stage['intent'].update(tenant_id=manifest['tenant_id'], document_id=manifest['document_id'],
        intent_id='intent-worker-eof', manifest_sha256=encode_manifest(manifest, stage['canonical_text']).sha256)
    points = deepcopy(inputs['second_points'])
    for point, member in zip(points, manifest['members'], strict=True):
        point['id'] = member['point_id']
        point['payload'].update({key: manifest[key] for key in
            ('tenant_id', 'document_id', 'revision_id', 'generation_id')})
    inputs.update(eof_stage=stage, eof_scope=dict(inputs['scope'], tenant_id=manifest['tenant_id']),
        eof_points=points)
    return inputs


async def python_publication_worker_cases(value):
    import asyncio
    import json
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit.contracts import Limits, TrustedScope
    from cragkit.execution import ExecutionLedger, BudgetExhausted
    from cragkit.errors import ProviderUnavailable, UnauthorizedScope
    from cragkit.qdrant_publication import (QdrantPublicationManager,
        PostgresQdrantPublicationAuthority, ManagedQdrantPublicationTransport,
        ManagedQdrantPublicationWorkerHost, PostgresQdrantWriter, PostgresQdrantRecovery,
        ManagedQdrantSupervisor, QdrantReconciliationVerifier)
    from qdrant_supervisor_cases import plain, request_bytes, observed_listener

    inputs = value['inputs']
    def configuration(raw):
        raw = dict(raw)
        for key in ('sslrootcert', 'passfile'):
            raw[key] = Path(raw[key])
        config = PoolConfig.model_validate(raw)
        if config.max_size != 1:
            raise RuntimeError('worker_fixture_pool_ceiling')
        return config
    writer_config, supervisor_config = configuration(value['writer_config']), configuration(value['supervisor_config'])
    supervisor_resource = PoolResource(supervisor_config)
    supervisor = ManagedQdrantSupervisor(Path(value['binary']), Path(value['work_dir']),
        inputs['instance_id'], inputs['config'])
    scopes = [TrustedScope.model_validate(inputs[key]) for key in ('scope', 'second_scope', 'eof_scope')]
    stages = [inputs['stage'], inputs['second_stage'], inputs['eof_stage']]
    permitted = {(scope.tenant_id, scope.principal_id, scope.authorization_revision,
        tuple(scope.grant_ids), stage['manifest']['collection'], stage['manifest']['document_id'])
        for scope, stage in zip(scopes, stages, strict=True)}
    deadline = asyncio.get_running_loop().time() + 145
    target = '/collections/' + inputs['config']['physical_collection']
    checks, results, parents = [], [], []
    endpoint = primary = host = worker_job = None
    paused_worker = None
    current = None

    async def authorize(scope, collection, document):
        return (scope.tenant_id, scope.principal_id, scope.authorization_revision,
            tuple(scope.grant_ids), collection, document) in permitted
    def reference(stage):
        return {key: stage['intent'][key] for key in ('collection', 'document_id', 'intent_id')}
    def context(stage, scope):
        return dict(scope=scope, **reference(stage), owner_token='00000000-0000-4000-8000-000000000099')
    def ledger(attempts=1):
        return ExecutionLedger(Limits(deadline_ms=60000, max_attempts=attempts, max_provider_calls=0), deadline=deadline)
    def job(stage, scope):
        return dict(writer_pool=dict(value['writer_config']), config=deepcopy(inputs['config']),
            scope=scope.model_dump(mode='json'), reference=reference(stage),
            limits=Limits(deadline_ms=60000, max_attempts=1, max_provider_calls=0).model_dump(mode='json'))
    def record(result):
        fields = ('intent_id', 'operation', 'state', 'revision_id', 'generation_id',
            'authority_committed', 'replica_complete', 'published', 'purge_complete')
        result = plain(result)
        if set(result) != set(fields) or any(type(result[key]) is not bool for key in fields[5:]):
            raise RuntimeError('worker_public_result')
        results.append([result[key] for key in fields])
        return result
    def usage(book, attempts=1):
        state = book.snapshot()
        if any(state[key] != expected for key, expected in
                (('attempts', attempts), ('provider_calls', 0), ('candidates', 0), ('pending', 0))):
            raise RuntimeError('worker_parent_accounting')
    async def provision(admin, probe):
        await admin.request('PUT', target, body=request_bytes(inputs['collection_config']), deadline=deadline)
        probe = plain(probe)
        path = '/collections/' + probe['collection']
        await admin.request('PUT', path, body=request_bytes(probe['collection_config']), deadline=deadline)
        raw = json.loads(await admin.request('PUT', path + '/points?wait=true&ordering=strong',
            body=request_bytes({'points': [probe['point']]}), deadline=deadline))
        if raw.get('result', {}).get('status') != 'completed':
            raise RuntimeError('worker_fixture_probe_ack')
    async def open_parent():
        nonlocal current
        if current is not None:
            raise RuntimeError('worker_parent_bundle_overlap')
        resource = PoolResource(writer_config)
        writer = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
        verifier = QdrantReconciliationVerifier(writer, supervisor)
        recovery = PostgresQdrantRecovery(supervisor_resource, inputs['config'], supervisor, verifier)
        transport = ManagedQdrantPublicationTransport(supervisor)
        manager = QdrantPublicationManager(PostgresQdrantPublicationAuthority(writer, recovery),
            transport, inputs['config'], supervisor, authorize)
        current = dict(resource=resource, writer=writer, verifier=verifier, recovery=recovery,
            transport=transport, manager=manager)
        parents.append(current)
        await resource.open()
        await manager.initialize(deadline=deadline)
        return current
    async def close_parent():
        nonlocal current
        bundle, current = current, None
        if bundle is None:
            return
        for key in ('manager', 'transport', 'recovery', 'verifier', 'writer', 'resource'):
            close = getattr(bundle[key], 'close', None)
            if callable(close):
                await asyncio.wait_for(close(), 5)
    async def fail(operation):
        try:
            await operation
        except (ProviderUnavailable, UnauthorizedScope):
            return
        raise RuntimeError('worker_expected_failure_missing')
    async def snapshot(bundle, stage, scope, expected_active, pending):
        result = await bundle['writer'].manager_snapshot(context(stage, scope), deadline=deadline)
        if result['document']['active_generation_id'] != expected_active or result['pending'] is not pending:
            raise RuntimeError('worker_authority_snapshot')
        return result
    def barrier_event(event, events):
        if event['kind'] == 'reserved':
            if (events or event['attempt_id'] != 1 or event['sequence'] != 1
                    or type(event['dispatch_id']) is not str or not event['dispatch_id']
                    or type(event['request_sha256']) is not str or len(event['request_sha256']) != 64
                    or any(char not in '0123456789abcdef' for char in event['request_sha256'])):
                raise RuntimeError('worker_reserved_marker_invalid')
        elif (len(events) != 1 or events[0]['kind'] != 'reserved'
                or dict(event, kind='reserved') != events[0]):
            raise RuntimeError('worker_reserved_before_write_mismatch')
        events.append(event)
    def write_event(event, events):
        if (len(events) != 2 or events[1]['kind'] != 'before_write'
                or event['attempt_id'] != events[1]['attempt_id']
                or event['dispatch_id'] != events[1]['dispatch_id']):
            raise RuntimeError('worker_write_observation_barrier_mismatch')
    try:
        await supervisor.initialize(deadline=deadline, provision=provision)
        endpoint = supervisor.identity()['endpoint']
        first_pid = await observed_listener(endpoint)
        original_identity = dict(supervisor.control_binding())
        await supervisor_resource.open()
        bundle = await open_parent()
        await bundle['manager'].stage(inputs['stage'], scopes[0], ledger(), deadline=deadline)
        await close_parent()
        host = ManagedQdrantPublicationWorkerHost(supervisor, authorize)
        observed = []
        normal_barriers = []
        async def observe(event, worker):
            event = plain(event)
            if event['kind'] in ('reserved', 'before_write'):
                barrier_event(event, normal_barriers)
            elif event['kind'] == 'write_observed':
                write_event(event, normal_barriers)
                observed.append(event['status'])
        book = ledger()
        result = record(await host.publish(job(inputs['stage'], scopes[0]), book, deadline=deadline, observer=observe))
        usage(book)
        if (result['published'] is not True or result['state'] != 'published'
                or observed != [200] or len(normal_barriers) != 2):
            raise RuntimeError('worker_actual_child_publication')
        if dict(supervisor.control_binding()) != original_identity or await observed_listener(endpoint) != first_pid:
            raise RuntimeError('worker_parent_supervisor_replaced')
        checks.append(CHECKS[0])
        observed.clear()
        normal_barriers.clear()
        book = ledger()
        historical = record(await host.publish(job(inputs['stage'], scopes[0]), book, deadline=deadline, observer=observe))
        usage(book)
        if historical != result or observed or normal_barriers:
            raise RuntimeError('worker_historical_rewrite')
        checks.append(CHECKS[1])
        book = ledger()
        prior = book.reserve(attempts=1)
        book.dispatch(prior)
        book.reconcile(prior)
        try:
            await host.publish(job(inputs['stage'], scopes[0]), book, deadline=deadline, observer=observe)
        except BudgetExhausted:
            pass
        else:
            raise RuntimeError('worker_budget_not_enforced')
        usage(book)
        if observed or normal_barriers:
            raise RuntimeError('worker_budget_mutation')
        checks.append(CHECKS[2])
        bundle = await open_parent()
        await bundle['manager'].stage(inputs['successor'], scopes[0], ledger(), deadline=deadline)
        await close_parent()
        barrier = []
        async def kill(event, worker):
            event = plain(event)
            if event['kind'] == 'write_observed':
                raise RuntimeError('worker_killed_child_sent_http')
            if event['kind'] in ('reserved', 'before_write'):
                barrier_event(event, barrier)
            if event['kind'] == 'before_write':
                await worker.terminate(deadline=min(deadline, asyncio.get_running_loop().time() + 5))
        book = ledger()
        await fail(host.publish(job(inputs['successor'], scopes[0]), book, deadline=deadline, observer=kill))
        usage(book)
        if len(barrier) != 2:
            raise RuntimeError('worker_crash_marker_missing')
        bundle = await open_parent()
        state = await snapshot(bundle, inputs['successor'], scopes[0], inputs['stage']['manifest']['generation_id'], True)
        status = await bundle['writer'].dispatch_status(context(inputs['successor'], scopes[0]), barrier[1]['dispatch_id'], deadline=deadline)
        if state['intent']['state'] != 'writing' or status is None or status['state'] not in ('dispatched', 'unknown'):
            raise RuntimeError('worker_crash_uncertainty_missing')
        if await observed_listener(endpoint) != first_pid:
            raise RuntimeError('worker_crash_killed_supervisor')
        checks.append(CHECKS[3])
        await bundle['manager'].stage(inputs['eof_stage'], scopes[2], ledger(), deadline=deadline)
        await close_parent()
        await _fixed_entry_eof(job(inputs['eof_stage'], scopes[2]), supervisor, deadline)
        bundle = await open_parent()
        state = await snapshot(bundle, inputs['eof_stage'], scopes[2], None, True)
        if state['intent']['state'] != 'writing':
            raise RuntimeError('worker_eof_published')
        # Check actual physical absence, not only absence of a diagnostic.
        attempt = supervisor.issue_attempt(dict(intent_id='eof-absence', owner_token=context(inputs['eof_stage'], scopes[2])['owner_token'],
            epoch=1, dispatch_id='eof-absence'), deadline=deadline)
        handle = supervisor.transport_for(attempt)
        try:
            points = json.loads(await handle.request('POST', target + '/points',
                body=request_bytes(dict(ids=[point['id'] for point in inputs['eof_points']], with_payload=True, with_vector=True)), deadline=deadline))
            if points.get('result') != []:
                raise RuntimeError('worker_eof_http_arrived')
        finally:
            await handle.close()
        checks.append(CHECKS[4])
        await bundle['manager'].stage(inputs['second_stage'], scopes[1], ledger(), deadline=deadline)
        await close_parent()
        reached = asyncio.Event()
        observations = []
        paused_barriers = []
        async def pause(event, worker):
            nonlocal paused_worker
            event = plain(event)
            if event['kind'] in ('reserved', 'before_write'):
                barrier_event(event, paused_barriers)
            if event['kind'] == 'before_write':
                await worker.pause(deadline=min(deadline, asyncio.get_running_loop().time() + 5))
                paused_worker = worker
                reached.set()
            elif event['kind'] == 'write_observed':
                write_event(event, paused_barriers)
                observations.append(event)
        book = ledger()
        worker_job = asyncio.create_task(host.publish(job(inputs['second_stage'], scopes[1]), book, deadline=deadline, observer=pause))
        arrived = asyncio.create_task(reached.wait())
        try:
            done, _ = await asyncio.wait((worker_job, arrived), timeout=15, return_when=asyncio.FIRST_COMPLETED)
            if arrived not in done:
                if worker_job.done():
                    await worker_job
                raise RuntimeError('worker_pause_not_reached')
        finally:
            arrived.cancel()
            await asyncio.gather(arrived, return_exceptions=True)
        if len(paused_barriers) != 2:
            raise RuntimeError('worker_pause_barriers_missing')
        checks.append(CHECKS[5])
        # Three max-one clients only in this explicit paused-E2 window.
        bundle = await open_parent()
        state = await snapshot(bundle, inputs['second_stage'], scopes[1], None, True)
        if state['intent']['state'] != 'writing':
            raise RuntimeError('worker_pause_not_durable')
        proof = await bundle['recovery'].recover('worker-native-recovery', deadline=deadline)
        binding = dict(supervisor.recovery_binding(proof))
        if binding['new_epoch'] != 2 or binding['credential_generation'] == original_identity['credential_generation']:
            raise RuntimeError('worker_retirement_missing')
        await paused_worker.resume(deadline=min(deadline, asyncio.get_running_loop().time() + 5))
        await fail(worker_job)
        worker_job = None
        usage(book)
        if len(observations) != 1 or observations[0]['status'] != 401:
            raise RuntimeError('worker_actual_retired_http_401_missing')
        checks.append(CHECKS[6])
        state = await snapshot(bundle, inputs['second_stage'], scopes[1], None, True)
        previous = await snapshot(bundle, inputs['successor'], scopes[0], inputs['stage']['manifest']['generation_id'], True)
        if (state['backend']['state'] != 'recovery_blocked' or state['backend']['epoch'] != 2
                or state['intent']['state'] == 'published' or previous['intent']['state'] == 'published'):
            raise RuntimeError('worker_retired_publication_or_reopen')
        checks.append(CHECKS[7])
        await host.close()
        if supervisor.control_binding()['alive'] is not True:
            raise RuntimeError('worker_host_closed_borrowed_supervisor')
        await observed_listener(endpoint)
        checks.append(CHECKS[8])
        return dict(runtime='python', checks=checks, proof_scope='ordinary_worker_process_only',
            public_results_sha256=sha256(request_bytes(results)).hexdigest())
    except BaseException as error:
        primary = error
        frame = error.__traceback__
        location = None
        while frame is not None:
            if frame.tb_frame.f_code.co_filename == __file__:
                location = frame.tb_lineno
            frame = frame.tb_next
        # Fixed fixture location only: never persist exception text or locals.
        (Path(value['work_dir']).parent.parent / 'python-failure-location.json').write_text(
            json.dumps(dict(step=len(checks), line=location)) + '\n')
        name = type(error).__name__
        raise NativePublicationWorkerFailure(dict(ok=False, step=len(checks), error=name if name in ERRORS else 'internal')) from None
    finally:
        failures = []
        end = asyncio.get_running_loop().time() + 15
        async def close(operation, action):
            try:
                await asyncio.wait_for(action(), max(.001, min(8, end - asyncio.get_running_loop().time())))
            except BaseException as error:
                failures.append(dict(operation=operation, outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if worker_job is not None:
            worker_job.cancel()
            await close('worker_drain', lambda: asyncio.gather(worker_job, return_exceptions=True))
        if host is not None:
            await close('host_close', host.close)
        for bundle in reversed(parents):
            for key in ('manager', 'transport', 'recovery', 'verifier', 'writer', 'resource'):
                action = getattr(bundle[key], 'close', None)
                if callable(action):
                    await close(key + '_close', action)
        await close('supervisor_resource_close', supervisor_resource.close)
        await close('controller_close', supervisor.close)
        if endpoint is not None:
            await close('listener_close', lambda: observed_listener(endpoint, allow_absent=True))
        if failures:
            name = type(primary).__name__ if primary is not None else None
            raise NativePublicationWorkerFailure(dict(ok=False, step=len(checks), error='cleanup_failed',
                primary=name if name in ERRORS else ('internal' if name else None), cleanup=failures[:64])) from None


async def _fixed_entry_eof(job, supervisor, deadline):
    """Close the real fixed child's private channel after its durable barrier."""
    import asyncio
    import base64
    import json
    import os
    import socket
    import struct
    import sys

    def raw(value):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    def digest(value):
        return sha256(raw(value)).hexdigest()
    parent, child = socket.socketpair()
    process = reader = stream = None
    attempts = {}
    reached = False
    reserved = None
    end = min(deadline, asyncio.get_running_loop().time() + 20)
    environment = {key: val for key, val in os.environ.items() if key in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL')}
    try:
        process = await asyncio.create_subprocess_exec(sys.executable, '-I', '-m', 'cragkit._qdrant_publication_worker', str(child.fileno()),
            pass_fds=(child.fileno(),), env=environment, stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        child.close()
        reader, stream = await asyncio.open_connection(sock=parent)
        async def send(value):
            payload = raw(value)
            if not 1 <= len(payload) <= 65536:
                raise RuntimeError('worker_eof_frame_bound')
            stream.write(struct.pack('!I', len(payload)) + payload)
            await asyncio.wait_for(stream.drain(), max(.001, end - asyncio.get_running_loop().time()))
        async def receive():
            length = struct.unpack('!I', await reader.readexactly(4))[0]
            if not 1 <= length <= 65536:
                raise RuntimeError('worker_eof_frame_bound')
            return json.loads(await reader.readexactly(length))
        boot = raw(dict(v=1, job=job, identity=dict(supervisor.profile_binding(job['config'])),
            remaining_ms=max(1, int((end - asyncio.get_running_loop().time()) * 1000))))
        if len(boot) > 262144:
            raise RuntimeError('worker_eof_boot_bound')
        await send(dict(v=1, op='boot_begin', total=len(boot), sha256=sha256(boot).hexdigest()))
        for offset in range(0, len(boot), 48000):
            await send(dict(v=1, op='boot_chunk', offset=offset, data=base64.b64encode(boot[offset:offset + 48000]).decode('ascii')))
        await send(dict(v=1, op='boot_end'))
        sequence = 0
        async with asyncio.timeout_at(end):
            for _ in range(32):
                message = await receive()
                sequence += 1
                if (type(message) is not dict or set(message) != {'v', 'id', 'op', 'remaining_ms', 'data'}
                        or message['v'] != 1 or message['id'] != sequence):
                    raise RuntimeError('worker_eof_request_shape')
                op, data = message['op'], message['data']
                if op == 'profile':
                    if data != dict(config_sha256=digest(job['config'])):
                        raise RuntimeError('worker_eof_profile')
                    answer = dict(supervisor.profile_binding(job['config']))
                elif op == 'authorize':
                    if data != dict(reference=job['reference'], scope_sha256=digest(job['scope'])):
                        raise RuntimeError('worker_eof_authorizer_pin')
                    answer = dict(allowed=True)
                elif op == 'issue':
                    if data['intent_id'] != job['reference']['intent_id'] or len(attempts) >= 8:
                        raise RuntimeError('worker_eof_attempt_target')
                    attempt = supervisor.issue_attempt(data, deadline=end)
                    key = {}
                    async def sink(value):
                        key.update(value)
                    await supervisor.deliver_worker_credential(attempt, sink, deadline=end)
                    token = len(attempts) + 1
                    attempts[token] = attempt
                    answer = dict(attempt_id=token, binding=dict(supervisor.attempt_binding(attempt)),
                        endpoint=key['endpoint'], api_key=key['api_key'])
                elif op == 'validate':
                    answer = dict(binding=dict(supervisor.attempt_binding(attempts[data['attempt_id']])))
                elif op == 'reserved':
                    binding = dict(supervisor.attempt_binding(attempts[data['attempt_id']]))
                    if (reserved is not None or set(data) != {'attempt_id', 'dispatch_id', 'sequence', 'request_sha256'}
                            or data['dispatch_id'] != binding['dispatch_id'] or data['sequence'] != 1
                            or type(data['request_sha256']) is not str
                            or len(data['request_sha256']) != 64
                            or any(ch not in '0123456789abcdef' for ch in data['request_sha256'])):
                        raise RuntimeError('worker_eof_reserved_target')
                    reserved = dict(data)
                    answer = {}
                elif op == 'before_write':
                    binding = dict(supervisor.attempt_binding(attempts[data['attempt_id']]))
                    if data['dispatch_id'] != binding['dispatch_id'] or data != reserved:
                        raise RuntimeError('worker_eof_dispatch_target')
                    reached = True
                    break
                else:
                    raise RuntimeError('worker_eof_unexpected_operation')
                await send(dict(v=1, id=sequence, ok=True, data=answer))
            if not reached:
                raise RuntimeError('worker_eof_barrier_missing')
        stream.close()
        await stream.wait_closed()
        await asyncio.wait_for(process.wait(), 8)
        if process.returncode is None:
            raise RuntimeError('worker_eof_child_not_reaped')
    finally:
        child.close()
        if stream is not None:
            stream.close()
        else:
            parent.close()
        if process is not None and process.returncode is None:
            process.kill()
            await asyncio.wait_for(process.wait(), 5)
