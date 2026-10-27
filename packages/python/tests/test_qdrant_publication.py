"""Public manager state-machine doubles; native completion is checked separately."""
import asyncio
import copy
from hashlib import sha256
import json
from types import MappingProxyType

import pytest

import cragkit.qdrant_publication as implementation
from cragkit.qdrant_publication import (ManagedQdrantPublicationTransport,
    PostgresQdrantPublicationAuthority, PostgresQdrantRecovery,
    QdrantPublicationManager, QdrantReconciliationVerifier)
from cragkit._qdrant_publication_verification import finalize_publication_projection
from cragkit._qdrant_writer import prepare_stage
from cragkit._qdrant_writer_contract import stage_data
from cragkit.contracts import Limits
from cragkit.execution import BudgetExhausted, ExecutionLedger
from cragkit.errors import (DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest,
    ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)
from test_qdrant_publication_verification import setup as ordinary_setup
from test_qdrant_reconciliation import Handle, run_async
from test_qdrant_writer import config, ctx, stage_input


def ledger():
    return ExecutionLedger(Limits(), deadline=asyncio.get_running_loop().time() + 5)


async def setup(monkeypatch, tmp_path):
    writer, supervisor, _, _, _, document, _, _ = await ordinary_setup(monkeypatch, tmp_path)
    recovery = PostgresQdrantRecovery(writer.resource, config(), supervisor,
        QdrantReconciliationVerifier(writer, supervisor))
    authority = PostgresQdrantPublicationAuthority(writer, recovery)
    transport = ManagedQdrantPublicationTransport(supervisor)
    plan = prepare_stage(stage_input())
    graph = stage_data(plan)
    state = {'intent': None, 'owner': None, 'pending': False, 'dispatches': {},
        'points': [], 'events': [], 'faults': set(), 'handles': [], 'authorizer': None,
        'preparation': None, 'mutations': 0, 'scope_calls': []}

    async def authorize(scope, collection, document_id):
        state['events'].append('authorize')
        state['scope_calls'].append((scope, collection, document_id))
        if state['authorizer'] is not None:
            return await state['authorizer'](scope, collection, document_id)
        return True

    manager = QdrantPublicationManager(authority, transport, config(), supervisor, authorize)

    async def initialize(*, deadline):
        pass

    monkeypatch.setattr(writer, 'initialize', initialize)
    monkeypatch.setattr(recovery, 'initialize', initialize)

    def check_scope(context):
        if context.scope.authorization_revision != document['authorization_revision']:
            raise UnauthorizedScope()

    def terminal():
        if document['tombstoned'] or document['mutation_epoch'] != 1:
            return 'denied'
        if document['active_generation_id'] != graph.intent.expected_active_generation_id:
            return 'conflict'
        return None

    async def snapshot(context, *, deadline):
        check_scope(context)
        return {'intent': copy.deepcopy(state['intent']), 'document': dict(document),
            'owner': state['owner'], 'pending': state['pending'],
            'max_sequence': max(state.get('sequence_base', 0),
                max((item['sequence'] for item in state['dispatches'].values()), default=0)),
            'backend': {'instance_id': 'instance-1', 'backend_namespace': 'fixture-local',
                'storage_identity': 'storage-1', 'supervisor_id': 'supervisor-1',
                'epoch': 2, 'state': 'open', 'recovery_id': None}}

    async def stage(value, scope, *, owner_token, deadline):
        state['events'].append('stage')
        state['intent'] = {'action': 'stage', 'state': 'staged',
            'payload_sha256': plan.payload_sha256, 'manifest_sha256': plan.manifest_sha256,
            'revision_id': graph.manifest.revision_id, 'generation_id': graph.manifest.generation_id,
            'authority_committed': False, 'replica_complete': False, 'purge_complete': False}
        return dict(state['intent'])

    async def admit(context, *, deadline):
        check_scope(context)
        failure = terminal()
        if state['intent']['state'] not in ('published', 'denied', 'conflict') and failure:
            state['intent']['state'] = failure
        if state['intent']['state'] in ('published', 'denied', 'conflict'):
            return {'intent': dict(state['intent']), 'owner': None}
        if state['pending']:
            raise ProviderUnavailable()
        state['owner'] = {'instance_id': 'instance-1', 'intent_id': context.intent_id,
            'owner_token': context.owner_token, 'backend_epoch': 2}
        if state['intent']['state'] == 'staged':
            state['intent']['state'] = 'writing'
        return {'intent': dict(state['intent']), 'owner': {
            'owner_token': context.owner_token, 'backend_epoch': 2}}

    async def load(context, *, deadline):
        return plan

    async def reserve(context, request, *, deadline):
        ids = tuple(request['point_ids'])
        points = writer._projection_points(graph, document)
        body = json.dumps({'points': [{'id': point.point_id,
            'payload': point.payload.model_dump(mode='json'), 'vector': {'dense': list(point.dense.values),
                'sparse': {'indices': list(point.sparse.indices), 'values': list(point.sparse.values)}}}
            for point in points if point.point_id in ids]}, separators=(',', ':')).encode()
        status = {'dispatch_id': request['dispatch_id'], 'sequence': request['sequence'],
            'owner_token': context.owner_token, 'backend_epoch': 2,
            'credential_generation': request['credential_generation'],
            'operation': request['operation'], 'state': 'reserved', 'completion_sha256': None,
            'request_sha256': sha256(body).hexdigest(), 'point_ids': ids}
        state['dispatches'].setdefault(request['dispatch_id'], status)
        state['pending'] = True
        if 'reserve_ack' in state['faults']:
            state['faults'].remove('reserve_ack')
            raise ProviderUnavailable()
        return {**status, 'request_bytes': body}

    async def status(context, identity, *, deadline):
        return state['dispatches'].get(identity)

    async def dispatched(context, identity, *, deadline):
        state['dispatches'][identity]['state'] = 'dispatched'
        if 'mark_ack' in state['faults']:
            state['faults'].remove('mark_ack')
            raise ProviderUnavailable()

    async def unknown(context, identity, *, deadline):
        if identity in state['dispatches']:
            state['dispatches'][identity]['state'] = 'unknown'
        state['pending'] = True

    async def settle(context, identity, digest, *, deadline):
        assert digest == sha256(b'{"status":"ok","result":{"status":"completed","operation_id":1}}').hexdigest()
        state['dispatches'][identity].update(state='settled', completion_sha256=digest)
        state['pending'] = False
        if 'settle_ack' in state['faults']:
            state['faults'].remove('settle_ack')
            raise ProviderUnavailable()

    async def project(context, binding, *, deadline):
        check_scope(context)
        if state['pending']:
            raise ProviderUnavailable()
        return finalize_publication_projection(writer, {'context': context, 'attempt_binding': MappingProxyType(dict(binding)),
            'manifest_sha256': plan.manifest_sha256, 'revision_id': graph.manifest.revision_id,
            'generation_id': graph.manifest.generation_id,
            'authorization_revision': document['authorization_revision'], 'mutation_epoch': document['mutation_epoch'],
            'active_generation_id': document['active_generation_id'], 'tombstoned': False,
            'points': writer._projection_points(graph, document),
            'authority': {key: document[key] for key in ('principal_ids', 'grant_ids', 'language', 'kind', 'tag')}})

    async def prepare(context, digest, *, deadline):
        state['events'].append('prepare')
        state['intent']['state'] = 'prepared'
        state['preparation'] = {'owner_token': context.owner_token, 'backend_epoch': 2,
            'authorization_revision': document['authorization_revision'], 'mutation_epoch': document['mutation_epoch'],
            'manifest_sha256': plan.manifest_sha256, 'readback_sha256': digest}
        if 'prepare_ack' in state['faults']:
            state['faults'].remove('prepare_ack')
            raise ProviderUnavailable()
        return dict(state['intent'])

    async def preparation(context, *, deadline):
        if state['preparation'] is None:
            return None
        last = max(state['dispatches'].values(), key=lambda item: item['sequence'])
        return {'preparation': dict(state['preparation']), 'dispatch': dict(last)}

    async def publish(context, *, deadline):
        state['events'].append('publish')
        failure = terminal()
        if failure:
            state['intent']['state'] = failure
        else:
            state['intent'].update(state='published', authority_committed=True, replica_complete=True)
            document['active_generation_id'] = graph.manifest.generation_id
        if 'publish_ack' in state['faults']:
            state['faults'].remove('publish_ack')
            raise ProviderUnavailable()
        return dict(state['intent'])

    methods = {'manager_snapshot': snapshot, 'stage': stage, 'admit_publication': admit,
        'load_stage': load, 'reserve_dispatch': reserve, 'dispatch_status': status,
        'mark_dispatched': dispatched, 'mark_unknown': unknown, 'settle_dispatch': settle,
        'project_publication': project, 'prepare': prepare, 'publication_preparation': preparation,
        'publish': publish}
    for name, method in methods.items():
        monkeypatch.setattr(writer, name, method)

    class NativeHandle(Handle):
        async def request(self, method, path, *, body=None, deadline, max_response_bytes=1048576):
            if method == 'PUT':
                state['mutations'] += 1
                state['events'].append('http')
                state['points'][:] = json.loads(body)['points']
                if 'http_ack' in state['faults']:
                    raise ProviderUnavailable()
                if 'queued_ack' in state['faults']:
                    return b'{"status":"ok","result":{"status":"acknowledged"}}'
                if 'extra_ack' in state['faults']:
                    return b'{"status":"ok","result":{"status":"completed","unexpected":true}}'
                return b'{"status":"ok","result":{"status":"completed","operation_id":1}}'
            return await super().request(method, path, body=body, deadline=deadline,
                                         max_response_bytes=max_response_bytes)

    def handle(capability):
        supervisor.attempt_binding(capability)
        result = NativeHandle(state['points'])
        state['handles'].append(result)
        return result

    monkeypatch.setattr(supervisor, 'transport_for', handle)
    return manager, writer, recovery, supervisor, transport, state, document


