import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PoolResource,parse_pool_config,bounded,now} from '../dist/postgres-pool.js';
import {PostgresQdrantWriter,WRITER_ROLE_SQL,publication_projection_data} from '../dist/qdrant-writer.js';
import {ManagedQdrantSupervisor} from '../dist/qdrant-supervisor.js';
import {QdrantPublicationVerifier,publication_receipt_data,attestation_receipt_data,
  publication_verifier_controller} from '../dist/qdrant-publication-verification.js';
import {publication_finalization} from '../dist/qdrant-publication-worker.js';
import {VerificationBudget} from '../dist/qdrant-reconciliation.js';
import {AUTHORITY_HISTORY_SQL,AUTHORITY_PUBLICATION_HISTORY,AUTHORITY_PUBLICATION_CATALOG_SQL,
  AUTHORITY_FINGERPRINT_SQL,EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT} from '../dist/qdrant-authority.js';
import {encode_dense_replay,encode_sparse_replay} from '../dist/qdrant-manifest.js';
import {InvalidRequest,IntegrityViolation,ProviderUnavailable,UnauthorizedScope,UnsupportedCapability,
  DeadlineExceeded} from '../dist/errors.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_publication.json',import.meta.url),'utf8'));
const config={...fixture.physical,dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse};
const context={scope:{tenant_id:'tenant-a',principal_id:'reader-a',grant_ids:['grant-a'],authorization_revision:'auth-1'},
  collection:'docs',document_id:'doc-1',intent_id:'intent-2',owner_token:'00000000-0000-4000-8000-000000000001'};
const ordinary={instance_id:'instance-fixture',storage_identity:'storage-fixture',supervisor_id:'supervisor-fixture',
  epoch:1,credential_generation:'credential-1',intent_id:context.intent_id,owner_token:context.owner_token,dispatch_id:'readback-1'};
const options=()=>({deadline:now()+5});
const clone=value=>JSON.parse(JSON.stringify(value));

