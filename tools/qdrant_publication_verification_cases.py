"""Native ordinary readback observations; no production dispatcher/publication."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from qdrant_publication_native import PublicationDatabase
from qdrant_supervisor_cases import observed_listener, plain, request_bytes
from qdrant_writer_cases import OWNER_TOKEN
from runtime_diagnostics import CleanupFailure

CHECKS = (
    'native_registration_and_atomic_stage',
    'pending_dispatch_refuses_before_http',
    'actual_completed_ack_primitive_settlement',
    'exact_ordinary_current_authority_receipt',
    'serialized_attempt_has_no_capability',
    'serialized_receipt_has_no_private_provenance',
    'equal_count_wrong_membership_rejected',
    'same_dimension_wrong_dense_vector_rejected',
    'wrong_sparse_vector_rejected',
    'missing_named_sparse_vector_rejected',
    'wrong_full_profile_payload_rejected',
    'projection_invalidated_by_owner_replacement',
    'later_authority_change_invalidates_projection_and_scope',
    'fresh_scope_rejects_stale_acl_replica',
    'fresh_scope_current_acl_readback_verified',
    'actual_transport_enforces_remaining_response_allowance',
    'epoch_advance_retires_ordinary_attempt',
    'recovery_attempt_cannot_mint_ordinary_receipt',
    'readback_never_publishes_or_changes_settled_journal',
)
ERRORS = frozenset(('IntegrityViolation', 'UnauthorizedScope', 'UnsupportedCapability',
    'InvalidRequest', 'ProviderUnavailable', 'DeadlineExceeded', 'IndexNotReady', 'internal'))


class NativePublicationVerificationFailure(RuntimeError):
    def __init__(self, step, error):
        super().__init__('publication_verification_native_case_failed')
        name = type(error).__name__
        self.observation = {'step': step, 'error': name if name in ERRORS else 'internal'}


async def python_publication_verification_cases(value):
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit._qdrant_publication_verification import (
        QdrantPublicationVerifier, publication_receipt_data,
    )
    from cragkit._qdrant_supervisor import ManagedQdrantSupervisor
    from cragkit._qdrant_writer import PostgresQdrantWriter, prepare_stage
    from cragkit.contracts import TrustedScope
    from cragkit.errors import (IntegrityViolation, InvalidRequest, ProviderUnavailable,
                                UnauthorizedScope, UnsupportedCapability)

    inputs = value['inputs']
    pool_config = dict(value['writer_config'])
    for key in ('passfile', 'sslrootcert'):
        pool_config[key] = Path(pool_config[key])
    resource = PoolResource(PoolConfig.model_validate(pool_config))
    writer = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
    supervisor = ManagedQdrantSupervisor(Path(value['binary']), Path(value['work_dir']),
        inputs['instance_id'], inputs['config'])
    verifier = QdrantPublicationVerifier(writer, supervisor)
    scope = TrustedScope.model_validate(inputs['scope'])
    context = {'scope': scope, 'collection': inputs['stage']['manifest']['collection'],
        'document_id': inputs['stage']['manifest']['document_id'],
        'intent_id': inputs['stage']['intent']['intent_id'], 'owner_token': OWNER_TOKEN}
    target = '/collections/' + inputs['config']['physical_collection']
    deadline = asyncio.get_running_loop().time() + 100
    connection = handle = None
    endpoint = primary = None
    checks = []

    async def provision(admin, probe):
        await admin.request('PUT', target, body=request_bytes(inputs['collection_config']), deadline=deadline)
        specification = plain(probe)
        probe_target = '/collections/' + specification['collection']
        await admin.request('PUT', probe_target,
            body=request_bytes(specification['collection_config']), deadline=deadline)
        completed(await admin.request('PUT', probe_target + '/points?wait=true&ordering=strong',
            body=request_bytes({'points': [specification['point']]}), deadline=deadline))

    async def expected(kind, operation):
        try:
            await operation()
        except kind:
            return
        raise RuntimeError('publication_verification_expected_failure_missing')

    async def sup(sql, params=()):
        async with connection.transaction():
            await connection.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            await connection.execute('SET LOCAL search_path=pg_catalog')
            await connection.execute("SELECT set_config('cragkit_qdrant.backend_instance_id',%s,true)",
                (inputs['instance_id'],))
            cursor = await connection.execute(sql, params)
            return await cursor.fetchall() if cursor.description is not None else []

    def completed(raw):
        response = json.loads(bytes(raw))
        if (response.get('status') != 'ok'
                or response.get('result', {}).get('status') != 'completed'):
            raise RuntimeError('publication_verification_write_not_completed')

    async def fault_points(points):
        # Deliberate bounded fixture corruption, never a production dispatch.
        completed(await handle.request('PUT', target + '/points?wait=true&ordering=strong',
            body=request_bytes({'points': points}), deadline=deadline))

    async def delete(ids):
        completed(await handle.request('POST', target + '/points/delete?wait=true&ordering=strong',
            body=request_bytes({'points': ids}), deadline=deadline))

    try:
        await supervisor.initialize(deadline=deadline, provision=provision)
        identity = supervisor.identity()
        endpoint = identity['endpoint']
        await observed_listener(endpoint)
        # Explicit fixture bootstrap using the restricted supervisor LOGIN.
        # No application administrator connection remains open in this phase.
        connection = await PublicationDatabase._connect(value['supervisor_config'])
        cursor = await connection.execute("SELECT current_user=session_user,rolcanlogin AND NOT "
            "(rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication),"
            "pg_has_role(current_user,'cragkit_qdrant_supervisor','USAGE'),"
            "NOT pg_has_role(current_user,'cragkit_qdrant_writer','MEMBER') "
            "FROM pg_roles WHERE rolname=current_user")
        if await cursor.fetchall() != [(True, True, True, True)]:
            raise RuntimeError('publication_verification_supervisor_login_boundary')
        await sup('INSERT INTO cragkit_qdrant.backend_instances '
            '(instance_id,backend_namespace,storage_identity,supervisor_id) VALUES (%s,%s,%s,%s)',
            (inputs['instance_id'], inputs['config']['backend_namespace'],
             identity['storage_identity'], identity['supervisor_id']))
        await resource.open()
        await writer.initialize(deadline=deadline)
        await writer.stage(prepare_stage(inputs['stage']), scope,
            owner_token=OWNER_TOKEN, deadline=deadline)
        await writer.acquire_owner(context, deadline=deadline)
        checks.append(CHECKS[0])

        binding = {'intent_id': context['intent_id'], 'owner_token': OWNER_TOKEN,
                   'epoch': 1, 'dispatch_id': 'f1-completed-ack'}
        attempt = supervisor.issue_attempt(binding, deadline=deadline)
        handle = supervisor.transport_for(attempt)
        reservation = await writer.reserve_dispatch(context, {
            'dispatch_id': binding['dispatch_id'], 'sequence': 1,
            'credential_generation': supervisor.attempt_binding(attempt)['credential_generation'],
            'operation': 'complete_point_upsert',
            'point_ids': [point['id'] for point in inputs['expected_points']],
        }, deadline=deadline)
        original_transport_for = supervisor.transport_for
        transport_calls = []

        def observe_transport(capability):
            transport_calls.append(True)
            return original_transport_for(capability)

        supervisor.transport_for = observe_transport
        await expected(ProviderUnavailable,
            lambda: verifier.verify(attempt, context, deadline=deadline))
        if transport_calls:
            raise RuntimeError('publication_verification_pending_http_started')
        checks.append(CHECKS[1])
        await writer.mark_dispatched(context, binding['dispatch_id'], deadline=deadline)
        acknowledgement = await handle.request('PUT', target + '/points?wait=true&ordering=strong',
            body=reservation['request_bytes'], deadline=deadline)
        completed(acknowledgement)
        await writer.settle_dispatch(context, binding['dispatch_id'],
            sha256(acknowledgement).hexdigest(), deadline=deadline)
        checks.append(CHECKS[2])
        receipt = await verifier.verify(attempt, context, deadline=deadline)
        witness = plain(publication_receipt_data(receipt, verifier)['witness'])
        for index in (2, 3, 5):
            witness[index] = '<native-identity>'
        witness_digest = sha256(request_bytes(witness)).hexdigest()
        checks.append(CHECKS[3])
        await expected(InvalidRequest, lambda: verifier.verify(
            plain(supervisor.attempt_binding(attempt)), context, deadline=deadline))
        checks.append(CHECKS[4])
        try:
            publication_receipt_data({}, verifier)
        except InvalidRequest:
            pass
        else:
            raise RuntimeError('publication_verification_copied_receipt_accepted')
        checks.append(CHECKS[5])

        original = deepcopy(inputs['expected_points'])
        changed = deepcopy(original)
        changed[0]['id'] = '00000000-0000-4000-8000-000000000099'
        await delete([original[0]['id']])
        await fault_points([changed[0]])
        await expected(IntegrityViolation, lambda: verifier.verify(attempt, context, deadline=deadline))
        await delete([changed[0]['id']])
        await fault_points(original)
        checks.append(CHECKS[6])
        mutations = (
            lambda point: point['vector'].__setitem__('dense', list(reversed(point['vector']['dense']))),
            lambda point: point['vector']['sparse']['values'].__setitem__(0,
                point['vector']['sparse']['values'][0] + 0.25),
            lambda point: point['vector'].pop('sparse'),
            lambda point: point['payload']['dense_profile'].__setitem__('model', 'wrong-profile'),
        )
        for index, mutate in enumerate(mutations):
            changed = deepcopy(original)
            mutate(changed[0])
            await fault_points(changed)
            await expected(IntegrityViolation,
                lambda: verifier.verify(attempt, context, deadline=deadline))
            await fault_points(original)
            checks.append(CHECKS[7 + index])

        projection = await writer.project_publication(context,
            dict(supervisor.attempt_binding(attempt)), deadline=deadline)
        alternate = dict(context, owner_token='00000000-0000-4000-8000-000000000002')
        await writer.acquire_owner(alternate, deadline=deadline)
        await expected(ProviderUnavailable,
            lambda: writer.validate_publication_projection(projection, deadline=deadline))
        await writer.acquire_owner(context, deadline=deadline)
        checks.append(CHECKS[11])
        projection = await writer.project_publication(context,
            dict(supervisor.attempt_binding(attempt)), deadline=deadline)
        security = {'action': 'update_authorization', 'intent_id': 'f1-authority-change',
            'tenant_id': scope.tenant_id, 'collection': context['collection'],
            'document_id': context['document_id'],
            'expected_authorization_revision': scope.authorization_revision,
            'expected_mutation_epoch': 1,
            'authorization': {'authorization_revision': 'auth-f1-2', 'principal_ids': ['reader-b'],
                'grant_ids': [], 'language': None, 'kind': None, 'tag': 'current', 'tombstoned': False}}
        await writer.apply_security(security, scope, owner_token=OWNER_TOKEN, deadline=deadline)
        await expected(UnauthorizedScope,
            lambda: writer.validate_publication_projection(projection, deadline=deadline))
        await expected(UnauthorizedScope, lambda: verifier.verify(attempt, context, deadline=deadline))
        checks.append(CHECKS[12])
        fresh_scope = TrustedScope.model_validate(dict(inputs['scope'], authorization_revision='auth-f1-2'))
        current = dict(context, scope=fresh_scope)
        await expected(IntegrityViolation, lambda: verifier.verify(attempt, current, deadline=deadline))
        checks.append(CHECKS[13])
        for point in original:
            point['payload'].update(authorization_revision='auth-f1-2', principal_ids=['reader-b'],
                grant_ids=[], tag='current')
            point['payload'].pop('language', None)
            point['payload'].pop('kind', None)
        await fault_points(original)
        await verifier.verify(attempt, current, deadline=deadline)
        checks.append(CHECKS[14])
        await expected(ProviderUnavailable,
            lambda: handle.request('GET', '/', deadline=deadline, max_response_bytes=1))
        checks.append(CHECKS[15])

        await handle.close()
        handle = None
        await sup("UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',"
            "epoch=2,recovery_id='f1-native' WHERE instance_id=%s", (inputs['instance_id'],))
        proof = await supervisor.recover({'recovery_id': 'f1-native', 'old_epoch': 1, 'new_epoch': 2},
            deadline=deadline)
        await expected(ProviderUnavailable, lambda: verifier.verify(attempt, current, deadline=deadline))
        checks.append(CHECKS[16])
        recovery_attempt = supervisor.issue_recovery_attempt(proof, dict(binding, epoch=2,
            recovery_id='f1-native', dispatch_id='f1-recovery-readback'), deadline=deadline)
        await expected(UnsupportedCapability,
            lambda: verifier.verify(recovery_attempt, current, deadline=deadline))
        checks.append(CHECKS[17])
        backend = await sup('SELECT state,epoch FROM cragkit_qdrant.backend_instances '
            'WHERE instance_id=%s', (inputs['instance_id'],))
        journals = await sup('SELECT state FROM cragkit_qdrant.dispatch_journal '
            'WHERE instance_id=%s', (inputs['instance_id'],))
        staged = await writer.inspect(current, deadline=deadline)
        if (backend != [('recovery_blocked', 2)] or journals != [('settled',)]
                or staged is None or staged['state'] != 'writing'
                or staged['authority_committed'] or staged['replica_complete']):
            raise RuntimeError('publication_verification_changed_publication_state')
        # No receipt invocation has changed the original expected pointer or
        # generation flags: source publication remains the dependent F2 task.
        async with resource.lease(deadline=deadline) as lease:
            async with lease.transaction():
                await lease.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                await lease.execute("SELECT set_config('cragkit_qdrant.tenant_id',%s,true),"
                    "set_config('cragkit_qdrant.collection',%s,true),"
                    "set_config('cragkit_qdrant.principal_id',%s,true),"
                    "set_config('cragkit_qdrant.grant_ids',%s,true),"
                    "set_config('cragkit_qdrant.authorization_revision',%s,true),"
                    "set_config('cragkit_qdrant.writer_document_id',%s,true),"
                    "set_config('cragkit_qdrant.writer_intent_id',%s,true),"
                    "set_config('cragkit_qdrant.writer_owner_token',%s,true),"
                    "set_config('cragkit_qdrant.backend_instance_id',%s,true)",
                    (fresh_scope.tenant_id, current['collection'], fresh_scope.principal_id,
                     json.dumps(list(fresh_scope.grant_ids)), fresh_scope.authorization_revision,
                     current['document_id'], current['intent_id'], OWNER_TOKEN, inputs['instance_id']))
                target_sql = ' WHERE tenant_id=%s AND collection=%s AND document_id=%s'
                target_values = (scope.tenant_id, current['collection'], current['document_id'])
                cursor = await lease.execute('SELECT active_generation_id FROM cragkit_qdrant.documents'
                    + target_sql, target_values)
                if await cursor.fetchall() != [(None,)]:
                    raise RuntimeError('publication_verification_pointer_changed')
                cursor = await lease.execute('SELECT published,ever_published FROM cragkit_qdrant.generations'
                    + target_sql, target_values)
                if await cursor.fetchall() != [(False, False)]:
                    raise RuntimeError('publication_verification_generation_published')
        checks.append(CHECKS[18])
        return {'runtime': 'python', 'checks': checks, 'proof_scope': 'ordinary_readback_only',
                'normalized_witness_sha256': witness_digest}
    except BaseException as error:
        primary = error
        if isinstance(error, Exception):
            raise NativePublicationVerificationFailure(len(checks), error) from None
        raise
    finally:
        failures = []
        for operation, owned in (
            ('transport_close', handle), ('verifier_close', verifier), ('writer_close', writer),
            ('resource_close', resource), ('supervisor_connection_close', connection),
            ('controller_close', supervisor),
        ):
            if owned is not None:
                try:
                    await asyncio.wait_for(owned.close(), 8)
                except BaseException as error:
                    failures.append((operation, error))
        if endpoint is not None:
            try:
                await observed_listener(endpoint, allow_absent=True)
            except BaseException as error:
                failures.append(('listener_close', error))
        if failures:
            raise CleanupFailure(failures, primary=primary, stage='recovery') from None
