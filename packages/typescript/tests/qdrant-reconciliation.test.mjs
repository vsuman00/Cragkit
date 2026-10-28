import test,{mock} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PoolResource,parse_pool_config,bounded,now} from '../dist/postgres-pool.js';
import {PostgresQdrantWriter,projection_data,WRITER_ROLE_SQL} from '../dist/qdrant-writer.js';
import {ManagedQdrantSupervisor} from '../dist/qdrant-supervisor.js';
import {QdrantReconciliationVerifier,receipt_data,verifier_authority,VerificationBudget,verification_budget,inspect_missing_readback,verify_projection_readback} from '../dist/qdrant-reconciliation.js';
import {AUTHORITY_HISTORY_SQL,AUTHORITY_PUBLICATION_HISTORY,AUTHORITY_PUBLICATION_CATALOG_SQL,
  AUTHORITY_FINGERPRINT_SQL,EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT} from '../dist/qdrant-authority.js';
import {encode_dense_replay,encode_sparse_replay} from '../dist/qdrant-manifest.js';
import {encode_manifest} from '../dist/qdrant-manifest.js';
import {point_id} from '../dist/qdrant-contract.js';
import {createHash} from 'node:crypto';
import {InvalidRequest,IntegrityViolation,UnsupportedCapability,ProviderUnavailable,UnauthorizedScope,DeadlineExceeded} from '../dist/errors.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_publication.json',import.meta.url),'utf8'));
const baseFixture=fixture;
const config={...fixture.physical,dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse};
const scope={tenant_id:'tenant-a',principal_id:'reader-a',grant_ids:['grant-a'],authorization_revision:'auth-1'};
const context={scope,collection:'docs',document_id:'doc-1',intent_id:'intent-2',owner_token:'00000000-0000-4000-8000-000000000001'};
const physical=Object.freeze({instance_id:'instance-fixture',storage_identity:'storage-fixture',supervisor_id:'supervisor-fixture',
  recovery_id:'recovery-1',old_epoch:1,new_epoch:2,credential_generation:'credential-2'});
const options=()=>({deadline:now()+5});
const jsonBytes=value=>Object.freeze(Array.from(Buffer.from(JSON.stringify(value))));
const clone=value=>JSON.parse(JSON.stringify(value));

