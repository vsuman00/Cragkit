"""Native delayed auth-1 upsert with independent auth-2 authority."""
from __future__ import annotations

from copy import deepcopy

CHECKS = (
    'held_auth1_full_point_before_http',
    'auth2_authority_commits_while_old_http_held',
    'unsettled_old_write_blocks_conflicting_replica_admission',
    'old_http_completion_ack_unknown_preserves_revocation',
    'managed_recovery_replays_current_auth2_payload',
    'current_source_only_zero_provider_text',
)


async def python_old_acl_late_cases(value):
    import asyncio
    import hashlib
    import json
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit._qdrant_writer import admit_security_owner, security_projection_data
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

    inputs = value['inputs']
    deadline = asyncio.get_running_loop().time() + 120
    def configuration(raw):
        raw = dict(raw)
        for key in ('sslrootcert', 'passfile'):
            raw[key] = Path(raw[key])
        result = PoolConfig.model_validate(raw)
        if result.max_size != 1:
            raise RuntimeError('old_acl_pool_bound')
        return result
    resource = PoolResource(configuration(value['writer_config']))
    supervisor_resource = PoolResource(configuration(value['supervisor_config']))
    reader = PoolResource(configuration(value['reader_config']))
    supervisor = ManagedQdrantSupervisor(Path(value['binary']), Path(value['work_dir']),
        inputs['instance_id'], inputs['config'])
    writer = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
    independent = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
    verifier = QdrantReconciliationVerifier(writer, supervisor)
    recovery = PostgresQdrantRecovery(supervisor_resource, inputs['config'], supervisor, verifier)
    authority = PostgresQdrantPublicationAuthority(writer, recovery)
    transport = ManagedQdrantPublicationTransport(supervisor)
    scope = TrustedScope.model_validate(inputs['scope'])
    auth2 = TrustedScope.model_validate(dict(inputs['scope'], authorization_revision='auth-2', principal_id='reader-b'))
    base, second = inputs['stage'], deepcopy(inputs['second_stage'])
    second['intent']['expected_active_generation_id'] = base['manifest']['generation_id']
    change = deepcopy(inputs['security'])
    change['authorization'].update(principal_ids=['reader-b'], grant_ids=[])
    collection, document = base['manifest']['collection'], base['manifest']['document_id']
    target = '/collections/' + inputs['config']['physical_collection']
    token = '00000000-0000-4000-8000-000000000099'
    checks, observations, requests, stores = [], [], [], []
    held = dict(armed=False, entered=asyncio.Event(), release=asyncio.Event(), completed=False, args=None)
    network = dict(puts=0)
    original_http = supervisor._http
    manager = security = endpoint = primary = task = None
    def reference(item):
        if 'manifest' in item:
            return {key: item['intent'][key] for key in ('collection', 'document_id', 'intent_id')}
        return {key: item[key] for key in ('collection', 'document_id', 'intent_id')}
    def context(item, selected):
        return dict(**reference(item), scope=selected, owner_token=token)
    async def authorize(selected, selected_collection, selected_document):
        return selected.tenant_id == scope.tenant_id and selected_collection == collection and selected_document == document
    async def call(method, item, selected):
        book = ExecutionLedger(Limits(max_provider_calls=0), deadline=deadline)
        try:
            return plain(await method(item, selected, book, deadline=deadline))
        finally:
            usage = book.snapshot()
            if (usage['attempts'], usage['provider_calls'], usage['pending']) != (1, 0, 0):
                raise RuntimeError('old_acl_usage')
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
        if mutation:
            network['puts'] += 1
        if paused:
            held.update(armed=False, args=args)
            held['entered'].set()
            await held['release'].wait()
        result = await original_http(*args, **kwargs)
        if paused:
            status, raw = result
            response = json.loads(raw)
            if status != 200 or response.get('result', {}).get('status') != 'completed':
                raise RuntimeError('old_acl_held_request_not_completed')
            held['completed'] = True
            raise ProviderUnavailable()
        return result
    async def provision(admin, probe):
        await admin.request('PUT', target, body=request_bytes(inputs['collection_config']), deadline=deadline)
        probe = plain(probe)
        path = '/collections/' + probe['collection']
        await admin.request('PUT', path, body=request_bytes(probe['collection_config']), deadline=deadline)
        await admin.request('PUT', path + '/points?wait=true&ordering=strong',
            body=request_bytes(dict(points=[probe['point']])), deadline=deadline)
    point = inputs['expected_points'][0]
    nomination = QdrantNomination.model_validate(dict(point_id=point['id'], branch='dense', score=1.,
        score_kind='cosine_similarity', payload=point['payload']))
    async def source(selected):
        store = PostgresQdrantSourceStore(reader, inputs['config']); stores.append(store)
        await store.initialize(deadline=deadline)
        request = store.open_request(dict(query='native old ACL verification', collection=collection), scope=selected, deadline=deadline)
        requests.append(request)
        return request, await request.fetch_candidate(nomination, max_source_bytes=16777216, include_source=True)
    def unavailable(result):
        if (result.state != 'unavailable' or result.binding is not None or result.evidence is not None
                or result.private_source is not None or result.source_bytes != 0):
            raise RuntimeError('old_acl_revoked_source_disclosed')
    async def revoked_release(request, binding):
        for purpose in ('provider', 'final'):
            unavailable(await request.release(binding, purpose=purpose, max_source_bytes=16777216, include_source=True))
    try:
        supervisor._http = observed_http
        await supervisor.initialize(deadline=deadline, provision=provision)
        endpoint = supervisor.identity()['endpoint']; await observed_listener(endpoint)
        for pool in (resource, supervisor_resource, reader):
            await pool.open()
        manager = QdrantPublicationManager(authority, transport, inputs['config'], supervisor, authorize)
        security = QdrantSecurityManager(independent, authorize)
        await manager.initialize(deadline=deadline); await security.initialize(deadline=deadline)
        await call(manager.stage, base, scope)
        if not (await call(manager.publish, reference(base), scope))['published']:
            raise RuntimeError('old_acl_base_not_published')
        await call(manager.stage, second, scope)
        retained_request, retained = await source(scope)
        if retained.state != 'verified' or retained.binding is None:
            raise RuntimeError('old_acl_retained_source_missing')
        held['armed'] = True
        task = asyncio.create_task(call(manager.publish, reference(second), scope))
        await asyncio.wait_for(held['entered'].wait(), max(.001, deadline - asyncio.get_running_loop().time()))
        old_points = json.loads(held['args'][3])['points']
        rows = await journal()
        old_rows = [row for row in rows if row[0] == second['intent']['intent_id']]
        if (len(old_points) != 2 or any(item['payload']['authorization_revision'] != 'auth-1'
                    or 'dense' not in item['vector'] or 'sparse' not in item['vector'] for item in old_points)
                or {item['id'] for item in old_points} != {item['point_id'] for item in second['manifest']['members']}
                or len(old_rows) != 1 or old_rows[0][2:] != ('dispatched', None) or task.done()):
            raise RuntimeError('old_acl_hold_not_admitted')
        checks.append(CHECKS[0]); observations.append(['held', 'auth-1', 2, 'dispatched'])
        puts = network['puts']
        admitted = await call(security.update_authorization, change, scope)
        current = await snapshot(change, auth2)
        if (not admitted['authority_committed'] or admitted['replica_complete'] or held['release'].is_set()
                or task.done() or network['puts'] != puts or current['document']['authorization_revision'] != 'auth-2'):
            raise RuntimeError('old_acl_authority_waited_or_dispatched')
        await revoked_release(retained_request, retained.binding)
        checks.append(CHECKS[1]); observations.append(['authority', 'auth-2', True, False])
        try:
            await admit_security_owner(independent, context(change, auth2), deadline=deadline)
        except ProviderUnavailable:
            pass
        else:
            raise RuntimeError('old_acl_conflicting_replica_admitted')
        if await journal() != rows or network['puts'] != puts or held['release'].is_set() or task.done():
            raise RuntimeError('old_acl_conflicting_dispatch')
        checks.append(CHECKS[2]); observations.append(['conflict', 'ProviderUnavailable', 0])
        old_key = held['args'][0]
        generation = supervisor.control_binding()['credential_generation']
        held['release'].set()
        try:
            await task
        except ProviderUnavailable:
            pass
        else:
            raise RuntimeError('old_acl_lost_ack_not_observed')
        task = None
        unknown = [row for row in await journal() if row[0] == second['intent']['intent_id']]
        if not held['completed'] or len(unknown) != 1 or unknown[0][2:] != ('unknown', None):
            raise RuntimeError('old_acl_uncertainty_missing')
        _, denied_after_completion = await source(scope)
        unavailable(denied_after_completion)
        checks.append(CHECKS[3]); observations.append(['late_completion', 200, 'unknown', 'unavailable', 0])
        converged = await call(manager.converge_security, reference(change), auth2)
        current = await snapshot(change, auth2)
        if (converged['state'] != 'complete' or not converged['replica_complete'] or current['pending']
                or current['backend']['state'] != 'open' or current['document']['active_generation_id'] != base['manifest']['generation_id']
                or supervisor.control_binding()['credential_generation'] == generation):
            raise RuntimeError('old_acl_convergence_incomplete')
        status, _ = await original_http(old_key, 'GET', target, None, deadline)
        if status != 401:
            raise RuntimeError('old_acl_key_not_fenced')
        projection = security_projection_data(await independent.project_security(context(change, auth2), deadline=deadline), independent)
        status, raw = await original_http(supervisor._key, 'POST', target + '/points',
            request_bytes(dict(ids=list(projection['point_ids']), with_payload=True, with_vector=True)), deadline)
        actual = json.loads(raw).get('result', [])
        expected = {}
        for item in projection['points']:
            vector = {'dense': list(item.dense.values)}
            if item.sparse is not None:
                vector['sparse'] = dict(indices=list(item.sparse.indices), values=list(item.sparse.values))
            expected[item.point_id] = dict(id=item.point_id, payload=item.payload.model_dump(mode='json', exclude_none=True), vector=vector)
        if (status != 200 or len(actual) != 4 or len(expected) != 4
                or {item['id'] for item in actual} != set(expected)
                or any({key: item[key] for key in ('id', 'payload', 'vector')} != expected[item['id']]
                    or item['payload']['authorization_revision'] != 'auth-2' for item in actual)
                or any(row[2] != 'settled' or row[3] is None for row in await journal())):
            raise RuntimeError('old_acl_current_payload_mismatch')
        checks.append(CHECKS[4]); observations.append(['recovered', 'auth-2', 4, 'open', True])
        _, denied = await source(scope); unavailable(denied)
        _, revoked = await source(TrustedScope.model_validate(dict(inputs['scope'], authorization_revision='auth-2')))
        unavailable(revoked)
        _, allowed = await source(auth2)
        if allowed.state != 'verified' or allowed.evidence is None or allowed.binding is None:
            raise RuntimeError('old_acl_current_source_missing')
        member = next(item for item in base['manifest']['members'] if item['point_id'] == point['id'])
        canonical = base['canonical_text'].encode('utf-8')
        excerpt = canonical[member['start_byte']:member['end_byte']]
        if (allowed.evidence.text != excerpt.decode('utf-8')
                or allowed.evidence.source_sha256 != hashlib.sha256(canonical).hexdigest()
                or allowed.evidence.text_sha256 != hashlib.sha256(excerpt).hexdigest()):
            raise RuntimeError('old_acl_current_source_fidelity')
        checks.append(CHECKS[5]); observations.append(['source', 'unavailable', 'unavailable', 'verified', 0])
        witness = request_bytes(['cragkit.qdrant.old-acl-late.v1', observations])
        return dict(runtime='python', checks=checks, proof_scope='native_old_acl_late_upsert_only',
            semantic_witness_sha256=hashlib.sha256(witness).hexdigest())
    except BaseException as error:
        primary = error
        name = type(error).__name__
        failure = NativePublicSecurityFailure(dict(ok=False, step=len(checks), error=name if name in ERRORS else 'internal'))
        failure.primary = error
        raise failure from None
    finally:
        held['release'].set()
        failures = []
        cleanup_deadline = asyncio.get_running_loop().time() + 12
        async def close(name, function):
            try:
                await asyncio.wait_for(function(), max(.001, min(8, cleanup_deadline - asyncio.get_running_loop().time())))
            except BaseException:
                failures.append(name)
        if task is not None:
            task.cancel()
            await close('publish_drain', lambda: asyncio.gather(task, return_exceptions=True))
        supervisor._http = original_http
        owned = requests + stores + [item for item in (manager, security, transport, authority, recovery,
            verifier, independent, writer, reader, resource, supervisor_resource, supervisor) if item is not None]
        for item in owned:
            action = getattr(item, 'close', None)
            if callable(action):
                await close(type(item).__name__, action)
        if any(not item._closed or item._bindings or item._pending for item in requests):
            failures.append('source_request_close_verification')
        if any(not item._closed or item._handle is not None for item in stores):
            failures.append('source_store_close_verification')
        for pool in (reader, resource, supervisor_resource):
            if pool._state != 'closed' or pool._users or pool._leases or not pool._driver_close_ok:
                failures.append('pool_close_verification')
        if supervisor._process is not None and supervisor._process.returncode is None:
            failures.append('process_close_verification')
        if endpoint is not None:
            await close('listener', lambda: observed_listener(endpoint, allow_absent=True))
        if failures:
            name = type(primary).__name__ if primary is not None else None
            raise NativePublicSecurityFailure(dict(ok=False, step=len(checks), error='cleanup_failed',
                primary=name if name in ERRORS else ('internal' if name else None), cleanup=failures)) from None
