"""Exact bounded readback doubles; SQL/process evidence is recorded separately."""
import asyncio
import copy
from functools import wraps
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from cragkit._qdrant_reconciliation import (ExpectedProjection, QdrantReconciliationVerifier,
    ReconciliationReceipt, projection_data, receipt_data, verifier_authority)
from cragkit._qdrant_supervisor import ManagedQdrantSupervisor, _Proof
from cragkit._qdrant_writer import PostgresQdrantWriter, prepare_stage
from cragkit._qdrant_writer_contract import stage_data
from cragkit._qdrant_contract import point_id
from cragkit._qdrant_manifest import encode_manifest
from cragkit.errors import IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability
from cragkit.errors import DeadlineExceeded
from test_qdrant_writer import Connection, config, ctx, resource, stage_input


def run_async(function):
    @wraps(function)
    def run(*args,**kwargs):return asyncio.run(function(*args,**kwargs))
    return run


class Handle:
    def __init__(self,points,tombstoned=False):
        self.points=points;self.tombstoned=tombstoned;self.calls=[];self.close_count=0
        self.get_patch=None;self.scroll_patch=None;self.on_request=None;self.close_failure=False
        self.padding=False;self.padding_size=1048576;self.page=0;self.extra_eof=False;self.response_limits=[]
    async def request(self,method,path,*,body,deadline,max_response_bytes=1048576):
        self.response_limits.append(max_response_bytes)
        request=json.loads(body);self.calls.append((method,path,request))
        assert method=='POST' and request['with_payload'] is True and request['with_vector'] is True
        if self.on_request is not None:self.on_request()
        if path.endswith('/scroll'):
            self.page+=1
            ordered=sorted(self.points,key=lambda point:point['id'])
            start=0
            if 'offset' in request:
                start=next(index+1 for index,point in enumerate(ordered) if point['id']==request['offset'])
            page=[] if self.tombstoned else copy.deepcopy(ordered[start:start+8])
            following=page[-1]['id'] if page and (start+8<len(ordered) or self.extra_eof and len(page)==8) else None
            result={'points':page,'next_page_offset':following}
            if self.scroll_patch is not None:result=self.scroll_patch(result,self.page)
        else:
            result=[] if self.tombstoned else [copy.deepcopy(point) for point in self.points if point['id'] in request['ids']]
            if self.get_patch is not None:result=self.get_patch(result)
        raw=json.dumps({'status':'ok','result':result},separators=(',',':')).encode()
        raw=raw+b' '*(self.padding_size-len(raw)) if self.padding else raw
        if len(raw)>max_response_bytes:raise ProviderUnavailable()
        return raw
    async def close(self):
        self.close_count+=1
        if self.close_failure:raise RuntimeError('PRIVATE_CLOSE')