/** Read-only fake driver and host method doubles test logic, not native proof origin. */
async function setup(tombstoned=false,memberCount=2){
  const fixture=clone(baseFixture);
  if(memberCount===64){
    const original=fixture.members[0];
    fixture.members=Array.from({length:64},(_,index)=>{
      const member=clone(original);member.chunk_id='chunk-'+String(index).padStart(3,'0');
      member.identity_tuple[9]=member.chunk_id;member.point_id=point_id(member.identity_tuple);return member;
    });
    const record={...fixture.physical,tenant_id:'tenant-a',collection:'docs',document_id:'doc-1',revision_id:fixture.source_revision.revision_id,
      generation_id:fixture.intent.generation_id,source_sha256:fixture.source_revision.source_sha256,source_bytes:fixture.source_revision.source_bytes,
      source_locator:fixture.source_revision.source_locator,parser_id:fixture.source_revision.parser_id,chunker_profile:fixture.intent.chunker_profile,
      dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse,members:fixture.members.map(member=>({
        chunk_id:member.chunk_id,point_id:member.point_id,start_byte:member.start_byte,end_byte:member.end_byte,text_sha256:member.text_sha256,
        dense_input_sha256:member.dense.vector_sha256,sparse_input_sha256:member.sparse.vector_sha256}))};
    const encoded=encode_manifest(record,fixture.source_revision.canonical_utf8.value);
    fixture.canonical_tuples.manifest=encoded.value;fixture.intent.manifest_sha256=encoded.sha256;
    fixture.canonical_tuples.stage_intent[6]=encoded.sha256;
    fixture.intent.payload_sha256=createHash('sha256').update(JSON.stringify(fixture.canonical_tuples.stage_intent)).digest('hex');
  }
  const common={tenant_id:'tenant-a',collection:'docs',document_id:'doc-1'};
  const revision=fixture.source_revision,generation=fixture.intent.generation_id;
  const members=fixture.members.map(member=>({...common,revision_id:revision.revision_id,generation_id:generation,
    chunk_id:member.chunk_id,point_id:member.point_id,start_byte:member.start_byte,end_byte:member.end_byte,
    source_sha256:revision.source_sha256,text_sha256:member.text_sha256,excerpt_utf8:Buffer.from(member.excerpt_utf8.value)}));
  const tables={
    backend_instances:[{instance_id:'instance-fixture',backend_namespace:'fixture-local',storage_identity:physical.storage_identity,
      supervisor_id:physical.supervisor_id,epoch:2,state:'recovery_blocked',recovery_id:'recovery-1'}],
    document_owners:[{...common,instance_id:'instance-fixture',intent_id:'intent-2',owner_token:context.owner_token,backend_epoch:2}],
    documents:[{...common,active_generation_id:'gen-1',principal_ids:['reader-a'],grant_ids:['grant-a'],authorization_revision:'auth-1',
      mutation_epoch:1,language:'en',kind:'guide',tag:'reference',tombstoned}],
    publication_intents:[{...common,intent_id:'intent-2',instance_id:'instance-fixture',action:'stage',state:'writing',
      payload_bytes:Buffer.from(JSON.stringify(fixture.canonical_tuples.stage_intent)),payload_sha256:fixture.intent.payload_sha256,
      manifest_bytes:Buffer.from(JSON.stringify(fixture.canonical_tuples.manifest)),manifest_sha256:fixture.intent.manifest_sha256,
      revision_id:revision.revision_id,generation_id:generation,expected_active_generation_id:'gen-1',
      expected_authorization_revision:'auth-1',expected_mutation_epoch:1,authority_committed:false,replica_complete:false,purge_complete:false}],
    document_revisions:[{...common,revision_id:revision.revision_id,canonical_utf8:Buffer.from(revision.canonical_utf8.value),
      source_sha256:revision.source_sha256,source_locator:revision.source_locator,parser_id:revision.parser_id}],
    generations:[{...common,...fixture.physical,revision_id:revision.revision_id,generation_id:generation,
      chunker_profile:fixture.intent.chunker_profile,dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse,expected_member_count:memberCount}],
    members,
    point_claims:members.map((member,i)=>({...member,...fixture.physical,instance_id:'instance-fixture',dense_profile:fixture.profiles.dense,
      sparse_profile:fixture.profiles.sparse,dense_input_sha256:fixture.members[i].dense.vector_sha256,sparse_input_sha256:fixture.members[i].sparse.vector_sha256})),
    vector_replays:fixture.members.map(member=>{
      const values=Array.from({length:1536},(_,i)=>i===member.dense.basis_index?1:0);
      const dense=encode_dense_replay(values,config.dense_profile),sparse=encode_sparse_replay(member.sparse.indices,member.sparse.values,config.sparse_profile);
      return {...common,...fixture.physical,revision_id:revision.revision_id,generation_id:generation,chunk_id:member.chunk_id,
        point_id:member.point_id,dense_blob:Buffer.from(dense.blob),dense_blob_sha256:dense.blob_sha256,
        sparse_blob:Buffer.from(sparse.blob),sparse_blob_sha256:sparse.blob_sha256};
    }),
  };
  const state={clients:[],requests:[],tables,closeFail:false,closed:0,mode:null,wait:null,afterHttp:null,padBytes:0,currentProof:Object.freeze({})};
  const pool={async end(){throw Error('borrowed pool');},async connect(){
    const client={status:'I',getTransactionStatus(){return this.status;},release(){},async query(query){
      const sql=query.text,params=query.values??[];
      if(sql.startsWith('BEGIN')){this.status='T';return {rows:[]};}
      if(sql==='COMMIT'||sql==='ROLLBACK'){this.status='I';return {rows:[]};}
      if(sql.startsWith('SET ')||sql.startsWith('SELECT set_config'))return {rows:[]};
      if(sql===WRITER_ROLE_SQL||sql===AUTHORITY_PUBLICATION_CATALOG_SQL)return {rows:[[true]]};
      if(sql===AUTHORITY_HISTORY_SQL)return {rows:AUTHORITY_PUBLICATION_HISTORY.map(row=>[...row])};
      if(sql===AUTHORITY_FINGERPRINT_SQL)return {rows:[[EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT]]};
      const match=/^SELECT (.+?) FROM cragkit_qdrant\.(\w+) WHERE /.exec(sql);
      if(!match)throw Error('unexpected read-only SQL');
      const [,columns,table]=match;
      let rows=tables[table].filter(row=>table==='backend_instances'?row.instance_id===params[0]:
        row.tenant_id===params[0]&&row.collection===params[1]&&row.document_id===params[2]);
      for(const field of ['intent_id','revision_id','generation_id','chunk_id']){
        const parameter=new RegExp(' AND '+field+'=\\$(\\d+)').exec(sql);
        if(parameter)rows=rows.filter(row=>row[field]===params[Number(parameter[1])-1]);
      }
      return {rows:rows.map(row=>columns.split(',').map(key=>row[key.replace('::text','')]))};
    }};state.clients.push(client);return client;
  }};
  const resource=new PoolResource(parse_pool_config({host:'host.invalid',dbname:'fixture',user:'writer',sslrootcert:'/fake/ca',passfile:'/fake/pass',release_timeout:.05,close_timeout:.1}),{pool});
  const writer=new PostgresQdrantWriter(resource,config,'instance-fixture');await writer.initialize(options());
  const projection=await writer.project_stage(context,physical,options()),expected=projection_data(projection,writer);
  const records=expected.points.map(point=>({id:point.point_id,payload:clone(point.payload),vector:{dense:[...point.dense.values],
    sparse:{indices:[...point.sparse.indices],values:[...point.sparse.values]}}}));
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-fixture',config);
  const methods=[];
  methods.push(mock.method(supervisor,'recovery_binding',proof=>{if(proof!==state.currentProof)throw new UnsupportedCapability();return physical;}));
  methods.push(mock.method(supervisor,'issue_recovery_attempt',(proof,binding)=>{
    if(proof!==state.currentProof||binding.epoch!==2||binding.recovery_id!=='recovery-1')throw new UnsupportedCapability();return Object.freeze({});
  }));
  methods.push(mock.method(supervisor,'transport_for',()=>({async close(){state.closed++;if(state.closeFail)throw Error('private close');},
    async request(method,path,request){
      assert.equal(state.clients.every(client=>client.status==='I'),true,'no SQL lease across HTTP');
      if(state.wait)await bounded(state.wait,{deadline:request.deadline,signal:request.signal});
      const body=JSON.parse(Buffer.from(request.body));state.requests.push({method,path,body,max_response_bytes:request.max_response_bytes});
      let points=tombstoned?[]:clone(records);
      if(state.mode==='missing')points=[];
      if(state.mode==='duplicate'&&points.length)points[1]=clone(points[0]);
      if(state.mode==='dense'&&points.length)points[0].vector.dense[0]=-1;
      if(state.mode==='sparse'&&points.length)points[0].vector.sparse.values[0]=9;
      if(state.mode==='text'&&points.length)points[0].payload.text='private source canary';
      if(state.mode==='foreign'&&points.length)points[0].payload.tenant_id='foreign';
      if(state.mode==='shard'&&points.length)points[0].shard_key='foreign-shard';
      if(state.mode==='metadata'&&points.length)points[0].version=1;
      if(state.afterHttp){const change=state.afterHttp;state.afterHttp=null;change();}
      if(path.endsWith('/scroll')){
        if(memberCount===64){
          if(state.mode==='overflow65'){
            const extra=clone(records[0]);extra.id='ffffffff-ffff-5fff-8fff-ffffffffffff';points.push(extra);
          }
          const start=body.offset===undefined?0:points.findIndex(point=>point.id===body.offset)+1;
          const page=points.slice(start,start+8);
          const next=page.length===8?page.at(-1).id:null;
          return padded({status:'ok',result:{points:page,next_page_offset:next}},request.max_response_bytes);
        }
        if(state.mode==='empty-offset')points=[];
        if(state.mode==='extra'||state.mode==='tombstone-extra'){
          const extra=clone(records[0]);extra.id='00000000-0000-5000-8000-000000000099';points.push(extra);
          if(state.mode==='tombstone-extra')extra.payload.dense_profile_id='wrong-profile';
        }
        return padded({status:'ok',result:{points,next_page_offset:['cycle','empty-offset'].includes(state.mode)?records[0].id:null}},request.max_response_bytes);
      }
      return padded({status:'ok',result:points.filter(point=>body.ids.includes(point.id))},request.max_response_bytes);
    }})));
  function padded(value,cap){
    assert.ok(Number.isInteger(cap)&&cap>=1&&cap<=1048576);
    const encoded=Buffer.from(JSON.stringify(value)),size=Math.max(encoded.length,state.padBytes);
    if(size>cap)throw new ProviderUnavailable();
    return state.padBytes?Object.freeze(Array.from(Buffer.concat([encoded,Buffer.alloc(size-encoded.length,32)]))):jsonBytes(value);
  }
  const verifier=new QdrantReconciliationVerifier(writer,supervisor);
  return {state,writer,verifier,supervisor,proof:state.currentProof,expected,async close(){await verifier.close();await writer.close();await resource.close();for(const method of methods.reverse())method.mock.restore();await supervisor.close();}};
}

