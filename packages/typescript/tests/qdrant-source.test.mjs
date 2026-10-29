import {AUTHORITY_PURGE_HISTORY,EXPECTED_PURGE_CATALOG_FINGERPRINT,EXPECTED_PURGE_CAPABILITY_FINGERPRINT,AUTHORITY_PURGE_CATALOG_SQL,PURGE_OWNER_SQL,PURGE_CAPABILITY_FINGERPRINT_SQL} from '../dist/qdrant-authority.js';
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {PostgresQdrantSourceStore} from '../dist/qdrant-source.js';
import {SOURCE_ROW_FIELDS,verify_source} from '../dist/qdrant-source-contract.js';
import {AUTHORITY_HISTORY,AUTHORITY_ROLE_SQL,AUTHORITY_CATALOG_SQL,AUTHORITY_HISTORY_SQL,AUTHORITY_FINGERPRINT_SQL,EXPECTED_AUTHORITY_FINGERPRINT} from '../dist/qdrant-authority.js';
import {PoolResource,parse_pool_config} from '../dist/postgres-pool.js';
import {InvalidRequest,IntegrityViolation,ProviderUnavailable,DeadlineExceeded,UnsupportedCapability} from '../dist/errors.js';
const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_sources.json',import.meta.url),'utf8'));
const deadline=()=>performance.now()/1000+3;
function resolve(v){if(typeof v==='string'&&v.startsWith('$ref:')){let out=fixture;for(const key of v.slice(5).split('.'))out=out[key];return resolve(out);}if(Array.isArray(v))return v.map(resolve);if(v&&typeof v==='object'){if(v.encoding==='utf8')return Buffer.from(v.value,'utf8');if(v.encoding==='hex')return Buffer.from(v.value,'hex');return Object.fromEntries(Object.entries(v).map(([k,x])=>[k,resolve(x)]));}return v;}
const config={backend_namespace:'fixture-local',physical_collection:'cragkit_qc_r1',collection_incarnation:'inc-1',dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse};
const base=()=>resolve(fixture.base_row),nom=()=>resolve(fixture.nomination);
function setup(){
  const state={rows:[base()],reads:0,clients:[],error:null,wait:null,history:AUTHORITY_HISTORY.map(row=>[...row]),fingerprint:EXPECTED_AUTHORITY_FINGERPRINT};
  const pool={ends:0,async connect(){const client={status:'I',releases:[],getTransactionStatus(){return this.status;},release(destroy=false){this.releases.push(destroy);},async query(q){
    if(q.text.startsWith('BEGIN')){this.status='T';return {rows:[]};}if(q.text==='ROLLBACK'){this.status='I';return {rows:[]};}
    if(q.text===PURGE_CAPABILITY_FINGERPRINT_SQL)return {rows:[[EXPECTED_PURGE_CAPABILITY_FINGERPRINT]]};if(q.text===PURGE_OWNER_SQL)return {rows:[[true]]};if(q.text===AUTHORITY_ROLE_SQL||q.text===AUTHORITY_CATALOG_SQL||q.text===AUTHORITY_PURGE_CATALOG_SQL)return {rows:[[true]]};if(q.text===AUTHORITY_HISTORY_SQL)return {rows:state.history};
    if(q.text===AUTHORITY_FINGERPRINT_SQL)return {rows:[[state.fingerprint]]};
    if(q.text.includes('FROM cragkit_qdrant.members m')){state.reads++;if(state.wait)await state.wait;if(state.error)throw state.error;return {rows:state.rows.map(r=>{const row={...r};if(Number(row.source_bytes)>q.values[0]||Number(row.source_bytes)>16777216||Number(row.excerpt_bytes)>32768){row.canonical_utf8=null;row.excerpt_utf8=null;}return SOURCE_ROW_FIELDS.map(k=>row[k]);})};}return {rows:[]};
  }};state.clients.push(client);return client;},async end(){this.ends++;}};
  const resource=new PoolResource(parse_pool_config({host:'host.invalid',dbname:'synthetic',user:'reader',sslrootcert:'/fake/ca',passfile:'/fake/pass'}),{pool});
  return {state,pool,resource,store:new PostgresQdrantSourceStore(resource,config)};
}
async function ready(){const x=setup();await x.store.initialize({deadline:deadline()});return x;}
const open=(store,extra={})=>store.open_request(fixture.request,{scope:fixture.scope,deadline:deadline(),...extra});

