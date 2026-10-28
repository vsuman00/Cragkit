"""Ordinary readback behavior; physical/SQL integration runs belong to root."""
import asyncio
import copy
import json

import pytest

import cragkit._qdrant_publication_verification as implementation
from cragkit._qdrant_publication_verification import (
    PublicationProjection, PublicationReadbackReceipt, QdrantPublicationVerifier,
    publication_projection_data, publication_receipt_data, attestation_receipt_data,
)
from cragkit._qdrant_publication_worker import controller_finalization
from cragkit.errors import (DeadlineExceeded, IntegrityViolation, InvalidRequest,
                            ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)
from test_qdrant_reconciliation import run_async, setup as recovery_setup
from test_qdrant_writer import ctx


async def setup(monkeypatch, tmp_path, *, member_count=2):
    writer, supervisor, proof, _, handle, document, _ = await recovery_setup(
        monkeypatch, tmp_path, member_count=member_count,
    )
    original = writer._query
    state = {'pending': False, 'backend': ('fixture-local', 'storage-1', 'supervisor-1',
                                         2, 'open', None), 'owner': True}

    async def query(connection, sql, params=()):
        if sql.startswith('SELECT backend_namespace,storage_identity'):
            return [state['backend']] if state['backend'] is not None else []
        if sql.startswith('SELECT dispatch_id FROM cragkit_qdrant.dispatch_journal'):
            return [('unknown',)] if state['pending'] else []
        if sql.startswith('SELECT owner_token::text,intent_id,backend_epoch,instance_id'):
            return [(ctx()['owner_token'], 'intent-2', 2, 'instance-1')] if state['owner'] else []
        return await original(connection, sql, params)

    monkeypatch.setattr(writer, '_query', query)
    supervisor._gate = True
    attempt = supervisor.issue_attempt({
        'intent_id': 'intent-2', 'owner_token': ctx()['owner_token'],
        'epoch': 2, 'dispatch_id': 'dispatch-ordinary',
    }, deadline=asyncio.get_running_loop().time() + 5)
    verifier = QdrantPublicationVerifier(writer, supervisor)
    return writer, supervisor, attempt, verifier, handle, document, state, proof


@run_async
async def test_full_ordinary_readback_private_receipt_and_witness(monkeypatch, tmp_path):
    writer, supervisor, attempt, verifier, handle, _, _, _ = await setup(monkeypatch, tmp_path)
    receipt = await verifier.verify(attempt, ctx(), deadline=asyncio.get_running_loop().time() + 5)
    data = publication_receipt_data(receipt, verifier)
    assert len(data['witness']) == 21
    assert data['witness'][0] == 'cragkit.qdrant.publication.readback.v1'
    assert data['witness'][4] == '2' and data['witness'][18] == 'false'
    assert json.loads(data['encoded_bytes']) == json.loads(json.dumps(data['witness']))
    assert data['sha256'] == data['readback_sha256']
    assert handle.close_count == 1 and len(handle.calls) == 2
    assert not writer._active
    assert 'PRIVATE' not in repr(receipt) + repr(data['witness'])
    with pytest.raises(TypeError):
        data['sha256'] = 'changed'
    for forged in (PublicationReadbackReceipt(), {}, dict(data)):
        with pytest.raises(InvalidRequest):
            publication_receipt_data(forged, verifier)
    with pytest.raises(InvalidRequest):
        publication_projection_data(PublicationProjection(), writer)
    supervisor._credential_generation = 'rotated'
    with pytest.raises(ProviderUnavailable):
        publication_receipt_data(receipt, verifier)