test('successful native-byte JSON readback yields issuer-bound immutable witness only',async()=>{
  const x=await setup();try{
    const receipt=await x.verifier.verify(x.proof,context,options()),data=receipt_data(receipt,x.verifier);
    assert.ok(Object.isFrozen(receipt));assert.deepEqual(JSON.parse(JSON.stringify(receipt)),{});
    assert.ok(Object.isFrozen(data.witness));assert.equal(data.witness.length,22);assert.equal(data.sha256,data.readback_sha256);
    assert.equal(data.point_ids.length,2);assert.equal('canonical_text'in data,false);
    assert.throws(()=>receipt_data({...receipt},x.verifier),InvalidRequest);
    assert.equal(x.state.requests.length,2);
    const scroll=x.state.requests.find(request=>request.path.endsWith('/scroll'));
    assert.equal(scroll.body.limit,8);assert.equal(scroll.body.with_payload,true);
    assert.equal(JSON.stringify(scroll.body.filter).includes('has_id'),false);
    assert.equal(JSON.stringify(scroll.body.filter).includes('dense_profile_id'),false);
    x.state.currentProof={};assert.throws(()=>receipt_data(receipt,x.verifier),UnsupportedCapability);
  }finally{await x.close();}
});

test('readback membership vectors payload and unsharded metadata contradictions never issue receipts',async()=>{
  for(const mode of ['missing','duplicate','dense','sparse','text','foreign','extra','shard','metadata','cycle','empty-offset']){
    const x=await setup();try{
      x.state.mode=mode;
      await assert.rejects(x.verifier.verify(x.proof,context,options()),error=>error instanceof IntegrityViolation&&!String(error).includes('canary'));
      assert.equal(x.state.tables.backend_instances[0].state,'recovery_blocked');
    }finally{await x.close();}
  }
});

