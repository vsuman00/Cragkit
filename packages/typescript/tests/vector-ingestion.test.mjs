import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import * as vector from '../dist/vector-ingestion.js';
import * as lexical from '../dist/ingestion.js';
import {PoolResource,parse_pool_config,now} from '../dist/postgres-pool.js';
import {EXPECTED_HISTORY,_CATALOG_SQL,_HISTORY_SQL,_COLLECTION_SQL} from '../dist/postgres-session.js';
import {EmbeddingAdapter,FAKE_PROFILE,OPENAI_PROFILE} from '../dist/embeddings.js';
import {parse_scope} from '../dist/contracts.js';
import {DeadlineExceeded,EmbeddingProfileMismatch,IndexNotReady,IntegrityViolation,InvalidRequest,ProviderUnavailable,UnauthorizedScope,UnsupportedCapability} from '../dist/errors.js';

export const oracle=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/vector_generations.json',import.meta.url),'utf8'));
export const scope=(changes={})=>parse_scope({tenant_id:'tenant',principal_id:'principal',authorization_revision:'auth',grant_ids:['unassigned-group'],...changes});
export const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};
export class Client {
  status='I';calls=[];releases=[];staged=[];published=[];document=[];revision=[];generation=[];jobs=[];manifest=[];vectors={};
  role=[[true]];catalog=[[true]];history=EXPECTED_HISTORY;collection=[['0.1','native_fts.v1']];capability=[[true]];
  profile=[[...Object.values(FAKE_PROFILE),'chunk_vectors_fake_1536']];grants=[[true]];missing;counts;vectorCounts;
  readyRows=[[1]];casRows=[[1]];jobRows=[[1]];commits=0;rollbacks=0;gucs=null;failure;
  getTransactionStatus(){return this.status;}
  release(destroy){this.releases.push(destroy);}
  async query({text,values}) {
    this.calls.push([text,values]);
    if(this.failure&&text.includes(this.failure[0]))throw this.failure[1];
    if(text==='BEGIN'){this.before=structuredClone([this.staged,this.published,this.document,this.revision,this.generation,this.jobs,this.manifest,this.vectors]);this.status='T';}
    if(text==='COMMIT'){this.commits++;this.status='I';this.gucs=null;}
    if(text==='ROLLBACK'){[this.staged,this.published,this.document,this.revision,this.generation,this.jobs,this.manifest,this.vectors]=this.before;this.rollbacks++;this.status='I';this.gucs=null;}
    const responses=new Map([
      [lexical._WRITER_ROLE_SQL,this.role],[_CATALOG_SQL,this.catalog],[_HISTORY_SQL,this.history],[_COLLECTION_SQL,this.collection],
      [vector._VECTOR_CAPABILITY_SQL,this.capability],[vector._SETUP_HISTORY_SQL,vector.EXPECTED_VECTOR_HISTORY],[vector._PROFILE_SQL,this.profile],
      [vector._VECTOR_JOB_SQL,this.jobs],[lexical._DOCUMENT_LOCK_SQL,this.document],[vector._VECTOR_GENERATION_SQL,this.generation],
      [vector._VECTOR_REVISION_SQL,this.revision],[vector._MANIFEST_SQL,this.manifest],[vector._GRANTS_SQL,this.grants],
      [vector._MISSING_SQL,this.missing??this.manifest.filter(row=>!Object.hasOwn(this.vectors,row[0])).map(row=>[row[0]])],
      [vector._VECTOR_COUNTS_SQL,this.vectorCounts??[[Object.keys(this.vectors).length]]],
      [lexical._COUNTS_SQL,this.counts??[[this.manifest.length,this.manifest.length]]],
    ]);
    if(responses.has(text))return {rows:responses.get(text)};
    if(text.includes("set_config('cragkit.tenant_id'"))this.gucs=values;
    if(/^(INSERT|UPDATE) /.test(text.trimStart())){
      this.staged.push([text,structuredClone(values)]);
      if(text.startsWith('INSERT INTO cragkit.documents')){if(!this.document.length)this.document=[[null,false,values[3]]];return {rows:[['document']]};}
      if(text.startsWith('INSERT INTO cragkit.ingestion_jobs'))this.jobs=[[values[4],values[5],'running',values[2],1]];
      if(text.startsWith('INSERT INTO cragkit.document_revisions'))this.revision=[[values[4],values[7],values[5],values[8],values[6]]];
      if(text.startsWith('INSERT INTO cragkit.index_generations'))this.generation=[[values[3],'staging',values.at(-1),FAKE_PROFILE.profile_id,values[5],'native_fts.v1']];
      if(text===lexical._CHUNKS_SQL)this.manifest=JSON.parse(values.at(-1)).map(row=>[row.chunk_id,row.ordinal,row.start_byte,row.end_byte,row.text,row.text_sha256,row.metadata]);
      if(text===vector._VECTOR_INSERT_SQL)for(const row of JSON.parse(values.at(-1)))this.vectors[row.chunk_id]=row.embedding;
      if(text.startsWith('UPDATE cragkit.ingestion_jobs')&&text.includes('attempt_count'))this.jobs[0][4]++;
      if(text.startsWith('UPDATE cragkit.index_generations')){if(this.readyRows.length)this.generation[0][1]='ready';return {rows:this.readyRows};}
      if(text.startsWith('UPDATE cragkit.documents')){if(this.casRows.length){this.document=[[values[0],false,values.at(-1)]];this.published.push(structuredClone(values));}return {rows:this.casRows};}
      if(text.startsWith('UPDATE cragkit.ingestion_jobs')&&text.includes("state='succeeded'")){if(this.jobRows.length)this.jobs[0][2]='succeeded';return {rows:this.jobRows};}
      return {rows:[[1]]};
    }
    return {rows:[]};
  }
}
export function fixture(options={}) {
  const client=new Client();const pool={leases:0,async connect(){this.leases++;return client;},async end(){assert.fail('borrowed pool closed');}};
  const config=parse_pool_config({host:'host.invalid',dbname:'synthetic',user:'writer',sslrootcert:'/synthetic/ca',passfile:'/synthetic/pass',release_timeout:0.03,close_timeout:0.1});
  const resource=new PoolResource(config,{pool});
  const transport={calls:[],change:null,failureAt:null,block:false,entered:deferred(),async send(body,options){
    assert.equal(client.status,'I');assert.equal(pool.leases,client.releases.length,'provider outside lease');
    const payload=JSON.parse(Buffer.from(body).toString());this.calls.push(payload);
    if(this.failureAt===this.calls.length)throw Error('private transport secret');
    if(this.block){this.entered.resolve();await new Promise((_,reject)=>{if(options.signal.aborted)reject(options.signal.reason);else options.signal.addEventListener('abort',()=>reject(options.signal.reason),{once:true});});}
    const response={model:FAKE_PROFILE.model,data:payload.input.map((_,index)=>({index,embedding:[1,...new Array(1535).fill(0)]}))};
    this.change?.(response);return Buffer.from(JSON.stringify(response));
  }};
  const adapter=new EmbeddingAdapter(transport.send.bind(transport),{name:'fake-byte-v1',count:text=>Buffer.byteLength(text)}, {limits:options.limits});
  const indexer=new vector.PostgresVectorIndexer(resource,options.authorize??(async()=>true),adapter,options.indexerOptions);
  return {client,pool,resource,transport,adapter,indexer};
}
export const input=(changes={})=>({collection:'collection',document_id:'document',intent_id:'intent',source_locator:'synthetic:source',scope:scope(),deadline:now()+2,...changes});
export const stage=(indexer,changes={},source='synthetic source')=>indexer.stage(source,input(changes));
const clean=async fixture=>{assert.equal(fixture.pool.leases,fixture.client.releases.length);await fixture.resource.close();};

