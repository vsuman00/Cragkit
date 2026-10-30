"""Native physical UUID collision between independently coordinated documents."""
from __future__ import annotations

from copy import deepcopy

CHECKS = (
    'distinct_coordinators_and_targeted_collision',
    'native_claim_conflict_wait_observed',
    'one_atomic_winner_loser_integrity_violation',
    'loser_successor_rolled_back_baselines_preserved',
    'winner_published_with_exact_native_readback',
    'loser_retry_zero_mutations_preserves_points',
    'collision_hook_restored_and_cleanup_verified',
)
PROOF_SCOPE = 'native_global_uuid_collision_only'


class _ClaimConnection:
    def __init__(self, connection, state, lane):
        self.connection, self.state, self.lane = connection, state, lane

    def __getattr__(self, key):
        return getattr(self.connection, key)

    async def execute(self, statement, params=()):
        import asyncio
        target = (self.state['armed'] and isinstance(statement, str)
            and statement.startswith('INSERT INTO cragkit_qdrant.point_claims ')
            and self.state['uuid'] in params)
        if target:
            cursor = await self.connection.execute('SELECT pg_backend_pid()')
            self.state['pids'][self.lane] = (await cursor.fetchall())[0][0]
            self.state['arrivals'][self.lane] += 1
            if self.lane == 'b': self.state['b_entered'].set()
        result = await self.connection.execute(statement, params)
        if target and self.lane == 'a':
            self.state['a_inserted'].set()
            await asyncio.wait_for(self.state['release'].wait(), 10)
        return result


class _ClaimPool:
    def __init__(self, config, state, lane):
        from cragkit._postgres_pool import _owned_pool
        self.pool, self.state, self.lane = _owned_pool(config), state, lane

    async def open(self, **options): return await self.pool.open(**options)
    async def wait(self, **options): return await self.pool.wait(**options)
    async def close(self, **options): return await self.pool.close(**options)
    async def getconn(self, **options):
        return _ClaimConnection(await self.pool.getconn(**options), self.state, self.lane)
    async def putconn(self, connection): return await self.pool.putconn(connection.connection)


