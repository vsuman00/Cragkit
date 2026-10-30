"""Actual public-manager cases on disposable native servers; no model calls."""
from __future__ import annotations

from copy import deepcopy

from qdrant_supervisor_cases import supervisor_input
from qdrant_writer_cases import writer_input, successor_stage

CHECKS = (
    'native_manager_initialized_explicit_borrowed_dependencies',
    'stage_commits_authority_without_qdrant_mutation_and_honors_ledger',
    'publish_uses_actual_completed_ack_full_readback_and_cas',
    'matching_terminal_stage_and_publish_are_historical_no_mutation',
    'changed_stage_payload_fails_without_new_writes',
    'authorizer_denial_malformed_failure_are_closed_no_writes',
    'competing_original_pointer_preserves_winner_and_persists_conflict',
    'prepared_quiescent_cancel_is_unpublished_and_resumes_without_upsert',
    'actual_preparation_commit_ack_loss_reconciles_without_http_resend',
    'finalization_session_excludes_raw_lifecycle_and_recovery',
    'late_revocation_blocks_publication_and_preserves_active',
    'fresh_scope_terminal_replay_never_restores_initial_acl',
    'actual_lost_write_ack_stays_unknown_and_retry_does_not_resend',
    'manager_close_preserves_borrowed_dependencies',
    'actual_atomic_stage_rollback_preserves_pointer_and_no_rows',
    'actual_stage_commit_ack_loss_resumes_exact_graph_without_http',
    'actual_publication_cas_commit_ack_loss_resolves_exactly_once',
    'bootstrap_acl_changed_rejected_without_sql_http_mutation',
    'partial_member_stage_rejected_before_http_preserves_pointer',
    'budget_before_dispatch_preserves_journal_stage_pointer_and_http',
)
ERRORS = frozenset(('IntegrityViolation', 'UnauthorizedScope', 'UnsupportedCapability',
    'InvalidRequest', 'ProviderUnavailable', 'DeadlineExceeded', 'IndexNotReady',
    'BudgetExhausted', 'CancelledError', 'AbortError', 'internal'))


class NativePublicationManagerFailure(RuntimeError):
    def __init__(self, observation):
        super().__init__('publication_manager_native_case_failed')
        self.observation = observation


def publication_manager_input():
    inputs = writer_input()
    inputs['collection_config'] = supervisor_input()['collection_config']
    stages = {}
    base = inputs['stage']['manifest']['generation_id']
    stages['stage_rollback'] = successor_stage(inputs, 'manager-stage-rollback', base)
    stages['stage_ack_loss'] = successor_stage(inputs, 'manager-stage-ack-loss', base)
    stages['loser'] = successor_stage(inputs, 'manager-loser', base)
    stages['winner'] = successor_stage(inputs, 'manager-winner', base)
    stages['denied_input'] = successor_stage(inputs, 'manager-denied-input', base)
    stages['wrong_dense'] = successor_stage(inputs, 'manager-wrong-dense', base)
    stages['wrong_sparse'] = successor_stage(inputs, 'manager-wrong-sparse', base)
    stages['wrong_profile'] = successor_stage(inputs, 'manager-wrong-profile', base)
    stages['missing_sparse'] = successor_stage(inputs, 'manager-missing-sparse', base)
    stages['equal_set'] = successor_stage(inputs, 'manager-equal-set', base)
    stages['equal_extra'] = successor_stage(inputs, 'manager-equal-extra', base)
    for key in ('mixed_revision_member', 'malformed_utf8_span', 'unsupported_sparse_encoder'):
        stages[key] = successor_stage(inputs, 'manager-' + key.replace('_', '-'), base)
    previous = stages['winner']['manifest']['generation_id']
    for key, suffix in (('prepared', 'manager-prepared'), ('commit', 'manager-commit'),
            ('session', 'manager-final-session'), ('revoked', 'manager-revoked')):
        stages[key] = successor_stage(inputs, suffix, previous)
        previous = stages[key]['manifest']['generation_id']
    # The revoked generation never publishes: the session generation stays active.
    stages['lost_ack'] = successor_stage(inputs, 'manager-lost-ack',
        stages['session']['manifest']['generation_id'])
    stages['lost_ack']['intent'].update(expected_authorization_revision='auth-manager-2',
        expected_mutation_epoch=2)
    inputs['stages'] = deepcopy(stages)
    return inputs


class _PreparationAckConnection:
    def __init__(self, connection, observations):
        self.connection, self.observations = connection, observations
        self.preparing = self.publishing = False

    def __getattr__(self, key):
        return getattr(self.connection, key)

    async def execute(self, statement, params=()):
        publication = self.observations['publication']
        if (publication['track'] and type(statement) is str
                and statement.startswith(('INSERT INTO cragkit_qdrant.',
                    'UPDATE cragkit_qdrant.', 'DELETE FROM cragkit_qdrant.'))):
            publication['dml'] += 1
        if (publication['armed'] and type(statement) is str
                and statement.startswith('UPDATE cragkit_qdrant.documents SET active_generation_id=')):
            self.publishing = True
            publication['cas_writes'] += 1
        stage = self.observations.get('stage')
        if (stage is not None and type(statement) is str
                and statement.startswith(('INSERT INTO cragkit_qdrant.',
                    'UPDATE cragkit_qdrant.', 'DELETE FROM cragkit_qdrant.'))):
            stage['dml'] += 1
        target = (stage is not None and type(statement) is str
            and statement.startswith('INSERT INTO cragkit_qdrant.publication_intents ')
            and stage['intent_id'] in params)
        if target:
            self.staging = True
            stage['inserts'] += 1
        result = await self.connection.execute(statement, params)
        if target and stage['action'] == 'rollback':
            from cragkit.errors import ProviderUnavailable
            stage['fired'] += 1
            stage['action'] = None
            raise ProviderUnavailable()
        if (self.observations['armed'] and type(statement) is str
                and statement.startswith('INSERT INTO cragkit_qdrant.preparations ')):
            self.preparing = True
        return result

    def transaction(self):
        owner, transaction = self, self.connection.transaction()
        class Transaction:
            async def __aenter__(self):
                owner.preparing = owner.publishing = False
                owner.staging = False
                await transaction.__aenter__()
                return self

            async def __aexit__(self, kind, error, traceback):
                result = await transaction.__aexit__(kind, error, traceback)
                stage = owner.observations.get('stage')
                if kind is None and owner.staging and stage['action'] == 'ack_loss':
                    stage.update(action=None, fired=stage['fired'] + 1,
                        retired_connection=owner.connection)
                    await owner.connection.close()
                    raise ConnectionError('injected_stage_commit_ack_loss')
                publication = owner.observations['publication']
                if kind is None and owner.publishing and publication['armed']:
                    publication.update(armed=False, fired=publication['fired']+1,
                        retired_connection=owner.connection)
                    await owner.connection.close()
                    raise ConnectionError('injected_publication_commit_ack_loss')
                if kind is None and owner.preparing and owner.observations['armed']:
                    owner.observations.update(armed=False, fired=owner.observations['fired'] + 1,
                        retired_connection=owner.connection)
                    raise ConnectionError('injected_preparation_commit_ack_loss')
                return result
        return Transaction()


class _PreparationAckPool:
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
        return _PreparationAckConnection(await self.pool.getconn(**options), self.observations)

    async def putconn(self, connection):
        return await self.pool.putconn(connection.connection)