test('VG-r1 staging commits profile-bound vectors without readiness or pointer writes',async()=>{
  const f=fixture();const receipt=await stage(f.indexer);assert.equal(receipt.embedding_profile,oracle.profile.profile_id);assert.equal(receipt.chunk_count,1);
  assert.equal(receipt.provider_calls,1);assert.equal(receipt.usage.length,1);assert.equal(receipt.usage[0].cost_usd,0);assert.ok(Object.isFrozen(receipt));assert.ok(Object.isFrozen(receipt.usage));
  assert.equal(f.client.generation[0][1],'staging');assert.deepEqual(f.client.published,[]);assert.ok(!f.client.calls.some(([sql])=>sql.includes("SET status='ready'")));
  const scoped=f.client.calls.findIndex(([sql])=>sql.includes("set_config('cragkit.tenant_id'"));const job=f.client.calls.findIndex(([sql])=>sql===vector._VECTOR_JOB_SQL);assert.ok(scoped>=0&&scoped<job);
  assert.deepEqual(f.transport.calls[0].input,['synthetic source']);await clean(f);
});
test('VG-r1 interrupted-stage and missing-only-resume retain successful batches with per-invocation usage',async()=>{
  const f=fixture({limits:{max_items:1}});f.transport.failureAt=2;const source='first\n\nsecond\n\nthird',changes={canonical_options:{target_bytes:6}};
  await assert.rejects(stage(f.indexer,changes,source),ProviderUnavailable);assert.equal(Object.keys(f.client.vectors).length,1);assert.deepEqual(f.client.published,[]);
  const first=f.transport.calls[0].input;f.transport.failureAt=null;const receipt=await stage(f.indexer,changes,source);
  assert.equal(receipt.chunk_count,3);assert.equal(Object.keys(f.client.vectors).length,3);assert.equal(receipt.provider_calls,2);assert.equal(receipt.usage.length,2);
  assert.ok(f.transport.calls.slice(2).every(call=>JSON.stringify(call.input)!==JSON.stringify(first)));await clean(f);
});
test('VG-r1 changed-payload rejects while identical staged replay spends no provider calls',async()=>{
  const f=fixture();const first=await stage(f.indexer),second=await stage(f.indexer);assert.equal(first.generation_id,second.generation_id);assert.equal(second.provider_calls,0);assert.deepEqual(second.usage,[]);
  await assert.rejects(stage(f.indexer,{},'changed source'),InvalidRequest);assert.equal(f.transport.calls.length,1);await clean(f);
});
for(const [id,mutate,kind] of [
  ['wrong-model-same-dimension',r=>r.model='other-model',EmbeddingProfileMismatch],['missing',r=>r.data=[],ProviderUnavailable],
  ['dimension',r=>r.data[0].embedding=[1],EmbeddingProfileMismatch],['normalization',r=>r.data[0].embedding[0]=2,ProviderUnavailable],
  ['duplicate',r=>r.data.push(r.data[0]),ProviderUnavailable],['unsafe-index',r=>r.data[0].index=Number.MAX_SAFE_INTEGER+1,ProviderUnavailable],
])test(`invalid provider batch ${id} never writes vectors`,async()=>{const f=fixture();f.transport.change=mutate;await assert.rejects(stage(f.indexer),kind);assert.deepEqual(f.client.vectors,{});assert.deepEqual(f.client.published,[]);await clean(f);});
for(const [field,value] of [['capability',[[false]]],['profile',[]],['profile',[[FAKE_PROFILE.profile_id,'fake','other-model',1536,'fake-byte-v1','l2','chunk_vectors_fake_1536']]]])test(`capability/exact model-space fails before provider ${field} ${JSON.stringify(value)}`,async()=>{const f=fixture();f.client[field]=value;await assert.rejects(stage(f.indexer),UnsupportedCapability);assert.equal(f.transport.calls.length,0);await clean(f);});
for(const allowed of [false,null,1,'yes'])test(`exact write authorization ${allowed} precedes DB/provider/canonicalization`,async()=>{const f=fixture({authorize:async()=>allowed});await assert.rejects(stage(f.indexer,{canonical_options:{token_counter:()=>assert.fail('unauthorized canonicalization')}}),UnauthorizedScope);assert.equal(f.pool.leases,0);assert.equal(f.transport.calls.length,0);await clean(f);});
for(const [column,value] of [[0,'foreign-chunk'],[1,Number.MAX_SAFE_INTEGER+1],[2,99],[3,Number.MAX_SAFE_INTEGER+1],[4,'corrupt private text'],[5,'bad-digest'],[6,{oversized_split:true,token_count:null,tokenizer_id:null}]])test(`mixed-manifest persisted corruption column ${column} precedes provider`,async()=>{const f=fixture();await stage(f.indexer);f.client.vectors={};f.client.manifest[0][column]=value;await assert.rejects(stage(f.indexer),IntegrityViolation);assert.equal(f.transport.calls.length,1);await clean(f);});
for(const mode of ['abort','deadline'])test(`provider ${mode} releases admission and leases`,async()=>{
  const f=fixture();f.transport.block=true;const controller=new AbortController();const pending=stage(f.indexer,{signal:controller.signal,deadline:now()+(mode==='deadline'?0.03:2)});await f.transport.entered.promise;if(mode==='abort')controller.abort('private reason');
  await assert.rejects(pending,mode==='deadline'?DeadlineExceeded:error=>error.name==='AbortError'&&!String(error).includes('private'));assert.deepEqual(f.client.vectors,{});f.transport.block=false;await stage(f.indexer);await clean(f);
});
test('inflight vector indexer has zero waiting queue',async()=>{const f=fixture();f.transport.block=true;const controller=new AbortController();const pending=stage(f.indexer,{signal:controller.signal});await f.transport.entered.promise;await assert.rejects(stage(f.indexer),IndexNotReady);assert.equal(f.transport.calls.length,1);controller.abort();await assert.rejects(pending,error=>error.name==='AbortError');await clean(f);});
for(const [key,value] of [['max_batches',0],['max_batches',129],['max_batches',true],['max_attempts',0],['max_attempts',9],['max_attempts',true]])test(`indexer bound ${key}=${value}`,()=>assert.throws(()=>fixture({indexerOptions:{[key]:value}}),InvalidRequest));
test('entire workload batch admission precedes database and provider',async()=>{const f=fixture({limits:{max_items:1},indexerOptions:{max_batches:1}});await assert.rejects(stage(f.indexer,{canonical_options:{target_bytes:6}},'first\n\nsecond'),InvalidRequest);assert.equal(f.pool.leases,0);assert.equal(f.transport.calls.length,0);await clean(f);});
test('resume attempt cap prevents additional provider dispatch',async()=>{const f=fixture({indexerOptions:{max_attempts:1}});f.transport.failureAt=1;await assert.rejects(stage(f.indexer),ProviderUnavailable);f.transport.failureAt=null;await assert.rejects(stage(f.indexer),IndexNotReady);assert.equal(f.transport.calls.length,1);await clean(f);});
test('colliding tenant document IDs retain distinct identities and scoped queries',async()=>{const a=fixture(),b=fixture();const x=await stage(a.indexer),y=await stage(b.indexer,{scope:scope({tenant_id:'other-tenant'})});for(const key of ['generation_id','revision_id','payload_sha256'])assert.notEqual(x[key],y[key]);for(const [f,tenant] of [[a,'tenant'],[b,'other-tenant']]){for(const [sql,params] of f.client.calls)if([vector._MISSING_SQL,vector._MANIFEST_SQL,vector._VECTOR_JOB_SQL,vector._VECTOR_INSERT_SQL].includes(sql))assert.equal(params[0],tenant);await clean(f);}});
for(const [id,document,kind] of [['tombstoned',['old',true,'auth'],UnauthorizedScope],['revoked-grant',['old',false,'revoked'],UnauthorizedScope],['stale-cas',['newer-generation',false,'auth'],IndexNotReady]])test(`VG-r1 ${id} blocks resume provider`,async()=>{const f=fixture();await stage(f.indexer);f.client.vectors={};f.client.document=[document];await assert.rejects(stage(f.indexer),kind);assert.equal(f.transport.calls.length,1);await clean(f);});
test('succeeded intent replay verifies ready complete manifest without provider',async()=>{const f=fixture();const first=await stage(f.indexer);f.client.jobs[0][2]='succeeded';f.client.generation[0][1]='ready';f.client.document=[[first.generation_id,false,'auth']];const result=await stage(f.indexer);assert.equal(result.replayed,true);assert.equal(result.provider_calls,0);assert.deepEqual(result.usage,[]);f.client.vectorCounts=[[0]];await assert.rejects(stage(f.indexer),IntegrityViolation);assert.equal(f.transport.calls.length,1);await clean(f);});
test('unprovisioned hosted profile rejects constructor without DB/provider',async()=>{const f=fixture();const adapter=new EmbeddingAdapter(async()=>assert.fail('provider'),{name:OPENAI_PROFILE.tokenizer,count:()=>1},{profile:OPENAI_PROFILE});assert.throws(()=>new vector.PostgresVectorIndexer(f.resource,async()=>true,adapter),UnsupportedCapability);assert.equal(f.pool.leases,0);await clean(f);});
for(const limits of [{max_batch_bytes:8},{max_batch_tokens:8}])test(`independent byte/token batching ${JSON.stringify(limits)}`,async()=>{const f=fixture({limits});const result=await stage(f.indexer,{canonical_options:{target_bytes:6}},'first\n\nsecond');assert.equal(result.chunk_count,2);assert.equal(f.transport.calls.length,2);assert.ok(f.transport.calls.every(call=>call.input.length===1));await clean(f);});
for(const mode of ['abort','deadline'])test(`authorizer ${mode} is bounded before lease`,async()=>{const entered=deferred();const f=fixture({authorize:async()=>{entered.resolve();await new Promise(()=>{});}});const controller=new AbortController();const pending=stage(f.indexer,{signal:controller.signal,deadline:now()+(mode==='deadline'?0.02:2)});await entered.promise;if(mode==='abort')controller.abort();await assert.rejects(pending,mode==='deadline'?DeadlineExceeded:error=>error.name==='AbortError');assert.equal(f.pool.leases,0);await clean(f);});
test('bytes metadata and canonical options snapshot before authorization await',async()=>{const gate=deferred(),entered=deferred();const f=fixture({authorize:async()=>{entered.resolve();await gate.promise;return true;}});const source=Buffer.from('synthetic source'),metadata={nested:[1]},canonical_options={target_bytes:2048};const pending=stage(f.indexer,{metadata,canonical_options},source);await entered.promise;source.fill(0);metadata.nested[0]=2;canonical_options.target_bytes=0;gate.resolve();await pending;assert.deepEqual(f.transport.calls[0].input,['synthetic source']);await clean(f);});
for(const [id,changes] of [
 ['option-accessor',()=>Object.defineProperty(input(),'deadline',{enumerable:true,get(){assert.fail('getter invoked');}})],
 ['option-symbol',()=>({...input(),[Symbol('hidden')]:1})],['option-prototype',()=>Object.assign(Object.create({inherited:1}),input())],
 ['canonical-accessor',()=>input({canonical_options:{get target_bytes(){assert.fail('getter invoked');}}})],
 ['metadata-accessor',()=>input({metadata:{get value(){assert.fail('getter invoked');}}})],
 ['metadata-symbol',()=>input({metadata:{[Symbol('hidden')]:1}})],['metadata-prototype',()=>input({metadata:new Date()})],
 ['metadata-sparse-array',()=>input({metadata:{values:new Array(2)}})],
])test(`hostile JS boundary ${id} fails before lease/getter/provider`,async()=>{const f=fixture();await assert.rejects(f.indexer.stage('synthetic source',changes()),InvalidRequest);assert.equal(f.pool.leases,0);assert.equal(f.transport.calls.length,0);await clean(f);});