async def stage_and_publish(manager):
    limit = asyncio.get_running_loop().time() + 5
    staged = await manager.stage(stage_input(), ctx()['scope'], ledger(), deadline=limit)
    published = await manager.publish({key: ctx()[key] for key in ('collection', 'document_id', 'intent_id')},
        ctx()['scope'], ledger(), deadline=limit)
    return staged, published


@run_async
async def test_public_stage_publish_historical_retry_and_zero_model_usage(monkeypatch, tmp_path):
    manager, writer, recovery, supervisor, _, state, document = await setup(monkeypatch, tmp_path)
    with pytest.raises(IndexNotReady):
        await manager.stage(stage_input(), ctx()['scope'], ledger(), deadline=asyncio.get_running_loop().time() + 5)
    await manager.initialize(deadline=asyncio.get_running_loop().time() + 5)
    budget = ledger()
    result = await manager.stage(stage_input(), ctx()['scope'], budget,
        deadline=asyncio.get_running_loop().time() + 5)
    assert result['state'] == 'staged' and state['mutations'] == 0
    assert budget.snapshot()['provider_calls'] == 0
    assert budget.snapshot()['candidates'] == 0 and budget.snapshot()['attempts'] == 1
    _, published = await stage_and_publish(manager)
    assert published['published'] and state['mutations'] == 1
    assert set(published) == {'intent_id', 'operation', 'state', 'revision_id', 'generation_id',
        'authority_committed', 'replica_complete', 'published', 'purge_complete'}
    with pytest.raises(TypeError):
        published['owner_token'] = 'forged'
    document.update(authorization_revision='auth-2', mutation_epoch=2, active_generation_id='newer')
    fresh = {**ctx()['scope'], 'authorization_revision': 'auth-2'}
    historical = await manager.stage(stage_input(), fresh, ledger(), deadline=asyncio.get_running_loop().time() + 5)
    assert historical['published'] and document['active_generation_id'] == 'newer'
    assert state['mutations'] == 1
    await manager.close()
    assert not writer._closed and not recovery._closed and not supervisor._closed