async def python_publication_manager_cases(value):
    import asyncio
    import json
    from hashlib import sha256
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit._qdrant_writer import _SCOPE_SQL
    from cragkit.contracts import Limits, TrustedScope
    from cragkit.execution import ExecutionLedger, BudgetExhausted
    from cragkit.errors import (IntegrityViolation, InvalidRequest, ProviderUnavailable,
        UnauthorizedScope, UnsupportedCapability)
    from cragkit.qdrant_publication import (QdrantPublicationManager,
        PostgresQdrantPublicationAuthority, ManagedQdrantPublicationTransport,
        PostgresQdrantWriter, PostgresQdrantRecovery, ManagedQdrantSupervisor,
        QdrantReconciliationVerifier)
    from qdrant_supervisor_cases import plain, request_bytes, observed_listener
    from runtime_diagnostics import CleanupFailure

    inputs = value['inputs']
    scenario = value.get('scenario', 'default')
    if scenario not in ('default', 'wrong_dense', 'wrong_sparse', 'wrong_profile', 'missing_sparse', 'equal_set', 'invalid_input'):
        raise RuntimeError('manager_fixture_scenario')
    def pool_config(raw):
        raw = dict(raw)
        for key in ('sslrootcert', 'passfile'):
            raw[key] = Path(raw[key])
        return PoolConfig.model_validate(raw)
    writer_config, supervisor_config = pool_config(value['writer_config']), pool_config(value['supervisor_config'])
    if writer_config.max_size != 1 or supervisor_config.max_size != 1:
        raise RuntimeError('manager_fixture_two_client_ceiling')
    acknowledgment = dict(armed=False, fired=0,
        publication=dict(armed=False,track=False,fired=0,cas_writes=0,dml=0))
    resource = PoolResource(writer_config, factory=lambda cfg: _PreparationAckPool(cfg, acknowledgment))
    supervisor_resource = PoolResource(supervisor_config)
    supervisor = ManagedQdrantSupervisor(Path(value['binary']), Path(value['work_dir']),
        inputs['instance_id'], inputs['config'])
    writer = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
    verifier = QdrantReconciliationVerifier(writer, supervisor)
    recovery = PostgresQdrantRecovery(supervisor_resource, inputs['config'], supervisor, verifier)
    authority = PostgresQdrantPublicationAuthority(writer, recovery)
    transport = ManagedQdrantPublicationTransport(supervisor)
    scope = TrustedScope.model_validate(inputs['scope'])
    fresh_scope = TrustedScope.model_validate(dict(inputs['scope'], authorization_revision='auth-manager-2'))
    deadline = asyncio.get_running_loop().time() + 105
    lookup_token = '00000000-0000-4000-8000-000000000099'
    collection, document_id = inputs['stage']['manifest']['collection'], inputs['stage']['manifest']['document_id']
    target = '/collections/' + inputs['config']['physical_collection']
    managers, handles, checks, snapshots = [], [], [], []
    mode = dict(action=None, intent_id=None, fired=False)
    network = dict(mutations=0, requests=0, drop=False, completed_drop=False)
    dense_fault = dict(armed=False, fired=0, point=None, points=None, originals=None,
        fixture_puts=0, repairing=False, repair_bodies=[], repair_completed=0)
    set_fault = dict(armed=False, watching=False, stage=None, extra=False, fired=0,
        puts=0, deletes=0, reads=[], points=None, originals=None, unexpected=None)
    endpoint = primary = manager = None
    supervisor_leases = 0
    original_supervisor_lease = supervisor_resource.lease
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def counted_supervisor_lease(**options):
        nonlocal supervisor_leases
        supervisor_leases += 1
        async with original_supervisor_lease(**options) as lease:
            yield lease
    supervisor_resource.lease = counted_supervisor_lease

    def reference(stage):
        return dict(collection=collection, document_id=document_id, intent_id=stage['intent']['intent_id'])
    def context(stage, selected_scope=scope):
        return dict(scope=selected_scope, **reference(stage), owner_token=lookup_token)
    def ledger():
        return ExecutionLedger(Limits(deadline_ms=60000, max_attempts=1, max_provider_calls=0), deadline=deadline)
    def save(result):
        result = plain(result)
        names = ('intent_id', 'operation', 'state', 'revision_id', 'generation_id',
            'authority_committed', 'replica_complete', 'published', 'purge_complete')
        if type(result) is not dict or set(result) != set(names):
            raise RuntimeError('manager_public_result_fields')
        if any(type(result[key]) is not bool for key in names[5:]):
            raise RuntimeError('manager_public_result_flags')
        snapshots.append([result[key] if index < 5 else str(result[key]).lower()
            for index, key in enumerate(names)])
        return result
    async def expect(kind, operation):
        try:
            await operation()
        except kind:
            return
        raise RuntimeError('manager_expected_failure_missing')
    def completed(raw):
        result = json.loads(bytes(raw))
        if result.get('status') != 'ok' or result.get('result', {}).get('status') != 'completed':
            raise RuntimeError('manager_fixture_ack_not_completed')
    async def provision(admin, probe):
        await admin.request('PUT', target, body=request_bytes(inputs['collection_config']), deadline=deadline)
        probe = plain(probe)
        path = '/collections/' + probe['collection']
        await admin.request('PUT', path, body=request_bytes(probe['collection_config']), deadline=deadline)
        completed(await admin.request('PUT', path + '/points?wait=true&ordering=strong',
            body=request_bytes({'points': [probe['point']]}), deadline=deadline))

    class ObservedHandle:
        def __init__(self, handle):
            self.handle = handle
        async def request(self, method, path, **options):
            network['requests'] += 1
            mutation = method == 'PUT' and '/points?' in path
            if mutation:
                network['mutations'] += 1
            if mutation and dense_fault['repairing']:
                body = json.loads(bytes(options['body']))
                points = body.get('points', [])
                expected_points = {point['id']: point for point in dense_fault['originals']}
                if (sorted(point['id'] for point in points) != sorted(expected_points)
                        or any(set(point['vector']) != {'dense', 'sparse'}
                            or point != expected_points[point['id']] for point in points)):
                    raise RuntimeError('manager_missing_sparse_repair_body_incomplete')
                dense_fault['repair_bodies'].append(deepcopy(points))
            raw = await self.handle.request(method, path, **options)
            if (set_fault['watching'] and method == 'POST'
                    and path in (target + '/points', target + '/points/scroll')):
                set_fault['reads'].append(dict(path=path, body=json.loads(bytes(options['body'])),
                    allowance=options.get('max_response_bytes'), response=json.loads(bytes(raw))))
            if mutation and set_fault['armed'] and path == target + '/points?wait=true&ordering=strong':
                body = json.loads(bytes(options['body']))
                ids = sorted(member['point_id'] for member in set_fault['stage']['manifest']['members'])
                if sorted(point['id'] for point in body.get('points', [])) == ids:
                    completed(raw)
                    selected = [point for point in body['points']
                        if point['vector']['dense'] == [1.0] + [0.0] * (len(point['vector']['dense']) - 1)]
                    if len(selected) != 1:
                        raise RuntimeError('manager_equal_set_fixture_basis')
                    copied = deepcopy(selected[0])
                    copied['id'] = ('00000000-0000-4000-8000-000000000098' if set_fault['extra']
                        else '00000000-0000-4000-8000-000000000099')
                    set_fault['armed'] = False
                    if not set_fault['extra']:
                        completed(await self.handle.request('POST', target + '/points/delete?wait=true&ordering=strong',
                            body=request_bytes(dict(points=[selected[0]['id']])), deadline=deadline))
                        set_fault['deletes'] += 1
                    completed(await self.handle.request('PUT', path,
                        body=request_bytes(dict(points=[copied])), deadline=deadline))
                    set_fault['puts'] += 1
                    set_fault['fired'] += 1
                    set_fault['originals'] = deepcopy(body['points'])
                    set_fault['points'] = [deepcopy(point) for point in body['points']
                        if set_fault['extra'] or point['id'] != selected[0]['id']] + [copied]
                    set_fault['unexpected'] = copied['id']
            if mutation and dense_fault['repairing']:
                completed(raw)
                dense_fault['repair_completed'] += 1
            if (mutation and dense_fault['armed']
                    and path == target + '/points?wait=true&ordering=strong'):
                body = json.loads(bytes(options['body']))
                members = inputs['stages'][scenario]['manifest']['members']
                if (sorted(point['id'] for point in body.get('points', []))
                        == sorted(member['point_id'] for member in members)):
                    completed(raw)
                    matching = [point for point in body['points']
                        if point['vector']['dense'] == [1.0] + [0.0] * (len(point['vector']['dense']) - 1)]
                    if len(matching) != 1:
                        raise RuntimeError('manager_wrong_dense_fixture_basis')
                    point = deepcopy(matching[0])
                    dense = point['vector']['dense']
                    if len(dense) < 2 or dense != [1.0] + [0.0] * (len(dense) - 1):
                        raise RuntimeError('manager_wrong_dense_fixture_basis')
                    if scenario == 'wrong_dense':
                        point['vector']['dense'] = [0.0, 1.0] + [0.0] * (len(dense) - 2)
                    elif scenario == 'wrong_sparse':
                        sparse = point['vector']['sparse']
                        if not sparse['values'] or len(sparse['indices']) != len(sparse['values']):
                            raise RuntimeError('manager_wrong_sparse_fixture_basis')
                        sparse['values'][0] += 0.25
                    elif scenario == 'wrong_profile':
                        if point['payload']['dense_profile']['model'] == 'wrong-profile':
                            raise RuntimeError('manager_wrong_profile_fixture_basis')
                        point['payload']['dense_profile']['model'] = 'wrong-profile'
                    elif scenario == 'missing_sparse':
                        del point['vector']['sparse']
                    expected_points = deepcopy(body['points'])
                    expected_points = [point if original['id'] == point['id'] else original
                        for original in expected_points]
                    dense_fault['armed'] = False
                    completed(await self.handle.request('PUT', path,
                        body=request_bytes({'points': [point]}), deadline=deadline))
                    dense_fault.update(fired=dense_fault['fired'] + 1, point=point,
                        points=expected_points, originals=deepcopy(body['points']),
                        fixture_puts=dense_fault['fixture_puts'] + 1)
            if mutation and network['drop']:
                completed(raw)
                network.update(drop=False, completed_drop=True)
                raise ProviderUnavailable()
            return raw
        async def close(self):
            await self.handle.close()

    async def authorize(selected_scope, selected_collection, selected_document):
        if (selected_collection, selected_document) != (collection, document_id):
            raise RuntimeError('manager_authorizer_target_changed')
        if mode['action'] is None or mode['fired']:
            return True
        lookup = dict(scope=selected_scope, collection=collection, document_id=document_id,
            intent_id=mode['intent_id'], owner_token=lookup_token)
        intent = await writer.inspect(lookup, deadline=deadline)
        if intent is None or intent['state'] != 'prepared':
            return True
        mode['fired'] = True
        if mode['action'] == 'cancel':
            mode['task'].cancel()
            await asyncio.sleep(0)
        elif mode['action'] == 'session':
            before = supervisor_leases
            await expect(ProviderUnavailable, lambda: supervisor.recover(dict(
                recovery_id='forbidden-manager-final', old_epoch=1, new_epoch=2), deadline=deadline))
            await expect(ProviderUnavailable, lambda: recovery.initialize(deadline=deadline))
            if before != supervisor_leases:
                raise RuntimeError('manager_finalization_competing_sql_started')
        elif mode['action'] == 'revoke':
            change = dict(action='update_authorization', intent_id='manager-security-change',
                tenant_id=scope.tenant_id, collection=collection, document_id=document_id,
                expected_authorization_revision='auth-1', expected_mutation_epoch=1,
                authorization=dict(authorization_revision='auth-manager-2', principal_ids=[], grant_ids=[],
                    language=None, kind=None, tag=None, tombstoned=False))
            await writer.apply_security(change, selected_scope, owner_token=lookup_token, deadline=deadline)
        return True

    async def new_manager(callback=authorize):
        instance = QdrantPublicationManager(authority, transport, inputs['config'], supervisor, callback)
        managers.append(instance)
        await instance.initialize(deadline=deadline)
        return instance
    async def stage_call(instance, stage, selected_scope=scope, selected_ledger=None):
        return await instance.stage(stage, selected_scope, selected_ledger or ledger(), deadline=deadline)
    async def publish_call(instance, stage, selected_scope=scope, selected_ledger=None):
        return await instance.publish(reference(stage), selected_scope, selected_ledger or ledger(), deadline=deadline)
    async def current(stage, selected_scope=scope):
        return await writer.manager_snapshot(context(stage, selected_scope), deadline=deadline)
    async def journal_states():
        async with supervisor_resource.lease(deadline=deadline) as connection:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                await connection.execute("SELECT set_config('cragkit_qdrant.backend_instance_id',%s,true)",
                    (inputs['instance_id'],))
                cursor = await connection.execute('SELECT state FROM cragkit_qdrant.dispatch_journal '
                    'WHERE instance_id=%s ORDER BY dispatch_id', (inputs['instance_id'],))
                return [row[0] for row in await cursor.fetchall()]
    async def document_acl(selected_scope):
        async with resource.lease(deadline=deadline) as connection:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                await connection.execute(_SCOPE_SQL, (selected_scope.tenant_id, collection,
                    selected_scope.principal_id, json.dumps(list(selected_scope.grant_ids)),
                    selected_scope.authorization_revision, document_id, 'manager-fixture-read',
                    lookup_token, inputs['instance_id']))
                cursor = await connection.execute('SELECT principal_ids,grant_ids,authorization_revision,'
                    'mutation_epoch,active_generation_id FROM cragkit_qdrant.documents '
                    'WHERE tenant_id=%s AND collection=%s AND document_id=%s',
                    (selected_scope.tenant_id, collection, document_id))
                return await cursor.fetchall()

    async def stage_graph(stage):
        from qdrant_publication_native import PublicationDatabase
        connection = await PublicationDatabase._connect(value['observer_config'])
        try:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION READ ONLY')
                await connection.execute("SET LOCAL statement_timeout='5000ms'")
                manifest = stage['manifest']
                prefix = (scope.tenant_id, collection, document_id)
                graph = {}
                for table, suffix, params in (
                    ('publication_intents', 'intent_id=%s', (stage['intent']['intent_id'],)),
                    ('document_revisions', 'revision_id=%s', (manifest['revision_id'],)),
                    ('generations', 'generation_id=%s', (manifest['generation_id'],)),
                    ('members', 'generation_id=%s', (manifest['generation_id'],)),
                    ('point_claims', 'generation_id=%s', (manifest['generation_id'],)),
                    ('vector_replays', 'generation_id=%s', (manifest['generation_id'],)),
                    ('document_owners', 'intent_id=%s', (stage['intent']['intent_id'],))):
                    cursor = await connection.execute('SELECT to_jsonb(t)::text FROM cragkit_qdrant.'
                        + table + ' t WHERE tenant_id=%s AND collection=%s AND document_id=%s AND '
                        + suffix + ' ORDER BY to_jsonb(t)::text', (*prefix, *params))
                    graph[table] = await cursor.fetchall()
                cursor = await connection.execute('SELECT active_generation_id FROM cragkit_qdrant.documents '
                    'WHERE tenant_id=%s AND collection=%s AND document_id=%s', prefix)
                graph['pointer'] = await cursor.fetchall()
                if scenario != 'default':
                    cursor = await connection.execute('SELECT to_jsonb(t)::text FROM '
                        'cragkit_qdrant.preparations t WHERE tenant_id=%s AND collection=%s '
                        'AND document_id=%s AND intent_id=%s ORDER BY to_jsonb(t)::text',
                        (*prefix, stage['intent']['intent_id']))
                    graph['preparations'] = await cursor.fetchall()
                    cursor = await connection.execute('SELECT state,completion_sha256 FROM '
                        'cragkit_qdrant.dispatch_journal WHERE tenant_id=%s AND collection=%s '
                        'AND document_id=%s AND intent_id=%s ORDER BY sequence',
                        (*prefix, stage['intent']['intent_id']))
                    graph['dispatches'] = await cursor.fetchall()
                return graph
        finally:
            await asyncio.wait_for(connection.close(), 3)

    async def corrupt_one_member(stage):
        from qdrant_publication_native import PublicationDatabase
        connection = await PublicationDatabase._connect(value['observer_config'])
        try:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                await connection.execute("SET LOCAL statement_timeout='5000ms'")
                manifest = stage['manifest']
                chunk_id = manifest['members'][0]['chunk_id']
                cursor = await connection.execute('DELETE FROM cragkit_qdrant.members '
                    'WHERE tenant_id=%s AND collection=%s AND document_id=%s '
                    'AND generation_id=%s AND chunk_id=%s RETURNING chunk_id',
                    (scope.tenant_id, collection, document_id, manifest['generation_id'], chunk_id))
                if await cursor.fetchall() != [(chunk_id,)]:
                    raise RuntimeError('manager_partial_member_corruption_target')
        finally:
            await asyncio.wait_for(connection.close(), 3)

    try:
        await supervisor.initialize(deadline=deadline, provision=provision)
        endpoint = supervisor.identity()['endpoint']
        await observed_listener(endpoint)
        original_transport_for = supervisor.transport_for
        def observed_transport(capability):
            handle = ObservedHandle(original_transport_for(capability))
            handles.append(handle)
            return handle
        supervisor.transport_for = observed_transport
        await resource.open()
        await supervisor_resource.open()
        manager = await new_manager()
        if scenario == 'invalid_input':
            base = inputs['stage']
            save(await stage_call(manager, base))
            published = save(await publish_call(manager, base))
            if not published['published'] or network['mutations'] != 1:
                raise RuntimeError('manager_invalid_input_base_unpublished')
            base_graph = await stage_graph(base)
            issued = 0
            original_issue_attempt = supervisor.issue_attempt
            def counted_issue_attempt(binding, **options):
                nonlocal issued
                issued += 1
                return original_issue_attempt(binding, **options)
            supervisor.issue_attempt = counted_issue_attempt
            for key, kind in (('mixed_revision_member', IntegrityViolation),
                    ('malformed_utf8_span', IntegrityViolation),
                    ('unsupported_sparse_encoder', UnsupportedCapability)):
                valid = inputs['stages'][key]
                invalid = deepcopy(valid)
                if key == 'mixed_revision_member':
                    member = invalid['manifest']['members'][0]
                    member['point_id'] = next(item['point_id'] for item in base['manifest']['members']
                        if item['chunk_id'] == member['chunk_id'])
                elif key == 'malformed_utf8_span':
                    member = next(item for item in invalid['manifest']['members'] if item['chunk_id'] == 'chunk-1')
                    if member['end_byte'] != 7:
                        raise RuntimeError('manager_invalid_input_utf8_fixture')
                    member['end_byte'] = 6
                else:
                    invalid['manifest']['sparse_profile']['encoder'] = 'bm25'
                activity = (issued, network['requests'], network['mutations'])
                journal = await journal_states()
                await expect(kind, lambda: stage_call(manager, invalid))
                graph = await stage_graph(valid)
                if ((issued, network['requests'], network['mutations']) != activity
                        or await journal_states() != journal or await stage_graph(base) != base_graph
                        or graph['pointer'] != [(base['manifest']['generation_id'],)]
                        or any(rows for table, rows in graph.items() if table != 'pointer')):
                    raise RuntimeError('manager_invalid_input_admission_wrote')
                attempt = original_issue_attempt(dict(intent_id=valid['intent']['intent_id'],
                    owner_token=lookup_token, epoch=supervisor.profile_binding(inputs['config'])['epoch'],
                    dispatch_id='manager-' + key.replace('_', '-') + '-absence'), deadline=deadline)
                probe = original_transport_for(attempt)
                fields = ('backend_namespace', 'physical_collection', 'collection_incarnation', 'tenant_id',
                    'collection', 'document_id', 'revision_id', 'generation_id')
                filters = dict(must=[dict(key=field, match=dict(value=valid['manifest'][field])) for field in fields])
                try:
                    physical = json.loads(bytes(await probe.request('POST', target + '/points',
                        body=request_bytes(dict(ids=[member['point_id'] for member in valid['manifest']['members']],
                            with_payload=True, with_vector=True)), deadline=deadline)))
                    scoped = json.loads(bytes(await probe.request('POST', target + '/points/scroll',
                        body=request_bytes(dict(filter=filters, limit=8, with_payload=True, with_vector=True)),
                        deadline=deadline)))
                    if (physical.get('status') != 'ok' or physical.get('result') != []
                            or scoped.get('status') != 'ok' or scoped.get('result') !=
                                dict(points=[], next_page_offset=None)):
                        raise RuntimeError('manager_invalid_input_physical_target_present')
                finally:
                    await probe.close()
                checks.append(key + '_rejected_before_write')
            if len(snapshots) != 2 or network['mutations'] != 1 or issued:
                raise RuntimeError('manager_invalid_input_inventory')
            return dict(runtime='python', checks=checks, proof_scope='public_invalid_input_only',
                public_snapshots_sha256=sha256(request_bytes(snapshots)).hexdigest())
        if scenario == 'equal_set':
            base = inputs['stage']
            save(await stage_call(manager, base))
            published = save(await publish_call(manager, base))
            if not published['published'] or network['mutations'] != 1:
                raise RuntimeError('manager_equal_set_base_unpublished')
            base_graph = await stage_graph(base)
            immutable = ('document_revisions', 'generations', 'members', 'point_claims', 'vector_replays')
            fields = ('backend_namespace', 'physical_collection', 'collection_incarnation', 'tenant_id',
                'collection', 'document_id', 'revision_id', 'generation_id')
            for key, extra, label in (
                    ('equal_set', False, 'equal_count_wrong_set_public_publish_rejected'),
                    ('equal_extra', True, 'third_extra_point_scroll_sentinel_rejected')):
                successor = inputs['stages'][key]
                staged = save(await stage_call(manager, successor))
                before = await stage_graph(successor)
                if staged['state'] != 'staged' or staged['published'] or before['preparations']:
                    raise RuntimeError('manager_equal_set_stage_flags')
                writes = network['mutations']
                set_fault.update(armed=True, watching=True, stage=successor, extra=extra, reads=[])
                try:
                    await expect(IntegrityViolation, lambda: publish_call(manager, successor))
                finally:
                    set_fault['watching'] = False
                after = await stage_graph(successor)
                state = await current(successor)
                generation = [json.loads(row[0]) for row in after['generations']]
                if (set_fault['armed'] or set_fault['fired'] != (2 if extra else 1)
                        or network['mutations'] != writes + 1
                        or any(before[table] != after[table] for table in immutable)
                        or after['pointer'] != [(base['manifest']['generation_id'],)] or after['preparations']
                        or len(generation) != 1 or generation[0]['published'] is not False
                        or generation[0]['ever_published'] is not False
                        or state['intent']['state'] != 'writing' or state['intent']['replica_complete'] is not False
                        or state['intent']['authority_committed'] is not False or state['pending']
                        or len(after['dispatches']) != 1 or after['dispatches'][0][0] != 'settled'
                        or not isinstance(after['dispatches'][0][1], str)
                        or len(after['dispatches'][0][1]) != 64
                        or any(char not in '0123456789abcdef' for char in after['dispatches'][0][1])
                        or set(await journal_states()) != {'settled'}
                        or any(set_fault['unexpected'] in row[0] for row in after['point_claims'])):
                    raise RuntimeError('manager_equal_set_publication_boundary')
                expected = {point['id']: point for point in set_fault['points']}
                filters = dict(must=[dict(key=field, match=dict(value=successor['manifest'][field])) for field in fields])
                if extra:
                    reads = set_fault['reads']
                    scrolls = [read for read in reads if read['path'] == target + '/points/scroll']
                    if (len(reads) != 2 or len(scrolls) != 1
                            or reads[0]['path'] != target + '/points' or scrolls[0] is not reads[1]
                            or scrolls[0]['body'] != dict(filter=filters, limit=8, with_payload=True, with_vector=True)
                            or any(type(read['allowance']) is not int or not 0 < read['allowance'] <= 1048576 for read in reads)
                            or scrolls[0]['response'].get('status') != 'ok'
                            or sorted(point['id'] for point in scrolls[0]['response']['result']['points']) != sorted(expected)
                            or any(any(point.get(field) != expected[point['id']][field]
                                for field in ('id', 'vector', 'payload'))
                                for point in scrolls[0]['response']['result']['points'])
                            or scrolls[0]['response']['result']['next_page_offset'] is not None):
                        raise RuntimeError('manager_equal_set_bounded_scroll_missing')
                probe_attempt = supervisor.issue_attempt(dict(intent_id=successor['intent']['intent_id'],
                    owner_token=state['owner']['owner_token'], epoch=state['backend']['epoch'],
                    dispatch_id='manager-' + key.replace('_', '-') + '-readback'), deadline=deadline)
                probe = supervisor.transport_for(probe_attempt)
                try:
                    all_ids = sorted({point['id'] for point in set_fault['originals']} | set(expected))
                    physical = json.loads(bytes(await probe.request('POST', target + '/points',
                        body=request_bytes(dict(ids=all_ids, with_payload=True, with_vector=True)), deadline=deadline)))
                    scoped = json.loads(bytes(await probe.request('POST', target + '/points/scroll',
                        body=request_bytes(dict(filter=filters, limit=8, with_payload=True, with_vector=True)), deadline=deadline)))
                    for response, rows in ((physical, physical.get('result', [])),
                            (scoped, scoped.get('result', {}).get('points', []))):
                        if (response.get('status') != 'ok' or sorted(row['id'] for row in rows) != sorted(expected)
                                or any(any(row.get(field) != expected[row['id']][field]
                                    for field in ('id', 'vector', 'payload')) for row in rows)):
                            raise RuntimeError('manager_equal_set_physical_observation')
                    if scoped['result']['next_page_offset'] is not None:
                        raise RuntimeError('manager_equal_set_diagnostic_continuation')
                    completed(await probe.handle.request('POST', target + '/points/delete?wait=true&ordering=strong',
                        body=request_bytes(dict(points=[set_fault['unexpected']])), deadline=deadline))
                    set_fault['deletes'] += 1
                finally:
                    await probe.close()
                base_after = await stage_graph(base)
                if any(base_after[table] != base_graph[table] for table in
                        (*immutable, 'publication_intents', 'pointer', 'preparations')):
                    raise RuntimeError('manager_equal_set_base_changed')
                checks.append(label)
            if (len(snapshots) != 4 or network['mutations'] != 3
                    or set_fault['puts'] != 2 or set_fault['deletes'] != 3):
                raise RuntimeError('manager_equal_set_inventory')
            return dict(runtime='python', checks=checks, proof_scope='public_wrong_set_only',
                public_snapshots_sha256=sha256(request_bytes(snapshots)).hexdigest())
        if scenario != 'default':
            base, successor = inputs['stage'], inputs['stages'][scenario]
            save(await stage_call(manager, base))
            published = save(await publish_call(manager, base))
            if published['state'] != 'published' or not published['published']:
                raise RuntimeError('manager_wrong_dense_base_unpublished')
            staged = save(await stage_call(manager, successor))
            before = await stage_graph(successor)
            base_graph = await stage_graph(base)
            if (len(successor['manifest']['members']) != 2 or staged['state'] != 'staged'
                    or staged['published'] or staged['replica_complete'] or before['preparations']):
                raise RuntimeError('manager_wrong_dense_stage_flags')
            writes = network['mutations']
            dense_fault['armed'] = True
            await expect(IntegrityViolation, lambda: publish_call(manager, successor))
            after = await stage_graph(successor)
            state = await current(successor)
            intent = state['intent']
            generation = [json.loads(row[0]) for row in after['generations']]
            immutable = ('document_revisions', 'generations', 'members', 'point_claims', 'vector_replays')
            base_after = await stage_graph(base)
            if (dense_fault['fired'] != 1 or dense_fault['armed'] or network['mutations'] != writes + 1
                    or any(before[table] != after[table] for table in immutable)
                    or any(base_after[table] != base_graph[table]
                        for table in (*immutable, 'publication_intents', 'pointer', 'preparations'))
                    or before['pointer'] != [(base['manifest']['generation_id'],)]
                    or after['pointer'] != before['pointer'] or after['preparations']
                    or len(generation) != 1 or generation[0]['published'] is not False
                    or generation[0]['ever_published'] is not False
                    or intent['state'] != 'writing' or intent['replica_complete'] is not False
                    or intent['authority_committed'] is not False or state['pending']
                    or len(after['dispatches']) != 1 or after['dispatches'][0][0] != 'settled'
                    or not isinstance(after['dispatches'][0][1], str)
                    or len(after['dispatches'][0][1]) != 64
                    or any(char not in '0123456789abcdef' for char in after['dispatches'][0][1])
                    or set(await journal_states()) != {'settled'}):
                raise RuntimeError('manager_wrong_dense_publication_boundary')
            point = dense_fault['point']
            ids = sorted(member['point_id'] for member in successor['manifest']['members'])
            probe_attempt = supervisor.issue_attempt(dict(intent_id=successor['intent']['intent_id'],
                owner_token=state['owner']['owner_token'], epoch=state['backend']['epoch'],
                dispatch_id='manager-' + scenario.replace('_', '-') + '-readback'), deadline=deadline)
            probe = supervisor.transport_for(probe_attempt)
            try:
                physical = json.loads(bytes(await probe.request('POST', target + '/points',
                    body=request_bytes(dict(ids=ids, with_payload=True, with_vector=True)),
                    deadline=deadline)))
            finally:
                await probe.close()
            rows = physical.get('result', [])
            corrupted = next((row for row in rows if row.get('id') == point['id']), {})
            if (physical.get('status') != 'ok' or sorted(row['id'] for row in rows) != ids
                    or any(corrupted.get(key) != point[key] for key in ('id', 'vector', 'payload'))):
                raise RuntimeError('manager_wrong_dense_physical_observation')
            if scenario in ('wrong_sparse', 'wrong_profile', 'missing_sparse'):
                expected_points = {point['id']: point for point in dense_fault['points']}
                if any(any(row.get(key) != expected_points[row['id']][key]
                        for key in ('id', 'vector', 'payload')) for row in rows):
                    raise RuntimeError('manager_corruption_exact_physical_observation')
            if len(snapshots) != 3:
                raise RuntimeError('manager_wrong_dense_snapshot_inventory')
            if scenario == 'missing_sparse':
                checks.append('missing_sparse_vector_public_publish_rejected')
                originals = {point['id']: point for point in dense_fault['originals']}
                for member, dense, sparse in zip(successor['manifest']['members'],
                        successor['dense_vectors'], successor['sparse_vectors'], strict=True):
                    submitted = originals[member['point_id']]
                    if (submitted['vector'] != dict(dense=dense, sparse=sparse)
                            or any(submitted['payload'][key] != successor['manifest'][key]
                                for key in ('dense_profile', 'sparse_profile'))):
                        raise RuntimeError('manager_missing_sparse_immutable_replay_input')
                dense_fault['repairing'] = True
                try:
                    repaired = save(await manager.repair(reference(successor), scope, ledger(),
                        deadline=deadline))
                finally:
                    dense_fault['repairing'] = False
                repaired_graph = await stage_graph(successor)
                repaired_state = await current(successor)
                repaired_generation = [json.loads(row[0]) for row in repaired_graph['generations']]
                expected_generation = [json.loads(row[0]) for row in before['generations']]
                for generation_row in expected_generation:
                    generation_row.update(published=True, ever_published=True)
                stable = ('document_revisions', 'members', 'point_claims', 'vector_replays')
                if (repaired['operation'] != 'repair' or repaired['state'] != 'published'
                        or not all(repaired[key] for key in
                            ('published', 'replica_complete', 'authority_committed'))
                        or repaired['generation_id'] != successor['manifest']['generation_id']
                        or repaired['revision_id'] != successor['manifest']['revision_id']
                        or dense_fault['fixture_puts'] != 1 or dense_fault['fired'] != 1
                        or len(dense_fault['repair_bodies']) != 1 or dense_fault['repair_completed'] != 1
                        or network['mutations'] != writes + 2
                        or any(before[table] != repaired_graph[table] for table in stable)
                        or repaired_graph['pointer'] != [(successor['manifest']['generation_id'],)]
                        or repaired_generation != expected_generation
                        or len(repaired_generation) != 1
                        or repaired_generation[0]['published'] is not True
                        or repaired_generation[0]['ever_published'] is not True
                        or repaired_state['intent']['state'] != 'published'
                        or repaired_state['pending'] or len(repaired_graph['dispatches']) != 2
                        or any(row[0] != 'settled' or not isinstance(row[1], str)
                            or len(row[1]) != 64 or any(char not in '0123456789abcdef' for char in row[1])
                            for row in repaired_graph['dispatches'])
                        or set(await journal_states()) != {'settled'} or len(snapshots) != 4):
                    raise RuntimeError('manager_missing_sparse_repair_boundary')
                repaired_probe_attempt = supervisor.issue_attempt(dict(
                    intent_id=successor['intent']['intent_id'], owner_token=state['owner']['owner_token'],
                    epoch=state['backend']['epoch'], dispatch_id='manager-missing-sparse-repaired-readback'),
                    deadline=deadline)
                repaired_probe = supervisor.transport_for(repaired_probe_attempt)
                try:
                    repaired_physical = json.loads(bytes(await repaired_probe.request('POST', target + '/points',
                        body=request_bytes(dict(ids=ids, with_payload=True, with_vector=True)), deadline=deadline)))
                finally:
                    await repaired_probe.close()
                repaired_rows = repaired_physical.get('result', [])
                expected_points = {point['id']: point for point in dense_fault['originals']}
                if (repaired_physical.get('status') != 'ok'
                        or sorted(row['id'] for row in repaired_rows) != ids
                        or any(any(row.get(key) != expected_points[row['id']][key]
                            for key in ('id', 'vector', 'payload')) for row in repaired_rows)):
                    raise RuntimeError('manager_missing_sparse_repaired_physical_observation')
                checks.append('missing_sparse_vector_complete_repair_published')
                return dict(runtime='python', checks=checks, proof_scope='public_corruption_repair_only',
                    public_snapshots_sha256=sha256(request_bytes(snapshots)).hexdigest())
            label = dict(wrong_dense='wrong_dense_vector_public_publish_rejected',
                wrong_sparse='wrong_sparse_vector_public_publish_rejected',
                wrong_profile='wrong_full_profile_public_publish_rejected')[scenario]
            return dict(runtime='python', checks=[label],
                proof_scope='public_corruption_only',
                public_snapshots_sha256=sha256(request_bytes(snapshots)).hexdigest())
        checks.append(CHECKS[0])
        base = inputs['stage']
        stages = inputs['stages']
        one = ledger()
        save(await stage_call(manager, base, selected_ledger=one))
        staged = await current(base)
        usage = one.snapshot()
        if (staged['document']['active_generation_id'] is not None or network['mutations']
                or usage['attempts'] != 1 or usage['provider_calls'] or usage['candidates'] or usage['pending']):
            raise RuntimeError('manager_stage_or_ledger_boundary')
        budget_journal = await journal_states()
        budget_activity = (network['requests'], network['mutations'])
        if budget_journal:
            raise RuntimeError('manager_budget_fixture_already_dispatched')
        await expect(BudgetExhausted, lambda: publish_call(manager, base, selected_ledger=one))
        if ((network['requests'], network['mutations']) != budget_activity
                or await journal_states() != budget_journal or await current(base) != staged):
            raise RuntimeError('manager_budget_dispatched_mutation')
        checks.append(CHECKS[1])
        published = save(await publish_call(manager, base))
        if (published['state'] != 'published' or not published['published']
                or (await current(base))['document']['active_generation_id'] != base['manifest']['generation_id']
                or not network['mutations'] or set(await journal_states()) != {'settled'}):
            raise RuntimeError('manager_native_publication_state')
        checks.append(CHECKS[2])
        writes = network['mutations']
        save(await stage_call(manager, base))
        save(await publish_call(manager, base))
        if network['mutations'] != writes:
            raise RuntimeError('manager_historical_retry_rewrote')
        checks.append(CHECKS[3])
        changed = deepcopy(base)
        changed['intent']['initial_authorization']['tag'] = 'changed-manager-bootstrap'
        await expect(IntegrityViolation, lambda: stage_call(manager, changed))
        if network['mutations'] != writes:
            raise RuntimeError('manager_changed_payload_rewrote')
        checks.append(CHECKS[4])
        async def denied(*args):
            return False
        async def malformed(*args):
            return 'yes'
        async def unavailable(*args):
            raise ProviderUnavailable()
        for callback, kind in ((denied, UnauthorizedScope), (malformed, InvalidRequest),
                (unavailable, ProviderUnavailable)):
            temporary = await new_manager(callback)
            await expect(kind, lambda: stage_call(temporary, stages['denied_input']))
            await temporary.close()
        if (await current(stages['denied_input']))['intent'] is not None or network['mutations'] != writes:
            raise RuntimeError('manager_authorization_admitted_work')
        checks.append(CHECKS[5])
        rollback = stages['stage_rollback']
        stage_requests = network['requests']
        acknowledgment['stage'] = dict(intent_id=rollback['intent']['intent_id'],
            action='rollback', inserts=0, fired=0, dml=0)
        await expect(ProviderUnavailable, lambda: stage_call(manager, rollback))
        graph = await stage_graph(rollback)
        if (acknowledgment['stage']['fired'] != 1 or acknowledgment['stage']['inserts'] != 1
                or any(rows for table, rows in graph.items() if table != 'pointer')
                or graph['pointer'] != [(base['manifest']['generation_id'],)]
                or (await current(rollback))['intent'] is not None or network['mutations'] != writes
                or network['requests'] != stage_requests):
            raise RuntimeError('manager_atomic_stage_rollback')

        ack_stage = stages['stage_ack_loss']
        acknowledgment['stage'] = dict(intent_id=ack_stage['intent']['intent_id'],
            action='ack_loss', inserts=0, fired=0, dml=0)
        acknowledged = plain(await stage_call(manager, ack_stage))
        fault = acknowledgment['stage']
        stage_dml = fault['dml']
        committed = await stage_graph(ack_stage)
        if (acknowledged['state'] != 'staged' or acknowledged['authority_committed']
                or fault['fired'] != 1 or fault['inserts'] != 1 or not fault['retired_connection'].closed
                or committed['pointer'] != [(base['manifest']['generation_id'],)]
                or any(len(committed[table]) != count for table, count in (
                    ('publication_intents', 1), ('document_revisions', 1), ('generations', 1),
                    ('members', len(ack_stage['manifest']['members'])),
                    ('point_claims', len(ack_stage['manifest']['members'])),
                    ('vector_replays', len(ack_stage['manifest']['members'])), ('document_owners', 0)))):
            raise RuntimeError('manager_stage_ack_graph_missing')
        # A genuinely new writer reconstructs the committed immutable graph.
        resumed_writer = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
        await resumed_writer.initialize(deadline=deadline)
        resumed_verifier = QdrantReconciliationVerifier(resumed_writer, supervisor)
        resumed_recovery = PostgresQdrantRecovery(supervisor_resource, inputs['config'], supervisor, resumed_verifier)
        resumed = QdrantPublicationManager(PostgresQdrantPublicationAuthority(resumed_writer, resumed_recovery),
            transport, inputs['config'], supervisor, authorize)
        managers.append(resumed)
        try:
            await resumed.initialize(deadline=deadline)
            from cragkit._qdrant_writer_contract import prepare_stage, stage_data
            actual = stage_data(await resumed_writer.load_stage(context(ack_stage), deadline=deadline))
            expected = stage_data(prepare_stage(ack_stage))
            def replay_facts(graph):
                return tuple(None if replay is None else
                    (replay.blob,replay.blob_sha256,replay.input_sha256)
                    for replay in (*graph.dense,*graph.sparse))
            if (actual.source != expected.source or actual.manifest != expected.manifest
                    or actual.intent != expected.intent or replay_facts(actual) != replay_facts(expected)):
                raise RuntimeError('manager_stage_ack_graph_changed')
            outcome = plain(await stage_call(resumed, ack_stage))
            if (outcome != acknowledged
                    or fault['inserts'] != 1 or await stage_graph(ack_stage) != committed
                    or fault['dml'] != stage_dml
                    or network['mutations'] != writes or network['requests'] != stage_requests):
                raise RuntimeError('manager_stage_ack_retry_changed_graph')
        finally:
            await resumed.close()
            managers.remove(resumed)
            await resumed_recovery.close()
            await resumed_writer.close()
        acknowledgment['stage'] = None
        # Fixture-admin corruption after a complete committed stage, not a public half-commit.
        await corrupt_one_member(ack_stage)
        partial_graph = await stage_graph(ack_stage)
        partial_generation = json.loads(partial_graph['generations'][0][0])
        if (len(ack_stage['manifest']['members']) != 2
                or partial_generation['expected_member_count'] != 2 or partial_generation['published']
                or json.loads(partial_graph['publication_intents'][0][0])['state'] != 'staged'
                or len(partial_graph['members']) != 1
                or partial_graph['point_claims'] != committed['point_claims']
                or partial_graph['vector_replays'] != committed['vector_replays']
                or partial_graph['pointer'] != [(base['manifest']['generation_id'],)]):
            raise RuntimeError('manager_partial_member_fixture_missing')
        partial_activity = (network['requests'], network['mutations'])
        await expect(IntegrityViolation, lambda: publish_call(manager, ack_stage))
        if ((network['requests'], network['mutations']) != partial_activity
                or await stage_graph(ack_stage) != partial_graph):
            raise RuntimeError('manager_partial_member_publication_mutated')
        save(await stage_call(manager, stages['loser']))
        save(await stage_call(manager, stages['winner']))
        publication = acknowledgment['publication']
        publication.update(armed=True,track=True)
        winner = save(await publish_call(manager, stages['winner']))
        winner_graph = await stage_graph(stages['winner'])
        import json
        intent_row = json.loads(winner_graph['publication_intents'][0][0])
        generation_row = json.loads(winner_graph['generations'][0][0])
        if (not winner['published'] or winner['state'] != 'published'
                or publication['armed'] or publication['fired'] != 1 or publication['cas_writes'] != 1
                or not publication['retired_connection'].closed
                or winner_graph['pointer'] != [(stages['winner']['manifest']['generation_id'],)]
                or intent_row['state'] != 'published' or not intent_row['replica_complete']
                or not generation_row['published'] or not generation_row['ever_published']):
            raise RuntimeError('manager_publication_commit_not_exact')
        after_commit = (publication['dml'],network['requests'])
        retry_manager = await new_manager()
        historical = plain(await publish_call(retry_manager, stages['winner']))
        if (historical != winner or (publication['dml'],network['requests']) != after_commit
                or await stage_graph(stages['winner']) != winner_graph):
            raise RuntimeError('manager_publication_commit_retry_mutated')
        await retry_manager.close()
        managers.remove(retry_manager)
        publication['track'] = False
        writes = network['mutations']
        loser = save(await publish_call(manager, stages['loser']))
        if (loser['state'] != 'conflict' or network['mutations'] != writes
                or (await current(stages['winner']))['document']['active_generation_id']
                    != stages['winner']['manifest']['generation_id']):
            raise RuntimeError('manager_original_pointer_conflict')
        checks.append(CHECKS[6])
        save(await stage_call(manager, stages['prepared']))
        mode.update(action='cancel', intent_id=stages['prepared']['intent']['intent_id'], fired=False)
        task = asyncio.create_task(publish_call(manager, stages['prepared']))
        mode['task'] = task
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise RuntimeError('manager_prepared_cancellation_missing')
        prepared = await current(stages['prepared'])
        if (not mode['fired'] or prepared['intent']['state'] != 'prepared'
                or prepared['document']['active_generation_id'] != stages['winner']['manifest']['generation_id']):
            raise RuntimeError('manager_preparation_became_public')
        writes = network['mutations']
        await manager.close()
        mode.update(action=None, intent_id=None, fired=False)
        manager = await new_manager()
        save(await publish_call(manager, stages['prepared']))
        if network['mutations'] != writes:
            raise RuntimeError('manager_prepared_resume_rewrote')
        checks.append(CHECKS[7])
        save(await stage_call(manager, stages['commit']))
        acknowledgment['armed'] = True
        writes = network['mutations']
        save(await publish_call(manager, stages['commit']))
        if (acknowledgment['armed'] or acknowledgment['fired'] != 1
                or not acknowledgment['retired_connection'].closed or network['mutations'] != writes + 1):
            raise RuntimeError('manager_preparation_ack_loss_not_reconciled')
        checks.append(CHECKS[8])
        save(await stage_call(manager, stages['session']))
        mode.update(action='session', intent_id=stages['session']['intent']['intent_id'], fired=False)
        save(await publish_call(manager, stages['session']))
        binding = supervisor.profile_binding(inputs['config'])
        if not mode['fired'] or binding['epoch'] != 1 or binding['recovery'] is not None:
            raise RuntimeError('manager_finalization_exclusion_missing')
        checks.append(CHECKS[9])
        mode.update(action=None, intent_id=None, fired=False)
        save(await stage_call(manager, stages['revoked']))
        mode.update(action='revoke', intent_id=stages['revoked']['intent']['intent_id'], fired=False)
        denied_result = save(await publish_call(manager, stages['revoked']))
        if (not mode['fired'] or denied_result['state'] != 'denied'
                or (await current(stages['revoked'], fresh_scope))['document']['active_generation_id']
                    != stages['session']['manifest']['generation_id']):
            raise RuntimeError('manager_revocation_published_staged_generation')
        checks.append(CHECKS[10])
        mode.update(action=None, intent_id=None, fired=False)
        writes = network['mutations']
        save(await stage_call(manager, base, fresh_scope))
        save(await publish_call(manager, base, fresh_scope))
        if (network['mutations'] != writes or await document_acl(fresh_scope) !=
                [([], [], 'auth-manager-2', 2, stages['session']['manifest']['generation_id'])]):
            raise RuntimeError('manager_historical_retry_restored_authority')
        checks.append(CHECKS[11])
        bootstrap_graph = await stage_graph(base)
        bootstrap_acl = await document_acl(fresh_scope)
        bootstrap_activity = (publication['dml'], network['requests'], network['mutations'])
        changed_bootstrap = deepcopy(base)
        changed_bootstrap['intent']['initial_authorization'].update(
            grant_ids=['grant-manager-bootstrap-changed'],
            tag='changed-manager-bootstrap-after-security')
        publication['track'] = True
        try:
            await expect(IntegrityViolation, lambda: stage_call(manager, changed_bootstrap, fresh_scope))
        finally:
            publication['track'] = False
        if ((publication['dml'], network['requests'], network['mutations']) != bootstrap_activity
                or await stage_graph(base) != bootstrap_graph
                or await document_acl(fresh_scope) != bootstrap_acl):
            raise RuntimeError('manager_changed_bootstrap_after_security_mutated')
        save(await stage_call(manager, stages['lost_ack'], fresh_scope))
        network['drop'] = True
        await expect(ProviderUnavailable, lambda: publish_call(manager, stages['lost_ack'], fresh_scope))
        writes = network['mutations']
        await manager.close()
        manager = await new_manager()
        await expect(ProviderUnavailable, lambda: publish_call(manager, stages['lost_ack'], fresh_scope))
        if (not network['completed_drop'] or network['mutations'] != writes
                or 'unknown' not in await journal_states()
                or (await current(stages['lost_ack'], fresh_scope))['document']['active_generation_id']
                    != stages['session']['manifest']['generation_id']):
            raise RuntimeError('manager_unknown_ack_was_replayed')
        checks.append(CHECKS[12])
        await manager.close()
        await writer.initialize(deadline=deadline)
        if supervisor.profile_binding(inputs['config'])['alive'] is not True:
            raise RuntimeError('manager_closed_borrowed_controller')
        await current(base, fresh_scope)
        await recovery.initialize(deadline=deadline)
        if 'unknown' not in await journal_states():
            raise RuntimeError('manager_borrowed_recovery_changed_unknown')
        checks.append(CHECKS[13])
        checks.extend(CHECKS[14:17])
        checks.append(CHECKS[17])
        checks.append(CHECKS[18])
        checks.append(CHECKS[19])
        if len(snapshots) != 19:
            raise RuntimeError('manager_public_snapshot_inventory')
        return dict(runtime='python', checks=checks, proof_scope='public_stage_publish_only',
            public_snapshots_sha256=sha256(request_bytes(snapshots)).hexdigest())
    except BaseException as error:
        primary = error
        name = type(error).__name__
        raise NativePublicationManagerFailure(dict(ok=False, step=len(checks),
            error=name if name in ERRORS else 'internal')) from None
    finally:
        failures = []
        cleanup_deadline = asyncio.get_running_loop().time() + 12
        factory = [('transport_close', transport)] if callable(getattr(transport, 'close', None)) else []
        for operation, owned in ([('manager_close', instance) for instance in managers]
                + factory
                + [('transport_close', handle) for handle in handles]
                + [('recovery_close', recovery)]
                + ([('verifier_close', verifier)] if callable(getattr(verifier, 'close', None)) else [])
                + [('writer_close', writer),
                   ('resource_close', resource), ('supervisor_resource_close', supervisor_resource),
                   ('controller_close', supervisor)]):
            try:
                await asyncio.wait_for(owned.close(), max(.001,
                    min(8, cleanup_deadline - asyncio.get_running_loop().time())))
            except BaseException as error:
                failures.append((operation, error))
        if endpoint is not None:
            try:
                await observed_listener(endpoint, allow_absent=True)
            except BaseException as error:
                failures.append(('listener_close', error))
        if failures:
            closed = []
            for operation, error in failures:
                name = type(error).__name__
                closed.append(dict(operation=operation, outcome=name if name in ERRORS else 'internal'))
            name = type(primary).__name__ if primary is not None else None
            raise NativePublicationManagerFailure(dict(ok=False, step=len(checks), error='cleanup_failed',
                primary=name if name in ERRORS else ('internal' if name else None), cleanup=closed)) from None