for(const c of fixture.cases)test(`QS-r1 shared ${c.id}`,async()=>{
  const x=await ready();let handle=open(x.store);let binding;let input=nom();let row=base();
  try{
    if(c.operation==='release'&&c.binding!=='serialized_identity_copy')binding=(await handle.fetch_candidate(input,{max_source_bytes:16777216})).binding;
    if(c.binding==='issued_by_other_request'){await handle.close();handle=open(x.store);}
    if(c.precondition==='provider_received_while_authorized')await handle.release(binding,{purpose:'provider',max_source_bytes:16777216});
    if(c.precondition==='provider_and_final_release_already_attempted'){await handle.release(binding,{purpose:'provider',max_source_bytes:16777216});await handle.release(binding,{purpose:'final',max_source_bytes:16777216});}
    if(c.precondition==='binding_request_closed')await handle.close();
    for(const [path,value]of Object.entries(c.set??{})){const keys=path.split('.');let target=keys[0]==='base_row'?row:input;for(const key of keys.slice(1,-1))target=target[key];target[keys.at(-1)]=resolve(value);}
    x.state.rows=c.authority==='no_row'?[]:[row];
    if(c.authority==='connection_failure')x.state.error=new Error('private credentials source query');
    if(c.authority==='deadline_expired'){await handle.close();handle=open(x.store,{deadline:performance.now()/1000+0.01});await new Promise(r=>setTimeout(r,15));}
    if(c.prior_fetch_attempts)for(let i=0;i<c.prior_fetch_attempts;i++)await handle.fetch_candidate(input,{max_source_bytes:16777216});
    const before=x.state.reads;
    const operation=()=>c.operation==='release'?handle.release(c.binding==='serialized_identity_copy'?structuredClone(input.payload):binding,{purpose:'final',max_source_bytes:c.remaining_source_bytes??c.max_source_bytes??16777216,include_source:c.include_source??false}):handle.fetch_candidate(input,{max_source_bytes:c.max_source_bytes??16777216,include_source:c.include_source??false});
    if(c.expected.error)await assert.rejects(operation(),e=>e.name===c.expected.error,c.id);
    else{
      const result=await operation();assert.equal(result.state,c.expected.state,c.id);if(c.expected.text!==undefined)assert.equal(result.evidence.text,c.expected.text,c.id);if(c.expected.source_bytes!==undefined)assert.equal(result.source_bytes,c.expected.source_bytes,c.id);if(c.expected.stale!==undefined)assert.equal(result.stale,c.expected.stale,c.id);
      if(c.expected.binding_issued!==undefined)assert.equal(result.binding!==null,c.expected.binding_issued,c.id);
      if(c.expected.private_canonical_source!==undefined)assert.equal(result.private_source.canonical_text,c.expected.private_canonical_source,c.id);
      assert.ok(Object.isFrozen(result));const serialized=JSON.stringify(result);assert.ok(!serialized.includes('private_source'));assert.ok(!serialized.includes('"binding"'));assert.ok(!serialized.includes('canonical_text'));
    }
    if(c.expected.sql_calls===0)assert.equal(x.state.reads-before,0,c.id);
  }finally{await handle.close();await x.store.close();assert.equal(x.pool.ends,0);await x.resource.close();}
});
test('private binding copies, purpose replay and final-before-provider reject without SQL',async()=>{
  const x=await ready();const h=open(x.store);const result=await h.fetch_candidate(nom(),{max_source_bytes:13,include_source:true});
  assert.throws(()=>JSON.stringify(result.binding),InvalidRequest);assert.throws(()=>JSON.stringify(h),InvalidRequest);
  for(const copy of [{},structuredClone(result.binding),{...result.binding}])await assert.rejects(h.release(copy,{purpose:'final',max_source_bytes:13}),InvalidRequest);
  await h.release(result.binding,{purpose:'final',max_source_bytes:13});const reads=x.state.reads;await assert.rejects(h.release(result.binding,{purpose:'provider',max_source_bytes:13}),InvalidRequest);assert.equal(x.state.reads,reads);await h.close();await x.store.close();await x.resource.close();
});
test('one live request, original deadline, snapshots and borrowed resources',async()=>{
  const x=await ready();const request=structuredClone(fixture.request),scope=structuredClone(fixture.scope);const h=x.store.open_request(request,{scope,deadline:deadline()});
  request.collection='other';scope.tenant_id='other';await assert.rejects(Promise.resolve().then(()=>open(x.store)),ProviderUnavailable);
  const result=await h.fetch_candidate(nom(),{max_source_bytes:13});assert.equal(result.evidence.collection,'docs');await h.close();const next=open(x.store);await next.close();await x.store.close();assert.equal(x.pool.ends,0);await x.resource.close();
});
test('row integer strings, BOM, strict buffers, size budget and immutable provenance',()=>{
  const row=base();for(const k of ['start_byte','end_byte','source_bytes','excerpt_bytes','mutation_epoch'])row[k]=String(row[k]);
  const opts={max_source_bytes:13};assert.equal(verify_source(nom(),[row],fixture.request,fixture.scope,config,opts).state,'verified');
  for(const value of ['01','1.0','-1','9007199254740992',true]){const bad=base();bad.start_byte=value;assert.throws(()=>verify_source(nom(),[bad],fixture.request,fixture.scope,config,opts),IntegrityViolation);}
  const loadedAboveBudget=base();assert.throws(()=>verify_source(nom(),[loadedAboveBudget],fixture.request,fixture.scope,config,{max_source_bytes:12}),IntegrityViolation);
  const bom=base(),input=nom();const bytes=Buffer.from('\ufeffA café 雪.\n');bom.canonical_utf8=bytes;bom.source_bytes=16;bom.start_byte=5;bom.end_byte=14;bom.source_sha256=createHash('sha256').update(bytes).digest('hex');input.payload.start_byte=5;input.payload.end_byte=14;input.payload.source_sha256=bom.source_sha256;
  const verified=verify_source(input,[bom],fixture.request,fixture.scope,config,{max_source_bytes:16,include_source:true});assert.ok(verified.private_source.canonical_text.startsWith('\ufeff'));
  assert.throws(()=>verify_source(nom(),[base()],fixture.request,fixture.scope,config,{max_source_bytes:13,retained:true,bound_provenance:{parser_id:'other',chunker_profile:'fixture_chunker_v1',source_locator:'fixture:qdrant/doc-1@rev-1'}}),IntegrityViolation);
});
test('midflight abort and close cancel borrowed queries with no release disclosure',async()=>{
  for(const mode of ['abort','close']){
    const x=await ready();const controller=new AbortController();const h=open(x.store,{signal:controller.signal});let finish;x.state.wait=new Promise(r=>finish=r);
    const pending=h.fetch_candidate(nom(),{max_source_bytes:13});const rejected=assert.rejects(pending,e=>e.name==='AbortError');await new Promise(r=>setImmediate(r));
    await assert.rejects(h.fetch_candidate(nom(),{max_source_bytes:13}),ProviderUnavailable);
    if(mode==='abort')controller.abort();else await h.close();await rejected;finish();assert.ok(x.state.clients.at(-1).releases.includes(true));await h.close();await x.store.close();await x.resource.close();
  }
});
test('defensive denied rows report loaded canonical bytes while returning no text',()=>{
  const row=base();row.grant_ids=[];row.principal_ids=[];
  const result=verify_source(nom(),[row],fixture.request,fixture.scope,config,{max_source_bytes:13,include_source:true});
  assert.equal(result.state,'unavailable');assert.equal(result.source_bytes,13);assert.equal(result.evidence,null);assert.equal(result.private_source,null);assert.equal(result.binding,null);
});
test('denied rows reject empty or partial buffers while null CASE columns remain unavailable',()=>{
  for(const [field,value]of [['canonical_utf8',new Uint8Array()],['canonical_utf8',Buffer.from('partial')],['excerpt_utf8',new Uint8Array()],['excerpt_utf8',Buffer.from('partial')]]){
    const row=base();row.grant_ids=[];row.principal_ids=[];row[field]=value;
    assert.throws(()=>verify_source(nom(),[row],fixture.request,fixture.scope,config,{max_source_bytes:13}),IntegrityViolation,field);
  }
  const row=base();row.grant_ids=[];row.principal_ids=[];row.canonical_utf8=null;row.excerpt_utf8=null;
  const result=verify_source(nom(),[row],fixture.request,fixture.scope,config,{max_source_bytes:13});
  assert.equal(result.state,'unavailable');assert.equal(result.source_bytes,0);assert.equal(result.evidence,null);assert.equal(result.private_source,null);
});

test('profile5 erased source with retained original lengths is unavailable before decoding',async()=>{
  const x=setup();x.state.history=AUTHORITY_PURGE_HISTORY.map(row=>[...row]);x.state.fingerprint=EXPECTED_PURGE_CATALOG_FINGERPRINT;
  let handle;
  try{
    await x.store.initialize({deadline:deadline()});handle=open(x.store);
    const erased=base();erased.canonical_utf8=null;erased.excerpt_utf8=null;erased.tombstoned=true;x.state.rows=[erased];
    assert(erased.source_bytes>0&&erased.excerpt_bytes>0);
    const result=await handle.fetch_candidate(nom(),{max_source_bytes:13,include_source:true});
    assert.equal(result.state,'unavailable');assert.equal(result.source_bytes,0);assert.equal(result.evidence,null);
    assert.equal(result.private_source,null);assert.equal(result.binding,null);
  }finally{await handle?.close();await x.store.close();await x.resource.close();}
});
