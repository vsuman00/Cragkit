import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {QdrantSearchStore,point_id,compile_filter} from '../dist/qdrant.js';
import {ExecutionLedger,BudgetExhausted} from '../dist/execution.js';
import {InvalidRequest,UnsupportedCapability,IntegrityViolation,DeadlineExceeded,IndexNotReady,ProviderUnavailable} from '../dist/errors.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_candidates.json',import.meta.url),'utf8'));
const config={backend_namespace:'fixture-local',physical_collection:'cragkit_qc_r1',collection_incarnation:'inc-1',dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse};
const scope=fixture.trusted_scope;
const request={query:'synthetic',collection:'docs',limits:{max_candidates:4}};
const dense=Array.from({length:1536},(_,i)=>i===0?1:0);
const sparse=fixture.vectors.sparse_manual;
const deadline=()=>performance.now()/1000+3;
const bytes=v=>Buffer.from(JSON.stringify(v));
function payload(){return {...structuredClone(fixture.base_payload),dense_profile:structuredClone(config.dense_profile),sparse_profile:structuredClone(config.sparse_profile)};}
function point(){return {id:point_id(fixture.point_id_cases[0].tuple),score:0.75,payload:payload()};}
function transport(points=[point()]){
  return {bounded_responses:true,cancellation_safe:true,calls:[],async request(method,path,options){
    this.calls.push({method,path,options,body:options.body&&JSON.parse(Buffer.from(options.body).toString())});
    if(path==='/')return bytes({version:'1.20.0'});
    if(path==='/cluster')return bytes({status:'ok',result:{status:'disabled'}});
    if(method==='GET')return bytes({status:'ok',result:{config:{params:{vectors:{dense:{size:1536,distance:'Cosine'}},sparse_vectors:{sparse:{}},replication_factor:1,write_consistency_factor:1}}}});
    return bytes({status:'ok',result:{points}});
  }};
}
function options(extra={}){return {scope,dense,branch_limits:{dense:2},ledger:new ExecutionLedger({limits:{max_candidates:4},deadline:deadline()}),deadline:deadline(),...extra};}
async function ready(t=transport()){const store=new QdrantSearchStore(config,t);await store.initialize({deadline:deadline()});return {store,t};}