async def setup(monkeypatch,tmp_path,*,tombstoned=False,member_count=2):
    connection=Connection();writer=PostgresQdrantWriter(resource(monkeypatch,connection),config(),'instance-1');writer._ready=True
    inputs=stage_input()
    if member_count!=2:
        template=copy.deepcopy(inputs['manifest']['members'][0])
        dense=copy.deepcopy(inputs['dense_vectors'][0]);sparse=copy.deepcopy(inputs['sparse_vectors'][0])
        manifest=inputs['manifest'];manifest['members']=[]
        inputs['dense_vectors']=[];inputs['sparse_vectors']=[]
        for index in range(member_count):
            member={**template,'chunk_id':f'chunk-{index:03d}'}
            member['point_id']=point_id(['cragkit.qdrant.point.v1',manifest['backend_namespace'],
                manifest['physical_collection'],manifest['collection_incarnation'],manifest['tenant_id'],
                manifest['collection'],manifest['document_id'],manifest['revision_id'],manifest['generation_id'],
                member['chunk_id'],manifest['dense_profile']['profile_id'],manifest['sparse_profile']['profile_id']])
            manifest['members'].append(member)
            inputs['dense_vectors'].append(copy.deepcopy(dense));inputs['sparse_vectors'].append(copy.deepcopy(sparse))
        inputs['intent']['manifest_sha256']=encode_manifest(manifest,inputs['canonical_text']).sha256
    plan=prepare_stage(inputs);graph=stage_data(plan)
    physical={'instance_id':'instance-1','storage_identity':'storage-1','supervisor_id':'supervisor-1',
              'recovery_id':'recovery-1','old_epoch':1,'new_epoch':2,'credential_generation':'credential-2'}
    document={'authorization_revision':'auth-1','mutation_epoch':1,'active_generation_id':'gen-1',
              'principal_ids':['reader-a'],'grant_ids':['grant-a'],'language':'en','kind':'guide','tag':'reference',
              'tombstoned':tombstoned}
    original=writer._query
    async def query(connection,sql,params=()):
        if sql.startswith('SELECT backend_namespace,storage_identity'):
            return [('fixture-local','storage-1','supervisor-1',2,'recovery_blocked','recovery-1')]
        if sql.startswith('SELECT owner_token::text,intent_id,backend_epoch,instance_id'):
            return [(ctx()['owner_token'],'intent-2',2,'instance-1')]
        return await original(connection,sql,params)
    async def read_document(connection,context,**options):
        if context.scope.authorization_revision!=document['authorization_revision']:raise UnauthorizedScope()
        return dict(document)
    async def load_stage(connection,context):return plan
    monkeypatch.setattr(writer,'_query',query);monkeypatch.setattr(writer,'_document',read_document)
    monkeypatch.setattr(writer,'_load_stage',load_stage)
    supervisor=ManagedQdrantSupervisor(Path('/fixture/qdrant'),tmp_path/'controller','instance-1',config())
    supervisor._owned=(1,2);supervisor._initialized=True;supervisor._gate=False;supervisor._epoch=2
    supervisor._storage_id='storage-1';supervisor._supervisor_id='supervisor-1'
    supervisor._credential_generation='credential-2';supervisor._key='PRIVATE_KEY'
    supervisor._process=SimpleNamespace(returncode=None)
    monkeypatch.setattr(supervisor,'_assert_owner',lambda:None)
    proof=_Proof();supervisor._proofs[proof]=dict(physical)
    projection=await writer.project_stage(ctx(),physical,deadline=asyncio.get_running_loop().time()+5)
    data=projection_data(projection,writer)
    points=[{'id':point.point_id,'payload':point.payload.model_dump(mode='json'),
        'vector':{'dense':list(point.dense.values),**({'sparse':{'indices':list(point.sparse.indices),
        'values':list(point.sparse.values)}} if point.sparse else {})}} for point in data['points']]
    handle=Handle(points,tombstoned)
    monkeypatch.setattr(supervisor,'transport_for',lambda cap:handle)
    return writer,supervisor,proof,projection,handle,document,physical


@run_async
async def test_complete_actual_readback_issues_only_private_bound_receipt(monkeypatch,tmp_path):
    writer,supervisor,proof,projection,handle,_,physical=await setup(monkeypatch,tmp_path)
    verifier=QdrantReconciliationVerifier(writer,supervisor)
    receipt=await verifier.verify(proof,ctx(),deadline=asyncio.get_running_loop().time()+5)
    result=receipt_data(receipt,verifier)
    assert result['physical_binding']==physical
    assert result['sha256']==result['readback_sha256']
    assert json.loads(result['encoded_bytes'])==json.loads(json.dumps(result['witness']))
    assert len(result['witness'])==22 and result['witness'][5:7]==('1','2')
    assert result['point_ids']==projection_data(projection,writer)['point_ids']
    assert handle.close_count==1 and len(handle.calls)==2
    fields={part['key'] for part in handle.calls[-1][2]['filter']['must']}
    assert fields=={'backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id','revision_id','generation_id'}
    assert 'PRIVATE' not in repr(receipt)+repr(result['witness'])
    with pytest.raises(TypeError):result['sha256']='changed'
    for forged in ({},ReconciliationReceipt()):
        with pytest.raises(InvalidRequest):receipt_data(forged,verifier)
    with pytest.raises(InvalidRequest):projection_data(ExpectedProjection(),writer)
    with pytest.raises(InvalidRequest):projection_data(projection,object())


