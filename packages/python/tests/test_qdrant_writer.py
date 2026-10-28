"""Pure admission and committed writer lifecycle, without services/providers."""
import asyncio
import copy
from hashlib import sha256
import json
from functools import wraps
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

import cragkit._qdrant_writer as implementation
from cragkit._postgres_pool import PoolConfig, PoolResource
from cragkit._qdrant_writer import PostgresQdrantWriter, prepare_stage, writer_binding
from cragkit._qdrant_writer_contract import StagePlan, stage_data
from cragkit.embeddings import OPENAI_PROFILE
from cragkit.errors import (DeadlineExceeded, EmbeddingProfileMismatch, IndexNotReady,
    IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability)
from test_qdrant_manifest import FIXTURE, TEXT, manifest_record, stage_record


def run_async(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))
    return run


def stage_input():
    dense = [[1.0]+[0.0]*1535, [0.0,1.0]+[0.0]*1534]
    return {'manifest':manifest_record(),'canonical_text':TEXT,'intent':stage_record(),
            'dense_vectors':dense,'sparse_vectors':[{'indices':[2,7],'values':[1.0,0.5]},
                                                   {'indices':[3],'values':[2.0]}]}


def config():
    return {**FIXTURE['physical'],'dense_profile':FIXTURE['profiles']['dense'],
            'sparse_profile':FIXTURE['profiles']['sparse']}


def ctx():
    return {'scope':{'tenant_id':'tenant-a','principal_id':'reader-a','grant_ids':['grant-a'],
                     'authorization_revision':'auth-1'},'collection':'docs','document_id':'doc-1',
            'intent_id':'intent-2','owner_token':'11111111-1111-4111-8111-111111111111'}


class Cursor:
    def __init__(self,rows): self.rows=rows
    async def fetchall(self): return self.rows


class Connection:
    def __init__(self):
        self.info=SimpleNamespace(transaction_status=0)
        self.calls=[]; self.commits=0; self.rollbacks=0; self.closed=False
        self.role=True; self.history=list(implementation.EXPECTED_PUBLICATION_HISTORY)
        self.hash=implementation.EXPECTED_PUBLICATION_CATALOG_FINGERPRINT
        self.failure=None; self.commit_failure=False; self.block=None
    def transaction(self):
        owner=self
        class Transaction:
            async def __aenter__(self): owner.info.transaction_status=2
            async def __aexit__(self,*args):
                if args[0] is None:
                    if owner.commit_failure: raise RuntimeError('PRIVATE_COMMIT')
                    owner.commits+=1
                else: owner.rollbacks+=1
                owner.info.transaction_status=0
        return Transaction()
    async def execute(self,sql,params=None):
        self.calls.append((sql,params))
        if sql.startswith('SET ') or 'set_config(' in sql: return Cursor([])
        if sql.startswith('UPDATE cragkit_qdrant.publication_intents SET state=%s'): return Cursor([])
        if self.block is not None: await self.block.wait()
        if self.failure is not None: raise self.failure
        if sql in (implementation._WRITER_ROLE_SQL,implementation._WRITER_ATTESTATION_ROLE_SQL):return Cursor([(self.role,)])
        if sql==implementation._HISTORY_SQL:return Cursor(self.history)
        if sql in (implementation._PUBLICATION_CATALOG_SQL,implementation._ATTESTATION_CATALOG_SQL):return Cursor([(True,)])
        if sql==implementation._CATALOG_FINGERPRINT_SQL:return Cursor([(self.hash,)])
        if 'SELECT action,state,payload_sha256' in sql:return Cursor([])
        raise AssertionError('unexpected SQL')
    async def close(self): self.closed=True;self.info.transaction_status=4


def resource(monkeypatch,connection):
    pool=PoolResource(PoolConfig(host='localhost',dbname='fixture',user='reader',
        sslrootcert=Path('/fixture/ca'),passfile=Path('/fixture/pass')))
    @asynccontextmanager
    async def lease(self,*,deadline): yield connection
    monkeypatch.setattr(PoolResource,'lease',lease)
    return pool


@pytest.mark.parametrize('field,value,error', [
    ('instance_id', 'other-instance', UnsupportedCapability),
    ('intent_id', 'other-intent', UnsupportedCapability),
    ('owner_token', '22222222-2222-4222-8222-222222222222', UnsupportedCapability),
    ('epoch', True, InvalidRequest),
])
@run_async
async def test_ordinary_projection_binding_refuses_before_lease(monkeypatch, field, value, error):
    connection = Connection()
    writer = PostgresQdrantWriter(resource(monkeypatch, connection), config(), 'instance-1')
    writer._ready = True
    binding = {'instance_id': 'instance-1', 'storage_identity': 'storage-1',
               'supervisor_id': 'supervisor-1', 'epoch': 2, 'credential_generation': 'credential-2',
               'intent_id': 'intent-2', 'owner_token': ctx()['owner_token'], 'dispatch_id': 'dispatch-1'}
    binding[field] = value
    with pytest.raises(error):
        await writer.project_publication(ctx(), binding, deadline=asyncio.get_running_loop().time() + 5)
    assert connection.calls == []


def test_stage_plan_binds_originals_without_public_source_or_vectors():
    raw=stage_input();plan=prepare_stage(raw)
    assert plan.member_count==2
    assert plan.manifest_sha256==FIXTURE['intent']['manifest_sha256']
    assert plan.payload_sha256==FIXTURE['intent']['payload_sha256']
    assert TEXT not in repr(plan)
    raw['dense_vectors'][0][0]=0
    raw['sparse_vectors'][0]['values'][0]=100
    assert stage_data(plan).dense[0].encoded.values[0]==1
    assert stage_data(plan).sparse[0].encoded.values[0]==1
    with pytest.raises(FrozenInstanceError): plan.member_count=3
    with pytest.raises(InvalidRequest): stage_data(StagePlan(plan.manifest_sha256,plan.payload_sha256,2))


@pytest.mark.parametrize('change', ['seal','source','intent','count','sparse','unknown','both'])
def test_stage_admission_rejects_inconsistent_or_malformed_inputs(change):
    raw=stage_input()
    if change=='seal': raw['dense_vectors'][0]=[0,1]+[0]*1534
    elif change=='source':raw['canonical_text']='other source'
    elif change=='intent':raw['intent']['document_id']='another'
    elif change=='count':raw['dense_vectors'].pop()
    elif change=='sparse':raw['sparse_vectors'][0]['indices']=[7,2]
    elif change=='unknown':raw['extra']=True
    else:raw['dense_batches']=[]
    with pytest.raises((InvalidRequest,IntegrityViolation)):prepare_stage(raw)


def test_real_profile_requires_bound_batches_before_any_database_work():
    raw=stage_input();raw['manifest']['dense_profile']=OPENAI_PROFILE.model_dump()
    raw['manifest']['sparse_profile']=None
    # A valid real manifest is needed before the vector-route check, rather than
    # accepting forged fake identities under a real profile.
    from cragkit._qdrant_contract import point_id
    from cragkit._qdrant_manifest import encode_manifest
    for member in raw['manifest']['members']:
        member['sparse_input_sha256']=None
        m=raw['manifest']
        member['point_id']=point_id(['cragkit.qdrant.point.v1',m['backend_namespace'],m['physical_collection'],
            m['collection_incarnation'],m['tenant_id'],m['collection'],m['document_id'],m['revision_id'],
            m['generation_id'],member['chunk_id'],OPENAI_PROFILE.profile_id,''])
    raw['intent']['manifest_sha256']=encode_manifest(raw['manifest'],TEXT).sha256
    raw['sparse_vectors']=None
    with pytest.raises(EmbeddingProfileMismatch):prepare_stage(raw)


def real_batch_input():
    from cragkit._qdrant_contract import point_id
    from cragkit._qdrant_manifest import encode_dense_replay, encode_manifest
    raw=stage_input();manifest=raw['manifest']
    manifest['dense_profile']=OPENAI_PROFILE.model_dump();manifest['sparse_profile']=None
    vectors=raw.pop('dense_vectors');vectors[0][0]=1.00099999
    for member,vector in zip(manifest['members'],vectors,strict=True):
        member['sparse_input_sha256']=None
        member['dense_input_sha256']=encode_dense_replay(vector,OPENAI_PROFILE).input_sha256
        member['point_id']=point_id(['cragkit.qdrant.point.v1',manifest['backend_namespace'],manifest['physical_collection'],
            manifest['collection_incarnation'],manifest['tenant_id'],manifest['collection'],manifest['document_id'],
            manifest['revision_id'],manifest['generation_id'],member['chunk_id'],OPENAI_PROFILE.profile_id,''])
    raw['intent']['manifest_sha256']=encode_manifest(manifest,TEXT).sha256
    raw['sparse_vectors']=None
    raw['dense_batches']=[{'profile':OPENAI_PROFILE.model_dump(),'vectors':vectors,
        'usage':{'prompt_tokens':0,'total_tokens':0,'cost_usd':0.0,'cost_kind':'estimated'},
        'provider_calls':1,'synthetic':False}]
    return raw


def test_real_full_batch_is_bound_once_and_retains_admitted_original_sidecar():
    raw=real_batch_input();plan=prepare_stage(raw)
    bound=stage_data(plan)
    assert bound.dense[0].encoded.values[0]>1.001
    original_blob=bound.dense[0].blob
    raw['dense_batches'][0]['vectors'][0][0]=0
    raw['dense_batches'][0]['profile']['model']='changed'
    assert stage_data(plan).dense[0].blob==original_blob
    assert bound.manifest.dense_profile.model==OPENAI_PROFILE.model