test('tombstones require both exact expected IDs absent and full scoped scroll empty',async()=>{
  const x=await setup(true);try{
    const receipt=await x.verifier.verify(x.proof,context,options());assert.equal(receipt_data(receipt,x.verifier).tombstoned,true);
    x.state.mode='tombstone-extra';await assert.rejects(x.verifier.verify(x.proof,context,options()),IntegrityViolation);
  }finally{await x.close();}
});

test('fresh SQL revalidation catches authority changes after HTTP and cleanup failures remain operational',async()=>{
  const x=await setup();try{
    x.state.afterHttp=()=>{x.state.tables.documents[0].tag='changed';};
    await assert.rejects(x.verifier.verify(x.proof,context,options()),UnauthorizedScope);
  }finally{await x.close();}
  const failed=await setup();try{
    failed.state.mode='dense';failed.state.closeFail=true;
    await assert.rejects(failed.verifier.verify(failed.proof,context,options()),ProviderUnavailable);
  }finally{failed.state.closeFail=false;await failed.close();}
});

test('copied proof, concurrent operations and midflight deadline/cancellation cannot mint receipts',async()=>{
  const x=await setup();try{
    await assert.rejects(x.verifier.verify({...x.proof},context,options()),UnsupportedCapability);
    let finish;x.state.wait=new Promise(resolve=>{finish=resolve;});
    const controller=new AbortController();const pending=x.verifier.verify(x.proof,context,{...options(),signal:controller.signal});
    const rejected=assert.rejects(pending,error=>error.name==='AbortError');await new Promise(resolve=>setImmediate(resolve));
    await assert.rejects(x.verifier.verify(x.proof,context,options()),ProviderUnavailable);controller.abort();await rejected;finish();x.state.wait=null;
    await assert.rejects(x.verifier.verify(x.proof,context,{deadline:now()-1}),DeadlineExceeded);
  }finally{await x.close();}
});

