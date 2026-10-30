"""Native reserved-COMMIT crash acceptance for the fixed publication child."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256

from qdrant_publication_worker_cases import ERRORS, NativePublicationWorkerFailure

CHECKS = (
    'actual_child_base_publish_preserves_parent_supervisor',
    'durable_reserved_then_owned_worker_sigkill_preserves_previous_generation',
    'fresh_sql_reserved_or_unknown_successor_unpublished',
    'physical_successor_points_absent',
    'elapsed_fresh_child_retry_preserves_single_reserved_dispatch',
    'host_close_preserves_supervisor_and_reaps_owned_children',
)


async def python_reserved_worker_cases(value):
    import asyncio
    import json
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit.contracts import Limits, TrustedScope
    from cragkit.execution import ExecutionLedger
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
            raise RuntimeError('reserved_worker_pool_ceiling')
        return config
    writer_config = configuration(value['writer_config'])
    supervisor_resource = PoolResource(configuration(value['supervisor_config']))
    supervisor = ManagedQdrantSupervisor(Path(value['binary']), Path(value['work_dir']),
        inputs['instance_id'], inputs['config'])
    scope = TrustedScope.model_validate(inputs['scope'])
    stage, successor = inputs['stage'], inputs['successor']
    deadline = asyncio.get_running_loop().time() + 100
    target = '/collections/' + inputs['config']['physical_collection']
    checks, results, bundles, hosts = [], [], [], []
    endpoint = primary = host = None
    original_identity = first_pid = None

    def reference(selected):
        return {key: selected['intent'][key] for key in ('collection', 'document_id', 'intent_id')}
    def context(selected):
        return dict(scope=scope, **reference(selected), owner_token='00000000-0000-4000-8000-000000000099')
    def ledger():
        return ExecutionLedger(Limits(deadline_ms=60000, max_attempts=1, max_provider_calls=0), deadline=deadline)
    def job(selected):
        return dict(writer_pool=dict(value['writer_config']), config=deepcopy(inputs['config']),
            scope=scope.model_dump(mode='json'), reference=reference(selected),
            limits=Limits(deadline_ms=60000, max_attempts=1, max_provider_calls=0).model_dump(mode='json'))
    async def authorize(selected_scope, collection, document):
        return (selected_scope == scope and collection == stage['manifest']['collection']
            and document == stage['manifest']['document_id'])
    def accounting(book):
        state = book.snapshot()
        if any(state[key] != expected for key, expected in
                (('attempts', 1), ('provider_calls', 0), ('candidates', 0), ('pending', 0))):
            raise RuntimeError('reserved_worker_accounting')
    async def provision(admin, probe):
        await admin.request('PUT', target, body=request_bytes(inputs['collection_config']), deadline=deadline)
        probe = plain(probe)
        path = '/collections/' + probe['collection']
        await admin.request('PUT', path, body=request_bytes(probe['collection_config']), deadline=deadline)
        result = json.loads(await admin.request('PUT', path + '/points?wait=true&ordering=strong',
            body=request_bytes({'points': [probe['point']]}), deadline=deadline))
        if result.get('result', {}).get('status') != 'completed':
            raise RuntimeError('reserved_worker_probe_ack')
    async def bundle(initialize_manager=True):
        resource = PoolResource(writer_config)
        writer = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
        verifier = QdrantReconciliationVerifier(writer, supervisor)
        recovery = PostgresQdrantRecovery(supervisor_resource, inputs['config'], supervisor, verifier)
        transport = ManagedQdrantPublicationTransport(supervisor)
        manager = QdrantPublicationManager(PostgresQdrantPublicationAuthority(writer, recovery),
            transport, inputs['config'], supervisor, authorize)
        entry = dict(resource=resource, writer=writer, verifier=verifier, recovery=recovery,
            transport=transport, manager=manager)
        bundles.append(entry)
        await resource.open()
        await (manager.initialize(deadline=deadline) if initialize_manager else writer.initialize(deadline=deadline))
        return entry
    async def close_bundle(entry):
        for key in ('manager', 'transport', 'recovery', 'verifier', 'writer', 'resource'):
            action = getattr(entry[key], 'close', None)
            if callable(action):
                await asyncio.wait_for(action(), 5)
        bundles.remove(entry)
    async def stage_call(selected):
        entry = await bundle()
        try:
            await entry['manager'].stage(selected, scope, ledger(), deadline=deadline)
        finally:
            await close_bundle(entry)
    async def snapshot():
        entry = await bundle(False)
        try:
            state = await entry['writer'].manager_snapshot(context(successor), deadline=deadline)
            if (state['document']['active_generation_id'] != stage['manifest']['generation_id']
                    or state['pending'] is not True or state['intent']['state'] != 'writing'
                    or state['intent']['authority_committed'] or state['intent']['replica_complete']):
                raise RuntimeError('reserved_worker_pointer_or_publication')
            return state
        finally:
            await close_bundle(entry)
    async def journal():
        async with supervisor_resource.lease(deadline=deadline) as connection:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                await connection.execute("SELECT set_config('cragkit_qdrant.backend_instance_id',%s,true)",
                    (inputs['instance_id'],))
                cursor = await connection.execute('SELECT dispatch_id,state,sequence::text '
                    'FROM cragkit_qdrant.dispatch_journal WHERE instance_id=%s AND intent_id=%s '
                    'ORDER BY sequence', (inputs['instance_id'], successor['intent']['intent_id']))
                return await cursor.fetchall()
    async def unchanged():
        if dict(supervisor.control_binding()) != original_identity or await observed_listener(endpoint) != first_pid:
            raise RuntimeError('reserved_worker_supervisor_changed')
    async def absent():
        attempt = supervisor.issue_attempt(dict(intent_id='reserved-absence',
            owner_token=context(successor)['owner_token'], epoch=1, dispatch_id='reserved-absence'), deadline=deadline)
        handle = supervisor.transport_for(attempt)
        try:
            result = json.loads(await handle.request('POST', target + '/points',
                body=request_bytes(dict(ids=[member['point_id'] for member in successor['manifest']['members']],
                    with_payload=True, with_vector=True)), deadline=deadline))
            if result.get('result') != []:
                raise RuntimeError('reserved_worker_successor_http_arrived')
        finally:
            await handle.close()
    async def failed_publish(selected_host, observer):
        book = ledger()
        try:
            await selected_host.publish(job(successor), book, deadline=deadline, observer=observer)
        except (ProviderUnavailable, UnauthorizedScope):
            pass
        else:
            raise RuntimeError('reserved_worker_expected_refusal')
        accounting(book)
    def new_host():
        selected = ManagedQdrantPublicationWorkerHost(supervisor, authorize)
        hosts.append(selected)
        return selected
    try:
        await supervisor.initialize(deadline=deadline, provision=provision)
        endpoint = supervisor.identity()['endpoint']
        first_pid = await observed_listener(endpoint)
        original_identity = dict(supervisor.control_binding())
        await supervisor_resource.open()
        await stage_call(stage)
        host = new_host()
        base_events = []
        async def observe_base(event, worker):
            base_events.append(plain(event))
        book = ledger()
        result = plain(await host.publish(job(stage), book, deadline=deadline, observer=observe_base))
        accounting(book)
        fields = ('intent_id', 'operation', 'state', 'revision_id', 'generation_id',
            'authority_committed', 'replica_complete', 'published', 'purge_complete')
        if (set(result) != set(fields) or result['state'] != 'published' or result['published'] is not True
                or result['authority_committed'] is not True or result['replica_complete'] is not True
                or [event['kind'] for event in base_events] != ['reserved', 'before_write', 'write_observed']
                or [event['status'] for event in base_events if event['kind'] == 'write_observed'] != [200]):
            raise RuntimeError('reserved_worker_base_publication')
        results.append([result[key] for key in fields])
        await unchanged()
        checks.append(CHECKS[0])
        await stage_call(successor)
        barrier, unexpected = [], []
        async def kill(event, worker):
            event = plain(event)
            if event['kind'] == 'reserved':
                barrier.append(event)
                await worker.terminate(deadline=min(deadline, asyncio.get_running_loop().time() + 5))
            else:
                unexpected.append(event)
        await failed_publish(host, kill)
        if len(barrier) != 1 or unexpected:
            raise RuntimeError('reserved_worker_crash_barrier')
        await snapshot()
        await unchanged()
        checks.append(CHECKS[1])
        rows = await journal()
        if (len(rows) != 1 or rows[0][0] != barrier[0]['dispatch_id']
                or rows[0][1] not in ('reserved', 'unknown') or str(rows[0][2]) != str(barrier[0]['sequence'])):
            raise RuntimeError('reserved_worker_durable_journal')
        await snapshot()
        checks.append(CHECKS[2])
        await absent()
        checks.append(CHECKS[3])
        await host.close()
        host = new_host()
        started = asyncio.get_running_loop().time()
        await asyncio.wait_for(asyncio.sleep(1.05), max(.001, deadline - started))
        if asyncio.get_running_loop().time() - started < 1.0:
            raise RuntimeError('reserved_worker_elapsed_wait')
        retry_events = []
        async def retry_observer(event, worker):
            retry_events.append(plain(event))
        await failed_publish(host, retry_observer)
        if retry_events or await journal() != rows:
            raise RuntimeError('reserved_worker_retry_dispatch')
        await snapshot()
        await absent()
        await unchanged()
        checks.append(CHECKS[4])
        await host.close()
        await unchanged()
        checks.append(CHECKS[5])
        return dict(runtime='python', checks=checks, proof_scope='reserved_worker_process_only',
            public_results_sha256=sha256(request_bytes(results)).hexdigest())
    except BaseException as error:
        primary = error
        frame, location = error.__traceback__, None
        while frame is not None:
            if frame.tb_frame.f_code.co_filename == __file__:
                location = frame.tb_lineno
            frame = frame.tb_next
        (Path(value['work_dir']).parent.parent / 'python-reserved-failure-location.json').write_text(
            json.dumps(dict(step=len(checks), line=location)) + '\n')
        name = type(error).__name__
        raise NativePublicationWorkerFailure(dict(ok=False, step=len(checks),
            error=name if name in ERRORS else 'internal')) from None
    finally:
        failures = []
        end = asyncio.get_running_loop().time() + 15
        async def close(operation, action):
            try:
                await asyncio.wait_for(action(), max(.001, min(8, end - asyncio.get_running_loop().time())))
            except BaseException as error:
                name = type(error).__name__
                failures.append(dict(operation=operation, outcome=name if name in ERRORS else 'internal'))
        for selected_host in reversed(hosts):
            await close('host_close', selected_host.close)
        for entry in reversed(bundles):
            for key in ('manager', 'transport', 'recovery', 'verifier', 'writer', 'resource'):
                action = getattr(entry[key], 'close', None)
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
