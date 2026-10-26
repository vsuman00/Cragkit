"""Pure admission and committed writer lifecycle, without services/providers."""
import asyncio
import copy
from functools import wraps
from contextlib import asynccontextmanager
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest

import cragkit._qdrant_writer as implementation
from cragkit._postgres_pool import PoolConfig, PoolResource
from cragkit._qdrant_writer import PostgresQdrantWriter, prepare_stage
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
        if sql==implementation._WRITER_ROLE_SQL:return Cursor([(self.role,)])
        if sql==implementation._HISTORY_SQL:return Cursor(self.history)
        if sql==implementation._PUBLICATION_CATALOG_SQL:return Cursor([(True,)])
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
