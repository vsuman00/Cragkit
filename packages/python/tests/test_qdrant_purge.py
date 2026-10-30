"""Purge capability and receipt wiring; native erasure is verified separately."""
import asyncio
from hashlib import sha256
import json
import pickle
from types import MappingProxyType

import pytest

import cragkit._qdrant_writer as writer_module
from cragkit._qdrant_publication_worker import controller_finalization
from cragkit._qdrant_security_readback import SecurityReadbackBudget
from cragkit._qdrant_security_verification import (
    PurgeAbsenceReceipt, purge_absence_receipt_data, verify_purge_ordinary,
)
from cragkit._qdrant_writer import PURGE_POLICY, PurgeProjection, purge_projection_data
from cragkit._qdrant_writer_contract import context
from cragkit.errors import IntegrityViolation, InvalidRequest, UnauthorizedScope, UnsupportedCapability
from cragkit.qdrant_publication import QdrantPublicationManager
from test_qdrant_security_verification import ordinary_setup
from test_qdrant_writer import run_async


def deadline():
    return asyncio.get_running_loop().time()+5


async def setup(monkeypatch,tmp_path,*,empty=False):
    values,_ = await ordinary_setup(monkeypatch,tmp_path,tombstoned=True,empty=empty)
    verifier,writer,supervisor,_,_,security,_,_,handle = values
    tombstone = context(security)
    current = context({**security,'intent_id':'purge-current'})
    # Only this receipt test substitutes projection SQL. Its graph is produced
    # by the existing bounded reconstruction fixture and genuine absence I/O.
    source = await writer.project_security(tombstone,deadline=deadline())
    source_data = writer_module.security_projection_data(source,writer)
    projection = PurgeProjection()
    projected = MappingProxyType(dict(context=current,tombstone_context=tombstone,
        purge_payload_sha256='a'*64,tombstone_payload_sha256=source_data['intent_sha256'],
        inventory_sha256=source_data['inventory_sha256'],inventory_bytes=b'fixture-inventory',
        policy_id=PURGE_POLICY,projection=source))
    writer_module._PURGE_PROJECTIONS[projection] = (writer,projected)
    writer._schema_profile = 5
    calls = []
    async def validate(selected,*,deadline):
        assert selected is projection
        calls.append(selected)
    monkeypatch.setattr(writer,'validate_purge_projection',validate)
    attempt = supervisor.issue_attempt(dict(intent_id=current.intent_id,owner_token=current.owner_token,
        epoch=2,dispatch_id='purge-absence-fixture'),deadline=deadline())
    return verifier,writer,supervisor,current,projection,attempt,handle,calls


@pytest.mark.parametrize('empty',[False,True])
@run_async
async def test_purge_receipt_exact_ten_fields_and_witness(monkeypatch,tmp_path,empty):
    verifier,writer,supervisor,current,projection,attempt,handle,calls = await setup(monkeypatch,tmp_path,empty=empty)
    limit = deadline()
    budget = SecurityReadbackBudget()
    receipt = await verify_purge_ordinary(verifier,attempt,current,projection,deadline=limit,budget=budget)
    with pytest.raises(InvalidRequest):
        purge_absence_receipt_data(receipt,verifier,deadline=limit)
    async with controller_finalization(supervisor,attempt,deadline=limit):
        data = purge_absence_receipt_data(receipt,verifier,deadline=limit)
        assert set(data) == {'context','tombstone_context','projection','attempt_binding','purge_payload_sha256',
            'inventory_sha256','absence_sha256','witness','encoded_bytes','sha256'}
        witness = json.loads(data['encoded_bytes'])
        assert len(witness) == 14
        assert witness[:8] == ['cragkit.qdrant.purge-ordinary-absence.v1','instance-1','storage-1',
            'supervisor-1','credential-2','2','purge-current',current.owner_token]
        assert witness[12] == PURGE_POLICY
        assert data['absence_sha256'] == data['sha256'] == sha256(data['encoded_bytes']).hexdigest()
        assert len(calls) == 2
        assert budget.remaining_calls == 513-len(handle.calls)
        assert any('/scroll' in call[1] for call in handle.calls)
        for fake in (PurgeAbsenceReceipt(),dict(data),object()):
            with pytest.raises(InvalidRequest):
                purge_absence_receipt_data(fake,verifier,deadline=limit)
        with pytest.raises(InvalidRequest):
            purge_absence_receipt_data(receipt,verifier,deadline=limit+1)
        with pytest.raises(TypeError):
            pickle.dumps(receipt)
    await verifier.close()


@run_async
async def test_purge_receipt_rejects_changed_authority_after_readback(monkeypatch,tmp_path):
    verifier,writer,_,current,projection,attempt,_,_ = await setup(monkeypatch,tmp_path)
    count = 0
    async def changed(selected,*,deadline):
        nonlocal count
        count += 1
        if count == 2:
            raise UnauthorizedScope()
    monkeypatch.setattr(writer,'validate_purge_projection',changed)
    with pytest.raises(UnauthorizedScope):
        await verify_purge_ordinary(verifier,attempt,current,projection,deadline=deadline())
    await verifier.close()


@run_async
async def test_purge_receipt_rejects_an_observed_claimed_point(monkeypatch,tmp_path):
    verifier,writer,_,current,projection,attempt,handle,_ = await setup(monkeypatch,tmp_path)
    source = writer_module.security_projection_data(purge_projection_data(projection,writer)['projection'],writer)
    point = source['points'][0]
    handle.points.append(dict(id=point.point_id,payload=point.payload.model_dump(mode='json'),
        vector=dict(dense=list(point.dense.values),sparse=dict(indices=list(point.sparse.indices),values=list(point.sparse.values)))))
    with pytest.raises(IntegrityViolation):
        await verify_purge_ordinary(verifier,attempt,current,projection,deadline=deadline())
    await verifier.close()


@run_async
async def test_purge_policy_is_rejected_before_dependency_access():
    manager = object.__new__(QdrantPublicationManager)
    with pytest.raises(InvalidRequest):
        await manager.purge({}, {}, object(),retention_policy=object(),deadline=deadline())
    with pytest.raises(UnsupportedCapability):
        await manager.purge({}, {}, object(),retention_policy='vectors_only',deadline=deadline())


def test_unissued_purge_projection_is_not_authority():
    with pytest.raises(TypeError):
        pickle.dumps(PurgeProjection())
