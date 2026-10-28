import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {PoolResource,parse_pool_config,now} from '../dist/postgres-pool.js';
import {PostgresQdrantWriter,prepare_stage,projection_data,publication_projection_data,writer_binding,WRITER_ROLE_SQL,WRITER_ATTESTATION_ROLE_SQL} from '../dist/qdrant-writer.js';
import {stage_data} from '../dist/qdrant-writer-contract.js';
import {AUTHORITY_HISTORY_SQL,AUTHORITY_PUBLICATION_HISTORY,AUTHORITY_PUBLICATION_CATALOG_SQL,
  AUTHORITY_FINGERPRINT_SQL,EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT,
  AUTHORITY_ATTESTATION_HISTORY,AUTHORITY_ATTESTATION_CATALOG_SQL,EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT} from '../dist/qdrant-authority.js';
import {ManagedQdrantSupervisor} from '../dist/qdrant-supervisor.js';
import {QdrantReconciliationVerifier} from '../dist/qdrant-reconciliation.js';
import {PostgresQdrantRecovery,RECOVERY_ROLE_SQL} from '../dist/qdrant-recovery.js';
import {QdrantPublicationVerifier} from '../dist/qdrant-publication-verification.js';
import {publication_finalization} from '../dist/qdrant-publication-worker.js';
import {encode_dense_replay,encode_manifest} from '../dist/qdrant-manifest.js';
import {point_id} from '../dist/qdrant-contract.js';
import {OPENAI_PROFILE} from '../dist/embeddings.js';
import {InvalidRequest,IntegrityViolation,UnauthorizedScope,UnsupportedCapability,IndexNotReady,
  ProviderUnavailable,DeadlineExceeded,EmbeddingProfileMismatch} from '../dist/errors.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_publication.json',import.meta.url),'utf8'));
const token='00000000-0000-4000-8000-000000000001';
const scope={tenant_id:'tenant-a',principal_id:'reader-a',grant_ids:['grant-a'],authorization_revision:'auth-1'};
const config={...fixture.physical,dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse};
const context={scope,collection:'docs',document_id:'doc-1',intent_id:'intent-2',owner_token:token};
const opts=()=>({deadline:now()+5});
const stageOpts=()=>({...opts(),owner_token:token});
const digest=value=>createHash('sha256').update(value).digest('hex');
const dispatchRequest={dispatch_id:'dispatch-manager',sequence:1,credential_generation:'credential-1',
  operation:'complete_point_upsert',point_ids:fixture.members.map(member=>member.point_id)};
function input(){
  const manifest={...fixture.physical,tenant_id:'tenant-a',collection:'docs',document_id:'doc-1',
    revision_id:fixture.source_revision.revision_id,generation_id:fixture.intent.generation_id,
    source_sha256:fixture.source_revision.source_sha256,source_bytes:fixture.source_revision.source_bytes,
    source_locator:fixture.source_revision.source_locator,parser_id:fixture.source_revision.parser_id,
    chunker_profile:fixture.intent.chunker_profile,dense_profile:structuredClone(fixture.profiles.dense),
    sparse_profile:structuredClone(fixture.profiles.sparse),members:fixture.members.map(member=>({
      chunk_id:member.chunk_id,point_id:member.point_id,start_byte:member.start_byte,end_byte:member.end_byte,
      text_sha256:member.text_sha256,dense_input_sha256:member.dense.vector_sha256,sparse_input_sha256:member.sparse.vector_sha256}))};
  const intent={intent_id:'intent-2',tenant_id:'tenant-a',collection:'docs',document_id:'doc-1',
    manifest_sha256:fixture.intent.manifest_sha256,expected_active_generation_id:null,
    expected_authorization_revision:'auth-1',expected_mutation_epoch:1,
    initial_authorization:{authorization_revision:'auth-1',principal_ids:['reader-a'],grant_ids:['grant-a'],
      language:'en',kind:'guide',tag:'reference',tombstoned:false}};
  return {manifest,intent,canonical_text:fixture.source_revision.canonical_utf8.value,
    dense_vectors:fixture.members.map(member=>Array.from({length:1536},(_,i)=>i===member.dense.basis_index?1:0)),
    sparse_vectors:fixture.members.map(member=>({indices:[...member.sparse.indices],values:[...member.sparse.values]}))};
}
function clone(value){
  if(Buffer.isBuffer(value))return Buffer.from(value);
  if(Array.isArray(value))return value.map(clone);
  if(value&&typeof value==='object')return Object.fromEntries(Object.entries(value).map(([key,item])=>[key,clone(item)]));
  return value;
}

/** A deterministic SQL-call double, not evidence of PostgreSQL constraint behavior. */
function setup(){
  const state={queries:[],clients:[],role:true,history:AUTHORITY_PUBLICATION_HISTORY.map(row=>[...row]),
    catalog:true,fingerprint:EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT,startStatus:'I',commitLost:false,
    rollbackFail:false,wait:null,commitError:null,tables:{backend_instances:[{instance_id:'instance-fixture',backend_namespace:'fixture-local',
      storage_identity:'storage-fixture',supervisor_id:'supervisor-fixture',epoch:1,state:'open',recovery_id:null}]}};
  const keys={documents:['tenant_id','collection','document_id'],document_revisions:['tenant_id','collection','document_id','revision_id'],
    generations:['tenant_id','collection','document_id','generation_id'],members:['tenant_id','collection','document_id','revision_id','generation_id','chunk_id'],
    publication_intents:['tenant_id','collection','document_id','intent_id'],point_claims:['backend_namespace','physical_collection','collection_incarnation','point_id'],
    vector_replays:['tenant_id','collection','document_id','revision_id','generation_id','chunk_id'],document_owners:['tenant_id','collection','document_id'],
    dispatch_journal:['tenant_id','collection','document_id','intent_id','dispatch_id'],dispatch_points:['tenant_id','collection','document_id','intent_id','dispatch_id','point_id'],
    preparations:['tenant_id','collection','document_id','intent_id'],preparation_attestations:['tenant_id','collection','document_id','intent_id','backend_epoch','owner_token']};
  const pool={ends:0,async end(){this.ends++;},async connect(){
    const client={status:state.startStatus,releases:[],snapshot:null,getTransactionStatus(){return this.status;},release(value=false){this.releases.push(value);},
      async query(query){
        const sql=query.text,params=query.values??[];state.queries.push(query);
        if(sql.startsWith('BEGIN')){this.attestationInserted=false;this.snapshot=clone(state.tables);this.status='T';return {rows:[]};}
        if(sql==='ROLLBACK'){if(state.rollbackFail)throw Error('private rollback');state.tables=this.snapshot;this.status='I';return {rows:[]};}
        if(sql==='COMMIT'){
          this.status='I';
          if(this.attestationInserted&&state.attestationCommitLost){state.attestationCommitLost=false;state.onAttestationLost?.();throw Error('synthetic attestation commit acknowledgment loss');}
          if(state.commitError){const failure=state.commitError;state.commitError=null;state.tables=this.snapshot;throw failure;}
          if(state.commitLost){state.commitLost=false;state.onLostCommit?.();throw Error('private lost acknowledgment');}
          return {rows:[]};
        }
        if(sql===WRITER_ATTESTATION_ROLE_SQL)return {rows:[[state.role&&state.attestationRole!==false]]};
        if(sql===RECOVERY_ROLE_SQL)return {rows:[[state.recoveryRole!==false]]};
        if(sql===WRITER_ROLE_SQL){if(state.wait)await state.wait;return {rows:[[state.role]]};}
        if(sql===AUTHORITY_HISTORY_SQL)return {rows:state.history};
        if(sql===AUTHORITY_PUBLICATION_CATALOG_SQL||sql===AUTHORITY_ATTESTATION_CATALOG_SQL)return {rows:[[state.catalog]]};
        if(sql===AUTHORITY_FINGERPRINT_SQL)return {rows:[[state.fingerprint]]};
        if(sql.startsWith('SET ')||sql.startsWith('SELECT set_config'))return {rows:[]};
        const insert=/^INSERT INTO cragkit_qdrant\.(\w+) \(([^)]+)\)/.exec(sql);
        if(insert){
          const [,table,columns]=insert;
          if(table==='preparation_attestations'){if(state.attestationBodyError)throw state.attestationBodyError;this.attestationInserted=true;}
          const row=Object.fromEntries(columns.split(',').map((column,i)=>[column,['dense_profile','sparse_profile'].includes(column)&&params[i]!==null?JSON.parse(params[i]):clone(params[i])]));
          const rows=state.tables[table]??=[];
          if(rows.some(existing=>keys[table].every(key=>existing[key]===row[key])))return {rows:[]};
          if(table==='documents')Object.assign(row,{active_generation_id:null,...row});
          if(table==='generations')Object.assign(row,{published:false,ever_published:false,...row});
          if(table==='publication_intents')Object.assign(row,{state:'staged',authority_committed:false,replica_complete:false,purge_complete:false,...row});
          if(table==='dispatch_journal')Object.assign(row,{state:'reserved',recovery:false,completion_sha256:null,...row});
          rows.push(row);return {rows:sql.includes('RETURNING document_id')?[[row.document_id]]:[]};
        }
        const select=/^SELECT (.+?) FROM cragkit_qdrant\.(\w+) WHERE /.exec(sql);
        if(select){
          const [,columns,table]=select;
          if(table==='document_owners'&&sql.includes('FOR UPDATE')&&state.onOwnerLock){
            const boundary=state.onOwnerLock;state.onOwnerLock=null;boundary(state);
          }
          let rows=(state.tables[table]??[]).filter(row=>table==='backend_instances'?row.instance_id===params[0]:
            row.tenant_id===params[0]&&row.collection===params[1]&&row.document_id===params[2]);
          for(const [column,number] of [...sql.matchAll(/(?:AND |\()((?:intent|dispatch|revision|generation|chunk|point)_id|payload_sha256|backend_namespace|physical_collection|collection_incarnation|backend_epoch|owner_token|instance_id)=\$(\d+)(?!\d)/g)].map(match=>[match[1],Number(match[2])])){
            rows=rows.filter(row=>row[column]===params[number-1]);
          }
          if(sql.includes('point_id=ANY'))rows=rows.filter(row=>params[3].includes(row.point_id));
          if(sql.includes("state<>'settled'"))rows=rows.filter(row=>row.state!=='settled');
          if(sql.includes('manifest_sha256<>$6'))rows=rows.filter(row=>row.manifest_sha256!==params[5]);
          const limit=Number(/LIMIT (\d+)/.exec(sql)?.[1]??65);
          return {rows:rows.slice(0,limit).map(row=>columns.split(',').map(column=>clone(row[column.replace('::text','')])))};
        }
        const update=/^UPDATE cragkit_qdrant\.(\w+) SET /.exec(sql);
        if(update){
          const table=update[1];let rows=(state.tables[table]??[]).filter(row=>row.tenant_id===params[0]&&row.collection===params[1]&&row.document_id===params[2]);
          if(table==='publication_intents'){
            const id=sql.includes('state=$4')?params[4]:params[3];rows=rows.filter(row=>row.intent_id===id);
            for(const row of rows){row.state=sql.includes('state=$4')?params[3]:/state='([^']+)'/.exec(sql)[1];
              if(sql.includes('authority_committed=true'))row.authority_committed=true;if(sql.includes('replica_complete=true'))row.replica_complete=true;}
          }else if(table==='document_owners')for(const row of rows)Object.assign(row,{instance_id:params[3],intent_id:params[4],owner_token:params[5],backend_epoch:params[6]});
          else if(table==='dispatch_journal'){
            rows=rows.filter(row=>row.intent_id===params[3]&&row.dispatch_id===params[4]);for(const row of rows)Object.assign(row,{state:params[5],completion_sha256:params[6]});
          }else if(table==='documents'){
            if(sql.includes('SET active_generation_id'))for(const row of rows)row.active_generation_id=params[3];
            else for(const row of rows)Object.assign(row,{principal_ids:params[3],grant_ids:params[4],authorization_revision:params[5],mutation_epoch:params[6],language:params[7],kind:params[8],tag:params[9],tombstoned:params[10]});
          }else if(table==='generations'){
            for(const row of rows){if(sql.includes('published=false')){if(row.generation_id!==params[3])row.published=false;}
              else if(row.generation_id===params[3]){row.published=true;row.ever_published=true;}}
          }
          return {rows:sql.includes('RETURNING document_id')?rows.map(row=>[row.document_id]):[]};
        }
        throw Error('unexpected synthetic SQL');
      }};
    state.clients.push(client);return client;
  }};
  const resource=new PoolResource(parse_pool_config({host:'host.invalid',dbname:'fixture',user:'writer',
    sslrootcert:'/fake/ca',passfile:'/fake/pass',release_timeout:.05,close_timeout:.1}),{pool});
  return {state,pool,resource,writer:new PostgresQdrantWriter(resource,config,'instance-fixture')};
}

