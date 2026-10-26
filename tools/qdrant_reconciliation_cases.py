"""Explicit E2a native fault observations; journals remain quarantined."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from hashlib import sha256
from pathlib import Path

from qdrant_publication_native import PublicationDatabase
from qdrant_supervisor_cases import plain, request_bytes, observed_listener
from qdrant_writer_cases import OWNER_TOKEN
from runtime_diagnostics import CleanupFailure

CHECKS = (
    'same_generation_different_manifest_rejected_without_member_append',
    'actual_journaled_write_lost_ack_remains_unknown',
    'physical_fence_and_same_owner_epoch_advance_remain_blocked',
    'actual_exact_current_authority_membership_and_vectors_verified',
    'serialized_physical_proof_cannot_mint_receipt',
    'serialized_receipt_has_no_private_provenance',
    'equal_count_wrong_membership_rejected',
    'same_dimension_wrong_dense_vector_rejected',
    'wrong_sparse_vector_rejected',
    'missing_named_sparse_vector_rejected',
    'wrong_full_profile_payload_rejected',
    'stale_scope_and_old_acl_replica_rejected_after_authority_change',
    'fresh_scope_and_actual_current_acl_readback_verified',
    'projection_invalidated_by_later_authority_change',
    'tombstone_requires_actual_absence_and_scoped_eof',
    'unexpected_scoped_point_prevents_tombstone_absence',
    'actual_transport_enforces_remaining_response_allowance',
    'readback_never_settles_journal_or_reopens_gate',
)

ERRORS = frozenset(('IntegrityViolation', 'UnauthorizedScope', 'UnsupportedCapability',
    'InvalidRequest', 'ProviderUnavailable', 'DeadlineExceeded', 'IndexNotReady', 'internal'))


class ReconciliationCaseFailure(RuntimeError):
    def __init__(self, step, error):
        super().__init__('reconciliation_native_case_failed')
        name = type(error).__name__
        self.observation = dict(step=step, error=name if name in ERRORS else 'internal')


async def python_reconciliation_cases(value):
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit._qdrant_supervisor import ManagedQdrantSupervisor
    from cragkit._qdrant_writer import PostgresQdrantWriter, prepare_stage
    from cragkit._qdrant_reconciliation import QdrantReconciliationVerifier, receipt_data
    from cragkit.contracts import TrustedScope
    from cragkit.errors import IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability

    inputs = value['inputs']
    cfg = dict(value['writer_config'])
    for name in ('passfile', 'sslrootcert'):
        cfg[name] = Path(cfg[name])
    resource = PoolResource(PoolConfig.model_validate(cfg))
    writer = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
    supervisor = ManagedQdrantSupervisor(Path(value['binary']), Path(value['work_dir']),
        inputs['instance_id'], inputs['config'])
    scope = TrustedScope.model_validate(inputs['scope'])
    ctx = dict(scope=scope, collection=inputs['stage']['manifest']['collection'],
        document_id=inputs['stage']['manifest']['document_id'],
        intent_id=inputs['stage']['intent']['intent_id'], owner_token=OWNER_TOKEN)
    deadline = asyncio.get_running_loop().time() + 100
    target = '/collections/' + inputs['config']['physical_collection']
    connection = handle = None
    endpoint = None
    primary = None
    checks = []

    async def provision(admin, probe):
        await admin.request('PUT', target, body=request_bytes(inputs['collection_config']), deadline=deadline)
        probe = plain(probe)
        await admin.request('PUT', '/collections/' + probe['collection'],
            body=request_bytes(probe['collection_config']), deadline=deadline)
        await admin.request('PUT', '/collections/' + probe['collection'] + '/points?wait=true&ordering=strong',
            body=request_bytes({'points': [probe['point']]}), deadline=deadline)

    async def expected(kind, operation):
        try:
            await operation()
        except kind:
            return
        raise RuntimeError('reconciliation_expected_failure_missing')

    async def sup(sql, params=()):
        async with connection.transaction():
            await connection.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
            await connection.execute('SET LOCAL search_path=pg_catalog')
            await connection.execute("SELECT set_config('cragkit_qdrant.backend_instance_id',%s,true)",
                (inputs['instance_id'],))
            cursor = await connection.execute(sql, params)
            return await cursor.fetchall() if cursor.description is not None else []

    async def fault_points(points):
        # Deliberate test-only corruption, never a production replay or receipt.
        completed(await handle.request('PUT', target + '/points?wait=true&ordering=strong',
            body=request_bytes({'points': points}), deadline=deadline))

    async def delete(ids):
        completed(await handle.request('POST', target + '/points/delete?wait=true&ordering=strong',
            body=request_bytes({'points': ids}), deadline=deadline))

    def completed(raw):
        result = json.loads(bytes(raw))
        if result.get('status') != 'ok' or result.get('result', {}).get('status') != 'completed':
            raise RuntimeError('reconciliation_fixture_write_not_completed')

    try:
        await supervisor.initialize(deadline=deadline, provision=provision)
        identity = supervisor.identity()
        endpoint = identity['endpoint']
        await observed_listener(endpoint)
        connection = await PublicationDatabase._connect(value['supervisor_config'])
        cursor = await connection.execute("SELECT current_user=session_user,rolcanlogin AND NOT "
            "(rolsuper OR rolbypassrls OR rolcreaterole OR rolcreatedb OR rolreplication),"
            "pg_has_role(current_user,'cragkit_qdrant_supervisor','USAGE'),"
            "NOT pg_has_role(current_user,'cragkit_qdrant_writer','MEMBER') FROM pg_roles WHERE rolname=current_user")
        if await cursor.fetchall() != [(True, True, True, True)]:
            raise RuntimeError('reconciliation_fixture_supervisor_login_boundary')
        await sup('INSERT INTO cragkit_qdrant.backend_instances '
            '(instance_id,backend_namespace,storage_identity,supervisor_id) VALUES (%s,%s,%s,%s)',
            (inputs['instance_id'], inputs['config']['backend_namespace'],
             identity['storage_identity'], identity['supervisor_id']))
        await resource.open()
        await writer.initialize(deadline=deadline)
        await writer.stage(prepare_stage(inputs['stage']), scope, owner_token=OWNER_TOKEN, deadline=deadline)
        await expected(IntegrityViolation, lambda: writer.stage(prepare_stage(inputs['conflicting_stage']),
            scope, owner_token=OWNER_TOKEN, deadline=deadline))
        intact = await writer.load_stage(ctx, deadline=deadline)
        if intact.member_count != 2:
            raise RuntimeError('reconciliation_generation_members_changed')
        checks.append(CHECKS[0])
        await writer.acquire_owner(ctx, deadline=deadline)
        binding = dict(intent_id=ctx['intent_id'], owner_token=OWNER_TOKEN,
            epoch=1, dispatch_id='e2a-lost-ack')
        cap = supervisor.issue_attempt(binding, deadline=deadline)
        ordinary = supervisor.transport_for(cap)
        reservation = await writer.reserve_dispatch(ctx, dict(dispatch_id=binding['dispatch_id'],
            sequence=1, credential_generation=supervisor.attempt_binding(cap)['credential_generation'],
            operation='complete_point_upsert', point_ids=[p['id'] for p in inputs['expected_points']]), deadline=deadline)
        await writer.mark_dispatched(ctx, binding['dispatch_id'], deadline=deadline)
        completed(await ordinary.request('PUT', target + '/points?wait=true&ordering=strong',
            body=reservation['request_bytes'], deadline=deadline))
        await writer.mark_unknown(ctx, binding['dispatch_id'], deadline=deadline)
        await ordinary.close()
        checks.append(CHECKS[1])
        await sup("UPDATE cragkit_qdrant.backend_instances SET state='recovery_blocked',"
            "epoch=2,recovery_id='e2a-native' WHERE instance_id=%s", (inputs['instance_id'],))
        proof = await supervisor.recover(dict(recovery_id='e2a-native', old_epoch=1, new_epoch=2), deadline=deadline)
        await sup('UPDATE cragkit_qdrant.document_owners SET backend_epoch=2 WHERE instance_id=%s',
            (inputs['instance_id'],))
        checks.append(CHECKS[2])
        verifier = QdrantReconciliationVerifier(writer, supervisor)
        receipt = await verifier.verify(proof, ctx, deadline=deadline)
        witness = plain(receipt_data(receipt, verifier)['witness'])
        for index in (2, 3, 7):
            witness[index] = '<native-identity>'
        witness_digest = sha256(request_bytes(witness)).hexdigest()
        checks.append(CHECKS[3])
        await expected(UnsupportedCapability, lambda: verifier.verify(plain(supervisor.recovery_binding(proof)), ctx, deadline=deadline))
        checks.append(CHECKS[4])
        # The helper is internal and must reject a copied public empty receipt.
        try:
            receipt_data({}, verifier)
        except InvalidRequest:
            pass
        else:
            raise RuntimeError('reconciliation_copied_receipt_accepted')
        checks.append(CHECKS[5])
        cap = supervisor.issue_recovery_attempt(proof, dict(binding, epoch=2,
            recovery_id='e2a-native', dispatch_id='e2a-fault-injection'), deadline=deadline)
        handle = supervisor.transport_for(cap)
        original = deepcopy(inputs['expected_points'])
        changed = deepcopy(original)
        changed[0]['id'] = '00000000-0000-4000-8000-000000000099'
        await delete([original[0]['id']])
        await fault_points([changed[0]])
        await expected(IntegrityViolation, lambda: verifier.verify(proof, ctx, deadline=deadline))
        await delete([changed[0]['id']])
        await fault_points(original)
        checks.append(CHECKS[6])
        mutations = [
            lambda p: p['vector'].__setitem__('dense', list(reversed(p['vector']['dense']))),
            lambda p: p['vector']['sparse']['values'].__setitem__(0, p['vector']['sparse']['values'][0] + 0.25),
            lambda p: p['vector'].pop('sparse'),
            lambda p: p['payload']['dense_profile'].__setitem__('model', 'wrong-profile'),
        ]
        for index, mutate in enumerate(mutations):
            changed = deepcopy(original)
            mutate(changed[0])
            await fault_points(changed)
            await expected(IntegrityViolation, lambda: verifier.verify(proof, ctx, deadline=deadline))
            await fault_points(original)
            checks.append(CHECKS[7 + index])
        security = dict(action='update_authorization', intent_id='e2a-authority-change',
            tenant_id=scope.tenant_id, collection=ctx['collection'], document_id=ctx['document_id'],
            expected_authorization_revision=scope.authorization_revision, expected_mutation_epoch=1,
            authorization=dict(authorization_revision='auth-e2a-2', principal_ids=['reader-b'],
                grant_ids=[], language=None, kind=None, tag='current', tombstoned=False))
        await writer.apply_security(security, scope, owner_token=OWNER_TOKEN, deadline=deadline)
        await expected(UnauthorizedScope, lambda: verifier.verify(proof, ctx, deadline=deadline))
        fresh = TrustedScope.model_validate(dict(inputs['scope'], authorization_revision='auth-e2a-2'))
        current = dict(ctx, scope=fresh)
        await expected(IntegrityViolation, lambda: verifier.verify(proof, current, deadline=deadline))
        checks.append(CHECKS[11])
        for point in original:
            point['payload'].update(authorization_revision='auth-e2a-2', principal_ids=['reader-b'], grant_ids=[], tag='current')
            point['payload'].pop('language', None)
            point['payload'].pop('kind', None)
        await fault_points(original)
        await verifier.verify(proof, current, deadline=deadline)
        checks.append(CHECKS[12])
        projection = await writer.project_stage(current, dict(supervisor.recovery_binding(proof)), deadline=deadline)
        tombstone = dict(security, action='tombstone', intent_id='e2a-tombstone',
            expected_authorization_revision='auth-e2a-2', expected_mutation_epoch=2,
            authorization=dict(authorization_revision='auth-e2a-3', principal_ids=[], grant_ids=[],
                language=None, kind=None, tag=None, tombstoned=True))
        await writer.apply_security(tombstone, fresh, owner_token=OWNER_TOKEN, deadline=deadline)
        await expected((IntegrityViolation, UnauthorizedScope), lambda: writer.validate_projection(projection, deadline=deadline))
        checks.append(CHECKS[13])
        dead = dict(ctx, scope=TrustedScope.model_validate(dict(inputs['scope'], authorization_revision='auth-e2a-3')))
        await expected(IntegrityViolation, lambda: verifier.verify(proof, dead, deadline=deadline))
        await delete([p['id'] for p in original])
        await verifier.verify(proof, dead, deadline=deadline)
        checks.append(CHECKS[14])
        foreign = deepcopy(original[0])
        foreign['id'] = '00000000-0000-4000-8000-000000000098'
        foreign['payload']['dense_profile']['model'] = 'wrong-profile'
        await fault_points([foreign])
        await expected(IntegrityViolation, lambda: verifier.verify(proof, dead, deadline=deadline))
        await delete([foreign['id']])
        await verifier.verify(proof, dead, deadline=deadline)
        checks.append(CHECKS[15])
        await expected(ProviderUnavailable, lambda: handle.request('GET', '/', deadline=deadline, max_response_bytes=1))
        checks.append(CHECKS[16])
        state = await sup('SELECT state,epoch FROM cragkit_qdrant.backend_instances WHERE instance_id=%s', (inputs['instance_id'],))
        pending = await sup('SELECT state FROM cragkit_qdrant.dispatch_journal WHERE instance_id=%s', (inputs['instance_id'],))
        if state != [('recovery_blocked', 2)] or pending != [('unknown',)]:
            raise RuntimeError('reconciliation_readback_changed_gate_or_journal')
        checks.append(CHECKS[17])
        return dict(runtime='python', checks=checks, proof_scope='authority_bound_readback_only',
            normalized_witness_sha256=witness_digest)
    except BaseException as error:
        primary = error
        if isinstance(error, Exception):
            raise ReconciliationCaseFailure(len(checks), error) from None
        raise
    finally:
        failures = []
        for operation, owned in [('transport_close', handle), ('writer_close', writer),
                ('resource_close', resource), ('supervisor_connection_close', connection),
                ('controller_close', supervisor)]:
            if owned is not None:
                try:
                    await asyncio.wait_for(owned.close(), 8)
                except BaseException as error:
                    failures.append(('runtime_close', error))
        if endpoint is not None:
            try:
                await observed_listener(endpoint, allow_absent=True)
            except BaseException as error:
                failures.append(('verify_inventory', error))
        if failures:
            raise CleanupFailure(failures, primary=primary, stage='recovery') from None