/** Real boundary validators over a deterministic driver/HTTP double; not native proof. */
async function setup(){
  const common={tenant_id:'tenant-a',collection:'docs',document_id:'doc-1'};
  const revision=fixture.source_revision,generation=fixture.intent.generation_id;
  const members=fixture.members.map(member=>({...common,revision_id:revision.revision_id,generation_id:generation,
    chunk_id:member.chunk_id,point_id:member.point_id,start_byte:member.start_byte,end_byte:member.end_byte,
    source_sha256:revision.source_sha256,text_sha256:member.text_sha256,excerpt_utf8:Buffer.from(member.excerpt_utf8.value)}));
  const tables={
    backend_instances:[{instance_id:ordinary.instance_id,backend_namespace:config.backend_namespace,
      storage_identity:ordinary.storage_identity,supervisor_id:ordinary.supervisor_id,epoch:1,state:'open',recovery_id:null}],
    document_owners:[{...common,instance_id:ordinary.instance_id,intent_id:context.intent_id,owner_token:context.owner_token,backend_epoch:1}],
    documents:[{...common,...clone(fixture.document)}],
    publication_intents:[{...common,intent_id:context.intent_id,instance_id:ordinary.instance_id,action:'stage',state:'writing',
      payload_bytes:Buffer.from(JSON.stringify(fixture.canonical_tuples.stage_intent)),payload_sha256:fixture.intent.payload_sha256,
      manifest_bytes:Buffer.from(JSON.stringify(fixture.canonical_tuples.manifest)),manifest_sha256:fixture.intent.manifest_sha256,
      revision_id:revision.revision_id,generation_id:generation,expected_active_generation_id:'gen-1',
      expected_authorization_revision:'auth-1',expected_mutation_epoch:1,authority_committed:false,replica_complete:false,purge_complete:false}],
    document_revisions:[{...common,revision_id:revision.revision_id,canonical_utf8:Buffer.from(revision.canonical_utf8.value),
      source_sha256:revision.source_sha256,source_locator:revision.source_locator,parser_id:revision.parser_id}],
    generations:[{...common,...fixture.physical,revision_id:revision.revision_id,generation_id:generation,
      chunker_profile:fixture.intent.chunker_profile,dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse,expected_member_count:2}],
    members,
    point_claims:members.map((member,i)=>({...member,...fixture.physical,instance_id:ordinary.instance_id,
      dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse,
      dense_input_sha256:fixture.members[i].dense.vector_sha256,sparse_input_sha256:fixture.members[i].sparse.vector_sha256})),
    vector_replays:fixture.members.map(member=>{
      const dense=encode_dense_replay(Array.from({length:1536},(_,i)=>i===member.dense.basis_index?1:0),config.dense_profile);
      const sparse=encode_sparse_replay(member.sparse.indices,member.sparse.values,config.sparse_profile);
      return {...common,...fixture.physical,revision_id:revision.revision_id,generation_id:generation,chunk_id:member.chunk_id,
        point_id:member.point_id,dense_blob:Buffer.from(dense.blob),dense_blob_sha256:dense.blob_sha256,
        sparse_blob:Buffer.from(sparse.blob),sparse_blob_sha256:sparse.blob_sha256};
    }),
    dispatch_journal:[],
  };
  const state={tables,clients:[],queries:[],requests:[],closed:0,closeFail:false,closeError:null,mode:null,wait:null,afterHttp:null,
    sqlWait:null,sqlEntered:null,
    attempt:Object.freeze({}),binding:{...ordinary},bindingCalls:0,poolClosed:0};
  const pool={async end(){state.poolClosed++;},async connect(){
    const client={status:'I',released:false,destroyed:false,getTransactionStatus(){return this.status;},
      release(destroy=false){this.released=true;this.destroyed=destroy;},async query(query){
      const sql=query.text,p=query.values??[];state.queries.push(sql);
      if(sql.startsWith('BEGIN')){this.status='T';return {rows:[]};}
      if(sql==='COMMIT'||sql==='ROLLBACK'){this.status='I';return {rows:[]};}
      if(sql.startsWith('SET ')||sql.startsWith('SELECT set_config'))return {rows:[]};
      if(sql===WRITER_ROLE_SQL){
        if(state.sqlWait){state.sqlEntered?.();await state.sqlWait;}
        return {rows:[[true]]};
      }
      if(sql===AUTHORITY_PUBLICATION_CATALOG_SQL)return {rows:[[true]]};
      if(sql===AUTHORITY_HISTORY_SQL)return {rows:AUTHORITY_PUBLICATION_HISTORY.map(row=>[...row])};
      if(sql===AUTHORITY_FINGERPRINT_SQL)return {rows:[[EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT]]};
      const match=/^SELECT (.+?) FROM cragkit_qdrant\.(\w+) WHERE /.exec(sql);
      if(!match)throw Error('Unexpected read-only SQL');
      const [,columns,table]=match;
      let rows=tables[table].filter(row=>table==='backend_instances'?row.instance_id===p[0]:
        row.tenant_id===p[0]&&row.collection===p[1]&&row.document_id===p[2]);
      for(const field of ['intent_id','revision_id','generation_id','chunk_id']){
        const parameter=new RegExp(' AND '+field+'=\\$(\\d+)').exec(sql);
        if(parameter)rows=rows.filter(row=>row[field]===p[Number(parameter[1])-1]);
      }
      if(sql.includes("state<>'settled'"))rows=rows.filter(row=>row.state!=='settled');
      return {rows:rows.map(row=>columns.split(',').map(key=>row[key.replace('::text','')]))};
    }};
    state.clients.push(client);return client;
  }};
  const resource=new PoolResource(parse_pool_config({host:'host.invalid',dbname:'fixture',user:'writer',
    sslrootcert:'/fake/ca',passfile:'/fake/pass',release_timeout:.05,close_timeout:.1}),{pool});
  const writer=new PostgresQdrantWriter(resource,config,ordinary.instance_id);
  await writer.initialize(options());
  const projection=await writer.project_publication(context,ordinary,options());
  const expected=publication_projection_data(projection,writer);
  const records=expected.points.map(point=>({id:point.point_id,payload:clone(point.payload),vector:{dense:[...point.dense.values],
    sparse:{indices:[...point.sparse.indices],values:[...point.sparse.values]}}}));
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work',ordinary.instance_id,config);
  supervisor.attempt_binding=attempt=>{
    state.bindingCalls++;
    if(attempt!==state.attempt)throw new InvalidRequest();
    return {...state.binding};
  };
  supervisor.transport_for=attempt=>{
    if(attempt!==state.attempt)throw new InvalidRequest();
    return {async close(){state.closed++;if(state.closeError)throw state.closeError;if(state.closeFail)throw Error('private cleanup');},async request(method,path,request){
      assert.equal(state.clients.every(client=>client.released&&(client.destroyed||client.status==='I')),true,
        'HTTP owns no live SQL lease; destroyed historical clients are not reused');
      assert.deepEqual(Object.keys(request).sort(),['body','deadline','max_response_bytes','signal'],
        'HTTP receives only its exact request options');
      if(state.wait)await bounded(state.wait,{deadline:request.deadline,signal:request.signal});
      const body=JSON.parse(Buffer.from(request.body));
      state.requests.push({method,path,body,cap:request.max_response_bytes});
      let observed=clone(records);
      if(state.mode==='missing')observed.pop();
      if(state.mode==='dense')observed[0].vector.dense=observed[0].vector.dense.map(value=>-value);
      if(state.mode==='sparse')observed[0].vector.sparse.values[0]+=1;
      if(state.mode==='payload')observed[0].payload.tag='stale';
      if(state.mode==='extra'&&path.endsWith('/scroll'))observed.push({...clone(observed[0]),id:'ffffffff-ffff-5fff-8fff-ffffffffffff'});
      if(state.afterHttp){const change=state.afterHttp;state.afterHttp=null;change();}
      const response={status:'ok',result:path.endsWith('/scroll')?{points:observed,next_page_offset:null}:
        observed.filter(point=>body.ids.includes(point.id))};
      const encoded=Buffer.from(JSON.stringify(response));
      const bytes=state.malformedBudget?Buffer.concat([Buffer.from('!'),Buffer.alloc(1048575,32)]):
        state.paddingBytes?Buffer.concat([encoded,Buffer.alloc(Math.max(0,state.paddingBytes-encoded.length),32)]):encoded;
      if(bytes.length>request.max_response_bytes)throw new ProviderUnavailable();
      return Object.freeze(Array.from(bytes));
    }};
  };
  const verifier=new QdrantPublicationVerifier(writer,supervisor);
  return {state,writer,supervisor,verifier,resource,async close(){await verifier.close();await writer.close();await resource.close();await supervisor.close();}};
}