@pytest.mark.parametrize('fault', ['reserve_ack', 'mark_ack', 'settle_ack', 'prepare_ack', 'publish_ack'])
@run_async
async def test_same_identity_sql_ack_reconciliation_never_resends_http(monkeypatch, tmp_path, fault):
    manager, _, _, _, _, state, _ = await setup(monkeypatch, tmp_path)
    await manager.initialize(deadline=asyncio.get_running_loop().time() + 5)
    state['faults'].add(fault)
    _, result = await stage_and_publish(manager)
    assert result['published'] and state['mutations'] == 1
    assert len(state['dispatches']) == 1


@pytest.mark.parametrize('fault,error', [('http_ack', ProviderUnavailable),
    ('queued_ack', IntegrityViolation), ('extra_ack', IntegrityViolation)])
@run_async
async def test_uncertain_http_never_replayed_or_published(monkeypatch, tmp_path, fault, error):
    manager, _, _, _, _, state, document = await setup(monkeypatch, tmp_path)
    await manager.initialize(deadline=asyncio.get_running_loop().time() + 5)
    state['faults'].add(fault)
    with pytest.raises(error):
        await stage_and_publish(manager)
    assert state['mutations'] == 1 and state['pending']
    assert next(iter(state['dispatches'].values()))['state'] == 'unknown'
    reference = {key: ctx()[key] for key in ('collection', 'document_id', 'intent_id')}
    with pytest.raises(ProviderUnavailable):
        await manager.publish(reference, ctx()['scope'], ledger(), deadline=asyncio.get_running_loop().time() + 5)
    assert state['mutations'] == 1 and document['active_generation_id'] == 'gen-1'


