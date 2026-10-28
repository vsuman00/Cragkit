"""Actual G0 receipts and same-intent publication on disposable native servers."""
from __future__ import annotations

from qdrant_publication_manager_cases import (ERRORS, _PreparationAckPool,
    _PreparationAckConnection)
from qdrant_recovery_cases import recovery_input
from qdrant_writer_cases import successor_stage
from qdrant_supervisor_cases import supervisor_input

CHECKS = (
    'native_g1_published_and_g2_prepared',
    'unrelated_document_recovery_preserves_prepared_intent_and_original_preparation',
    'current_f1_receipt_requires_live_finalization_and_original_writer',
    'actual_attestation_commit_ack_loss_reconciles_same_key',
    'exact_receipt_retry_preserves_attestation_without_mutation',
    'contradictory_verification_binding_is_denied',
    'copied_and_stale_receipts_and_context_are_denied',
    'interruption_preserves_prior_active_and_original_preparation',
    'same_prepared_intent_and_generation_publish_at_current_epoch',
    'current_security_change_denies_attestation_and_preserves_active',
)


class NativeAttestationFailure(RuntimeError):
    def __init__(self, observation):
        super().__init__('attestation_native_case_failed')
        self.observation = observation


def attestation_input():
    inputs = recovery_input()
    inputs['collection_config'] = supervisor_input()['collection_config']
    prepared = successor_stage(inputs, 'attestation-prepared', inputs['stage']['manifest']['generation_id'])
    revoked = successor_stage(inputs, 'attestation-revoked', prepared['manifest']['generation_id'])
    inputs['stages'] = dict(prepared=prepared, revoked=revoked)
    return inputs


class _AttestationAckConnection(_PreparationAckConnection):
    async def execute(self, statement, params=()):
        if (self.observations['armed'] and type(statement) is str
                and statement.startswith('INSERT INTO cragkit_qdrant.preparation_attestations ')):
            self.preparing = True
            self.observations['insert_count'] += 1
        return await self.connection.execute(statement, params)


class _AttestationAckPool(_PreparationAckPool):
    async def getconn(self, **options):
        return _AttestationAckConnection(await self.pool.getconn(**options), self.observations)