test('ordinary full native-byte readback issues only immutable issuer-bound provenance',async()=>{
  const f=await setup();
  try{
    const receipt=await f.verifier.verify(f.state.attempt,context,options());
    const data=publication_receipt_data(receipt,f.verifier);
    assert.deepEqual(JSON.parse(JSON.stringify(receipt)),{});
    assert.ok(Object.isFrozen(data.witness));
    assert.equal(data.witness.length,21);
    assert.equal(data.sha256,data.readback_sha256);
    assert.equal(data.point_ids.length,2);
    assert.equal('canonical_text'in data,false);
    assert.equal(f.state.requests.length,2);
    assert.equal(f.state.closed,1);
    assert.equal(JSON.stringify(f.state.requests[1].body.filter).includes('has_id'),false);
    assert.throws(()=>publication_receipt_data({...receipt},f.verifier),InvalidRequest);
    const foreign=new QdrantPublicationVerifier(f.writer,f.supervisor);
    assert.throws(()=>publication_receipt_data(receipt,foreign),InvalidRequest);
    await foreign.close();
    f.state.binding.credential_generation='changed';
    assert.throws(()=>publication_receipt_data(receipt,f.verifier),UnsupportedCapability);
  }finally{await f.close();}
});

test('attestation consumes only the original receipt and writer inside native finalization',async()=>{
  const f=await setup(),lease=options();
  const foreignWriter=new PostgresQdrantWriter(f.resource,config,ordinary.instance_id);
  const foreignVerifier=new QdrantPublicationVerifier(f.writer,f.supervisor);
  try{
    const receipt=await f.verifier.verify(f.state.attempt,context,lease);
    assert.equal(publication_verifier_controller(f.verifier,f.writer),f.supervisor);
    assert.throws(()=>publication_verifier_controller(f.verifier,foreignWriter),InvalidRequest);
    await assert.rejects(attestation_receipt_data(receipt,f.verifier,f.writer,lease),InvalidRequest);
    await f.supervisor.control_session(async()=>{
      await assert.rejects(attestation_receipt_data(receipt,f.verifier,f.writer,lease),InvalidRequest);
    });
    await publication_finalization(f.supervisor,f.state.attempt,async()=>{
      assert.equal(await attestation_receipt_data(receipt,f.verifier,f.writer,lease),publication_receipt_data(receipt,f.verifier));
      await assert.rejects(attestation_receipt_data({...receipt},f.verifier,f.writer,lease),InvalidRequest);
      await assert.rejects(attestation_receipt_data(receipt,foreignVerifier,f.writer,lease),InvalidRequest);
      await assert.rejects(attestation_receipt_data(receipt,f.verifier,foreignWriter,lease),InvalidRequest);
      f.state.binding.credential_generation='retired';
      await assert.rejects(attestation_receipt_data(receipt,f.verifier,f.writer,lease),UnsupportedCapability);
    },lease);
  }finally{await foreignVerifier.close();await foreignWriter.close();await f.close();}
});

