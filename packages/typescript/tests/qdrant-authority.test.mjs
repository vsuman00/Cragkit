import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PoolResource,parse_pool_config} from '../dist/postgres-pool.js';
import {PostgresQdrantAuthority,AUTHORITY_HISTORY,AUTHORITY_CATALOG_SQL,AUTHORITY_ROLE_SQL,AUTHORITY_HISTORY_SQL,AUTHORITY_SCOPE_SQL,AUTHORITY_FINGERPRINT_SQL,EXPECTED_AUTHORITY_FINGERPRINT,AUTHORITY_PUBLICATION_HISTORY,AUTHORITY_PUBLICATION_CATALOG_SQL,EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT,AUTHORITY_ATTESTATION_HISTORY,AUTHORITY_ATTESTATION_CATALOG_SQL,EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT} from '../dist/qdrant-authority.js';
import {SOURCE_ROW_FIELDS,validate_nomination} from '../dist/qdrant-source-contract.js';
import {AUTHORITY_SECURITY_GUARD_HISTORY,EXPECTED_SECURITY_GUARD_AUTHORITY_FINGERPRINT,AUTHORITY_SECURITY_GUARD_CATALOG_SQL,SECURITY_GUARD_OWNER_SQL,publication_schema_profile} from '../dist/qdrant-authority.js';
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
    if(q.text===AUTHORITY_CATALOG_SQL||q.text===AUTHORITY_PUBLICATION_CATALOG_SQL||q.text===AUTHORITY_ATTESTATION_CATALOG_SQL||q.text===AUTHORITY_SECURITY_GUARD_CATALOG_SQL)return {rows:[[state.catalog]]};if(q.text===SECURITY_GUARD_OWNER_SQL)return {rows:state.ownerRows??[[true]]};if(q.text===AUTHORITY_ROLE_SQL)return {rows:[[state.role]]};if(q.text===AUTHORITY_HISTORY_SQL){if(state.historyError)throw state.historyError;return {rows:state.history};}
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

test('exact source and publication profiles select their own structural check and fingerprint', async () => {
  const captured = JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_publication_catalog.json', import.meta.url), 'utf8'));
  assert.deepEqual(AUTHORITY_PUBLICATION_HISTORY, captured.history);
  assert.equal(EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT, captured.catalog_fingerprint);
  assert.ok(AUTHORITY_HISTORY_SQL.endsWith('LIMIT 5'));
  for (const publication of [false, true]) {
    const x = setup();
    if (publication) {
      x.state.history = AUTHORITY_PUBLICATION_HISTORY.map(row => [...row]);
      x.state.fingerprint = [[EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT]];
    }
    await x.authority.initialize({deadline: deadline()});
    const expected = publication ? AUTHORITY_PUBLICATION_CATALOG_SQL : AUTHORITY_CATALOG_SQL;
    const other = publication ? AUTHORITY_CATALOG_SQL : AUTHORITY_PUBLICATION_CATALOG_SQL;
    const historyIndex = x.state.queries.findIndex(query => query.text === AUTHORITY_HISTORY_SQL);
    const catalogIndex = x.state.queries.findIndex(query => query.text === expected);
    assert.ok(historyIndex >= 0 && catalogIndex > historyIndex);
    assert.equal(x.state.queries.some(query => query.text === other), false);
    await x.resource.close();
  }
});

test('history and fingerprints cannot cross profiles or accept unknown extensions', async () => {
  const histories = [
    [], [null], null, [['0002_publication', AUTHORITY_PUBLICATION_HISTORY[1][1]]],
    [...AUTHORITY_PUBLICATION_HISTORY, ['0003_unknown', 'a'.repeat(64)]],
    [...AUTHORITY_PUBLICATION_HISTORY].reverse(),
    [['0001_authority', AUTHORITY_HISTORY[0][1], 'extra']],
    [['0001_authority']], [[null, AUTHORITY_HISTORY[0][1]]],
    [...AUTHORITY_PUBLICATION_HISTORY, ...AUTHORITY_HISTORY],
  ];
  for (const history of histories) {
    const x = setup();
    x.state.history = history;
    await assert.rejects(x.authority.initialize({deadline: deadline()}), UnsupportedCapability);
    assert.equal(x.state.queries.some(query => query.text === AUTHORITY_CATALOG_SQL || query.text === AUTHORITY_PUBLICATION_CATALOG_SQL), false);
    await x.resource.close();
  }
  for (const publication of [false, true]) {
    const x = setup();
    x.state.history = publication ? AUTHORITY_PUBLICATION_HISTORY.map(row => [...row]) : AUTHORITY_HISTORY.map(row => [...row]);
    x.state.fingerprint = [[publication ? EXPECTED_AUTHORITY_FINGERPRINT : EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT]];
    await assert.rejects(x.authority.initialize({deadline: deadline()}), UnsupportedCapability);
    await x.resource.close();
  }
});