@run_async
async def test_attestation_receipt_requires_original_issuer_and_acquired_helper(monkeypatch, tmp_path):
    writer, supervisor, attempt, verifier, _, _, _, _ = await setup(monkeypatch, tmp_path)
    end = asyncio.get_running_loop().time() + 5
    receipt = await verifier.verify(attempt, ctx(), deadline=end)
    expected = publication_receipt_data(receipt, verifier)
    with pytest.raises(InvalidRequest):
        await attestation_receipt_data(receipt, verifier, writer, deadline=end)
    async with supervisor.control_session():
        with pytest.raises(InvalidRequest):
            await attestation_receipt_data(receipt, verifier, writer, deadline=end)
    other_verifier = QdrantPublicationVerifier(writer, supervisor)
    async with controller_finalization(supervisor, attempt, deadline=end):
        actual = await attestation_receipt_data(receipt, verifier, writer, deadline=end - .1)
        assert actual is expected
        with pytest.raises(TypeError):
            actual['readback_sha256'] = 'changed'
        for forged, issuer, owner in ((PublicationReadbackReceipt(), verifier, writer),
                (dict(expected), verifier, writer), (receipt, other_verifier, writer),
                (receipt, verifier, object()), (receipt, object.__new__(QdrantPublicationVerifier), writer)):
            with pytest.raises(InvalidRequest):
                await attestation_receipt_data(forged, issuer, owner, deadline=end)
        for copier in (copy.copy, copy.deepcopy):
            with pytest.raises(TypeError):
                copier(receipt)
        async def inherited():
            with pytest.raises(InvalidRequest):
                await attestation_receipt_data(receipt, verifier, writer, deadline=end)
        await asyncio.create_task(inherited())
        with pytest.raises(InvalidRequest):
            await attestation_receipt_data(receipt, verifier, writer, deadline=end + 1)
    with pytest.raises(InvalidRequest):
        await attestation_receipt_data(receipt, verifier, writer, deadline=end)


@run_async
async def test_attestation_receipt_rejects_foreign_context_rebound_verifier_and_retired_attempt(monkeypatch, tmp_path):
    from cragkit._qdrant_supervisor import ManagedQdrantSupervisor
    from test_qdrant_writer import config
    writer, supervisor, attempt, verifier, _, _, _, _ = await setup(monkeypatch, tmp_path)
    end = asyncio.get_running_loop().time() + 5
    receipt = await verifier.verify(attempt, ctx(), deadline=end)
    foreign = ManagedQdrantSupervisor(tmp_path/'other', tmp_path/'other-work', 'other-instance', config())
    async with controller_finalization(foreign, object(), deadline=end):
        with pytest.raises(InvalidRequest):
            await attestation_receipt_data(receipt, verifier, writer, deadline=end)
    async with controller_finalization(supervisor, attempt, deadline=end):
        verifier.supervisor = foreign
        with pytest.raises(InvalidRequest):
            await attestation_receipt_data(receipt, verifier, writer, deadline=end)
        verifier.supervisor = supervisor
        verifier.writer = object()
        with pytest.raises(InvalidRequest):
            await attestation_receipt_data(receipt, verifier, writer, deadline=end)
        verifier.writer = writer
        supervisor._credential_generation = 'retired-attempt'
        with pytest.raises(ProviderUnavailable):
            await attestation_receipt_data(receipt, verifier, writer, deadline=end)


@run_async
async def test_attestation_checks_context_again_after_awaited_validation(monkeypatch, tmp_path):
    writer, supervisor, attempt, verifier, _, _, _, _ = await setup(monkeypatch, tmp_path)
    end = asyncio.get_running_loop().time() + 5
    receipt = await verifier.verify(attempt, ctx(), deadline=end)
    original = implementation.validate_publication_receipt
    async def rebind_after_validation(value, issuer, *, deadline):
        result = await original(value, issuer, deadline=deadline)
        await asyncio.sleep(0)
        issuer.writer = object()
        return result
    monkeypatch.setattr(implementation, 'validate_publication_receipt', rebind_after_validation)
    async with controller_finalization(supervisor, attempt, deadline=end):
        with pytest.raises(InvalidRequest):
            await attestation_receipt_data(receipt, verifier, writer, deadline=end)
    verifier.writer = writer
    expected = publication_receipt_data(receipt, verifier)
    async def expiry_after_validation(value, issuer, *, deadline):
        # Unit seam isolates expiry across the awaited controller validation.
        await asyncio.sleep(.02)
        return expected
    monkeypatch.setattr(implementation, 'validate_publication_receipt', expiry_after_validation)
    end = asyncio.get_running_loop().time() + .01
    async with controller_finalization(supervisor, attempt, deadline=end):
        with pytest.raises(DeadlineExceeded):
            await attestation_receipt_data(receipt, verifier, writer, deadline=end)