test('64 members require every UUID batch and explicit empty scoped EOF within 17 calls',async()=>{
  const x=await setup(false,64);try{
    const receipt=await x.verifier.verify(x.proof,context,{deadline:now()+10});
    assert.equal(receipt_data(receipt,x.verifier).point_ids.length,64);
    assert.equal(x.state.requests.length,17);
    assert.equal(x.state.requests.filter(request=>request.path.endsWith('/scroll')).length,9);
    for(const request of x.state.requests)assert.ok(request.body.ids?request.body.ids.length<=8:request.body.limit===8);
  }finally{await x.close();}
});
test('an unexpected 65th scoped member is rejected on the overflow page',async()=>{
  const x=await setup(false,64);try{
    x.state.mode='overflow65';await assert.rejects(x.verifier.verify(x.proof,context,options()),IntegrityViolation);
    assert.equal(x.state.requests.length,17);assert.equal(x.state.tables.backend_instances[0].state,'recovery_blocked');
  }finally{await x.close();}
});
test('aggregate allowance shrinks HTTP stream caps and zero remaining prevents dispatch',async()=>{
  for(const padding of [900000,1048576]){
    const x=await setup(false,64);try{
      x.state.padBytes=padding;await assert.rejects(x.verifier.verify(x.proof,context,{deadline:now()+30}),ProviderUnavailable);
      if(padding===1048576){assert.equal(x.state.requests.length,8);}
      else{
        assert.equal(x.state.requests.length,10);
        assert.equal(x.state.requests.at(-1).max_response_bytes,8388608-9*900000);
      }
      assert.ok(x.state.requests.every(request=>request.max_response_bytes>0&&request.max_response_bytes<=1048576));
    }finally{await x.close();}
  }
});

test('verifier requires exact native components and rejects proxies without invoking traps',async()=>{
  const x=await setup();try{
    let hooks=0;
    const writerProxy=new Proxy(x.writer,{getPrototypeOf(){hooks++;throw Error('private');}});
    const supervisorProxy=new Proxy(x.supervisor,{getPrototypeOf(){hooks++;throw Error('private');}});
    class DerivedWriter extends PostgresQdrantWriter{}
    class DerivedSupervisor extends ManagedQdrantSupervisor{}
    const clients=x.state.clients.length,requests=x.state.requests.length;
    for(const [writer,supervisor] of [[writerProxy,x.supervisor],[x.writer,supervisorProxy],
      [Object.create(DerivedWriter.prototype),x.supervisor],[x.writer,Object.create(DerivedSupervisor.prototype)]]){
      assert.throws(()=>new QdrantReconciliationVerifier(writer,supervisor),InvalidRequest);
    }
    assert.equal(hooks,0);assert.equal(x.state.clients.length,clients);assert.equal(x.state.requests.length,requests);
  }finally{await x.close();}
});

test('internal authority binding requires the exact registered verifier and supervisor pair',async()=>{
  const x=await setup();try{
    assert.equal(verifier_authority(x.verifier,x.supervisor),x.writer);
    class DerivedVerifier extends QdrantReconciliationVerifier{}
    let hooks=0;
    const proxy=new Proxy(x.verifier,{getPrototypeOf(){hooks++;throw Error('private');}});
    for(const [verifier,supervisor] of [[x.verifier,{}],[{},x.supervisor],
      [Object.create(QdrantReconciliationVerifier.prototype),x.supervisor],
      [new DerivedVerifier(x.writer,x.supervisor),x.supervisor],[proxy,x.supervisor]]){
      assert.throws(()=>verifier_authority(verifier,supervisor),InvalidRequest);
    }
    assert.equal(hooks,0);assert.equal(x.state.requests.length,0);
  }finally{await x.close();}
});

