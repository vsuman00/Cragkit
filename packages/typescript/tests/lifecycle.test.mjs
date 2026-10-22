import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { PostgresLifecycle, _PURGE_CATALOG_SQL, _PURGER_ROLE_SQL, _TOMBSTONE_SQL, _PURGE_SQL, _MARKER_SQL } from '../dist/lifecycle.js';
import { _WRITER_ROLE_SQL, _LOCK_SQL, _DOCUMENT_LOCK_SQL } from '../dist/ingestion.js';
import { EXPECTED_HISTORY, _CATALOG_SQL, _HISTORY_SQL, _SCOPE_SQL } from '../dist/postgres-session.js';
import { parse_scope } from '../dist/contracts.js';
import { now } from '../dist/postgres-pool.js';
import { InvalidRequest, UnauthorizedScope, IndexNotReady, IntegrityViolation, ProviderUnavailable, DeadlineExceeded, UnsupportedCapability } from '../dist/errors.js';
const stamp='2026-10-22 01:02:03.123456+00';
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {resolve,promise};};
class Client {
  status='I';calls=[];released=[];document=['generation',false,'auth'];children=3;metadata={private:'synthetic'};
  role=true;catalog=true;purgeCatalog=true;history=EXPECTED_HISTORY;failure;badCommit=false;badRollback=false;mutationRows=[[1]];deleteRows=[[stamp]];
  getTransactionStatus(){return this.status;}
  release(destroy){this.released.push(destroy);}
  async query(query){
    this.calls.push(query);assert.equal(query.rowMode,'array');
    if(this.failure?.text===query.text){if(this.failure.gate)await this.failure.gate;throw this.failure.error;}
    if(query.text==='BEGIN'){this.before=structuredClone({document:this.document,children:this.children,metadata:this.metadata});this.status='T';}
    if(query.text==='COMMIT')this.status=this.badCommit?'E':'I';
    if(query.text==='ROLLBACK'){Object.assign(this,this.before);this.status=this.badRollback?'E':'I';}
    if(query.text===_WRITER_ROLE_SQL||query.text===_PURGER_ROLE_SQL)return {rows:[[this.role]]};
    if(query.text===_PURGE_CATALOG_SQL)return {rows:[[this.purgeCatalog]]};
    if(query.text===_CATALOG_SQL)return {rows:[[this.catalog]]};
    if(query.text===_HISTORY_SQL)return {rows:this.history};
    if(query.text===_DOCUMENT_LOCK_SQL)return {rows:this.document===null?[]:[this.document]};
    if(query.text===_TOMBSTONE_SQL){this.document[1]=true;return {rows:this.mutationRows};}
    if(query.text===_PURGE_SQL){this.document=null;this.children=0;return {rows:this.deleteRows};}
    if(query.text===_MARKER_SQL){this.document=[null,true,query.values[3]];this.metadata={};return {rows:this.mutationRows};}
    return {rows:[]};
  }
}
class Resource {
  client=new Client();config={release_timeout:0.02};leases=0;
  async withLease(options,body){this.leases++;return body(this.client,options.signal??new AbortController().signal);}
}
const scope=()=>parse_scope({tenant_id:'tenant',principal_id:'principal',authorization_revision:'auth',grant_ids:['read-group']});
const options=()=>({collection:'collection',document_id:'document',expected_generation_id:'generation',scope:scope(),deadline:now()+1});
function fixture(authorizer=async()=>true){const resource=new Resource();return {resource,client:resource.client,lifecycle:new PostgresLifecycle(resource,authorizer)};}
test('tombstone preserves pointer, metadata and children; repeated call reports unchanged',async()=>{
  const {resource,client,lifecycle}=fixture();const result=await lifecycle.tombstone(options());
  assert.deepEqual(result,{tenant_id:'tenant',collection:'collection',document_id:'document',state:'tombstoned',active_generation_id:'generation',changed:true});
  assert.ok(Object.isFrozen(result));assert.equal(client.children,3);assert.deepEqual(client.metadata,{private:'synthetic'});
  assert.equal((await lifecycle.tombstone(options())).changed,false);assert.equal(resource.leases,2);
  assert.deepEqual(client.calls.find(q=>q.text===_LOCK_SQL).values,['["cragkit.document.v1","tenant","collection","document"]']);
  assert.deepEqual(client.calls.find(q=>q.text===_TOMBSTONE_SQL).values,['tenant','collection','document','auth','generation']);
});
test('purge deletes parent and cascades, reinserts same precision timestamp and minimal marker',async()=>{
  const {client,lifecycle}=fixture();client.document[1]=true;const result=await lifecycle.purge_tombstoned(options());
  assert.deepEqual(result,{tenant_id:'tenant',collection:'collection',document_id:'document',state:'purged',active_generation_id:null,changed:true});
  assert.equal(client.children,0);assert.deepEqual(client.metadata,{});assert.deepEqual(client.document,[null,true,'auth']);
  assert.deepEqual(client.calls.find(q=>q.text===_MARKER_SQL).values,['tenant','collection','document','auth',stamp]);
  assert.ok(_PURGE_SQL.includes('created_at::text'));assert.ok(_MARKER_SQL.includes('$5::timestamptz'));
  assert.equal((await lifecycle.purge_tombstoned({...options(),expected_generation_id:null})).changed,true);
  await assert.rejects(lifecycle.purge_tombstoned(options()),IndexNotReady);
});
test('purge role guard permits parent DELETE only and leaves ingestion guard unchanged',()=>{
  assert.ok(_PURGER_ROLE_SQL.includes("c.relname <> 'documents'"));assert.ok(_PURGER_ROLE_SQL.includes("'TRUNCATE'"));assert.ok(!_WRITER_ROLE_SQL.includes("c.relname <> 'documents'"));
});
test('authorizer sees immutable snapshot and explicit operation before lease',async()=>{
  const entered=deferred();const release=deferred();let seen;const {resource,lifecycle}=fixture(async(...args)=>{seen=args;entered.resolve();await release.promise;return true;});
  const input=options();const pending=lifecycle.purge_tombstoned(input);await entered.promise;assert.equal(resource.leases,0);
  input.document_id='changed';input.expected_generation_id=null;input.scope={...scope(),tenant_id:'foreign'};resource.client.document[1]=true;release.resolve();
  const result=await pending;assert.equal(result.document_id,'document');assert.equal(result.tenant_id,'tenant');assert.equal(seen[3],'purge');assert.ok(Object.isFrozen(seen[0]));
});
for(const value of [false,null,1,'true'])test(`nontrue authorizer denied ${String(value)}`,async()=>{
  const {resource,lifecycle}=fixture(async()=>value);await assert.rejects(lifecycle.tombstone(options()),UnauthorizedScope);assert.equal(resource.leases,0);
});
for(const changes of [{collection:''},{collection:'x'.repeat(129)},{document_id:'\0'},{document_id:'\uD800'},{expected_generation_id:undefined},{expected_generation_id:''},{unknown:true}])test(`invalid lifecycle input ${JSON.stringify(changes)}`,async()=>{
  const {resource,lifecycle}=fixture();await assert.rejects(lifecycle.tombstone({...options(),...changes}),InvalidRequest);assert.equal(resource.leases,0);
});
test('input getters are rejected without executing them',async()=>{
  const {resource,lifecycle}=fixture();let invoked=false;const input=options();Object.defineProperty(input,'document_id',{enumerable:true,get(){invoked=true;return 'document';}});
  await assert.rejects(lifecycle.tombstone(input),InvalidRequest);assert.equal(invoked,false);assert.equal(resource.leases,0);
});
for(const [row,error] of [[null,UnauthorizedScope],[['generation',false,'different'],UnauthorizedScope],[['other',false,'auth'],IndexNotReady],[['generation','false','auth'],IntegrityViolation],[['generation',false,''],IntegrityViolation]])test(`locked document validation ${JSON.stringify(row)}`,async()=>{
  const {client,lifecycle}=fixture();client.document=row;await assert.rejects(lifecycle.tombstone(options()),error);assert.equal(client.calls.at(-1).text,'ROLLBACK');
});
test('purging live document is invalid and leaves data unchanged',async()=>{
  const {client,lifecycle}=fixture();await assert.rejects(lifecycle.purge_tombstoned(options()),InvalidRequest);assert.equal(client.children,3);assert.equal(client.document[1],false);
});
test('role, catalog and history failures precede mutation',async()=>{
  for(const [field,value,error] of [['role',false,UnauthorizedScope],['catalog',false,UnsupportedCapability],['history',[],UnsupportedCapability]]){
    const {client,lifecycle}=fixture();client[field]=value;await assert.rejects(lifecycle.tombstone(options()),error);assert.equal(client.document[1],false);
  }
});
test('failed reinsertion rolls back erased parent and all cascaded children',async()=>{
  const {client,lifecycle}=fixture();client.document[1]=true;client.failure={text:_MARKER_SQL,error:new Error('private-provider')};
  await assert.rejects(lifecycle.purge_tombstoned(options()),error=>error instanceof ProviderUnavailable&&!String(error).includes('private'));
  assert.deepEqual(client.document,['generation',true,'auth']);assert.equal(client.children,3);assert.equal(client.status,'I');
});
test('missing mutation rows are integrity errors and rollback',async()=>{
  for(const method of ['tombstone','purge_tombstoned']){const {client,lifecycle}=fixture();client.document[1]=method==='purge_tombstoned';client.mutationRows=[];await assert.rejects(lifecycle[method](options()),IntegrityViolation);assert.equal(client.children,3);}
});
test('uncertain commit discards connection rather than claiming rollback',async()=>{
  const {client,lifecycle}=fixture();client.badCommit=true;await assert.rejects(lifecycle.tombstone(options()),ProviderUnavailable);assert.deepEqual(client.released,[true]);assert.ok(!client.calls.some(q=>q.text==='ROLLBACK'));
});
test('callback deadline and cancellation prevent lease',async()=>{
  for(const abort of [false,true]){const controller=new AbortController();const {resource,lifecycle}=fixture(async()=>new Promise(()=>{}));const promise=lifecycle.tombstone({...options(),deadline:now()+0.02,signal:controller.signal});const check=assert.rejects(promise,error=>abort?error.name==='AbortError':error instanceof DeadlineExceeded);if(abort)controller.abort('private reason');await check;assert.equal(resource.leases,0);}
});
test('driver SQLSTATE failures are typed without provider details',async()=>{
  for(const [code,kind] of [['57014',DeadlineExceeded],['42501',UnauthorizedScope],['23503',IntegrityViolation]]){const {client,lifecycle}=fixture();client.failure={text:_TOMBSTONE_SQL,error:Object.assign(new Error('private-source'),{code})};await assert.rejects(lifecycle.tombstone(options()),error=>error instanceof kind&&!String(error).includes('private'));assert.equal(client.document[1],false);}
});
test('lifecycle import performs no optional-driver load or network/write work',()=>{
  const script=`import{registerHooks,syncBuiltinESMExports}from'node:module';import fs from'node:fs';import net from'node:net';import tls from'node:tls';const deny=()=>{throw Error('side effect')};net.connect=deny;net.createConnection=deny;tls.connect=deny;fs.writeFile=deny;fs.writeFileSync=deny;fs.promises.writeFile=deny;syncBuiltinESMExports();registerHooks({resolve(s,c,n){if(s==='pg'||s.startsWith('pg/'))throw Error('driver');return n(s,c)}});await import('./dist/lifecycle.js');`;
  const child=spawnSync(process.execPath,['--input-type=module','-e',script],{cwd:new URL('..',import.meta.url),encoding:'utf8',timeout:5000});assert.equal(child.status,0,child.stderr);
});
test('inherited, nonenumerable and symbol options are rejected before callback',async()=>{
  const inputs=[Object.assign(Object.create({}),options()),options(),options()];
  Object.defineProperty(inputs[1],'document_id',{value:'document',enumerable:false});
  inputs[2][Symbol('extra')]='invalid';
  for(const input of inputs){const {resource,lifecycle}=fixture();await assert.rejects(lifecycle.tombstone(input),InvalidRequest);assert.equal(resource.leases,0);}
});
test('deadline getters cannot execute during options validation',async()=>{
  let accessed=false;const input=options();Object.defineProperty(input,'deadline',{enumerable:true,get(){accessed=true;return now()+1;}});
  await assert.rejects(fixture().lifecycle.tombstone(input),InvalidRequest);assert.equal(accessed,false);
});
test('unsafe scope identifiers fail before authorizer or lease',async()=>{
  const {resource,lifecycle}=fixture(async()=>assert.fail('authorizer called'));
  for(const change of [{tenant_id:'\0'},{principal_id:'\0'},{authorization_revision:'\0'},{grant_ids:['\0']}]){
    await assert.rejects(lifecycle.tombstone({...options(),scope:parse_scope({...scope(),...change})}),InvalidRequest);
  }
  assert.equal(resource.leases,0);
});
test('oversized or malformed creation timestamp restores parent after delete',async()=>{
  for(const timestamp of ['x'.repeat(129),'','\0',null]){
    const {client,lifecycle}=fixture();client.document[1]=true;client.deleteRows=[[timestamp]];
    await assert.rejects(lifecycle.purge_tombstoned(options()),IntegrityViolation);assert.equal(client.children,3);assert.deepEqual(client.document,['generation',true,'auth']);
  }
});

