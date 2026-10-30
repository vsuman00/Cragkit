"""Shared native public purge fixtures and acceptance consumers."""
from __future__ import annotations

from copy import deepcopy
import re

CHECKS = (
    'tombstone_before_purge_denies_source_while_points_remain',
    'published_retained_and_unknown_put_erased_with_claims_retained',
    'source_denied_before_and_after_managed_erasure',
    'completed_purge_retry_is_metadata_only',
    'lost_delete_ack_requires_actual_refence_before_erasure',
    'interrupted_delete_keeps_purge_pending_until_recovery',
    'ordinary_purge_owner_handoff_resumes_without_guard_bypass',
    'lost_erasure_commit_confirms_exact_retained_history',
    'ownerless_tombstone_bootstrap_and_forged_receipt_refusal',
    'unknown_extra_or_foreign_scope_cannot_authorize_erasure',
)

POLICY = 'erase_managed_source_and_replay_v1'
COMPLETED = ('base', 'delete_loss', 'handoff', 'commit_loss', 'ownerless', 'authority_change', 'purge_interruption')
FAULT_CHECKS = (
    'current_credential_pending_delete_refused',
    'administrative_foreign_intent_pending_refused_and_restored',
    'replaced_owner_refused_before_erasure',
    'changed_authority_refused_before_erasure',
    'superseded_purge_handoff_commit_loss_resumes_without_mutation',
)

# This fixed, fixture-only SQL is never accepted by a product API. A temporary
# fourth client changes one already settled historical row, then restores it.
FOREIGN_FAULT_SQL = dict(
    select="SELECT dispatch_id,state,completion_sha256,encode(sha256(convert_to(row_to_json(j)::text,'UTF8')),'hex') "
        'FROM cragkit_qdrant.dispatch_journal j WHERE (tenant_id,collection,document_id,intent_id)=(?,?,?,?) ORDER BY sequence LIMIT 257',
    disable='ALTER TABLE cragkit_qdrant.dispatch_journal DISABLE TRIGGER publication_dispatch_guard',
    enable='ALTER TABLE cragkit_qdrant.dispatch_journal ENABLE TRIGGER publication_dispatch_guard',
    inject="UPDATE cragkit_qdrant.dispatch_journal SET state='unknown',completion_sha256=NULL "
        "WHERE (tenant_id,collection,document_id,intent_id,dispatch_id)=(?,?,?,?,?) AND state='settled' AND completion_sha256=? RETURNING dispatch_id",
    restore="UPDATE cragkit_qdrant.dispatch_journal SET state='settled',completion_sha256=? "
        "WHERE (tenant_id,collection,document_id,intent_id,dispatch_id)=(?,?,?,?,?) AND state='unknown' AND completion_sha256 IS NULL RETURNING dispatch_id",
    trigger="SELECT tgenabled FROM pg_catalog.pg_trigger WHERE tgrelid='cragkit_qdrant.dispatch_journal'::regclass AND tgname='publication_dispatch_guard'",
)


def loads_managed_bodies(sql):
    selected = re.match(r'^\s*SELECT\s+(.+?)\s+FROM\s+cragkit_qdrant\.'
        r'(?:document_revisions|members|vector_replays|dispatch_journal)\b', sql, re.I | re.S)
    if selected is None:
        return False
    fields = re.sub(r'\b(?:canonical_utf8|dense_blob|sparse_blob|excerpt_utf8|request_bytes)\s+'
        r'IS\s+(?:NOT\s+)?NULL\b', 'body_marker', selected[1], flags=re.I)
    return re.search(r'\b(?:canonical_utf8|dense_blob|sparse_blob|excerpt_utf8|request_bytes)\b', fields) is not None


class NativePurgeFailure(RuntimeError):
    def __init__(self, observation, primary=None):
        super().__init__('purge_native_case_failed')
        self.observation = observation
        self.primary = primary


def purge_input():
    from cragkit._qdrant_manifest import encode_security_intent
    from qdrant_security_guard_native import guard_inputs
    from qdrant_supervisor_cases import supervisor_input
    from qdrant_writer_cases import successor_stage

    documents = {}
    for name in (*COMPLETED, 'extra'):
        seed, _ = guard_inputs('purge-' + name)
        stage = seed['stage']
        authorization = deepcopy(stage['intent']['initial_authorization'])
        authorization.update(authorization_revision='auth-2', tombstoned=True)
        tombstone = dict(action='tombstone', intent_id='native-tombstone-' + name,
            tenant_id=seed['scope']['tenant_id'], collection=stage['manifest']['collection'],
            document_id=stage['manifest']['document_id'], expected_authorization_revision='auth-1',
            expected_mutation_epoch=1, authorization=authorization)
        purge = dict(intent_id='native-purge-' + name, tenant_id=tombstone['tenant_id'],
            collection=tombstone['collection'], document_id=tombstone['document_id'],
            tombstone_intent_payload_sha256=encode_security_intent(tombstone).sha256,
            expected_authorization_revision='auth-2', expected_mutation_epoch=2)
        documents[name] = dict(stage=stage,
            second_stage=successor_stage(seed, 'purge-' + name + '-retained', stage['manifest']['generation_id']),
            expected_points=seed['expected_points'], tombstone=tombstone, purge=purge)
        if name == 'delete_loss':
            documents[name]['published_second'] = True
        if name == 'authority_change':
            changed = deepcopy(tombstone)
            changed.update(intent_id=tombstone['intent_id']+'-auth3',
                expected_authorization_revision='auth-2', expected_mutation_epoch=2)
            changed['authorization']['authorization_revision'] = 'auth-3'
            documents[name].update(followup_tombstone=changed, followup_purge=dict(purge,
                intent_id=purge['intent_id']+'-auth3', expected_authorization_revision='auth-3',
                expected_mutation_epoch=3, tombstone_intent_payload_sha256=encode_security_intent(changed).sha256))
    return dict(config=seed['config'], instance_id=seed['instance_id'], scope=seed['scope'],
        collection_config=supervisor_input()['collection_config'], documents=documents,
        foreign_fault_sql=deepcopy(FOREIGN_FAULT_SQL))