@pytest.mark.parametrize('change',['synthetic','profile','count','too_many'])
def test_real_batch_contradictions_are_rejected_without_a_provider(change):
    raw=real_batch_input();batch=raw['dense_batches'][0]
    if change=='synthetic':batch['synthetic']=True
    elif change=='profile':batch['profile']['model']='wrong-model'
    elif change=='count':batch['vectors'].pop()
    else:raw['dense_batches']=[batch]*9
    with pytest.raises((EmbeddingProfileMismatch,InvalidRequest)):prepare_stage(raw)


def test_hostile_sqlstate_accessor_is_redacted():
    class Hostile(Exception):
        @property
        def sqlstate(self): raise RuntimeError('PRIVATE_ACCESSOR')
    async def check():
        safe=implementation._safe(Hostile('PRIVATE'),asyncio.get_running_loop().time()+1)
        assert type(safe) is ProviderUnavailable and 'PRIVATE' not in str(safe)
    asyncio.run(check())


def test_config_string_bound_applies_before_validation_copy(monkeypatch):
    bad=config();bad['backend_namespace']='x'*1025
    with pytest.raises(InvalidRequest):
        PostgresQdrantWriter(resource(monkeypatch,Connection()),bad,'instance')


@run_async
async def test_metadata_receipt_is_immutable(monkeypatch):
    connection=Connection();writer=PostgresQdrantWriter(resource(monkeypatch,connection),config(),'fixture-instance')
    original=writer._query
    async def query(connection,sql,params=()):
        if sql.startswith('SELECT action,state,payload_sha256'):
            return [('stage','staged','a'*64,'b'*64,'rev-1','gen-1',False,False,False)]
        return await original(connection,sql,params)
    monkeypatch.setattr(writer,'_query',query)
    deadline=asyncio.get_running_loop().time()+1
    await writer.initialize(deadline=deadline)
    receipt=await writer.inspect(ctx(),deadline=deadline)
    with pytest.raises(TypeError):receipt['state']='published'


@pytest.mark.parametrize('corruption',[None,'missing_member','invalid_utf8','wrong_excerpt','wrong_manifest','wrong_replay','wrong_profile','extra_raw_member','extra_raw_claim','extra_raw_replay'])
@run_async
async def test_preparation_reconstructs_complete_manifest_and_every_original_sidecar(monkeypatch,corruption):
    data=stage_data(prepare_stage(stage_input()));m=data.manifest
    writer=PostgresQdrantWriter(resource(monkeypatch,Connection()),config(),'fixture-instance')
    intent_rows=[(m.revision_id,m.generation_id,data.manifest_encoding.encoded_bytes,data.manifest_encoding.sha256)]
    generation=[data.source,m.source_sha256,m.source_locator,m.parser_id,m.backend_namespace,
        m.physical_collection,m.collection_incarnation,m.chunker_profile,m.dense_profile.model_dump(),
        m.sparse_profile.model_dump(),len(m.members)]
    members=[]
    for member,dense,sparse in zip(m.members,data.dense,data.sparse,strict=True):
        members.append([member.chunk_id,member.point_id,member.start_byte,member.end_byte,m.source_sha256,
            member.text_sha256,data.source[member.start_byte:member.end_byte],dense.input_sha256,sparse.input_sha256,
            dense.blob,dense.blob_sha256,sparse.blob,sparse.blob_sha256,m.dense_profile.model_dump(),m.sparse_profile.model_dump()])
    if corruption=='missing_member':members.pop()
    elif corruption=='invalid_utf8':generation[0]=data.source[:-1]+b'\xff'
    elif corruption=='wrong_excerpt':members[0][6]=b'wrong'
    elif corruption=='wrong_manifest':generation[2]='different-locator'
    elif corruption=='wrong_replay':members[1][9]=members[0][9];members[1][10]=members[0][10]
    elif corruption=='wrong_profile':members[1][13]={**members[1][13],'model':'wrong-model'}
    async def query(connection,sql,params=()):
        if sql.startswith('SELECT revision_id,generation_id,manifest_bytes'):return intent_rows
        if sql.startswith('SELECT r.canonical_utf8'):return [tuple(generation)]
        if sql.startswith('SELECT m.chunk_id'):return [tuple(row) for row in members]
        if sql.startswith('SELECT chunk_id,point_id::text'):
            base=[(member.chunk_id,member.point_id) for member in m.members]
            if 'FROM cragkit_qdrant.members ' in sql:
                return base+([('hidden-extra','ffffffff-ffff-4fff-8fff-ffffffffffff')] if corruption=='extra_raw_member' else [])
            if 'FROM cragkit_qdrant.point_claims ' in sql:
                rows=[(*item,'fixture-instance',m.backend_namespace,m.physical_collection,m.collection_incarnation) for item in base]
                return rows+([('hidden-extra','ffffffff-ffff-4fff-8fff-ffffffffffff','fixture-instance',m.backend_namespace,m.physical_collection,m.collection_incarnation)] if corruption=='extra_raw_claim' else [])
            rows=[(*item,m.backend_namespace,m.physical_collection,m.collection_incarnation) for item in base]
            return rows+([('hidden-extra','ffffffff-ffff-4fff-8fff-ffffffffffff',m.backend_namespace,m.physical_collection,m.collection_incarnation)] if corruption=='extra_raw_replay' else [])
        if sql.startswith('SELECT payload_bytes,payload_sha256'):
            return [(data.intent_encoding.encoded_bytes,data.intent_encoding.sha256)]
        raise AssertionError('unexpected SQL')
    monkeypatch.setattr(writer,'_query',query)
    parsed=implementation.context(ctx())
    if corruption is None:
        restored=await writer._load_stage(Connection(),parsed)
        assert restored.manifest_sha256==data.manifest_encoding.sha256
        assert stage_data(restored).source==data.source
        assert stage_data(restored).dense[0].blob==data.dense[0].blob
    else:
        with pytest.raises(IntegrityViolation):await writer._load_stage(Connection(),parsed)


@pytest.mark.parametrize('patch,expected',[({},None),({'authorization_revision':'auth-2'},'denied'),
    ({'mutation_epoch':2},'denied'),({'tombstoned':True},'denied'),
    ({'active_generation_id':'another'},'conflict')])
@run_async
async def test_final_fences_distinguish_denial_from_pointer_conflict(monkeypatch,patch,expected):
    writer=PostgresQdrantWriter(resource(monkeypatch,Connection()),config(),'fixture-instance')
    document={'authorization_revision':'auth-1','mutation_epoch':1,'active_generation_id':'gen-1','tombstoned':False,**patch}
    async def lock(connection,context,**options):
        assert options=={'check_revision':False,'validate_owner':False}
        return 1,document
    async def query(connection,sql,params=()):
        if sql.startswith('SELECT owner_token::text'):return [(ctx()['owner_token'],'intent-2',1)]
        return [('auth-1',1,'gen-1','a'*64,'gen-2','rev-2','writing')]
    async def read_document(connection,context,**options):
        assert options=={'check_revision':False,'lock':False}
        return document
    monkeypatch.setattr(writer,'_lock',lock);monkeypatch.setattr(writer,'_query',query)
    monkeypatch.setattr(writer,'_document',read_document)
    assert (await writer._fences(Connection(),implementation.context(ctx())))[3]==expected


@pytest.mark.parametrize('state',['denied','conflict'])
@run_async
async def test_known_final_fence_failure_commits_terminal_receipt(monkeypatch,state):
    connection=Connection();writer=PostgresQdrantWriter(resource(monkeypatch,connection),config(),'fixture-instance')
    writer._ready=True
    async def inspect(connection,context):
        terminal=[params[0] for sql,params in connection.calls if sql.startswith('UPDATE cragkit_qdrant.publication_intents SET state=%s')]
        return {'action':'stage','state':terminal[-1] if terminal else 'writing'}
    async def fences(connection,context):return 1,{},(),state
    monkeypatch.setattr(writer,'_inspect',inspect);monkeypatch.setattr(writer,'_fences',fences)
    receipt=await writer.prepare(ctx(),'a'*64,deadline=asyncio.get_running_loop().time()+1)
    assert receipt['state']==state and connection.commits==1 and connection.rollbacks==0


@run_async
async def test_wrong_scope_alone_does_not_poison_an_unchanged_intent(monkeypatch):
    writer=PostgresQdrantWriter(resource(monkeypatch,Connection()),config(),'fixture-instance')
    async def query(connection,sql,params=()):return [('auth-1',1,'gen-1','a'*64,'gen-2','rev-2','prepared')]
    async def document(connection,context,**options):
        return {'authorization_revision':'auth-1','mutation_epoch':1,'active_generation_id':'gen-1','tombstoned':False}
    monkeypatch.setattr(writer,'_query',query);monkeypatch.setattr(writer,'_document',document)
    value=ctx();value['scope']['authorization_revision']='wrong-scope'
    with pytest.raises(UnauthorizedScope):await writer._fences(Connection(),implementation.context(value))


