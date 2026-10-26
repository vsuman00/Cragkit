"""Native E2b inputs and observations, separate from the full H fault matrix."""
from __future__ import annotations

from copy import deepcopy
import asyncio
from contextlib import asynccontextmanager
from hashlib import sha256
import json
from pathlib import Path

from qdrant_supervisor_cases import supervisor_input, request_bytes, plain, observed_listener, old_key_mutation_status
from qdrant_writer_cases import writer_input, OWNER_TOKEN
from runtime_diagnostics import CleanupFailure

CHECKS = (
    'actual_native_instance_registered_with_restricted_supervisor_login',
    'two_documents_have_real_journaled_writes_with_lost_acknowledgments',
    'durable_instance_block_commits_before_actual_physical_fencing',
    'captured_old_key_is_denied_after_same_storage_restart',
    'recovery_owner_advance_preserves_exact_token_and_rejects_wrong_owner',
    'copied_receipt_cannot_authorize_sql_settlement',
    'retired_readback_settles_only_the_authorized_document',
    'another_document_uncertainty_keeps_sql_and_native_admission_closed',
    'same_recovery_identity_refences_without_advancing_blocked_sql_epoch',
    'second_authorized_document_settles_without_invented_scope',
    'actual_current_generation_write_remains_unknown_in_durable_journal',
    'current_generation_readback_cannot_clear_a_possible_late_write',
    'current_generation_uncertainty_prevents_reopening',
    'another_actual_same_identity_fence_retires_the_unknown_generation',
    'retired_settlement_retry_is_idempotent',
    'shared_supervisor_session_blocks_competing_coordinator_and_raw_mutations',
    'released_session_allows_same_identity_refence_and_manager_handoff',
    'actual_sql_open_commit_lost_ack_reconciles_with_native_gate_sealed',
    'private_sql_handoff_resumes_actual_ordinary_reads_at_current_epoch',
    'next_recovery_identity_advances_a_fresh_epoch_and_reopens_privately',
    'recovery_never_publishes_or_marks_replica_completion',
)
ERRORS = frozenset(('IntegrityViolation', 'UnauthorizedScope', 'IndexNotReady', 'InvalidRequest',
    'ProviderUnavailable', 'UnsupportedCapability', 'DeadlineExceeded', 'internal'))


class NativeRecoveryFailure(RuntimeError):
    def __init__(self, observation):
        super().__init__('recovery_native_case_failed')
        self.observation = observation


def recovery_input():
    from cragkit._qdrant_contract import point_id
    from cragkit._qdrant_manifest import encode_manifest
    value = writer_input()
    value['collection_config'] = supervisor_input()['collection_config']
    stage = deepcopy(value['stage'])
    manifest = stage['manifest']
    manifest.update(tenant_id='tenant-e2b-other', document_id='doc-e2b-other',
        revision_id='rev-e2b-other', generation_id='gen-e2b-other')
    for member in manifest['members']:
        member['point_id'] = point_id(['cragkit.qdrant.point.v1', manifest['backend_namespace'],
            manifest['physical_collection'], manifest['collection_incarnation'], manifest['tenant_id'],
            manifest['collection'], manifest['document_id'], manifest['revision_id'], manifest['generation_id'],
            member['chunk_id'], manifest['dense_profile']['profile_id'], manifest['sparse_profile']['profile_id']])
    stage['intent'].update(tenant_id=manifest['tenant_id'], document_id=manifest['document_id'],
        intent_id='intent-e2b-other', manifest_sha256=encode_manifest(manifest, stage['canonical_text']).sha256)
    points = deepcopy(value['expected_points'])
    for point, member in zip(points, manifest['members'], strict=True):
        point['id'] = member['point_id']
        point['payload'].update({key: manifest[key] for key in
            ('tenant_id', 'document_id', 'revision_id', 'generation_id')})
    value.update(second_stage=stage, second_scope=dict(value['scope'], tenant_id=manifest['tenant_id']),
        second_points=points)
    return value