function diagnosticTransport(expected,{missing=[],mode=null,padding=0}={}){
  const calls=[];
  const records=expected.points.map(point=>({id:point.point_id,payload:clone(point.payload),vector:{dense:[...point.dense.values],
    ...(point.sparse?{sparse:{indices:[...point.sparse.indices],values:[...point.sparse.values]}}:{})}}));
  return {calls,async close(){},async request(method,path,options){
    const body=JSON.parse(Buffer.from(options.body));calls.push({method,path,body,maximum:options.max_response_bytes});
    let present=clone(records.filter(point=>!missing.includes(point.id)));
    if(mode==='dense'&&present.length)present[0].vector.dense[0]=-1;
    if(mode==='sparse'&&present.length)present[0].vector.sparse.values[0]=9;
    if(mode==='payload'&&present.length)present[0].payload.authorization_revision='stale';
    if(mode==='profile'&&present.length)present[0].payload.dense_profile={...present[0].payload.dense_profile,revision:'wrong'};
    if(mode==='duplicate'&&present.length)present.push(clone(present[0]));
    const scroll=path.endsWith('/scroll');
    if(mode==='extra'&&scroll){const extra=clone(records[0]);extra.id='ffffffff-ffff-5fff-8fff-ffffffffffff';present.push(extra);}
    if(mode==='get-scroll-drift'&&scroll)present=present.filter(point=>point.id!==records[0].id);
    if(mode==='get-wrong-batch'&&!scroll)present=[clone(records.at(-1))];
    if(!scroll)present=mode==='get-wrong-batch'?present:present.filter(point=>body.ids.includes(point.id));
    const start=scroll&&body.offset!==undefined?present.findIndex(point=>point.id===body.offset)+1:0;
    const page=scroll?present.slice(start,start+8):present;
    const next=mode==='cycle'&&scroll?records[0].id:scroll&&page.length===8?page.at(-1).id:null;
    const value={status:'ok',result:scroll?{points:page,next_page_offset:next}:page};
    if(mode==='bad-offset'&&scroll)value.result.next_page_offset='bad';
    if(mode==='bad-envelope')return jsonBytes({result:[]});
    if(mode==='malformed-json')return Object.freeze([123,110,111]);
    if(mode==='invalid-byte')return Object.freeze([256]);
    const raw=Buffer.from(JSON.stringify(value));
    const length=padding?Math.min(padding,options.max_response_bytes):raw.length;
    if(raw.length>length)throw new ProviderUnavailable();
    return Object.freeze(Array.from(Buffer.concat([raw,Buffer.alloc(length-raw.length,32)])));
  }};
}

test('missing inspection reports only exact missing UUIDs and never changes strict completeness',async()=>{
  const x=await setup();try{
    const ids=x.expected.points.map(point=>point.point_id);
    for(const absent of [[],[ids[0]],ids]){
      const transport=diagnosticTransport(x.expected,{missing:absent});
      const missing=await inspect_missing_readback(transport,config.physical_collection,x.expected,options());
      assert.deepEqual(missing,[...absent].sort());assert(Object.isFrozen(missing));
      assert.equal(transport.calls.length,2);
      const scroll=transport.calls[1].body;
      assert.equal(scroll.limit,8);assert.equal(scroll.filter.must.length,8);
      assert.equal(scroll.filter.must.some(item=>['has_id','id','dense_profile','dense_profile_id'].includes(item.key)),false);
      if(absent.length)await assert.rejects(verify_projection_readback(transport,config.physical_collection,x.expected,options()),IntegrityViolation);
      else await verify_projection_readback(transport,config.physical_collection,x.expected,options());
    }
  }finally{await x.close();}
});

test('missing inspection refuses present corruption extras duplicates and inconsistent observation sets',async()=>{
  const x=await setup();try{
    for(const mode of ['dense','sparse','payload','profile','duplicate','extra','get-scroll-drift','cycle','bad-offset','bad-envelope']){
      const transport=diagnosticTransport(x.expected,{mode});
      await assert.rejects(inspect_missing_readback(transport,config.physical_collection,x.expected,options()),IntegrityViolation,mode);
    }
  }finally{await x.close();}
});

test('missing inspection rejects unsupported tombstones and invalid expected membership before HTTP',async()=>{
  const x=await setup();try{
    const transport=diagnosticTransport(x.expected);
    await assert.rejects(inspect_missing_readback(transport,config.physical_collection,{...x.expected,tombstoned:true},options()),UnsupportedCapability);
    for(const points of [[],Array.from({length:65},()=>x.expected.points[0]),[x.expected.points[0],x.expected.points[0]],
      [{...x.expected.points[0],payload:{...x.expected.points[0].payload,physical_collection:'foreign'}}]]){
      await assert.rejects(inspect_missing_readback(transport,config.physical_collection,{...x.expected,points},options()),InvalidRequest);
    }
    assert.equal(transport.calls.length,0);
  }finally{await x.close();}
});

test('missing inspection enforces each GET batch and complete 64-member scoped enumeration',async()=>{
  const x=await setup(false,64);try{
    const transport=diagnosticTransport(x.expected);
    assert.deepEqual(await inspect_missing_readback(transport,config.physical_collection,x.expected,{deadline:now()+10}),[]);
    assert.equal(transport.calls.length,17);assert.equal(transport.calls.at(-1).body.offset,x.expected.points.at(-1).point_id);
    const drift=diagnosticTransport(x.expected,{mode:'get-wrong-batch'});
    await assert.rejects(inspect_missing_readback(drift,config.physical_collection,x.expected,options()),IntegrityViolation);
    assert.equal(drift.calls.length,1);
  }finally{await x.close();}
});