test('publication structural profile is strict and old structural probe remains independent', async () => {
  assert.ok(AUTHORITY_CATALOG_SQL.includes("polcmd<>'r'"));
  assert.ok(!AUTHORITY_CATALOG_SQL.includes('publication_intents'));
  assert.ok(AUTHORITY_PUBLICATION_CATALOG_SQL.includes("c.relkind='r'"));
  assert.ok(AUTHORITY_PUBLICATION_CATALOG_SQL.includes('=13'));
  assert.ok(AUTHORITY_PUBLICATION_CATALOG_SQL.includes('=12'));
  assert.ok(AUTHORITY_PUBLICATION_CATALOG_SQL.includes('c.relrowsecurity AND c.relforcerowsecurity'));
  assert.ok(AUTHORITY_PUBLICATION_CATALOG_SQL.includes('NOT k.convalidated'));
  assert.ok(AUTHORITY_PUBLICATION_CATALOG_SQL.includes('p.prosecdef'));
  assert.ok(AUTHORITY_PUBLICATION_CATALOG_SQL.includes("t.tgenabled<>'O'"));
  const x = setup();
  x.state.history = AUTHORITY_PUBLICATION_HISTORY.map(row => [...row]);
  x.state.fingerprint = [[EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT]];
  x.state.catalog = false;
  await assert.rejects(x.authority.initialize({deadline: deadline()}), UnsupportedCapability);
  await x.resource.close();
});

test('restricted reader SQL refuses operational reads and helper or capability escalation', async () => {
  assert.ok(AUTHORITY_ROLE_SQL.includes("'cragkit_qdrant_writer','cragkit_qdrant_supervisor'"));
  assert.ok(AUTHORITY_ROLE_SQL.includes("pg_has_role(current_user,r.oid,'MEMBER')"));
  assert.ok(AUTHORITY_ROLE_SQL.includes("has_any_column_privilege(current_user,c.oid,'SELECT')"));
  assert.ok(AUTHORITY_ROLE_SQL.includes("c.relname NOT IN('documents','document_revisions','generations','members','schema_migrations')"));
  assert.ok(AUTHORITY_ROLE_SQL.includes("p.oid IS DISTINCT FROM to_regprocedure"));
  for (const publication of [false, true]) {
    const x = setup();
    if (publication) {
      x.state.history = AUTHORITY_PUBLICATION_HISTORY.map(row => [...row]);
      x.state.fingerprint = [[EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT]];
    }
    await x.authority.initialize({deadline: deadline()});
    x.state.role = false;
    await assert.rejects(read(x), UnauthorizedScope);
    assert.equal(x.state.queries.some(query => query.text.includes('FROM cragkit_qdrant.members m')), false);
    await x.resource.close();
  }
});

test('malformed history cells cannot invoke accessors serialization or proxy hooks', async () => {
  let calls = 0;
  const cell = {toJSON() { calls++; throw Error('private'); }};
  const accessor = [...AUTHORITY_HISTORY[0]];
  Object.defineProperty(accessor, '0', {get() { calls++; throw Error('private'); }});
  const proxy = new Proxy([...AUTHORITY_HISTORY[0]], {get() { calls++; throw Error('private'); }});
  const outer = [[...AUTHORITY_HISTORY[0]]];
  Object.defineProperty(outer, '0', {get() { calls++; throw Error('private'); }});
  const outerProxy = new Proxy([[...AUTHORITY_HISTORY[0]]], {get() { calls++; throw Error('private'); }});
  const cycle = []; cycle.push(cycle);
  for (const history of [[[cell, 'checksum']], [accessor], [proxy], [cycle], outer, outerProxy]) {
    const x = setup();
    x.state.history = history;
    await assert.rejects(x.authority.initialize({deadline: deadline()}), UnsupportedCapability);
    await x.resource.close();
  }
  assert.equal(calls, 0);
});

test('history shape mapping preserves deadline and redacted operational failures', async () => {
  for (const [error, expected] of [[new DeadlineExceeded(), DeadlineExceeded], [new Error('private history failure'), ProviderUnavailable]]) {
    const x = setup();
    x.state.historyError = error;
    await assert.rejects(x.authority.initialize({deadline: deadline()}), result => result instanceof expected && !String(result).includes('private'));
    await x.resource.close();
  }
});