test('writer binding exposes immutable original constructor metadata without I/O or resource access',async()=>{
  const f=setup();
  const raw=structuredClone(config);
  const writer=new PostgresQdrantWriter(f.resource,raw,'original-instance');
  try{
    raw.physical_collection='changed_after_constructor';
    const binding=writer_binding(writer);
    assert.deepEqual(Object.keys(binding).sort(),['config','instance_id']);
    assert.equal(binding.instance_id,'original-instance');
    assert.equal(binding.config.physical_collection,config.physical_collection);
    assert.ok(Object.isFrozen(binding));
    assert.ok(Object.isFrozen(binding.config));
    assert.ok(Object.isFrozen(binding.config.dense_profile));
    assert.throws(()=>{binding.config.dense_profile.model='changed';},TypeError);
    assert.equal(f.state.queries.length,0);
    assert.equal(f.state.clients.length,0);
    assert.equal(f.pool.ends,0);
    assert.equal('resource'in binding,false);
  }finally{await writer.close();await f.writer.close();await f.resource.close();}
});

test('writer binding rejects copied, unregistered, subclass and proxy objects before I/O',async()=>{
  const f=setup();
  class Foreign extends PostgresQdrantWriter {}
  const child=new Foreign(f.resource,config,'child-instance');
  try{
    for(const value of [null,{}, {...f.writer},Object.create(PostgresQdrantWriter.prototype),child,new Proxy(f.writer,{})]){
      assert.throws(()=>writer_binding(value),InvalidRequest);
    }
    assert.equal(f.state.queries.length,0);
    assert.equal(f.state.clients.length,0);
  }finally{await child.close();await f.writer.close();await f.resource.close();}
});

test('private immutable StagePlan binds vectors and exact declared member seals',()=>{
  const raw=input(),plan=prepare_stage(raw);
  assert.ok(Object.isFrozen(plan));assert.equal(plan.manifest_sha256,fixture.intent.manifest_sha256);
  assert.deepEqual(Object.keys(plan).sort(),['manifest_sha256','member_count','payload_sha256']);
  raw.dense_vectors[0][0]=0;raw.canonical_text='changed';
  assert.equal(plan.member_count,2);assert.equal(JSON.stringify(plan).includes('café'),false);
  assert.throws(()=>prepare_stage({...input(),dense_batches:[]}),InvalidRequest);
  const wrong=input();wrong.dense_vectors[0][0]=0;wrong.dense_vectors[0][1]=1;
  assert.throws(()=>prepare_stage(wrong),IntegrityViolation);
});

const ordinaryBinding={instance_id:'instance-fixture',storage_identity:'storage-fixture',supervisor_id:'supervisor-fixture',
  epoch:1,credential_generation:'credential-1',intent_id:context.intent_id,owner_token:token,dispatch_id:'readback-1'};

async function ordinarySetup(){
  const f=setup();
  Object.assign(f.state.tables.backend_instances[0],{storage_identity:ordinaryBinding.storage_identity,
    supervisor_id:ordinaryBinding.supervisor_id,recovery_id:null});
  await f.writer.initialize(opts());
  await f.writer.stage(prepare_stage(input()),scope,stageOpts());
  await f.writer.acquire_owner(context,opts());
  return f;
}

test('manager snapshots are immutable metadata for absent, scoped and staged targets',async()=>{
  const f=setup();
  try{
    await f.writer.initialize(opts());
    const empty=await f.writer.manager_snapshot(context,opts());
    assert.deepEqual({intent:empty.intent,document:empty.document,owner:empty.owner,max_sequence:empty.max_sequence,pending:empty.pending},
      {intent:null,document:null,owner:null,max_sequence:0,pending:false});
    assert.ok(Object.isFrozen(empty.backend));
    await f.writer.stage(prepare_stage(input()),scope,stageOpts());
    const staged=await f.writer.manager_snapshot(context,opts());
    assert.equal(staged.intent.state,'staged');
    assert.equal(staged.document.authorization_revision,'auth-1');
    assert.ok(Object.isFrozen(staged.document));
    assert.equal(JSON.stringify(staged).includes('canonical_utf8'),false);
    const hidden=await f.writer.manager_snapshot({...context,scope:{...scope,tenant_id:'foreign'}},opts());
    assert.equal(hidden.document,null);
    assert.equal(hidden.intent,null);
    await assert.rejects(f.writer.manager_snapshot({...context,scope:{...scope,authorization_revision:'stale'}},opts()),UnauthorizedScope);
  }finally{await f.writer.close();await f.resource.close();}
});

test('snapshot sequences are intent-scoped while pending work includes predecessor intents',async()=>{
  const f=await ordinarySetup();
  try{
    f.state.tables.dispatch_journal=[
      {tenant_id:scope.tenant_id,collection:'docs',document_id:'doc-1',intent_id:context.intent_id,dispatch_id:'current-1',sequence:2,state:'settled'},
      {tenant_id:scope.tenant_id,collection:'docs',document_id:'doc-1',intent_id:'predecessor',dispatch_id:'old',sequence:200,state:'unknown'},
    ];
    const result=await f.writer.manager_snapshot(context,opts());
    assert.equal(result.max_sequence,2);
    assert.equal(result.pending,true);
    assert.equal(result.owner.owner_token,token);
    f.state.tables.dispatch_journal.push({...f.state.tables.dispatch_journal[0],dispatch_id:'duplicate-sequence'});
    await assert.rejects(f.writer.manager_snapshot(context,opts()),IntegrityViolation);
    f.state.tables.dispatch_journal=Array.from({length:257},(_,i)=>({...f.state.tables.dispatch_journal[0],dispatch_id:'d-'+i,sequence:i+1}));
    await assert.rejects(f.writer.manager_snapshot(context,opts()),IntegrityViolation);
  }finally{await f.writer.close();await f.resource.close();}
});

test('publication admission validates the whole stage before acquiring a stable owner',async()=>{
  const f=setup();
  try{
    await f.writer.initialize(opts());
    await f.writer.stage(prepare_stage(input()),scope,stageOpts());
    const admitted=await f.writer.admit_publication(context,opts());
    assert.equal(admitted.intent.state,'writing');
    assert.deepEqual(admitted.owner,{owner_token:token,backend_epoch:1});
    assert.ok(Object.isFrozen(admitted.owner));
    assert.deepEqual(await f.writer.admit_publication(context,opts()),admitted);
    f.state.tables.vector_replays.pop();
    await assert.rejects(f.writer.admit_publication(context,opts()),IntegrityViolation);
  }finally{await f.writer.close();await f.resource.close();}
});