@run_async
async def test_changed_pointer_can_be_recorded_after_another_owner_has_published(monkeypatch):
    writer=PostgresQdrantWriter(resource(monkeypatch,Connection()),config(),'fixture-instance')
    async def query(connection,sql,params=()):return [('auth-1',1,'gen-1','a'*64,'gen-2','rev-2','prepared')]
    async def document(connection,context,**options):
        assert options['lock'] is False
        return {'authorization_revision':'auth-1','mutation_epoch':1,'active_generation_id':'new-winner','tombstoned':False}
    async def forbidden_owner_lock(*args,**kwargs):raise AssertionError('stale owner must not hide known pointer conflict')
    monkeypatch.setattr(writer,'_query',query);monkeypatch.setattr(writer,'_document',document)
    monkeypatch.setattr(writer,'_lock',forbidden_owner_lock)
    assert (await writer._fences(Connection(),implementation.context(ctx())))[3]=='conflict'


@run_async
async def test_delete_reservation_requires_tombstoned_purge_intent(monkeypatch):
    connection=Connection();writer=PostgresQdrantWriter(resource(monkeypatch,connection),config(),'fixture-instance')
    writer._ready=True
    async def lock(*args,**kwargs):return 1,{'tombstoned':False}
    async def fences(*args,**kwargs):return ('stage',)
    monkeypatch.setattr(writer,'_lock',lock);monkeypatch.setattr(writer,'_operation_fences',fences)
    with pytest.raises(InvalidRequest):await writer.reserve_dispatch(ctx(),{'dispatch_id':'delete-1','sequence':1,
        'credential_generation':'key-1','operation':'delete_points','point_ids':[FIXTURE['members'][0]['point_id']]},
        deadline=asyncio.get_running_loop().time()+1)
    assert connection.rollbacks==1


@pytest.mark.parametrize('method',['prepare','publish'])
@pytest.mark.parametrize('action',['update_authorization','tombstone','purge'])
@run_async
async def test_only_stage_intents_can_prepare_or_publish(monkeypatch,method,action):
    connection=Connection();writer=PostgresQdrantWriter(resource(monkeypatch,connection),config(),'fixture-instance')
    writer._ready=True
    async def inspect(connection,context):return {'action':action,'state':'authority_committed'}
    monkeypatch.setattr(writer,'_inspect',inspect)
    deadline=asyncio.get_running_loop().time()+1
    with pytest.raises(InvalidRequest):
        if method=='prepare':await writer.prepare(ctx(),'a'*64,deadline=deadline)
        else:await writer.publish(ctx(),deadline=deadline)
    assert connection.rollbacks==1 and connection.commits==0


@pytest.mark.parametrize('state',['dispatched','unknown','settled'])
@run_async
async def test_only_new_dispatch_requires_current_security_fences(monkeypatch,state):
    connection=Connection();writer=PostgresQdrantWriter(resource(monkeypatch,connection),config(),'fixture-instance')
    writer._ready=True;calls=[]
    async def lock(connection,context,**options):
        calls.append(('lock',options));return 1,{}
    async def fences(*args,**kwargs):calls.append(('fences',{}));return ()
    original=writer._query
    async def query(connection,sql,params=()):
        if sql.startswith('SELECT state,completion_sha256'):
            return [('reserved',None,ctx()['owner_token'])]
        return await original(connection,sql,params)
    original_execute=connection.execute
    async def execute(sql,params=None):
        if sql.startswith('UPDATE cragkit_qdrant.dispatch_journal'):return Cursor([])
        return await original_execute(sql,params)
    monkeypatch.setattr(writer,'_lock',lock);monkeypatch.setattr(writer,'_operation_fences',fences)
    monkeypatch.setattr(writer,'_query',query);monkeypatch.setattr(connection,'execute',execute)
    await writer._dispatch_state(ctx(),'dispatch-1',state,'a'*64 if state=='settled' else None,
        asyncio.get_running_loop().time()+1)
    assert calls[0]==('lock',{'check_revision':state=='dispatched'})
    assert any(name=='fences' for name,_ in calls)==(state=='dispatched')


@pytest.mark.parametrize('state',['dispatched','settled'])
@run_async
async def test_unknown_dispatch_requires_supervisor_instead_of_new_admission(monkeypatch,state):
    connection=Connection()
    writer=PostgresQdrantWriter(resource(monkeypatch,connection),config(),'fixture-instance')
    writer._ready=True
    async def lock(*args,**kwargs):return 1,{}
    async def fences(*args,**kwargs):return ()
    original=writer._query
    async def query(connection,sql,params=()):
        if sql.startswith('SELECT state,completion_sha256'):
            return [('unknown',None,ctx()['owner_token'])]
        return await original(connection,sql,params)
    monkeypatch.setattr(writer,'_lock',lock)
    monkeypatch.setattr(writer,'_operation_fences',fences)
    monkeypatch.setattr(writer,'_query',query)
    with pytest.raises(ProviderUnavailable):
        await writer._dispatch_state(ctx(),'dispatch-1',state,'a'*64 if state=='settled' else None,
            asyncio.get_running_loop().time()+1)
    assert connection.rollbacks==1 and connection.commits==0


@run_async
async def test_cas_rechecks_document_after_wait_before_rejecting_replaced_owner(monkeypatch):
    writer=PostgresQdrantWriter(resource(monkeypatch,Connection()),config(),'fixture-instance')
    async def query(connection,sql,params=()):
        if sql.startswith('SELECT owner_token::text'):
            raise AssertionError('a known pointer conflict must be classified before token rejection')
        return [('auth-1',1,'gen-1','a'*64,'gen-2','rev-2','prepared')]
    async def document(connection,context,**options):
        assert options=={'check_revision':False,'lock':False}
        return {'authorization_revision':'auth-1','mutation_epoch':1,'active_generation_id':'gen-1','tombstoned':False}
    async def waited_lock(connection,context,**options):
        assert options=={'check_revision':False,'validate_owner':False}
        # Publisher B replaced the owner and pointer while A waited for this lock.
        return 1,{'authorization_revision':'auth-1','mutation_epoch':1,'active_generation_id':'winner','tombstoned':False}
    monkeypatch.setattr(writer,'_query',query);monkeypatch.setattr(writer,'_document',document)
    monkeypatch.setattr(writer,'_lock',waited_lock)
    assert (await writer._fences(Connection(),implementation.context(ctx())))[3]=='conflict'


@pytest.mark.parametrize('method',['prepare','publish'])
@run_async
async def test_unsettled_work_is_operational_before_preparation_or_publication(monkeypatch,method):
    connection=Connection();writer=PostgresQdrantWriter(resource(monkeypatch,connection),config(),'fixture-instance')
    writer._ready=True
    async def inspect(connection,context):return {'action':'stage','state':'prepared' if method=='publish' else 'writing'}
    async def fences(connection,context):
        return 1,{},('auth-1',1,'gen-1','a'*64,'gen-2','rev-2','prepared'),None
    original=writer._query
    async def query(connection,sql,params=()):
        if sql.startswith('SELECT dispatch_id FROM cragkit_qdrant.dispatch_journal'):return [('unknown-dispatch',)]
        return await original(connection,sql,params)
    async def forbidden_graph(*args,**kwargs):raise AssertionError('uncertainty must block before graph preparation')
    monkeypatch.setattr(writer,'_inspect',inspect);monkeypatch.setattr(writer,'_fences',fences)
    monkeypatch.setattr(writer,'_query',query);monkeypatch.setattr(writer,'_load_stage',forbidden_graph)
    with pytest.raises(ProviderUnavailable):
        if method=='prepare':await writer.prepare(ctx(),'a'*64,deadline=asyncio.get_running_loop().time()+1)
        else:await writer.publish(ctx(),deadline=asyncio.get_running_loop().time()+1)
    assert connection.rollbacks==1 and connection.commits==0


@pytest.mark.parametrize('path',['ordinary_lock','final_cas'])
@pytest.mark.parametrize('owners',[[],[('22222222-2222-4222-8222-222222222222','other-intent',1)]])
@run_async
async def test_owner_only_loss_is_operational_while_immutable_fences_match(monkeypatch,path,owners):
    writer=PostgresQdrantWriter(resource(monkeypatch,Connection()),config(),'fixture-instance')
    document={'authorization_revision':'auth-1','mutation_epoch':1,'active_generation_id':'gen-1','tombstoned':False}
    async def query(connection,sql,params=()):
        if sql.startswith('SELECT epoch,state,backend_namespace'):return [(1,'open','fixture-local')]
        if sql.startswith('SELECT owner_token::text'):return owners
        if sql.startswith('SELECT expected_authorization_revision'):
            return [('auth-1',1,'gen-1','a'*64,'gen-2','rev-2','prepared')]
        raise AssertionError('unexpected query')
    async def read_document(connection,context,**options):return document
    monkeypatch.setattr(writer,'_query',query);monkeypatch.setattr(writer,'_document',read_document)
    parsed=implementation.context(ctx())
    with pytest.raises(ProviderUnavailable):
        if path=='ordinary_lock':await writer._lock(Connection(),parsed)
        else:await writer._fences(Connection(),parsed)


@run_async
async def test_initialize_exact_publication_profile_and_fresh_roles(monkeypatch):
    connection=Connection();writer=PostgresQdrantWriter(resource(monkeypatch,connection),config(),'fixture-instance')
    deadline=asyncio.get_running_loop().time()+2
    with pytest.raises(IndexNotReady):await writer.inspect(ctx(),deadline=deadline)
    assert connection.calls==[]
    await writer.initialize(deadline=deadline)
    assert connection.commits==1
    assert await writer.inspect(ctx(),deadline=deadline) is None
    settings=[params for sql,params in connection.calls if sql==implementation._SCOPE_SQL]
    assert settings[0]==('tenant-a','docs','reader-a','["grant-a"]','auth-1','doc-1','intent-2',ctx()['owner_token'],'fixture-instance')
    connection.role=False
    with pytest.raises(UnauthorizedScope):await writer.inspect(ctx(),deadline=deadline)
    assert connection.rollbacks==1