test('source authority accepts the frozen exact attestation catalog with its own fingerprint',async()=>{
  const captured=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_attestation_catalog.json',import.meta.url),'utf8'));
  assert.deepEqual(AUTHORITY_ATTESTATION_HISTORY,captured.history);assert.equal(EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT,captured.catalog_fingerprint);
  const x=setup();x.state.history=AUTHORITY_ATTESTATION_HISTORY.map(row=>[...row]);x.state.fingerprint=[[EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT]];
  try{await x.authority.initialize({deadline:deadline()});assert(x.state.queries.some(query=>query.text===AUTHORITY_ATTESTATION_CATALOG_SQL));assert.equal(x.state.queries.some(query=>query.text===AUTHORITY_PUBLICATION_CATALOG_SQL),false);}
  finally{await x.resource.close();}
});
test('attestation source profile rejects hash/fingerprint mismatch, fourth history and new grant drift',async()=>{
  for(const change of [state=>{state.history[2][1]='a'.repeat(64);},state=>{state.fingerprint=[[EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT]];},state=>{state.history.push(['0004_unknown','a'.repeat(64)]);}]){
    const x=setup();x.state.history=AUTHORITY_ATTESTATION_HISTORY.map(row=>[...row]);x.state.fingerprint=[[EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT]];change(x.state);
    try{await assert.rejects(x.authority.initialize({deadline:deadline()}),UnsupportedCapability);}finally{await x.resource.close();}
  }
  const x=setup();x.state.history=AUTHORITY_ATTESTATION_HISTORY.map(row=>[...row]);x.state.fingerprint=[[EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT]];
  try{await x.authority.initialize({deadline:deadline()});x.state.role=false;await assert.rejects(read(x),UnauthorizedScope);assert.equal(x.state.queries.some(query=>query.text.includes('FROM cragkit_qdrant.members m')),false);}finally{await x.resource.close();}
});