@pytest.mark.parametrize('case', ['pending', 'owner', 'blocked', 'epoch', 'missing', 'tombstone'])
@run_async
async def test_unavailable_authority_refuses_before_http(monkeypatch, tmp_path, case):
    _, _, attempt, verifier, handle, document, state, _ = await setup(monkeypatch, tmp_path)
    if case == 'pending':
        state['pending'] = True
    elif case == 'owner':
        state['owner'] = False
    elif case == 'blocked':
        state['backend'] = (*state['backend'][:4], 'recovery_blocked', 'recovery-1')
    elif case == 'epoch':
        state['backend'] = (*state['backend'][:3], 3, 'open', None)
    elif case == 'missing':
        state['backend'] = None
    else:
        document['tombstoned'] = True
    expected = UnauthorizedScope if case == 'tombstone' else ProviderUnavailable
    with pytest.raises(expected):
        await verifier.verify(attempt, ctx(), deadline=asyncio.get_running_loop().time() + 5)
    assert not handle.calls and handle.close_count == 0


@pytest.mark.parametrize('case', ['extra', 'vector', 'payload', 'duplicate'])
@run_async
async def test_full_set_vector_and_payload_integrity(monkeypatch, tmp_path, case):
    _, _, attempt, verifier, handle, _, _, _ = await setup(monkeypatch, tmp_path)
    if case == 'extra':
        extra = copy.deepcopy(handle.points[0])
        extra['id'] = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'
        handle.points.append(extra)
    elif case == 'vector':
        handle.points[0]['vector']['dense'] = [0.0, 0.0, 1.0] + [0.0] * 1533
    elif case == 'payload':
        handle.points[0]['payload']['tag'] = 'wrong'
    else:
        handle.get_patch = lambda points: [points[0], points[0]]
    with pytest.raises(IntegrityViolation):
        await verifier.verify(attempt, ctx(), deadline=asyncio.get_running_loop().time() + 5)
    assert handle.close_count == 1


@run_async
async def test_late_authority_change_and_cleanup_failure_never_issue_receipt(monkeypatch, tmp_path):
    _, _, attempt, verifier, handle, document, _, _ = await setup(monkeypatch, tmp_path)
    handle.on_request = lambda: document.update(tag='changed')
    with pytest.raises(UnauthorizedScope):
        await verifier.verify(attempt, ctx(), deadline=asyncio.get_running_loop().time() + 5)
    handle.on_request = None
    handle.close_failure = True
    with pytest.raises(ProviderUnavailable) as caught:
        await verifier.verify(attempt, ctx(), deadline=asyncio.get_running_loop().time() + 5)
    assert 'PRIVATE' not in str(caught.value) and caught.value.__cause__ is None


@pytest.mark.parametrize('field,value', [
    ('backend_namespace', 'foreign-namespace'),
    ('storage_identity', 'foreign-storage'),
    ('supervisor_id', 'foreign-supervisor'),
])
@run_async
async def test_backend_identity_contradiction_is_integrity(monkeypatch, tmp_path, field, value):
    _, _, attempt, verifier, handle, _, state, _ = await setup(monkeypatch, tmp_path)
    row = list(state['backend'])
    row[{'backend_namespace': 0, 'storage_identity': 1, 'supervisor_id': 2}[field]] = value
    state['backend'] = tuple(row)
    with pytest.raises(IntegrityViolation):
        await verifier.verify(attempt, ctx(), deadline=asyncio.get_running_loop().time() + 5)
    assert handle.calls == []


