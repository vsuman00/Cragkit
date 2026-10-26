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


async def python_writer_cases(config, inputs):
    """Execute the native Python authority against a caller-owned private pool."""
    import asyncio
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit._qdrant_contract import QdrantConfig, parse_model
    from cragkit._qdrant_writer import PostgresQdrantWriter, prepare_stage
    from cragkit.contracts import TrustedScope
    from cragkit.errors import IntegrityViolation, UnauthorizedScope, IndexNotReady, ProviderUnavailable

    private_config = dict(config)
    private_config['sslrootcert'] = Path(private_config['sslrootcert'])
    private_config['passfile'] = Path(private_config['passfile'])
    resource = PoolResource(PoolConfig.model_validate(private_config))
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
    try:
        await resource.open()
        await expect(IndexNotReady, lambda: writer.inspect(context, deadline=deadline))
        await writer.initialize(deadline=deadline)
        checks.append('explicit_initialization_exact_schema_and_dedicated_login')
        plan = prepare_stage(inputs['stage'])
        await writer.stage(plan, scope, owner_token=OWNER_TOKEN, deadline=deadline)
        first = await writer.inspect(context, deadline=deadline)
        if first is None or first['state'] != 'staged' or first['authority_committed']:
            raise RuntimeError('writer_stage_state')
        await writer.stage(plan, scope, owner_token=OWNER_TOKEN, deadline=deadline)
        if await writer.inspect(context, deadline=deadline) != first:
            raise RuntimeError('writer_stage_replay_changed')
        checks.append('immutable_creation_and_exact_idempotent_stage_replay')
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
        await other.publish(b, deadline=deadline)
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
        tombstone = await writer.apply_security(security, current_scope, owner_token=OWNER_TOKEN, deadline=deadline)
        await writer.apply_security(security, current_scope, owner_token=OWNER_TOKEN, deadline=deadline)
        checks.append('immediate_monotonic_tombstone_with_stable_security_intent')
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
        return dict(runtime='python', checks=checks, publication_proof='authority_transactions_only')
    except BaseException as error:
        primary = error
        raise
    finally:
        failures = []
        for owned in (writer, other, resource, other_resource):
            try:
                await owned.close()
            except BaseException as error:
                failures.append(('runtime_close', error))
        if failures:
            raise CleanupFailure(failures, primary=primary, stage='runtime_login') from None
