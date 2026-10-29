import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {SecurityReadbackBudget,security_readback_budget,inspect_security_readback,verify_security_readback} from '../dist/qdrant-security-readback.js';
import {encode_dense,encode_sparse} from '../dist/qdrant-vectors.js';
import {point_id} from '../dist/qdrant-contract.js';
import {now} from '../dist/postgres-pool.js';
import {InvalidRequest,IntegrityViolation,ProviderUnavailable,DeadlineExceeded} from '../dist/errors.js';
const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_publication.json',import.meta.url),'utf8'));
const config={...fixture.physical,dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse};
const options=()=>({deadline:now()+5});
const clone=value=>JSON.parse(JSON.stringify(value));
const bytes=value=>Object.freeze(Array.from(Buffer.from(JSON.stringify(value))));
function setup(size=3,tombstoned=false){
  const context={scope:{tenant_id:'tenant-a',principal_id:'reader-a',grant_ids:['grant-a'],authorization_revision:'auth-2'},
    collection:'docs',document_id:'doc-1',intent_id:'security-1',owner_token:'00000000-0000-4000-8000-000000000001'};
  const points=Array.from({length:size},(_,index)=>{
    const member=fixture.members[0],generation='generation-'+Math.floor(index/8),chunk='chunk-'+index;
    const payload={...fixture.physical,tenant_id:'tenant-a',collection:'docs',document_id:'doc-1',revision_id:fixture.source_revision.revision_id,
      generation_id:generation,chunk_id:chunk,start_byte:member.start_byte,end_byte:member.end_byte,
      source_sha256:fixture.source_revision.source_sha256,text_sha256:member.text_sha256,dense_profile:config.dense_profile,sparse_profile:config.sparse_profile,
      dense_profile_id:config.dense_profile.profile_id,sparse_profile_id:config.sparse_profile.profile_id,
      authorization_revision:'auth-2',principal_ids:['reader-a'],grant_ids:['grant-a'],language:'en'};
    const id=point_id(['cragkit.qdrant.point.v1',config.backend_namespace,config.physical_collection,config.collection_incarnation,
      'tenant-a','docs','doc-1',payload.revision_id,generation,chunk,config.dense_profile.profile_id,config.sparse_profile.profile_id]);
    return Object.freeze({point_id:id,payload,dense:encode_dense(Array.from({length:1536},(_,i)=>i===index%1536?1:0),config.dense_profile),
      sparse:encode_sparse([index],[1],config.sparse_profile)});
  }).sort((a,b)=>a.point_id.localeCompare(b.point_id));
  const expected={context,point_ids:points.map(point=>point.point_id),points,tombstoned};
  const stored=points.map(point=>({id:point.point_id,payload:clone(point.payload),vector:{dense:[...point.dense.values],sparse:{indices:[...point.sparse.indices],values:[...point.sparse.values]}}}));
  const state={get:clone(stored),scroll:clone(stored),calls:[],closed:0,mode:null};
  const transport={async request(method,path,request){
    state.calls.push({method,path,...request,body:JSON.parse(Buffer.from(request.body))});
    const body=state.calls.at(-1).body;
    if(state.mode==='throw')throw new Error('private transport error');
    if(state.mode==='malformed')return [123,33];
    if(state.mode==='bytes')return [256];
    if(state.mode==='proxy')return new Proxy([],{});
    if(state.mode==='oversized')return Array(request.max_response_bytes+1).fill(32);
    if(state.mode==='abort'){request.signal?.dispatchEvent(new Event('abort'));}
    const values=path.endsWith('/scroll')?state.scroll:state.get.filter(row=>body.ids.includes(row.id));
    if(path.endsWith('/scroll')){
      let start=body.offset?state.scroll.findIndex(row=>row.id===body.offset)+1:0;
      if(state.mode==='empty-nonfinal')return bytes({status:'ok',result:{points:[],next_page_offset:expected.point_ids[0]}});
      if(state.mode==='repeat-offset')start=0;
      const page=values.slice(start,start+8),next=start+8<values.length||state.mode==='repeat-offset'?page.at(-1)?.id:null;
      return bytes({status:'ok',result:{points:page,next_page_offset:next}});
    }
    return bytes({status:'ok',result:values});
  },async close(){state.closed++;}};
  return {expected,state,transport};
}

test('current multigeneration inspection and verification use full six-field scope and borrowed lifetime',async()=>{
  const f=setup(17),budget=new SecurityReadbackBudget();
  const result=await inspect_security_readback(f.transport,config,f.expected,options(),budget);
  assert.deepEqual(result,{present_ids:f.expected.point_ids,missing_ids:[],stale_ids:[]});
  assert.ok(Object.isFrozen(result.present_ids));assert.equal(Object.isFrozen(result),true);
  assert.equal(budget.remaining_calls,513-6);
  for(const call of f.state.calls){
    assert.equal(call.method,'POST');assert.equal(call.max_response_bytes<=1048576,true);
    if(call.path.endsWith('/scroll'))assert.deepEqual(call.body.filter.must.map(item=>item.key),
      ['backend_namespace','physical_collection','collection_incarnation','tenant_id','collection','document_id']);
    else assert.ok(call.body.ids.length<=8);
  }
  await verify_security_readback(f.transport,config,f.expected,options(),budget);assert.equal(f.state.closed,0);
});