async def python_attestation_cases(value):
    import asyncio
    from copy import copy
    import json
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit._qdrant_writer import prepare_stage
    from cragkit._qdrant_publication_verification import QdrantPublicationVerifier
    from cragkit._qdrant_publication_worker import controller_finalization
    from cragkit.contracts import Limits, TrustedScope
    from cragkit.execution import ExecutionLedger
    from cragkit.errors import IntegrityViolation, InvalidRequest, UnsupportedCapability, UnauthorizedScope
    from cragkit.qdrant_publication import (QdrantPublicationManager, PostgresQdrantPublicationAuthority,
        ManagedQdrantPublicationTransport, PostgresQdrantWriter, PostgresQdrantRecovery,
        ManagedQdrantSupervisor, QdrantReconciliationVerifier)
    from qdrant_supervisor_cases import plain, request_bytes, observed_listener

    inputs = value['inputs']
    def config(raw):
        raw = dict(raw)
        for key in ('sslrootcert', 'passfile'):
            raw[key] = Path(raw[key])
        return PoolConfig.model_validate(raw)
    writer_config, supervisor_config = config(value['writer_config']), config(value['supervisor_config'])
    if writer_config.max_size != 1 or supervisor_config.max_size != 1:
        raise RuntimeError('attestation_fixture_two_client_ceiling')
    acknowledgment = dict(armed=False, fired=0, insert_count=0)
    resource = PoolResource(writer_config, factory=lambda cfg: _AttestationAckPool(cfg, acknowledgment))
    supervisor_resource = PoolResource(supervisor_config)
    supervisor = ManagedQdrantSupervisor(Path(value['binary']), Path(value['work_dir']),
        inputs['instance_id'], inputs['config'])
    writer = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
    reconciler = QdrantReconciliationVerifier(writer, supervisor)
    recovery = PostgresQdrantRecovery(supervisor_resource, inputs['config'], supervisor, reconciler)
    authority = PostgresQdrantPublicationAuthority(writer, recovery)
    transport = ManagedQdrantPublicationTransport(supervisor)
    verifier = QdrantPublicationVerifier(writer, supervisor)
    scope = TrustedScope.model_validate(inputs['scope'])
    lookup_token = '00000000-0000-4000-8000-000000000099'
    deadline = asyncio.get_running_loop().time() + 125
    checks, handles = [], []
    mode = dict(cancel=False, fired=False)
    network = dict(mutations=0)
    endpoint = primary = manager = None
    target = '/collections/' + inputs['config']['physical_collection']

    def reference(stage):
        return dict(collection=stage['manifest']['collection'], document_id=stage['manifest']['document_id'],
            intent_id=stage['intent']['intent_id'])
    def context(stage, selected_scope=scope, token=lookup_token):
        return dict(scope=selected_scope, **reference(stage), owner_token=token)
    def ledger():
        return ExecutionLedger(Limits(deadline_ms=60000, max_attempts=1, max_provider_calls=0), deadline=deadline)
    async def snapshot(stage, selected_scope=scope):
        return await writer.manager_snapshot(context(stage, selected_scope), deadline=deadline)
    async def expect(kinds, operation):
        try:
            await operation()
        except kinds:
            return
        raise RuntimeError('attestation_expected_refusal_missing')
    async def authorize(selected_scope, collection, document):
        if mode['cancel'] and not mode['fired']:
            state = await snapshot(mode['stage'])
            if state['intent'] is not None and state['intent']['state'] == 'prepared':
                mode['fired'] = True
                asyncio.current_task().cancel()
                await asyncio.sleep(0)
        return True
    async def prepare(stage):
        await manager.stage(stage, scope, ledger(), deadline=deadline)
        mode.update(cancel=True, fired=False, stage=stage)
        task = asyncio.create_task(manager.publish(reference(stage), scope, ledger(), deadline=deadline))
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise RuntimeError('attestation_prepared_pause_missing')
        mode.update(cancel=False)
        state = await snapshot(stage)
        if not mode['fired'] or state['intent']['state'] != 'prepared':
            raise RuntimeError('attestation_not_prepared')
        return context(stage, token=state['owner']['owner_token'])
    def completed(raw):
        result = json.loads(bytes(raw))
        if result.get('status') != 'ok' or result.get('result', {}).get('status') != 'completed':
            raise RuntimeError('attestation_native_ack_not_completed')
    async def provision(admin, probe):
        await admin.request('PUT', target, body=request_bytes(inputs['collection_config']), deadline=deadline)
        probe = plain(probe)
        path = '/collections/' + probe['collection']
        await admin.request('PUT', path, body=request_bytes(probe['collection_config']), deadline=deadline)
        completed(await admin.request('PUT', path + '/points?wait=true&ordering=strong',
            body=request_bytes({'points': [probe['point']]}), deadline=deadline))
    class Handle:
        def __init__(self, actual): self.actual = actual
        async def request(self, method, path, **options):
            if method == 'PUT' and '/points?' in path:
                network['mutations'] += 1
            return await self.actual.request(method, path, **options)
        async def close(self): await self.actual.close()
    async def ordinary(ctx, epoch, dispatch):
        attempt = supervisor.issue_attempt(dict(intent_id=ctx['intent_id'], owner_token=ctx['owner_token'],
            epoch=epoch, dispatch_id=dispatch), deadline=deadline)
        return attempt, await verifier.verify(attempt, ctx, deadline=deadline)
    async def refence(identity, contexts):
        proof = await recovery.recover(identity, deadline=deadline)
        for ctx in contexts:
            await recovery.advance_owner(proof, ctx, deadline=deadline)
        opened = await recovery.reopen(proof, deadline=deadline)
        if dict(opened) != dict(state='open', epoch=2 if identity == 'attestation-recovery' else 3):
            raise RuntimeError('attestation_recovery_not_open')

    try:
        await supervisor.initialize(deadline=deadline, provision=provision)
        endpoint = supervisor.identity()['endpoint']
        await observed_listener(endpoint)
        original_transport = supervisor.transport_for
        def observed_transport(attempt):
            handle = Handle(original_transport(attempt)); handles.append(handle); return handle
        supervisor.transport_for = observed_transport
        await resource.open(); await supervisor_resource.open()
        manager = QdrantPublicationManager(authority, transport, inputs['config'], supervisor, authorize)
        await manager.initialize(deadline=deadline)
        base, prepared, revoked = inputs['stage'], inputs['stages']['prepared'], inputs['stages']['revoked']
        await manager.stage(base, scope, ledger(), deadline=deadline)
        if (await manager.publish(reference(base), scope, ledger(), deadline=deadline))['state'] != 'published':
            raise RuntimeError('attestation_g1_not_published')
        ctx = await prepare(prepared)
        original = plain(await writer.attestation_snapshot(ctx, deadline=deadline))
        if original['attestation'] is not None or original['preparation']['backend_epoch'] != 1:
            raise RuntimeError('attestation_original_preparation_wrong')
        old_attempt, old_receipt = await ordinary(ctx, 1, 'attestation-old')
        checks.append(CHECKS[0])
        other_scope = TrustedScope.model_validate(inputs['second_scope'])
        other = context(inputs['second_stage'], other_scope, '00000000-0000-4000-8000-000000000002')
        await writer.stage(prepare_stage(inputs['second_stage']), other_scope,
            owner_token=other['owner_token'], deadline=deadline)
        await writer.acquire_owner(other, deadline=deadline)
        await refence('attestation-recovery', (ctx, other))
        state = await snapshot(prepared)
        current = plain(await writer.attestation_snapshot(ctx, deadline=deadline))
        if (state['intent']['state'] != 'prepared' or state['owner']['backend_epoch'] != 2
                or current != original or state['document']['active_generation_id'] != base['manifest']['generation_id']):
            raise RuntimeError('attestation_recovery_changed_preparation')
        writes = network['mutations']
        checks.append(CHECKS[1])
        attempt, receipt = await ordinary(ctx, 2, 'attestation-current')
        refusals = (InvalidRequest, UnsupportedCapability)
        await expect(refusals, lambda: writer.attest_prepared(receipt, verifier, deadline=deadline))
        foreign = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
        foreign_verifier = QdrantPublicationVerifier(foreign, supervisor)
        async with controller_finalization(supervisor, attempt, deadline=deadline):
            await expect(refusals, lambda: writer.attest_prepared(receipt, foreign_verifier, deadline=deadline))
        await foreign_verifier.close()
        checks.append(CHECKS[2])
        acknowledgment['armed'] = True
        async with controller_finalization(supervisor, attempt, deadline=deadline):
            attested = plain(await writer.attest_prepared(receipt, verifier, deadline=deadline))
        if (acknowledgment['armed'] or acknowledgment['fired'] != 1 or acknowledgment['insert_count'] != 1
                or not acknowledgment['retired_connection'].closed or attested['attestation']['backend_epoch'] != 2
                or attested['intent']['state'] != 'prepared'):
            raise RuntimeError('attestation_commit_ack_not_reconciled')
        checks.append(CHECKS[3])
        async with controller_finalization(supervisor, attempt, deadline=deadline):
            retried = plain(await writer.attest_prepared(receipt, verifier, deadline=deadline))
        if retried != attested or network['mutations'] != writes:
            raise RuntimeError('attestation_retry_changed_result_or_resent')
        checks.append(CHECKS[4])
        alternate_attempt, alternate_receipt = await ordinary(ctx, 2, 'attestation-contradiction')
        async with controller_finalization(supervisor, alternate_attempt, deadline=deadline):
            await expect(IntegrityViolation, lambda: writer.attest_prepared(alternate_receipt, verifier, deadline=deadline))
        checks.append(CHECKS[5])
        try:
            copy(receipt)
        except TypeError:
            pass
        else:
            raise RuntimeError('attestation_receipt_copy_not_rejected')
        async with controller_finalization(supervisor, attempt, deadline=deadline):
            await expect(refusals, lambda: writer.attest_prepared(type(receipt)(), verifier, deadline=deadline))
            await expect(refusals, lambda: writer.attest_prepared(old_receipt, verifier, deadline=deadline))
        await expect(refusals, lambda: writer.attest_prepared(receipt, verifier, deadline=deadline))
        checks.append(CHECKS[6])
        current = plain(await writer.attestation_snapshot(ctx, deadline=deadline))
        state = await snapshot(prepared)
        if (current['preparation'] != original['preparation'] or current['attestation'] != attested['attestation']
                or state['intent']['state'] != 'prepared' or network['mutations'] != writes
                or state['document']['active_generation_id'] != base['manifest']['generation_id']):
            raise RuntimeError('attestation_interruption_changed_original')
        checks.append(CHECKS[7])
        async with controller_finalization(supervisor, attempt, deadline=deadline):
            published = await writer.publish(ctx, deadline=deadline)
        state = await snapshot(prepared)
        if (published['state'] != 'published' or attested['attestation']['intent_id'] != ctx['intent_id']
                or state['intent']['generation_id'] != prepared['manifest']['generation_id']
                or state['document']['active_generation_id'] != prepared['manifest']['generation_id']
                or network['mutations'] != writes):
            raise RuntimeError('attestation_same_intent_not_published')
        checks.append(CHECKS[8])
        revoked_ctx = await prepare(revoked)
        await refence('attestation-security-recovery', (revoked_ctx,))
        revoked_attempt, revoked_receipt = await ordinary(revoked_ctx, 3, 'attestation-security')
        change = dict(action='update_authorization', intent_id='attestation-security-change',
            tenant_id=scope.tenant_id, collection=ctx['collection'], document_id=ctx['document_id'],
            expected_authorization_revision='auth-1', expected_mutation_epoch=1,
            authorization=dict(authorization_revision='auth-attestation-2', principal_ids=[], grant_ids=[],
                language=None, kind=None, tag=None, tombstoned=False))
        async with controller_finalization(supervisor, revoked_attempt, deadline=deadline):
            await writer.apply_security(change, scope, owner_token=lookup_token, deadline=deadline)
            try:
                denied = await writer.attest_prepared(revoked_receipt, verifier, deadline=deadline)
            except UnauthorizedScope:
                denied = None
            if denied is not None and (denied['intent']['state'] != 'denied' or denied['attestation'] is not None):
                raise RuntimeError('attestation_security_accepted')
        fresh_scope = TrustedScope.model_validate(dict(inputs['scope'], authorization_revision='auth-attestation-2'))
        state = await snapshot(revoked, fresh_scope)
        if state['document']['active_generation_id'] != prepared['manifest']['generation_id']:
            raise RuntimeError('attestation_security_changed_active')
        checks.append(CHECKS[9])
        return dict(runtime='python', checks=checks, proof_scope='native_prepared_attestation_only')
    except BaseException as error:
        primary = error
        name = type(error).__name__
        import traceback
        locations=[]
        for frame in traceback.extract_tb(error.__traceback__):
            path=Path(frame.filename).resolve()
            try: relative=path.relative_to(Path(__file__).resolve().parents[1])
            except ValueError: continue
            if str(relative).startswith(('packages/python/src/','tools/')):
                locations.append(dict(path=str(relative),line=frame.lineno))
        (Path(value['work_dir']).parent / 'failure-locations.json').write_text(json.dumps(locations)+'\n')
        raise NativeAttestationFailure(dict(ok=False, step=len(checks), error=name if name in ERRORS else 'internal')) from None
    finally:
        failures = []
        cleanup_deadline = asyncio.get_running_loop().time() + 15
        owned = ([('manager_close', manager)] if manager is not None else [])
        owned += [('transport_close', handle) for handle in handles]
        owned += [('verifier_close', verifier), ('recovery_close', recovery), ('writer_close', writer),
            ('resource_close', resource), ('supervisor_resource_close', supervisor_resource), ('controller_close', supervisor)]
        for operation, item in owned:
            try:
                await asyncio.wait_for(item.close(), max(.001, min(8, cleanup_deadline-asyncio.get_running_loop().time())))
            except BaseException as error:
                failures.append(dict(operation=operation, outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if endpoint is not None:
            try: await observed_listener(endpoint, allow_absent=True)
            except BaseException as error:
                failures.append(dict(operation='listener_close', outcome=type(error).__name__ if type(error).__name__ in ERRORS else 'internal'))
        if failures:
            name = type(primary).__name__ if primary is not None else None
            raise NativeAttestationFailure(dict(ok=False, step=len(checks), error='cleanup_failed',
                primary=name if name in ERRORS else ('internal' if name else None), cleanup=failures)) from None