@pytest.mark.parametrize('allowed,error', [(False, UnauthorizedScope), (1, InvalidRequest)])
@run_async
async def test_callback_result_and_ledger_boundaries(monkeypatch, tmp_path, allowed, error):
    manager, _, _, _, _, state, _ = await setup(monkeypatch, tmp_path)
    await manager.initialize(deadline=asyncio.get_running_loop().time() + 5)

    async def authorize(*args):
        return allowed

    state['authorizer'] = authorize
    with pytest.raises(error):
        await manager.stage(stage_input(), ctx()['scope'], ledger(), deadline=asyncio.get_running_loop().time() + 5)
    assert 'stage' not in state['events'] and state['mutations'] == 0
    with pytest.raises(InvalidRequest):
        await manager.stage(stage_input(), ctx()['scope'], None, deadline=asyncio.get_running_loop().time() + 5)


@run_async
async def test_constructor_graph_and_public_input_shapes_are_nominal_before_io(monkeypatch, tmp_path):
    manager, writer, recovery, supervisor, transport, state, _ = await setup(monkeypatch, tmp_path)
    authority = PostgresQdrantPublicationAuthority(writer, recovery)
    changed = config()
    changed['physical_collection'] = 'other_collection'
    with pytest.raises(UnsupportedCapability):
        QdrantPublicationManager(authority, transport, changed, supervisor, lambda *args: True)
    phantom = object.__new__(PostgresQdrantRecovery)
    holder = PostgresQdrantPublicationAuthority(writer, phantom)
    with pytest.raises(InvalidRequest):
        QdrantPublicationManager(holder, transport, config(), supervisor, lambda *args: True)
    with pytest.raises(InvalidRequest):
        ManagedQdrantPublicationTransport({})
    with pytest.raises(InvalidRequest):
        await manager.publish({**{key: ctx()[key] for key in ('collection', 'document_id', 'intent_id')},
            'owner_token': ctx()['owner_token']}, ctx()['scope'], ledger(),
            deadline=asyncio.get_running_loop().time() + 5)
    with pytest.raises(UnauthorizedScope):
        await manager.stage(stage_input(), {**ctx()['scope'], 'tenant_id': 'foreign'}, ledger(),
            deadline=asyncio.get_running_loop().time() + 5)
    assert state['events'] == [] and state['mutations'] == 0


@run_async
async def test_transport_host_close_rejects_sessions_without_closing_supervisor(monkeypatch, tmp_path):
    manager, _, _, supervisor, transport, _, _ = await setup(monkeypatch, tmp_path)
    session = transport._open({'intent_id': ctx()['intent_id'], 'owner_token': ctx()['owner_token'],
        'epoch': 2, 'dispatch_id': 'host-close'}, deadline=asyncio.get_running_loop().time() + 5)
    await transport.close()
    assert session.closed and not supervisor._closed
    with pytest.raises(ProviderUnavailable):
        transport._open({'intent_id': ctx()['intent_id'], 'owner_token': ctx()['owner_token'],
            'epoch': 2, 'dispatch_id': 'new'}, deadline=asyncio.get_running_loop().time() + 5)
    await manager.close()


