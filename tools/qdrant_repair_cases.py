"""Native public repair acceptance; synthetic data and actual recovery authority."""
from __future__ import annotations
from qdrant_attestation_cases import _AttestationAckPool, ERRORS
from qdrant_attestation_cases import attestation_input
from qdrant_writer_cases import successor_stage

CHECKS=(
 'stage_repair_publishes',
 'same_epoch_prepared_repair_without_point_resend',
 'cross_epoch_prepared_actual_attestation_ack_loss',
 'interrupted_attested_repair_preserves_prior_active',
 'attested_retry_same_generation_without_point_resend',
 'complete_unknown_recovery_then_bounded_verified_replay',
 'historical_repair_no_replay',
 'callback_denial_preserves_active',
 'foreign_unknown_keeps_instance_blocked',
 'source_authority_outage_fails_repair_authorization',
)
class NativeRepairFailure(RuntimeError):
    def __init__(self,observation):
        super().__init__('repair_native_case_failed');self.observation=observation

def repair_input():
    value=attestation_input()
    previous=value['stages']['prepared']['manifest']['generation_id']
    for key in ('cross','uncertain','blocked'):
        stage=successor_stage(value,'repair-'+key,previous)
        value['stages'][key]=stage
        previous=stage['manifest']['generation_id']
    value['stages'].pop('revoked')
    return value