@pytest.mark.parametrize('drift',['oldhistory','thirdhistory','hash'])
@run_async
async def test_initialize_refuses_mixed_unknown_profiles(monkeypatch,drift):
    connection=Connection()
    if drift=='oldhistory':connection.history=connection.history[:1]
    elif drift=='thirdhistory':connection.history.append(('0003','a'*64))
    else:connection.hash='a'*64
    writer=PostgresQdrantWriter(resource(monkeypatch,connection),config(),'fixture-instance')
    with pytest.raises(UnsupportedCapability):await writer.initialize(deadline=asyncio.get_running_loop().time()+2)
    assert connection.commits==0 and connection.rollbacks==1


@run_async
async def test_lost_commit_discards_connection_and_redacts(monkeypatch):
    connection=Connection();connection.commit_failure=True
    writer=PostgresQdrantWriter(resource(monkeypatch,connection),config(),'fixture-instance')
    with pytest.raises(ProviderUnavailable) as caught:
        await writer.initialize(deadline=asyncio.get_running_loop().time()+2)
    assert 'PRIVATE' not in str(caught.value) and caught.value.__cause__ is None
    assert connection.closed


@run_async
async def test_close_cancels_blocked_initialize_without_closing_borrowed_pool(monkeypatch):
    connection=Connection();connection.block=asyncio.Event()
    writer=PostgresQdrantWriter(resource(monkeypatch,connection),config(),'fixture-instance')
    task=asyncio.create_task(writer.initialize(deadline=asyncio.get_running_loop().time()+10))
    await asyncio.sleep(0)
    with pytest.raises(ProviderUnavailable):await writer.initialize(deadline=asyncio.get_running_loop().time()+1)
    await writer.close()
    with pytest.raises(asyncio.CancelledError):await task
    assert connection.rollbacks==1


def test_role_probe_checks_extra_column_and_function_privileges():
    assert 'has_column_privilege' in implementation._WRITER_ROLE_SQL
    assert 'IS DISTINCT FROM CASE' in implementation._WRITER_ROLE_SQL
    assert "c.relname='members' AND a.attname='point_id'" in implementation._WRITER_ROLE_SQL
    assert "c.relname='backend_instances' AND a.attname='epoch'" in implementation._WRITER_ROLE_SQL
    assert implementation._WRITER_ROLE_SQL.count('p.oid IS NOT DISTINCT FROM to_regprocedure(')==8
    assert "has_function_privilege('cragkit_qdrant_writer'" not in implementation._WRITER_ROLE_SQL
    assert "'cragkit_qdrant_supervisor','MEMBER'" in implementation._WRITER_ROLE_SQL


def test_fixed_writer_capability_remains_nologin_safe_and_without_outbound_memberships():
    sql=implementation._WRITER_ROLE_SQL
    assert "r.rolname='cragkit_qdrant_writer'" in sql
    assert 'NOT (r.rolcanlogin OR r.rolsuper OR r.rolbypassrls OR r.rolcreaterole OR r.rolcreatedb OR r.rolreplication)' in sql
    assert 'NOT EXISTS(SELECT 1 FROM pg_auth_members membership WHERE membership.member=r.oid)' in sql


def test_constructor_requires_actual_borrowed_resource():
    with pytest.raises(InvalidRequest):PostgresQdrantWriter(object(),config(),'instance')


def test_writer_binding_is_original_immutable_metadata_without_io_or_resource(monkeypatch):
    connection = Connection()
    pool = resource(monkeypatch, connection)
    writer = PostgresQdrantWriter(pool, config(), 'instance-1')
    binding = writer_binding(writer)
    assert set(binding) == {'config', 'instance_id'}
    assert binding['config'] is writer.config and binding['instance_id'] == 'instance-1'
    assert connection.calls == [] and not connection.closed and not writer._ready
    with pytest.raises(TypeError):
        binding['resource'] = pool
    with pytest.raises(ValueError):
        binding['config'].physical_collection = 'other_collection'
    with pytest.raises(ValueError):
        binding['config'].dense_profile.model = 'other-model'


def test_writer_binding_rejects_unissued_copied_and_subclass_objects(monkeypatch):
    class Child(PostgresQdrantWriter):
        pass

    pool = resource(monkeypatch, Connection())
    writer = PostgresQdrantWriter(pool, config(), 'instance-1')
    for value in ({}, object(), copy.copy(writer), object.__new__(PostgresQdrantWriter),
                  Child(pool, config(), 'instance-1')):
        with pytest.raises(InvalidRequest):
            writer_binding(value)


@pytest.mark.parametrize('field', ['resource', 'config', 'instance_id'])
def test_writer_binding_rejects_reassigned_public_constructor_binding(monkeypatch, field):
    connection = Connection()
    pool = resource(monkeypatch, connection)
    writer = PostgresQdrantWriter(pool, config(), 'instance-1')
    replacements = {'resource': PoolResource(pool.config),
                    'config': writer.config.model_copy(), 'instance_id': 'other-instance'}
    setattr(writer, field, replacements[field])
    with pytest.raises(InvalidRequest):
        writer_binding(writer)
    assert not connection.closed and connection.calls == []


@pytest.mark.parametrize('conflicting',[False,True])
@run_async
async def test_same_generation_cannot_adopt_a_different_manifest_even_at_equal_count(monkeypatch,conflicting):
    connection=Connection();writer=PostgresQdrantWriter(resource(monkeypatch,connection),config(),'fixture-instance')
    writer._ready=True;events=[]
    async def inspect(connection,context):return {'action':'stage','state':'staged'}
    async def ensure(connection,table,values,keys,json_columns=()):events.append(('ensure',table))
    async def document(connection,context,**options):
        events.append(('lock','document'))
        return {'authorization_revision':'auth-1','mutation_epoch':1,'active_generation_id':'gen-1','tombstoned':False}
    original=writer._query
    async def query(connection,sql,params=()):
        if sql.startswith('SELECT document_id FROM'):return [('doc-1',)]
        if sql.startswith('SELECT intent_id FROM cragkit_qdrant.publication_intents'):
            assert events[-1]==('lock','document')
            assert 'manifest_sha256 IS DISTINCT FROM' in sql and 'manifest_bytes IS DISTINCT FROM' in sql
            return [('other-stage-intent',)] if conflicting else []
        return await original(connection,sql,params)
    monkeypatch.setattr(writer,'_inspect',inspect);monkeypatch.setattr(writer,'_ensure',ensure)
    monkeypatch.setattr(writer,'_document',document);monkeypatch.setattr(writer,'_query',query)
    plan=prepare_stage(stage_input());options={'owner_token':ctx()['owner_token'],'deadline':asyncio.get_running_loop().time()+2}
    if conflicting:
        with pytest.raises(IntegrityViolation):await writer.stage(plan,ctx()['scope'],**options)
        assert events==[('ensure','publication_intents'),('lock','document')]
        assert connection.rollbacks==1
    else:
        await writer.stage(plan,ctx()['scope'],**options)
        assert ('ensure','members') in events and connection.commits==1