test('original fence admission persists terminal outcomes before owner takeover',async()=>{
  for(const failure of ['denied','conflict']){
    const f=await ordinarySetup();
    try{
      const replacement='00000000-0000-4000-8000-000000000002';
      Object.assign(f.state.tables.document_owners[0],{intent_id:'newer-intent',owner_token:replacement});
      let current=context;
      if(failure==='denied'){
        Object.assign(f.state.tables.documents[0],{authorization_revision:'auth-2',mutation_epoch:2,tombstoned:true});
        await assert.rejects(f.writer.admit_publication(context,opts()),UnauthorizedScope);
        assert.equal((await f.writer.inspect(context,opts())).state,'writing');
        current={...context,scope:{...scope,authorization_revision:'auth-2'}};
      }else{
        f.state.tables.documents[0].active_generation_id='newer-generation';
      }
      const result=await f.writer.admit_publication(current,opts());
      assert.equal(result.intent.state,failure);
      assert.equal(result.owner,null);
      assert.equal(f.state.tables.document_owners[0].owner_token,replacement);
      const pointer=f.state.tables.documents[0].active_generation_id;
      f.state.tables.backend_instances[0].state='recovery_blocked';
      f.state.tables.backend_instances[0].recovery_id='recovery-1';
      assert.deepEqual(await f.writer.admit_publication(current,opts()),result);
      assert.equal(f.state.tables.documents[0].active_generation_id,pointer);
    }finally{await f.writer.close();await f.resource.close();}
  }
});

test('admission refreshes fences after owner wait and refuses unresolved predecessor work',async()=>{
  const f=await ordinarySetup();
  try{
    f.state.onOwnerLock=state=>{
      state.tables.documents[0].active_generation_id='winner';
      state.tables.document_owners[0].owner_token='00000000-0000-4000-8000-000000000002';
    };
    const start=f.state.queries.length;
    const result=await f.writer.admit_publication(context,opts());
    assert.equal(result.intent.state,'conflict');
    assert.equal(result.owner,null);
    const queries=f.state.queries.slice(start).map(query=>query.text);
    const backend=queries.findIndex(sql=>sql.includes('backend_instances')&&sql.endsWith('FOR SHARE'));
    const owner=queries.findIndex(sql=>sql.includes('document_owners')&&sql.endsWith('FOR UPDATE'));
    const document=queries.findIndex(sql=>sql.includes('FROM cragkit_qdrant.documents')&&sql.endsWith('FOR UPDATE'));
    assert.ok(backend>=0&&owner>backend&&document>owner);
  }finally{await f.writer.close();await f.resource.close();}
  const blocked=await ordinarySetup();
  try{
    blocked.state.tables.dispatch_journal=[{tenant_id:scope.tenant_id,collection:'docs',document_id:'doc-1',intent_id:'predecessor',state:'reserved'}];
    await assert.rejects(blocked.writer.admit_publication({...context,owner_token:'00000000-0000-4000-8000-000000000003'},opts()),ProviderUnavailable);
    assert.equal(blocked.state.tables.document_owners[0].owner_token,token);
  }finally{await blocked.writer.close();await blocked.resource.close();}
});

test('admission observes the same intent published during its owner-lock wait',async()=>{
  const f=await ordinarySetup();
  try{
    f.state.onOwnerLock=state=>{
      Object.assign(state.tables.publication_intents[0],{state:'published',authority_committed:true,replica_complete:true});
      state.tables.documents[0].active_generation_id=fixture.intent.generation_id;
      state.tables.document_owners[0].owner_token='00000000-0000-4000-8000-000000000002';
    };
    const start=f.state.queries.length;
    const result=await f.writer.admit_publication(context,opts());
    assert.equal(result.intent.state,'published');
    assert.equal(result.owner,null);
    assert.equal(f.state.queries.slice(start).some(query=>/^UPDATE cragkit_qdrant\.(document_owners|publication_intents)/.test(query.text)),false);
  }finally{await f.writer.close();await f.resource.close();}
});

test('admission lost COMMIT acknowledgment reconciles only the same identity',async()=>{
  const f=setup();
  try{
    await f.writer.initialize(opts());
    await f.writer.stage(prepare_stage(input()),scope,stageOpts());
    f.state.commitLost=true;
    f.state.onLostCommit=()=>{f.state.tables.documents[0].active_generation_id='changed-after-admission';};
    const result=await f.writer.admit_publication(context,opts());
    assert.deepEqual(result.owner,{owner_token:token,backend_epoch:1});
    assert.equal(result.intent.state,'writing','confirmed historical admission is metadata, not new mutation permission');
    assert.equal(f.state.tables.document_owners.length,1);
    assert.ok(f.state.clients.some(client=>client.releases.includes(true)));
    assert.equal(f.state.queries.filter(query=>query.text.startsWith('INSERT INTO cragkit_qdrant.document_owners')).length,1);
    assert.equal((await f.writer.admit_publication(context,opts())).intent.state,'conflict');
  }finally{await f.writer.close();await f.resource.close();}
});

test('known commit failures and native cancellation never retry admission',async()=>{
  for(const [failure,expected] of [
    [Object.assign(Error('private known rollback'),{code:'23514'}),IntegrityViolation],
    [new DOMException('private cancellation','AbortError'),error=>error.name==='AbortError'],
    [new DeadlineExceeded(),DeadlineExceeded],
  ]){
    const f=setup();
    try{
      await f.writer.initialize(opts());
      await f.writer.stage(prepare_stage(input()),scope,stageOpts());
      f.state.commitError=failure;
      const start=f.state.queries.length;
      await assert.rejects(f.writer.admit_publication(context,opts()),expected);
      assert.equal(f.state.queries.slice(start).filter(query=>query.text.startsWith('BEGIN')).length,1);
    }finally{await f.writer.close();await f.resource.close();}
  }
});

test('dispatch metadata reconciles exact completion without exposing or replaying bytes',async()=>{
  const f=await ordinarySetup();
  try{
    assert.equal(await f.writer.dispatch_status(context,'missing',opts()),null);
    const reserved=await f.writer.reserve_dispatch(context,dispatchRequest,opts());
    const status=await f.writer.dispatch_status(context,dispatchRequest.dispatch_id,opts());
    assert.equal(status.state,'reserved');
    assert.equal(status.request_sha256,reserved.request_sha256);
    assert.deepEqual(status.point_ids,[...dispatchRequest.point_ids].sort());
    assert.equal('request_bytes'in status,false);
    assert.ok(Object.isFrozen(status.point_ids));
    await f.writer.mark_dispatched(context,dispatchRequest.dispatch_id,opts());
    f.state.commitLost=true;
    await f.writer.settle_dispatch(context,dispatchRequest.dispatch_id,'f'.repeat(64),opts());
    const completed=await f.writer.dispatch_status(context,dispatchRequest.dispatch_id,opts());
    assert.equal(completed.state,'settled');
    assert.equal(completed.completion_sha256,'f'.repeat(64));
    assert.equal(await f.writer.dispatch_status({...context,intent_id:'different-intent'},dispatchRequest.dispatch_id,opts()),null);
    f.state.tables.documents[0].authorization_revision='auth-2';
    await assert.rejects(f.writer.dispatch_status(context,dispatchRequest.dispatch_id,opts()),UnauthorizedScope);
    const fresh={...context,scope:{...scope,authorization_revision:'auth-2'}};
    assert.deepEqual(await f.writer.dispatch_status(fresh,dispatchRequest.dispatch_id,opts()),completed);
  }finally{await f.writer.close();await f.resource.close();}
});

test('dispatch status requires a currently authorized document even for missing IDs',async()=>{
  const f=setup();
  try{
    await f.writer.initialize(opts());
    await assert.rejects(f.writer.dispatch_status(context,'missing',opts()),UnauthorizedScope);
  }finally{await f.writer.close();await f.resource.close();}
});

test('preparation lookup returns original fences and selected settled dispatch under fresh caller scope',async()=>{
  const f=await ordinarySetup();
  try{
    assert.equal(await f.writer.publication_preparation(context,opts()),null);
    await f.writer.reserve_dispatch(context,dispatchRequest,opts());
    await f.writer.settle_dispatch(context,dispatchRequest.dispatch_id,'a'.repeat(64),opts());
    await f.writer.prepare(context,'b'.repeat(64),opts());
    const prepared=await f.writer.publication_preparation(context,opts());
    assert.equal(prepared.preparation.readback_sha256,'b'.repeat(64));
    assert.equal(prepared.dispatch.dispatch_id,dispatchRequest.dispatch_id);
    assert.equal(prepared.preparation.owner_token,token);
    assert.equal('request_bytes'in prepared.dispatch,false);
    assert.ok(Object.isFrozen(prepared.preparation));
    Object.assign(f.state.tables.documents[0],{authorization_revision:'auth-2',mutation_epoch:2,tombstoned:true});
    await assert.rejects(f.writer.publication_preparation(context,opts()),UnauthorizedScope);
    const fresh={...context,scope:{...scope,authorization_revision:'auth-2'}};
    assert.deepEqual(await f.writer.publication_preparation(fresh,opts()),prepared);
    assert.equal((await f.writer.admit_publication(fresh,opts())).intent.state,'denied');
  }finally{await f.writer.close();await f.resource.close();}
});

test('preparation lookup rejects retired epochs and contradictory original metadata',async()=>{
  for(const [change,error] of [
    [f=>{f.state.tables.backend_instances[0].epoch=2;},ProviderUnavailable],
    [f=>{f.state.tables.preparations[0].authorization_revision='wrong';},IntegrityViolation],
    [f=>{f.state.tables.dispatch_journal[0].owner_token='00000000-0000-4000-8000-000000000002';},IntegrityViolation],
    [f=>{f.state.tables.preparations=[];},IntegrityViolation],
  ]){
    const f=await ordinarySetup();
    try{
      await f.writer.reserve_dispatch(context,dispatchRequest,opts());
      await f.writer.settle_dispatch(context,dispatchRequest.dispatch_id,'a'.repeat(64),opts());
      await f.writer.prepare(context,'b'.repeat(64),opts());
      change(f);
      await assert.rejects(f.writer.publication_preparation(context,opts()),error);
    }finally{await f.writer.close();await f.resource.close();}
  }
});

