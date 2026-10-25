import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {bind_embedding_batch,QdrantSearchStore,point_id} from '../dist/qdrant.js';
import {FAKE_PROFILE,OPENAI_PROFILE,EmbeddingBatchSchema} from '../dist/embeddings.js';
import {ExecutionLedger} from '../dist/execution.js';
import {valid_native_json} from '../dist/shared.js';
import {EmbeddingProfileMismatch,InvalidRequest,IntegrityViolation,UnsupportedCapability} from '../dist/errors.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_candidates.json',import.meta.url),'utf8'));
const unit=()=>Array.from({length:1536},(_,i)=>i===0?1:0);
function batch(profile=FAKE_PROFILE,count=1){return {profile:structuredClone(profile),vectors:Array.from({length:count},unit),usage:{prompt_tokens:2,total_tokens:2,cost_usd:profile.provider==='fake'?0:null,cost_kind:profile.provider==='fake'?'known':'unknown'},provider_calls:1,synthetic:profile.provider==='fake'};}
const deadline=()=>performance.now()/1000+3;
const bytes=v=>Buffer.from(JSON.stringify(v));
function config(profile=FAKE_PROFILE){return {backend_namespace:'fixture-local',physical_collection:'cragkit_qc_r1',collection_incarnation:'inc-1',dense_profile:profile,sparse_profile:null};}
function responsePoint(profile=FAKE_PROFILE){
  const payload={...structuredClone(fixture.base_payload),dense_profile:structuredClone(profile),dense_profile_id:profile.profile_id,sparse_profile:null,sparse_profile_id:''};
  const tuple=['cragkit.qdrant.point.v1',payload.backend_namespace,payload.physical_collection,payload.collection_incarnation,payload.tenant_id,payload.collection,payload.document_id,payload.revision_id,payload.generation_id,payload.chunk_id,payload.dense_profile_id,''];
  return {id:point_id(tuple),score:0.75,payload};
}
function spyTransport(profile=FAKE_PROFILE){return {bounded_responses:true,cancellation_safe:true,calls:[],async request(method,path,options){this.calls.push({method,path,body:options.body&&JSON.parse(Buffer.from(options.body).toString())});
  if(path==='/')return bytes({version:'1.20.0'});
  if(path==='/cluster')return bytes({status:'ok',result:{status:'disabled'}});
  if(method==='GET')return bytes({status:'ok',result:{config:{params:{vectors:{dense:{size:1536,distance:'Cosine'}},sparse_vectors:{},replication_factor:1,write_consistency_factor:1}}}});
  return bytes({status:'ok',result:{points:[responsePoint(profile)]}});
}};}
function searchOptions(dense){return {scope:fixture.trusted_scope,dense,branch_limits:{dense:1},ledger:new ExecutionLedger({limits:{max_candidates:2},deadline:deadline()}),deadline:deadline()};}
const request={query:'synthetic routing only',collection:'docs',limits:{max_candidates:2}};