test('QC-r1 UUID fixtures preserve literal Unicode and escaping',()=>{
  for(const c of fixture.point_id_cases)assert.equal(point_id(c.tuple),c.expected_uuid);
  assert.notEqual(point_id(fixture.point_id_cases[2].tuple),point_id(fixture.point_id_cases[3].tuple));
  assert.throws(()=>point_id([...fixture.point_id_cases[0].tuple, 'extra']),InvalidRequest);
  const collection=structuredClone(fixture.point_id_cases[0].tuple);collection[5]='x'.repeat(129);assert.throws(()=>point_id(collection),InvalidRequest);
  collection[5]='雪'.repeat(43);assert.throws(()=>point_id(collection),InvalidRequest);
  collection[5]='x'.repeat(128);assert.match(point_id(collection),/^[a-f0-9-]{36}$/);
  const sparseId=structuredClone(fixture.point_id_cases[0].tuple);sparseId[11]='  ';assert.throws(()=>point_id(sparseId),InvalidRequest);
});
test('scope/filter before branch limit; nominations are immutable and text-free',async()=>{
  const {store,t}=await ready();const opts=options({sparse,branch_limits:{dense:2,sparse:1}});
  const out=await store.search_candidates(request,opts);
  assert.equal(out.length,2);assert.equal(out[0].verification,'UNVERIFIED');assert.equal(out[1].score_kind,'dot_product');
  assert.ok(Object.isFrozen(out));assert.ok(Object.isFrozen(out[0].payload.dense_profile));
  assert.equal(out[0].payload.revision_id,'rev-1');assert.ok(!('text'in out[0].payload));
  assert.deepEqual(t.calls[3].body.filter,fixture.scope_filter);assert.equal(t.calls[4].body.using,'sparse');
  assert.ok(Array.isArray(t.calls[3].body.with_payload));assert.equal(t.calls[3].body.with_vector,false);
  assert.equal(opts.ledger.snapshot().candidates,3);assert.equal(opts.ledger.snapshot().provider_calls,0);assert.equal(opts.ledger.snapshot().pending,0);
  await store.close();
});
test('empty grants retain principal scope; nested OR cannot escape scope',()=>{
  const filter={op:'or',filters:[{op:'eq',field:'kind',value:'guide'},{op:'in',field:'tag',values:['reference']}]};
  const out=compile_filter({...request,required_filters:[filter]},{...scope,grant_ids:[]});
  assert.deepEqual(out.must.slice(0,3),fixture.empty_grants_filter.must);assert.equal(out.must[3].should.length,2);
});
test('unsupported and malformed filters dispatch nothing',async()=>{
  const {store,t}=await ready();
  for(const f of [{op:'ne',field:'kind',value:'x'},{op:'eq',field:'tag',value:true},{op:'in',field:'tag',values:[1]}])await assert.rejects(store.search_candidates({...request,required_filters:[f]},options()),UnsupportedCapability);
  await assert.rejects(store.search_candidates({...request,required_filters:[{op:'eq',field:'unknown',value:'x'}]},options()),InvalidRequest);
  assert.equal(t.calls.length,3);await store.close();
});
test('all malformed successful replica responses fail atomically',async()=>{
  const mutations=[['foreign_scope',p=>p.payload.tenant_id='other'],['wrong_collection',p=>p.payload.collection='other'],['bad_span',p=>p.payload.end_byte=0],['bad_digest',p=>p.payload.source_sha256='bad'],['same_id_wrong_model',p=>p.payload.dense_profile.model='other'],['wrong_uuid',p=>p.id='00000000-0000-5000-8000-000000000000'],['payload_text_injection',p=>p.payload.text='SYNTHETIC INJECTION'],['cosine_outside_range',p=>p.score=1.01],['no_replica_acl',p=>{p.payload.principal_ids=[];p.payload.grant_ids=[];}]];
  for(const [id,mutate] of mutations){const p=point();mutate(p);const {store}=await ready(transport([p]));const opts=options();await assert.rejects(store.search_candidates(request,opts),IntegrityViolation,id);assert.equal(opts.ledger.snapshot().pending,0);await store.close();}
  for(const points of [[point(),point()],[point(),point(),point()]]){const {store}=await ready(transport(points));await assert.rejects(store.search_candidates(request,options()),IntegrityViolation);await store.close();}
});
test('required metadata checks, stale ACL nomination and empty result preserve limits',async()=>{
  const stale=point();stale.payload.authorization_revision='auth-0';const {store}=await ready(transport([stale]));
  assert.equal((await store.search_candidates(request,options()))[0].payload.authorization_revision,'auth-0');
  await assert.rejects(store.search_candidates({...request,required_filters:[{op:'eq',field:'tag',value:'missing'}]},options()),IntegrityViolation);await store.close();
  const empty=await ready(transport([]));assert.deepEqual(await empty.store.search_candidates(request,options()),[]);await empty.store.close();
});
test('vector validity, branch admission, ledger exhaustion and unchecked objects reject pre-query',async()=>{
  const {store,t}=await ready();
  for(const bad of [{indices:[7,2],values:[1,1]},{indices:[2,2],values:[1,1]},{indices:[2],values:[0]},{indices:[2],values:[-1]},{indices:[2],values:[1e300]},{indices:[2],values:[1e-300]}])await assert.rejects(store.search_candidates(request,options({sparse:bad,branch_limits:{dense:1,sparse:1}})),InvalidRequest);
  await assert.rejects(store.search_candidates(request,options({dense:[1,0]})),InvalidRequest);
  await assert.rejects(store.search_candidates(request,options({branch_limits:{dense:3,sparse:1}})),InvalidRequest);
  const ledger=new ExecutionLedger({limits:{max_candidates:1},deadline:deadline()});await assert.rejects(store.search_candidates(request,options({ledger})),BudgetExhausted);
  const cyclic={...request};cyclic.required_filters=[cyclic];await assert.rejects(store.search_candidates(cyclic,options()),InvalidRequest);
  const accessor={...request};Object.defineProperty(accessor,'query',{get(){throw Error('secret');},enumerable:true});await assert.rejects(store.search_candidates(accessor,options()),InvalidRequest);
  assert.equal(t.calls.length,3);await store.close();
});
test('explicit initialization rejects incompatible version and distributed profile',async()=>{
  const unready=new QdrantSearchStore(config,transport());await assert.rejects(unready.search_candidates(request,options()),IndexNotReady);await unready.close();
  const t=transport();t.request=async()=>bytes({version:'1.19.0'});const store=new QdrantSearchStore(config,t);await assert.rejects(store.initialize({deadline:deadline()}),UnsupportedCapability);await store.close();
  assert.throws(()=>new QdrantSearchStore(config,{request(){}}),UnsupportedCapability);
});
test('transport capability/configuration failures preserve redacted typed errors',async()=>{
  for(const ErrorType of [UnsupportedCapability,InvalidRequest]){
    const t=transport();const original=t.request;t.request=async function(m,p,o){if(m==='POST'){const error=new ErrorType();error.message='private transport credential';throw error;}return original.call(this,m,p,o);};
    const {store}=await ready(t);const opts=options();await assert.rejects(store.search_candidates(request,opts),e=>e instanceof ErrorType&&!e.message.includes('private'));assert.equal(opts.ledger.snapshot().pending,0);await store.close();
  }
});
test('valid unknown profiles are unsupported while malformed descriptors are invalid',()=>{
  assert.throws(()=>new QdrantSearchStore({...config,dense_profile:{...config.dense_profile,model:'unknown-model'}},transport()),UnsupportedCapability);
  assert.throws(()=>new QdrantSearchStore({...config,sparse_profile:{...config.sparse_profile,revision:'other'}},transport()),UnsupportedCapability);
  assert.throws(()=>new QdrantSearchStore({...config,dense_profile:{...config.dense_profile,dimensions:true}},transport()),InvalidRequest);
  assert.throws(()=>new QdrantSearchStore({...config,sparse_profile:{...config.sparse_profile,extra:'bad'}},transport()),InvalidRequest);
});
test('initialization long deadlines avoid timer overflow and unsafe external deadlines never query',async()=>{
  const t=transport();const original=t.request;
  t.request=async function(m,p,o){if(p==='/'){await new Promise(resolve=>setTimeout(resolve,10));assert.equal(o.signal.aborted,false);}return original.call(this,m,p,o);};
  const store=new QdrantSearchStore(config,t);
  try {
    await assert.rejects(store.initialize({deadline:Number.MAX_SAFE_INTEGER+1}),InvalidRequest);assert.equal(t.calls.length,0);
    await store.initialize({deadline:performance.now()/1000+3000000});
    for(const value of [NaN,Infinity,-Infinity,Number.MAX_SAFE_INTEGER+1,-Number.MAX_SAFE_INTEGER-1])await assert.rejects(store.search_candidates(request,options({deadline:value})),InvalidRequest);
    assert.equal(t.calls.length,3);
  }finally{await store.close();}
});
test('raw parser rejects duplicate keys, invalid UTF8, nonfinite and excessive nesting',async()=>{
  for(const raw of [Buffer.from('{"result":{},"result":{"points":[]}}'),Buffer.from([0xff]),Buffer.from('{"result":{"points":[{"score":1e9999}]}}'),Buffer.from('['.repeat(34)+'0'+']'.repeat(34))]){
    const t=transport();const original=t.request;t.request=async function(m,p,o){return m==='POST'?raw:original.call(this,m,p,o);};const {store}=await ready(t);await assert.rejects(store.search_candidates(request,options()),IntegrityViolation);await store.close();
  }
});
test('QC semantic integer JSON literals remain equivalent in metadata and full descriptors',async()=>{
  const t=transport();const original=t.request;
  t.request=async function(m,p,o){const raw=await original.call(this,m,p,o);return Buffer.from(Buffer.from(raw).toString().replace(/"dimensions":1536/g,'"dimensions":1536.0').replace(/"size":1536/g,'"size":1536.0').replace(/"start_byte":0/g,'"start_byte":0.0').replace(/"end_byte":4/g,'"end_byte":4.0').replace(/"replication_factor":1/g,'"replication_factor":1.0').replace(/"write_consistency_factor":1/g,'"write_consistency_factor":1.0'));};
  const {store}=await ready(t);assert.equal((await store.search_candidates(request,options()))[0].payload.end_byte,4);await store.close();
});
test('malformed success envelopes, multivectors and float32 roundoff have explicit outcomes',async()=>{
  for(const [path,mutate,error]of [['/',r=>delete r.version,IntegrityViolation],['/cluster',r=>delete r.status,IntegrityViolation],['/collections/cragkit_qc_r1',r=>r.result.config.params.vectors.dense.multivector_config={},UnsupportedCapability]]){
    const t=transport();const original=t.request;t.request=async function(m,p,o){const r=JSON.parse(Buffer.from(await original.call(this,m,p,o)).toString());if(p===path)mutate(r);return bytes(r);};
    const store=new QdrantSearchStore(config,t);await assert.rejects(store.initialize({deadline:deadline()}),error);await store.close();
  }
  const p=point();p.score=1.0000001;const {store}=await ready(transport([p]));assert.equal((await store.search_candidates(request,options()))[0].score,1.0000001);await store.close();
});
test('cross-branch payload contradictions discard every nomination and settle admission',async()=>{
  const t=transport();const original=t.request;let queries=0;
  t.request=async function(m,p,o){if(m==='POST'&&++queries===2){const changed=point();changed.payload.authorization_revision='auth-0';return bytes({status:'ok',result:{points:[changed]}});}return original.call(this,m,p,o);};
  const {store}=await ready(t);const opts=options({sparse,branch_limits:{dense:1,sparse:1}});await assert.rejects(store.search_candidates(request,opts),IntegrityViolation);assert.equal(opts.ledger.snapshot().pending,0);await store.close();
});
test('dense-only profile retains absent sparse identity and rejects sparse capability',async()=>{
  const p=point();p.payload.sparse_profile=null;p.payload.sparse_profile_id='';p.id=point_id(fixture.point_id_cases.find(c=>c.id==='dense_only').tuple);
  const t=transport([p]);const original=t.request;t.request=async function(m,path,o){const raw=await original.call(this,m,path,o);if(m==='GET'&&path.startsWith('/collections/')){const r=JSON.parse(Buffer.from(raw).toString());r.result.config.params.sparse_vectors={};return bytes(r);}return raw;};
  const store=new QdrantSearchStore({...config,sparse_profile:null},t);await store.initialize({deadline:deadline()});assert.equal((await store.search_candidates(request,options()))[0].payload.sparse_profile_id,'');await assert.rejects(store.search_candidates(request,options({sparse,branch_limits:{dense:1,sparse:1}})),UnsupportedCapability);await store.close();
});
test('midflight cancellation, shared deadline and close settle reservations without closing borrowed transport',async()=>{
  for(const mode of ['cancel','deadline','close']){
    const t=transport();let entered;const started=new Promise(r=>entered=r);let transportClosed=false;t.close=()=>{transportClosed=true;};const original=t.request;
    t.request=async function(m,p,o){if(m!=='POST')return original.call(this,m,p,o);entered();return new Promise((_,reject)=>{o.signal.addEventListener('abort',()=>reject(Error('private raw failure')),{once:true});});};
    const {store}=await ready(t);const controller=new AbortController();const opts=options({signal:controller.signal,deadline:mode==='deadline'?performance.now()/1000+0.03:deadline()});
    const pending=store.search_candidates(request,opts);const assertion=assert.rejects(pending,mode==='deadline'?DeadlineExceeded:e=>e.name==='AbortError');await started;
    await assert.rejects(store.search_candidates(request,options()),ProviderUnavailable);
    if(mode==='cancel')controller.abort();if(mode==='close')await store.close();await assertion;
    assert.equal(opts.ledger.snapshot().pending,0);assert.equal(transportClosed,false);await store.close();
    await assert.rejects(store.search_candidates(request,options()),e=>e instanceof InvalidRequest||e instanceof IndexNotReady);
  }
});