@pytest.mark.parametrize('fault',['missing','duplicate','wrong_dense','extra_vector','payload_text','wrong_scope','wrong_profile','wrong_sparse','outer_text','overcount'])
@run_async
async def test_direct_retrieve_rejects_foreign_or_incomplete_full_points(monkeypatch,tmp_path,fault):
    writer,supervisor,proof,_,handle,_,_=await setup(monkeypatch,tmp_path)
    def patch(points):
        if fault=='missing':points.pop()
        elif fault=='duplicate':points[1]=copy.deepcopy(points[0])
        elif fault=='wrong_dense':points[0]['vector']['dense'][0]=-1
        elif fault=='extra_vector':points[0]['vector']['other']=[1]
        elif fault=='payload_text':points[0]['payload']['text']='PRIVATE_SOURCE'
        elif fault=='wrong_scope':points[0]['payload']['tenant_id']='foreign'
        elif fault=='wrong_profile':points[0]['payload']['dense_profile']['model']='wrong'
        elif fault=='wrong_sparse':points[0]['vector']['sparse']['values'][0]=3
        elif fault=='outer_text':points[0]['text']='PRIVATE_SOURCE'
        else:points*=5
        return points
    handle.get_patch=patch;verifier=QdrantReconciliationVerifier(writer,supervisor)
    with pytest.raises(IntegrityViolation):await verifier.verify(proof,ctx(),deadline=asyncio.get_running_loop().time()+5)
    assert handle.close_count==1


@pytest.mark.parametrize('fault',['extra','duplicate','offset_cycle','missing_eof_set'])
@run_async
async def test_generation_scroll_requires_exact_full_set_and_valid_eof(monkeypatch,tmp_path,fault):
    writer,supervisor,proof,_,handle,_,_=await setup(monkeypatch,tmp_path)
    def patch(result,page):
        if fault=='extra':
            point=copy.deepcopy(result['points'][0]);point['id']='ffffffff-ffff-4fff-8fff-ffffffffffff';result['points'].append(point)
        elif fault=='duplicate':result['points'].append(copy.deepcopy(result['points'][0]))
        elif fault=='missing_eof_set':result['points'].pop()
        else:result={'points':[],'next_page_offset':'ffffffff-ffff-4fff-8fff-ffffffffffff'}
        return result
    handle.scroll_patch=patch
    with pytest.raises(IntegrityViolation):await QdrantReconciliationVerifier(writer,supervisor).verify(proof,ctx(),deadline=asyncio.get_running_loop().time()+5)


@run_async
async def test_tombstone_requires_absent_expected_ids_and_empty_scoped_enumeration(monkeypatch,tmp_path):
    writer,supervisor,proof,_,handle,_,_=await setup(monkeypatch,tmp_path,tombstoned=True)
    verifier=QdrantReconciliationVerifier(writer,supervisor)
    receipt=await verifier.verify(proof,ctx(),deadline=asyncio.get_running_loop().time()+5)
    assert receipt_data(receipt,verifier)['tombstoned'] is True
    handle.get_patch=lambda points:[{'id':'foreign-present'}]
    with pytest.raises(IntegrityViolation):await verifier.verify(proof,ctx(),deadline=asyncio.get_running_loop().time()+5)


@run_async
async def test_fresh_authority_recheck_prevents_receipt_after_concurrent_revocation(monkeypatch,tmp_path):
    writer,supervisor,proof,_,handle,document,_=await setup(monkeypatch,tmp_path)
    def revoke():document['authorization_revision']='auth-2';document['mutation_epoch']=2
    handle.on_request=revoke
    with pytest.raises(UnauthorizedScope):await QdrantReconciliationVerifier(writer,supervisor).verify(proof,ctx(),deadline=asyncio.get_running_loop().time()+5)
    assert handle.close_count==1


@run_async
async def test_cleanup_failure_is_operational_and_never_releases_receipt(monkeypatch,tmp_path):
    writer,supervisor,proof,_,handle,_,_=await setup(monkeypatch,tmp_path)
    handle.close_failure=True;handle.get_patch=lambda points:[]
    with pytest.raises(ProviderUnavailable) as caught:
        await QdrantReconciliationVerifier(writer,supervisor).verify(proof,ctx(),deadline=asyncio.get_running_loop().time()+5)
    assert 'PRIVATE' not in str(caught.value)


@run_async
async def test_aggregate_budget_cannot_be_reported_as_complete(monkeypatch,tmp_path):
    writer,supervisor,proof,_,handle,_,_=await setup(monkeypatch,tmp_path,member_count=64)
    handle.padding=True
    with pytest.raises(ProviderUnavailable):await QdrantReconciliationVerifier(writer,supervisor).verify(proof,ctx(),deadline=asyncio.get_running_loop().time()+5)
    assert len(handle.calls)<=17