class ManagerConnection(Connection):
    """Stateful committed-metadata double; no remote completion is simulated."""
    def __init__(self, state):
        super().__init__()
        self.state = state

    def transaction(self):
        connection = self

        class Transaction:
            async def __aenter__(self):
                connection.info.transaction_status = 2
                self.before = {
                    key: value if isinstance(value, BaseException) else copy.deepcopy(value)
                    for key, value in connection.state.items()
                }

            async def __aexit__(self, kind, error, traceback):
                if kind is None:
                    connection.commits += 1
                    failure = connection.state.pop('commit_error', None)
                    if failure is not None:
                        raise failure
                else:
                    connection.rollbacks += 1
                    connection.state.clear()
                    connection.state.update(self.before)
                connection.info.transaction_status = 0

        return Transaction()

    async def execute(self, sql, params=None):
        if (sql.startswith('SET ') or 'set_config(' in sql
                or sql in (implementation._WRITER_ROLE_SQL,implementation._WRITER_ATTESTATION_ROLE_SQL)):
            return await super().execute(sql, params)
        self.calls.append((sql, params))
        if self.state.get('body_error') is not None:
            raise self.state['body_error']
        if sql.startswith('SELECT active_generation_id,authorization_revision,mutation_epoch,tombstoned'):
            if 'FOR UPDATE' in sql and self.state.get('after_owner_wait') is not None:
                patch = self.state.pop('after_owner_wait')
                self.state['document'].update(patch)
            document = self.state['document']
            return Cursor([] if document is None else [tuple(document[key] for key in
                ('active_generation_id', 'authorization_revision', 'mutation_epoch', 'tombstoned'))])
        if sql.startswith('SELECT action,state,payload_sha256'):
            intent = self.state['intent']
            return Cursor([] if intent is None else [tuple(intent[key] for key in implementation._META)])
        if sql.startswith('SELECT instance_id,backend_namespace,storage_identity'):
            return Cursor(self.state['backend'])
        if sql.startswith('SELECT instance_id,intent_id,owner_token::text,backend_epoch'):
            if 'FOR UPDATE' in sql:
                self.state['owner_locked'] = True
            return Cursor([] if self.state['owner'] is None else [self.state['owner']])
        if sql.startswith('SELECT sequence FROM cragkit_qdrant.dispatch_journal'):
            return Cursor(self.state['sequences'])
        if sql.startswith('SELECT dispatch_id FROM cragkit_qdrant.dispatch_journal'):
            return Cursor(self.state['pending'])
        if sql.startswith('SELECT expected_authorization_revision,expected_mutation_epoch,expected_active_generation_id FROM'):
            assert self.state.get('owner_locked') is True
            return Cursor([self.state['fences']])
        if sql.startswith('SELECT owner_token::text,backend_epoch,authorization_revision,mutation_epoch,manifest_sha256,readback_sha256'):
            return Cursor(self.state.get('preparations', []))
        if sql.startswith('SELECT expected_authorization_revision,expected_mutation_epoch,manifest_sha256 FROM'):
            return Cursor([(self.state['fences'][0], self.state['fences'][1],
                            self.state['intent']['manifest_sha256'])])
        if sql.startswith('SELECT payload_bytes,payload_sha256,manifest_bytes FROM'):
            return Cursor(self.state['original_payloads'])
        if sql.startswith('SELECT dispatch_id,sequence FROM cragkit_qdrant.dispatch_journal'):
            return Cursor(self.state['selected_dispatches'])
        if sql.startswith('INSERT INTO cragkit_qdrant.document_owners'):
            self.state['owner'] = (params[3], params[4], params[5], params[6])
            self.state['owner_writes'] += 1
            return Cursor([])
        if sql.startswith("UPDATE cragkit_qdrant.publication_intents SET state='writing'"):
            if self.state['intent']['state'] == 'staged':
                self.state['intent']['state'] = 'writing'
            return Cursor([])
        if sql.startswith('UPDATE cragkit_qdrant.publication_intents SET state=%s'):
            self.state['intent']['state'] = params[0]
            return Cursor([])
        if sql.startswith('SELECT sequence,owner_token::text,backend_epoch,credential_generation'):
            return Cursor(self.state['dispatch'])
        if sql.startswith('SELECT backend_namespace,physical_collection,collection_incarnation,point_id::text'):
            return Cursor(self.state['dispatch_members'])
        if sql.startswith('SELECT point_id::text FROM cragkit_qdrant.point_claims'):
            return Cursor(self.state['claims'])
        raise AssertionError('unexpected manager SQL')


def manager_writer(monkeypatch):
    plan = prepare_stage(stage_input())
    graph = stage_data(plan)
    state = {
        'document': {'active_generation_id': graph.intent.expected_active_generation_id,
            'authorization_revision': 'auth-1', 'mutation_epoch': 1, 'tombstoned': False},
        'intent': {'action': 'stage', 'state': 'staged', 'payload_sha256': plan.payload_sha256,
            'manifest_sha256': plan.manifest_sha256, 'revision_id': graph.manifest.revision_id,
            'generation_id': graph.manifest.generation_id, 'authority_committed': False,
            'replica_complete': False, 'purge_complete': False},
        'backend': [('instance-1', 'fixture-local', 'storage-1', 'supervisor-1', 1, 'open', None)],
        'owner': None, 'owner_writes': 0, 'sequences': [], 'pending': [],
        'fences': ('auth-1', 1, graph.intent.expected_active_generation_id),
        'dispatch': [], 'dispatch_members': [], 'claims': [],
    }
    connections = []
    pool = resource(monkeypatch, Connection())

    @asynccontextmanager
    async def lease(self, *, deadline):
        connection = ManagerConnection(state)
        connections.append(connection)
        yield connection

    monkeypatch.setattr(PoolResource, 'lease', lease)
    writer = PostgresQdrantWriter(pool, config(), 'instance-1')
    writer._ready = True
    loads = []

    async def load(connection, context):
        loads.append(context)
        if state.get('graph_error'):
            raise IntegrityViolation()
        return plan

    monkeypatch.setattr(writer, '_load_stage', load)
    return writer, state, connections, loads


@run_async
async def test_manager_snapshot_absent_and_existing_are_closed_immutable_metadata(monkeypatch):
    writer, state, connections, _ = manager_writer(monkeypatch)
    deadline = asyncio.get_running_loop().time() + 5
    state['document'] = state['intent'] = None
    empty = await writer.manager_snapshot(ctx(), deadline=deadline)
    assert empty['document'] is None and empty['intent'] is None and empty['owner'] is None
    assert empty['max_sequence'] == 0 and empty['pending'] is False
    with pytest.raises(TypeError):
        empty['backend']['epoch'] = 2
    state['owner'] = ('instance-1', 'predecessor-intent',
                      '22222222-2222-4222-8222-222222222222', 1)
    state['sequences'] = [(1,), (5,)]
    state['pending'] = [('other-intent-dispatch',)]
    snapshot = await writer.manager_snapshot(ctx(), deadline=deadline)
    assert snapshot['owner']['intent_id'] == 'predecessor-intent'
    assert snapshot['max_sequence'] == 5 and snapshot['pending'] is True
    assert set(snapshot) == {'intent', 'document', 'backend', 'owner', 'max_sequence', 'pending'}
    pending_call = next(call for call in connections[-1].calls
                        if call[0].startswith('SELECT dispatch_id'))
    assert pending_call[1] == ('tenant-a', 'docs', 'doc-1')


@pytest.mark.parametrize('sequences', [[(1,), (1,)], [(257,)], [(True,)], [(1.0,)], [(1,)] * 257])
@run_async
async def test_manager_snapshot_rejects_invalid_sequence_history(monkeypatch, sequences):
    writer, state, _, _ = manager_writer(monkeypatch)
    state['sequences'] = sequences
    with pytest.raises(IntegrityViolation):
        await writer.manager_snapshot(ctx(), deadline=asyncio.get_running_loop().time() + 5)


@pytest.mark.parametrize('patch,outcome', [
    ({'active_generation_id': 'new-active'}, 'conflict'),
    ({'mutation_epoch': 2}, 'denied'),
    ({'tombstoned': True}, 'denied'),
])
@run_async
async def test_admission_persists_original_fence_failure_after_owner_wait(monkeypatch, patch, outcome):
    writer, state, connections, loads = manager_writer(monkeypatch)
    state['owner'] = ('instance-1', 'competing-intent',
                      '22222222-2222-4222-8222-222222222222', 1)
    previous = state['owner']
    state['after_owner_wait'] = patch
    result = await writer.admit_publication(ctx(), deadline=asyncio.get_running_loop().time() + 5)
    assert result['intent']['state'] == outcome and result['owner'] is None
    assert state['owner'] == previous and state['owner_writes'] == 0 and loads == []
    assert connections[0].commits == 1
    calls = [sql for sql, _ in connections[0].calls]
    backend = next(index for index, sql in enumerate(calls) if 'FOR SHARE' in sql)
    owner = next(index for index, sql in enumerate(calls)
                 if sql.startswith('SELECT instance_id,intent_id,owner_token::text,backend_epoch ')
                 and 'FROM cragkit_qdrant.document_owners' in sql and 'FOR UPDATE' in sql)
    document = next(index for index, sql in enumerate(calls)
                    if 'documents' in sql and 'FOR UPDATE' in sql)
    assert backend < owner < document


@run_async
async def test_stale_caller_scope_never_poisoned_and_terminal_does_not_take_owner(monkeypatch):
    writer, state, _, loads = manager_writer(monkeypatch)
    state['document']['authorization_revision'] = 'auth-new'
    with pytest.raises(UnauthorizedScope):
        await writer.admit_publication(ctx(), deadline=asyncio.get_running_loop().time() + 5)
    assert state['intent']['state'] == 'staged' and state['owner_writes'] == 0
    state['intent']['state'] = 'published'
    state['document']['active_generation_id'] = 'later-generation'
    current = copy.deepcopy(ctx())
    current['scope']['authorization_revision'] = 'auth-new'
    result = await writer.admit_publication(current, deadline=asyncio.get_running_loop().time() + 5)
    assert result['intent']['state'] == 'published' and result['owner'] is None
    assert state['document']['active_generation_id'] == 'later-generation'
    assert state['owner_writes'] == 0 and loads == []


@pytest.mark.parametrize('failure', ['pending', 'graph'])
@run_async
async def test_admission_refuses_pending_or_corrupt_graph_without_takeover(monkeypatch, failure):
    writer, state, _, _ = manager_writer(monkeypatch)
    if failure == 'pending':
        state['pending'] = [('reserved-predecessor',)]
    else:
        state['graph_error'] = True
    with pytest.raises(ProviderUnavailable if failure == 'pending' else IntegrityViolation):
        await writer.admit_publication(ctx(), deadline=asyncio.get_running_loop().time() + 5)
    assert state['owner_writes'] == 0 and state['intent']['state'] == 'staged'


@run_async
async def test_normal_admission_is_same_context_and_lost_commit_ack_reconciles(monkeypatch):
    writer, state, connections, loads = manager_writer(monkeypatch)
    state['commit_error'] = RuntimeError('PRIVATE_ACK_LOST')
    result = await writer.admit_publication(ctx(), deadline=asyncio.get_running_loop().time() + 5)
    assert result['owner'] == {'owner_token': ctx()['owner_token'], 'backend_epoch': 1}
    assert result['intent']['state'] == 'writing'
    assert state['owner_writes'] == 1 and len(loads) == 1
    assert len(connections) == 2 and connections[0].closed
    assert state['owner'][2] == ctx()['owner_token']