class _Rows:
    def __init__(self, cursor, rows):
        self._cursor, self._rows = cursor, rows

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    async def fetchall(self):
        rows, self._rows = self._rows, []
        return rows


class _AckConnection:
    """Actual driver connection; only a committed acknowledgment is withheld."""
    def __init__(self, connection, observations):
        self.connection, self.observations = connection, observations
        self.open_update = False

    def __getattr__(self, name):
        return getattr(self.connection, name)

    async def execute(self, statement, params=(), **options):
        self.observations['sql_calls'] += 1
        cursor = await self.connection.execute(statement, params, **options)
        if type(statement) is str and "UPDATE cragkit_qdrant.backend_instances SET state='open'" in statement:
            self.open_update = True
            if self.observations['armed'] or self.observations['fired']:
                self.observations['open_updates'] += 1
        if (self.observations['fired'] and type(statement) is str
                and statement.startswith('SELECT backend_namespace,storage_identity,supervisor_id,epoch,state,recovery_id ')
                and 'FROM cragkit_qdrant.backend_instances' in statement):
            rows = await cursor.fetchall()
            if len(rows) == 1 and rows[0][3:] == (2, 'open', None):
                self.observations['fresh_open_reads'] += 1
            return _Rows(cursor, rows)
        return cursor

    def transaction(self):
        owner = self
        transaction = self.connection.transaction()
        class Transaction:
            async def __aenter__(self):
                owner.open_update = False
                await transaction.__aenter__()
                return self

            async def __aexit__(self, kind, error, traceback):
                result = await transaction.__aexit__(kind, error, traceback)
                observations = owner.observations
                if kind is None and observations['armed'] and owner.open_update:
                    observations['armed'] = False
                    observations['fired'] = True
                    observations['assert_sealed']()
                    observations['boundary_sealed'] = True
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