@run_async
async def test_partial_aggregate_allowance_is_enforced_by_native_transport_reader(monkeypatch,tmp_path):
    writer,supervisor,proof,_,handle,_,_=await setup(monkeypatch,tmp_path,member_count=64)
    handle.padding=True;handle.padding_size=1048576-1000
    with pytest.raises(ProviderUnavailable):
        await QdrantReconciliationVerifier(writer,supervisor).verify(proof,ctx(),deadline=asyncio.get_running_loop().time()+5)
    assert handle.response_limits[:8]==[1048576]*8
    assert handle.response_limits[8]==8000 and len(handle.calls)==9


@run_async
async def test_full_64_member_set_reaches_eof_within_17_calls(monkeypatch,tmp_path):
    writer,supervisor,proof,_,handle,_,_=await setup(monkeypatch,tmp_path,member_count=64)
    handle.extra_eof=True
    verifier=QdrantReconciliationVerifier(writer,supervisor)
    receipt=await verifier.verify(proof,ctx(),deadline=asyncio.get_running_loop().time()+5)
    assert len(receipt_data(receipt,verifier)['point_ids'])==64
    assert len(handle.calls)==17 and handle.calls[-1][2]['offset'] is not None


@run_async
async def test_65th_backend_member_is_not_hidden_by_the_64_member_limit(monkeypatch,tmp_path):
    writer,supervisor,proof,_,handle,_,_=await setup(monkeypatch,tmp_path,member_count=64)
    extra=copy.deepcopy(handle.points[0]);extra['id']='ffffffff-ffff-ffff-ffff-ffffffffffff'
    handle.points.append(extra)
    with pytest.raises(IntegrityViolation):
        await QdrantReconciliationVerifier(writer,supervisor).verify(proof,ctx(),deadline=asyncio.get_running_loop().time()+5)
    assert len(handle.calls)==17


@run_async
async def test_receipt_accessor_rejects_a_physically_retired_proof(monkeypatch,tmp_path):
    writer,supervisor,proof,_,_,_,_=await setup(monkeypatch,tmp_path)
    verifier=QdrantReconciliationVerifier(writer,supervisor)
    receipt=await verifier.verify(proof,ctx(),deadline=asyncio.get_running_loop().time()+5)
    supervisor._proofs.clear()
    with pytest.raises(UnsupportedCapability):receipt_data(receipt,verifier)


@run_async
async def test_slow_final_physical_check_cannot_issue_a_receipt_after_deadline(monkeypatch,tmp_path):
    writer,supervisor,proof,_,_,_,_=await setup(monkeypatch,tmp_path)
    checked=False
    validate=writer.validate_projection
    binding=supervisor.recovery_binding
    async def validate_then_mark(projection,*,deadline):
        nonlocal checked
        await validate(projection,deadline=deadline)
        checked=True
    def slow_final_binding(value):
        if checked:
            time.sleep(0.15)
        return binding(value)
    monkeypatch.setattr(writer,'validate_projection',validate_then_mark)
    monkeypatch.setattr(supervisor,'recovery_binding',slow_final_binding)
    with pytest.raises(DeadlineExceeded):
        await QdrantReconciliationVerifier(writer,supervisor).verify(
            proof,ctx(),deadline=asyncio.get_running_loop().time()+0.1)


@run_async
async def test_internal_authority_binding_requires_the_exact_registered_pair(monkeypatch,tmp_path):
    writer,supervisor,_,_,handle,_,_=await setup(monkeypatch,tmp_path)
    verifier=QdrantReconciliationVerifier(writer,supervisor)
    assert verifier_authority(verifier,supervisor) is writer
    class DerivedVerifier(QdrantReconciliationVerifier):pass
    for value,target in [(verifier,object()),(object(),supervisor),
            (object.__new__(QdrantReconciliationVerifier),supervisor),
            (DerivedVerifier(writer,supervisor),supervisor)]:
        with pytest.raises(InvalidRequest):verifier_authority(value,target)
    assert not handle.calls