@run_async
async def test_body_operational_failure_is_not_retried_as_lost_commit(monkeypatch):
    writer, state, connections, _ = manager_writer(monkeypatch)
    state['body_error'] = ProviderUnavailable()
    with pytest.raises(ProviderUnavailable):
        await writer.admit_publication(ctx(), deadline=asyncio.get_running_loop().time() + 5)
    assert len(connections) == 1 and connections[0].rollbacks == 1
    assert state['owner_writes'] == 0


def manager_dispatch(state):
    identity = FIXTURE['members'][0]['point_id']
    body = json.dumps({'points': [identity]}, separators=(',', ':')).encode()
    state['dispatch'] = [(1, ctx()['owner_token'], 1, 'credential-1', 'delete_points',
        'settled', 'a' * 64, sha256(body).hexdigest(), body, 'instance-1', False)]
    state['dispatch_members'] = [('fixture-local', config()['physical_collection'],
                                 config()['collection_incarnation'], identity)]
    state['claims'] = [(identity,)]
    return identity


@run_async
async def test_dispatch_status_is_exact_scoped_metadata_not_completion_proof(monkeypatch):
    writer, state, _, _ = manager_writer(monkeypatch)
    assert await writer.dispatch_status(ctx(), 'absent', deadline=asyncio.get_running_loop().time() + 5) is None
    point = manager_dispatch(state)
    status = await writer.dispatch_status(ctx(), 'dispatch-1', deadline=asyncio.get_running_loop().time() + 5)
    assert status['completion_sha256'] == 'a' * 64 and status['point_ids'] == (point,)
    assert set(status) == {'dispatch_id', 'sequence', 'owner_token', 'backend_epoch',
        'credential_generation', 'operation', 'state', 'completion_sha256', 'request_sha256', 'point_ids'}
    with pytest.raises(TypeError):
        status['state'] = 'unknown'
    row = list(state['dispatch'][0])
    row[5], row[6] = 'unknown', None
    state['dispatch'] = [tuple(row)]
    unknown = await writer.dispatch_status(ctx(), 'dispatch-1', deadline=asyncio.get_running_loop().time() + 5)
    assert unknown['state'] == 'unknown' and unknown['completion_sha256'] is None
    assert state['dispatch'][0][5] == 'unknown'


@pytest.mark.parametrize('failure', ['hash', 'points', 'claim', 'physical', 'completion', 'sequence'])
@run_async
async def test_dispatch_status_rejects_contradictory_durable_metadata(monkeypatch, failure):
    writer, state, _, _ = manager_writer(monkeypatch)
    manager_dispatch(state)
    row = list(state['dispatch'][0])
    if failure == 'hash':
        row[7] = 'b' * 64
    elif failure == 'points':
        state['dispatch_members'] *= 2
    elif failure == 'claim':
        state['claims'] = []
    elif failure == 'physical':
        state['dispatch_members'][0] = ('foreign', *state['dispatch_members'][0][1:])
    elif failure == 'completion':
        row[6] = None
    else:
        row[0] = 257
    state['dispatch'] = [tuple(row)]
    with pytest.raises(IntegrityViolation):
        await writer.dispatch_status(ctx(), 'dispatch-1', deadline=asyncio.get_running_loop().time() + 5)


def manager_prepared(state):
    manager_dispatch(state)
    graph = stage_data(prepare_stage(stage_input()))
    state['intent']['state'] = 'prepared'
    state['owner'] = ('instance-1', ctx()['intent_id'], ctx()['owner_token'], 1)
    state['preparations'] = [(ctx()['owner_token'], 1, 'auth-1', 1,
                              state['intent']['manifest_sha256'], 'd' * 64)]
    state['original_payloads'] = [(graph.intent_encoding.encoded_bytes,
        graph.intent_encoding.sha256, graph.manifest_encoding.encoded_bytes)]
    state['selected_dispatches'] = [('dispatch-1', 1)]
    row = list(state['dispatch'][0])
    point = state['dispatch_members'][0][3]
    body = json.dumps({'points': [{'id': point, 'payload': {}, 'vector': {}}]},
                      separators=(',', ':')).encode()
    row[4], row[7], row[8] = 'complete_point_upsert', sha256(body).hexdigest(), body
    state['dispatch'] = [tuple(row)]


@run_async
async def test_publication_preparation_preserves_original_fences_under_fresh_current_scope(monkeypatch):
    writer, state, connections, _ = manager_writer(monkeypatch)
    manager_prepared(state)
    deadline = asyncio.get_running_loop().time() + 5
    metadata = await writer.publication_preparation(ctx(), deadline=deadline)
    assert metadata['preparation']['owner_token'] == ctx()['owner_token']
    assert metadata['dispatch']['dispatch_id'] == 'dispatch-1'
    assert 'request_bytes' not in metadata['dispatch']
    with pytest.raises(TypeError):
        metadata['preparation']['readback_sha256'] = 'e' * 64
    state['document'].update(authorization_revision='auth-2', mutation_epoch=2)
    fresh = copy.deepcopy(ctx())
    fresh['scope']['authorization_revision'] = 'auth-2'
    original = await writer.publication_preparation(fresh, deadline=deadline)
    assert original['preparation']['authorization_revision'] == 'auth-1'
    outcome = await writer.admit_publication(fresh, deadline=deadline)
    assert outcome['intent']['state'] == 'denied' and outcome['owner'] is None
    assert all(not sql.startswith(('INSERT ', 'UPDATE ', 'DELETE '))
               for sql, _ in connections[0].calls)


@run_async
async def test_preparation_metadata_allows_different_current_owner_then_fresh_admission(monkeypatch):
    writer, state, _, loads = manager_writer(monkeypatch)
    manager_prepared(state)
    state['owner'] = ('instance-1', 'quiescent-other-intent',
                      '22222222-2222-4222-8222-222222222222', 1)
    original_preparation = state['preparations'][0]
    deadline = asyncio.get_running_loop().time() + 5
    metadata = await writer.publication_preparation(ctx(), deadline=deadline)
    assert metadata['preparation']['owner_token'] == ctx()['owner_token']
    assert state['owner'][1] == 'quiescent-other-intent' and state['owner_writes'] == 0
    assert len(loads) == 1
    admitted = await writer.admit_publication(ctx(), deadline=deadline)
    assert admitted['owner']['owner_token'] == ctx()['owner_token']
    assert state['owner'][1:3] == (ctx()['intent_id'], ctx()['owner_token'])
    assert state['preparations'][0] == original_preparation


@pytest.mark.parametrize('failure,error', [('pending', ProviderUnavailable), ('graph', IntegrityViolation)])
@run_async
async def test_preparation_lookup_requires_full_graph_and_document_wide_settled_work(monkeypatch, failure, error):
    writer, state, _, _ = manager_writer(monkeypatch)
    manager_prepared(state)
    if failure == 'pending':
        state['pending'] = [('other-intent-unknown',)]
    else:
        state['graph_error'] = True
    with pytest.raises(error):
        await writer.publication_preparation(ctx(), deadline=asyncio.get_running_loop().time() + 5)
    assert state['owner_writes'] == 0


@pytest.mark.parametrize('failure,error', [('missing', IntegrityViolation), ('retired', ProviderUnavailable),
    ('manifest', IntegrityViolation), ('owner', IntegrityViolation), ('digest', IntegrityViolation)])
@run_async
async def test_publication_preparation_rejects_corruption_and_retired_bindings(monkeypatch, failure, error):
    writer, state, _, _ = manager_writer(monkeypatch)
    manager_prepared(state)
    if failure == 'missing':
        state['preparations'] = []
    elif failure == 'retired':
        state['backend'] = [(*state['backend'][0][:4], 2, 'open', None)]
    elif failure == 'manifest':
        row = state['original_payloads'][0]
        state['original_payloads'] = [(row[0], row[1], b'changed')]
    elif failure == 'owner':
        row = list(state['dispatch'][0])
        row[1] = '22222222-2222-4222-8222-222222222222'
        state['dispatch'] = [tuple(row)]
    else:
        row = list(state['preparations'][0])
        row[5] = 'invalid'
        state['preparations'] = [tuple(row)]
    with pytest.raises(error):
        await writer.publication_preparation(ctx(), deadline=asyncio.get_running_loop().time() + 5)


@pytest.mark.parametrize('profile', [2,3])
@run_async
async def test_writer_initialization_selects_complete_literal_role_profile_before_readiness(monkeypatch,profile):
    connection = Connection()
    if profile == 3:
        connection.history = list(implementation.EXPECTED_ATTESTATION_HISTORY)
        connection.hash = implementation.EXPECTED_ATTESTATION_CATALOG_FINGERPRINT
    writer = PostgresQdrantWriter(resource(monkeypatch,connection),config(),'instance-1')
    await writer.initialize(deadline=asyncio.get_running_loop().time()+5)
    role = implementation._WRITER_ATTESTATION_ROLE_SQL if profile==3 else implementation._WRITER_ROLE_SQL
    assert writer._schema_profile == profile and writer._ready
    assert next(index for index,(sql,_) in enumerate(connection.calls) if sql==implementation._HISTORY_SQL) < next(index for index,(sql,_) in enumerate(connection.calls) if sql==role)
    connection.calls.clear()
    await writer.inspect(ctx(),deadline=asyncio.get_running_loop().time()+5)
    assert any(sql==role for sql,_ in connection.calls)
    connection.role=False
    with pytest.raises(UnauthorizedScope):
        await writer.inspect(ctx(),deadline=asyncio.get_running_loop().time()+5)