async def python_recovery_cases(value):
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit._qdrant_supervisor import ManagedQdrantSupervisor
    from cragkit._qdrant_writer import PostgresQdrantWriter, prepare_stage, writer_binding
    from cragkit._qdrant_reconciliation import QdrantReconciliationVerifier, receipt_data
    from cragkit._qdrant_recovery import PostgresQdrantRecovery, recovery_components
    from cragkit.contracts import TrustedScope
    from cragkit.errors import InvalidRequest, ProviderUnavailable, UnsupportedCapability
    import logging

    inputs = value['inputs']
    def config(raw):
        result = dict(raw)
        for key in ('sslrootcert', 'passfile'):
            result[key] = Path(result[key])
        return PoolConfig.model_validate(result)
    writer_config, sup_config = config(value['writer_config']), config(value['supervisor_config'])
    if writer_config.max_size != 1 or sup_config.max_size != 1:
        raise RuntimeError('recovery_fixture_two_client_ceiling')
    observations = dict(armed=False, fired=False, boundary_sealed=False, open_updates=0,
        fresh_open_reads=0, handoff_checked=False, sql_calls=0)
    resource = PoolResource(writer_config)
    sup_resource = PoolResource(sup_config, factory=lambda cfg: _AckPool(cfg, observations))
    supervisor = ManagedQdrantSupervisor(Path(value['binary']), Path(value['work_dir']),
        inputs['instance_id'], inputs['config'])
    writer = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
    verifier = QdrantReconciliationVerifier(writer, supervisor)
    recovery = PostgresQdrantRecovery(sup_resource, inputs['config'], supervisor, verifier)
    if (writer_binding(writer)['instance_id'] != inputs['instance_id']
            or recovery_components(recovery, writer, supervisor, inputs['config']) is not verifier):
        raise RuntimeError('recovery_fixture_native_dependency_binding')
    def context(stage, scope, token):
        return dict(scope=TrustedScope.model_validate(scope), collection=stage['manifest']['collection'],
            document_id=stage['manifest']['document_id'], intent_id=stage['intent']['intent_id'], owner_token=token)
    ctx = context(inputs['stage'], inputs['scope'], OWNER_TOKEN)
    second_token = '00000000-0000-4000-8000-000000000002'
    second = context(inputs['second_stage'], inputs['second_scope'], second_token)
    deadline = asyncio.get_running_loop().time() + 100
    target = '/collections/' + inputs['config']['physical_collection']
    checks, handles, old_credential = [], set(), {}
    fence_count = 0
    pause_physical = None
    competing_recovery = None
    endpoint = primary = None
    logger = logging.getLogger('psycopg.pool')
    # Driver messages can contain connection metadata. Closed observations below
    # retain failures without formatting the expected discarded-client warning.
    quiet = lambda record: False
    logger.addFilter(quiet)

    async def expect(kind, operation):
        try:
            await operation()
        except kind:
            return
        raise RuntimeError('recovery_native_expected_refusal_missing')

    def completed(raw):
        body = json.loads(bytes(raw))
        if body.get('status') != 'ok' or body.get('result', {}).get('status') != 'completed':
            raise RuntimeError('recovery_native_write_not_completed')

    def ordinary_blocked(epoch):
        try:
            supervisor.issue_attempt(dict(intent_id=ctx['intent_id'], owner_token=OWNER_TOKEN,
                epoch=epoch, dispatch_id='must-remain-blocked'), deadline=deadline)
        except ProviderUnavailable:
            return
        raise RuntimeError('recovery_native_ordinary_gate_open')

    def assert_sealed():
        if not supervisor.control_binding()['sealed']:
            raise RuntimeError('recovery_native_lost_ack_not_sealed')
        ordinary_blocked(2)
    observations['assert_sealed'] = assert_sealed

    async def provision(admin, probe):
        await admin.request('PUT', target, body=request_bytes(inputs['collection_config']), deadline=deadline)
        probe = plain(probe)
        await admin.request('PUT', '/collections/' + probe['collection'],
            body=request_bytes(probe['collection_config']), deadline=deadline)
        completed(await admin.request('PUT', '/collections/' + probe['collection'] + '/points?wait=true&ordering=strong',
            body=request_bytes({'points': [probe['point']]}), deadline=deadline))

    async def sup(operation):
        async with sup_resource.lease(deadline=deadline) as connection:
            async with connection.transaction():
                await connection.execute('SET TRANSACTION ISOLATION LEVEL READ COMMITTED')
                await connection.execute('SET LOCAL search_path=pg_catalog')
                await connection.execute("SELECT set_config('cragkit_qdrant.backend_instance_id',%s,true)",
                    (inputs['instance_id'],))
                async def query(statement, params=()):
                    cursor = await connection.execute(statement, params)
                    return await cursor.fetchall() if cursor.description is not None else []
                return await operation(query)

    async def state():
        return await sup(lambda query: query('SELECT state,epoch,recovery_id FROM cragkit_qdrant.backend_instances WHERE instance_id=%s',
            (inputs['instance_id'],)))

    async def journal():
        return await sup(lambda query: query('SELECT dispatch_id,state FROM cragkit_qdrant.dispatch_journal WHERE instance_id=%s ORDER BY dispatch_id',
            (inputs['instance_id'],)))

    async def assert_blocked(epoch=2):
        identity = 'e2b-native' if epoch == 2 else 'e2b-next'
        if await state() != [('recovery_blocked', epoch, identity)]:
            raise RuntimeError('recovery_native_sql_not_blocked')
        ordinary_blocked(epoch)

    async def close_handle(handle):
        await handle.close()
        handles.discard(handle)

    async def ordinary_read(epoch, dispatch):
        cap = supervisor.issue_attempt(dict(intent_id=ctx['intent_id'], owner_token=OWNER_TOKEN,
            epoch=epoch, dispatch_id=dispatch), deadline=deadline)
        handle = supervisor.transport_for(cap); handles.add(handle)
        raw = await handle.request('GET', target, deadline=deadline)
        if json.loads(raw).get('status') != 'ok': raise RuntimeError('recovery_native_ordinary_read_failed')
        await close_handle(handle)

    async def lost_ack(context, stage, points, dispatch_id, capture=False):
        await writer.stage(prepare_stage(stage), context['scope'], owner_token=context['owner_token'], deadline=deadline)
        await writer.acquire_owner(context, deadline=deadline)
        cap = supervisor.issue_attempt(dict(intent_id=context['intent_id'], owner_token=context['owner_token'],
            epoch=1, dispatch_id=dispatch_id), deadline=deadline)
        handle = supervisor.transport_for(cap); handles.add(handle)
        if capture:
            async def save(credential): old_credential.update(credential)
            await supervisor.deliver_worker_credential(cap, save, deadline=deadline)
        reservation = await writer.reserve_dispatch(context, dict(dispatch_id=dispatch_id, sequence=1,
            credential_generation=supervisor.attempt_binding(cap)['credential_generation'],
            operation='complete_point_upsert', point_ids=[point['id'] for point in points]), deadline=deadline)
        await writer.mark_dispatched(context, dispatch_id, deadline=deadline)
        completed(await handle.request('PUT', target + '/points?wait=true&ordering=strong',
            body=reservation['request_bytes'], deadline=deadline))
        await writer.mark_unknown(context, dispatch_id, deadline=deadline)
        await close_handle(handle)
        return reservation

    try:
        await supervisor.initialize(deadline=deadline, provision=provision)
        endpoint = supervisor.identity()['endpoint']
        first_pid = await observed_listener(endpoint)
        await resource.open(); await sup_resource.open()
        await writer.initialize(deadline=deadline)
        await recovery.initialize(deadline=deadline)
        if await state() != [('open', 1, None)]: raise RuntimeError('recovery_native_registration')
        checks.append(CHECKS[0])
        original = await lost_ack(ctx, inputs['stage'], inputs['expected_points'], 'e2b-first-lost', True)
        await lost_ack(second, inputs['second_stage'], inputs['second_points'], 'e2b-second-lost')
        if await journal() != [('e2b-first-lost', 'unknown'), ('e2b-second-lost', 'unknown')]:
            raise RuntimeError('recovery_native_unknown_journals_missing')
        checks.append(CHECKS[1])
        real_session = supervisor.control_session
        @asynccontextmanager
        async def observed_session():
            from types import SimpleNamespace
            async with real_session() as actual:
                async def observed_recover(record, *, deadline):
                    nonlocal fence_count, pause_physical
                    if await state() != [('recovery_blocked', record['new_epoch'], record['recovery_id'])]:
                        raise RuntimeError('recovery_native_physical_before_commit')
                    ordinary_blocked(record['new_epoch'])
                    if pause_physical is not None:
                        started, released = pause_physical
                        pause_physical = None
                        await expect(ProviderUnavailable, lambda: supervisor.recover(record, deadline=deadline))
                        await asyncio.create_task(expect(ProviderUnavailable,
                            lambda: supervisor.recover(record, deadline=deadline)))
                        started.set()
                        async with asyncio.timeout_at(deadline): await released.wait()
                    proof = await actual.recover(record, deadline=deadline)
                    fence_count += 1
                    return proof
                def observed_finish(barrier, token, *, deadline):
                    if observations['fired'] and not observations['handoff_checked']:
                        if (not supervisor.control_binding()['sealed'] or not observations['boundary_sealed']
                                or observations['fresh_open_reads'] < 1 or observations['open_updates'] != 1):
                            raise RuntimeError('recovery_native_handoff_before_sql_reconciliation')
                        observations['handoff_checked'] = True
                    return actual.finish_recovery(barrier, token, deadline=deadline)
                yield SimpleNamespace(block_ordinary=actual.block_ordinary, recover=observed_recover,
                    seal_recovery=actual.seal_recovery, finish_recovery=observed_finish)
        supervisor.control_session = observed_session
        proof_a = await recovery.recover('e2b-native', deadline=deadline)
        await assert_blocked()
        if fence_count != 1 or await observed_listener(endpoint) == first_pid:
            raise RuntimeError('recovery_native_restart_missing')
        binding_a = supervisor.recovery_binding(proof_a)
        checks.append(CHECKS[2])
        status = await asyncio.to_thread(old_key_mutation_status, old_credential,
            target + '/points?wait=true&ordering=strong', original['request_bytes'])
        if status != 401: raise RuntimeError('recovery_native_retired_key_not_denied')
        checks.append(CHECKS[3])
        await expect(ProviderUnavailable, lambda: recovery.advance_owner(proof_a,
            dict(ctx, owner_token=second_token), deadline=deadline))
        owner = await recovery.advance_owner(proof_a, ctx, deadline=deadline)
        if dict(owner) != dict(owner_token=OWNER_TOKEN, backend_epoch=2): raise RuntimeError('recovery_native_owner_rebound')
        checks.append(CHECKS[4])
        receipt_a = await verifier.verify(proof_a, ctx, deadline=deadline)
        await expect(InvalidRequest, lambda: recovery.settle_retired(proof_a, {}, deadline=deadline))
        checks.append(CHECKS[5])
        if (await recovery.settle_retired(proof_a, receipt_a, deadline=deadline))['settled_count'] != 1:
            raise RuntimeError('recovery_native_settlement_missing')
        if await journal() != [('e2b-first-lost', 'settled'), ('e2b-second-lost', 'unknown')]:
            raise RuntimeError('recovery_native_foreign_document_settled')
        checks.append(CHECKS[6])
        await expect(ProviderUnavailable, lambda: recovery.reopen(proof_a, deadline=deadline))
        await assert_blocked()
        if not supervisor.control_binding()['sealed']: raise RuntimeError('recovery_native_pending_not_sealed')
        checks.append(CHECKS[7])
        proof_b = await recovery.recover('e2b-native', deadline=deadline)
        binding_b = supervisor.recovery_binding(proof_b)
        if (fence_count != 2 or binding_b['new_epoch'] != 2
                or binding_a['credential_generation'] == binding_b['credential_generation']):
            raise RuntimeError('recovery_native_repeated_fence_missing')
        for call in (lambda: supervisor.recovery_binding(proof_a), lambda: receipt_data(receipt_a, verifier)):
            try: call()
            except UnsupportedCapability: pass
            else: raise RuntimeError('recovery_native_stale_physical_proof_accepted')
        await assert_blocked()
        checks.append(CHECKS[8])
        await recovery.advance_owner(proof_b, second, deadline=deadline)
        other_receipt = await verifier.verify(proof_b, second, deadline=deadline)
        if (await recovery.settle_retired(proof_b, other_receipt, deadline=deadline))['settled_count'] != 1:
            raise RuntimeError('recovery_native_other_authorized_document_not_settled')
        checks.append(CHECKS[9])
        dispatch_id = 'e2b-current-unknown'
        async def reserve(query):
            await query("INSERT INTO cragkit_qdrant.dispatch_journal(tenant_id,collection,document_id,intent_id,dispatch_id,instance_id,sequence,owner_token,backend_epoch,credential_generation,operation,recovery,request_bytes,request_sha256) VALUES(%s,%s,%s,%s,%s,%s,2,%s,2,%s,'complete_point_upsert',true,%s,%s)",
                (ctx['scope'].tenant_id, ctx['collection'], ctx['document_id'], ctx['intent_id'], dispatch_id,
                 inputs['instance_id'], OWNER_TOKEN, binding_b['credential_generation'], original['request_bytes'],
                 sha256(original['request_bytes']).hexdigest()))
            for point in inputs['expected_points']:
                await query('INSERT INTO cragkit_qdrant.dispatch_points(tenant_id,collection,document_id,intent_id,dispatch_id,backend_namespace,physical_collection,collection_incarnation,point_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (ctx['scope'].tenant_id, ctx['collection'], ctx['document_id'], ctx['intent_id'], dispatch_id,
                     inputs['config']['backend_namespace'], inputs['config']['physical_collection'], inputs['config']['collection_incarnation'], point['id']))
        await sup(reserve)
        async def dispatch_state(state):
            return await sup(lambda query: query('UPDATE cragkit_qdrant.dispatch_journal SET state=%s WHERE instance_id=%s AND dispatch_id=%s',
                (state, inputs['instance_id'], dispatch_id)))
        await dispatch_state('dispatched')
        cap = supervisor.issue_recovery_attempt(proof_b, dict(intent_id=ctx['intent_id'], owner_token=OWNER_TOKEN,
            epoch=2, recovery_id='e2b-native', dispatch_id=dispatch_id), deadline=deadline)
        handle = supervisor.transport_for(cap); handles.add(handle)
        completed(await handle.request('PUT', target + '/points?wait=true&ordering=strong',
            body=original['request_bytes'], deadline=deadline))
        await close_handle(handle)
        await dispatch_state('unknown')
        checks.append(CHECKS[10])
        current_receipt = await verifier.verify(proof_b, ctx, deadline=deadline)
        await expect(ProviderUnavailable, lambda: recovery.settle_retired(proof_b, current_receipt, deadline=deadline))
        if await journal() != [('e2b-current-unknown', 'unknown'), ('e2b-first-lost', 'settled'), ('e2b-second-lost', 'settled')]:
            raise RuntimeError('recovery_native_current_generation_settled')
        checks.append(CHECKS[11])
        await expect(ProviderUnavailable, lambda: recovery.reopen(proof_b, deadline=deadline))
        await assert_blocked()
        if not supervisor.control_binding()['sealed']: raise RuntimeError('recovery_native_current_generation_not_sealed')
        checks.append(CHECKS[12])
        proof_c = await recovery.recover('e2b-native', deadline=deadline)
        binding_c = supervisor.recovery_binding(proof_c)
        if (fence_count != 3 or binding_c['new_epoch'] != 2
                or binding_c['credential_generation'] == binding_b['credential_generation']):
            raise RuntimeError('recovery_native_current_generation_not_retired')
        await recovery.advance_owner(proof_c, ctx, deadline=deadline)
        receipt_c = await verifier.verify(proof_c, ctx, deadline=deadline)
        if (await recovery.settle_retired(proof_c, receipt_c, deadline=deadline))['settled_count'] != 1:
            raise RuntimeError('recovery_native_retired_generation_not_settled')
        checks.append(CHECKS[13])
        if (await recovery.settle_retired(proof_c, receipt_c, deadline=deadline))['settled_count'] != 0:
            raise RuntimeError('recovery_native_settlement_replay_changed')
        checks.append(CHECKS[14])
        competing_recovery = PostgresQdrantRecovery(sup_resource, inputs['config'], supervisor, verifier)
        await competing_recovery.initialize(deadline=deadline)
        started, released = asyncio.Event(), asyncio.Event()
        pause_physical = (started, released)
        competing = asyncio.create_task(competing_recovery.recover('e2b-native', deadline=deadline))
        reached = asyncio.create_task(started.wait())
        try:
            async with asyncio.timeout_at(deadline):
                completed_tasks, _ = await asyncio.wait((competing, reached), return_when=asyncio.FIRST_COMPLETED)
            if competing in completed_tasks:
                await competing
                raise RuntimeError('recovery_native_competitor_did_not_pause')
        finally:
            if not reached.done(): reached.cancel()
            await asyncio.gather(reached, return_exceptions=True)
        before = observations['sql_calls']
        await expect(ProviderUnavailable, lambda: recovery.reopen(proof_c, deadline=deadline))
        await expect(ProviderUnavailable, lambda: supervisor.recover(
            dict(recovery_id='e2b-native', old_epoch=1, new_epoch=2), deadline=deadline))
        if observations['sql_calls'] != before:
            raise RuntimeError('recovery_native_competing_operation_reached_sql')
        await assert_blocked()
        checks.append(CHECKS[15])
        released.set()
        handoff_proof = await competing
        if supervisor.recovery_binding(handoff_proof)['new_epoch'] != 2 or fence_count != 4:
            raise RuntimeError('recovery_native_shared_session_handoff')
        await competing_recovery.close(); competing_recovery = None
        checks.append(CHECKS[16])
        observations['armed'] = True
        try:
            opened = await recovery.reopen(handoff_proof, deadline=deadline)
        except ProviderUnavailable:
            if not observations['fired'] or not supervisor.control_binding()['sealed']: raise
            ordinary_blocked(2)
            opened = await recovery.reopen(handoff_proof, deadline=asyncio.get_running_loop().time()+30)
        if (not observations['fired'] or not observations['boundary_sealed'] or not observations['handoff_checked']
                or observations['open_updates'] != 1 or observations['fresh_open_reads'] < 1
                or dict(opened) != dict(state='open', epoch=2)):
            raise RuntimeError('recovery_native_open_ack_not_reconciled')
        checks.append(CHECKS[17])
        if await state() != [('open', 2, None)]: raise RuntimeError('recovery_native_sql_not_open')
        await ordinary_read(2, 'e2b-ordinary-after-recovery')
        try: supervisor.recovery_binding(handoff_proof)
        except UnsupportedCapability: pass
        else: raise RuntimeError('recovery_native_old_proof_after_open')
        checks.append(CHECKS[18])
        next_proof = await recovery.recover('e2b-next', deadline=deadline)
        if supervisor.recovery_binding(next_proof)['new_epoch'] != 3 or fence_count != 5:
            raise RuntimeError('recovery_native_next_epoch_not_advanced')
        await assert_blocked(3)
        if dict(await recovery.reopen(next_proof, deadline=deadline)) != dict(state='open', epoch=3):
            raise RuntimeError('recovery_native_next_epoch_not_open')
        if await state() != [('open', 3, None)]: raise RuntimeError('recovery_native_next_sql_state')
        await ordinary_read(3, 'e2b-next-ordinary')
        checks.append(CHECKS[19])
        for context in (ctx, second):
            intent = await writer.inspect(context, deadline=deadline)
            if intent is None or intent['state'] != 'writing' or any(intent[key] for key in
                    ('authority_committed', 'replica_complete', 'purge_complete')):
                raise RuntimeError('recovery_native_claimed_publication')
        remaining = await journal()
        if len(remaining) != 3 or any(row[1] != 'settled' for row in remaining):
            raise RuntimeError('recovery_native_final_journal')
        checks.append(CHECKS[20])
        return dict(runtime='python', checks=checks, proof_scope='durable_recovery_settlement_only')
    except BaseException as error:
        primary = error
        if isinstance(error, Exception):
            name = type(error).__name__
            raise NativeRecoveryFailure(dict(ok=False, step=len(checks), error=name if name in ERRORS else 'internal')) from None
        raise
    finally:
        failures = []
        for handle in list(handles):
            try: await asyncio.wait_for(handle.close(), 3)
            except BaseException as error: failures.append(('runtime_close', error))
        for owned in (recovery, competing_recovery, writer, resource, sup_resource, supervisor):
            if owned is None: continue
            try: await asyncio.wait_for(owned.close(), 8)
            except BaseException as error: failures.append(('runtime_close', error))
        if endpoint is not None:
            try: await observed_listener(endpoint, allow_absent=True)
            except BaseException as error: failures.append(('verify_inventory', error))
        logger.removeFilter(quiet)
        if failures: raise CleanupFailure(failures, primary=primary, stage='recovery') from None