@run_async
async def test_callback_exception_is_redacted_and_no_admission_occurs(monkeypatch, tmp_path):
    manager, _, _, _, _, state, _ = await setup(monkeypatch, tmp_path)
    await manager.initialize(deadline=asyncio.get_running_loop().time() + 5)

    async def authorize(*args):
        raise RuntimeError('PRIVATE_CALLBACK_CANARY')

    state['authorizer'] = authorize
    with pytest.raises(ProviderUnavailable) as caught:
        await manager.stage(stage_input(), ctx()['scope'], ledger(), deadline=asyncio.get_running_loop().time() + 5)
    assert 'PRIVATE' not in str(caught.value) and caught.value.__cause__ is None
    assert 'stage' not in state['events'] and state['mutations'] == 0


@run_async
async def test_final_session_excludes_lifecycle_and_publish_persists_late_denial(monkeypatch, tmp_path):
    manager, _, _, supervisor, _, state, document = await setup(monkeypatch, tmp_path)
    await manager.initialize(deadline=asyncio.get_running_loop().time() + 5)
    observed = []

    async def authorize(*args):
        if state['intent'] is not None and state['intent']['state'] == 'prepared':
            with pytest.raises(ProviderUnavailable):
                supervisor.block_ordinary()
            observed.append('excluded')
            document.update(authorization_revision='auth-2', mutation_epoch=2)
        return True

    state['authorizer'] = authorize
    _, result = await stage_and_publish(manager)
    assert result['state'] == 'denied' and not result['published']
    assert observed == ['excluded'] and document['active_generation_id'] == 'gen-1'


