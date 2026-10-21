import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { spawnSync } from 'node:child_process';
import { PostgresSession, EXPECTED_HISTORY, _ROLE_SQL, _CATALOG_SQL, _HISTORY_SQL, _COLLECTION_SQL, _SCOPE_SQL } from '../dist/postgres-session.js';
import { PostgresRetriever } from '../dist/retrieval.js';
import { parse_request, parse_scope } from '../dist/contracts.js';
import { now } from '../dist/postgres-pool.js';
import { IntegrityViolation, InvalidRequest, UnauthorizedScope, UnsupportedCapability, DeadlineExceeded, ContextBudgetTooSmall, ProviderUnavailable } from '../dist/errors.js';
const sha=value=>createHash('sha256').update(value).digest('hex');
const scope=()=>parse_scope({tenant_id:'tenant',principal_id:'principal',authorization_revision:'auth',grant_ids:['grant']});
const request=()=>parse_request({request_id:'request',query:'Café',collection:'collection'});
const candidate=()=>({tenant_id:'tenant',collection:'collection',document_id:'document',revision_id:'revision',generation_id:'generation',chunk_id:'chunk',start_byte:0,end_byte:Buffer.byteLength('Café🙂'),text_sha256:sha('Café🙂'),score:1});
const row=()=>['tenant','collection','document','revision','generation','chunk',sha('Café🙂'),Buffer.byteLength('Café🙂'),'Café🙂',0,Buffer.byteLength('Café🙂'),Buffer.byteLength('Café🙂'),'Café🙂',sha('Café🙂'),'synthetic:source','native_fts.v1',true];
class Client {
  status='I';calls=[];sourceRows=[row()];candidates=[candidate()];destroyed=[];failure;block;
  getTransactionStatus(){return this.status;}
  release(destroy){this.destroyed.push(destroy);}
  async query(query){
    this.calls.push(query);assert.equal(query.rowMode,'array');
    if(this.failure&&query.text.includes(this.failure.match))throw this.failure.error;
    if(this.block&&query.text.includes(this.block.match)){this.block.entered?.();await this.block.promise;}
    if(query.text.startsWith('BEGIN'))this.status='T';if(query.text==='ROLLBACK')this.status='I';
    if(query.text===_ROLE_SQL||query.text===_CATALOG_SQL)return {rows:[[true]]};
    if(query.text===_HISTORY_SQL)return {rows:EXPECTED_HISTORY.map(value=>[...value])};
    if(query.text===_COLLECTION_SQL)return {rows:[['0.1','native_fts.v1']]};
    if(query.text===_SCOPE_SQL)return {rows:[]};
    if(query.text.includes('WITH search AS'))return {rows:this.candidates.map(value=>[value.tenant_id,value.collection,value.document_id,value.revision_id,value.generation_id,value.chunk_id,value.start_byte,value.end_byte,value.text_sha256,value.score,'native_fts.v1','pg_catalog.simple'])};
    if(query.text.includes('r.canonical_sha256')){
      const rows=typeof this.sourceRows==='function'?this.sourceRows(query.values):this.sourceRows;
      return {rows:structuredClone(rows)};
    }
    return {rows:[]};
  }
}
class Resource {
  config={release_timeout:0.05};leases=0;client=new Client();
  async withLease(options,body){this.leases++;return body(this.client,options.signal??new AbortController().signal);}
}
const bound=()=>({scope:scope(),deadline:now()+1});
async function fetch(resource,c=candidate(),budget=16777216,input=request()){
  return new PostgresSession(resource).transaction(input,bound(),handle=>handle.fetch_evidence(c,{max_source_bytes:budget}));
}
test('source verifies exact canonical digest, UTF8 span and immutable output',async()=>{
  const resource=new Resource();const result=await fetch(resource);
  assert.equal(result.state,'verified');assert.equal(result.source_bytes,9);assert.equal(result.evidence.source_sha256,sha('Café🙂'));assert.equal(result.evidence.text,'Café🙂');assert.ok(Object.isFrozen(result)&&Object.isFrozen(result.evidence));
  const query=resource.client.calls.find(query=>query.text.includes('r.canonical_sha256'));
  assert.deepEqual(query.values,[16777216,'tenant','collection','document','revision','generation','chunk','tenant','collection','auth','auth','principal',['grant']]);
  assert.ok(query.text.includes('g.status=\'ready\'')&&!query.text.includes('g.generation_id=d.active_generation_id'));
});
test('source fetch reapplies required identifier filters after current ACL',async()=>{
  const resource=new Resource();const input=parse_request({...request(),required_filters:[{op:'eq',field:'document_id',value:"x' OR TRUE --"}]});await fetch(resource,candidate(),16777216,input);
  const query=resource.client.calls.find(query=>query.text.includes('r.canonical_sha256'));assert.ok(query.text.includes('$14'));assert.ok(!query.text.includes('OR TRUE'));assert.equal(query.values.at(-1),"x' OR TRUE --");
});
test('scope mismatch fails before source SQL and malformed candidate fails safely',async()=>{
  for(const changes of [{tenant_id:'foreign'},{collection:'foreign'}]){const resource=new Resource();await assert.rejects(fetch(resource,{...candidate(),...changes}),UnauthorizedScope);assert.ok(!resource.client.calls.some(query=>query.text.includes('r.canonical_sha256')));}
  for(const changes of [{start_byte:NaN},{end_byte:0},{document_id:'\0'}])await assert.rejects(fetch(new Resource(),{...candidate(),...changes}),InvalidRequest);
});
for(const [index,value] of [[0,'foreign'],[6,'0'.repeat(64)],[7,16777217],[9,1],[10,7],[11,7],[12,'tampered'],[13,'0'.repeat(64)],[16,null]])test(`source corruption column ${index}`,async()=>{
  const resource=new Resource();resource.client.sourceRows[0][index]=value;await assert.rejects(fetch(resource),IntegrityViolation);
});
test('source rejects mid-scalar boundaries even if chunk and candidate digest agree',async()=>{
  const resource=new Resource();const c={...candidate(),start_byte:1,end_byte:2,text_sha256:sha('x')};const r=row();r[8]='🙂xx';r[6]=sha(r[8]);r[7]=6;r[9]=1;r[10]=2;r[11]=1;r[12]='x';r[13]=sha('x');resource.client.sourceRows=[r];await assert.rejects(fetch(resource,c),IntegrityViolation);
});
test('missing source, bounded unloaded source and retained generation are distinct',async()=>{
  const resource=new Resource();resource.client.sourceRows=[];assert.equal((await fetch(resource)).state,'unavailable');
  const r=row();r[8]=null;resource.client.sourceRows=[r];const exhausted=await fetch(resource,candidate(),7);assert.deepEqual(exhausted,{state:'budget_exhausted',evidence:null,source_bytes:0,stale:false});
  resource.client.sourceRows=[row()];resource.client.sourceRows[0][16]=false;assert.equal((await fetch(resource)).stale,true);
});
test('canonical bigint decimal offsets are parsed exactly, unsafe values rejected',async()=>{
  const resource=new Resource();for(const index of [7,9,10,11])resource.client.sourceRows[0][index]=String(resource.client.sourceRows[0][index]);assert.equal((await fetch(resource)).state,'verified');
  for(const value of ['01','1e1','9007199254740993','-1']){resource.client.sourceRows=[row()];resource.client.sourceRows[0][7]=value;await assert.rejects(fetch(resource),IntegrityViolation);}
});
test('duplicates and unsupported profiles fail closed',async()=>{
  const resource=new Resource();resource.client.sourceRows=[row(),row()];await assert.rejects(fetch(resource),IntegrityViolation);resource.client.sourceRows=[row()];resource.client.sourceRows[0][15]='other';await assert.rejects(fetch(resource),UnsupportedCapability);
});
test('retrieval returns partial unknown coverage with actual rendered evidence only',async()=>{
  const resource=new Resource();const result=await new PostgresRetriever(resource).retrieve(request(),bound());
  assert.equal(result.status,'partial');assert.equal(result.execution,'complete');assert.deepEqual(result.facets,[]);assert.equal(result.context,JSON.stringify(result.evidence));assert.equal(result.usage.context_tokens,Math.ceil(Buffer.byteLength(result.context)/4));assert.equal(result.usage.cost_kind,'known');assert.deepEqual(result.limitations,[{code:'coverage_unknown',facet_ids:[],evidence_ids:[]}]);assert.ok(Object.isFrozen(result)&&Object.isFrozen(result.evidence));assert.equal(resource.leases,2);
});
test('empty candidates and unavailable source return insufficient without operational fallback',async()=>{
  for(const missing of ['candidates','source']){const resource=new Resource();if(missing==='candidates')resource.client.candidates=[];else resource.client.sourceRows=[];const result=await new PostgresRetriever(resource).retrieve(request(),bound());assert.equal(result.status,'insufficient');assert.equal(result.context,'');assert.equal(result.usage.context_tokens,0);assert.equal(result.evidence.length,0);}
  const resource=new Resource();resource.client.failure={match:'WITH search AS',error:new Error('private-provider')};await assert.rejects(new PostgresRetriever(resource).retrieve(request(),bound()),ProviderUnavailable);
});
test('unsupported output contracts and impossible envelope fail before leasing',async()=>{
  for(const profile of [{renderer:'other'},{tokenizer:'declared'},{counting_mode:'strict',tokenizer:'declared'}]){const resource=new Resource();const input=parse_request({...request(),output_profile:profile});await assert.rejects(new PostgresRetriever(resource).retrieve(input,bound()),UnsupportedCapability);assert.equal(resource.leases,0);}
  const resource=new Resource();const input=parse_request({...request(),limits:{max_context_tokens:256}});await assert.rejects(new PostgresRetriever(resource).retrieve(input,bound()),ContextBudgetTooSmall);assert.equal(resource.leases,0);
});
test('context rejection skips whole chunk and reports truncation and budget',async()=>{
  const resource=new Resource();const input=parse_request({...request(),limits:{max_context_tokens:257}});const result=await new PostgresRetriever(resource).retrieve(input,bound());assert.equal(result.context,'');assert.equal(result.evidence.length,0);assert.deepEqual(result.limitations.map(value=>value.code),['coverage_unknown','truncated_evidence','budget_exhausted']);
});
test('source timeout and caller abort remain typed and rollback completes',async()=>{
  for(const abort of [false,true]){const resource=new Resource();const controller=new AbortController();let entered;const ready=new Promise(resolve=>entered=resolve);resource.client.block={match:'r.canonical_sha256',promise:new Promise(()=>{}),entered};const pending=new PostgresRetriever(resource).retrieve(request(),{scope:scope(),deadline:now()+0.05,signal:controller.signal});const check=assert.rejects(pending,error=>abort?error.name==='AbortError'&&!String(error).includes('private'):error instanceof DeadlineExceeded);await ready;if(abort)controller.abort('private-reason');await check;}
});
test('new retrieval imports do not load optional driver or perform network/writes',()=>{
  const script=`import{registerHooks,syncBuiltinESMExports}from'node:module';import fs from'node:fs';import net from'node:net';import tls from'node:tls';const deny=()=>{throw Error('side effect')};net.connect=deny;net.createConnection=deny;tls.connect=deny;fs.writeFile=deny;fs.writeFileSync=deny;fs.promises.writeFile=deny;syncBuiltinESMExports();registerHooks({resolve(s,c,n){if(s==='pg'||s.startsWith('pg/'))throw Error('driver');return n(s,c)}});await import('./dist/retrieval.js');`;
  const result=spawnSync(process.execPath,['--input-type=module','-e',script],{cwd:new URL('..',import.meta.url),encoding:'utf8',timeout:5000});assert.equal(result.status,0,result.stderr);
});
const fixtures=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/retrieval.json',import.meta.url),'utf8'));
for(const example of fixtures.source_cases)test(`shared source ${example.id}`,async()=>{
  const resource=new Resource();resource.client.sourceRows=example.rows;const operation=new PostgresSession(resource).transaction(parse_request(example.request),{scope:parse_scope(example.scope),deadline:now()+1},handle=>handle.fetch_evidence(example.candidate,{max_source_bytes:example.max_source_bytes}));
  if(example.error)await assert.rejects(operation,error=>error.code===example.error);else assert.deepEqual(await operation,example.expected);
});
for(const example of fixtures.result_cases)test(`shared result ${example.id}`,async()=>{
  const resource=new Resource();resource.client.candidates=example.candidates;resource.client.sourceRows=params=>example.sources.find(source=>[example.candidates[source.candidate_index].tenant_id,example.candidates[source.candidate_index].collection,example.candidates[source.candidate_index].document_id,example.candidates[source.candidate_index].revision_id,example.candidates[source.candidate_index].generation_id,example.candidates[source.candidate_index].chunk_id].every((value,index)=>value===params[index+1]))?.rows??[];
  const operation=new PostgresRetriever(resource).retrieve(parse_request(example.request),{scope:parse_scope(example.scope),deadline:now()+1});
  if(example.error)await assert.rejects(operation,error=>error.code===example.error);else assert.deepEqual(await operation,example.expected);
});

test('source byte budget is snapshotted before query awaits',async()=>{
  const resource=new Resource();let entered,release;
  const ready=new Promise(resolve=>entered=resolve);
  const gate=new Promise(resolve=>release=resolve);
  resource.client.block={match:'r.canonical_sha256',promise:gate,entered};
  const sourceOptions={max_source_bytes:100};
  const pending=new PostgresSession(resource).transaction(request(),bound(),handle=>handle.fetch_evidence(candidate(),sourceOptions));
  await ready;sourceOptions.max_source_bytes=0;release();
  assert.equal((await pending).state,'verified');
});
test('source candidate and options accessors reject without invoking getters',async()=>{
  const resource=new Resource();
  const bad={...candidate(),get document_id(){assert.fail('candidate getter executed');}};
  await assert.rejects(new PostgresSession(resource).transaction(request(),bound(),handle=>handle.fetch_evidence(bad,{max_source_bytes:100})),InvalidRequest);
  const badOptions={get max_source_bytes(){assert.fail('options getter executed');}};
  await assert.rejects(new PostgresSession(resource).transaction(request(),bound(),handle=>handle.fetch_evidence(candidate(),badOptions)),InvalidRequest);
});