test('preparation metadata does not authorize owner takeover after its read',async()=>{
  const f=await ordinarySetup();
  try{
    await f.writer.reserve_dispatch(context,dispatchRequest,opts());
    await f.writer.settle_dispatch(context,dispatchRequest.dispatch_id,'a'.repeat(64),opts());
    await f.writer.prepare(context,'b'.repeat(64),opts());
    const replacement='00000000-0000-4000-8000-000000000002';
    Object.assign(f.state.tables.document_owners[0],{intent_id:'replacement-intent',owner_token:replacement});
    const lookup={...context,owner_token:'00000000-0000-4000-8000-000000000003'};
    const metadata=await f.writer.publication_preparation(lookup,opts());
    assert.equal(metadata.preparation.owner_token,token);
    assert.equal(f.state.tables.document_owners[0].owner_token,replacement,'metadata does not mutate current owner');
    f.state.tables.dispatch_journal.push({tenant_id:scope.tenant_id,collection:'docs',document_id:'doc-1',
      intent_id:'replacement-intent',dispatch_id:'pending-replacement',sequence:1,state:'unknown'});
    await assert.rejects(f.writer.publication_preparation(lookup,opts()),ProviderUnavailable);
    await assert.rejects(f.writer.admit_publication(context,opts()),ProviderUnavailable);
    assert.equal(f.state.tables.document_owners[0].owner_token,replacement);
    f.state.tables.dispatch_journal.pop();
    const admitted=await f.writer.admit_publication(context,opts());
    assert.equal(admitted.intent.state,'prepared');
    assert.equal(admitted.owner.owner_token,token);
    assert.equal(f.state.tables.document_owners[0].owner_token,token);
  }finally{await f.writer.close();await f.resource.close();}
});

test('dispatch status rejects malformed journal, membership and self-hashed wrong IDs',async()=>{
  for(const change of [
    f=>{f.state.tables.dispatch_journal[0].sequence=257;},
    f=>{f.state.tables.dispatch_journal[0].completion_sha256='a'.repeat(64);},
    f=>{f.state.tables.dispatch_points[0].physical_collection='foreign';},
    f=>{f.state.tables.point_claims[0].instance_id='foreign';},
    f=>{
      const journal=f.state.tables.dispatch_journal[0];
      const body=JSON.parse(journal.request_bytes);
      body.points[0].id='ffffffff-ffff-5fff-8fff-ffffffffffff';
      journal.request_bytes=Buffer.from(JSON.stringify(body));
      journal.request_sha256=digest(journal.request_bytes);
    },
  ]){
    const f=await ordinarySetup();
    try{
      await f.writer.reserve_dispatch(context,dispatchRequest,opts());
      change(f);
      await assert.rejects(f.writer.dispatch_status(context,dispatchRequest.dispatch_id,opts()),IntegrityViolation);
    }finally{await f.writer.close();await f.resource.close();}
  }
});

test('ordinary publication projection binds complete raw graph, current payload and fixed witness',async()=>{
  const f=await ordinarySetup();
  try{
    const projection=await f.writer.project_publication(context,ordinaryBinding,opts());
    const data=publication_projection_data(projection,f.writer);
    assert.deepEqual(JSON.parse(JSON.stringify(projection)),{});
    assert.ok(Object.isFrozen(data.witness));
    assert.equal(data.witness.length,21);
    assert.equal(data.witness[0],'cragkit.qdrant.publication.readback.v1');
    assert.equal(data.point_ids.length,2);
    assert.equal(data.readback_sha256,digest(Buffer.from(data.encoded_bytes)));
    assert.equal(data.points[0].payload.authorization_revision,'auth-1');
    assert.equal('canonical_text'in data,false);
    assert.throws(()=>publication_projection_data({...projection},f.writer),InvalidRequest);
    await f.writer.validate_publication_projection(projection,opts());
    f.state.tables.documents[0].tag='changed';
    await assert.rejects(f.writer.validate_publication_projection(projection,opts()),UnauthorizedScope);
  }finally{await f.writer.close();await f.resource.close();}
});

test('ordinary publication rejects target mismatch before SQL and document-wide pending work',async()=>{
  const f=await ordinarySetup();
  try{
    const before=f.state.queries.length;
    await assert.rejects(f.writer.project_publication(context,{...ordinaryBinding,intent_id:'foreign'},opts()),UnsupportedCapability);
    assert.equal(f.state.queries.length,before);
    f.state.tables.dispatch_journal=[{tenant_id:scope.tenant_id,collection:context.collection,document_id:context.document_id,
      intent_id:'predecessor-intent',state:'unknown'}];
    await assert.rejects(f.writer.project_publication(context,ordinaryBinding,opts()),ProviderUnavailable);
    f.state.tables.dispatch_journal=[];
    f.state.tables.vector_replays.pop();
    await assert.rejects(f.writer.project_publication(context,ordinaryBinding,opts()),IntegrityViolation);
  }finally{await f.writer.close();await f.resource.close();}
});

test('ordinary publication distinguishes current backend and authority fences',async()=>{
  for(const [change,error] of [
    [f=>{f.state.tables.backend_instances[0].epoch=2;},ProviderUnavailable],
    [f=>{f.state.tables.backend_instances[0].state='recovery_blocked';},ProviderUnavailable],
    [f=>{f.state.tables.backend_instances[0].storage_identity='different';},IntegrityViolation],
    [f=>{f.state.tables.document_owners[0].owner_token='00000000-0000-4000-8000-000000000002';},ProviderUnavailable],
    [f=>{f.state.tables.documents[0].authorization_revision='auth-2';},UnauthorizedScope],
    [f=>{f.state.tables.documents[0].tombstoned=true;},UnauthorizedScope],
  ]){
    const f=await ordinarySetup();
    try{
      change(f);
      await assert.rejects(f.writer.project_publication(context,ordinaryBinding,opts()),error);
    }finally{await f.writer.close();await f.resource.close();}
  }
});

test('real profiles require bound full E batches before SQL',()=>{
  const raw=input();raw.manifest.dense_profile=OPENAI_PROFILE;raw.manifest.sparse_profile=null;raw.sparse_vectors=null;
  for(let i=0;i<raw.manifest.members.length;i++){
    const member=raw.manifest.members[i];const tuple=[...fixture.members[i].identity_tuple];tuple[10]=OPENAI_PROFILE.profile_id;tuple[11]='';
    member.point_id=point_id(tuple);member.dense_input_sha256=encode_dense_replay(raw.dense_vectors[i],OPENAI_PROFILE).input_sha256;member.sparse_input_sha256=null;
  }
  raw.intent.manifest_sha256=encode_manifest(raw.manifest,raw.canonical_text).sha256;
  assert.throws(()=>prepare_stage(raw),EmbeddingProfileMismatch);
  const vectors=raw.dense_vectors;delete raw.dense_vectors;
  raw.dense_batches=[{profile:OPENAI_PROFILE,vectors,usage:{prompt_tokens:1,total_tokens:1,cost_usd:0,cost_kind:'estimated'},provider_calls:1,synthetic:false}];
  assert.doesNotThrow(()=>prepare_stage(raw));
  raw.dense_batches[0].synthetic=true;
  assert.throws(()=>prepare_stage(raw),EmbeddingProfileMismatch);
});

test('malformed inputs, proxies and copied plans fail before database checkout',async()=>{
  const x=setup();let hooks=0;
  const malicious=new Proxy(input(),{ownKeys(){hooks++;throw Error('private');}});
  assert.throws(()=>prepare_stage(malicious),InvalidRequest);
  await assert.rejects(x.writer.stage({...prepare_stage(input())},scope,stageOpts()),InvalidRequest);
  await assert.rejects(x.writer.inspect({...context,collection:undefined},opts()),InvalidRequest);
  assert.equal(hooks,0);assert.equal(x.state.clients.length,0);await x.writer.close();await x.resource.close();
});

test('explicit initialization is exact new profile and each lease requires dedicated writer safety',async()=>{
  const x=setup();await assert.rejects(x.writer.inspect(context,opts()),IndexNotReady);
  await x.writer.initialize(opts());assert.ok(x.state.queries.some(query=>query.text==='BEGIN ISOLATION LEVEL READ COMMITTED'));
  await x.writer.inspect(context,opts());assert.equal(x.state.queries.filter(query=>query.text===WRITER_ROLE_SQL).length,2);
  x.state.role=false;await assert.rejects(x.writer.inspect(context,opts()),UnauthorizedScope);
  assert.ok(WRITER_ROLE_SQL.includes("pg_has_role(current_user,capability.oid,'USAGE')"));
  assert.ok(WRITER_ROLE_SQL.includes('capability.rolcanlogin OR capability.rolsuper OR capability.rolbypassrls OR capability.rolcreaterole OR capability.rolcreatedb OR capability.rolreplication'));
  assert.ok(WRITER_ROLE_SQL.includes('membership.member=capability.oid'));
  assert.ok(WRITER_ROLE_SQL.includes("WHEN privilege='UPDATE' THEN c.relname IN ('documents','generations','publication_intents','document_owners','dispatch_journal')"));
  assert.ok(WRITER_ROLE_SQL.includes("(c.relname='members' AND a.attname='point_id')"));
  assert.ok(WRITER_ROLE_SQL.includes("p.oid IS NOT DISTINCT FROM to_regprocedure"));
  assert.equal(WRITER_ROLE_SQL.includes("has_table_privilege('cragkit_qdrant_writer'"),false);
  await x.writer.close();await x.resource.close();assert.equal(x.pool.ends,0);
});