@run_async
async def test_unchanged_graph_row_order_does_not_invalidate_projection(monkeypatch,tmp_path):
    from cragkit._qdrant_writer_contract import StageData,issue_stage
    writer,_,_,projection,_,_,_=await setup(monkeypatch,tmp_path)
    graph=stage_data(prepare_stage(stage_input()))
    reversed_manifest=graph.manifest.model_copy(update={'members':tuple(reversed(graph.manifest.members))})
    reversed_plan=issue_stage(StageData(reversed_manifest,graph.intent,graph.source,
        graph.manifest_encoding,graph.intent_encoding,tuple(reversed(graph.dense)),tuple(reversed(graph.sparse))))
    async def load(connection,context):return reversed_plan
    monkeypatch.setattr(writer,'_load_stage',load)
    await writer.validate_projection(projection,deadline=asyncio.get_running_loop().time()+2)


@pytest.mark.parametrize('change,error',[
    ('manifest_sha256',IntegrityViolation),('revision_id',IntegrityViolation),
    ('generation_id',IntegrityViolation),('seals',IntegrityViolation),
    ('mutation_epoch',UnauthorizedScope),('active_generation_id',UnauthorizedScope),
    ('tombstoned',UnauthorizedScope),('metadata',UnauthorizedScope),
])
@run_async
async def test_fresh_projection_distinguishes_immutable_corruption_from_authority_change(monkeypatch,tmp_path,change,error):
    from dataclasses import replace
    from cragkit._qdrant_reconciliation import finalize_projection
    from cragkit._qdrant_vectors import encode_dense
    writer,_,_,projection,_,_,_=await setup(monkeypatch,tmp_path)
    original=projection_data(projection,writer);data=dict(original)
    sample=original['points'][0].payload
    data['authority']={key:getattr(sample,key) for key in ('principal_ids','grant_ids','language','kind','tag')}
    if change in ('manifest_sha256','revision_id','generation_id','active_generation_id'):
        data[change]='f'*64 if change=='manifest_sha256' else 'changed'
    elif change=='mutation_epoch':data[change]=2
    elif change=='tombstoned':data[change]=True
    elif change=='metadata':
        data['authority']['tag']='changed'
        data['points']=tuple(replace(point,payload=point.payload.model_copy(update={'tag':'changed'})) for point in data['points'])
    else:
        first=data['points'][0]
        vector=encode_dense([-value for value in first.dense.values],first.payload.dense_profile)
        data['points']=(replace(first,dense=vector),*data['points'][1:])
    changed=finalize_projection(writer,data)
    async def project(*args,**kwargs):return changed
    monkeypatch.setattr(writer,'project_stage',project)
    with pytest.raises(error):await writer.validate_projection(projection,deadline=asyncio.get_running_loop().time()+2)


@pytest.mark.parametrize('fault,error',[
    ('missing',ProviderUnavailable),('state',ProviderUnavailable),('epoch',ProviderUnavailable),
    ('recovery_id',ProviderUnavailable),('namespace',IntegrityViolation),
    ('storage_identity',IntegrityViolation),('supervisor_id',IntegrityViolation),
    ('shape',IntegrityViolation),('epoch_type',IntegrityViolation),
    ('instance',UnsupportedCapability),('owner',ProviderUnavailable),
])
@run_async
async def test_projection_separates_backend_identity_corruption_from_operational_fences(monkeypatch,tmp_path,fault,error):
    writer,_,_,_,_,_,physical=await setup(monkeypatch,tmp_path)
    original=writer._query
    async def query(connection,sql,params=()):
        if sql.startswith('SELECT backend_namespace,storage_identity'):
            if fault=='missing':return []
            row=['fixture-local','storage-1','supervisor-1',2,'recovery_blocked','recovery-1']
            positions={'namespace':0,'storage_identity':1,'supervisor_id':2,'epoch':3,'state':4,'recovery_id':5}
            if fault in positions:row[positions[fault]]=3 if fault=='epoch' else 'changed'
            elif fault=='shape':row.pop()
            elif fault=='epoch_type':row[3]=True
            return [tuple(row)]
        if fault=='owner' and sql.startswith('SELECT owner_token::text,intent_id,backend_epoch,instance_id'):
            return [('different-owner','intent-2',2,'instance-1')]
        return await original(connection,sql,params)
    monkeypatch.setattr(writer,'_query',query)
    if fault=='instance':physical={**physical,'instance_id':'different-instance'}
    with pytest.raises(error):await writer.project_stage(ctx(),physical,deadline=asyncio.get_running_loop().time()+2)