@run_async
async def test_prepared_resume_retains_owner_and_witness_without_second_mutation(monkeypatch, tmp_path):
    manager, writer, _, _, transport, state, _ = await setup(monkeypatch, tmp_path)
    await manager.initialize(deadline=asyncio.get_running_loop().time() + 5)
    original_publish = writer.publish

    async def stop_before_cas(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(writer, 'publish', stop_before_cas)
    with pytest.raises(asyncio.CancelledError):
        await stage_and_publish(manager)
    original_owner = state['preparation']['owner_token']
    state['owner'] = {'instance_id': 'instance-1', 'intent_id': 'quiescent-other-intent',
        'owner_token': '22222222-2222-4222-8222-222222222222', 'backend_epoch': 2}
    monkeypatch.setattr(writer, 'publish', original_publish)
    reference = {key: ctx()[key] for key in ('collection', 'document_id', 'intent_id')}
    result = await manager.publish(reference, ctx()['scope'], ledger(), deadline=asyncio.get_running_loop().time() + 5)
    assert result['published'] and state['mutations'] == 1
    assert state['owner']['owner_token'] == original_owner
    with pytest.raises(InvalidRequest):
        transport._ack_hash(implementation._Acknowledgment(), object())


@run_async
async def test_persistent_sequence_limit_is_budget_exhaustion_without_dispatch(monkeypatch, tmp_path):
    manager, _, _, _, _, state, _ = await setup(monkeypatch, tmp_path)
    await manager.initialize(deadline=asyncio.get_running_loop().time() + 5)
    await manager.stage(stage_input(), ctx()['scope'], ledger(), deadline=asyncio.get_running_loop().time() + 5)
    state['sequence_base'] = 256
    reference = {key: ctx()[key] for key in ('collection', 'document_id', 'intent_id')}
    with pytest.raises(BudgetExhausted):
        await manager.publish(reference, ctx()['scope'], ledger(), deadline=asyncio.get_running_loop().time() + 5)
    assert state['mutations'] == 0 and state['dispatches'] == {}


@pytest.mark.parametrize('change,error', [('digest', IntegrityViolation), ('credential', ProviderUnavailable)])
@run_async
async def test_prepared_resume_rejects_witness_or_retired_credential_without_writes(monkeypatch, tmp_path, change, error):
    manager, writer, _, _, _, state, _ = await setup(monkeypatch, tmp_path)
    await manager.initialize(deadline=asyncio.get_running_loop().time() + 5)
    original_publish = writer.publish

    async def stop(*args, **kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(writer, 'publish', stop)
    with pytest.raises(asyncio.CancelledError):
        await stage_and_publish(manager)
    monkeypatch.setattr(writer, 'publish', original_publish)
    if change == 'digest':
        state['preparation']['readback_sha256'] = 'e' * 64
    else:
        next(iter(state['dispatches'].values()))['credential_generation'] = 'retired'
    reference = {key: ctx()[key] for key in ('collection', 'document_id', 'intent_id')}
    with pytest.raises(error):
        await manager.publish(reference, ctx()['scope'], ledger(), deadline=asyncio.get_running_loop().time() + 5)
    assert state['mutations'] == 1 and state['intent']['state'] == 'prepared'


@run_async
async def test_uncooperative_callback_keeps_manager_closed_until_actual_unwind(monkeypatch, tmp_path):
    manager, _, _, _, _, state, _ = await setup(monkeypatch, tmp_path)
    await manager.initialize(deadline=asyncio.get_running_loop().time() + 5)
    entered, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(implementation, '_CLEANUP_SECONDS', 0.01)

    async def authorize(*args):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()
        return True

    state['authorizer'] = authorize
    task = asyncio.create_task(manager.stage(stage_input(), ctx()['scope'], ledger(),
        deadline=asyncio.get_running_loop().time() + 0.03))
    await entered.wait()
    with pytest.raises(DeadlineExceeded):
        await task
    assert manager._active is not None and manager._closed
    with pytest.raises(ProviderUnavailable):
        await manager.stage(stage_input(), ctx()['scope'], ledger(), deadline=asyncio.get_running_loop().time() + 5)
    release.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert 'stage' not in state['events'] and state['mutations'] == 0


@pytest.mark.parametrize('boundary', ['stage', 'final_publish'])
@run_async
async def test_explicit_cancellation_is_latched_after_callback_suppresses_it(monkeypatch, tmp_path, boundary):
    manager, writer, recovery, supervisor, _, state, document = await setup(monkeypatch, tmp_path)
    await manager.initialize(deadline=asyncio.get_running_loop().time() + 5)
    entered, release = asyncio.Event(), asyncio.Event()
    monkeypatch.setattr(implementation, '_CLEANUP_SECONDS', 0.01)

    async def authorize(*args):
        selected = ((boundary == 'stage' and state['intent'] is None)
                    or (boundary == 'final_publish' and state['intent'] is not None
                        and state['intent']['state'] == 'prepared'))
        if selected:
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
        return True

    state['authorizer'] = authorize
    if boundary == 'stage':
        operation = manager.stage(stage_input(), ctx()['scope'], ledger(),
            deadline=asyncio.get_running_loop().time() + 5)
    else:
        operation = stage_and_publish(manager)
    caller = asyncio.create_task(operation)
    await entered.wait()
    child = manager._active
    assert child is not None
    caller.cancel()
    with pytest.raises(asyncio.CancelledError):
        await caller
    assert manager._closed and manager._cancelled and manager._active is child
    before = list(state['events'])
    if boundary == 'final_publish':
        assert state['intent']['state'] == 'prepared'
        assert supervisor._control_token is not None
        with pytest.raises(ProviderUnavailable):
            supervisor.block_ordinary()
    with pytest.raises(ProviderUnavailable):
        await manager.stage(stage_input(), ctx()['scope'], ledger(),
            deadline=asyncio.get_running_loop().time() + 5)
    # Resume before the original five-second deadline. Cancellation, rather
    # than expiry, must prohibit every later stage/prepare/publication step.
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await child
    await asyncio.sleep(0)
    assert state['events'] == before and 'publish' not in state['events']
    assert document['active_generation_id'] == 'gen-1'
    assert supervisor._control_token is None and manager._active is None
    assert not writer._closed and not recovery._closed and not supervisor._closed