async def python_repair_cases(value):
    import asyncio
    import json
    from pathlib import Path
    from cragkit._postgres_pool import PoolConfig, PoolResource
    from cragkit.contracts import Limits, TrustedScope
    from cragkit.execution import ExecutionLedger
    from cragkit.errors import UnauthorizedScope, ProviderUnavailable
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
        raise RuntimeError('repair_fixture_two_client_ceiling')
    acknowledgment = dict(armed=False, fired=0, insert_count=0,
        publication=dict(track=False,dml=0,armed=False,cas_writes=0,fired=0))
    resource = PoolResource(writer_config, factory=lambda cfg: _AttestationAckPool(cfg, acknowledgment))
    supervisor_resource = PoolResource(supervisor_config)
    supervisor = ManagedQdrantSupervisor(Path(value['binary']), Path(value['work_dir']),
        inputs['instance_id'], inputs['config'])
    writer = PostgresQdrantWriter(resource, inputs['config'], inputs['instance_id'])
    reconciler = QdrantReconciliationVerifier(writer, supervisor)
    recovery = PostgresQdrantRecovery(supervisor_resource, inputs['config'], supervisor, reconciler)
    authority = PostgresQdrantPublicationAuthority(writer, recovery)
    transport = ManagedQdrantPublicationTransport(supervisor)
    scope = TrustedScope.model_validate(inputs['scope'])
    lookup_token = '00000000-0000-4000-8000-000000000099'
    deadline = asyncio.get_running_loop().time() + 125
    checks, handles = [], []
    mode = dict(cancel=False, fired=False)
    network = dict(mutations=0,drop=False,requests=0)
    outage = dict(armed=False, entered=0, reads=0, unavailable=0)
    endpoint = primary = manager = inspection_resource = None
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
        raise RuntimeError('repair_expected_refusal_missing')
    async def authorize(selected_scope, collection, document):
        if outage['armed']:
            outage['entered'] += 1
            if (selected_scope != scope or collection != outage['stage']['manifest']['collection']
                    or document != outage['stage']['manifest']['document_id']):
                raise RuntimeError('repair_outage_wrong_authorization_target')
            outage['before'] = await authority_read(resource, outage['stage'])
            outage['reads'] += 1
            if (outage['before'][0] != outage['previous'] or outage['before'][1] == 'published'):
                raise RuntimeError('repair_outage_invalid_prior_authority')
            await resource.close()
            try:
                await authority_read(resource, outage['stage'])
            except ProviderUnavailable:
                outage['unavailable'] += 1
                raise
            raise RuntimeError('repair_outage_authority_still_available')
        if mode.get('deny'):return False
        if mode['cancel'] and not mode['fired']:
            state = await snapshot(mode['stage'])
            if state['intent'] is not None and state['intent']['state'] == 'prepared':
                mode['fired'] = True
                asyncio.current_task().cancel()
                await asyncio.sleep(0)
        return True
    async def authority_read(selected_resource, stage):
        from cragkit._qdrant_writer import _SCOPE_SQL
        bounded = min(deadline, asyncio.get_running_loop().time() + 5)
        async with asyncio.timeout_at(bounded):
            async with selected_resource.lease(deadline=bounded) as connection:
                async with connection.transaction():
                    await connection.execute('SET TRANSACTION READ ONLY')
                    await connection.execute("SELECT set_config('statement_timeout',%s,true)",
                        (str(max(1, int((bounded-asyncio.get_running_loop().time())*1000))),))
                    await connection.execute(_SCOPE_SQL, (scope.tenant_id, stage['manifest']['collection'],
                        scope.principal_id, json.dumps(list(scope.grant_ids)), scope.authorization_revision,
                        stage['manifest']['document_id'], stage['intent']['intent_id'], lookup_token, inputs['instance_id']))
                    cursor = await connection.execute('SELECT d.active_generation_id,i.state '
                        'FROM cragkit_qdrant.documents d JOIN cragkit_qdrant.publication_intents i '
                        'USING (tenant_id,collection,document_id) WHERE d.tenant_id=%s AND d.collection=%s '
                        'AND d.document_id=%s AND i.intent_id=%s LIMIT 1',
                        (scope.tenant_id,stage['manifest']['collection'],stage['manifest']['document_id'],stage['intent']['intent_id']))
                    rows = await cursor.fetchall()
                    if len(rows) != 1:raise RuntimeError('repair_outage_authority_row_missing')
                    return tuple(rows[0])
    async def prepare(stage):
        await manager.stage(stage, scope, ledger(), deadline=deadline)
        mode.update(cancel=True, fired=False, stage=stage)
        task = asyncio.create_task(manager.publish(reference(stage), scope, ledger(), deadline=deadline))
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise RuntimeError('repair_prepared_pause_missing')
        mode.update(cancel=False)
        state = await snapshot(stage)
        if not mode['fired'] or state['intent']['state'] != 'prepared':
            raise RuntimeError('repair_not_prepared')
        return context(stage, token=state['owner']['owner_token'])
    def completed(raw):
        result = json.loads(bytes(raw))
        if result.get('status') != 'ok' or result.get('result', {}).get('status') != 'completed':
            raise RuntimeError('repair_native_ack_not_completed')
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
            network['requests'] += 1
            if method == 'PUT' and '/points?' in path:
                network['mutations'] += 1
            response=await self.actual.request(method,path,**options)
            if method=='PUT' and '/points?' in path and network['drop']:
                network['drop']=False
                raise ProviderUnavailable()
            return response
        async def close(self): await self.actual.close()
    async def refence(identity, contexts):
        proof = await recovery.recover(identity, deadline=deadline)
        for ctx in contexts:
            await recovery.advance_owner(proof, ctx, deadline=deadline)
        opened = await recovery.reopen(proof, deadline=deadline)
        if dict(opened) != dict(state='open', epoch=2):
            raise RuntimeError('repair_recovery_not_open')

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
        base, prepared, cross, uncertain, blocked = (inputs['stage'],inputs['stages']['prepared'],
            inputs['stages']['cross'],inputs['stages']['uncertain'],inputs['stages']['blocked'])
        async def repair(stage,selected_scope=scope):
            book=ledger()
            result=await manager.repair(reference(stage),selected_scope,book,deadline=deadline)
            if book.snapshot()['attempts']!=1:raise RuntimeError('repair_double_attempt')
            return result
        await manager.stage(base,scope,ledger(),deadline=deadline)
        result=await repair(base)
        if result['state']!='published' or result['operation']!='repair':raise RuntimeError('repair_initial_failed')
        checks.append(CHECKS[0])
        ctx=await prepare(prepared)
        writes=network['mutations']
        result=await repair(prepared)
        if result['state']!='published' or network['mutations']!=writes:raise RuntimeError('repair_prepared_resent')
        checks.append(CHECKS[1])
        cross_ctx=await prepare(cross)
        cross_original=plain(await writer.attestation_snapshot(cross_ctx,deadline=deadline))
        await refence('repair-external-recovery',(cross_ctx,))
        writes=network['mutations']
        acknowledgment['armed']=True
        actual_publish=writer.publish
        interrupted=False
        async def interrupt_publish(value,*,deadline):
            nonlocal interrupted
            current=plain(await writer.attestation_snapshot(value,deadline=deadline))
            if current['attestation'] is None:raise RuntimeError('repair_no_attestation_before_publish')
            interrupted=True
            raise asyncio.CancelledError()
        writer.publish=interrupt_publish
        try:
            task=asyncio.create_task(repair(cross))
            try:await task
            except asyncio.CancelledError:pass
            else:raise RuntimeError('repair_interrupt_missing')
        finally:writer.publish=actual_publish
        if not interrupted or acknowledgment['fired']!=1 or acknowledgment['armed'] or acknowledgment['insert_count']!=1:
            raise RuntimeError('repair_actual_ack_loss_not_reconciled')
        checks.append(CHECKS[2])
        state=await snapshot(cross)
        attested=plain(await writer.attestation_snapshot(cross_ctx,deadline=deadline))
        if (state['document']['active_generation_id']!=prepared['manifest']['generation_id']
                or state['intent']['state']!='prepared' or attested['preparation']!=cross_original['preparation']
                or network['mutations']!=writes):raise RuntimeError('repair_interrupt_changed_prior')
        checks.append(CHECKS[3])
        result=await repair(cross)
        if result['state']!='published' or result['generation_id']!=cross['manifest']['generation_id'] or network['mutations']!=writes:
            raise RuntimeError('repair_attested_retry_resent')
        checks.append(CHECKS[4])
        await manager.stage(uncertain,scope,ledger(),deadline=deadline)
        network['drop']=True
        await expect(ProviderUnavailable,lambda:manager.publish(reference(uncertain),scope,ledger(),deadline=deadline))
        state=await snapshot(uncertain)
        if not state['pending']:raise RuntimeError('repair_unknown_journal_missing')
        writes=network['mutations']
        result=await repair(uncertain)
        state=await snapshot(uncertain)
        if result['state']!='published' or state['pending'] or state['backend']['state']!='open' or network['mutations']!=writes+1:
            raise RuntimeError('repair_unknown_not_settled_replayed')
        checks.append(CHECKS[5])
        writes=network['mutations']
        result=await repair(uncertain)
        if result['state']!='published' or network['mutations']!=writes:raise RuntimeError('repair_history_replayed')
        checks.append(CHECKS[6])
        await manager.stage(blocked,scope,ledger(),deadline=deadline)
        mode['deny']=True
        await expect(UnauthorizedScope,lambda:repair(blocked))
        mode['deny']=False
        state=await snapshot(blocked)
        if state['document']['active_generation_id']!=uncertain['manifest']['generation_id'] or network['mutations']!=writes:
            raise RuntimeError('repair_callback_denial_mutated')
        checks.append(CHECKS[7])
        network['drop']=True
        await expect(ProviderUnavailable,lambda:manager.publish(reference(blocked),scope,ledger(),deadline=deadline))
        other_scope=TrustedScope.model_validate(inputs['second_scope'])
        other=inputs['second_stage']
        await manager.stage(other,other_scope,ledger(),deadline=deadline)
        network['drop']=True
        await expect(ProviderUnavailable,lambda:manager.publish(reference(other),other_scope,ledger(),deadline=deadline))
        await expect(ProviderUnavailable,lambda:repair(blocked))
        state=await snapshot(blocked)
        foreign=await snapshot(other,other_scope)
        if state['backend']['state']!='recovery_blocked' or not foreign['pending'] or state['pending']:
            raise RuntimeError('repair_foreign_uncertainty_not_preserved')
        checks.append(CHECKS[8])
        observed = dict(preflight=0,recovery=0,publish=0)
        originals = ((writer,'preflight_repair','preflight'),(recovery,'recover','recovery'),(writer,'publish','publish'))
        saved = []
        for owner, name, key in originals:
            actual = getattr(owner,name)
            async def observe(*args,_actual=actual,_key=key,**kwargs):
                observed[_key] += 1
                return await _actual(*args,**kwargs)
            saved.append((owner,name,actual))
            setattr(owner,name,observe)
        writes, requests = network['mutations'], network['requests']
        outage.update(armed=True,stage=blocked,previous=uncertain['manifest']['generation_id'])
        try:
            await expect(ProviderUnavailable,lambda:repair(blocked))
        finally:
            outage['armed']=False
            for owner,name,actual in saved:setattr(owner,name,actual)
        if (outage['entered']!=1 or outage['reads']!=1 or outage['unavailable']!=1
                or any(observed.values()) or network['mutations']!=writes or network['requests']!=requests):
            raise RuntimeError('repair_outage_not_isolated_before_backend')
        await supervisor_resource.close()
        inspection_resource = PoolResource(writer_config)
        try:
            await inspection_resource.open()
            after = await authority_read(inspection_resource,blocked)
        finally:
            await inspection_resource.close()
        if after != outage['before']:raise RuntimeError('repair_outage_changed_authority')
        checks.append(CHECKS[9])
        return dict(runtime='python',checks=checks,proof_scope='native_managed_repair_g1a_only')
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
        raise NativeRepairFailure(dict(ok=False, step=len(checks), error=name if name in ERRORS else 'internal')) from None
    finally:
        failures = []
        cleanup_deadline = asyncio.get_running_loop().time() + 15
        owned = ([('manager_close', manager)] if manager is not None else [])
        owned += [('transport_close', handle) for handle in handles]
        owned += [('recovery_close', recovery), ('writer_close', writer),
            ('resource_close', resource), ('supervisor_resource_close', supervisor_resource)]
        if inspection_resource is not None:owned.append(('inspection_resource_close',inspection_resource))
        owned.append(('controller_close',supervisor))
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
            raise NativeRepairFailure(dict(ok=False, step=len(checks), error='cleanup_failed',
                primary=name if name in ERRORS else ('internal' if name else None), cleanup=failures)) from None