test('an unawaited receipt validation cannot outlive its native finalization context',async()=>{
  const f=await setup(),lease=options();let pending;
  try{
    const receipt=await f.verifier.verify(f.state.attempt,context,lease);
    await publication_finalization(f.supervisor,f.state.attempt,async()=>{
      pending=attestation_receipt_data(receipt,f.verifier,f.writer,lease);
      pending.catch(()=>{});
    },lease);
    await assert.rejects(pending,InvalidRequest);
  }finally{await f.close();}
});

test('forged, recovery and mismatched ordinary attempts fail before SQL and HTTP',async()=>{
  const f=await setup();
  try{
    const before=f.state.queries.length;
    await assert.rejects(f.verifier.verify({},context,options()),InvalidRequest);
    f.state.binding.recovery_id='recovery-1';
    await assert.rejects(f.verifier.verify(f.state.attempt,context,options()),UnsupportedCapability);
    delete f.state.binding.recovery_id;
    f.state.binding.intent_id='foreign';
    await assert.rejects(f.verifier.verify(f.state.attempt,context,options()),UnsupportedCapability);
    assert.equal(f.state.queries.length,before);
    assert.equal(f.state.requests.length,0);
  }finally{await f.close();}
});

test('pending predecessor work and stale authority refuse before opening HTTP',async()=>{
  for(const [change,error] of [
    [f=>f.state.tables.dispatch_journal.push({tenant_id:'tenant-a',collection:'docs',document_id:'doc-1',intent_id:'older',state:'unknown'}),ProviderUnavailable],
    [f=>{f.state.tables.documents[0].tombstoned=true;},UnauthorizedScope],
    [f=>{f.state.tables.document_owners[0].backend_epoch=2;},ProviderUnavailable],
  ]){
    const f=await setup();
    try{
      change(f);
      await assert.rejects(f.verifier.verify(f.state.attempt,context,options()),error);
      assert.equal(f.state.requests.length,0);
      assert.equal(f.state.closed,0);
    }finally{await f.close();}
  }
});

test('complete set, both named vectors and current payload are required',async()=>{
  for(const mode of ['missing','dense','sparse','payload','extra']){
    const f=await setup();
    try{
      f.state.mode=mode;
      await assert.rejects(f.verifier.verify(f.state.attempt,context,options()),IntegrityViolation,mode);
      assert.equal(f.state.closed,1);
    }finally{await f.close();}
  }
});

test('late authority or attempt changes cannot mint a receipt',async()=>{
  for(const [change,error] of [
    [f=>{f.state.tables.documents[0].authorization_revision='auth-2';},UnauthorizedScope],
    [f=>{f.state.tables.documents[0].tag='changed';},UnauthorizedScope],
    [f=>{f.state.binding.credential_generation='new-key';},UnsupportedCapability],
  ]){
    const f=await setup();
    try{
      f.state.afterHttp=()=>change(f);
      await assert.rejects(f.verifier.verify(f.state.attempt,context,options()),error);
      assert.equal(f.state.closed,1);
    }finally{await f.close();}
  }
});

test('deadline, cancellation, no-queue admission and borrowed cleanup remain bounded',async()=>{
  const f=await setup();
  try{
    await assert.rejects(f.verifier.verify(f.state.attempt,context,{deadline:now()-1}),DeadlineExceeded);
    f.state.wait=new Promise(()=>{});
    const abort=new AbortController();
    const pending=f.verifier.verify(f.state.attempt,context,{...options(),signal:abort.signal});
    await assert.rejects(f.verifier.verify(f.state.attempt,context,options()),ProviderUnavailable);
    abort.abort();
    await assert.rejects(pending,error=>error.name==='AbortError');
    f.state.wait=null;
    const receipt=await f.verifier.verify(f.state.attempt,context,options());
    assert.ok(publication_receipt_data(receipt,f.verifier));
    await f.verifier.close();
    assert.equal(f.state.poolClosed,0);
    await assert.rejects(f.verifier.verify(f.state.attempt,context,options()),ProviderUnavailable);
  }finally{await f.close();}
});