test('wrong history, drift and dirty leases fail closed',async()=>{
  for(const change of [state=>{state.history=[];},state=>{state.fingerprint='bad';},state=>{state.catalog=false;}]){
    const x=setup();change(x.state);await assert.rejects(x.writer.initialize(opts()),UnsupportedCapability);await x.writer.close();await x.resource.close();
  }
  const x=setup();x.state.startStatus='T';await assert.rejects(x.writer.initialize(opts()),InvalidRequest);
  assert.deepEqual(x.state.clients[0].releases,[true]);await x.writer.close();await x.resource.close();
});

test('atomic stage replay compares immutable facts and scope without adopting changed input',async()=>{
  const x=setup();await x.writer.initialize(opts());const raw=input(),plan=prepare_stage(raw);
  const first=await x.writer.stage(plan,scope,stageOpts());assert.equal(first.state,'staged');
  await x.writer.stage(plan,scope,stageOpts());assert.equal(x.state.tables.members.length,2);
  const changed=input();changed.intent.initial_authorization.tag='changed';
  await assert.rejects(x.writer.stage(prepare_stage(changed),scope,stageOpts()),IntegrityViolation);
  await assert.rejects(x.writer.stage(plan,{...scope,tenant_id:'foreign'},stageOpts()),UnauthorizedScope);
  const scoped=x.state.queries.find(query=>query.text.includes("set_config('cragkit_qdrant.writer_document_id'"));
  assert.equal(scoped.values.length,9);assert.deepEqual(scoped.values.slice(0,3),['tenant-a','docs','reader-a']);
  await x.writer.close();await x.resource.close();
});

test('lost stage commit acknowledgment reconciles the same identity without duplicate generation',async()=>{
  const x=setup();await x.writer.initialize(opts());x.state.commitLost=true;
  const result=await x.writer.stage(prepare_stage(input()),scope,stageOpts());
  assert.equal(result.state,'staged');assert.equal(x.state.tables.generations.length,1);assert.equal(x.state.tables.members.length,2);
  assert.ok(x.state.clients.some(client=>client.releases.includes(true)));await x.writer.close();await x.resource.close();
});

test('reservation constructs complete immutable wire bytes and binds exact point set',async()=>{
  const x=setup();await x.writer.initialize(opts());await x.writer.stage(prepare_stage(input()),scope,stageOpts());
  const owner=await x.writer.acquire_owner(context,opts());assert.deepEqual(owner,{owner_token:token,backend_epoch:1});
  const request={dispatch_id:'dispatch-1',sequence:1,credential_generation:'credential-1',operation:'complete_point_upsert',point_ids:fixture.members.map(member=>member.point_id)};
  const reservation=await x.writer.reserve_dispatch(context,request,opts());
  assert.ok(Object.isFrozen(reservation.request_bytes));assert.equal(digest(Buffer.from(reservation.request_bytes)),reservation.request_sha256);
  const body=JSON.parse(Buffer.from(reservation.request_bytes));assert.equal(body.points.length,2);
  for(const point of body.points){assert.deepEqual(Object.keys(point.vector).sort(),['dense','sparse']);assert.equal(point.payload.authorization_revision,'auth-1');assert.equal('text'in point.payload,false);}
  assert.equal(await x.writer.mark_dispatched(context,'dispatch-1',opts()),undefined);
  await x.writer.mark_unknown(context,'dispatch-1',opts());
  await assert.rejects(x.writer.settle_dispatch(context,'dispatch-1','a'.repeat(64),opts()),ProviderUnavailable);
  await assert.rejects(x.writer.mark_dispatched(context,'dispatch-1',opts()),ProviderUnavailable);
  const before=x.state.queries.length;await assert.rejects(x.writer.reserve_dispatch(context,{...request,dispatch_id:'dispatch-2',sequence:2},opts()),ProviderUnavailable);
  assert.ok(x.state.queries.slice(before).findIndex(query=>query.text.includes('backend_instances')&&query.text.includes('FOR SHARE'))<x.state.queries.slice(before).findIndex(query=>query.text.includes('document_owners')&&query.text.includes('FOR UPDATE')));
  await x.writer.close();await x.resource.close();
});

test('settled preparation publication and immediate tombstone are authority transactions only',async()=>{
  const x=setup();await x.writer.initialize(opts());await x.writer.stage(prepare_stage(input()),scope,stageOpts());await x.writer.acquire_owner(context,opts());
  await x.writer.reserve_dispatch(context,{dispatch_id:'dispatch-1',sequence:1,credential_generation:'credential-1',operation:'complete_point_upsert',point_ids:fixture.members.map(member=>member.point_id)},opts());
  await x.writer.settle_dispatch(context,'dispatch-1','b'.repeat(64),opts());
  await x.writer.prepare(context,'c'.repeat(64),opts());await x.writer.publish(context,opts());
  assert.equal((await x.writer.inspect(context,opts())).state,'published');
  const security={action:'tombstone',intent_id:'tombstone-1',tenant_id:'tenant-a',collection:'docs',document_id:'doc-1',
    expected_authorization_revision:'auth-1',expected_mutation_epoch:1,authorization:{authorization_revision:'auth-2',principal_ids:[],grant_ids:[],language:null,kind:null,tag:null,tombstoned:true}};
  const start=x.state.queries.length;const result=await x.writer.apply_security(security,scope,stageOpts());assert.equal(result.authority_committed,true);
  await x.writer.apply_security(security,scope,stageOpts());assert.equal(x.state.tables.documents[0].mutation_epoch,2);
  assert.equal(x.state.queries.slice(start).some(query=>query.text.includes('FOR SHARE')),false);
  await x.writer.close();await x.resource.close();
});

test('completed publication receipt survives a later active generation without republishing',async()=>{
  const x=setup();
  await x.writer.initialize(opts());
  await x.writer.stage(prepare_stage(input()),scope,stageOpts());
  await x.writer.acquire_owner(context,opts());
  await x.writer.prepare(context,'c'.repeat(64),opts());
  const receipt=await x.writer.publish(context,opts());
  x.state.tables.documents[0].active_generation_id='successor-generation';
  x.state.tables.generations[0].published=false;
  const start=x.state.queries.length;
  assert.deepEqual(await x.writer.publish(context,opts()),receipt);
  assert.equal(x.state.tables.documents[0].active_generation_id,'successor-generation');
  assert.equal(x.state.queries.slice(start).some(query=>query.text.startsWith('UPDATE cragkit_qdrant.')),false);
  await x.writer.close();await x.resource.close();
});

test('single active operation, midflight cancellation and close are bounded and caller-owned',async()=>{
  const x=setup();await x.writer.initialize(opts());let finish;x.state.wait=new Promise(resolve=>{finish=resolve;});
  const controller=new AbortController();const pending=x.writer.inspect(context,{...opts(),signal:controller.signal});
  const stopped=assert.rejects(pending,error=>error.name==='AbortError');await new Promise(resolve=>setImmediate(resolve));
  await assert.rejects(x.writer.inspect(context,opts()),ProviderUnavailable);controller.abort();await stopped;
  finish();x.state.wait=null;await x.writer.close();await x.writer.close();await assert.rejects(x.writer.inspect(context,opts()),ProviderUnavailable);
  await x.resource.close();assert.equal(x.pool.ends,0);
});

test('expired or malformed deadlines never check out a client',async()=>{
  const x=setup();for(const value of [NaN,Infinity,Number.MAX_SAFE_INTEGER+1])await assert.rejects(x.writer.initialize({deadline:value}),InvalidRequest);
  await assert.rejects(x.writer.initialize({deadline:now()-1}),DeadlineExceeded);assert.equal(x.state.clients.length,0);await x.writer.close();await x.resource.close();
});

test('fresh scope revision is checked before new staging and reservation bytes', async () => {
  const x=setup();
  await x.writer.initialize(opts());
  const before=x.state.clients.length;
  await assert.rejects(x.writer.stage(prepare_stage(input()), {...scope,authorization_revision:'wrong'}, stageOpts()), UnauthorizedScope);
  assert.equal(x.state.clients.length,before);
  await x.writer.stage(prepare_stage(input()),scope,stageOpts());
  await x.writer.acquire_owner(context,opts());
  const dispatch={dispatch_id:'dispatch-1',sequence:1,credential_generation:'credential-1',operation:'complete_point_upsert',point_ids:fixture.members.map(member=>member.point_id)};
  await x.writer.reserve_dispatch(context,dispatch,opts());
  const wrong={...context,scope:{...scope,authorization_revision:'wrong'}};
  await assert.rejects(x.writer.reserve_dispatch(wrong,dispatch,opts()),UnauthorizedScope);
  assert.equal(x.state.tables.publication_intents[0].state,'writing');
  await x.writer.close();await x.resource.close();
});

test('prepare and publish persist terminal fence outcomes even after another owner replaces them', async () => {
  for(const method of ['prepare','publish']){
    for(const failure of ['denied','conflict','scope-only']){
      const x=setup();await x.writer.initialize(opts());
      await x.writer.stage(prepare_stage(input()),scope,stageOpts());await x.writer.acquire_owner(context,opts());
      if(method==='publish')await x.writer.prepare(context,'c'.repeat(64),opts());
      const before=x.state.queries.length;
      let current=context;
      if(failure==='denied')Object.assign(x.state.tables.documents[0],{authorization_revision:'auth-2',mutation_epoch:2,tombstoned:true});
      if(failure==='conflict'){
        x.state.tables.documents[0].active_generation_id='other-generation';
        Object.assign(x.state.tables.document_owners[0],{intent_id:'other-intent',owner_token:'00000000-0000-4000-8000-000000000002'});
      }
      if(failure==='scope-only')current={...context,scope:{...scope,authorization_revision:'wrong'}};
      const run=()=>method==='prepare'?x.writer.prepare(current,'c'.repeat(64),opts()):x.writer.publish(current,opts());
      if(failure==='scope-only'){
        await assert.rejects(run(),UnauthorizedScope);
        assert.equal(x.state.tables.publication_intents[0].state,method==='prepare'?'writing':'prepared');
      }else{
        const result=await run();assert.equal(result.state,failure);assert.ok(Object.isFrozen(result));
        assert.equal((await x.writer.inspect(context,opts())).state,failure);
      }
      assert.equal(x.state.queries.slice(before).some(query=>query.text.includes('FOR SHARE')),false);
      await x.writer.close();await x.resource.close();
    }
  }
});