const shared=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/lifecycle.json',import.meta.url),'utf8'));
for(const example of shared.cases){
  test(`shared lifecycle ${example.name}`,async()=>{
    const {client,lifecycle}=fixture();
    client.document=structuredClone(example.row);
    const method=example.operation==='purge'?'purge_tombstoned':'tombstone';
    const operation=lifecycle[method]({...options(),expected_generation_id:example.expected_generation_id});
    if(example.error)await assert.rejects(operation,error=>error.code===example.error);
    else assert.deepEqual(await operation,example.expected);
  });
}

test('purge rejects an unsafe FK or disabled-trigger catalog before parent deletion',async()=>{
  const {client,lifecycle}=fixture();
  client.document[1]=true;
  client.purgeCatalog=false;
  await assert.rejects(lifecycle.purge_tombstoned(options()),UnsupportedCapability);
  assert.equal(client.children,3);
  assert.ok(!client.calls.some(query=>query.text===_PURGE_SQL));
});

test('optional vector purge catalog retains exact scoped cascade guards',()=>{
  // Structural coverage; native acceptance probes catalog behavior and cascades.
  const query=_PURGE_CATALOG_SQL.replace(/\s+/g,' ');
  for(const expected of [
    'SELECT * FROM base_expected UNION ALL',
    'WHERE EXISTS (SELECT 1 FROM known_vector_storage)',
    "('chunk_vectors_fake_1536','chunks',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','chunk_id']",
    "('chunk_vectors_fake_1536','index_generations',ARRAY['tenant_id','collection_id','document_id','revision_id','generation_id','embedding_profile']",
    '(SELECT count(*) FROM actual)=(SELECT count(*) FROM expected)',
    "a.child_schema='cragkit'",
    'a.child_columns=e.child_columns AND a.parent_columns=e.parent_columns',
    'a.delete_action=e.delete_action AND a.convalidated',
    "WHERE relkind<>'r' OR NOT relrowsecurity",
    "'chunks','chunk_vectors_fake_1536','document_grants','ingestion_jobs','chunk_lexical')",
    "t.tgenabled NOT IN ('O','A')",
  ])assert.ok(query.includes(expected),expected);
});