test('VG-r1 baseline and replacement sources stage the shared canonical fixture',async()=>{
  assert.equal(oracle.revision,'VG-r1');
  for(const source of [oracle.baseline_source,oracle.replacement_source]){
    const f=fixture();const receipt=await stage(f.indexer,{metadata:oracle.metadata,canonical_options:oracle.canonical_options},source);
    assert.equal(receipt.chunk_count,f.client.manifest.length);assert.equal(Object.keys(f.client.vectors).length,receipt.chunk_count);
    assert.deepEqual(f.client.published,[]);assert.equal(f.client.generation[0][1],'staging');await clean(f);
  }
});
for(const missing of [[['foreign-chunk']],[['duplicate'],['duplicate']]])test(`invalid missing-vector manifest rejects before provider ${JSON.stringify(missing)}`,async()=>{
  const f=fixture();await stage(f.indexer);f.client.vectors={};f.client.missing=missing;
  await assert.rejects(stage(f.indexer),IntegrityViolation);assert.equal(f.transport.calls.length,1);await clean(f);
});

test('native bigint attempt counter decimal string resumes safely',async()=>{
  const f=fixture();await stage(f.indexer);f.client.jobs[0][4]='1';f.client.vectors={};
  const receipt=await stage(f.indexer);assert.equal(receipt.provider_calls,1);assert.equal(f.transport.calls.length,2);await clean(f);
});
for(const counter of ['9007199254740992','1.0','-1',0])test(`malformed or unsafe persisted attempt counter ${counter} prevents provider`,async()=>{
  const f=fixture();await stage(f.indexer);f.client.jobs[0][4]=counter;f.client.vectors={};
  await assert.rejects(stage(f.indexer),IndexNotReady);assert.equal(f.transport.calls.length,1);await clean(f);
});