test('restart load_stage issues a private plan from verified original sidecars without rounded readmission', async () => {
  const x=setup();await x.writer.initialize(opts());
  const raw=input();raw.dense_vectors[0][0]=1.00099999;
  raw.manifest.members[0].dense_input_sha256=encode_dense_replay(raw.dense_vectors[0],config.dense_profile).input_sha256;
  raw.intent.manifest_sha256=encode_manifest(raw.manifest,raw.canonical_text).sha256;
  await x.writer.stage(prepare_stage(raw),scope,stageOpts());await x.writer.close();
  const restarted=new PostgresQdrantWriter(x.resource,config,'instance-fixture');await restarted.initialize(opts());
  const loaded=await restarted.load_stage(context,opts());
  assert.ok(Object.isFrozen(loaded));assert.equal(loaded.manifest_sha256,raw.intent.manifest_sha256);
  assert.equal(JSON.stringify(loaded).includes('café'),false);
  const data=stage_data(loaded);
  assert.ok(Object.isFrozen(data.record));assert.ok(data.dense[0].encoded.values[0]-1>0.001);
  assert.equal(data.dense[0].input_sha256,raw.manifest.members[0].dense_input_sha256);
  await assert.rejects(restarted.load_stage({...context,scope:{...scope,authorization_revision:'wrong'}},opts()),UnauthorizedScope);
  x.state.tables.vector_replays[0].dense_blob[40]^=1;
  await assert.rejects(restarted.load_stage(context,opts()),IntegrityViolation);
  await restarted.close();await x.resource.close();
});

test('revocation blocks new dispatch admission but not honest known or unknown outcome records', async () => {
  for(const outcome of ['dispatch-denied','settled','unknown']){
    const x=setup();await x.writer.initialize(opts());
    await x.writer.stage(prepare_stage(input()),scope,stageOpts());await x.writer.acquire_owner(context,opts());
    await x.writer.reserve_dispatch(context,{dispatch_id:'dispatch-1',sequence:1,credential_generation:'credential-1',
      operation:'complete_point_upsert',point_ids:fixture.members.map(member=>member.point_id)},opts());
    if(outcome!=='dispatch-denied')await x.writer.mark_dispatched(context,'dispatch-1',opts());
    Object.assign(x.state.tables.documents[0],{authorization_revision:'auth-2',mutation_epoch:2,principal_ids:[],grant_ids:[]});
    if(outcome==='dispatch-denied'){
      await assert.rejects(x.writer.mark_dispatched(context,'dispatch-1',opts()),UnauthorizedScope);
      assert.equal(x.state.tables.dispatch_journal[0].state,'reserved');
    }else if(outcome==='settled'){
      await x.writer.settle_dispatch(context,'dispatch-1','d'.repeat(64),opts());
      assert.equal(x.state.tables.dispatch_journal[0].state,'settled');
    }else{
      await x.writer.mark_unknown(context,'dispatch-1',opts());
      assert.equal(x.state.tables.dispatch_journal[0].state,'unknown');
    }
    await x.writer.close();await x.resource.close();
  }
});

test('CAS refreshes terminal fences after the owner-lock wait before validating the old token', async () => {
  for(const method of ['prepare','publish']){
    for(const change of ['denied','conflict','owner-only']){
      const x=setup();await x.writer.initialize(opts());
      await x.writer.stage(prepare_stage(input()),scope,stageOpts());await x.writer.acquire_owner(context,opts());
      if(method==='publish')await x.writer.prepare(context,'e'.repeat(64),opts());
      const start=x.state.queries.length;
      x.state.onOwnerLock=state=>{
        Object.assign(state.tables.document_owners[0],{intent_id:'new-intent',owner_token:'00000000-0000-4000-8000-000000000002'});
        if(change==='denied')Object.assign(state.tables.documents[0],{authorization_revision:'auth-2',mutation_epoch:2});
        if(change==='conflict')state.tables.documents[0].active_generation_id='new-generation';
      };
      const run=()=>method==='prepare'?x.writer.prepare(context,'e'.repeat(64),opts()):x.writer.publish(context,opts());
      if(change==='owner-only'){
        await assert.rejects(run(),ProviderUnavailable);
        assert.equal(x.state.tables.publication_intents[0].state,method==='prepare'?'writing':'prepared');
      }else{
        const receipt=await run();assert.equal(receipt.state,change);
        assert.equal((await x.writer.inspect(context,opts())).state,change);
      }
      const queries=x.state.queries.slice(start);
      const owner=queries.findIndex(query=>query.text.includes('FROM cragkit_qdrant.document_owners')&&query.text.includes('FOR UPDATE'));
      const document=queries.findIndex(query=>query.text.includes('FROM cragkit_qdrant.documents')&&query.text.includes('FOR UPDATE'));
      assert.ok(owner>=0&&document>owner);
      await x.writer.close();await x.resource.close();
    }
  }
});

test('one generation cannot acquire a second different manifest through a new intent',async()=>{
  const x=setup();await x.writer.initialize(opts());await x.writer.stage(prepare_stage(input()),scope,stageOpts());
  const changed=input();changed.intent.intent_id='other-stage';changed.intent.initial_authorization=null;
  for(let i=0;i<changed.manifest.members.length;i++){
    const member=changed.manifest.members[i];member.chunk_id='replacement-'+i;
    const tuple=[...fixture.members[i].identity_tuple];tuple[9]=member.chunk_id;member.point_id=point_id(tuple);
  }
  changed.intent.manifest_sha256=encode_manifest(changed.manifest,changed.canonical_text).sha256;
  const before=x.state.queries.length;
  await assert.rejects(x.writer.stage(prepare_stage(changed),scope,stageOpts()),IntegrityViolation);
  assert.equal(x.state.tables.members.length,2);assert.equal(x.state.tables.publication_intents.length,1);
  assert.equal(x.state.queries.slice(before).some(query=>query.text.startsWith('INSERT INTO cragkit_qdrant.members')),false);
  await x.writer.close();await x.resource.close();
});

function blocked(x){
  Object.assign(x.state.tables.backend_instances[0],{state:'recovery_blocked',epoch:2,recovery_id:'recovery-1',
    storage_identity:'storage-fixture',supervisor_id:'supervisor-fixture'});
  x.state.tables.document_owners[0].backend_epoch=2;
  return {instance_id:'instance-fixture',storage_identity:'storage-fixture',supervisor_id:'supervisor-fixture',
    recovery_id:'recovery-1',old_epoch:1,new_epoch:2,credential_generation:'credential-2'};
}
test('private recovery projection binds exact current authority and physical epoch',async()=>{
  const x=setup();await x.writer.initialize(opts());await x.writer.stage(prepare_stage(input()),scope,stageOpts());
  await x.writer.acquire_owner(context,opts());const physical=blocked(x);
  const projection=await x.writer.project_stage(context,physical,opts()),data=projection_data(projection,x.writer);
  assert.ok(Object.isFrozen(projection));assert.deepEqual(JSON.parse(JSON.stringify(projection)),{});
  assert.equal(data.points.length,2);assert.equal(data.manifest_sha256,fixture.intent.manifest_sha256);
  assert.ok(Object.isFrozen(data.points[0].payload));assert.equal('canonical_text'in data,false);
  await x.writer.validate_projection(projection,opts());
  await assert.rejects(x.writer.validate_projection({...projection},opts()),InvalidRequest);
  await assert.rejects(x.writer.project_stage(context,{...physical,storage_identity:'foreign'},opts()),IntegrityViolation);
  x.state.tables.document_owners[0].backend_epoch=1;
  await assert.rejects(x.writer.project_stage(context,physical,opts()),ProviderUnavailable);
  await x.writer.close();await x.resource.close();
});
test('projection validation rechecks full graph and mutable authority before receipt admission',async()=>{
  for(const change of ['metadata','authorization','tombstone']){
    const x=setup();await x.writer.initialize(opts());await x.writer.stage(prepare_stage(input()),scope,stageOpts());
    await x.writer.acquire_owner(context,opts());const projection=await x.writer.project_stage(context,blocked(x),opts());
    const document=x.state.tables.documents[0];
    if(change==='metadata')document.tag='changed';
    if(change==='authorization')document.authorization_revision='auth-2';
    if(change==='tombstone')document.tombstoned=true;
    await assert.rejects(x.writer.validate_projection(projection,opts()),UnauthorizedScope);
    assert.equal(x.state.tables.backend_instances[0].state,'recovery_blocked');
    await x.writer.close();await x.resource.close();
  }
});

