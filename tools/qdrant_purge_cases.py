"""Shared native public purge fixtures and acceptance consumers."""
from __future__ import annotations

from copy import deepcopy
import re

CHECKS = (
    'published_retained_and_unknown_put_erased_with_claims_retained',
    'source_denied_before_and_after_managed_erasure',
    'completed_purge_retry_is_metadata_only',
    'lost_delete_ack_requires_actual_refence_before_erasure',
    'ordinary_purge_owner_handoff_resumes_without_guard_bypass',
    'lost_erasure_commit_confirms_exact_retained_history',
    'ownerless_tombstone_bootstrap_and_forged_receipt_refusal',
    'unknown_extra_or_foreign_scope_cannot_authorize_erasure',
)

POLICY = 'erase_managed_source_and_replay_v1'
COMPLETED = ('base', 'delete_loss', 'handoff', 'commit_loss', 'ownerless')


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
    return dict(config=seed['config'], instance_id=seed['instance_id'], scope=seed['scope'],
        collection_config=supervisor_input()['collection_config'], documents=documents)


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
    from cragkit._qdrant_writer import purge_projection_data, security_projection_data
    from cragkit._qdrant_security_verification import PurgeAbsenceReceipt, purge_absence_receipt_data
    from cragkit.qdrant_publication import (QdrantPublicationManager, QdrantSecurityManager,
        PostgresQdrantPublicationAuthority, ManagedQdrantPublicationTransport,
        PostgresQdrantWriter, PostgresQdrantRecovery, ManagedQdrantSupervisor,
        QdrantReconciliationVerifier)
    from qdrant_publication_manager_cases import ERRORS
    from qdrant_supervisor_cases import plain, request_bytes, observed_listener

    inputs = value['inputs']
    deadline = asyncio.get_running_loop().time() + 180
    checks, observations, requests, stores = [], [], [], []
    network = dict(count=0, mode=None, put_drops=0, delete_drops=0, deletes=[])
    database = dict(writes=0, bodies=0, mode=None, rollbacks=0, lost=0,
        confirming=False, confirmations=0, confirm_queries=0, confirm_http=0,
        confirm_bodies=0, confirm_writes=0, functions=0, guard_active=False)
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
            self.actual, self.erased, self.readonly = actual, False, False
        def __getattr__(self, name):
            return getattr(self.actual, name)
        def transaction(self, *args, **kwargs):
            transaction = self.actual.transaction(*args, **kwargs)
            connection = self
            class Transaction:
                async def __aenter__(self):
                    connection.erased = connection.readonly = False
                    return await transaction.__aenter__()
                async def __aexit__(self, kind, error, traceback):
                    result = await transaction.__aexit__(kind, error, traceback)
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
            cursor = await self.actual.execute(statement, params, **options)
            if type(statement) is str and statement.startswith('SELECT true FROM cragkit_qdrant.lock_current_security('):
                database['guard_active'] = True
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
    async def source(selected):
        base = documents['base']['stage']
        point = documents['base']['expected_points'][0]
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
        first = await purge(base['purge'])
        expected_ids = {member['point_id'] for stage in (base['stage'], base['second_stage']) for member in stage['manifest']['members']}
        if (supervisor.control_binding()['credential_generation'] == credential or network['put_drops'] != 1
                or set(point for batch in network['deletes'] for point in batch) != expected_ids):
            raise RuntimeError('purge_base_physical_fence')
        checks.append(CHECKS[0]); observations.append(row(first))
        _, after_source = await source(auth2); unavailable(after_source)
        checks.append(CHECKS[1]); observations.append(['source', 'verified', 'unavailable', 'unavailable'])
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
        checks.append(CHECKS[2]); observations.append(row(first))
        item = await setup('delete_loss'); await commit(item['tombstone'])
        network['mode'] = 'delete'
        await expect(ProviderUnavailable, lambda: purge(item['purge']))
        pending = await snapshot(item['purge'])
        credential = supervisor.control_binding()['credential_generation']
        if not pending['pending'] or pending['backend']['state'] != 'recovery_blocked' or pending['intent']['purge_complete']:
            raise RuntimeError('purge_delete_unknown_not_preserved')
        result = await purge(item['purge'])
        if supervisor.control_binding()['credential_generation'] == credential or network['delete_drops'] != 1:
            raise RuntimeError('purge_delete_retry_not_refenced')
        checks.append(CHECKS[3]); observations.append(row(result))
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
        result = await purge(item['purge'])
        if counts != (supervisor.control_binding()['credential_generation'], len(network['deletes'])):
            raise RuntimeError('purge_handoff_repeated_delete')
        checks.append(CHECKS[4]); observations.append(row(result))
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
        checks.append(CHECKS[5]); observations.append(row(result))
        item = await setup('ownerless'); await commit(item['tombstone'])
        denied = await writer.admit_publication(context(item['stage']), deadline=deadline)
        pending = await snapshot(item['stage'])
        if denied['intent']['state'] != 'denied' or pending['owner'] is not None:
            raise RuntimeError('purge_ownerless_prerequisite')
        result = await purge(item['purge'])
        checks.append(CHECKS[6]); observations.append(row(result))
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
        checks.append(CHECKS[7]); observations.append(['refusals', 'integrity_violation', 'unauthorized_scope', 'unsupported_capability'])
        witness = json.dumps(['cragkit.qdrant.managed-purge.v1', observations], ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        return dict(runtime='python', checks=checks, proof_scope='native_managed_purge_only', semantic_witness_sha256=hashlib.sha256(witness).hexdigest())
    except BaseException as error:
        primary = error
        name = type(error).__name__
        raise NativePurgeFailure(dict(ok=False, step=len(checks), error=name if name in ERRORS else 'internal'), primary=error) from None
    finally:
        writer.complete_purge = original_complete
        supervisor._http = original_http
        failures = []
        cleanup_deadline = asyncio.get_running_loop().time() + 12
        async def close(operation, function):
            try: await asyncio.wait_for(function(), max(.001, min(8, cleanup_deadline - asyncio.get_running_loop().time())))
            except BaseException: failures.append(operation)
        owned = [('source_request', item) for item in requests] + [('source_store', item) for item in stores]
        owned += [('manager', item) for item in (manager, security_manager) if item is not None]
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
