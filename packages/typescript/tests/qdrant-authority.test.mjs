import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PoolResource,parse_pool_config} from '../dist/postgres-pool.js';
import {PostgresQdrantAuthority,AUTHORITY_HISTORY,AUTHORITY_CATALOG_SQL,AUTHORITY_ROLE_SQL,AUTHORITY_HISTORY_SQL,AUTHORITY_SCOPE_SQL,AUTHORITY_FINGERPRINT_SQL,EXPECTED_AUTHORITY_FINGERPRINT} from '../dist/qdrant-authority.js';
import {SOURCE_ROW_FIELDS,validate_nomination} from '../dist/qdrant-source-contract.js';
import {parse_request,parse_scope} from '../dist/requests.js';
import {parse_config} from '../dist/qdrant-contract.js';
import {DeadlineExceeded,IntegrityViolation,InvalidRequest,ProviderUnavailable,UnauthorizedScope,UnsupportedCapability} from '../dist/errors.js';
const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_sources.json',import.meta.url),'utf8'));
const deadline=()=>performance.now()/1000+2;
function resolve(v){if(typeof v==='string'&&v.startsWith('$ref:')){let out=fixture;for(const k of v.slice(5).split('.'))out=out[k];return resolve(out);}if(Array.isArray(v))return v.map(resolve);if(v&&typeof v==='object'){if(v.encoding==='utf8')return Buffer.from(v.value,'utf8');return Object.fromEntries(Object.entries(v).map(([k,x])=>[k,resolve(x)]));}return v;}
const request=parse_request(fixture.request),scope=parse_scope(fixture.scope),config=parse_config({backend_namespace:'fixture-local',physical_collection:'cragkit_qc_r1',collection_incarnation:'inc-1',dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse});
const nomination=validate_nomination(resolve(fixture.nomination),request,scope,config);
function setup(){const state={queries:[],clients:[],catalog:true,role:true,fingerprint:[[EXPECTED_AUTHORITY_FINGERPRINT]],history:AUTHORITY_HISTORY.map(r=>[...r]),rows:[SOURCE_ROW_FIELDS.map(k=>resolve(fixture.base_row)[k])],queryError:null,rollbackFail:false,dirtyRollback:false,startStatus:'I',wait:null};
  const pool={ends:0,async connect(){const client={status:state.startStatus,releases:[],getTransactionStatus(){return this.status;},release(destroy=false){this.releases.push(destroy);},async query(q){state.queries.push(q);
    if(q.text.startsWith('BEGIN')){this.status='T';return {rows:[]};}if(q.text==='ROLLBACK'){if(state.rollbackFail)throw Error('private rollback');this.status=state.dirtyRollback?'T':'I';return {rows:[]};}
    if(q.text===AUTHORITY_CATALOG_SQL)return {rows:[[state.catalog]]};if(q.text===AUTHORITY_ROLE_SQL)return {rows:[[state.role]]};if(q.text===AUTHORITY_HISTORY_SQL)return {rows:state.history};
    if(q.text===AUTHORITY_FINGERPRINT_SQL)return {rows:state.fingerprint};
    if(q.text.includes('FROM cragkit_qdrant.members m')){if(state.wait)await state.wait;if(state.queryError)throw state.queryError;return {rows:state.rows};}return {rows:[]};}};state.clients.push(client);return client;},async end(){this.ends++;}};
  const resource=new PoolResource(parse_pool_config({host:'host.invalid',dbname:'synthetic',user:'reader',sslrootcert:'/fake/ca',passfile:'/fake/pass',release_timeout:0.05,close_timeout:0.1}),{pool});return {state,pool,resource,authority:new PostgresQdrantAuthority(resource)};
}
function read(x,extra={}){return x.authority.read(nomination,request,scope,config,{deadline:deadline(),retained:false,max_source_bytes:13,...extra});}
test('explicit read-only initialization checks actual role, catalog and exact independent history',async()=>{
  const x=setup();await x.authority.initialize({deadline:deadline()});assert.ok(x.state.queries.some(q=>q.text==='BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY'));assert.ok(x.state.queries.some(q=>q.text===AUTHORITY_ROLE_SQL));assert.ok(x.state.queries.some(q=>q.text===AUTHORITY_HISTORY_SQL));assert.equal(x.state.clients[0].status,'I');assert.deepEqual(x.state.clients[0].releases,[false]);assert.equal(x.pool.ends,0);await x.resource.close();
});
test('incompatible catalog/history and unsafe role fail closed with clean rollback',async()=>{
  for(const [field,value,ErrorType]of [['catalog',false,UnsupportedCapability],['role',false,UnauthorizedScope],['history',[],UnsupportedCapability],['history',[['0001_authority','wrong']],UnsupportedCapability]]){const x=setup();x.state[field]=value;await assert.rejects(x.authority.initialize({deadline:deadline()}),ErrorType);assert.equal(x.state.clients[0].status,'I');await x.resource.close();}
});
test('full scoped joins, five transaction-local settings, byte CASE gate and required filters precede LIMIT',async()=>{
  const x=setup();const rows=await read(x);assert.equal(rows[0].point_id,nomination.point_id);
  const scoped=x.state.queries.find(q=>q.text===AUTHORITY_SCOPE_SQL);assert.deepEqual(scoped.values,[scope.tenant_id,request.collection,scope.principal_id,JSON.stringify(scope.grant_ids),scope.authorization_revision]);
  const source=x.state.queries.find(q=>q.text.includes('FROM cragkit_qdrant.members m'));assert.equal(source.values[0],13);assert.ok(source.text.includes('CASE WHEN octet_length'));assert.ok(source.text.includes('g.published AND d.active_generation_id=g.generation_id'));assert.ok(source.text.includes('d.kind = $16'));assert.ok(source.text.includes('d.authorization_revision=$10'));assert.ok(source.text.includes('d.grant_ids && $12::text[]'));assert.ok(source.text.endsWith('LIMIT 2'));assert.equal(x.state.clients[0].status,'I');await x.resource.close();
});
test('retained read keeps fresh scope/filter checks and never demands active generation',async()=>{
  const x=setup();await read(x,{retained:true});const sql=x.state.queries.find(q=>q.text.includes('FROM cragkit_qdrant.members m')).text;assert.ok(sql.includes('g.ever_published AND TRUE'));assert.ok(!sql.includes('d.active_generation_id=g.generation_id'));assert.ok(sql.includes('d.kind = $16'));await x.resource.close();
});
test('duplicate/short driver rows reject and no raw error text escapes',async()=>{
  for(const rows of [[[]],[[],[]]]){const x=setup();x.state.rows=rows;await assert.rejects(read(x),IntegrityViolation);await x.resource.close();}
  const x=setup();x.state.queryError=new Error('private credentials raw query');await assert.rejects(read(x),e=>e instanceof ProviderUnavailable&&!String(e).includes('private'));assert.equal(x.state.clients[0].status,'I');await x.resource.close();
});
test('failed or dirty rollback destroys the borrowed client instead of reusing it',async()=>{
  for(const field of ['rollbackFail','dirtyRollback']){const x=setup();x.state[field]=true;await assert.rejects(read(x),ProviderUnavailable);assert.deepEqual(x.state.clients[0].releases,[true]);assert.equal(x.pool.ends,0);await x.resource.close();}
  const dirty=setup();dirty.state.startStatus='T';await assert.rejects(read(dirty),InvalidRequest);assert.deepEqual(dirty.state.clients[0].releases,[true]);await dirty.resource.close();
});
test('midflight deadline/cancellation drops the connection and observes late settlement',async()=>{
  for(const mode of ['deadline','cancel']){
    const x=setup();let finish;x.state.wait=new Promise(r=>finish=r);const controller=new AbortController();
    const pending=read(x,{deadline:mode==='deadline'?performance.now()/1000+0.02:deadline(),signal:controller.signal});const rejected=assert.rejects(pending,mode==='deadline'?DeadlineExceeded:e=>e.name==='AbortError');await new Promise(r=>setImmediate(r));if(mode==='cancel')controller.abort();await rejected;assert.ok(x.state.clients[0].releases.includes(true));finish();await x.resource.close();
  }
});
test('malformed/expired deadline refuses checkout and unsafe SQL profiles remain parameterized',async()=>{
  const x=setup();for(const value of [NaN,Infinity,Number.MAX_SAFE_INTEGER+1])await assert.rejects(x.authority.initialize({deadline:value}),InvalidRequest);await assert.rejects(x.authority.initialize({deadline:performance.now()/1000-1}),DeadlineExceeded);assert.equal(x.state.clients.length,0);
  assert.ok(AUTHORITY_ROLE_SQL.includes('current_user = session_user'));assert.ok(AUTHORITY_ROLE_SQL.includes('pg_has_role'));assert.ok(AUTHORITY_ROLE_SQL.includes('pg_write_all_data'));assert.ok(AUTHORITY_ROLE_SQL.includes('has_any_column_privilege'));await x.resource.close();
});
test('independent statement cancellation is operational until the shared deadline elapsed',async()=>{
  const x=setup();x.state.queryError=Object.assign(new Error('private cancellation'),{code:'57014'});await assert.rejects(read(x),ProviderUnavailable);await x.resource.close();
});
test('embedded catalog query is byte-exact and missing/drifted fingerprints fail initialization',async()=>{
  assert.equal(AUTHORITY_FINGERPRINT_SQL,readFileSync(new URL('../../../contracts/QDRANT_AUTHORITY_CATALOG_V5.sql',import.meta.url),'utf8'));
  for(const fingerprint of [[],[['changed']],[[EXPECTED_AUTHORITY_FINGERPRINT],[EXPECTED_AUTHORITY_FINGERPRINT]]]){
    const x=setup();x.state.fingerprint=fingerprint;await assert.rejects(x.authority.initialize({deadline:deadline()}),UnsupportedCapability);await x.resource.close();
  }
});
test('each fresh lease rechecks role privileges before reading source bytes',async()=>{
  const x=setup();await x.authority.initialize({deadline:deadline()});x.state.role=false;
  await assert.rejects(read(x),UnauthorizedScope);
  assert.equal(x.state.queries.filter(q=>q.text.includes('FROM cragkit_qdrant.members m')).length,0);
  assert.equal(x.state.clients.at(-1).status,'I');await x.resource.close();
});