test('known stale mutable fields and missing claims are diagnostics only',async()=>{
  const f=setup();f.state.get.pop();f.state.scroll.pop();
  for(const list of [f.state.get,f.state.scroll])Object.assign(list[0].payload,{authorization_revision:'auth-1',principal_ids:[],grant_ids:['old'],language:'fr',kind:'old',tag:'old'});
  const result=await inspect_security_readback(f.transport,config,f.expected,options());
  assert.deepEqual(result.missing_ids,[f.expected.point_ids.at(-1)]);assert.deepEqual(result.stale_ids,[f.expected.point_ids[0]]);
  await assert.rejects(verify_security_readback(f.transport,config,f.expected,options()),IntegrityViolation);
});

for(const mode of ['duplicates','order'])test(`ACL ${mode} are stale and representation drift cannot satisfy exact verification`,async()=>{
  const f=setup();
  // Expected source authority is canonical; valid wire representations still differ.
  if(mode==='order'){
    f.expected.points[0].payload.principal_ids=['reader-a','reader-b'];
    f.state.get[0].payload.principal_ids=['reader-b','reader-a'];
  }else f.state.get[0].payload.principal_ids=['reader-a','reader-a'];
  f.state.scroll[0].payload.principal_ids=[...f.state.get[0].payload.principal_ids];
  const result=await inspect_security_readback(f.transport,config,f.expected,options());
  assert.deepEqual(result.stale_ids,[f.expected.point_ids[0]]);
  await assert.rejects(verify_security_readback(f.transport,config,f.expected,options()),IntegrityViolation);
  f.state.scroll[0].payload.principal_ids=[...f.expected.points[0].payload.principal_ids];
  await assert.rejects(inspect_security_readback(f.transport,config,f.expected,options()),IntegrityViolation);
});

test('tombstone inspection observes debris while strict verification requires complete absence',async()=>{
  const f=setup(2,true);
  assert.equal((await inspect_security_readback(f.transport,config,f.expected,options())).present_ids.length,2);
  await assert.rejects(verify_security_readback(f.transport,config,f.expected,options()),IntegrityViolation);
  f.state.get=[];f.state.scroll=[];await verify_security_readback(f.transport,config,f.expected,options());
  const empty=setup(0);await verify_security_readback(empty.transport,config,empty.expected,options());
  assert.equal(empty.state.calls.length,1);assert.ok(empty.state.calls[0].body.filter.must.some(item=>item.key==='document_id'));
});

for(const fault of ['extra','extra-generation','duplicate','dense','sparse','profile','immutable','unknown','mutable-shape','shard','membership','scroll-only'])
  test(`security readback refuses ${fault} corruption`,async()=>{
    const f=setup();
    if(fault==='extra'||fault==='extra-generation'){
      const row=clone(f.state.scroll[0]);row.id='00000000-0000-4000-8000-000000000099';row.payload.generation_id='unclaimed';f.state.scroll.push(row);
    }else if(fault==='duplicate')f.state.get.push(clone(f.state.get[0]));
    else if(fault==='dense')f.state.get[0].vector.dense.fill(0);
    else if(fault==='sparse')f.state.get[0].vector.sparse.values[0]=2;
    else if(fault==='profile')f.state.get[0].payload.dense_profile.model='foreign';
    else if(fault==='immutable')f.state.get[0].payload.source_sha256='0'.repeat(64);
    else if(fault==='unknown')f.state.get[0].payload.private_text='canary';
    else if(fault==='mutable-shape')f.state.get[0].payload.grant_ids='invalid';
    else if(fault==='shard')f.state.get[0].shard_key='foreign-shard';
    else if(fault==='membership')f.state.get[0].id=f.expected.point_ids[1];
    else f.state.get.pop();
    await assert.rejects(inspect_security_readback(f.transport,config,f.expected,options()),IntegrityViolation);
  });

for(const mode of ['empty-nonfinal','repeat-offset','malformed','bytes','proxy','oversized','throw'])test(`security readback ${mode} fails without closing transport`,async()=>{
  const f=setup(9);f.state.mode=mode;const budget=new SecurityReadbackBudget();
  await assert.rejects(inspect_security_readback(f.transport,config,f.expected,options(),budget),mode==='throw'?ProviderUnavailable:IntegrityViolation);
  assert.ok(budget.remaining_calls<513);if(['malformed','bytes','oversized'].includes(mode))assert.ok(budget.remaining_bytes<8388608);
  assert.equal(f.state.closed,0);
});