test('projection distinguishes unavailable recovery control from immutable physical contradictions',async()=>{
  for(const change of ['wrong-instance','missing','open','epoch','recovery-id','namespace','storage','supervisor']){
    const x=setup();await x.writer.initialize(opts());await x.writer.stage(prepare_stage(input()),scope,stageOpts());
    await x.writer.acquire_owner(context,opts());const physical=blocked(x),backend=x.state.tables.backend_instances[0];
    const clients=x.state.clients.length;
    if(change==='wrong-instance')physical.instance_id='other-instance';
    if(change==='missing')x.state.tables.backend_instances=[];
    if(change==='open')backend.state='open';
    if(change==='epoch')backend.epoch=3;
    if(change==='recovery-id')backend.recovery_id='other-recovery';
    if(change==='namespace')backend.backend_namespace='other-namespace';
    if(change==='storage')backend.storage_identity='other-storage';
    if(change==='supervisor')backend.supervisor_id='other-supervisor';
    const expected=change==='wrong-instance'?UnsupportedCapability:
      ['namespace','storage','supervisor'].includes(change)?IntegrityViolation:ProviderUnavailable;
    await assert.rejects(x.writer.project_stage(context,physical,opts()),expected);
    if(change==='wrong-instance')assert.equal(x.state.clients.length,clients);
    await x.writer.close();await x.resource.close();
  }
});

function useAttestationProfile(f){f.state.history=AUTHORITY_ATTESTATION_HISTORY.map(row=>[...row]);f.state.fingerprint=EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT;}
/** Actual private F1 provenance/context over deterministic SQL/HTTP doubles, not native proof. */
async function attestationSetup(){
  const f=setup();useAttestationProfile(f);await f.writer.initialize(opts());
  await f.writer.stage(prepare_stage(input()),scope,stageOpts());await f.writer.acquire_owner(context,opts());
  await f.writer.reserve_dispatch(context,dispatchRequest,opts());await f.writer.settle_dispatch(context,dispatchRequest.dispatch_id,'a'.repeat(64),opts());
  await f.writer.prepare(context,'b'.repeat(64),opts());
  const original=clone(f.state.tables.preparations[0]);
  f.state.tables.backend_instances[0].epoch=2;f.state.tables.document_owners[0].backend_epoch=2;
  const binding={instance_id:'instance-fixture',storage_identity:'storage-fixture',supervisor_id:'supervisor-fixture',epoch:2,credential_generation:'credential-2',intent_id:context.intent_id,owner_token:context.owner_token,dispatch_id:'verification-2'};
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/worker-fixture','instance-fixture',config),attempt=Object.freeze({});
  f.state.httpCalls=0;f.state.session=false;
  supervisor.attempt_binding=selected=>{if(selected!==attempt)throw new InvalidRequest();return {...binding};};
  supervisor.control_binding=()=>({instance_id:binding.instance_id,backend_namespace:config.backend_namespace,storage_identity:binding.storage_identity,supervisor_id:binding.supervisor_id,epoch:binding.epoch,credential_generation:binding.credential_generation,recovery:null,sealed:false,alive:true});
  supervisor.control_session=async body=>{if(f.state.session)throw new ProviderUnavailable();f.state.session=true;try{return await body({});}finally{f.state.session=false;}};
  const projection=await f.writer.project_publication(context,binding,opts()),expected=publication_projection_data(projection,f.writer);
  const records=expected.points.map(point=>({id:point.point_id,payload:clone(point.payload),vector:{dense:[...point.dense.values],sparse:{indices:[...point.sparse.indices],values:[...point.sparse.values]}}}));
  supervisor.transport_for=selected=>{if(selected!==attempt)throw new InvalidRequest();return {async close(){},async request(method,path,request){
    assert.equal(f.state.clients.every(client=>client.status==='I'||client.releases.includes(true)),true);f.state.httpCalls++;
    const body=JSON.parse(Buffer.from(request.body)),response={status:'ok',result:path.endsWith('/scroll')?{points:records,next_page_offset:null}:records.filter(point=>body.ids.includes(point.id))};return [...Buffer.from(JSON.stringify(response))];
  }};};
  const verifier=new QdrantPublicationVerifier(f.writer,supervisor),receipt=await verifier.verify(attempt,context,opts());
  return {...f,original,binding,supervisor,attempt,verifier,receipt,
    run:async(operation,options=opts())=>publication_finalization(supervisor,attempt,()=>operation(options),options),
    close:async()=>{await verifier.close();await f.writer.close();await f.resource.close();}};
}