@pytest.mark.parametrize('failure', ['fourth','hash','fingerprint'])
@run_async
async def test_writer_attestation_profile_rejects_unknown_history_without_mutation(monkeypatch,failure):
    connection=Connection()
    connection.history=list(implementation.EXPECTED_ATTESTATION_HISTORY)
    connection.hash=implementation.EXPECTED_ATTESTATION_CATALOG_FINGERPRINT
    if failure=='fourth':connection.history.append(('0004_other','a'*64))
    elif failure=='hash':connection.history[-1]=(connection.history[-1][0],'a'*64)
    else:connection.hash=implementation.EXPECTED_PUBLICATION_CATALOG_FINGERPRINT
    writer=PostgresQdrantWriter(resource(monkeypatch,connection),config(),'instance-1')
    with pytest.raises(UnsupportedCapability):
        await writer.initialize(deadline=asyncio.get_running_loop().time()+5)
    assert not writer._ready
    assert all(not sql.startswith(('INSERT ','UPDATE ','DELETE ')) for sql,_ in connection.calls)


def test_writer_attestation_literal_permissions_do_not_broaden_ordinary_profile():
    assert 'preparation_attestations' not in implementation._WRITER_ROLE_SQL
    assert implementation._WRITER_ATTESTATION_ROLE_SQL.count("'preparation_attestations')") == 4
    assert "has_table_privilege(current_user,'cragkit_qdrant.preparation_attestations','SELECT,INSERT')" in implementation._WRITER_ATTESTATION_ROLE_SQL
    assert "WHEN privilege='UPDATE' THEN c.relname IN ('documents','generations','publication_intents','document_owners','dispatch_journal')" in implementation._WRITER_ATTESTATION_ROLE_SQL


class AttestationConnection(ManagerConnection):
    """SQL transaction/acknowledgment double, not a physical F1 proof."""
    def transaction(self):
        transaction=super().transaction()
        owner=self
        class Transaction:
            async def __aenter__(self):
                return await transaction.__aenter__()
            async def __aexit__(self,kind,error,traceback):
                try:
                    return await transaction.__aexit__(kind,error,traceback)
                except RuntimeError:
                    if kind is None and owner.state.pop('commit_confirm_absent',False):
                        owner.state['attestations']=[]
                    raise
        return Transaction()
    async def execute(self,sql,params=None):
        if sql.startswith('SELECT instance_id,owner_token::text,backend_epoch,authorization_revision'):
            self.calls.append((sql,params))
            return Cursor([('instance-1',*row) for row in self.state['preparations']])
        if sql.startswith('SELECT tenant_id,collection,document_id,intent_id,instance_id,owner_token::text'):
            self.calls.append((sql,params))
            return Cursor(self.state.get('attestations',[]))
        if sql.startswith('INSERT INTO cragkit_qdrant.preparation_attestations'):
            self.calls.append((sql,params))
            self.state['insert_attempts']=self.state.get('insert_attempts',0)+1
            if self.state.get('insert_error') is not None:raise self.state['insert_error']
            self.state.setdefault('attestations',[]).append(tuple(params))
            return Cursor([])
        if sql.startswith('SELECT owner_token::text,backend_epoch,instance_id,manifest_sha256'):
            self.calls.append((sql,params))
            return Cursor([(row[0],row[1],'instance-1',row[4],row[2],row[3]) for row in self.state['preparations']])
        if sql.startswith('UPDATE cragkit_qdrant.generations') or sql.startswith('UPDATE cragkit_qdrant.documents'):
            self.calls.append((sql,params));self.state.setdefault('publication_updates',[]).append(sql);return Cursor([])
        if sql.startswith("UPDATE cragkit_qdrant.publication_intents SET state='published'"):
            self.calls.append((sql,params));self.state['intent']['state']='published';return Cursor([])
        return await super().execute(sql,params)


def attestation_writer(monkeypatch):
    writer,state,_,loads=manager_writer(monkeypatch)
    manager_prepared(state)
    writer._schema_profile=3
    state['attestations']=[]
    state['guard']=True
    state['document'].update(principal_ids=['reader-a'],grant_ids=['grant-a'],language=None,kind=None,tag=None)
    connections=[]
    @asynccontextmanager
    async def lease(self,*,deadline):
        connection=AttestationConnection(state);connections.append(connection);yield connection
    monkeypatch.setattr(PoolResource,'lease',lease)
    plan=prepare_stage(stage_input());graph=stage_data(plan)
    parsed=implementation.context(ctx())
    # Fences/proof bindings are explicit unit fixtures; native acceptance owns real receipts.
    async def fences(connection,selected):
        state['fence_reads']=state.get('fence_reads',0)+1
        return 2,state['document'],(graph.intent.expected_authorization_revision,graph.intent.expected_mutation_epoch,
            graph.intent.expected_active_generation_id,plan.manifest_sha256,graph.manifest.generation_id,
            graph.manifest.revision_id,state['intent']['state']),state.get('fence_failure')
    monkeypatch.setattr(writer,'_fences',fences)
    receipt,verifier,controller=object(),object(),object()
    data={'context':parsed,'attempt_binding':dict(instance_id='instance-1',storage_identity='storage-1',supervisor_id='supervisor-1',
        epoch=2,credential_generation='credential-2',intent_id=parsed.intent_id,owner_token=parsed.owner_token,dispatch_id='verification-2'),
        'projection':object(),'manifest_sha256':plan.manifest_sha256,'generation_id':graph.manifest.generation_id,
        'revision_id':graph.manifest.revision_id,'authorization_revision':'auth-1','mutation_epoch':1,
        'active_generation_id':graph.intent.expected_active_generation_id,'tombstoned':False,'readback_sha256':'e'*64}
    # Bind the fixture's metadata digest exactly; this is not a physical readback receipt.
    projected=implementation.finalize_publication_projection(writer,{
        'context':parsed,'attempt_binding':implementation.ordinary_binding(data['attempt_binding']),
        'manifest_sha256':plan.manifest_sha256,'revision_id':graph.manifest.revision_id,'generation_id':graph.manifest.generation_id,
        'authorization_revision':'auth-1','mutation_epoch':1,'active_generation_id':graph.intent.expected_active_generation_id,
        'tombstoned':False,'points':writer._projection_points(graph,state['document']),
        'authority':{key:state['document'][key] for key in ('principal_ids','grant_ids','language','kind','tag')}})
    data['projection']=projected
    data['readback_sha256']=implementation.publication_projection_data(projected,writer)['readback_sha256']
    async def receipt_data(selected,selected_verifier,expected_writer,*,deadline):
        if selected is not receipt or selected_verifier is not verifier or expected_writer is not writer:
            raise InvalidRequest()
        guard(controller,deadline=deadline)
        return data
    def guard(selected,*,deadline):
        if selected is not controller or not state['guard']:raise InvalidRequest()
    async def validate(projection,*,deadline):
        assert projection is data['projection'] and not any(connection.info.transaction_status==2 for connection in connections)
        state['projection_checks']=state.get('projection_checks',0)+1
    monkeypatch.setattr(implementation,'attestation_receipt_data',receipt_data)
    monkeypatch.setattr(implementation,'publication_verifier_controller',lambda selected,expected:controller)
    monkeypatch.setattr(implementation,'require_publication_finalization',guard)
    monkeypatch.setattr(writer,'validate_publication_projection',validate)
    return writer,state,connections,loads,receipt,verifier,data


@run_async
async def test_attestation_snapshot_same_key_retry_preserves_original_prepared_row(monkeypatch):
    writer,state,connections,loads,receipt,verifier,data=attestation_writer(monkeypatch)
    original=copy.deepcopy(state['preparations'])
    deadline=asyncio.get_running_loop().time()+5
    snapshot=await writer.attestation_snapshot(ctx(),deadline=deadline)
    assert snapshot['attestation'] is None and snapshot['preparation']['backend_epoch']==1
    result=await writer.attest_prepared(receipt,verifier,deadline=deadline)
    repeated=await writer.attest_prepared(receipt,verifier,deadline=deadline)
    assert result==repeated and state['insert_attempts']==1
    assert tuple(result['attestation'])==implementation._ATTESTATION_FIELDS
    assert result['attestation']['verification_id']=='verification-2' and result['attestation']['backend_epoch']==2
    assert state['intent']['state']=='prepared' and state['preparations']==original
    assert len(loads)>=3 and state['projection_checks']==2
    with pytest.raises(TypeError):result['attestation']['readback_sha256']='changed'
    assert all('SET state=\'writing\'' not in sql for connection in connections for sql,_ in connection.calls)


@pytest.mark.parametrize('failure', ['old_profile','receipt','context'])
@run_async
async def test_invalid_attestation_profile_or_private_binding_never_borrows(monkeypatch,failure):
    writer,state,connections,_,receipt,verifier,_=attestation_writer(monkeypatch)
    if failure=='old_profile':writer._schema_profile=2
    elif failure=='receipt':receipt=object()
    else:state['guard']=False
    with pytest.raises(UnsupportedCapability if failure=='old_profile' else InvalidRequest):
        await writer.attest_prepared(receipt,verifier,deadline=asyncio.get_running_loop().time()+5)
    assert connections==[]


