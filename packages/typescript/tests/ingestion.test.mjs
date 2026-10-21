import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import * as implementation from '../dist/ingestion.js';
import { PoolResource, parse_pool_config, now } from '../dist/postgres-pool.js';
import { EXPECTED_HISTORY, _CATALOG_SQL, _HISTORY_SQL, _COLLECTION_SQL } from '../dist/postgres-session.js';
import { parse_scope } from '../dist/contracts.js';
import { canonicalize } from '../dist/canonical.js';
import { DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability } from '../dist/errors.js';

const scope = () => parse_scope({tenant_id:'tenant',principal_id:'principal',authorization_revision:'auth',grant_ids:['unassigned-group']});
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return {promise, resolve}; };
class Client {
  status = 'I'; calls = []; releases = []; staged = []; published = []; document = []; revision = [];
  generation = []; jobs = []; counts = [[1,1]]; role = [[true]]; catalog = [[true]]; history = EXPECTED_HISTORY;
  collection = [['0.1','native_fts.v1']]; created = true; failure; commitError; commitBlock = false; rollbackBad = false;
  readyRows = [[1]];
  commits = 0; rollbacks = 0; gucs = null;
  getTransactionStatus() { return this.status; }
  release(destroy) { this.releases.push(destroy); }
  async query({text,values}) {
    this.calls.push([text,values]);
    if (this.failure && text.includes(this.failure[0])) throw this.failure[1];
    if (text === 'BEGIN') {
      this.before = structuredClone([this.staged,this.published,this.document,this.revision,this.gucs]); this.status='T';
    }
    if (text === 'COMMIT') {
      if (this.commitBlock) await new Promise(()=>{});
      if (this.commitError) throw this.commitError;
      this.commits++;this.status=this.rollbackBad?'E':'I';this.gucs=null;
    }
    if (text === 'ROLLBACK') {
      [this.staged,this.published,this.document,this.revision,this.gucs] = this.before;
      this.rollbacks++;this.status=this.rollbackBad?'E':'I';
    }
    if (text === implementation._WRITER_ROLE_SQL) return {rows:this.role};
    if (text === _CATALOG_SQL) return {rows:this.catalog};
    if (text === _HISTORY_SQL) return {rows:this.history};
    if (text === _COLLECTION_SQL) return {rows:this.collection};
    if (text === implementation._JOB_SQL) return {rows:this.jobs};
    if (text === implementation._DOCUMENT_LOCK_SQL) return {rows:this.document};
    if (text === implementation._REVISION_SQL) return {rows:this.revision};
    if (text === implementation._GENERATION_SQL) return {rows:this.generation};
    if (text === implementation._COUNTS_SQL) return {rows:this.counts};
    if (text.includes("set_config('cragkit.tenant_id'")) this.gucs=values;
    if (/^(INSERT|UPDATE) /.test(text)) {
      this.staged.push([text,structuredClone(values)]);
      if (text.startsWith('UPDATE cragkit.index_generations')) return {rows:this.readyRows};
      if (text.startsWith('INSERT INTO cragkit.documents')) {
        if (this.created) this.document=[[null,false,values[3]]];
        return {rows:this.created?[['document']]:[]};
      }
      if (text.startsWith('INSERT INTO cragkit.document_revisions')) this.revision=[[values[4],values[7],values[5],values[8]]];
      if (text.startsWith('UPDATE cragkit.documents')) this.published.push(structuredClone(values));
      return {rows:[[1]]};
    }
    return {rows:[]};
  }
}
function fixture(authorize = async()=>true) {
  const client = new Client(); const pool={leases:0,async connect(){this.leases++;return client;},async end(){assert.fail('borrowed pool closed');}};
  const config = parse_pool_config({host:'host.invalid',dbname:'synthetic',user:'writer',sslrootcert:'/synthetic/ca',passfile:'/synthetic/pass',release_timeout:0.03,close_timeout:0.1});
  const resource=new PoolResource(config,{pool});
  return {client,pool,resource,indexer:new implementation.PostgresIndexer(resource,authorize)};
}
const ingest = (indexer,changes={},source='synthetic source') => indexer.ingest(source,{collection:'collection',document_id:'document',intent_id:'intent',source_locator:'synthetic:source',scope:scope(),deadline:now()+1,...changes});