test('binding returns immutable E-r1 batch, snapshots vectors/profile/usage and makes no calls',()=>{
  const source=batch();const result=bind_embedding_batch(source,FAKE_PROFILE,{expected_items:1});
  assert.deepEqual(result,EmbeddingBatchSchema.parse(source));assert.ok(Object.isFrozen(result));assert.ok(Object.isFrozen(result.vectors[0]));assert.ok(Object.isFrozen(result.usage));
  source.vectors[0][0]=0;source.profile.model='changed';source.usage.cost_kind='unknown';assert.equal(result.vectors[0][0],1);assert.equal(result.profile.model,FAKE_PROFILE.model);assert.equal(result.usage.cost_kind,'known');
});
test('eight full vectors fit dedicated batch guard without expanding core JSON admission',()=>{
  const source=batch(FAKE_PROFILE,8);assert.equal(valid_native_json(source),false);
  const bound=bind_embedding_batch(source,FAKE_PROFILE,{expected_items:8});assert.equal(bound.vectors.length,8);assert.ok(bound.vectors.every(Object.isFrozen));assert.equal(valid_native_json(source),false);
});
test('real binding preserves unknown usage and declared estimated cost separately',()=>{
  const unknown=batch(OPENAI_PROFILE);unknown.usage.prompt_tokens=null;unknown.usage.total_tokens=null;
  assert.deepEqual(bind_embedding_batch(unknown,OPENAI_PROFILE).usage,unknown.usage);
  const estimated=batch(OPENAI_PROFILE);estimated.usage.cost_kind='estimated';estimated.usage.cost_usd=0.000001;
  const bound=bind_embedding_batch(estimated,OPENAI_PROFILE);assert.equal(bound.usage.cost_kind,'estimated');assert.equal(bound.usage.cost_usd,0.000001);assert.equal(bound.synthetic,false);
});
test('full profile, dimensions and synthetic flag mismatches fail closed',()=>{
  for(const mutate of [v=>v.profile.model='same-dimension-other-model',v=>v.profile.profile_id='other-profile',v=>v.profile.dimensions=1535,v=>v.vectors[0].pop(),v=>v.synthetic=false]){
    const value=batch();mutate(value);assert.throws(()=>bind_embedding_batch(value,FAKE_PROFILE),EmbeddingProfileMismatch);
  }
  assert.throws(()=>bind_embedding_batch(batch(),OPENAI_PROFILE),EmbeddingProfileMismatch);
  assert.throws(()=>bind_embedding_batch(batch(),{...FAKE_PROFILE,model:'unsupported'}),EmbeddingProfileMismatch);
});
test('malformed structure, unchecked copies and invalid expected counts are invalid requests',()=>{
  const base=batch();
  for(const value of [{...base,provider_calls:0},{...base,provider_calls:true},{...base,synthetic:'true'},{...base,extra:'unknown'},{...base,profile:{...base.profile,extra:'unknown'}},{...base,vectors:[]},{...base,vectors:Array.from({length:9},unit)}])assert.throws(()=>bind_embedding_batch(value,FAKE_PROFILE),InvalidRequest);
  for(const count of [0,9,1.5,true,null])assert.throws(()=>bind_embedding_batch(base,FAKE_PROFILE,{expected_items:count}),InvalidRequest);
  assert.throws(()=>bind_embedding_batch(base,FAKE_PROFILE,{expected_items:2}),InvalidRequest);
  assert.throws(()=>bind_embedding_batch(base,FAKE_PROFILE,{other:1}),InvalidRequest);
  const unchecked=structuredClone(EmbeddingBatchSchema.parse(base));unchecked.usage.total_tokens=0;assert.throws(()=>bind_embedding_batch(unchecked,FAKE_PROFILE),InvalidRequest);
});
test('cycle, accessor, nonnative, sparse arrays and deep inputs reject before copying',()=>{
  const cycle=batch();cycle.usage.extra=cycle;assert.throws(()=>bind_embedding_batch(cycle,FAKE_PROFILE),InvalidRequest);
  const accessor=batch();Object.defineProperty(accessor,'vectors',{get(){throw Error('private getter');},enumerable:true});assert.throws(()=>bind_embedding_batch(accessor,FAKE_PROFILE),InvalidRequest);
  const nonnative=batch();nonnative.profile=new Date();assert.throws(()=>bind_embedding_batch(nonnative,FAKE_PROFILE),InvalidRequest);
  const hole=batch();delete hole.vectors[0][1];assert.throws(()=>bind_embedding_batch(hole,FAKE_PROFILE),InvalidRequest);
  const symbol=batch();symbol[Symbol('private')]=true;assert.throws(()=>bind_embedding_batch(symbol,FAKE_PROFILE),InvalidRequest);
  const extraIndex=batch();const fakeArray=new Array(1536);for(let i=1;i<1536;i++)fakeArray[i]=0;fakeArray.extra=1;extraIndex.vectors[0]=fakeArray;assert.throws(()=>bind_embedding_batch(extraIndex,FAKE_PROFILE),InvalidRequest);
  const subclass=batch();subclass.vectors[0]=new (class extends Array {})(...unit());assert.throws(()=>bind_embedding_batch(subclass,FAKE_PROFILE),InvalidRequest);
  const deep=batch();let nested=deep;for(let i=0;i<10;i++){nested.extra={};nested=nested.extra;}assert.throws(()=>bind_embedding_batch(deep,FAKE_PROFILE),InvalidRequest);
});
test('batch and expected-profile strings and keys are bounded before schema validation',()=>{
  for(const text of ['x'.repeat(1025),'雪'.repeat(342)]){
    const value=batch();value.profile.model=text;assert.throws(()=>bind_embedding_batch(value,FAKE_PROFILE),InvalidRequest);
    assert.throws(()=>bind_embedding_batch(batch(),{...FAKE_PROFILE,model:text}),InvalidRequest);
  }
  for(const key of ['x'.repeat(257),'雪'.repeat(86),'\ud800']){
    const value=batch();value[key]='bounded';assert.throws(()=>bind_embedding_batch(value,FAKE_PROFILE),InvalidRequest);
    const profile={...FAKE_PROFILE,[key]:'bounded'};assert.throws(()=>bind_embedding_batch(batch(),profile),InvalidRequest);
  }
});
test('invalid vector values and norms reject without normalization',()=>{
  for(const component of [NaN,Infinity,true,'1',null,{}]){const value=batch();value.vectors[0][0]=component;assert.throws(()=>bind_embedding_batch(value,FAKE_PROFILE),InvalidRequest);}
  const zero=batch();zero.vectors[0][0]=0;assert.throws(()=>bind_embedding_batch(zero,FAKE_PROFILE),InvalidRequest);
  const norm=batch();norm.vectors[0][0]=2;assert.throws(()=>bind_embedding_batch(norm,FAKE_PROFILE),InvalidRequest);
});
test('usage combinations and bounds are validated without inventing unknown accounting',()=>{
  for(const mutate of [v=>v.usage.prompt_tokens=null,v=>v.usage.total_tokens=1,v=>v.usage.prompt_tokens=true,v=>v.usage.total_tokens=2147483648,v=>v.usage.cost_usd=-1,v=>v.usage.cost_usd=NaN,v=>v.usage.cost_kind='estimated',v=>v.usage.cost_usd=null]){const value=batch();mutate(value);assert.throws(()=>bind_embedding_batch(value,FAKE_PROFILE),InvalidRequest);}
  for(const usage of [{prompt_tokens:null,total_tokens:null,cost_usd:0,cost_kind:'known'},{prompt_tokens:2,total_tokens:2,cost_usd:null,cost_kind:'estimated'},{prompt_tokens:2,total_tokens:2,cost_usd:1,cost_kind:'unknown'},{prompt_tokens:2,total_tokens:2,cost_usd:1000001,cost_kind:'estimated'}])assert.throws(()=>bind_embedding_batch({...batch(OPENAI_PROFILE),usage},OPENAI_PROFILE),InvalidRequest);
});
test('real-profile routing accepts one bound batch but makes no provider call or real vector write',async()=>{
  const transport=spyTransport(OPENAI_PROFILE),store=new QdrantSearchStore(config(OPENAI_PROFILE),transport);await store.initialize({deadline:deadline()});
  const opts=searchOptions(bind_embedding_batch(batch(OPENAI_PROFILE),OPENAI_PROFILE));const result=await store.search_candidates(request,opts);
  assert.equal(result[0].payload.dense_profile.model,OPENAI_PROFILE.model);assert.equal(result[0].verification,'UNVERIFIED');
  assert.deepEqual(transport.calls[3].body.query,unit());assert.equal(transport.calls[3].body.using,'dense');assert.equal(opts.ledger.snapshot().provider_calls,0);assert.equal(opts.ledger.snapshot().candidates,1);assert.equal(opts.ledger.snapshot().pending,0);await store.close();
});
test('real raw vectors, wrong batch identity and multi-vector queries reject before query dispatch',async()=>{
  const t=spyTransport(OPENAI_PROFILE),store=new QdrantSearchStore(config(OPENAI_PROFILE),t);await store.initialize({deadline:deadline()});
  for(const dense of [unit(),batch(),{...batch(OPENAI_PROFILE),synthetic:true}])await assert.rejects(store.search_candidates(request,searchOptions(dense)),EmbeddingProfileMismatch);
  await assert.rejects(store.search_candidates(request,{...searchOptions(batch(OPENAI_PROFILE)),sparse:fixture.vectors.sparse_manual,branch_limits:{dense:1,sparse:1}}),UnsupportedCapability);
  await assert.rejects(store.search_candidates(request,searchOptions(batch(OPENAI_PROFILE,2))),InvalidRequest);assert.equal(t.calls.length,3);await store.close();
});
test('real plus sparse configuration fails before any I/O',()=>{
  const t=spyTransport(OPENAI_PROFILE);assert.throws(()=>new QdrantSearchStore({...config(OPENAI_PROFILE),sparse_profile:fixture.profiles.sparse},t),UnsupportedCapability);assert.equal(t.calls.length,0);
});
test('fake raw and bound vectors both work; selected response profiles remain exact',async()=>{
  const t=spyTransport(),store=new QdrantSearchStore(config(),t);await store.initialize({deadline:deadline()});
  assert.equal((await store.search_candidates(request,searchOptions(unit()))).length,1);assert.equal((await store.search_candidates(request,searchOptions(batch()))).length,1);
  const original=t.request;t.request=async function(m,p,o){if(m==='POST'){const point=responsePoint();point.payload.dense_profile.model='wrong-model';return bytes({status:'ok',result:{points:[point]}});}return original.call(this,m,p,o);};
  await assert.rejects(store.search_candidates(request,searchOptions(batch())),IntegrityViolation);await store.close();
});
test('shared QC-r1-E batch fixtures agree on profile and wire errors',()=>{
  const shared=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_embedding_batches.json',import.meta.url),'utf8'));
  for(const c of shared.cases){
    const profile=shared.profiles[c.profile];
    const source={profile:structuredClone(profile),vectors:[Array.from({length:shared.vector.dimensions},(_,i)=>i===shared.vector.basis_index?1:0)],usage:{prompt_tokens:1,total_tokens:1,cost_usd:0,cost_kind:profile.provider==='fake'?'known':'estimated'},provider_calls:1,synthetic:profile.provider==='fake'};
    for(const patch of c.patches){let target=source;for(const key of patch.path.slice(0,-1))target=target[key];target[patch.path.at(-1)]=structuredClone(patch.value);}
    if(c.error)assert.throws(()=>bind_embedding_batch(source,profile,{expected_items:c.expected_items}),e=>e.code===c.error,c.id);
    else {const result=bind_embedding_batch(source,profile,{expected_items:c.expected_items});assert.deepEqual(result.profile,profile,c.id);assert.deepEqual(result.usage,source.usage,c.id);assert.ok(Object.isFrozen(result));assert.ok(Object.isFrozen(result.vectors[0]));}
  }
});