async def python_purge_cases(value):
    import asyncio
    import hashlib
    import json
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig, PoolResource, _owned_pool
    from cragkit.contracts import Limits, TrustedScope
    from cragkit.execution import ExecutionLedger
    from cragkit.errors import (ProviderUnavailable, IntegrityViolation, InvalidRequest,
        UnauthorizedScope, UnsupportedCapability)
    from cragkit.qdrant import QdrantNomination
    from cragkit.qdrant_source import PostgresQdrantSourceStore
    from cragkit._qdrant_writer import purge_projection_data, security_projection_data, purge_dispatch_plan_data
    from cragkit._qdrant_security_verification import (PurgeAbsenceReceipt, purge_absence_receipt_data,
        QdrantSecurityVerifier)
    from cragkit._qdrant_recovery import settle_purge_guarded, _SECURITY_JOURNAL_COLUMNS
    from cragkit.qdrant_publication import (QdrantPublicationManager, QdrantSecurityManager,
        PostgresQdrantPublicationAuthority, ManagedQdrantPublicationTransport,
        PostgresQdrantWriter, PostgresQdrantRecovery, ManagedQdrantSupervisor,
        QdrantReconciliationVerifier)
    from qdrant_publication_manager_cases import ERRORS
    from qdrant_supervisor_cases import plain, request_bytes, observed_listener

    inputs = value['inputs']
    deadline = asyncio.get_running_loop().time() + 180
    checks, observations, requests, stores = [], [], [], []
    fault_checks, extra_verifiers = [], []
    settlement_probe = dict(active=False, foreign=[], owned=[], updates=0)
    network = dict(count=0, mode=None, put_drops=0, delete_drops=0, deletes=[])
    delete_interruption = dict(armed=False, entered=asyncio.Event(), cancelled=False)
    database = dict(writes=0, bodies=0, mode=None, rollbacks=0, lost=0,
        confirming=False, confirmations=0, confirm_queries=0, confirm_http=0,
        confirm_bodies=0, confirm_writes=0, functions=0, guard_active=False, handoff_lost=0)
    def configuration(raw):
        raw = dict(raw)
        for key in ('sslrootcert', 'passfile'):
            raw[key] = Path(raw[key])
        config = PoolConfig.model_validate(raw)
        if config.max_size != 1:
            raise RuntimeError('purge_pool_bound')
        return config
    class SettlementConnection:
        def __init__(self, actual):
            self.actual, self.erased, self.readonly, self.handoff = actual, False, False, False
        def __getattr__(self, name):
            return getattr(self.actual, name)
        def transaction(self, *args, **kwargs):
            transaction = self.actual.transaction(*args, **kwargs)
            connection = self
            class Transaction:
                async def __aenter__(self):
                    connection.erased = connection.readonly = connection.handoff = False
                    return await transaction.__aenter__()
                async def __aexit__(self, kind, error, traceback):
                    result = await transaction.__aexit__(kind, error, traceback)
                    if connection.handoff and kind is None and database['mode'] == 'handoff_commit':
                        database.update(mode=None, handoff_lost=database['handoff_lost']+1)
                        lost = ConnectionError('native_purge_handoff_commit_reply_withheld')
                        lost.sqlstate = '08006'
                        raise lost
                    if connection.erased and kind is None and database['mode'] == 'commit':
                        database.update(mode=None, lost=database['lost'] + 1, confirming=True)
                        lost = ConnectionError('native_purge_commit_reply_withheld')
                        lost.sqlstate = '08006'
                        raise lost
                    if connection.readonly and database['confirming']:
                        database['confirming'] = False
                    return result
            return Transaction()
        async def execute(self, statement, params=None, **options):
            sql = statement if type(statement) is str else ''
            if (database['guard_active'] and sql.startswith('SELECT active_generation_id,authorization_revision')
                    and sql.endswith('FOR UPDATE')):
                raise RuntimeError('purge_guard_competing_document_lock')
            erase = sql.startswith('SELECT cragkit_qdrant.erase_purged_document(')
            write = erase or sql.startswith(('INSERT ', 'UPDATE ', 'DELETE '))
            bodies = loads_managed_bodies(sql)
            database['writes'] += int(write)
            database['bodies'] += int(bodies)
            if database['confirming']:
                database['confirm_queries'] += 1
                database['confirm_writes'] += int(write)
                database['confirm_bodies'] += int(bodies)
            if sql.endswith('READ COMMITTED READ ONLY') or sql == 'SET TRANSACTION READ ONLY':
                self.readonly = True
                if database['confirming']:
                    database['confirmations'] += 1
            cursor = await self.actual.execute(statement, params, **options)
            if database['mode']=='handoff_commit' and sql.startswith(('UPDATE cragkit_qdrant.document_owners ',
                    'INSERT INTO cragkit_qdrant.document_owners ')):
                self.handoff = True
            if erase:
                database['functions'] += 1
                self.erased = True
                if database['mode'] == 'rollback':
                    database.update(mode=None, rollbacks=database['rollbacks'] + 1)
                    raise IntegrityViolation()
            return cursor
    class SettlementPool:
        def __init__(self, config): self.actual = _owned_pool(config)
        def __getattr__(self, name): return getattr(self.actual, name)
        async def getconn(self, **options):
            return SettlementConnection(await self.actual.getconn(**options))
        async def putconn(self, connection): await self.actual.putconn(connection.actual)

    class GuardConnection:
        def __init__(self, actual): self.actual = actual
        def __getattr__(self, name): return getattr(self.actual, name)
        def transaction(self, *args, **kwargs):
            transaction = self.actual.transaction(*args, **kwargs)
            class Transaction:
                async def __aenter__(self): return await transaction.__aenter__()
                async def __aexit__(self, kind, error, trace):
                    try: return await transaction.__aexit__(kind, error, trace)
                    finally: database['guard_active'] = False
            return Transaction()
        async def execute(self, statement, params=None, **options):
            if type(statement) is str and statement.startswith('UPDATE cragkit_qdrant.dispatch_journal'):
                settlement_probe['updates'] += 1
            cursor = await self.actual.execute(statement, params, **options)
            if type(statement) is str and statement.startswith('SELECT true FROM cragkit_qdrant.lock_current_security('):
                database['guard_active'] = True
            if settlement_probe['active'] and type(statement) is str:
                kind = ('foreign' if statement.startswith('SELECT 1 FROM cragkit_qdrant.dispatch_journal')
                    and 'intent_id<>' in statement else 'owned' if statement.startswith('SELECT '+_SECURITY_JOURNAL_COLUMNS) else None)
                if kind is not None:
                    actual = cursor
                    class ObservedCursor:
                        async def fetchall(self):
                            rows = await actual.fetchall()
                            settlement_probe[kind].append(rows)
                            return rows
                    return ObservedCursor()
            return cursor

    class GuardPool(SettlementPool):
        async def getconn(self, **options):
            return GuardConnection(await self.actual.getconn(**options))

    resource = PoolResource(configuration(value['writer_config']), factory=SettlementPool)
    supervisor_resource = PoolResource(configuration(value['supervisor_config']), factory=GuardPool)
    reader = PoolResource(configuration(value['reader_config']))
    supervisor = ManagedQdrantSupervisor(Path(value['binary']), Path(value['work_dir']),
        inputs['instance_id'], inputs['config'])
    writer = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
    verifier = QdrantReconciliationVerifier(writer, supervisor)
    recovery = PostgresQdrantRecovery(supervisor_resource, inputs['config'], supervisor, verifier)
    authority = PostgresQdrantPublicationAuthority(writer, recovery)
    transport = ManagedQdrantPublicationTransport(supervisor)
    scope = TrustedScope.model_validate(inputs['scope'])
    auth2 = TrustedScope.model_validate(dict(inputs['scope'], authorization_revision='auth-2'))
    documents = inputs['documents']
    collection = documents['base']['stage']['manifest']['collection']
    document_ids = {item['stage']['manifest']['document_id'] for item in documents.values()}
    target = '/collections/' + inputs['config']['physical_collection']
    manager = security_manager = endpoint = primary = None
    original_http = supervisor._http
    original_complete = writer.complete_purge
    original_recover = recovery.recover
    recovered = {}
    async def captured_recover(*args, **options):
        proof = await original_recover(*args, **options)
        recovered['proof'] = proof
        return proof
    recovery.recover = captured_recover
    token = '00000000-0000-4000-8000-000000000099'
    def reference(item):
        if 'manifest' in item:
            return dict(collection=item['manifest']['collection'], document_id=item['manifest']['document_id'],
                intent_id=item['intent']['intent_id'])
        return {key: item[key] for key in ('collection', 'document_id', 'intent_id')}
    def context(item, selected=auth2):
        return dict(**reference(item), scope=selected, owner_token=token)
    async def snapshot(item, selected=auth2):
        return await writer.manager_snapshot(context(item, selected), deadline=deadline)
    async def permitted(selected, selected_collection, selected_document):
        return selected.tenant_id == scope.tenant_id and selected_collection == collection and selected_document in document_ids
    async def call(method, item, selected=scope, **kwargs):
        ledger = ExecutionLedger(Limits(deadline_ms=180000, max_provider_calls=0), deadline=deadline)
        try:
            return await method(item, selected, ledger, deadline=deadline, **kwargs)
        finally:
            usage = ledger.snapshot()
            if (usage['attempts'], usage['provider_calls'], usage['pending']) != (1, 0, 0):
                raise RuntimeError('purge_usage')
    async def purge(item, selected=auth2):
        result = plain(await call(manager.purge, item, selected, retention_policy=POLICY))
        if (len(result) != 9 or result['operation'] != 'purge' or result['state'] != 'complete'
                or not all(result[key] for key in ('authority_committed', 'replica_complete', 'purge_complete'))
                or result['published']):
            raise RuntimeError('purge_result_flags')
        return result
    def row(result):
        return [result[key] for key in ('intent_id', 'operation', 'state', 'authority_committed', 'replica_complete', 'purge_complete')]
    async def expect(kind, operation):
        try: await operation()
        except kind: return
        raise RuntimeError('purge_expected_refusal')
    async def commit(item, selected=scope):
        result = plain(await call(security_manager.tombstone, item, selected))
        if not result['authority_committed'] or result['purge_complete']:
            raise RuntimeError('purge_tombstone_flags')
    async def setup(name):
        item = documents[name]
        await call(manager.stage, item['stage'])
        if name != 'ownerless':
            published = plain(await call(manager.publish, reference(item['stage'])))
            if not published['published']: raise RuntimeError('purge_setup_publish')
            await call(manager.stage, item['second_stage'])
            if item.get('published_second'):
                result = plain(await call(manager.publish, reference(item['second_stage'])))
                if not result['published']: raise RuntimeError('purge_setup_second_publish')
        return item
    async def observed_http(*args, **kwargs):
        network['count'] += 1
        if database['confirming']: database['confirm_http'] += 1
        result = await original_http(*args, **kwargs)
        if len(args) > 3:
            method, path, body = args[1:4]
            kind = 'put' if method == 'PUT' and path == target + '/points?wait=true&ordering=strong' else (
                'delete' if method == 'POST' and path == target + '/points/delete?wait=true&ordering=strong' else None)
            if kind == 'delete':
                network['deletes'].append(json.loads(body)['points'])
                if delete_interruption['armed']:
                    status, raw = result
                    response = json.loads(raw)
                    if (status != 200 or response.get('status') != 'ok'
                            or response.get('result', {}).get('status') != 'completed'):
                        raise RuntimeError('purge_interruption_not_dispatched')
                    delete_interruption['armed'] = False
                    delete_interruption['entered'].set()
                    try:
                        # The actual response exists, but no managed caller has
                        # received it or settled this dispatched deletion.
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        delete_interruption['cancelled'] = True
                        raise
            if kind is not None and network['mode'] == kind:
                status, raw = result
                response = json.loads(raw)
                if status != 200 or response.get('status') != 'ok' or response.get('result', {}).get('status') != 'completed':
                    raise RuntimeError('purge_fault_not_completed')
                network['mode'] = None
                network[kind + '_drops'] += 1
                raise ProviderUnavailable()
        return result
    async def provision(admin, probe):
        await admin.request('PUT', target, body=request_bytes(inputs['collection_config']), deadline=deadline)
        probe = plain(probe)
        path = '/collections/' + probe['collection']
        await admin.request('PUT', path, body=request_bytes(probe['collection_config']), deadline=deadline)
        await admin.request('PUT', path + '/points?wait=true&ordering=strong',
            body=request_bytes(dict(points=[probe['point']])), deadline=deadline)
    async def source(selected, item=None):
        item = documents['base'] if item is None else item
        base = item['stage']
        point = item['expected_points'][0]
        nomination = QdrantNomination.model_validate(dict(point_id=point['id'], branch='dense', score=1.0,
            score_kind='cosine_similarity', payload=point['payload']))
        store = PostgresQdrantSourceStore(reader, inputs['config']); stores.append(store)
        await store.initialize(deadline=deadline)
        request = store.open_request(dict(query='native purge verification', collection=collection), scope=selected, deadline=deadline)
        requests.append(request)
        fetched = await request.fetch_candidate(nomination, max_source_bytes=16777216, include_source=True)
        if fetched.state == 'verified':
            member = next(member for member in base['manifest']['members'] if member['point_id'] == point['id'])
            canonical = base['canonical_text'].encode('utf-8')
            excerpt = canonical[member['start_byte']:member['end_byte']]
            if (fetched.binding is None or fetched.evidence is None or fetched.private_source is None
                    or fetched.evidence.text != excerpt.decode('utf-8')
                    or fetched.evidence.source_sha256 != hashlib.sha256(canonical).hexdigest()
                    or fetched.evidence.text_sha256 != hashlib.sha256(excerpt).hexdigest()
                    or fetched.private_source.canonical_text != base['canonical_text']):
                raise RuntimeError('purge_source_fidelity')
        else: unavailable(fetched)
        return request, fetched
    def unavailable(fetched):
        if (fetched.state != 'unavailable' or fetched.binding is not None or fetched.evidence is not None
                or fetched.private_source is not None or fetched.source_bytes):
            raise RuntimeError('purge_source_disclosure')
    def graph(projection):
        data = purge_projection_data(projection, writer)
        result = dict(security_projection_data(data['projection'], writer))
        # Reprojection issues fresh nominal vectors; compare their bound contents.
        result['points'] = tuple((point.point_id, point.payload.model_dump(mode='json'),
            point.dense.profile.model_dump(mode='json'), point.dense.values,
            point.dense.sealed_bytes, point.dense.input_sha256,
            None if point.sparse is None else (point.sparse.profile.model_dump(mode='json'),
                point.sparse.indices, point.sparse.values, point.sparse.sealed_bytes,
                point.sparse.input_sha256)) for point in result['points'])
        return result
    async def content_unavailable(item):
        from cragkit._qdrant_writer_contract import context as parse_context
        ctx = parse_context(context(item))
        async def read(connection):
            cursor = await connection.execute('SELECT content_unavailable FROM cragkit_qdrant.documents WHERE tenant_id=%s AND collection=%s AND document_id=%s',
                (scope.tenant_id, item['collection'], item['document_id']))
            rows = await cursor.fetchall()
            if rows not in ([(True,)], [(False,)]): raise RuntimeError('purge_marker_shape')
            return rows[0][0]
        return await writer._run(ctx, deadline, read, read_only=True)
    async def foreign_fault(key, saved=None):
        pool = _owned_pool(configuration(value['admin_config']))
        connection = None
        sql = inputs['foreign_fault_sql']
        def statement(name): return sql[name].replace('?', '%s')
        async def rows(name, params=()):
            return await (await connection.execute(statement(name), params)).fetchall()
        try:
            operation_deadline = asyncio.get_running_loop().time()+8 if saved is not None else deadline
            await pool.open(wait=True, timeout=max(.001, operation_deadline-asyncio.get_running_loop().time()))
            connection = await pool.getconn(timeout=max(.001, operation_deadline-asyncio.get_running_loop().time()))
            async with connection.transaction():
                await connection.execute('SET LOCAL statement_timeout=8000')
                current = await rows('select', key)
                if saved is None:
                    if not 1 <= len(current) <= 256 or any(row[1]!='settled' or not row[2] for row in current):
                        raise RuntimeError('purge_foreign_fixture_shape')
                    saved = current
                    params = (*key,saved[0][0],saved[0][2])
                    operation = 'inject'
                else:
                    params = (saved[0][2],*key,saved[0][0])
                    operation = 'restore'
                await connection.execute(statement('disable'))
                if await rows(operation,params) != [(saved[0][0],)]:
                    raise RuntimeError('purge_foreign_fixture_update')
                await connection.execute(statement('enable'))
                if await rows('trigger') != [('O',)]:
                    raise RuntimeError('purge_foreign_trigger_not_restored')
                if operation=='restore' and await rows('select',key) != saved:
                    raise RuntimeError('purge_foreign_history_not_restored')
            return saved
        finally:
            if connection is not None: await pool.putconn(connection)
            await pool.close(timeout=3)
    try:
        supervisor._http = observed_http
        await supervisor.initialize(deadline=deadline, provision=provision)
        endpoint = supervisor.identity()['endpoint']; await observed_listener(endpoint)
        await resource.open(); await supervisor_resource.open(); await reader.open()
        manager = QdrantPublicationManager(authority, transport, inputs['config'], supervisor, permitted)
        security_manager = QdrantSecurityManager(writer, permitted)
        await manager.initialize(deadline=deadline); await security_manager.initialize(deadline=deadline)
        base = await setup('base')
        retained_request, fetched = await source(scope)
        if fetched.state != 'verified': raise RuntimeError('purge_source_initial')
        network['mode'] = 'put'
        await expect(ProviderUnavailable, lambda: call(manager.publish, reference(base['second_stage'])))
        pending = await snapshot(base['second_stage'], scope)
        if not pending['pending'] or pending['document']['active_generation_id'] != base['stage']['manifest']['generation_id']:
            raise RuntimeError('purge_unknown_put_missing')
        credential = supervisor.control_binding()['credential_generation']
        await commit(base['tombstone'])
        released = await retained_request.release(fetched.binding, purpose='final', max_source_bytes=16777216, include_source=True)
        unavailable(released)
        _, before_source = await source(auth2); unavailable(before_source)
        expected_ids = {member['point_id'] for stage in (base['stage'], base['second_stage']) for member in stage['manifest']['members']}
        tombstoned = await snapshot(base['tombstone'])
        if (tombstoned['document'] != dict(active_generation_id=base['stage']['manifest']['generation_id'],
                authorization_revision='auth-2', mutation_epoch=2, tombstoned=True)
                or tombstoned['intent']['action'] != 'tombstone'
                or tombstoned['intent']['state'] != 'authority_committed'
                or not tombstoned['intent']['authority_committed']
                or tombstoned['intent']['replica_complete'] or tombstoned['intent']['purge_complete']
                or not tombstoned['pending'] or (await snapshot(base['purge']))['intent'] is not None
                or await content_unavailable(base['purge'])):
            raise RuntimeError('purge_tombstone_before_purge_authority')
        manifest = base['stage']['manifest']
        fields = ('backend_namespace', 'physical_collection', 'collection_incarnation',
            'tenant_id', 'collection', 'document_id')
        filters = dict(must=[dict(key=field, match=dict(value=manifest[field])) for field in fields])
        capability = supervisor.issue_attempt(dict(intent_id='native-tombstone-before-purge', owner_token=token,
            epoch=supervisor.control_binding()['epoch'], dispatch_id='native-tombstone-before-purge'), deadline=deadline)
        probe = supervisor.transport_for(capability)
        try:
            physical = json.loads(bytes(await probe.request('POST', target + '/points/scroll',
                body=request_bytes(dict(filter=filters, limit=8, with_payload=True, with_vector=False)), deadline=deadline)))
            result = physical.get('result', {})
            points = result.get('points', [])
            if (physical.get('status') != 'ok' or len(expected_ids) != 4 or len(points) != len(expected_ids)
                    or {point['id'] for point in points} != expected_ids
                    or result.get('next_page_offset', 'missing') is not None
                    or any(point['payload'].get(field) != manifest[field] for point in points for field in fields)):
                raise RuntimeError('purge_tombstone_before_purge_points')
        finally:
            await probe.close()
        denied = await writer.admit_publication(context(base['second_stage']), deadline=deadline)
        if (denied['intent']['state'] != 'denied'
                or (await snapshot(base['tombstone']))['document'] != tombstoned['document']):
            raise RuntimeError('purge_tombstone_before_purge_publication')
        checks.append(CHECKS[0])
        observations.append(['tombstone_before_purge', 'unavailable', 'unavailable', len(expected_ids),
            True, False, True, 'denied'])
        first = await purge(base['purge'])
        if (supervisor.control_binding()['credential_generation'] == credential or network['put_drops'] != 1
                or set(point for batch in network['deletes'] for point in batch) != expected_ids):
            raise RuntimeError('purge_base_physical_fence')
        checks.append(CHECKS[1]); observations.append(row(first))
        _, after_source = await source(auth2); unavailable(after_source)
        checks.append(CHECKS[2]); observations.append(['source', 'verified', 'unavailable', 'unavailable'])
        counts = (network['count'], database['writes'], database['bodies'])
        if await purge(base['purge']) != first or counts != (network['count'], database['writes'], database['bodies']):
            raise RuntimeError('purge_retry_not_metadata_only')
        newer = deepcopy(base['tombstone'])
        newer.update(intent_id='native-tombstone-base-newer', expected_authorization_revision='auth-2', expected_mutation_epoch=2)
        newer['authorization']['authorization_revision'] = 'auth-3'
        await commit(newer, auth2)
        auth3 = TrustedScope.model_validate(dict(inputs['scope'], authorization_revision='auth-3'))
        counts = (network['count'], database['writes'], database['bodies'])
        if await purge(base['purge'], auth3) != first or counts != (network['count'], database['writes'], database['bodies']):
            raise RuntimeError('purge_retry_new_authority_not_metadata_only')
        checks.append(CHECKS[3]); observations.append(row(first))
        item = await setup('delete_loss'); await commit(item['tombstone'])
        network['mode'] = 'delete'
        await expect(ProviderUnavailable, lambda: purge(item['purge']))
        pending = await snapshot(item['purge'])
        credential = supervisor.control_binding()['credential_generation']
        if not pending['pending'] or pending['backend']['state'] != 'recovery_blocked' or pending['intent']['purge_complete']:
            raise RuntimeError('purge_delete_unknown_not_preserved')
        old_owner = dict(context(item['purge']), intent_id=pending['owner']['intent_id'],
            owner_token=pending['owner']['owner_token'])
        projection = await writer.project_purge(context(item['purge']), POLICY, deadline=deadline)
        fault_verifier = QdrantSecurityVerifier(writer,supervisor)
        extra_verifiers.append(fault_verifier)
        async def refused_settlement():
            return await settle_purge_guarded(recovery,fault_verifier,recovered['proof'],old_owner,
                projection,deadline=deadline)
        functions = database['functions']
        before_graph, updates = graph(projection), settlement_probe['updates']
        settlement_probe.update(active=True,foreign=[],owned=[])
        await expect(ProviderUnavailable,refused_settlement)
        settlement_probe['active'] = False
        if (not settlement_probe['owned'] or not any(row[5]==credential and row[10]!='settled'
                for group in settlement_probe['owned'] for row in group)
                or await snapshot(item['purge']) != pending or database['functions']!=functions
                or await content_unavailable(item['purge'])
                or supervisor.control_binding()['credential_generation']!=credential
                or settlement_probe['updates']!=updates
                or graph(await writer.project_purge(context(item['purge']),POLICY,deadline=deadline))!=before_graph):
            raise RuntimeError('purge_current_credential_refusal_missing')
        fault_checks.append(FAULT_CHECKS[0])
        manifest = item['stage']['manifest']
        key = tuple(manifest[field] for field in ('tenant_id','collection','document_id'))+(item['stage']['intent']['intent_id'],)
        saved = await foreign_fault(key)
        try:
            corrupted = await snapshot(item['purge'])
            settlement_probe.update(active=True,foreign=[],owned=[])
            await expect(ProviderUnavailable,refused_settlement)
            settlement_probe['active'] = False
            if (not any(settlement_probe['foreign']) or settlement_probe['owned']
                    or await snapshot(item['purge'])!=corrupted or database['functions']!=functions
                    or await content_unavailable(item['purge'])
                    or supervisor.control_binding()['credential_generation']!=credential
                    or settlement_probe['updates']!=updates
                    or graph(await writer.project_purge(context(item['purge']),POLICY,deadline=deadline))!=before_graph):
                raise RuntimeError('purge_foreign_pending_refusal_missing')
        finally:
            settlement_probe['active'] = False
            await foreign_fault(key,saved)
        if await snapshot(item['purge'])!=pending:
            raise RuntimeError('purge_foreign_pending_not_restored')
        fault_checks.append(FAULT_CHECKS[1])
        result = await purge(item['purge'])
        if supervisor.control_binding()['credential_generation'] == credential or network['delete_drops'] != 1:
            raise RuntimeError('purge_delete_retry_not_refenced')
        checks.append(CHECKS[4]); observations.append(row(result))
        item = await setup('purge_interruption'); await commit(item['tombstone'])
        expected_ids = {member['point_id'] for stage in (item['stage'], item['second_stage'])
            for member in stage['manifest']['members']}
        original_plan = writer.project_purge_dispatch
        interrupted_dispatch = {}
        async def capture_plan(authorization, point_ids, **options):
            plan = await original_plan(authorization, point_ids, **options)
            data = purge_dispatch_plan_data(plan, authorization, writer, deadline=options['deadline'])
            interrupted_dispatch.update(context=data['context'], dispatch_id=data['attempt_binding']['dispatch_id'],
                purge_context=purge_projection_data(data['projection'], writer)['context'],
                graph=graph(data['projection']))
            return plan
        writer.project_purge_dispatch = capture_plan
        functions, deletes = database['functions'], len(network['deletes'])
        delete_interruption['armed'] = True
        interrupted = asyncio.create_task(purge(item['purge']))
        try:
            await asyncio.wait_for(delete_interruption['entered'].wait(),
                max(.001, deadline-asyncio.get_running_loop().time()))
            interrupted.cancel()
            await expect(asyncio.CancelledError, lambda: interrupted)
        finally:
            delete_interruption['armed'] = False
            if not interrupted.done(): interrupted.cancel()
            await asyncio.gather(interrupted, return_exceptions=True)
            writer.project_purge_dispatch = original_plan
        pending = await snapshot(item['purge'])
        credential = supervisor.control_binding()['credential_generation']
        current = interrupted_dispatch['purge_context']
        before_graph = interrupted_dispatch['graph']
        journal = await writer.dispatch_status(interrupted_dispatch['context'],
            interrupted_dispatch['dispatch_id'], deadline=deadline)
        if (not delete_interruption['cancelled'] or manager._active is not None
                or len(network['deletes']) != deletes+1
                or not pending['pending'] or pending['backend']['state'] != 'recovery_blocked'
                or not pending['document']['tombstoned']
                or pending['intent']['purge_complete'] or pending['intent']['replica_complete']
                or len(expected_ids) != 4 or set(before_graph['point_ids']) != expected_ids
                or journal is None or journal['operation'] != 'delete_points'
                or journal['state'] not in ('dispatched', 'unknown') or journal['completion_sha256'] is not None
                or database['functions'] != functions or await content_unavailable(item['purge'])
                or graph(await writer.project_purge(current, POLICY, deadline=deadline)) != before_graph):
            raise RuntimeError('purge_interruption_uncertainty_lost')
        replacement = dict(context(item['purge']), owner_token='00000000-0000-4000-8000-000000000003')
        await expect(ProviderUnavailable, lambda: writer.acquire_owner(replacement, deadline=deadline))
        if (await snapshot(item['purge']) != pending
                or graph(await writer.project_purge(current, POLICY, deadline=deadline)) != before_graph):
            raise RuntimeError('purge_interruption_early_claim_reuse')
        _, denied = await source(auth2, item); unavailable(denied)
        result = await purge(item['purge'])
        completed = await snapshot(item['purge'])
        if (supervisor.control_binding()['credential_generation'] == credential
                or completed['pending'] or completed['backend']['state'] != 'open'
                or not await content_unavailable(item['purge'])
                or database['functions'] != functions+1):
            raise RuntimeError('purge_interruption_recovery_missing')
        manifest = item['stage']['manifest']
        filters = dict(must=[dict(key=field, match=dict(value=manifest[field])) for field in fields])
        capability = supervisor.issue_attempt(dict(intent_id='native-purge-interruption-absence', owner_token=token,
            epoch=supervisor.control_binding()['epoch'], dispatch_id='native-purge-interruption-absence'), deadline=deadline)
        probe = supervisor.transport_for(capability)
        try:
            physical = json.loads(bytes(await probe.request('POST', target + '/points/scroll',
                body=request_bytes(dict(filter=filters, limit=8, with_payload=True, with_vector=False)), deadline=deadline)))
            if (physical.get('status') != 'ok' or physical.get('result', {}).get('points') != []
                    or physical.get('result', {}).get('next_page_offset', 'missing') is not None):
                raise RuntimeError('purge_interruption_scoped_absence')
        finally:
            await probe.close()
        _, denied = await source(auth2, item); unavailable(denied)
        checks.append(CHECKS[5]); observations.append([
            'purge_interruption', 'aborted', 'recovery_blocked', True, True, 'unavailable', True, 0, 'complete'])
        item = await setup('handoff'); await commit(item['tombstone'])
        captured = {}
        async def interrupt(verifier, receipt, **options):
            captured.update(verifier=verifier, receipt=receipt)
            raise ProviderUnavailable()
        writer.complete_purge = interrupt
        await expect(ProviderUnavailable, lambda: purge(item['purge']))
        writer.complete_purge = original_complete
        pending = await snapshot(item['purge'])
        if pending['backend']['state'] != 'open' or pending['owner']['intent_id'] != item['purge']['intent_id'] or pending['pending']:
            raise RuntimeError('purge_handoff_not_open')
        current = dict(context(item['purge']), owner_token=pending['owner']['owner_token'])
        await writer.project_purge(current, POLICY, deadline=deadline)
        import copy
        import pickle
        for clone in (copy.copy, pickle.dumps):
            try: clone(captured['receipt'])
            except TypeError: pass
            else: raise RuntimeError('purge_receipt_serialized')
        writes = database['writes']
        await expect(InvalidRequest, lambda: original_complete(captured['verifier'], PurgeAbsenceReceipt(), deadline=deadline))
        await expect(InvalidRequest, lambda: original_complete(object(), captured['receipt'], deadline=deadline))
        await expect(InvalidRequest, lambda: original_complete(captured['verifier'], captured['receipt'], deadline=deadline))
        if writes != database['writes']: raise RuntimeError('purge_forgery_dml')
        counts = (supervisor.control_binding()['credential_generation'], len(network['deletes']))
        entered, suppressed, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def held_completion(verifier, receipt, **options):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                suppressed.set()
                await release.wait()
            return await original_complete(verifier, receipt, **options)
        writer.complete_purge = held_completion
        functions = database['functions']
        cancelled = asyncio.create_task(purge(item['purge']))
        inner = None
        try:
            await asyncio.wait_for(entered.wait(), max(.001, deadline-asyncio.get_running_loop().time()))
            inner = manager._active
            if inner is None or inner.done():
                raise RuntimeError('purge_cancellation_callback_missing')
            cancelled.cancel()
            await asyncio.wait_for(suppressed.wait(), max(.001, deadline-asyncio.get_running_loop().time()))
            epoch = supervisor.control_binding()['epoch']
            async def competing_issue():
                supervisor.issue_attempt(dict(intent_id=current['intent_id'], owner_token=current['owner_token'],
                    epoch=epoch, dispatch_id='purge-forbidden-cancelled-finalization'), deadline=deadline)
            await expect(ProviderUnavailable, competing_issue)
            await expect(ProviderUnavailable, lambda: supervisor.recover(dict(
                recovery_id='purge-forbidden-cancelled-finalization', old_epoch=epoch, new_epoch=epoch+1), deadline=deadline))
            await expect(ProviderUnavailable, supervisor.close)
            if (release.is_set() or manager._active is not inner or inner.done()
                    or database['functions'] != functions or await content_unavailable(item['purge'])):
                raise RuntimeError('purge_cancelled_callback_custody_lost')
            release.set()
            await expect(asyncio.CancelledError, lambda: cancelled)
            await asyncio.gather(inner, return_exceptions=True)
            if (manager._active is not None or database['functions'] != functions
                    or await content_unavailable(item['purge'])):
                raise RuntimeError('purge_cancelled_callback_late_erasure')
        finally:
            release.set()
            await asyncio.gather(cancelled, *(() if inner is None else (inner,)), return_exceptions=True)
            writer.complete_purge = original_complete
        owner_changed = False
        async def changed_owner(verifier, receipt, **options):
            nonlocal owner_changed
            data = purge_absence_receipt_data(receipt,verifier,deadline=deadline)
            original_context = dict(context(item['purge']),owner_token=data['context'].owner_token)
            replacement = dict(original_context,owner_token='00000000-0000-4000-8000-000000000077')
            functions = database['functions']
            before_graph = graph(data['projection'])
            await writer.acquire_owner(replacement,deadline=deadline)
            owner_changed = True
            try:
                changed = await snapshot(item['purge'])
                if changed['owner']['owner_token']!=replacement['owner_token']:
                    raise RuntimeError('purge_owner_not_replaced')
                await expect(ProviderUnavailable,lambda: original_complete(verifier,receipt,**options))
                if (database['functions']!=functions or await content_unavailable(item['purge'])
                        or graph(await writer.project_purge(original_context,POLICY,deadline=deadline))!=before_graph):
                    raise RuntimeError('purge_changed_owner_erased')
            finally:
                await writer.acquire_owner(original_context,deadline=deadline)
            raise ProviderUnavailable()
        writer.complete_purge = changed_owner
        try:
            await expect(ProviderUnavailable,lambda: purge(item['purge']))
        finally:
            writer.complete_purge = original_complete
        if not owner_changed or (await snapshot(item['purge']))['owner']['owner_token']!=current['owner_token']:
            raise RuntimeError('purge_changed_owner_not_restored')
        fault_checks.append(FAULT_CHECKS[2])
        result = await purge(item['purge'])
        if counts != (supervisor.control_binding()['credential_generation'], len(network['deletes'])):
            raise RuntimeError('purge_handoff_repeated_delete')
        checks.append(CHECKS[6]); observations.append(row(result))
        item = await setup('commit_loss'); await commit(item['tombstone'])
        captured.clear()
        async def rollback_completion(verifier, receipt, **options):
            data = purge_absence_receipt_data(receipt, verifier, deadline=deadline)
            captured.update(context=data['context'], graph=graph(data['projection']))
            return await original_complete(verifier, receipt, **options)
        writer.complete_purge = rollback_completion
        database['mode'] = 'rollback'
        await expect(IntegrityViolation, lambda: purge(item['purge']))
        writer.complete_purge = original_complete
        restored = graph(await writer.project_purge(captured['context'], POLICY, deadline=deadline))
        if database['rollbacks'] != 1:
            raise RuntimeError('purge_rollback_not_injected')
        if restored != captured['graph']:
            raise RuntimeError('purge_rollback_graph_changed')
        database['mode'] = 'commit'
        result = await purge(item['purge'])
        if (database['lost'] != 1 or database['confirmations'] != 1 or not database['confirm_queries']
                or database['confirm_http'] or database['confirm_bodies'] or database['confirm_writes'] or database['confirming']):
            raise RuntimeError('purge_commit_confirmation_not_readonly')
        checks.append(CHECKS[7]); observations.append(row(result))
        item = await setup('ownerless'); await commit(item['tombstone'])
        denied = await writer.admit_publication(context(item['stage']), deadline=deadline)
        pending = await snapshot(item['stage'])
        if denied['intent']['state'] != 'denied' or pending['owner'] is not None:
            raise RuntimeError('purge_ownerless_prerequisite')
        result = await purge(item['purge'])
        checks.append(CHECKS[8]); observations.append(row(result))
        item = await setup('authority_change'); await commit(item['tombstone'])
        functions = database['functions']
        async def changed_authority(verifier,receipt,**options):
            await commit(item['followup_tombstone'],auth2)
            return await original_complete(verifier,receipt,**options)
        writer.complete_purge = changed_authority
        try:
            await expect(UnauthorizedScope,lambda: purge(item['purge']))
        finally:
            writer.complete_purge = original_complete
        stale = await snapshot(item['purge'],auth3)
        if (stale['document']['authorization_revision']!='auth-3'
                or stale['intent']['replica_complete'] or stale['intent']['purge_complete']
                or database['functions']!=functions or await content_unavailable(item['purge'])):
            raise RuntimeError('purge_changed_authority_erased')
        before_handoff = (database['functions'],len(network['deletes']))
        database['mode'] = 'handoff_commit'
        await expect(ProviderUnavailable,lambda: purge(item['followup_purge'],auth3))
        after_handoff = await snapshot(item['followup_purge'],auth3)
        if (database['handoff_lost']!=1 or database['mode'] is not None
                or after_handoff['owner']['intent_id']!=item['followup_purge']['intent_id']
                or after_handoff['intent']['state']!='writing'
                or after_handoff['intent']['purge_complete']
                or before_handoff!=(database['functions'],len(network['deletes']))
                or await content_unavailable(item['purge'])):
            raise RuntimeError('purge_handoff_lost_reply_mutated')
        await purge(item['followup_purge'],auth3)
        if len(network['deletes'])!=before_handoff[1] or database['functions']!=before_handoff[0]+1:
            raise RuntimeError('purge_handoff_retry_repeated_delete')
        stale = await snapshot(item['purge'],auth3)
        if stale['intent']['replica_complete'] or stale['intent']['purge_complete']:
            raise RuntimeError('purge_stale_authority_completed')
        fault_checks.append(FAULT_CHECKS[3])
        fault_checks.append(FAULT_CHECKS[4])
        item = await setup('extra')
        extra = deepcopy(item['expected_points'][0]); extra['id'] = '00000000-0000-4000-8000-000000000088'
        capability = supervisor.issue_attempt(dict(intent_id='native-extra-point', owner_token=token,
            epoch=supervisor.control_binding()['epoch'], dispatch_id='native-extra-point'), deadline=deadline)
        handle = supervisor.transport_for(capability)
        await handle.request('PUT', target + '/points?wait=true&ordering=strong', body=request_bytes(dict(points=[extra])), deadline=deadline)
        await commit(item['tombstone'])
        await expect(IntegrityViolation, lambda: purge(item['purge']))
        pending = await snapshot(item['purge'])
        if pending['intent']['purge_complete'] or await content_unavailable(item['purge']) or any(extra['id'] in batch for batch in network['deletes']):
            raise RuntimeError('purge_unknown_extra_erased')
        foreign = dict(item['purge'], tenant_id='foreign-tenant')
        counts = (network['count'], database['writes'])
        # These two refusals precede ledger admission by contract.
        await expect(UnauthorizedScope, lambda: manager.purge(foreign, auth2,
            ExecutionLedger(Limits(max_provider_calls=0), deadline=deadline), retention_policy=POLICY, deadline=deadline))
        await expect(UnsupportedCapability, lambda: manager.purge(item['purge'], auth2,
            ExecutionLedger(Limits(max_provider_calls=0), deadline=deadline), retention_policy='unsupported', deadline=deadline))
        if counts != (network['count'], database['writes']): raise RuntimeError('purge_refusal_mutated')
        checks.append(CHECKS[9]); observations.append(['refusals', 'integrity_violation', 'unauthorized_scope', 'unsupported_capability'])
        if tuple(fault_checks)!=FAULT_CHECKS:
            raise RuntimeError('purge_fault_checks_missing')
        witness = json.dumps(['cragkit.qdrant.managed-purge.v2', observations, fault_checks], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return dict(runtime='python', checks=checks, fault_checks=fault_checks,
            proof_scope='native_managed_purge_only', semantic_witness_sha256=hashlib.sha256(witness).hexdigest())
    except BaseException as error:
        primary = error
        name = type(error).__name__
        raise NativePurgeFailure(dict(ok=False, step=len(checks), error=name if name in ERRORS else 'internal'), primary=error) from None
    finally:
        writer.complete_purge = original_complete
        recovery.recover = original_recover
        supervisor._http = original_http
        failures = []
        cleanup_deadline = asyncio.get_running_loop().time() + 12
        async def close(operation, function):
            try: await asyncio.wait_for(function(), max(.001, min(8, cleanup_deadline - asyncio.get_running_loop().time())))
            except BaseException: failures.append(operation)
        owned = [('source_request', item) for item in requests] + [('source_store', item) for item in stores]
        owned += [('manager', item) for item in (manager, security_manager) if item is not None]
        owned += [('fault_verifier',item) for item in extra_verifiers]
        owned += [('transport', transport), ('authority', authority), ('recovery', recovery), ('verifier', verifier),
            ('writer', writer), ('reader_pool', reader), ('writer_pool', resource), ('supervisor_pool', supervisor_resource), ('supervisor', supervisor)]
        for operation, item in owned:
            if callable(getattr(item, 'close', None)): await close(operation, item.close)
        if any(not item._closed or item._bindings or item._pending for item in requests): failures.append('source_request_close')
        if any(not item._closed or item._handle is not None for item in stores): failures.append('source_store_close')
        for pool in (reader, resource, supervisor_resource):
            if pool._state != 'closed' or pool._users or pool._leases or not pool._driver_close_ok: failures.append('pool_close')
        if supervisor._process is not None and supervisor._process.returncode is None: failures.append('process_close')
        if endpoint is not None:
            async def listener(): await observed_listener(endpoint, allow_absent=True)
            await close('listener', listener)
        if failures:
            raise NativePurgeFailure(dict(ok=False, step=len(checks), error='internal'), primary=primary) from None