async def python_global_uuid_cases(value):
    import asyncio
    import hashlib
    import json
    from pathlib import Path
    import cragkit._qdrant_manifest as manifest_module
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit.contracts import Limits, TrustedScope
    from cragkit.errors import IntegrityViolation
    from cragkit.execution import ExecutionLedger
    from cragkit.qdrant_publication import (QdrantPublicationManager,
        PostgresQdrantPublicationAuthority, ManagedQdrantPublicationTransport,
        PostgresQdrantWriter, PostgresQdrantRecovery, ManagedQdrantSupervisor,
        QdrantReconciliationVerifier)
    from qdrant_public_security_cases import NativePublicSecurityFailure
    from qdrant_publication_manager_cases import ERRORS
    from qdrant_supervisor_cases import plain, request_bytes, observed_listener

    inputs = deepcopy(value['inputs'])
    base_a, base_b = inputs['baseline_a'], inputs['baseline_b']
    next_a, next_b = inputs['successor_a'], inputs['successor_b']
    collision = tuple(inputs['collision_tuple']); shared = inputs['collision_uuid']
    original_point_id = manifest_module.point_id
    ordinary_loser = original_point_id(collision)
    if ordinary_loser == shared: raise RuntimeError('global_uuid_injection_not_needed')
    patch = dict(hits=0, enabled=True)
    def injected_point_id(identity):
        natural = original_point_id(identity)
        if patch['enabled'] and tuple(identity) == collision:
            patch['hits'] += 1
            return shared
        return natural
    deadline = asyncio.get_running_loop().time() + 150
    state = dict(armed=False, uuid=shared, pids={}, arrivals=dict(a=0, b=0),
        a_inserted=asyncio.Event(), b_entered=asyncio.Event(), release=asyncio.Event())
    def config(raw):
        raw = dict(raw)
        for key in ('sslrootcert', 'passfile'): raw[key] = Path(raw[key])
        parsed = PoolConfig.model_validate(raw)
        if parsed.max_size != 1: raise RuntimeError('global_uuid_pool_bound')
        return parsed
    resources = [PoolResource(config(value['writer_config']),
        factory=lambda cfg, lane=lane: _ClaimPool(cfg, state, lane)) for lane in ('a', 'b')]
    writers = [PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id']) for resource in resources]
    observer = PoolResource(config(value['observer_config']))
    supervisor = ManagedQdrantSupervisor(Path(value['binary']), Path(value['work_dir']), inputs['instance_id'], inputs['config'])
    scope = TrustedScope.model_validate(inputs['scope'])
    target = '/collections/' + inputs['config']['physical_collection']
    checks, rows, owned, supervisor_resources, tasks = [], [], [], [], []
    network = dict(mutations=0)
    endpoint = primary = None
    original_http = supervisor._http
    def reference(stage): return {key: stage['intent'][key] for key in ('collection', 'document_id', 'intent_id')}
    def context(stage, lane):
        return dict(**reference(stage), scope=scope,
            owner_token='00000000-0000-4000-8000-00000000000' + str(lane + 1))
    async def authorize(selected, collection, document):
        return (selected == scope and collection == base_a['manifest']['collection']
            and document in (base_a['manifest']['document_id'], base_b['manifest']['document_id']))
    async def call(method, item):
        book = ExecutionLedger(Limits(deadline_ms=150000, max_provider_calls=0), deadline=deadline)
        try: return plain(await method(item, scope, book, deadline=deadline))
        finally:
            usage = book.snapshot()
            if (usage['attempts'], usage['provider_calls'], usage['pending']) != (1, 0, 0):
                raise RuntimeError('global_uuid_usage')
    async def observed_http(*args, **kwargs):
        if len(args) >= 3:
            method, path = args[1:3]
            if method in ('PUT', 'DELETE', 'PATCH') or (method == 'POST' and path not in
                    (target + '/points', target + '/points/scroll', target + '/points/count')
                    and not path.endswith(('/search', '/query'))):
                network['mutations'] += 1
        return await original_http(*args, **kwargs)
    async def provision(admin, probe):
        await admin.request('PUT', target, body=request_bytes(inputs['collection_config']), deadline=deadline)
        probe = plain(probe); path = '/collections/' + probe['collection']
        await admin.request('PUT', path, body=request_bytes(probe['collection_config']), deadline=deadline)
        await admin.request('PUT', path + '/points?wait=true&ordering=strong',
            body=request_bytes(dict(points=[probe['point']])), deadline=deadline)
    async def read_points(ids):
        status, raw = await original_http(supervisor._key, 'POST', target + '/points',
            request_bytes(dict(ids=ids, with_payload=True, with_vector=True)), deadline)
        body = json.loads(raw)
        if status != 200 or body.get('status') != 'ok': raise RuntimeError('global_uuid_readback')
        return sorted([{key: item[key] for key in ('id', 'payload', 'vector')} for item in body['result']], key=lambda item: item['id'])
    async def managers():
        resource = PoolResource(config(value['supervisor_config']))
        supervisor_resources.append(resource); await resource.open()
        result = []
        for writer in writers:
            verifier = QdrantReconciliationVerifier(writer, supervisor)
            recovery = PostgresQdrantRecovery(resource, inputs['config'], supervisor, verifier)
            authority = PostgresQdrantPublicationAuthority(writer, recovery)
            transport = ManagedQdrantPublicationTransport(supervisor)
            manager = QdrantPublicationManager(authority, transport, inputs['config'], supervisor, authorize)
            owned.extend((manager, transport, recovery, verifier))
            await manager.initialize(deadline=deadline); result.append(manager)
        return result, resource
    async def query(sql, params=()):
        async with observer.lease(deadline=deadline) as connection:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION READ ONLY')
                cursor = await connection.execute(sql, params)
                return await cursor.fetchall()
    async def baseline_graph():
        result = []
        for stage in (base_a, base_b):
            m = stage['manifest']
            for table in ('document_revisions', 'generations', 'members', 'point_claims', 'vector_replays'):
                result.append(await query('SELECT row_to_json(t)::text FROM cragkit_qdrant.' + table +
                    ' t WHERE tenant_id=%s AND collection=%s AND document_id=%s AND revision_id=%s ORDER BY row_to_json(t)::text',
                    (m['tenant_id'], m['collection'], m['document_id'], m['revision_id'])))
        return result
    async def loser_absent():
        m = next_b['manifest']; identity = (m['tenant_id'], m['collection'], m['document_id'])
        for table, column, selected in [('publication_intents', 'intent_id', next_b['intent']['intent_id']),
                ('document_revisions', 'revision_id', m['revision_id']), ('generations', 'generation_id', m['generation_id']),
                ('members', 'generation_id', m['generation_id']), ('point_claims', 'generation_id', m['generation_id']),
                ('vector_replays', 'generation_id', m['generation_id']), ('dispatch_journal', 'intent_id', next_b['intent']['intent_id'])]:
            if await query('SELECT count(*) FROM cragkit_qdrant.' + table +
                    ' WHERE tenant_id=%s AND collection=%s AND document_id=%s AND ' + column + '=%s', (*identity, selected)) != [(0,)]:
                raise RuntimeError('global_uuid_loser_graph_survived')
    try:
        manifest_module.point_id = injected_point_id
        next_b['intent']['manifest_sha256'] = manifest_module.encode_manifest(next_b['manifest'], next_b['canonical_text']).sha256
        if (original_point_id(collision) == shared or manifest_module.point_id(collision) != shared
                or manifest_module.point_id(('cragkit.qdrant.point.v1', *collision[1:6], 'unrelated-global-uuid', *collision[7:])) == shared):
            raise RuntimeError('global_uuid_mapping_scope')
        supervisor._http = observed_http
        await supervisor.initialize(deadline=deadline, provision=provision)
        endpoint = supervisor.identity()['endpoint']; await observed_listener(endpoint)
        for resource in resources: await resource.open()
        active, supervisor_resource = await managers()
        baseline_snapshots = []
        for lane, stage in enumerate((base_a, base_b)):
            await call(active[lane].stage, stage)
            if not (await call(active[lane].publish, reference(stage)))['published']:
                raise RuntimeError('global_uuid_baseline_publication')
            snapshot = plain(await writers[lane].manager_snapshot(context(stage, lane), deadline=deadline))
            if (snapshot['owner'] is None or snapshot['owner']['intent_id'] != stage['intent']['intent_id']
                    or snapshot['document']['active_generation_id'] != stage['manifest']['generation_id']):
                raise RuntimeError('global_uuid_baseline_owner')
            baseline_snapshots.append(snapshot)
        if (base_a['manifest']['document_id'] == base_b['manifest']['document_id']
                or baseline_snapshots[0]['owner']['owner_token'] == baseline_snapshots[1]['owner']['owner_token']):
            raise RuntimeError('global_uuid_coordinators_not_distinct')
        baseline_ids = [member['point_id'] for stage in (base_a, base_b) for member in stage['manifest']['members']]
        baseline_points = await read_points(baseline_ids)
        if len(baseline_points) != len(baseline_ids): raise RuntimeError('global_uuid_baseline_points')
        await supervisor_resource.close(); await observer.open()
        baseline_rows = await baseline_graph()
        checks.append(CHECKS[0]); rows.append(['coordinators', 2, 2, 1])
        state['armed'] = True; before = network['mutations']
        task_a = asyncio.create_task(call(active[0].stage, next_a)); tasks.append(task_a)
        await asyncio.wait_for(state['a_inserted'].wait(), 8)
        task_b = asyncio.create_task(call(active[1].stage, next_b)); tasks.append(task_b)
        await asyncio.wait_for(state['b_entered'].wait(), 8)
        waiting = False
        for _ in range(200):
            if await query("SELECT EXISTS(SELECT 1 FROM pg_catalog.pg_stat_activity a JOIN pg_catalog.pg_locks l ON l.pid=a.pid WHERE a.pid=%s AND a.state='active' AND a.wait_event_type='Lock' AND a.wait_event='transactionid' AND l.locktype='transactionid' AND NOT l.granted AND %s=ANY(pg_catalog.pg_blocking_pids(a.pid)))",
                    (state['pids']['b'], state['pids']['a'])) == [(True,)]:
                waiting = True; break
            if task_b.done(): break
            await asyncio.sleep(.01)
        if not waiting or task_a.done() or task_b.done() or state['pids']['a'] == state['pids']['b']:
            raise RuntimeError('global_uuid_actual_conflict_not_observed')
        checks.append(CHECKS[1]); rows.append(['claim_wait', True])
        state['release'].set()
        outcomes = await asyncio.wait_for(asyncio.gather(task_a, task_b, return_exceptions=True), 12)
        tasks.clear(); state['armed'] = False
        if (isinstance(outcomes[0], BaseException) or outcomes[0].get('state') != 'staged'
                or outcomes[0].get('operation') != 'stage' or not isinstance(outcomes[1], IntegrityViolation)
                or state['arrivals'] != dict(a=1, b=1) or network['mutations'] != before):
            raise RuntimeError('global_uuid_outcome')
        m = next_a['manifest']; member = next(item for item in m['members'] if item['point_id'] == shared)
        claim_sql = ('SELECT instance_id,tenant_id,collection,document_id,revision_id,generation_id,chunk_id,source_sha256,text_sha256,start_byte,end_byte,dense_profile,sparse_profile,dense_input_sha256,sparse_input_sha256 '
            'FROM cragkit_qdrant.point_claims WHERE backend_namespace=%s AND physical_collection=%s AND collection_incarnation=%s AND point_id=%s::uuid')
        claim_key = (m['backend_namespace'], m['physical_collection'], m['collection_incarnation'], shared)
        claim = await query(claim_sql, claim_key)
        expected = (inputs['instance_id'], *[m[key] for key in ('tenant_id','collection','document_id','revision_id','generation_id')],
            member['chunk_id'],m['source_sha256'],member['text_sha256'],member['start_byte'],member['end_byte'],
            m['dense_profile'],m['sparse_profile'],member['dense_input_sha256'],member['sparse_input_sha256'])
        if claim != [expected]: raise RuntimeError('global_uuid_claim_owner')
        checks.append(CHECKS[2]); rows.append(['claim_result', 1, 'IntegrityViolation', 0])
        await loser_absent()
        if await baseline_graph() != baseline_rows or await read_points(baseline_ids) != baseline_points:
            raise RuntimeError('global_uuid_baselines_changed')
        for lane, stage in enumerate((base_a, base_b)):
            fresh = plain(await writers[lane].manager_snapshot(context(stage, lane), deadline=deadline))
            if (fresh['document'] != baseline_snapshots[lane]['document'] or fresh['owner'] != baseline_snapshots[lane]['owner']):
                raise RuntimeError('global_uuid_baseline_pointer_owner_changed')
        checks.append(CHECKS[3]); rows.append(['rollback', 0, True, True])
        await observer.close()
        active, _ = await managers()
        published = await call(active[0].publish, reference(next_a))
        ids = [item['point_id'] for item in next_a['manifest']['members']]
        winner_points = await read_points(ids)
        if not published['published'] or len(winner_points) != len(ids): raise RuntimeError('global_uuid_winner_publication')
        for point in winner_points:
            if (point['payload']['document_id'] != m['document_id'] or point['payload']['generation_id'] != m['generation_id']
                    or point['payload']['revision_id'] != m['revision_id']): raise RuntimeError('global_uuid_winner_point_owner')
        checks.append(CHECKS[4]); rows.append(['publication', True, 1])
        before = network['mutations']
        try: await call(active[1].stage, next_b)
        except IntegrityViolation: pass
        else: raise RuntimeError('global_uuid_retry_adopted')
        if network['mutations'] != before or await read_points(ids) != winner_points or await read_points(baseline_ids) != baseline_points:
            raise RuntimeError('global_uuid_retry_changed_points')
        # Release supervisor SQL before reopening the independent observer.
        await supervisor_resources[-1].close()
        observer = PoolResource(config(value['observer_config'])); await observer.open()
        await loser_absent()
        if await query(claim_sql, claim_key) != claim:
            raise RuntimeError('global_uuid_winner_claim_changed')
        checks.append(CHECKS[5]); rows.append(['retry', 'IntegrityViolation', 0, True, True])
    except BaseException as error:
        primary = error
    finally:
        state['release'].set(); failures = []
        patch['enabled'] = False; manifest_module.point_id = original_point_id
        if (manifest_module.point_id is not original_point_id or original_point_id(collision) != ordinary_loser
                or ordinary_loser == shared or (primary is None and patch['hits'] < 2)): failures.append('collision_hook_restore')
        for task in tasks: task.cancel()
        if tasks:
            try: await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 5)
            except BaseException: failures.append('stage_drain')
        supervisor._http = original_http
        cleanup_deadline = asyncio.get_running_loop().time() + 20
        async def close(name, action):
            try: await asyncio.wait_for(action(), max(.001, min(5, cleanup_deadline - asyncio.get_running_loop().time())))
            except BaseException: failures.append(name)
        for item in owned + writers + [observer] + resources + supervisor_resources + [supervisor]:
            action = getattr(item, 'close', None)
            if callable(action): await close(type(item).__name__, action)
        for resource in resources + supervisor_resources + [observer]:
            if resource._state != 'closed' or resource._users or resource._leases or not resource._driver_close_ok:
                failures.append('pool_close_verification')
        if supervisor._process is not None and supervisor._process.returncode is None: failures.append('process_close_verification')
        if endpoint is not None: await close('listener', lambda: observed_listener(endpoint, allow_absent=True))
        if failures:
            name = type(primary).__name__ if primary is not None else None
            raise NativePublicSecurityFailure(dict(ok=False, step=len(checks), error='cleanup_failed',
                primary=name if name in ERRORS else ('internal' if name else None), cleanup=failures)) from None
    if primary is not None:
        name = type(primary).__name__
        failure = NativePublicSecurityFailure(dict(ok=False, step=len(checks), error=name if name in ERRORS else 'internal'))
        failure.primary = primary
        raise failure from None
    checks.append(CHECKS[6]); rows.append(['cleanup', True])
    return dict(runtime='python', checks=checks, proof_scope=PROOF_SCOPE,
        semantic_witness_sha256=hashlib.sha256(request_bytes(['cragkit.qdrant.global-uuid.v1', rows])).hexdigest())
