"""Native public current-security convergence on disposable servers."""
from __future__ import annotations

from copy import deepcopy
from qdrant_security_verification_cases import NativeSecurityVerificationFailure

CHECKS = (
    'public_authority_then_full_document_convergence',
    'completed_retry_has_no_physical_or_authority_mutation',
    'repeated_update_preserves_original_stage_history',
    'acl_replica_ack_lost_replays_current_revocation',
    'lost_completed_ack_keeps_pending_and_retry_refences',
    'current_source_allowed_and_revoked_scopes',
    'ownerless_denied_stage_public_bootstrap',
    'authority_change_during_convergence_refuses_stale_completion',
    'tombstone_during_convergence_denies_source_and_preserves_pending',
)


class NativePublicSecurityFailure(NativeSecurityVerificationFailure):
    def __init__(self, observation):
        super().__init__('public_security_native_case_failed')
        self.observation = observation


async def python_public_security_cases(value):
    import asyncio
    import hashlib
    import json
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit.contracts import Limits, TrustedScope
    from cragkit.execution import ExecutionLedger
    from cragkit.errors import ProviderUnavailable, UnauthorizedScope
    from cragkit.qdrant import QdrantNomination
    from cragkit.qdrant_source import PostgresQdrantSourceStore
    from cragkit._qdrant_writer import security_projection_data
    from cragkit.qdrant_publication import (
        QdrantPublicationManager, QdrantSecurityManager,
        PostgresQdrantPublicationAuthority, ManagedQdrantPublicationTransport,
        PostgresQdrantWriter, PostgresQdrantRecovery, ManagedQdrantSupervisor,
        QdrantReconciliationVerifier,
    )
    from qdrant_publication_manager_cases import ERRORS
    from qdrant_supervisor_cases import plain, request_bytes, observed_listener

    inputs = value['inputs']
    deadline = asyncio.get_running_loop().time() + 120
    def configuration(raw):
        raw = dict(raw)
        for key in ('sslrootcert', 'passfile'):
            raw[key] = Path(raw[key])
        config = PoolConfig.model_validate(raw)
        if config.max_size != 1:
            raise RuntimeError('public_security_pool_bound')
        return config
    resource = PoolResource(configuration(value['writer_config']))
    supervisor_resource = PoolResource(configuration(value['supervisor_config']))
    reader = PoolResource(configuration(value['reader_config']))
    supervisor = ManagedQdrantSupervisor(Path(value['binary']), Path(value['work_dir']),
        inputs['instance_id'], inputs['config'])
    writer = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
    verifier = QdrantReconciliationVerifier(writer, supervisor)
    recovery = PostgresQdrantRecovery(supervisor_resource, inputs['config'], supervisor, verifier)
    authority = PostgresQdrantPublicationAuthority(writer, recovery)
    transport = ManagedQdrantPublicationTransport(supervisor)
    base = inputs['stage']
    collection = base['manifest']['collection']
    document = base['manifest']['document_id']
    ownerless_document = inputs['ownerless_stage']['manifest']['document_id']
    target = '/collections/' + inputs['config']['physical_collection']
    token = '00000000-0000-4000-8000-000000000099'
    scope = TrustedScope.model_validate(inputs['scope'])
    checks, observations, requests, stores = [], [], [], []
    hook = dict(change=None, scope=None)
    network = dict(count=0, armed=False, drops=0, completed=0, puts=0, retired_resends=0)
    lost = {}
    endpoint = primary = manager = security_manager = None
    original_http = supervisor._http

    def trusted(revision, principal=None):
        return TrustedScope.model_validate(dict(inputs['scope'], authorization_revision=revision,
            principal_id=principal or scope.principal_id))
    def reference(item):
        if 'manifest' in item:
            return dict(collection=item['manifest']['collection'], document_id=item['manifest']['document_id'],
                intent_id=item['intent']['intent_id'])
        return {key: item[key] for key in ('collection', 'document_id', 'intent_id')}
    def context(item, selected):
        return dict(**reference(item), scope=selected, owner_token=token)
    async def snapshot(item, selected):
        return await writer.manager_snapshot(context(item, selected), deadline=deadline)
    async def call(method, item, selected):
        book = ExecutionLedger(Limits(max_provider_calls=0), deadline=deadline)
        try:
            return await method(item, selected, book, deadline=deadline)
        finally:
            usage = book.snapshot()
            if (usage['attempts'], usage['provider_calls'], usage['pending']) != (1, 0, 0):
                raise RuntimeError('public_security_usage')
    async def permitted(selected, selected_collection, selected_document):
        return (selected.tenant_id == scope.tenant_id and selected_collection == collection
            and selected_document in (document, ownerless_document))
    async def authorize(selected, selected_collection, selected_document):
        if not await permitted(selected, selected_collection, selected_document):
            return False
        change = hook['change']
        if change is not None:
            selected_scope = hook['scope']
            hook['change'] = None
            await commit(change, selected_scope)
        return True
    async def commit(change, selected):
        method = security_manager.tombstone if change['action'] == 'tombstone' else security_manager.update_authorization
        result = plain(await call(method, change, selected))
        if not result['authority_committed'] or result['replica_complete'] or result['purge_complete']:
            raise RuntimeError('public_security_authority_flags')
        return result
    async def converge(change, selected):
        result = plain(await call(manager.converge_security, reference(change), selected))
        if (result['operation'] != 'converge_security' or result['state'] != 'complete'
                or not result['authority_committed'] or not result['replica_complete'] or result['purge_complete']):
            raise RuntimeError('public_security_completion_flags')
        return result
    def row(result):
        return [result[key] for key in ('intent_id', 'operation', 'state',
            'authority_committed', 'replica_complete', 'purge_complete')]
    def change(number, *, tombstone=False):
        result = deepcopy(inputs['security'])
        result.update(action='tombstone' if tombstone else 'update_authorization',
            intent_id='native-security-public-tombstone' if tombstone else f'native-security-public-auth-{number}',
            expected_authorization_revision=f'auth-{number - 1}', expected_mutation_epoch=number - 1)
        result['authorization'].update(authorization_revision=f'auth-{number}', principal_ids=['reader-b'],
            grant_ids=[], tag=f'public-security-{number}', tombstoned=tombstone)
        return result
    async def expect(kind, operation):
        try:
            await operation()
        except kind:
            return
        raise RuntimeError('public_security_expected_refusal')
    async def observed_http(*args, **kwargs):
        network['count'] += 1
        if (len(args) > 2 and args[1] == 'PUT'
                and args[2] == target + '/points?wait=true&ordering=strong'
                and lost.get('key') == args[0]):
            network['retired_resends'] += 1
        result = await original_http(*args, **kwargs)
        if len(args) > 2 and args[1] == 'PUT' and args[2] == target + '/points?wait=true&ordering=strong':
            network['puts'] += 1
            if network['armed']:
                status, raw = result
                response = json.loads(raw)
                if status != 200 or response.get('status') != 'ok' or response.get('result', {}).get('status') != 'completed':
                    raise RuntimeError('public_security_fault_not_completed')
                network.update(armed=False, drops=network['drops'] + 1, completed=network['completed'] + 1)
                lost.update(key=args[0], points=json.loads(args[3])['points'])
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
    nomination = QdrantNomination.model_validate(dict(point_id=point['id'], branch='dense', score=1.0,
        score_kind='cosine_similarity', payload=point['payload']))
    async def source(selected):
        store = PostgresQdrantSourceStore(reader, inputs['config'])
        stores.append(store)
        await store.initialize(deadline=deadline)
        request = store.open_request(dict(query='native security verification', collection=collection),
            scope=selected, deadline=deadline)
        requests.append(request)
        fetched = await request.fetch_candidate(nomination, max_source_bytes=16777216, include_source=True)
        if fetched.state == 'verified':
            member = next(item for item in base['manifest']['members'] if item['point_id'] == point['id'])
            canonical = base['canonical_text'].encode('utf-8')
            excerpt = canonical[member['start_byte']:member['end_byte']]
            evidence = fetched.evidence
            if (evidence is None or fetched.binding is None or evidence.text != excerpt.decode('utf-8')
                    or evidence.source_sha256 != hashlib.sha256(canonical).hexdigest()
                    or evidence.text_sha256 != hashlib.sha256(excerpt).hexdigest()
                    or fetched.private_source is None or fetched.private_source.canonical_text != base['canonical_text']):
                raise RuntimeError('public_security_source_fidelity')
        elif (fetched.state != 'unavailable' or fetched.binding is not None or fetched.evidence is not None
                or fetched.private_source is not None or fetched.source_bytes):
            raise RuntimeError('public_security_source_disclosure')
        return request, store, fetched
    async def close_source(request, store):
        await request.close()
        await store.close()
    async def journal(intent_id, *, pending_only=False):
        async with supervisor_resource.lease(deadline=deadline) as connection:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                await connection.execute("SELECT set_config('cragkit_qdrant.backend_instance_id',%s,true)",
                    (inputs['instance_id'],))
                cursor = await connection.execute('SELECT state,completion_sha256 FROM cragkit_qdrant.dispatch_journal '
                    'WHERE instance_id=%s AND tenant_id=%s AND collection=%s AND document_id=%s '
                    'AND intent_id=%s ' + ("AND state<>'settled' " if pending_only else '')
                    + 'ORDER BY sequence LIMIT 9',
                    (inputs['instance_id'], scope.tenant_id, collection, document, intent_id))
                return await cursor.fetchall()

    try:
        supervisor._http = observed_http
        await supervisor.initialize(deadline=deadline, provision=provision)
        endpoint = supervisor.identity()['endpoint']
        await observed_listener(endpoint)
        await resource.open()
        await supervisor_resource.open()
        await reader.open()
        manager = QdrantPublicationManager(authority, transport, inputs['config'], supervisor, authorize)
        security_manager = QdrantSecurityManager(writer, permitted)
        await manager.initialize(deadline=deadline)
        await security_manager.initialize(deadline=deadline)
        await call(manager.stage, base, scope)
        published = plain(await call(manager.publish, reference(base), scope))
        if published['state'] != 'published' or not published['published']:
            raise RuntimeError('public_security_base_not_published')
        second = deepcopy(inputs['second_stage'])
        second['intent']['expected_active_generation_id'] = base['manifest']['generation_id']
        await call(manager.stage, second, scope)
        original = await snapshot(base, scope)
        first = deepcopy(inputs['security'])
        first['authorization'].update(principal_ids=[scope.principal_id], grant_ids=[])
        await commit(first, scope)
        auth2 = trusted('auth-2')
        projected = security_projection_data(await writer.project_security(context(first, auth2), deadline=deadline), writer)
        if len(projected['generations']) != 2 or len(projected['point_ids']) != 4:
            raise RuntimeError('public_security_claimed_inventory')
        first_result = await converge(first, auth2)
        checks.append(CHECKS[0]); observations.append(row(first_result))
        before, count = await snapshot(first, auth2), network['count']
        retry = await converge(first, auth2)
        if retry != first_result or await snapshot(first, auth2) != before or network['count'] != count:
            raise RuntimeError('public_security_completed_retry_mutated')
        checks.append(CHECKS[1]); observations.append(row(retry))
        retained_request, retained_store, retained = await source(auth2)
        if retained.state != 'verified':
            raise RuntimeError('public_security_source_initial')
        third = change(3)
        await commit(third, auth2)
        auth3 = trusted('auth-3', 'reader-b')
        drops, completed, puts = network['drops'], network['completed'], network['puts']
        network['armed'] = True
        await expect(ProviderUnavailable, lambda: converge(third, auth3))
        pending = await snapshot(third, auth3)
        generation = supervisor.control_binding()['credential_generation']
        if not pending['pending']:
            raise RuntimeError('public_security_acl_pending_missing')
        if pending['backend']['state'] != 'recovery_blocked':
            raise RuntimeError('public_security_acl_backend_not_blocked')
        if not pending['intent']['authority_committed'] or pending['intent']['replica_complete']:
            raise RuntimeError('public_security_acl_authority_flags')
        if pending['document']['authorization_revision'] != 'auth-3':
            raise RuntimeError('public_security_acl_authority_revision')
        owner_intent = pending['owner']['intent_id']
        if await journal(owner_intent, pending_only=True) != [('unknown', None)]:
            raise RuntimeError('public_security_acl_journal_not_unknown')
        if network['drops'] != drops + 1 or network['completed'] != completed + 1:
            raise RuntimeError('public_security_acl_completed_loss_count')
        if network['puts'] != puts + 1:
            raise RuntimeError('public_security_acl_initial_put_count')
        released = await retained_request.release(retained.binding, purpose='final', max_source_bytes=16777216, include_source=True)
        if (released.state != 'unavailable' or released.binding is not None or released.evidence is not None
                or released.private_source is not None or released.source_bytes != 0):
            raise RuntimeError('public_security_retained_release')
        await close_source(retained_request, retained_store)
        denied_request, denied_store, denied = await source(trusted('auth-3'))
        allowed_request, allowed_store, allowed = await source(trusted('auth-3', 'reader-b'))
        if (denied.state, allowed.state) != ('unavailable', 'verified'):
            raise RuntimeError('public_security_current_source')
        source_row = ['source', retained.state, released.state, denied.state, allowed.state]
        await close_source(denied_request, denied_store)
        await close_source(allowed_request, allowed_store)
        third_result = await converge(third, auth3)
        retired_key = lost.pop('key')
        status, _ = await original_http(retired_key, 'GET', target, None, deadline)
        if status != 401:
            raise RuntimeError('public_security_acl_old_key_not_fenced')
        if supervisor.control_binding()['credential_generation'] == generation:
            raise RuntimeError('public_security_acl_credential_generation_unchanged')
        if network['retired_resends']:
            raise RuntimeError('public_security_acl_replay_used_retired_key')
        current = security_projection_data(await writer.project_security(context(third, auth3), deadline=deadline), writer)
        status, raw = await original_http(supervisor._key, 'POST', target + '/points',
            request_bytes(dict(ids=list(current['point_ids']), with_payload=True, with_vector=True)), deadline)
        physical = json.loads(raw)
        points = physical.get('result', [])
        expected_ids = sorted(current['point_ids'])
        expected_payloads = {item.point_id: item.payload.model_dump(mode='json', exclude_none=True)
            for item in current['points']}
        if (status != 200 or physical.get('status') != 'ok' or len(expected_ids) != 4
                or sorted(item['id'] for item in points) != expected_ids
                or any(item['payload']['authorization_revision'] != 'auth-3'
                    or item['payload']['principal_ids'] != ['reader-b'] or item['payload']['grant_ids'] != []
                    or item['payload'] != expected_payloads[item['id']]
                    for item in points)
                or any(item['payload']['authorization_revision'] != 'auth-3' for item in lost['points'])
                or sorted(item['id'] for item in lost['points']) != expected_ids
                or any(item['payload'] != expected_payloads[item['id']]
                    or 'dense' not in item['vector'] for item in lost['points'])
                or any(state != 'settled' or digest is None for state, digest in await journal(owner_intent))
                or network['drops'] != drops + 1 or network['completed'] != completed + 1):
            raise RuntimeError('public_security_acl_current_replica_missing')
        recovered = await snapshot(third, auth3)
        if recovered['pending'] or recovered['backend']['state'] != 'open':
            raise RuntimeError('public_security_acl_recovery_incomplete')
        historical = await snapshot(base, trusted('auth-3', 'reader-b'))
        if historical['intent'] != original['intent'] or historical['document']['active_generation_id'] != base['manifest']['generation_id']:
            raise RuntimeError('public_security_history_changed')
        checks.append(CHECKS[2]); observations.append(row(third_result))
        checks.append(CHECKS[3]); observations.append(['acl_replica_ack_lost', 'auth-3', 'recovery_blocked',
            'unknown', 'unavailable', 'unavailable', 0, 1, 0, True, True])
        fourth = change(4)
        await commit(fourth, trusted('auth-3', 'reader-b'))
        auth4 = trusted('auth-4', 'reader-b')
        drops, completed = network['drops'], network['completed']
        network['armed'] = True
        await expect(ProviderUnavailable, lambda: converge(fourth, auth4))
        pending = await snapshot(fourth, auth4)
        generation = supervisor.control_binding()['credential_generation']
        if not pending['pending'] or pending['backend']['state'] != 'recovery_blocked' or pending['intent']['replica_complete']:
            raise RuntimeError('public_security_unknown_not_preserved')
        fourth_result = await converge(fourth, auth4)
        if (supervisor.control_binding()['credential_generation'] == generation
                or network['drops'] != drops + 1 or network['completed'] != completed + 1):
            raise RuntimeError('public_security_retry_not_refenced')
        checks.append(CHECKS[4]); observations.append(row(fourth_result))
        checks.append(CHECKS[5]); observations.append(source_row)
        ownerless = inputs['ownerless_stage']
        await call(manager.stage, ownerless, scope)
        ownerless_change = deepcopy(inputs['ownerless_security'])
        ownerless_change['authorization'].update(principal_ids=[scope.principal_id], grant_ids=[])
        await commit(ownerless_change, scope)
        denied_stage = await writer.admit_publication(context(ownerless, auth2), deadline=deadline)
        ownerless_before = await snapshot(ownerless, auth2)
        if denied_stage['intent']['state'] != 'denied' or ownerless_before['owner'] is not None:
            raise RuntimeError('public_security_ownerless_prerequisite')
        ownerless_result = await converge(ownerless_change, auth2)
        checks.append(CHECKS[6]); observations.append(row(ownerless_result))
        fifth, sixth = change(5), change(6)
        await commit(fifth, auth4)
        hook.update(change=sixth, scope=trusted('auth-5', 'reader-b'))
        await expect(UnauthorizedScope, lambda: converge(fifth, trusted('auth-5', 'reader-b')))
        drift = await snapshot(sixth, trusted('auth-6', 'reader-b'))
        if (hook['change'] is not None or drift['document']['authorization_revision'] != 'auth-6'
                or drift['document']['active_generation_id'] != base['manifest']['generation_id']):
            raise RuntimeError('public_security_drift_authority')
        checks.append(CHECKS[7]); observations.append(['drift', 'unauthorized_scope', 'auth-6'])
        await converge(sixth, trusted('auth-6', 'reader-b'))
        seventh, tombstone = change(7), change(8, tombstone=True)
        await commit(seventh, trusted('auth-6', 'reader-b'))
        hook.update(change=tombstone, scope=trusted('auth-7', 'reader-b'))
        await expect(UnauthorizedScope, lambda: converge(seventh, trusted('auth-7', 'reader-b')))
        final = await snapshot(tombstone, trusted('auth-8', 'reader-b'))
        final_request, final_store, unavailable = await source(trusted('auth-8', 'reader-b'))
        if (hook['change'] is not None or final['document']['authorization_revision'] != 'auth-8'
                or not final['document']['tombstoned'] or not final['intent']['authority_committed']
                or final['intent']['replica_complete'] or final['intent']['purge_complete']
                or unavailable.state != 'unavailable'):
            raise RuntimeError('public_security_tombstone_authority')
        await close_source(final_request, final_store)
        checks.append(CHECKS[8]); observations.append(['tombstone', 'unauthorized_scope', 'unavailable', True, False])
        witness = json.dumps(['cragkit.qdrant.public-security.v1', observations], ensure_ascii=False,
            separators=(',', ':')).encode('utf-8')
        return dict(runtime='python', checks=checks, proof_scope='native_public_security_convergence_only',
            semantic_witness_sha256=hashlib.sha256(witness).hexdigest())
    except BaseException as error:
        primary = error
        name = type(error).__name__
        failure = NativePublicSecurityFailure(dict(ok=False, step=len(checks), error=name if name in ERRORS else 'internal'))
        failure.primary = error
        raise failure from None
    finally:
        supervisor._http = original_http
        failures = []
        cleanup_deadline = asyncio.get_running_loop().time() + 12
        async def close(operation, function):
            try:
                await asyncio.wait_for(function(), max(.001, min(8, cleanup_deadline - asyncio.get_running_loop().time())))
            except BaseException:
                failures.append(operation)
        owned = [('source_request', item) for item in requests] + [('source_store', item) for item in stores]
        owned += [('manager', item) for item in (manager, security_manager) if item is not None]
        owned += [('transport', transport), ('authority', authority), ('recovery', recovery), ('verifier', verifier),
            ('writer', writer), ('reader_pool', reader), ('writer_pool', resource),
            ('supervisor_pool', supervisor_resource), ('supervisor', supervisor)]
        for operation, item in owned:
            if callable(getattr(item, 'close', None)):
                await close(operation, item.close)
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
            async def listener():
                await observed_listener(endpoint, allow_absent=True)
            await close('listener', listener)
        if failures:
            name = type(primary).__name__ if primary is not None else None
            raise NativePublicSecurityFailure(dict(ok=False, step=len(checks), error='cleanup_failed',
                primary=name if name in ERRORS else ('internal' if name else None), cleanup=failures)) from None