test('shared nominal verification budget shrinks across separate passes and zero forbids another HTTP',async()=>{
  const x=await setup();try{
    const budget=new VerificationBudget(),transport=diagnosticTransport(x.expected,{missing:x.expected.points.map(point=>point.point_id),padding:900000});
    assert.equal(budget.remaining_bytes,8388608);assert.equal(verification_budget(budget),budget);
    assert.equal(verification_budget().remaining_bytes,8388608);
    for(let pass=0;pass<5;pass++)await inspect_missing_readback(transport,config.physical_collection,x.expected,{deadline:now()+30},budget);
    assert.equal(transport.calls.length,10);assert.equal(transport.calls.at(-1).maximum,8388608-9*900000);
    assert.equal(budget.remaining_bytes,0);
    await assert.rejects(inspect_missing_readback(transport,config.physical_collection,x.expected,options(),budget),ProviderUnavailable);
    await assert.rejects(verify_projection_readback(transport,config.physical_collection,x.expected,options(),budget),ProviderUnavailable);
    assert.equal(transport.calls.length,10);
    assert.throws(()=>{budget.remaining_bytes=8388608;},TypeError);
    assert.throws(()=>new VerificationBudget(1),InvalidRequest);
  }finally{await x.close();}
});

test('malformed returned bytes consume budget before parsing and fabricated budgets cause no HTTP',async()=>{
  const x=await setup();try{
    const budget=new VerificationBudget();
    for(const [mode,length] of [['malformed-json',3],['invalid-byte',1]]){
      const before=budget.remaining_bytes,transport=diagnosticTransport(x.expected,{mode});
      await assert.rejects(inspect_missing_readback(transport,config.physical_collection,x.expected,options(),budget),IntegrityViolation);
      assert.equal(budget.remaining_bytes,before-length);
    }
    const transport=diagnosticTransport(x.expected);let hooks=0;
    const proxy=new Proxy(new VerificationBudget(),{getPrototypeOf(){hooks++;throw Error('hook');}});
    for(const fake of [{remaining_bytes:8388608},Object.create(VerificationBudget.prototype),proxy,null]){
      await assert.rejects(inspect_missing_readback(transport,config.physical_collection,x.expected,options(),fake),InvalidRequest);
      await assert.rejects(x.verifier.verify(x.proof,context,options(),fake),InvalidRequest);
    }
    assert.equal(hooks,0);assert.equal(transport.calls.length,0);
  }finally{await x.close();}
});

test('strict E2 verifier shares an explicitly supplied verification budget across receipt passes',async()=>{
  const x=await setup();try{
    const budget=new VerificationBudget();
    await x.verifier.verify(x.proof,context,options(),budget);const after=budget.remaining_bytes;
    assert(after<8388608);
    await x.verifier.verify(x.proof,context,options(),budget);assert(budget.remaining_bytes<after);
    assert.equal(x.state.requests.length,4);
  }finally{await x.close();}
});

test('missing inspection rejects empty continuation and 65th member rather than claiming missing diagnostics',async()=>{
  const x=await setup(false,64);try{
    const extra=diagnosticTransport(x.expected,{mode:'extra'});
    await assert.rejects(inspect_missing_readback(extra,config.physical_collection,x.expected,{deadline:now()+10}),IntegrityViolation);
    assert.equal(extra.calls.length,17);
    const empty=diagnosticTransport(x.expected,{mode:'cycle',missing:x.expected.points.map(point=>point.point_id)});
    await assert.rejects(inspect_missing_readback(empty,config.physical_collection,x.expected,options()),IntegrityViolation);
  }finally{await x.close();}
});

test('response ceiling violations consume returned byte allowance before failure',async()=>{
  const x=await setup();try{
    const budget=new VerificationBudget();let calls=0;
    const transport={async close(){},async request(){calls++;return new Array(1048577).fill(32);}};
    await assert.rejects(inspect_missing_readback(transport,config.physical_collection,x.expected,options(),budget),IntegrityViolation);
    assert.equal(calls,1);assert.equal(budget.remaining_bytes,8388608-1048577);
  }finally{await x.close();}
});
