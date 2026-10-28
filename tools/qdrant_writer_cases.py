"""Native writer transaction cases; remote completion proof belongs to F/H."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json

from qdrant_publication_schema import publication_fixture
from runtime_diagnostics import CleanupFailure

OWNER_TOKEN = '00000000-0000-4000-8000-000000000001'


def writer_input():
    """Build a creation intent from the committed two-member synthetic fixture."""
    fixture = publication_fixture()
    document, source = fixture['document'], fixture['source_revision']
    manifest = dict(fixture['physical'], **{key: document[key]
        for key in ('tenant_id', 'collection', 'document_id')})
    manifest.update({key: source[key] for key in
        ('revision_id', 'source_sha256', 'source_bytes', 'source_locator', 'parser_id')})
    manifest.update(generation_id=fixture['intent']['generation_id'],
        chunker_profile=fixture['intent']['chunker_profile'],
        dense_profile=fixture['profiles']['dense'], sparse_profile=fixture['profiles']['sparse'], members=[])
    dense, sparse = [], []
    for member in fixture['members']:
        manifest['members'].append({key: member[key] for key in
            ('chunk_id', 'point_id', 'start_byte', 'end_byte', 'text_sha256')} | dict(
                dense_input_sha256=member['dense']['vector_sha256'],
                sparse_input_sha256=member['sparse']['vector_sha256']))
        vector = [0.0] * 1536
        vector[member['dense']['basis_index']] = member['dense']['value']
        dense.append(vector)
        sparse.append({key: member['sparse'][key] for key in ('indices', 'values')})
    initial = {key: document[key] for key in
        ('authorization_revision', 'principal_ids', 'grant_ids', 'language', 'kind', 'tag')}
    initial['tombstoned'] = False
    intent = {key: document[key] for key in ('tenant_id', 'collection', 'document_id')}
    intent.update(intent_id=fixture['intent']['intent_id'], manifest_sha256=fixture['intent']['manifest_sha256'],
        expected_active_generation_id=None, expected_authorization_revision=document['authorization_revision'],
        expected_mutation_epoch=1, initial_authorization=initial)
    config = dict(fixture['physical'], dense_profile=fixture['profiles']['dense'],
        sparse_profile=fixture['profiles']['sparse'])
    scope = dict(tenant_id=document['tenant_id'], principal_id='reader-a',
        authorization_revision=document['authorization_revision'], grant_ids=['grant-a'])
    expected_points = []
    for member, vector, sparse_vector in zip(manifest['members'], dense, sparse, strict=True):
        payload = {key: manifest[key] for key in ('backend_namespace', 'physical_collection',
            'collection_incarnation', 'tenant_id', 'collection', 'document_id', 'revision_id',
            'generation_id', 'source_sha256', 'dense_profile', 'sparse_profile')}
        payload.update({key: member[key] for key in
            ('chunk_id', 'start_byte', 'end_byte', 'text_sha256')})
        payload.update(dense_profile_id=config['dense_profile']['profile_id'],
            sparse_profile_id=config['sparse_profile']['profile_id'],
            authorization_revision=initial['authorization_revision'],
            principal_ids=sorted(set(initial['principal_ids']), key=lambda item: item.encode()),
            grant_ids=sorted(set(initial['grant_ids']), key=lambda item: item.encode()))
        payload.update({key: initial[key] for key in ('language', 'kind', 'tag') if initial[key] is not None})
        expected_points.append(dict(id=member['point_id'], payload=payload,
            vector=dict(dense=vector, sparse=sparse_vector)))
    return dict(config=config, scope=scope, expected_points=deepcopy(expected_points), stage=dict(manifest=manifest,
        canonical_text=source['canonical_utf8']['value'], intent=intent,
        dense_vectors=dense, sparse_vectors=sparse), instance_id='instance-fixture')


def successor_stage(inputs, suffix, expected_active):
    """Derive new immutable fixture identities without changing the source bytes."""
    from cragkit._qdrant_contract import point_id
    from cragkit._qdrant_manifest import encode_manifest
    stage = deepcopy(inputs['stage'])
    manifest = stage['manifest']
    manifest['revision_id'] = 'rev-' + suffix
    manifest['generation_id'] = 'gen-' + suffix
    for member in manifest['members']:
        member['point_id'] = point_id(['cragkit.qdrant.point.v1', manifest['backend_namespace'],
            manifest['physical_collection'], manifest['collection_incarnation'], manifest['tenant_id'],
            manifest['collection'], manifest['document_id'], manifest['revision_id'], manifest['generation_id'],
            member['chunk_id'], manifest['dense_profile']['profile_id'], manifest['sparse_profile']['profile_id']])
    stage['intent'].update(intent_id='intent-' + suffix, initial_authorization=None,
        expected_active_generation_id=expected_active,
        manifest_sha256=encode_manifest(manifest, stage['canonical_text']).sha256)
    return stage


class _AckConnection:
    """Use the actual driver, withholding one acknowledged COMMIT in this fixture."""
    def __init__(self, connection, observations):
        self.connection, self.observations = connection, observations

    def __getattr__(self, key):
        return getattr(self.connection, key)

    def transaction(self):
        connection = self.connection
        transaction, observations = connection.transaction(), self.observations
        class Transaction:
            async def __aenter__(self):
                await transaction.__aenter__()
                return self

            async def __aexit__(self, kind, error, traceback):
                result = await transaction.__aexit__(kind, error, traceback)
                if kind is None and observations['armed']:
                    observations['armed'] = False
                    observations['fired'] += 1
                    observations['retired_connection'] = connection
                    raise ConnectionError('injected_committed_ack_loss')
                return result
        return Transaction()


class _AckPool:
    def __init__(self, config, observations):
        from cragkit._postgres_pool import _owned_pool
        self.pool, self.observations = _owned_pool(config), observations

    async def open(self, **options):
        return await self.pool.open(**options)

    async def wait(self, **options):
        return await self.pool.wait(**options)

    async def close(self, **options):
        return await self.pool.close(**options)

    async def getconn(self, **options):
        return _AckConnection(await self.pool.getconn(**options), self.observations)

    async def putconn(self, connection):
        return await self.pool.putconn(connection.connection)


async def python_writer_cases(config, inputs):
    """Execute the native Python authority against a caller-owned private pool."""
    import asyncio
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit._qdrant_contract import QdrantConfig, parse_model
    from cragkit._qdrant_writer import PostgresQdrantWriter, prepare_stage
    from cragkit.contracts import TrustedScope, Limits
    from cragkit.execution import ExecutionLedger
    from cragkit.qdrant_publication import QdrantSecurityManager
    from cragkit.errors import IntegrityViolation, UnauthorizedScope, IndexNotReady, ProviderUnavailable

    private_config = dict(config)
    private_config['sslrootcert'] = Path(private_config['sslrootcert'])
    private_config['passfile'] = Path(private_config['passfile'])
    acknowledgment = dict(armed=False, fired=0)
    resource = PoolResource(PoolConfig.model_validate(private_config),
        factory=lambda cfg: _AckPool(cfg, acknowledgment))
    writer = PostgresQdrantWriter(resource, parse_model(QdrantConfig, inputs['config']), inputs['instance_id'])
    other_resource = PoolResource(PoolConfig.model_validate(private_config))
    other = PostgresQdrantWriter(other_resource, parse_model(QdrantConfig, inputs['config']), inputs['instance_id'])
    scope = parse_model(TrustedScope, inputs['scope'])
    context = dict(scope=scope, collection=inputs['stage']['manifest']['collection'],
        document_id=inputs['stage']['manifest']['document_id'],
        intent_id=inputs['stage']['intent']['intent_id'], owner_token=OWNER_TOKEN)
    deadline = asyncio.get_running_loop().time() + 60
    checks = []
    async def expect(error_type, operation):
        try:
            await operation()
        except error_type:
            return
        raise RuntimeError('writer_expected_failure_missing')
    primary = None
    security_manager = None
    try:
        await resource.open()
        await expect(IndexNotReady, lambda: writer.inspect(context, deadline=deadline))
        await writer.initialize(deadline=deadline)
        checks.append('explicit_initialization_exact_schema_and_dedicated_login')
        empty = await writer.manager_snapshot(context, deadline=deadline)
        if (empty['intent'] is not None or empty['document'] is not None or empty['owner'] is not None
                or empty['max_sequence'] != 0 or empty['pending']
                or empty['backend']['state'] != 'open' or empty['backend']['epoch'] != 1
                or empty['backend']['backend_namespace'] != inputs['config']['backend_namespace']):
            raise RuntimeError('manager_absent_snapshot')
        plan = prepare_stage(inputs['stage'])
        await writer.stage(plan, scope, owner_token=OWNER_TOKEN, deadline=deadline)
        first = await writer.inspect(context, deadline=deadline)
        if first is None or first['state'] != 'staged' or first['authority_committed']:
            raise RuntimeError('writer_stage_state')
        await writer.stage(plan, scope, owner_token=OWNER_TOKEN, deadline=deadline)
        if await writer.inspect(context, deadline=deadline) != first:
            raise RuntimeError('writer_stage_replay_changed')
        checks.append('immutable_creation_and_exact_idempotent_stage_replay')
        staged = await writer.manager_snapshot(context, deadline=deadline)
        if (staged['intent']['state'] != 'staged' or staged['document']['active_generation_id'] is not None
                or staged['document']['authorization_revision'] != 'auth-1'):
            raise RuntimeError('manager_staged_snapshot')
        checks.append('manager_snapshot_absent_and_staged_state')
        admission = await writer.admit_publication(context, deadline=deadline)
        if (admission['intent']['state'] != 'writing'
                or dict(admission['owner']) != dict(owner_token=OWNER_TOKEN, backend_epoch=1)):
            raise RuntimeError('manager_owner_admission')
        exact_owner = dict(instance_id=inputs['instance_id'], intent_id=context['intent_id'],
            owner_token=OWNER_TOKEN, backend_epoch=1)
        if dict((await writer.manager_snapshot(context, deadline=deadline))['owner']) != exact_owner:
            raise RuntimeError('manager_snapshot_owner_binding')
        checks.append('manager_admission_acquires_exact_private_owner')
        alternate = dict(context, owner_token='00000000-0000-4000-8000-000000000002')
        acknowledgment['armed'] = True
        admitted = await writer.admit_publication(alternate, deadline=deadline)
        if (acknowledgment['armed'] or acknowledgment['fired'] != 1
                or not acknowledgment['retired_connection'].closed
                or admitted['owner']['owner_token'] != alternate['owner_token']
                or (await writer.manager_snapshot(context, deadline=deadline))['owner']['owner_token'] != alternate['owner_token']):
            raise RuntimeError('manager_committed_admission_ack_loss')
        await writer.admit_publication(context, deadline=deadline)
        checks.append('manager_admission_commit_ack_loss_reconciles_same_owner')
        changed = deepcopy(inputs['stage'])
        changed['intent']['initial_authorization']['tag'] = 'changed'
        changed_plan = prepare_stage(changed)
        await expect(IntegrityViolation, lambda: writer.stage(changed_plan, scope, owner_token=OWNER_TOKEN, deadline=deadline))
        checks.append('stable_intent_changed_payload_rejected')
        foreign_scope = parse_model(TrustedScope, dict(inputs['scope'], tenant_id='foreign-tenant'))
        await expect(UnauthorizedScope, lambda: writer.stage(plan, foreign_scope, owner_token=OWNER_TOKEN, deadline=deadline))
        checks.append('stage_trusted_scope_cannot_be_rebound')
        await writer.acquire_owner(context, deadline=deadline)
        point_ids = [member['point_id'] for member in inputs['stage']['manifest']['members']]
        dispatch = dict(dispatch_id='native-dispatch-1', sequence=1, credential_generation='credential-1',
            operation='complete_point_upsert', point_ids=point_ids)
        reservation = await writer.reserve_dispatch(context, dispatch, deadline=deadline)
        # Native helper fields are inspected here, never emitted to a report.
        body = bytes(reservation['request_bytes'])
        if sha256(body).hexdigest() != reservation['request_sha256']:
            raise RuntimeError('writer_reserved_request_digest')
        payload = json.loads(body)
        if sorted(point['id'] for point in payload['points']) != sorted(point_ids):
            raise RuntimeError('writer_reserved_exact_point_set')
        if sorted(payload['points'], key=lambda point: point['id']) != sorted(inputs['expected_points'], key=lambda point: point['id']):
            raise RuntimeError('writer_reserved_complete_vectors_current_acl')
        checks.append('committed_reservation_constructs_exact_complete_points_and_current_acl')
        waiting = await writer.manager_snapshot(dict(context, intent_id='manager-other-intent'), deadline=deadline)
        status = await writer.dispatch_status(context, dispatch['dispatch_id'], deadline=deadline)
        if (not waiting['pending'] or waiting['intent'] is not None or status is None
                or status['state'] != 'reserved' or status['sequence'] != 1 or status['completion_sha256'] is not None
                or list(status['point_ids']) != sorted(point_ids) or status['request_sha256'] != reservation['request_sha256']
                or 'request_bytes' in status
                or await writer.dispatch_status(context, 'manager-missing-dispatch', deadline=deadline) is not None):
            raise RuntimeError('manager_pending_dispatch_snapshot')
        expected_status = dict(dispatch_id=dispatch['dispatch_id'], sequence=1, owner_token=OWNER_TOKEN,
            backend_epoch=1, credential_generation='credential-1', operation='complete_point_upsert',
            state='reserved', completion_sha256=None, request_sha256=reservation['request_sha256'],
            point_ids=tuple(sorted(point_ids)))
        if dict(status) != expected_status:
            raise RuntimeError('manager_closed_dispatch_status')
        checks.append('manager_snapshot_document_wide_uncertainty_and_exact_dispatch_metadata')
        reordered = await writer.reserve_dispatch(context, dict(dispatch, point_ids=list(reversed(point_ids))), deadline=deadline)
        if reordered['request_bytes'] != reservation['request_bytes'] or reordered['request_sha256'] != reservation['request_sha256']:
            raise RuntimeError('writer_same_claimed_set_replay_changed_request')
        checks.append('reservation_replay_uses_same_exact_claimed_set_independent_of_input_order')
        await expect(ProviderUnavailable, lambda: writer.reserve_dispatch(context,
            dict(dispatch, dispatch_id='blocked-dispatch', sequence=2), deadline=deadline))
        await expect(ProviderUnavailable, lambda: writer.prepare(context, sha256(b'blocked-preparation').hexdigest(), deadline=deadline))
        checks.append('reserved_work_blocks_new_dispatch_and_preparation_as_operational_failure')
        await writer.mark_dispatched(context, dispatch['dispatch_id'], deadline=deadline)
        # D tests transaction barriers only. This synthetic completion hash is
        # deliberately not reported as an actual Qdrant acknowledgment/readback.
        completion = sha256(b'D-native-synthetic-completion').hexdigest()
        await writer.settle_dispatch(context, dispatch['dispatch_id'], completion, deadline=deadline)
        settled = await writer.dispatch_status(context, dispatch['dispatch_id'], deadline=deadline)
        if dict(settled) != dict(expected_status, state='settled', completion_sha256=completion):
            raise RuntimeError('manager_settled_dispatch_snapshot')
        checks.append('manager_settled_dispatch_status_preserves_known_fixture_hash')
        await writer.prepare(context, completion, deadline=deadline)
        await writer.publish(context, deadline=deadline)
        published = await writer.inspect(context, deadline=deadline)
        if published is None or published['state'] != 'published' or not published['authority_committed'] or not published['replica_complete']:
            raise RuntimeError('writer_atomic_publication_state')
        await writer.publish(context, deadline=deadline)
        checks.append('atomic_authority_preparation_publication_and_replay')
        # Two actual LOGIN connections, with the administrative setup connection
        # already closed by the parent. The first intent pauses at preparation.
        await other_resource.open()
        await other.initialize(deadline=deadline)
        async def prepared(actor, stage, token):
            target = dict(context, intent_id=stage['intent']['intent_id'], owner_token=token)
            await actor.stage(prepare_stage(stage), scope, owner_token=token, deadline=deadline)
            await actor.acquire_owner(target, deadline=deadline)
            request = dict(dispatch_id='dispatch-' + stage['intent']['intent_id'], sequence=1,
                credential_generation='credential-1', operation='complete_point_upsert',
                point_ids=[member['point_id'] for member in stage['manifest']['members']])
            await actor.reserve_dispatch(target, request, deadline=deadline)
            await actor.mark_dispatched(target, request['dispatch_id'], deadline=deadline)
            await actor.settle_dispatch(target, request['dispatch_id'], completion, deadline=deadline)
            await actor.prepare(target, completion, deadline=deadline)
            return target
        contender_a = successor_stage(inputs, 'race-a', inputs['stage']['manifest']['generation_id'])
        contender_b = successor_stage(inputs, 'race-b', inputs['stage']['manifest']['generation_id'])
        # Stage both against the same original active pointer before either wins.
        await other.stage(prepare_stage(contender_b), scope, owner_token='00000000-0000-4000-8000-000000000002', deadline=deadline)
        a = await prepared(writer, contender_a, OWNER_TOKEN)
        b = await prepared(other, contender_b, '00000000-0000-4000-8000-000000000002')
        conflict_stage = inputs['successors']['manager-conflict']
        conflict_context = dict(context, intent_id=conflict_stage['intent']['intent_id'])
        await writer.stage(prepare_stage(conflict_stage), scope, owner_token=OWNER_TOKEN, deadline=deadline)
        await other.publish(b, deadline=deadline)
        before_conflict = await writer.manager_snapshot(conflict_context, deadline=deadline)
        conflict = await writer.admit_publication(conflict_context, deadline=deadline)
        after_conflict = await writer.manager_snapshot(conflict_context, deadline=deadline)
        if (conflict['intent']['state'] != 'conflict' or conflict['owner'] is not None
                or before_conflict['document'] != after_conflict['document']
                or before_conflict['owner'] != after_conflict['owner']):
            raise RuntimeError('manager_original_pointer_conflict')
        checks.append('manager_original_pointer_conflict_before_takeover')
        loser = await writer.publish(a, deadline=deadline)
        if loser['state'] != 'conflict' or loser['authority_committed']:
            raise RuntimeError('writer_competing_publication_must_persist_conflict')
        if (await other.inspect(b, deadline=deadline))['state'] != 'published':
            raise RuntimeError('writer_competing_publication_winner_changed')
        checks.append('two_login_publication_interleaving_preserves_winner_and_original_cas')
        historical = await writer.publish(context, deadline=deadline)
        if historical['state'] != 'published' or historical['generation_id'] != inputs['stage']['manifest']['generation_id']:
            raise RuntimeError('writer_historical_publication_replay_lost')
        checks.append('superseded_completed_publication_replays_historical_outcome')
        denied_stage = successor_stage(inputs, 'denied', contender_b['manifest']['generation_id'])
        denied_context = await prepared(writer, denied_stage, OWNER_TOKEN)
        manager_denied_stage = inputs['successors']['manager-denied']
        manager_denied_context = dict(context, intent_id=manager_denied_stage['intent']['intent_id'])
        await writer.stage(prepare_stage(manager_denied_stage), scope, owner_token=OWNER_TOKEN, deadline=deadline)
        revocation = dict(action='update_authorization', intent_id='native-revocation', tenant_id=scope.tenant_id,
            collection=context['collection'], document_id=context['document_id'],
            expected_authorization_revision='auth-1', expected_mutation_epoch=1,
            authorization=dict(authorization_revision='auth-2', principal_ids=[], grant_ids=[],
                language=None, kind=None, tag=None, tombstoned=False))
        await other.apply_security(revocation, scope, owner_token='00000000-0000-4000-8000-000000000002', deadline=deadline)
        denied = await writer.publish(denied_context, deadline=deadline)
        if denied['state'] != 'denied' or denied['authority_committed']:
            raise RuntimeError('writer_revoked_publication_must_persist_denied')
        checks.append('two_login_revocation_after_preparation_denies_publication')
        current_scope = parse_model(TrustedScope, dict(inputs['scope'], authorization_revision='auth-2'))
        await expect(UnauthorizedScope, lambda: writer.admit_publication(manager_denied_context, deadline=deadline))
        if (await writer.inspect(manager_denied_context, deadline=deadline))['state'] != 'staged':
            raise RuntimeError('manager_stale_scope_poisoned_intent')
        checks.append('manager_stale_caller_cannot_poison_valid_intent')
        fresh_denied = dict(manager_denied_context, scope=current_scope)
        before_denial = await writer.manager_snapshot(fresh_denied, deadline=deadline)
        admission_denied = await writer.admit_publication(fresh_denied, deadline=deadline)
        historical_context = dict(context, scope=current_scope)
        historical_admission = await writer.admit_publication(historical_context, deadline=deadline)
        after_denial = await writer.manager_snapshot(historical_context, deadline=deadline)
        if (admission_denied['intent']['state'] != 'denied' or admission_denied['owner'] is not None
                or historical_admission['intent']['state'] != 'published' or historical_admission['owner'] is not None
                or before_denial['document'] != after_denial['document']
                or before_denial['owner'] != after_denial['owner']):
            raise RuntimeError('manager_original_security_denial')
        checks.append('manager_original_security_denial_before_takeover_and_historical_metadata')
        stale = dict(revocation, intent_id='native-stale-security')
        stale_receipt = await writer.apply_security(stale, scope, owner_token=OWNER_TOKEN, deadline=deadline)
        if stale_receipt['state'] != 'denied' or stale_receipt['authority_committed']:
            raise RuntimeError('writer_stale_security_not_durably_denied')
        replay = await writer.apply_security(stale, current_scope, owner_token=OWNER_TOKEN, deadline=deadline)
        if replay != stale_receipt:
            raise RuntimeError('writer_stale_security_replay_changed')
        checks.append('stale_security_intent_denied_without_overwriting_current_authority')
        security = dict(action='tombstone', intent_id='native-tombstone', tenant_id=scope.tenant_id,
            collection=inputs['stage']['manifest']['collection'], document_id=context['document_id'],
            expected_authorization_revision='auth-2', expected_mutation_epoch=2,
            authorization=dict(authorization_revision='auth-3', principal_ids=[], grant_ids=[],
                language=None, kind=None, tag=None, tombstoned=True))
        acknowledgment['armed'] = True
        tombstone = await writer.apply_security(security, current_scope, owner_token=OWNER_TOKEN, deadline=deadline)
        if (acknowledgment['armed'] or acknowledgment['fired'] != 2
                or not acknowledgment['retired_connection'].closed or not tombstone['authority_committed']
                or tombstone['replica_complete'] or tombstone['purge_complete']):
            raise RuntimeError('security_commit_ack_confirmation_failed')
        checks.append('security_commit_ack_loss_confirms_without_mutation_replay')
        await writer.apply_security(security, current_scope, owner_token=OWNER_TOKEN, deadline=deadline)
        checks.append('immediate_monotonic_tombstone_with_stable_security_intent')
        historical_security = await writer.apply_security(revocation, scope, owner_token=OWNER_TOKEN, deadline=deadline)
        if not historical_security['authority_committed'] or historical_security['payload_sha256'] == tombstone['payload_sha256']:
            raise RuntimeError('superseded_security_history_lost')
        checks.append('superseded_security_retry_preserves_current_tombstone')
        purge_scope = parse_model(TrustedScope, dict(inputs['scope'], authorization_revision='auth-3'))
        purge = dict(intent_id='native-purge', tenant_id=scope.tenant_id, collection=context['collection'],
            document_id=context['document_id'], tombstone_intent_payload_sha256=tombstone['payload_sha256'],
            expected_authorization_revision='auth-3', expected_mutation_epoch=3)
        purge_receipt = await writer.bind_purge(purge, purge_scope, owner_token=OWNER_TOKEN, deadline=deadline)
        if purge_receipt['state'] != 'authority_committed' or not purge_receipt['authority_committed'] or purge_receipt['purge_complete'] or purge_receipt['replica_complete']:
            raise RuntimeError('writer_purge_binding_misreports_replica_completion')
        if await writer.bind_purge(purge, purge_scope, owner_token=OWNER_TOKEN, deadline=deadline) != purge_receipt:
            raise RuntimeError('writer_purge_binding_replay_changed')
        checks.append('tombstone_bound_purge_admission_is_idempotent_and_replica_pending')
        purge_context = dict(context,scope=purge_scope,intent_id=purge['intent_id'])
        await writer.acquire_owner(purge_context,deadline=deadline)
        await writer.reserve_dispatch(purge_context,dict(dispatch_id='native-public-pending-purge',sequence=1,
            credential_generation='native-unconfirmed-delete',operation='delete_points',
            point_ids=[inputs['stage']['manifest']['members'][0]['point_id']]),deadline=deadline)
        before_security = await writer.manager_snapshot(purge_context,deadline=deadline)
        if not before_security['pending']:
            raise RuntimeError('security_public_missing_uncertainty')
        await other.close()
        await other_resource.close()
        supervisor_config = dict(inputs['supervisor_config'])
        for key in ('sslrootcert','passfile'):
            supervisor_config[key] = Path(supervisor_config[key])
        supervisor_resource = PoolResource(PoolConfig.model_validate(supervisor_config))
        try:
            await supervisor_resource.open()
            async with supervisor_resource.lease(deadline=deadline) as connection:
                async with connection.transaction():
                    await connection.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                    await connection.execute("SELECT set_config('cragkit_qdrant.backend_instance_id',%s,true)",(inputs['instance_id'],))
                    await connection.execute("UPDATE cragkit_qdrant.backend_instances SET epoch=epoch+1,state='recovery_blocked',recovery_id=%s WHERE instance_id=%s",
                        ('native-public-security-gate',inputs['instance_id']))
        finally:
            await supervisor_resource.close()
        authorizations = []
        async def authorize_security(selected, collection, document):
            if selected.tenant_id != scope.tenant_id or (collection,document) != (context['collection'],context['document_id']):
                raise RuntimeError('security_public_callback_target')
            authorizations.append(selected.authorization_revision)
            return True
        security_manager = QdrantSecurityManager(writer,authorize_security)
        await security_manager.initialize(deadline=deadline)
        public_change = dict(security,intent_id='native-public-update',action='update_authorization',
            expected_authorization_revision='auth-3',expected_mutation_epoch=3,
            authorization=dict(security['authorization'],authorization_revision='auth-4',language='de'))
        def security_book():
            return ExecutionLedger(Limits(deadline_ms=60000,max_attempts=1,max_provider_calls=0),deadline=deadline)
        acknowledgment['armed'] = True
        book = security_book()
        public_result = await security_manager.update_authorization(public_change,purge_scope,book,deadline=deadline)
        if (set(public_result) != {'intent_id','operation','state','revision_id','generation_id','authority_committed',
                'replica_complete','published','purge_complete'} or public_result['operation']!='update_authorization'
                or not public_result['authority_committed'] or public_result['replica_complete'] or public_result['published']
                or public_result['purge_complete'] or acknowledgment['fired']!=3 or acknowledgment['armed']):
            raise RuntimeError('security_public_admission_flags')
        if (book.snapshot()['attempts'],book.snapshot()['provider_calls'],book.snapshot()['pending'])!=(1,0,0):
            raise RuntimeError('security_public_admission_usage')
        public_tombstone = dict(public_change,action='tombstone',intent_id='native-public-tombstone',
            expected_authorization_revision='auth-4',expected_mutation_epoch=4,
            authorization=dict(public_change['authorization'],authorization_revision='auth-5'))
        public_scope = parse_model(TrustedScope,dict(inputs['scope'],authorization_revision='auth-4'))
        result = await security_manager.tombstone(public_tombstone,public_scope,security_book(),deadline=deadline)
        if not result['authority_committed'] or result['replica_complete'] or result['operation']!='tombstone':
            raise RuntimeError('security_public_tombstone_flags')
        checks.append('public_security_admission_callbacks_usage_and_lost_commit')
        await security_manager.close()
        if not (await writer.inspect(dict(context,intent_id=public_tombstone['intent_id']),deadline=deadline))['authority_committed']:
            raise RuntimeError('security_public_closed_borrowed_writer')
        if authorizations!=['auth-3','auth-4']:
            raise RuntimeError('security_public_callback_scope')
        checks.append('public_security_close_preserves_borrowed_writer')
        latest_scope = parse_model(TrustedScope,dict(inputs['scope'],authorization_revision='auth-5'))
        after_security = await writer.manager_snapshot(dict(purge_context,scope=latest_scope),deadline=deadline)
        if (not after_security['pending'] or after_security['owner']!=before_security['owner']
                or after_security['backend']['state']!='recovery_blocked'):
            raise RuntimeError('security_public_changed_recovery_ownership')
        checks.append('public_security_commits_with_blocked_backend_and_uncertain_purge')
        return dict(runtime='python', checks=checks, publication_proof='authority_transactions_only')
    except BaseException as error:
        primary = error
        raise
    finally:
        failures = []
        for owned in ((security_manager,) if security_manager is not None else ())+(writer, other, resource, other_resource):
            try:
                await owned.close()
            except BaseException as error:
                failures.append(('runtime_close', error))
        if failures:
            raise CleanupFailure(failures, primary=primary, stage='runtime_login') from None