@pytest.mark.parametrize('failure', ['digest','credential','verification','owner','epoch','pointer','shape'])
@run_async
async def test_current_attestation_rows_are_exact_and_contradictions_fail(monkeypatch,failure):
    writer,state,_,_,receipt,verifier,_=attestation_writer(monkeypatch)
    deadline=asyncio.get_running_loop().time()+5
    await writer.attest_prepared(receipt,verifier,deadline=deadline)
    values=list(state['attestations'][0]);fields=implementation._ATTESTATION_FIELDS
    key,value={'digest':('readback_sha256','bad'),'credential':('credential_generation','different'),
        'verification':('verification_id','different'),'owner':('owner_token','22222222-2222-4222-8222-222222222222'),
        'epoch':('backend_epoch',3),'pointer':('expected_active_generation_id','different'),
        'shape':('readback_sha256','bad')}[failure]
    values[fields.index(key)]=value
    state['attestations']=[tuple(values[:-1]) if failure=='shape' else tuple(values)]
    with pytest.raises(IntegrityViolation):
        await writer.attest_prepared(receipt,verifier,deadline=deadline)


@run_async
async def test_lost_attestation_commit_ack_confirms_same_key_with_fresh_fences(monkeypatch):
    writer,state,connections,_,receipt,verifier,_=attestation_writer(monkeypatch)
    state['commit_error']=RuntimeError('PRIVATE_ACTUAL_COMMIT_ACK_LOSS')
    result=await writer.attest_prepared(receipt,verifier,deadline=asyncio.get_running_loop().time()+5)
    assert result['attestation'] is not None and state['insert_attempts']==1 and len(connections)==2
    assert connections[0].closed and state['fence_reads']==2


@run_async
async def test_attestation_body_provider_failure_and_cancel_are_not_commit_unknown(monkeypatch):
    writer,state,connections,_,receipt,verifier,_=attestation_writer(monkeypatch)
    state['insert_error']=ProviderUnavailable()
    with pytest.raises(ProviderUnavailable):
        await writer.attest_prepared(receipt,verifier,deadline=asyncio.get_running_loop().time()+5)
    assert len(connections)==1 and connections[0].rollbacks==1 and state['attestations']==[]
    state['insert_error']=asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await writer.attest_prepared(receipt,verifier,deadline=asyncio.get_running_loop().time()+5)
    assert len(connections)==2 and state['attestations']==[]


@pytest.mark.parametrize('failure', ['denied','conflict'])
@run_async
async def test_changed_attestation_fences_persist_terminal_outcome_without_insert(monkeypatch,failure):
    writer,state,_,_,receipt,verifier,_=attestation_writer(monkeypatch)
    state['fence_failure']=failure
    result=await writer.attest_prepared(receipt,verifier,deadline=asyncio.get_running_loop().time()+5)
    assert result['intent']['state']==failure and result['attestation'] is None
    assert state['attestations']==[] and state['preparations'][0][1]==1


@run_async
async def test_publication_requires_current_effective_preparation_and_full_graph(monkeypatch):
    writer,state,_,loads,receipt,verifier,_=attestation_writer(monkeypatch)
    deadline=asyncio.get_running_loop().time()+5
    with pytest.raises(ProviderUnavailable):await writer.publish(ctx(),deadline=deadline)
    assert not state.get('publication_updates')
    await writer.attest_prepared(receipt,verifier,deadline=deadline)
    result=await writer.publish(ctx(),deadline=deadline)
    assert result['state']=='published' and len(loads)>=3
    assert state['preparations'][0][1]==1


@run_async
async def test_unknown_attestation_commit_absence_allows_one_same_key_sql_retry(monkeypatch):
    writer,state,connections,_,receipt,verifier,_=attestation_writer(monkeypatch)
    state['commit_error']=RuntimeError('PRIVATE_UNKNOWN_COMMIT')
    state['commit_confirm_absent']=True
    result=await writer.attest_prepared(receipt,verifier,deadline=asyncio.get_running_loop().time()+5)
    assert result['attestation'] is not None and len(state['attestations'])==1
    assert state['insert_attempts']==2 and len(connections)==3 and state['fence_reads']==3
    inserts=[params for connection in connections for sql,params in connection.calls
        if sql.startswith('INSERT INTO cragkit_qdrant.preparation_attestations')]
    assert len(inserts)==2 and inserts[0]==inserts[1]


@run_async
async def test_old_publication_profile_cannot_use_retired_original_preparation(monkeypatch):
    writer,state,_,_,_,_,_=attestation_writer(monkeypatch)
    writer._schema_profile=2
    with pytest.raises(ProviderUnavailable):
        await writer.publish(ctx(),deadline=asyncio.get_running_loop().time()+5)
    assert not state.get('publication_updates') and state['intent']['state']=='prepared'


@pytest.mark.parametrize('field,value', [('expected_active_generation_id','other-active'),
    ('expected_authorization_revision','other-auth'),('expected_mutation_epoch',2)])
@run_async
async def test_attestation_raw_intent_bytes_cannot_be_rebased_via_fence_columns(monkeypatch,field,value):
    writer,state,_,_,receipt,verifier,_=attestation_writer(monkeypatch)
    plan=prepare_stage(stage_input());graph=stage_data(plan)
    positions={'expected_authorization_revision':0,'expected_mutation_epoch':1,'expected_active_generation_id':2}
    original=(graph.intent.expected_authorization_revision,graph.intent.expected_mutation_epoch,
        graph.intent.expected_active_generation_id,plan.manifest_sha256,graph.manifest.generation_id,graph.manifest.revision_id,'prepared')
    changed=list(original);changed[positions[field]]=value
    async def fences(connection,selected):return 2,state['document'],tuple(changed),None
    monkeypatch.setattr(writer,'_fences',fences)
    with pytest.raises(IntegrityViolation):
        await writer.attest_prepared(receipt,verifier,deadline=asyncio.get_running_loop().time()+5)
    assert state['attestations']==[] and state['intent']['state']=='prepared'


@run_async
async def test_attestation_rejects_already_published_intent_instead_of_null_terminal(monkeypatch):
    writer,state,_,_,receipt,verifier,_=attestation_writer(monkeypatch)
    state['intent']['state']='published'
    with pytest.raises(InvalidRequest):
        await writer.attest_prepared(receipt,verifier,deadline=asyncio.get_running_loop().time()+5)
    assert state['attestations']==[]


@run_async
@pytest.mark.parametrize('outcome', ['prepared', 'denied', 'conflict', 'published'])
async def test_repair_preflight_locks_without_owner_or_epoch_mutation(monkeypatch, outcome):
    writer,state,connections,loads,receipt,verifier,data=attestation_writer(monkeypatch)
    order=[]
    plan=prepare_stage(stage_input()); graph=stage_data(plan)
    original=(graph.intent.expected_authorization_revision, graph.intent.expected_mutation_epoch,
        graph.intent.expected_active_generation_id, plan.manifest_sha256,
        graph.manifest.generation_id, graph.manifest.revision_id, 'prepared')
    state['intent']['state']='published' if outcome=='published' else 'prepared'
    document=dict(state['document'])
    if outcome=='denied': document['tombstoned']=True
    if outcome=='conflict': document['active_generation_id']='winner-generation'
    backend=dict(instance_id='instance-1',state='recovery_blocked',epoch=2,recovery_id='recovery-1')
    owner=dict(instance_id='instance-1',intent_id=ctx()['intent_id'],owner_token=ctx()['owner_token'],backend_epoch=1)
    async def get_backend(connection,*,lock=False):
        assert lock;order.append('backend');return backend
    async def get_owner(connection,context,*,lock=False):
        assert lock;order.append('owner');return owner
    async def get_document(connection,context,*,lock=False):
        assert lock;order.append('document');return document
    async def get_intent(connection,context):return state['intent']
    original_query=writer._query
    async def query(connection,sql,params=()):
        if sql.startswith('SELECT expected_authorization_revision,expected_mutation_epoch,expected_active_generation_id,manifest_sha256'):
            return [original]
        if sql.startswith('SELECT dispatch_id FROM cragkit_qdrant.dispatch_journal'):
            return [('unknown-target',)]
        return await original_query(connection,sql,params)
    async def changed(connection,context,selected):
        state['intent']['state']=selected;return state['intent']
    for name,method in [('_manager_backend',get_backend),('_manager_owner',get_owner),
            ('_manager_document',get_document),('_manager_intent',get_intent),('_query',query),('_outcome',changed)]:
        monkeypatch.setattr(writer,name,method)
    result=await writer.preflight_repair(ctx(),deadline=asyncio.get_running_loop().time()+5)
    assert set(result)=={'intent','owner','backend','pending'}
    assert order==['backend','owner','document'] and result['pending']
    assert result['intent']['state']==outcome and owner['backend_epoch']==1 and backend['epoch']==2
    assert state.get('insert_attempts',0)==0 and state.get('publication_updates',[])==[]


@run_async
async def test_repair_preflight_old_profile_fails_before_checkout(monkeypatch):
    writer,state,connections,loads,receipt,verifier,data=attestation_writer(monkeypatch)
    writer._schema_profile=2
    with pytest.raises(UnsupportedCapability):
        await writer.preflight_repair(ctx(),deadline=asyncio.get_running_loop().time()+5)
    assert connections==[]
