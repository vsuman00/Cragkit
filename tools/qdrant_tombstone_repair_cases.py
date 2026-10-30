"""Native irreversible tombstone during an admitted repair."""
from __future__ import annotations

from copy import deepcopy

CHECKS = (
    'repair_admitted_before_tombstone',
    'independent_tombstone_commits_without_wait',
    'source_and_grants_denied_while_repair_held',
    'pending_purge_preserves_owner_claims_pointer',
    'late_repair_ack_unknown_cannot_publish',
    'managed_purge_fences_and_settles_uncertainty',
    'final_absence_and_source_denial_preserve_outside',
)


async def python_tombstone_repair_cases(value):
    import asyncio
    import hashlib
    import json
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit._qdrant_manifest import encode_security_intent
    from cragkit._qdrant_writer import purge_projection_data, security_projection_data
    from cragkit.contracts import Limits, TrustedScope
    from cragkit.errors import ProviderUnavailable
    from cragkit.execution import ExecutionLedger
    from cragkit.qdrant import QdrantNomination
    from cragkit.qdrant_source import PostgresQdrantSourceStore
    from cragkit.qdrant_publication import (QdrantPublicationManager, QdrantSecurityManager,
        PostgresQdrantPublicationAuthority, ManagedQdrantPublicationTransport, PostgresQdrantWriter,
        PostgresQdrantRecovery, ManagedQdrantSupervisor, QdrantReconciliationVerifier)
    from qdrant_public_security_cases import NativePublicSecurityFailure
    from qdrant_publication_manager_cases import ERRORS
    from qdrant_supervisor_cases import plain, request_bytes, observed_listener

    inputs = value['inputs']; policy = 'erase_managed_source_and_replay_v1'
    deadline = asyncio.get_running_loop().time() + 150
    def configuration(raw):
        raw = dict(raw)
        for key in ('sslrootcert', 'passfile'):
            raw[key] = Path(raw[key])
        config = PoolConfig.model_validate(raw)
        if config.max_size != 1:
            raise RuntimeError('tombstone_repair_pool_bound')
        return config
    resource = PoolResource(configuration(value['writer_config']))
    supervisor_resource = PoolResource(configuration(value['supervisor_config']))
    reader = PoolResource(configuration(value['reader_config']))
    supervisor = ManagedQdrantSupervisor(Path(value['binary']), Path(value['work_dir']), inputs['instance_id'], inputs['config'])
    writer = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
    independent = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
    verifier = QdrantReconciliationVerifier(writer, supervisor)
    recovery = PostgresQdrantRecovery(supervisor_resource, inputs['config'], supervisor, verifier)
    authority = PostgresQdrantPublicationAuthority(writer, recovery)
    transport = ManagedQdrantPublicationTransport(supervisor)
    scope = TrustedScope.model_validate(inputs['scope'])
    auth2 = TrustedScope.model_validate(dict(inputs['scope'], authorization_revision='auth-2'))
    base, outside, second = inputs['stage'], inputs['ownerless_stage'], deepcopy(inputs['second_stage'])
    second['intent']['expected_active_generation_id'] = base['manifest']['generation_id']
    tombstone = deepcopy(inputs['security'])
    tombstone.update(action='tombstone', intent_id='native-tombstone-during-repair')
    tombstone['authorization'].update(tombstoned=True, principal_ids=[], grant_ids=[])
    purge = dict(intent_id='native-purge-tombstone-repair', tenant_id=tombstone['tenant_id'],
        collection=tombstone['collection'], document_id=tombstone['document_id'],
        expected_authorization_revision='auth-2', expected_mutation_epoch=2,
        tombstone_intent_payload_sha256=encode_security_intent(tombstone).sha256)
    collection, document = base['manifest']['collection'], base['manifest']['document_id']
    target = '/collections/' + inputs['config']['physical_collection']
    token = '00000000-0000-4000-8000-000000000099'
    checks, observations, requests, stores = [], [], [], []
    held = dict(armed=False, entered=asyncio.Event(), release=asyncio.Event(), completed=False, args=None)
    network = dict(puts=0)
    original_http = supervisor._http
    manager = security = endpoint = primary = task = None
    def reference(item):
        record = item['intent'] if 'manifest' in item else item
        return {key: record[key] for key in ('collection', 'document_id', 'intent_id')}
    def context(item, selected):
        return dict(**reference(item), scope=selected, owner_token=token)
    async def authorize(selected, selected_collection, selected_document):
        return (selected.tenant_id == scope.tenant_id and selected_collection == collection
            and selected_document in (document, outside['manifest']['document_id']))
    async def call(method, item, selected, **kwargs):
        book = ExecutionLedger(Limits(deadline_ms=150000, max_provider_calls=0), deadline=deadline)
        try:
            return plain(await method(item, selected, book, deadline=deadline, **kwargs))
        finally:
            usage = book.snapshot()
            if (usage['attempts'], usage['provider_calls'], usage['pending']) != (1, 0, 0):
                raise RuntimeError('tombstone_repair_usage')
    async def snapshot(item, selected):
        return await independent.manager_snapshot(context(item, selected), deadline=deadline)
    async def journal():
        async with supervisor_resource.lease(deadline=deadline) as connection:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION READ ONLY')
                await connection.execute("SELECT set_config('cragkit_qdrant.backend_instance_id',%s,true)", (inputs['instance_id'],))
                cursor = await connection.execute('SELECT intent_id,dispatch_id,state,completion_sha256 FROM cragkit_qdrant.dispatch_journal '
                    'WHERE instance_id=%s AND tenant_id=%s AND collection=%s AND document_id=%s ORDER BY intent_id,sequence',
                    (inputs['instance_id'], scope.tenant_id, collection, document))
                return await cursor.fetchall()
    async def observed_http(*args, **kwargs):
        mutation = len(args) > 3 and args[1] == 'PUT' and args[2] == target + '/points?wait=true&ordering=strong'
        paused = mutation and held['armed']
        if mutation: network['puts'] += 1
        if paused:
            held.update(armed=False, args=args); held['entered'].set()
            await held['release'].wait()
        result = await original_http(*args, **kwargs)
        if paused:
            status, raw = result
            if status != 200 or json.loads(raw).get('result', {}).get('status') != 'completed':
                raise RuntimeError('tombstone_repair_old_write_not_completed')
            held['completed'] = True
            raise ProviderUnavailable()
        return result
    async def provision(admin, probe):
        await admin.request('PUT', target, body=request_bytes(inputs['collection_config']), deadline=deadline)
        probe = plain(probe); path = '/collections/' + probe['collection']
        await admin.request('PUT', path, body=request_bytes(probe['collection_config']), deadline=deadline)
        await admin.request('PUT', path + '/points?wait=true&ordering=strong',
            body=request_bytes(dict(points=[probe['point']])), deadline=deadline)
    async def source(stage, selected):
        member = stage['manifest']['members'][0]
        payload = dict(inputs['expected_points'][0]['payload'])
        payload.update({key: stage['manifest'][key] for key in ('tenant_id', 'collection', 'document_id', 'revision_id', 'generation_id')})
        nomination = QdrantNomination.model_validate(dict(point_id=member['point_id'], branch='dense', score=1.,
            score_kind='cosine_similarity', payload=payload))
        store = PostgresQdrantSourceStore(reader, inputs['config']); stores.append(store)
        await store.initialize(deadline=deadline)
        request = store.open_request(dict(query='native tombstone repair verification', collection=collection), scope=selected, deadline=deadline)
        requests.append(request)
        fetched = await request.fetch_candidate(nomination, max_source_bytes=16777216, include_source=True)
        if fetched.state == 'verified':
            canonical = stage['canonical_text'].encode('utf-8'); excerpt = canonical[member['start_byte']:member['end_byte']]
            if (fetched.evidence is None or fetched.binding is None or fetched.evidence.text != excerpt.decode('utf-8')
                    or fetched.evidence.source_sha256 != hashlib.sha256(canonical).hexdigest()
                    or fetched.evidence.text_sha256 != hashlib.sha256(excerpt).hexdigest()):
                raise RuntimeError('tombstone_repair_source_fidelity')
        return request, fetched
    def unavailable(result):
        if (result.state != 'unavailable' or result.binding is not None or result.evidence is not None
                or result.private_source is not None or result.source_bytes != 0):
            raise RuntimeError('tombstone_repair_source_disclosed')
    async def read_points(key, ids):
        status, raw = await original_http(key, 'POST', target + '/points',
            request_bytes(dict(ids=list(ids), with_payload=True, with_vector=True)), deadline)
        response = json.loads(raw)
        if status != 200 or response.get('status') != 'ok':
            raise RuntimeError('tombstone_repair_readback')
        return response['result']
    async def scoped_absence(ids):
        if await read_points(supervisor._key, ids) != []:
            raise RuntimeError('tombstone_repair_points_remain')
        status, raw = await original_http(supervisor._key, 'POST', target + '/points/scroll',
            request_bytes(dict(filter=dict(must=[dict(key=key, match=dict(value=selected))
                for key, selected in (('tenant_id', scope.tenant_id), ('collection', collection), ('document_id', document))]),
                limit=8, with_payload=True, with_vector=True)), deadline)
        response = json.loads(raw)
        result = response.get('result', {})
        if status != 200 or response.get('status') != 'ok' or result.get('points') != [] or result.get('next_page_offset', 'missing') is not None:
            raise RuntimeError('tombstone_repair_scoped_absence_incomplete')
    try:
        supervisor._http = observed_http
        await supervisor.initialize(deadline=deadline, provision=provision)
        endpoint = supervisor.identity()['endpoint']; await observed_listener(endpoint)
        for pool in (resource, supervisor_resource, reader): await pool.open()
        manager = QdrantPublicationManager(authority, transport, inputs['config'], supervisor, authorize)
        security = QdrantSecurityManager(independent, authorize)
        await manager.initialize(deadline=deadline); await security.initialize(deadline=deadline)
        for stage in (base, outside):
            await call(manager.stage, stage, scope)
            if not (await call(manager.publish, reference(stage), scope))['published']:
                raise RuntimeError('tombstone_repair_setup_publication')
        outside_ids = [member['point_id'] for member in outside['manifest']['members']]
        outside_points = await read_points(supervisor._key, outside_ids)
        if len(outside_points) != 2: raise RuntimeError('tombstone_repair_outside_missing')
        await call(manager.stage, second, scope)
        # Repair resumes an owned intent; a settled base owner must first hand
        # ownership to the staged successor through ordinary native admission.
        admitted_repair = await independent.admit_publication(context(second, scope), deadline=deadline)
        if (admitted_repair['owner'] is None or admitted_repair['owner']['owner_token'] != token
                or admitted_repair['intent']['state'] != 'writing'):
            raise RuntimeError('tombstone_repair_successor_owner_missing')
        owned_repair = await snapshot(second, scope)
        if (owned_repair['owner'] is None or owned_repair['owner']['intent_id'] != second['intent']['intent_id']
                or owned_repair['owner']['owner_token'] != token or owned_repair['pending']):
            raise RuntimeError('tombstone_repair_successor_snapshot_mismatch')
        retained_request, retained = await source(base, scope)
        if retained.state != 'verified': raise RuntimeError('tombstone_repair_retained_missing')
        held['armed'] = True
        task = asyncio.create_task(call(manager.repair, reference(second), scope))
        arrived = asyncio.create_task(held['entered'].wait())
        try:
            done, _ = await asyncio.wait((task, arrived), timeout=max(.001, deadline - asyncio.get_running_loop().time()),
                return_when=asyncio.FIRST_COMPLETED)
            if arrived not in done:
                if task.done(): await task
                raise RuntimeError('tombstone_repair_hold_not_reached')
        finally:
            arrived.cancel()
            await asyncio.gather(arrived, return_exceptions=True)
        points = json.loads(held['args'][3])['points']; rows = await journal()
        old = [row for row in rows if row[0] == second['intent']['intent_id']]
        if (len(points) != 2 or any(item['payload']['authorization_revision'] != 'auth-1' for item in points)
                or len(old) != 1 or old[0][2:] != ('dispatched', None) or task.done()):
            raise RuntimeError('tombstone_repair_admission_missing')
        before = await snapshot(second, scope)
        checks.append(CHECKS[0]); observations.append(['repair', 'auth-1', 2, 'dispatched'])
        puts = network['puts']
        admitted = await call(security.tombstone, tombstone, scope)
        dead = await snapshot(tombstone, auth2)
        if (not admitted['authority_committed'] or admitted['purge_complete'] or network['puts'] != puts
                or task.done() or held['release'].is_set() or not dead['document']['tombstoned']
                or dead['document']['authorization_revision'] != 'auth-2' or dead['document']['mutation_epoch'] != 2):
            raise RuntimeError('tombstone_repair_authority_waited')
        checks.append(CHECKS[1]); observations.append(['tombstone', 'auth-2', True, False])
        for purpose in ('provider', 'final'):
            unavailable(await retained_request.release(retained.binding, purpose=purpose, max_source_bytes=16777216, include_source=True))
        for selected in (scope, auth2):
            _, fetched = await source(base, selected); unavailable(fetched)
        checks.append(CHECKS[2]); observations.append(['source', 'unavailable', 'unavailable', 0])
        await independent.bind_purge(purge, auth2, owner_token=token, deadline=deadline)
        pending = await snapshot(purge, auth2)
        projection = await independent.project_purge(context(purge, auth2), policy, deadline=deadline)
        data = purge_projection_data(projection, independent)
        graph = security_projection_data(data['projection'], independent)
        ids = list(graph['point_ids'])
        if (not graph['tombstoned'] or graph['authorization_revision'] != 'auth-2' or graph['mutation_epoch'] != 2
                or graph['principal_ids'] != () or graph['grant_ids'] != ()):
            raise RuntimeError('tombstone_repair_authority_graph_mismatch')
        try:
            await independent.admit_purge_tombstone_owner(projection, deadline=deadline)
        except ProviderUnavailable:
            pass
        else:
            raise RuntimeError('tombstone_repair_owner_gate_open')
        if (len(ids) != 4 or pending['owner'] != before['owner'] or not pending['pending']
                or pending['intent']['purge_complete'] or pending['document']['active_generation_id'] != base['manifest']['generation_id']
                or await journal() != rows or network['puts'] != puts):
            raise RuntimeError('tombstone_repair_pending_state_changed')
        checks.append(CHECKS[3]); observations.append(['pending', 4, 'ProviderUnavailable'])
        old_key = held['args'][0]; generation = supervisor.control_binding()['credential_generation']
        held['release'].set()
        try: await task
        except ProviderUnavailable: pass
        else: raise RuntimeError('tombstone_repair_lost_ack_missing')
        task = None
        unknown = [row for row in await journal() if row[0] == second['intent']['intent_id']]
        after = await snapshot(purge, auth2)
        if (not held['completed'] or len(unknown) != 1 or unknown[0][2:] != ('unknown', None)
                or not after['pending'] or after['intent']['purge_complete'] or not after['document']['tombstoned']
                or after['document']['active_generation_id'] != base['manifest']['generation_id']
                or after['document']['authorization_revision'] != 'auth-2' or after['document']['mutation_epoch'] != 2
                or after['owner'] != before['owner']
                or (await snapshot(second, auth2))['intent']['state'] == 'published'):
            raise RuntimeError('tombstone_repair_resurrection_or_early_purge')
        after_projection = await independent.project_purge(context(purge, auth2), policy, deadline=deadline)
        after_graph = security_projection_data(purge_projection_data(after_projection, independent)['projection'], independent)
        if (set(after_graph['point_ids']) != set(ids) or not after_graph['tombstoned']
                or after_graph['principal_ids'] != () or after_graph['grant_ids'] != ()):
            raise RuntimeError('tombstone_repair_claims_changed')
        checks.append(CHECKS[4]); observations.append(['late_completion', 200, 'unknown', False])
        original_complete = writer.complete_purge
        completions = []
        async def checked_complete(selected_verifier, receipt, **options):
            current = await writer.manager_snapshot(context(purge, auth2), deadline=deadline)
            if current['pending'] or current['intent']['purge_complete'] or any(row[2] != 'settled' for row in await journal()):
                raise RuntimeError('tombstone_repair_completion_before_settlement')
            for _ in range(2):
                await scoped_absence(ids)
            completions.append(True)
            return await original_complete(selected_verifier, receipt, **options)
        writer.complete_purge = checked_complete
        try: completed = await call(manager.purge, purge, auth2, retention_policy=policy)
        finally: writer.complete_purge = original_complete
        final = await snapshot(purge, auth2)
        if (completed['state'] != 'complete' or not completed['purge_complete'] or not completed['replica_complete']
                or final['pending'] or final['backend']['state'] != 'open' or len(completions) != 1
                or supervisor.control_binding()['credential_generation'] == generation):
            raise RuntimeError('tombstone_repair_purge_incomplete')
        status, _ = await original_http(old_key, 'GET', target, None, deadline)
        if status != 401: raise RuntimeError('tombstone_repair_old_key_not_fenced')
        checks.append(CHECKS[5]); observations.append(['purged', 'open', True, True])
        for _ in range(2):
            await scoped_absence(ids)
        preserved = await read_points(supervisor._key, outside_ids)
        normalize = lambda rows: sorted([{key: item[key] for key in ('id', 'payload', 'vector')} for item in rows], key=lambda item: item['id'])
        if normalize(preserved) != normalize(outside_points): raise RuntimeError('tombstone_repair_outside_changed')
        _, denied = await source(base, auth2); unavailable(denied)
        _, allowed = await source(outside, scope)
        if allowed.state != 'verified': raise RuntimeError('tombstone_repair_outside_source_denied')
        checks.append(CHECKS[6]); observations.append(['absence', 0, 'unavailable', 'verified', 0])
        return dict(runtime='python', checks=checks, proof_scope='native_tombstone_during_repair_only',
            semantic_witness_sha256=hashlib.sha256(request_bytes(['cragkit.qdrant.tombstone-repair.v1', observations])).hexdigest())
    except BaseException as error:
        primary = error; name = type(error).__name__
        failure = NativePublicSecurityFailure(dict(ok=False, step=len(checks), error=name if name in ERRORS else 'internal'))
        failure.primary = error
        raise failure from None
    finally:
        held['release'].set(); failures = []
        cleanup_deadline = asyncio.get_running_loop().time() + 15
        async def close(name, action):
            try: await asyncio.wait_for(action(), max(.001, min(8, cleanup_deadline - asyncio.get_running_loop().time())))
            except BaseException: failures.append(name)
        if task is not None:
            task.cancel(); await close('repair_drain', lambda: asyncio.gather(task, return_exceptions=True))
        supervisor._http = original_http
        for item in requests + stores + [item for item in (manager, security, transport, authority, recovery, verifier,
                independent, writer, reader, resource, supervisor_resource, supervisor) if item is not None]:
            action = getattr(item, 'close', None)
            if callable(action): await close(type(item).__name__, action)
        for pool in (reader, resource, supervisor_resource):
            if pool._state != 'closed' or pool._users or pool._leases or not pool._driver_close_ok: failures.append('pool_close_verification')
        if any(not item._closed or item._bindings or item._pending for item in requests): failures.append('source_request_close_verification')
        if any(not item._closed or item._handle is not None for item in stores): failures.append('source_store_close_verification')
        if supervisor._process is not None and supervisor._process.returncode is None: failures.append('process_close_verification')
        if endpoint is not None: await close('listener', lambda: observed_listener(endpoint, allow_absent=True))
        if failures:
            name = type(primary).__name__ if primary is not None else None
            raise NativePublicSecurityFailure(dict(ok=False, step=len(checks), error='cleanup_failed',
                primary=name if name in ERRORS else ('internal' if name else None), cleanup=failures)) from None