test('shared attempted-call budget cannot reset through repeated empty passes or failed HTTP',async()=>{
  const f=setup(0),budget=new SecurityReadbackBudget();
  for(let count=0;count<513;count++)await verify_security_readback(f.transport,config,f.expected,options(),budget);
  assert.equal(budget.remaining_calls,0);assert.ok(budget.remaining_bytes>0);
  await assert.rejects(inspect_security_readback(f.transport,config,f.expected,options(),budget),ProviderUnavailable);
  assert.equal(f.state.calls.length,513);
  assert.equal(security_readback_budget(budget),budget);
  for(const invalid of [{...budget},Object.create(SecurityReadbackBudget.prototype),new Proxy(budget,{})])assert.throws(()=>security_readback_budget(invalid),InvalidRequest);
  class Child extends SecurityReadbackBudget{}assert.throws(()=>new Child(),InvalidRequest);
  assert.throws(()=>new SecurityReadbackBudget(1),InvalidRequest);
  assert.throws(()=>{budget.remaining_calls=513;},TypeError);
  const g=setup(0),other=new SecurityReadbackBudget();g.state.mode='throw';
  await assert.rejects(inspect_security_readback(g.transport,config,g.expected,options(),other),ProviderUnavailable);assert.equal(other.remaining_calls,512);
});

test('shared byte allowance charges malformed replies and reduces the next transport maximum',async()=>{
  const f=setup(0),budget=new SecurityReadbackBudget();
  f.transport.request=async(method,path,options)=>{f.state.calls.push(options.max_response_bytes);return Array(options.max_response_bytes).fill(32);};
  for(let pass=0;pass<8;pass++)await assert.rejects(inspect_security_readback(f.transport,config,f.expected,options(),budget),IntegrityViolation);
  assert.equal(budget.remaining_bytes,0);assert.equal(budget.remaining_calls,505);
  await assert.rejects(inspect_security_readback(f.transport,config,f.expected,options(),budget),ProviderUnavailable);assert.equal(f.state.calls.length,8);
});

for(const invalid of ['ids','scope','authorization','profile','point-id','tombstone'])test(`expected ${invalid} admission fails before HTTP`,async()=>{
  const f=setup();
  if(invalid==='ids')f.expected.point_ids=[...f.expected.point_ids].reverse();
  if(invalid==='scope')f.expected.context.document_id='foreign';
  if(invalid==='authorization')f.expected.context.scope.authorization_revision='other';
  if(invalid==='profile')f.expected.points[0].payload.dense_profile={...config.dense_profile,model:'foreign'};
  if(invalid==='point-id')f.expected.point_ids[0]='00000000-0000-4000-8000-000000000099';
  if(invalid==='tombstone')f.expected.tombstoned=1;
  await assert.rejects(inspect_security_readback(f.transport,config,f.expected,options()),InvalidRequest);assert.equal(f.state.calls.length,0);
});

test('caller deadline and abort prevent late transport success from becoming verification',async()=>{
  const f=setup(0);let complete;f.transport.request=async()=>new Promise(resolve=>{complete=resolve;});
  const controller=new AbortController(),budget=new SecurityReadbackBudget();
  const work=verify_security_readback(f.transport,config,f.expected,{...options(),signal:controller.signal},budget);
  const response=bytes({status:'ok',result:{points:[],next_page_offset:null}});
  const refusal=assert.rejects(work,error=>error.name==='AbortError');controller.abort();complete(response);await refusal;
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(budget.remaining_bytes,8388608-response.length);
  assert.equal(budget.remaining_calls,512);assert.equal(f.state.closed,0);
  const g=setup(0);g.transport.request=async()=>{await new Promise(resolve=>setTimeout(resolve,30));return bytes({status:'ok',result:{points:[],next_page_offset:null}});};
  await assert.rejects(verify_security_readback(g.transport,config,g.expected,{deadline:now()+.01}),DeadlineExceeded);
});


test('storage mutation acknowledgment shares readback call and byte limits',async()=>{
  const {security_storage_request}=await import('../dist/qdrant-security-readback.js');
  let calls=0;const transport={async request(method,path,options){calls++;assert.ok(['POST','PUT'].includes(method));
    assert.deepEqual(options.body,[123,125]);assert.ok(options.max_response_bytes<=1048576);return Object.freeze([123,125]);}};
  const budget=new SecurityReadbackBudget(),lease=options();
  for(let index=0;index<512;index++)await security_storage_request(transport,'POST','/read',[123,125],lease,budget);
  assert.deepEqual(await security_storage_request(transport,'PUT','/write',[123,125],lease,budget),[123,125]);
  assert.equal(budget.remaining_calls,0);assert.equal(budget.remaining_bytes,8388608-1026);
  await assert.rejects(security_storage_request(transport,'POST','/read',[123,125],lease,budget),ProviderUnavailable);
  assert.equal(calls,513);
});