@run_async
async def test_current_authority_revalidation_and_private_projection_issuer(monkeypatch, tmp_path):
    writer, supervisor, attempt, _, _, document, _, _ = await setup(monkeypatch, tmp_path)
    deadline = asyncio.get_running_loop().time() + 5
    projection = await writer.project_publication(
        ctx(), dict(supervisor.attempt_binding(attempt)), deadline=deadline,
    )
    with pytest.raises(InvalidRequest):
        publication_projection_data(projection, object())
    document['grant_ids'] = ['changed-grant']
    with pytest.raises(UnauthorizedScope):
        await writer.validate_publication_projection(projection, deadline=deadline)


@run_async
async def test_actual_attempt_only_and_target_match(monkeypatch, tmp_path):
    writer, supervisor, attempt, verifier, handle, _, _, proof = await setup(monkeypatch, tmp_path)
    for forged in ({}, proof):
        with pytest.raises(InvalidRequest):
            await verifier.verify(forged, ctx(), deadline=asyncio.get_running_loop().time() + 5)
    binding = dict(supervisor.attempt_binding(attempt))
    binding['intent_id'] = 'other-intent'
    with pytest.raises(UnsupportedCapability):
        await writer.project_publication(ctx(), binding, deadline=asyncio.get_running_loop().time() + 5)
    assert not handle.calls


@run_async
async def test_bounded_64_members_and_no_sql_lease_during_http(monkeypatch, tmp_path):
    writer, _, attempt, verifier, handle, _, _, _ = await setup(monkeypatch, tmp_path, member_count=64)
    handle.on_request = lambda: (_ for _ in ()).throw(AssertionError()) if writer._active else None
    receipt = await verifier.verify(attempt, ctx(), deadline=asyncio.get_running_loop().time() + 5)
    assert len(publication_receipt_data(receipt, verifier)['point_ids']) == 64
    assert len(handle.calls) == 16


@run_async
async def test_cancel_close_and_borrowed_resources(monkeypatch, tmp_path):
    writer, supervisor, attempt, verifier, handle, _, _, _ = await setup(monkeypatch, tmp_path)
    entered = asyncio.Event()

    async def blocked(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(handle, 'request', blocked)
    task = asyncio.create_task(verifier.verify(attempt, ctx(),
        deadline=asyncio.get_running_loop().time() + 5))
    await entered.wait()
    with pytest.raises(ProviderUnavailable):
        await verifier.verify(attempt, ctx(), deadline=asyncio.get_running_loop().time() + 5)
    await verifier.close()
    assert task.cancelled() and handle.close_count == 1
    assert not writer._closed and not supervisor._closed
    with pytest.raises(ProviderUnavailable):
        await verifier.verify(attempt, ctx(), deadline=asyncio.get_running_loop().time() + 5)


@run_async
async def test_late_deadline_has_no_receipt(monkeypatch, tmp_path):
    _, _, attempt, verifier, handle, _, _, _ = await setup(monkeypatch, tmp_path)
    original = handle.request

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.05)
        return await original(*args, **kwargs)

    monkeypatch.setattr(handle, 'request', slow)
    with pytest.raises(DeadlineExceeded):
        await verifier.verify(attempt, ctx(), deadline=asyncio.get_running_loop().time() + 0.01)
    assert handle.close_count == 1


@run_async
async def test_hanging_handle_cleanup_is_bounded_operational_failure(monkeypatch, tmp_path):
    writer, supervisor, attempt, verifier, handle, _, _, _ = await setup(monkeypatch, tmp_path)
    entered = asyncio.Event()

    async def hanging_close():
        handle.close_count += 1
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(handle, 'close', hanging_close)
    monkeypatch.setattr(implementation, '_CLEANUP_SECONDS', 0.01)
    started = asyncio.get_running_loop().time()
    with pytest.raises(ProviderUnavailable):
        await verifier.verify(attempt, ctx(), deadline=started + 5)
    assert entered.is_set() and asyncio.get_running_loop().time() - started < 0.5
    assert verifier._active is None
    assert not writer._closed and not supervisor._closed