function guardSetup(){
  const x=setup();x.state.history=AUTHORITY_SECURITY_GUARD_HISTORY.map(row=>[...row]);
  x.state.fingerprint=[[EXPECTED_SECURITY_GUARD_AUTHORITY_FINGERPRINT]];return x;
}
test('profile4 pins exact accepted metadata and keeps writer/recovery selection unsupported',async()=>{
  const captured=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_security_guard_catalog.json',import.meta.url),'utf8'));
  assert.deepEqual(AUTHORITY_SECURITY_GUARD_HISTORY,captured.history);
  assert.equal(EXPECTED_SECURITY_GUARD_AUTHORITY_FINGERPRINT,captured.catalog_fingerprint);
  assert.ok(AUTHORITY_HISTORY_SQL.endsWith('LIMIT 5'));
  assert.throws(()=>publication_schema_profile(AUTHORITY_SECURITY_GUARD_HISTORY),UnsupportedCapability);
  assert.ok(AUTHORITY_PUBLICATION_CATALOG_SQL.includes("AND p.prosecdef)"));
  assert.ok(AUTHORITY_ATTESTATION_CATALOG_SQL.includes("AND p.prosecdef)"));
  assert.ok(AUTHORITY_SECURITY_GUARD_CATALOG_SQL.includes('p.pronargs<>22'));
  assert.ok(AUTHORITY_SECURITY_GUARD_CATALOG_SQL.includes('p.proconfig IS DISTINCT FROM'));
  const x=guardSetup();
  try{
    await x.authority.initialize({deadline:deadline()});
    assert.ok(x.state.queries.some(query=>query.text===AUTHORITY_SECURITY_GUARD_CATALOG_SQL));
    assert.ok(x.state.queries.some(query=>query.text===SECURITY_GUARD_OWNER_SQL));
    assert.equal(x.state.queries.some(query=>query.text===AUTHORITY_ATTESTATION_CATALOG_SQL),false);
    assert.equal(x.state.queries.some(query=>/^SELECT cragkit_qdrant\.lock_current_security\(/.test(query.text)),false);
    assert.equal(x.pool.ends,0);
  }finally{await x.resource.close();}
});

test('profile4 validates history body fingerprint and owner privileges before every source read including direct reads',async()=>{
  for(const initialized of [false,true]){
    const x=guardSetup();
    try{
      if(initialized)await x.authority.initialize({deadline:deadline()});
      let start=x.state.queries.length;await read(x);
      let queries=x.state.queries.slice(start),source=queries.findIndex(query=>query.text.includes('FROM cragkit_qdrant.members m'));
      for(const sql of [AUTHORITY_HISTORY_SQL,AUTHORITY_SECURITY_GUARD_CATALOG_SQL,AUTHORITY_FINGERPRINT_SQL,SECURITY_GUARD_OWNER_SQL])
        assert.ok(queries.findIndex(query=>query.text===sql)>=0&&queries.findIndex(query=>query.text===sql)<source);
      x.state.ownerRows=[[false]];start=x.state.queries.length;
      await assert.rejects(read(x),UnsupportedCapability);
      assert.equal(x.state.queries.slice(start).some(query=>query.text.includes('FROM cragkit_qdrant.members m')),false);
      x.state.ownerRows=[[true]];await read(x);
      x.state.fingerprint=[['changed-body-or-policy']];start=x.state.queries.length;
      await assert.rejects(read(x),UnsupportedCapability);
      assert.equal(x.state.queries.slice(start).some(query=>query.text.includes('FROM cragkit_qdrant.members m')),false);
    }finally{await x.resource.close();}
  }
});

for(const drift of ['checksum','suffix','downgrade','catalog','owner'])test(`profile4 ${drift} drift cannot fall back to an old source profile`,async()=>{
  const x=guardSetup();
  try{
    await x.authority.initialize({deadline:deadline()});
    if(drift==='checksum')x.state.history[3][1]='f'.repeat(64);
    if(drift==='suffix')x.state.history.push(['0005_unknown','f'.repeat(64)]);
    if(drift==='downgrade'){x.state.history=AUTHORITY_ATTESTATION_HISTORY.map(row=>[...row]);x.state.fingerprint=[[EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT]];}
    if(drift==='catalog')x.state.catalog=false;
    if(drift==='owner')x.state.ownerRows=[[false]];
    const start=x.state.queries.length;await assert.rejects(read(x),UnsupportedCapability);
    assert.equal(x.state.queries.slice(start).some(query=>query.text.includes('FROM cragkit_qdrant.members m')),false);
    assert.equal(x.state.clients.at(-1).status,'I');
  }finally{await x.resource.close();}
});

test('owner metadata is a complete read-only catalog predicate rather than a guard call or minimal subset',()=>{
  for(const required of ['pg_catalog.pg_auth_members','pg_catalog.pg_namespace','pg_catalog.pg_database','pg_catalog.pg_class',
    'pg_catalog.pg_type','pg_catalog.pg_proc','pg_catalog.pg_policy','has_table_privilege','has_column_privilege','has_function_privilege',
    'has_schema_privilege','admin_option','inherit_option','set_option','m.grantor=10','m.grantor=operator_id',
    'scope_visible(text,text,text[],text[],text,boolean)','valid_identity_array(text[])','scope_grants()',
    'security_guard_document_update','polwithcheck','a.is_grantable','rolcanlogin','rolcreaterole','rolbypassrls','rolinherit'])assert.ok(SECURITY_GUARD_OWNER_SQL.includes(required),required);
  assert.equal(/\b(?:INSERT INTO|UPDATE cragkit|DELETE FROM|SET ROLE|SET LOCAL|FOR UPDATE|FOR SHARE)\b/.test(SECURITY_GUARD_OWNER_SQL),false);
  assert.equal(SECURITY_GUARD_OWNER_SQL.includes('payload_bytes'),false);
  assert.equal(SECURITY_GUARD_OWNER_SQL.includes('canonical_utf8'),false);
});

test('profile4 owner result rejects malformed native scalars without serialization hooks',async()=>{
  let called=0;
  const cell={toJSON(){called++;return true;}},accessor=[];
  Object.defineProperty(accessor,'0',{get(){called++;return true;},enumerable:true});
  for(const ownerRows of [[],[[1]],[[cell]],[accessor],new Proxy([[true]],{get(){called++;return [];}})]){
    const x=guardSetup();x.state.ownerRows=ownerRows;
    try{await assert.rejects(x.authority.initialize({deadline:deadline()}),UnsupportedCapability);}
    finally{await x.resource.close();}
  }
  assert.equal(called,0);
});

test('profile4 retained/current source filters and byte budgets remain parameterized after metadata checks',async()=>{
  const x=guardSetup();
  try{
    await x.authority.initialize({deadline:deadline()});await read(x,{retained:true,max_source_bytes:7});
    const source=x.state.queries.find(query=>query.text.includes('FROM cragkit_qdrant.members m'));
    assert.equal(source.values[0],7);assert.ok(source.text.includes('g.ever_published AND TRUE'));
    assert.ok(source.text.includes('d.authorization_revision=$10'));assert.ok(source.text.includes('d.kind = $16'));
    assert.equal(x.pool.ends,0);
  }finally{await x.resource.close();}
});