test('writer selects literal ordinary or attestation permissions only after exact bounded history',async()=>{
  assert.equal(WRITER_ROLE_SQL.includes('preparation_attestations'),false);
  assert.equal((WRITER_ATTESTATION_ROLE_SQL.match(/'preparation_attestations'/g)??[]).length,4);
  for(const attestation of [false,true]){
    const f=setup();if(attestation)useAttestationProfile(f);
    try{
      await f.writer.initialize(opts());const role=attestation?WRITER_ATTESTATION_ROLE_SQL:WRITER_ROLE_SQL;
      assert(f.state.queries.findIndex(query=>query.text===AUTHORITY_HISTORY_SQL)<f.state.queries.findIndex(query=>query.text===role));
      const start=f.state.queries.length;await f.writer.inspect(context,opts());assert(f.state.queries.slice(start).some(query=>query.text===role));
      assert.equal(f.state.queries.slice(start).some(query=>query.text===(attestation?WRITER_ROLE_SQL:WRITER_ATTESTATION_ROLE_SQL)),false);
      f.state.role=false;await assert.rejects(f.writer.inspect(context,opts()),UnauthorizedScope);
    }finally{await f.writer.close();await f.resource.close();}
  }
});
test('writer rejects unknown fourth history, incorrect attestation hash/fingerprint and unsafe grants',async()=>{
  for(const change of [state=>state.history.push(['0004_unknown','a'.repeat(64)]),state=>{state.history[2][1]='a'.repeat(64);},state=>{state.fingerprint=EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT;},state=>{state.attestationRole=false;}]){
    const f=setup();useAttestationProfile(f);change(f.state);
    try{await assert.rejects(f.writer.initialize(opts()),f.state.attestationRole===false?UnauthorizedScope:UnsupportedCapability);await assert.rejects(f.writer.inspect(context,opts()),IndexNotReady);assert.equal(f.state.queries.some(query=>/^INSERT|^UPDATE/.test(query.text)),false);}finally{await f.writer.close();await f.resource.close();}
  }
});
test('old ordinary profile refuses new attestation entry points before extra SQL or receipt access',async()=>{
  const f=setup();await f.writer.initialize(opts());const before=f.state.queries.length;
  try{await assert.rejects(f.writer.attestation_snapshot(context,opts()),UnsupportedCapability);await assert.rejects(f.writer.attest_prepared({}, {},opts()),UnsupportedCapability);assert.equal(f.state.queries.length,before);}finally{await f.writer.close();await f.resource.close();}
});
test('attestation snapshot retains original six fields and selects only current exact tuple',async()=>{
  const f=await attestationSetup();
  try{
    const snapshot=await f.writer.attestation_snapshot(context,opts());assert.deepEqual(Object.keys(snapshot).sort(),['attestation','preparation']);assert.equal(snapshot.attestation,null);assert.equal(snapshot.preparation.backend_epoch,1);assert.equal(Object.keys(snapshot.preparation).length,6);
    f.state.tables.preparation_attestations=[{...context,tenant_id:scope.tenant_id,backend_epoch:99,instance_id:'instance-fixture'}];
    assert.equal((await f.writer.attestation_snapshot(context,opts())).attestation,null);
    const query=f.state.queries.findLast(query=>query.text.includes('FROM cragkit_qdrant.preparation_attestations'));
    assert(query.text.includes('backend_epoch=$5 AND owner_token=$6::uuid AND instance_id=$7'));assert(query.text.includes('LIMIT 2'));assert.equal(/ORDER BY|max\(/i.test(query.text),false);
    await assert.rejects(f.writer.attestation_snapshot({...context,owner_token:'00000000-0000-4000-8000-000000000003'},opts()),ProviderUnavailable);
  }finally{await f.close();}
});
test('private attestation requires original receipt, verifier, writer and active helper scope before SQL',async()=>{
  const f=await attestationSetup();
  try{
    let before=f.state.queries.length;await assert.rejects(f.writer.attest_prepared(f.receipt,f.verifier,opts()),InvalidRequest);assert.equal(f.state.queries.length,before);
    await f.run(async options=>{before=f.state.queries.length;await assert.rejects(f.writer.attest_prepared({...f.receipt},f.verifier,options),InvalidRequest);assert.equal(f.state.queries.length,before);});
    assert.equal(f.state.tables.preparation_attestations,undefined);
  }finally{await f.close();}
});
test('actual issuer-bound ordinary receipt appends exact current attestation and same-key retry preserves old preparation',async()=>{
  const f=await attestationSetup();
  try{
    const calls=f.state.httpCalls;
    const result=await f.run(options=>f.writer.attest_prepared(f.receipt,f.verifier,options));
    assert.deepEqual(Object.keys(result).sort(),['attestation','intent']);assert.equal(result.intent.state,'prepared');assert.equal(Object.keys(result.attestation).length,14);assert.equal(result.attestation.backend_epoch,2);assert.equal(result.attestation.verification_id,f.binding.dispatch_id);assert.equal(result.attestation.credential_generation,'credential-2');
    const retried=await f.run(options=>f.writer.attest_prepared(f.receipt,f.verifier,options));assert.deepEqual(retried,result);assert.equal(f.state.tables.preparation_attestations.length,1);assert.deepEqual(f.state.tables.preparations[0],f.original);assert.equal(f.state.httpCalls,calls);
    f.state.tables.preparation_attestations[0].readback_sha256='c'.repeat(64);
    await assert.rejects(f.run(options=>f.writer.attest_prepared(f.receipt,f.verifier,options)),IntegrityViolation);
  }finally{await f.close();}
});
test('actual COMMIT acknowledgement loss confirms one exact tuple without HTTP or insertion replay',async()=>{
  for(const absent of [false,true]){
    const f=await attestationSetup();
    try{
      f.state.attestationCommitLost=true;if(absent)f.state.onAttestationLost=()=>{f.state.tables.preparation_attestations=[];};
      const before=f.state.queries.length,calls=f.state.httpCalls;
      const result=await f.run(options=>f.writer.attest_prepared(f.receipt,f.verifier,options));assert.equal(result.attestation.backend_epoch,2);
      const inserts=f.state.queries.slice(before).filter(query=>query.text.startsWith('INSERT INTO cragkit_qdrant.preparation_attestations'));
      assert.equal(inserts.length,absent?2:1);assert.equal(f.state.tables.preparation_attestations.length,1);assert.equal(f.state.httpCalls,calls);assert(f.state.clients.some(client=>client.releases.includes(true)));
    }finally{await f.close();}
  }
});
test('attestation body operational failure is not an unknown COMMIT and never retries insertion',async()=>{
  const f=await attestationSetup();
  try{f.state.attestationBodyError=new ProviderUnavailable();const before=f.state.queries.length;await assert.rejects(f.run(options=>f.writer.attest_prepared(f.receipt,f.verifier,options)),ProviderUnavailable);assert.equal(f.state.queries.slice(before).filter(query=>query.text.startsWith('INSERT INTO cragkit_qdrant.preparation_attestations')).length,1);assert.deepEqual(f.state.tables.preparations[0],f.original);}finally{await f.close();}
});
test('changed security or pointer persists terminal fence outcome without publishing or attesting',async()=>{
  for(const outcome of ['denied','conflict']){
    const f=await attestationSetup();
    try{
      if(outcome==='denied')Object.assign(f.state.tables.documents[0],{authorization_revision:'auth-2',mutation_epoch:2,tombstoned:true});else f.state.tables.documents[0].active_generation_id='other-generation';
      const prior=f.state.tables.documents[0].active_generation_id;
      const result=await f.run(options=>f.writer.attest_prepared(f.receipt,f.verifier,options));assert.equal(result.intent.state,outcome);assert.equal(result.attestation,null);assert.equal(f.state.tables.documents[0].active_generation_id,prior);assert.deepEqual(f.state.tables.preparations[0],f.original);
    }finally{await f.close();}
  }
});
test('publication uses current exact attestation, rejects missing/contradictory tuples and preserves original preparation',async()=>{
  for(const mode of ['valid','missing','malformed','decoy']){
    const f=await attestationSetup();
    try{
      await f.run(options=>f.writer.attest_prepared(f.receipt,f.verifier,options));
      if(mode==='missing')f.state.tables.preparation_attestations=[];
      if(mode==='malformed')f.state.tables.preparation_attestations[0].manifest_sha256='a'.repeat(64);
      if(mode==='decoy')f.state.tables.preparation_attestations[0].backend_epoch=99;
      const before=f.state.tables.documents[0].active_generation_id;
      if(mode==='valid'){assert.equal((await f.writer.publish(context,opts())).state,'published');assert.equal(f.state.tables.documents[0].active_generation_id,f.state.tables.generations[0].generation_id);}
      else{await assert.rejects(f.writer.publish(context,opts()),mode==='malformed'?IntegrityViolation:ProviderUnavailable);assert.equal(f.state.tables.documents[0].active_generation_id,before);}
      assert.deepEqual(f.state.tables.preparations[0],f.original);
    }finally{await f.close();}
  }
});

test('supervisor recovery accepts exact ordinary and attestation catalogs without attestation privilege expansion',async()=>{
  for(const attestation of [false,true]){
    const f=setup();if(attestation)useAttestationProfile(f);
    const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/recovery-fixture','instance-fixture',config);
    const local={instance_id:'instance-fixture',backend_namespace:config.backend_namespace,storage_identity:'storage-fixture',supervisor_id:'supervisor-fixture',epoch:1,credential_generation:'credential-1',recovery:null,sealed:false,alive:true};
    supervisor.control_binding=()=>({...local});supervisor.control_session=async body=>body({block_ordinary(){}});
    const verifier=new QdrantReconciliationVerifier(f.writer,supervisor),recovery=new PostgresQdrantRecovery(f.resource,config,supervisor,verifier);
    try{await recovery.initialize(opts());assert(f.state.queries.some(query=>query.text===(attestation?AUTHORITY_ATTESTATION_CATALOG_SQL:AUTHORITY_PUBLICATION_CATALOG_SQL)));assert.equal(RECOVERY_ROLE_SQL.includes("'preparation_attestations'"),false);f.state.recoveryRole=false;await assert.rejects(recovery.initialize(opts()),UnauthorizedScope);}finally{await recovery.close();await verifier.close();await f.writer.close();await f.resource.close();}
  }
});
test('attestation fresh-lease grant drift and invalid deadline/cancellation stop before insertion',async()=>{
  const f=await attestationSetup();
  try{
    f.state.attestationRole=false;await assert.rejects(f.writer.attestation_snapshot(context,opts()),UnauthorizedScope);f.state.attestationRole=true;
    for(const options of [{deadline:now()-1},{...opts(),signal:AbortSignal.abort()}]){
      const before=f.state.queries.length;await assert.rejects(f.writer.attest_prepared(f.receipt,f.verifier,options),error=>['DeadlineExceeded','AbortError'].includes(error.name));assert.equal(f.state.queries.length,before);
    }
    assert.equal(f.state.tables.preparation_attestations,undefined);
  }finally{await f.close();}
});

test('stored stage fence columns cannot contradict immutable intent bytes before attestation or final publication',async()=>{
  for(const method of ['attestation_snapshot','publish'])for(const field of ['expected_active_generation_id','expected_authorization_revision','expected_mutation_epoch']){
    const f=await attestationSetup();
    try{
      f.state.tables.publication_intents[0][field]=field==='expected_mutation_epoch'?2:'forged';
      const pointer=f.state.tables.documents[0].active_generation_id;
      await assert.rejects(f.writer[method](context,opts()),IntegrityViolation);assert.equal(f.state.tables.documents[0].active_generation_id,pointer);assert.equal(f.state.tables.publication_intents[0].state,'prepared');
    }finally{await f.close();}
  }
});


test('snapshot rejects an original preparation from a future epoch without an attestation',async()=>{
  const f=await attestationSetup();
  try{
    f.state.tables.preparations[0].backend_epoch=3;
    await assert.rejects(f.writer.attestation_snapshot(context,opts()),IntegrityViolation);
    assert.equal(f.state.tables.preparation_attestations,undefined);
  }finally{await f.close();}
});

test('repair preflight requires exact attestation profile before checkout',async()=>{
  const f=setup();
  try{
    await f.writer.initialize(opts());const before=f.state.clients.length;
    await assert.rejects(f.writer.preflight_repair(context,opts()),UnsupportedCapability);
    assert.equal(f.state.clients.length,before);
  }finally{await f.writer.close();await f.resource.close();}
});

test('repair preflight inspects blocked uncertainty without ownership or state changes and locks in order',async()=>{
  const f=setup();useAttestationProfile(f);
  try{
    await f.writer.initialize(opts());await f.writer.stage(prepare_stage(input()),scope,stageOpts());
    await f.writer.acquire_owner(context,opts());await f.writer.reserve_dispatch(context,dispatchRequest,opts());
    blocked(f);const before=clone(f.state.tables),start=f.state.queries.length;
    const result=await f.writer.preflight_repair(context,opts());
    assert.deepEqual(Object.keys(result).sort(),['backend','intent','owner','pending']);
    assert.equal(result.backend.state,'recovery_blocked');assert.equal(result.pending,true);
    assert.equal(result.owner.owner_token,token);assert.equal(result.intent.state,'writing');
    assert.deepEqual(f.state.tables,before);
    const sql=f.state.queries.slice(start).map(query=>query.text);
    const backend=sql.findIndex(text=>text.includes('FROM cragkit_qdrant.backend_instances')&&text.endsWith('FOR SHARE'));
    const owner=sql.findIndex(text=>text.includes('FROM cragkit_qdrant.document_owners')&&text.includes('FOR UPDATE'));
    const document=sql.findIndex(text=>text.includes('FROM cragkit_qdrant.documents')&&text.includes('FOR UPDATE'));
    assert(backend>=0&&owner>backend&&document>owner);
  }finally{await f.writer.close();await f.resource.close();}
});

test('repair preflight commits original fence outcomes while blocked and preserves terminal history',async()=>{
  for(const failure of ['denied','conflict']){
    const f=setup();useAttestationProfile(f);
    try{
      await f.writer.initialize(opts());await f.writer.stage(prepare_stage(input()),scope,stageOpts());
      f.state.tables.backend_instances[0].state='recovery_blocked';f.state.tables.backend_instances[0].recovery_id='recovery-fixture';
      if(failure==='denied')f.state.tables.documents[0].tombstoned=true;
      else f.state.tables.documents[0].active_generation_id='winner';
      const result=await f.writer.preflight_repair(context,opts());assert.equal(result.intent.state,failure);
      assert.equal(result.owner,null);assert.equal(f.state.tables.publication_intents[0].state,failure);
      f.state.tables.documents[0].active_generation_id='later';
      assert.equal((await f.writer.preflight_repair(context,opts())).intent.state,failure);
    }finally{await f.writer.close();await f.resource.close();}
  }
});

test('repair preflight denies wrong scope and malformed immutable graph without allocating owner',async()=>{
  const f=setup();useAttestationProfile(f);
  try{
    await f.writer.initialize(opts());await f.writer.stage(prepare_stage(input()),scope,stageOpts());
    await assert.rejects(f.writer.preflight_repair({...context,scope:{...scope,authorization_revision:'wrong'}},opts()),UnauthorizedScope);
    f.state.tables.document_revisions[0].canonical_utf8=Buffer.from('corrupt');
    await assert.rejects(f.writer.preflight_repair(context,opts()),IntegrityViolation);
    assert.equal(f.state.tables.document_owners,undefined);
  }finally{await f.writer.close();await f.resource.close();}
});