test('ingestion import does not load an optional driver or perform network/process I/O',()=>{
  const script=`import {syncBuiltinESMExports} from 'node:module';import net from 'node:net';import child from 'node:child_process';
  net.connect=net.createConnection=()=>{throw Error('network')};child.spawn=child.exec=()=>{throw Error('process')};syncBuiltinESMExports();
  await import(${JSON.stringify(new URL('../dist/ingestion.js',import.meta.url).href)});`;
  const result=spawnSync(process.execPath,['--input-type=module','-e',script],{encoding:'utf8',timeout:5000});
  assert.equal(result.status,0,result.stderr);assert.equal(result.stdout,'');
});
test('new ingestion commits immutable receipt and scoped parameterized batch',async()=>{
  const {client,indexer,resource}=fixture();
  const result=await ingest(indexer);
  assert.equal(result.replayed,false);assert.equal(result.chunk_count,1);assert.equal(Object.isFrozen(result),true);
  assert.equal(client.commits,1);assert.equal(client.rollbacks,0);assert.equal(client.status,'I');assert.equal(client.gucs,null);
  assert.equal(client.published.length,1);assert.deepEqual(client.releases,[false]);
  const grants=client.staged.filter(([text])=>text.includes('document_grants'));
  assert.equal(grants.length,1);assert.ok(!JSON.stringify(grants).includes('unassigned-group'));
  assert.ok(client.staged.every(([text])=>!text.includes('synthetic source')));
  await resource.close();
});
for (const changes of [{collection:''},{document_id:'\0'},{source_locator:'\ud800'},{intent_id:''},{metadata:{n:NaN}},
  {metadata:{n:Infinity}},{metadata:{n:'\0'}},{metadata:{n:undefined}},{canonical_options:{target_bytes:0}},{unknown:true}]) {
  test(`invalid ingest boundary ${JSON.stringify(changes)}`,async()=>{
    const {pool,indexer,resource}=fixture();await assert.rejects(ingest(indexer,changes),InvalidRequest);
    assert.equal(pool.leases,0);await resource.close();
  });
}
for (const allowed of [false,null,1,'yes']) test(`write authorization exact true ${allowed}`,async()=>{
  const {pool,indexer,resource}=fixture(async()=>allowed);
  await assert.rejects(ingest(indexer,{canonical_options:{token_counter:()=>assert.fail('parsed unauthorized text')}}),UnauthorizedScope);
  assert.equal(pool.leases,0);await resource.close();
});
test('write authorization is deadline and AbortSignal bounded without leasing',async()=>{
  const {pool,indexer,resource}=fixture(async()=>new Promise(()=>{}));
  await assert.rejects(ingest(indexer,{deadline:now()+0.01}),DeadlineExceeded);
  const controller=new AbortController();const pending=ingest(indexer,{signal:controller.signal});controller.abort('private-reason');
  await assert.rejects(pending,error=>error.name==='AbortError'&&!String(error).includes('private'));
  assert.equal(pool.leases,0);await resource.close();
});
for (const [field,value,kind] of [['role',[[false]],UnauthorizedScope],['catalog',[[false]],UnsupportedCapability],['history',[],UnsupportedCapability],['collection',[['0.1','other']],UnsupportedCapability]]) {
  test(`schema/role fail closed ${field}`,async()=>{
    const {client,indexer,resource}=fixture();client[field]=value;
    await assert.rejects(ingest(indexer),kind);assert.equal(client.rollbacks,1);assert.deepEqual(client.staged,[]);await resource.close();
  });
}
test('caller prepublication error rolls back without changing exception identity',async()=>{
  const {client,indexer,resource}=fixture();const sentinel=new Error('caller');
  await assert.rejects(ingest(indexer,{before_publish:async()=>{assert.ok(client.staged.length);assert.equal(client.published.length,0);throw sentinel;}}),error=>error===sentinel);
  assert.equal(client.rollbacks,1);assert.deepEqual(client.staged,[]);assert.deepEqual(client.published,[]);await resource.close();
});
for (const [document,kind] of [[['active',true,'auth'],UnauthorizedScope],[['active',false,'stale'],UnauthorizedScope],[['active',false,'auth'],IndexNotReady]]) {
  test(`document authorization/CAS ${JSON.stringify(document)}`,async()=>{
    const {client,indexer,resource}=fixture();client.created=false;client.document=[document];
    await assert.rejects(ingest(indexer,{expected_generation_id:'stale-active'}),kind);
    assert.equal(client.rollbacks,1);assert.deepEqual(client.staged,[]);await resource.close();
  });
}
for (const [code,kind] of [['57014',DeadlineExceeded],['42501',UnauthorizedScope],['42P01',UnsupportedCapability],['XX000',ProviderUnavailable]]) {
  test(`redacted driver error ${code}`,async()=>{
    const {client,indexer,resource}=fixture();client.failure=['INSERT INTO cragkit.index_generations',Object.assign(new Error('private-driver-secret'),{code})];
    await assert.rejects(ingest(indexer),error=>error instanceof kind&&!String(error).includes('private'));
    assert.equal(client.rollbacks,1);assert.deepEqual(client.staged,[]);await resource.close();
  });
}
test('same intent replay verifies original ready generation without writes',async()=>{
  const {client,indexer,resource}=fixture();const first=await ingest(indexer);client.staged=[];client.published=[];
  client.jobs=[[first.payload_sha256,first.generation_id,'succeeded','document']];
  client.document=[['newer-generation',false,'auth']];client.generation=[[first.revision_id,'ready',first.chunk_count]];
  const replay=await ingest(indexer);assert.deepEqual(replay,{...first,replayed:true});assert.deepEqual(client.staged,[]);await resource.close();
});
for (const corrupt of ['payload','document','state','generation','counts']) test(`replay rejects corruption ${corrupt}`,async()=>{
  const {client,indexer,resource}=fixture();const first=await ingest(indexer);client.staged=[];
  client.jobs=[[first.payload_sha256,first.generation_id,'succeeded','document']];client.generation=[[first.revision_id,'ready',1]];
  if(corrupt==='payload')client.jobs[0][0]='changed';if(corrupt==='document')client.jobs[0][3]='other';
  if(corrupt==='state')client.jobs[0][2]='running';if(corrupt==='generation')client.generation[0][1]='staging';if(corrupt==='counts')client.counts=[[0,0]];
  await assert.rejects(ingest(indexer),['payload','document'].includes(corrupt)?InvalidRequest:corrupt==='state'?IndexNotReady:IntegrityViolation);
  assert.deepEqual(client.staged,[]);await resource.close();
});
for (const block of [false,true]) test(`commit uncertainty destroys lease ${block}`,async()=>{
  const {client,indexer,resource}=fixture();client.commitBlock=block;client.commitError=Object.assign(new Error('private'),{code:'XX000'});
  await assert.rejects(ingest(indexer,{deadline:now()+0.02}),block?DeadlineExceeded:ProviderUnavailable);
  assert.deepEqual(client.releases,[true]);assert.equal(client.rollbacks,0);await resource.close();
});
test('abort during staged hook destroys only that lease and next request works',async()=>{
  const {client,indexer,resource,pool}=fixture();const gate=deferred();const controller=new AbortController();
  const pending=ingest(indexer,{signal:controller.signal,before_publish:async()=>{gate.resolve();await new Promise(()=>{});}});
  await gate.promise;controller.abort();await assert.rejects(pending,error=>error.name==='AbortError');
  assert.deepEqual(client.releases,[true]);assert.equal(client.commits,0);
  const next=new Client();pool.connect=async()=>next;
  assert.equal((await ingest(indexer)).replayed,false);assert.equal(next.commits,1);await resource.close();
});
test('metadata, canonical options and caller bytes are snapshotted before authorizer await',async()=>{
  const gate=deferred();const entered=deferred();const {client,indexer,resource}=fixture(async()=>{entered.resolve();await gate.promise;return true;});
  const bytes=Buffer.from('synthetic source');const metadata={nested:[1]};const canonical_options={target_bytes:2048};
  const pending=ingest(indexer,{metadata,canonical_options},bytes);await entered.promise;
  bytes.fill(0);metadata.nested[0]=2;canonical_options.target_bytes=0;gate.resolve();const result=await pending;
  assert.equal(result.canonical_sha256,canonicalize('synthetic source').canonical_sha256);
  assert.equal(client.published[0][1],JSON.stringify({nested:[1]}));await resource.close();
});
test('cycles, accessors, symbol keys and malicious metadata prototypes fail closed',()=>{
  const cycle={};cycle.self=cycle;
  for(const value of [cycle,new Date(),{get value(){assert.fail('getter invoked');}}, {[Symbol('hidden')]:1},new Proxy({}, {getPrototypeOf(){throw Error('private');}})]) {
    assert.throws(()=>implementation.metadata_snapshot(value),InvalidRequest);
  }
});
const oracle=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/ingestion.json',import.meta.url),'utf8'));
for(const item of oracle.metadata_cases)test(`shared metadata TLV oracle ${item.id}`,()=>assert.equal(implementation.metadata_snapshot(item.value)[1],item.sha256));

const canonicalOracle=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/canonical.json',import.meta.url),'utf8'));
for(const item of oracle.identifier_cases)test(`shared identifier oracle ${item.id}`,()=>{
  const document=canonicalOracle.cases.find(value=>value.id===item.canonical_case).expected;
  const metadata=oracle.metadata_cases.find(value=>value.id===item.metadata_case);
  assert.deepEqual(implementation.identifiers(document,parse_scope(item.scope),item.collection,item.document_id,
    item.intent_id,item.source_locator,metadata.sha256,item.expected_generation_id),item.expected);
});

test('missing ready publication barrier cannot publish the document',async()=>{
  const {client,indexer,resource}=fixture();client.readyRows=[];
  await assert.rejects(ingest(indexer),IntegrityViolation);
  assert.equal(client.commits,0);assert.equal(client.rollbacks,1);assert.deepEqual(client.published,[]);await resource.close();
});

test('option accessors fail before any getter or lease',async()=>{
  const {pool,indexer,resource}=fixture();
  await assert.rejects(indexer.ingest('synthetic',{get deadline(){assert.fail('caller getter invoked');}}),InvalidRequest);
  assert.equal(pool.leases,0);await resource.close();
});