test('failed handle drain remains operational and exact constructor types are enforced',async()=>{
  const f=await setup();
  try{
    f.state.closeFail=true;
    await assert.rejects(f.verifier.verify(f.state.attempt,context,options()),ProviderUnavailable);
    class Foreign extends ManagedQdrantSupervisor {}
    assert.throws(()=>new QdrantPublicationVerifier(f.writer,new Foreign('/owned/qdrant','/private/foreign','foreign',config)),InvalidRequest);
    assert.throws(()=>new QdrantPublicationVerifier(new Proxy(f.writer,{}),f.supervisor),InvalidRequest);
  }finally{f.state.closeFail=false;await f.close();}
});

test('a cancelled SQL checkout is destroyed and a later healthy checkout can verify',async()=>{
  const f=await setup();
  let release;
  try{
    let entered;
    const paused=new Promise(resolve=>{entered=resolve;});
    f.state.sqlEntered=entered;
    f.state.sqlWait=new Promise(resolve=>{release=resolve;});
    const abort=new AbortController();
    const pending=f.verifier.verify(f.state.attempt,context,{...options(),signal:abort.signal});
    await paused;
    abort.abort();
    await assert.rejects(pending,error=>error.name==='AbortError');
    assert.ok(f.state.clients.some(client=>client.destroyed&&client.status==='T'));
    release();
    f.state.sqlWait=null;
    const receipt=await f.verifier.verify(f.state.attempt,context,options());
    assert.ok(publication_receipt_data(receipt,f.verifier));
    assert.equal(f.state.requests.length,2);
  }finally{release?.();await f.close();}
});

test('handle cleanup timeout is operational while native cleanup abort is preserved',async()=>{
  for(const [failure,expected] of [
    [new DeadlineExceeded(),error=>error instanceof ProviderUnavailable],
    [new DOMException('private abort','AbortError'),error=>error.name==='AbortError'],
  ]){
    const f=await setup();
    try{
      f.state.closeError=failure;
      await assert.rejects(f.verifier.verify(f.state.attempt,context,options()),expected);
      assert.equal(f.state.closed,2,'failed normal close is followed by bounded cleanup');
    }finally{f.state.closeError=null;await f.close();}
  }
});

test('F1 shares native verification bytes across passes and sends only the remaining cap',async()=>{
  const fixture=await setup();
  try{
    const {state,verifier}=fixture,budget=new VerificationBudget();
    state.paddingBytes=1048576-1000;
    for(let pass=0;pass<4;pass++){
      const receipt=await verifier.verify(state.attempt,context,options(),budget);
      assert.ok(publication_receipt_data(receipt,verifier).projection);
    }
    assert.equal(budget.remaining_bytes,8000);
    assert.equal(state.requests.length,8);
    await assert.rejects(verifier.verify(state.attempt,context,options(),budget),ProviderUnavailable);
    assert.equal(state.requests.at(-1).cap,8000);
    assert.equal(budget.remaining_bytes,8000);
    state.paddingBytes=0;
    const receipt=await verifier.verify(state.attempt,context,options());
    assert.ok(publication_receipt_data(receipt,verifier).readback_sha256);
    assert.equal(budget.remaining_bytes,8000);
  }finally{await fixture.close();}
});

test('F1 malformed replies consume shared bytes before parsing and exhaustion prevents another HTTP request',async()=>{
  const fixture=await setup();
  try{
    const {state,verifier}=fixture,budget=new VerificationBudget();
    state.malformedBudget=true;
    for(let pass=0;pass<8;pass++){
      await assert.rejects(verifier.verify(state.attempt,context,options(),budget),IntegrityViolation);
      assert.equal(budget.remaining_bytes,8388608-(pass+1)*1048576);
    }
    assert.equal(state.requests.length,8);
    await assert.rejects(verifier.verify(state.attempt,context,options(),budget),ProviderUnavailable);
    assert.equal(state.requests.length,8);
    assert.equal(budget.remaining_bytes,0);
  }finally{await fixture.close();}
});

test('F1 forged or foreign byte budgets fail before controller binding, source lease or HTTP',async()=>{
  const fixture=await setup();
  try{
    const {state,verifier}=fixture;
    class ForeignBudget extends VerificationBudget{}
    const beforeClients=state.clients.length,beforeBindings=state.bindingCalls;
    for(const budget of [{remaining_bytes:8388608},Object.create(VerificationBudget.prototype),new ForeignBudget(),null]){
      await assert.rejects(verifier.verify(state.attempt,context,options(),budget),InvalidRequest);
    }
    assert.equal(state.clients.length,beforeClients);
    assert.equal(state.bindingCalls,beforeBindings);
    assert.equal(state.requests.length,0);
  }finally{await fixture.close();}
});
