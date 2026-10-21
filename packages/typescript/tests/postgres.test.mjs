import test from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, writeFile, chmod, rm, symlink } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { PoolResource, parse_pool_config, now } from '../dist/postgres-pool.js';
import { InvalidRequest, ProviderUnavailable, DeadlineExceeded } from '../dist/errors.js';

const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => { resolve=a; reject=b; }); return {promise,resolve,reject}; };
const tick = () => new Promise(resolve => setImmediate(resolve));
const options = () => ({ deadline: now()+1 });
function config(extra={}) { return parse_pool_config({host:'host.invalid',dbname:'synthetic',user:'runtime',sslrootcert:'/synthetic/ca',passfile:'/synthetic/pass',...extra}); }
class Client {
  releases=[]; status='I'; queries=[];
  getTransactionStatus() { return this.status; }
  async query(query) { this.queries.push(query); return {rows:[]}; }
  release(destroy=false) { this.releases.push(destroy); }
}
class Pool {
  clients=[]; ends=0;
  async connect() { const client=new Client(); this.clients.push(client); return client; }
  async end() { this.ends++; }
}
async function owned(callback, extra={}) {
  const dir=await mkdtemp(join(tmpdir(),'cragkit-ts-pool-'));
  try {
    const ca=join(dir,'ca'); const pass=join(dir,'pass');
    await writeFile(ca,'synthetic'); await writeFile(pass,'synthetic',{mode:0o600}); await chmod(pass,0o600);
    await callback(config({sslrootcert:ca,passfile:pass,...extra}),dir);
  } finally { await rm(dir,{recursive:true,force:true}); }
}
for (const value of [NaN,Infinity,-Infinity,0,-1,31]) test(`invalid startup timeout ${value}`,()=>assert.throws(()=>config({startup_timeout:value}),InvalidRequest));
for (const extra of [{host:'postgresql://host.invalid/db'},{host:'a,b'},{dbname:'x=y'},{user:' '},{max_size:3},{max_size:true},{max_waiting:17},{max_waiting:-1},{passfile:'relative'},{sslrootcert:'relative'},{release_timeout:3,close_timeout:2},{unknown:true}]) {
  test(`strict config ${JSON.stringify(extra)}`,()=>assert.throws(()=>config(extra),InvalidRequest));
}
test('configuration snapshots are frozen',()=>assert.equal(Object.isFrozen(config()),true));
test('borrowed pool never opens or ends caller resources',async()=>{
  const pool=new Pool(); const resource=new PoolResource(config(),{pool});
  await resource.open(); await resource.open();
  await resource.withLease(options(),async client=>assert.equal(client.getTransactionStatus(),'I'));
  await resource.close(); await resource.close();
  assert.equal(pool.ends,0); assert.deepEqual(pool.clients[0].releases,[false]);
  await assert.rejects(resource.withLease(options(),async()=>{}),ProviderUnavailable);
});
test('owned startup and close are explicit and idempotent',()=>owned(async cfg=>{
  const pool=new Pool(); let calls=0;
  const resource=new PoolResource(cfg,{factory:()=>{calls++;return pool;}});
  assert.equal(calls,0); await assert.rejects(resource.withLease(options(),async()=>{}),ProviderUnavailable);
  await resource.open(); await resource.open(); assert.equal(calls,1);
  assert.deepEqual(pool.clients[0].releases,[false]); await resource.close(); await resource.close(); assert.equal(pool.ends,1);
}));
test('close before open is terminal',()=>owned(async cfg=>{
  let calls=0; const resource=new PoolResource(cfg,{factory:()=>{calls++;return new Pool();}});
  await resource.close(); await assert.rejects(resource.open(),ProviderUnavailable); assert.equal(calls,0);
}));
test('owned startup rejects unsafe file metadata before factory',()=>owned(async cfg=>{
  await chmod(cfg.passfile,0o644); let called=false;
  const resource=new PoolResource(cfg,{factory:()=>{called=true;return new Pool();}});
  await assert.rejects(resource.open(),InvalidRequest); assert.equal(called,false); await resource.close();
}));
test('owned startup refuses symlink password files',()=>owned(async(cfg,dir)=>{
  const link=join(dir,'link'); await symlink(cfg.passfile,link);
  const resource=new PoolResource(config({...cfg,passfile:link}),{factory:()=>new Pool()});
  await assert.rejects(resource.open(),InvalidRequest); await resource.close();
}));
test('PG environment redirection is rejected without reading its value',()=>owned(async cfg=>{
  const prior=process.env.PGSERVICE; process.env.PGSERVICE='synthetic';
  try { const resource=new PoolResource(cfg,{factory:()=>new Pool()}); await assert.rejects(resource.open(),InvalidRequest); await resource.close(); }
  finally { if(prior===undefined)delete process.env.PGSERVICE;else process.env.PGSERVICE=prior; }
}));
test('caller body exception identity and cause survive',async()=>{
  const pool=new Pool(); const resource=new PoolResource(config(),{pool}); const cause=new Error('cause');const sentinel=new Error('caller',{cause});
  await assert.rejects(resource.withLease(options(),async()=>{throw sentinel;}),error=>error===sentinel&&error.cause===cause);
  assert.deepEqual(pool.clients[0].releases,[false]);await resource.close();
});
test('driver acquisition failure has fixed redacted error',async()=>{
  const pool=new Pool();pool.connect=async()=>{throw new Error('private-provider-token');};
  const resource=new PoolResource(config(),{pool});
  await assert.rejects(resource.withLease(options(),async()=>{}),error=>error instanceof ProviderUnavailable&&!String(error).includes('private'));
  await resource.close();
});
test('expired, malformed and preaborted leases do not acquire',async()=>{
  const pool=new Pool();const resource=new PoolResource(config(),{pool});
  for(const deadline of [NaN,Infinity,'bad']) await assert.rejects(resource.withLease({deadline},async()=>{}),InvalidRequest);
  await assert.rejects(resource.withLease({deadline:now()-1},async()=>{}),DeadlineExceeded);
  const controller=new AbortController();controller.abort('private-reason');
  await assert.rejects(resource.withLease({...options(),signal:controller.signal},async()=>{}),error=>error.name==='AbortError'&&!String(error).includes('private'));
  assert.equal(pool.clients.length,0);await resource.close();
});
test('zero queue saturates at one wrapper lease',async()=>{
  const pool=new Pool();const resource=new PoolResource(config({max_size:1,max_waiting:0}),{pool});const gate=deferred();const entered=deferred();
  const first=resource.withLease(options(),async()=>{entered.resolve();await gate.promise;});await entered.promise;
  await assert.rejects(resource.withLease(options(),async()=>assert.fail('admitted')),ProviderUnavailable);
  gate.resolve();await first;await resource.close();
});
test('aborted pending checkout returns its eventual client once',async()=>{
  const gate=deferred();const pool=new Pool();pool.connect=()=>gate.promise;const resource=new PoolResource(config(),{pool});const controller=new AbortController();
  const lease=resource.withLease({...options(),signal:controller.signal},async()=>assert.fail('entered'));controller.abort('private');
  await assert.rejects(lease,error=>error.name==='AbortError');const client=new Client();gate.resolve(client);await tick();
  assert.deepEqual(client.releases,[false]);await resource.close();
});
test('deadline destroys active client and stops lease',async()=>{
  const pool=new Pool();const resource=new PoolResource(config(),{pool});
  await assert.rejects(resource.withLease({deadline:now()+0.02},async()=>new Promise(()=>{})),DeadlineExceeded);
  assert.deepEqual(pool.clients[0].releases,[true]);await resource.close();
});
test('late checkout after event loop stall is rejected before body',async()=>{
  const pool=new Pool();const client=new Client();pool.connect=async()=>{const until=now()+0.025;while(now()<until){}return client;};
  const resource=new PoolResource(config(),{pool});
  await assert.rejects(resource.withLease({deadline:now()+0.01},async()=>assert.fail('late body')),DeadlineExceeded);
  assert.equal(client.releases.length,1);await resource.close();
});
test('close cancels active wrapper lease without ending borrowed pool',async()=>{
  const pool=new Pool();const resource=new PoolResource(config(),{pool});const entered=deferred();
  const lease=resource.withLease(options(),async()=>{entered.resolve();return new Promise(()=>{});});
  const outcome=assert.rejects(lease,error=>error.name==='AbortError');await entered.promise;await resource.close();await outcome;
  assert.equal(pool.ends,0);assert.deepEqual(pool.clients[0].releases,[true]);
});
test('close from own lease rejects rather than deadlocks',async()=>{
  const resource=new PoolResource(config(),{pool:new Pool()});
  await resource.withLease(options(),async()=>assert.rejects(resource.close(),InvalidRequest));await resource.close();
});
test('owned driver close failure is cached and redacted',()=>owned(async cfg=>{
  const pool=new Pool();pool.end=async()=>{pool.ends++;throw new Error('private-close');};const resource=new PoolResource(cfg,{factory:()=>pool});await resource.open();
  await assert.rejects(resource.close(),ProviderUnavailable);await assert.rejects(resource.close(),ProviderUnavailable);assert.equal(pool.ends,1);
}));
test('native harness refuses authorization before reading nonexistent private config',()=>{
  const child=spawnSync(process.execPath,['../../tools/check_typescript_postgres.mjs','--config','/nonexistent/private'],{cwd:new URL('..',import.meta.url),encoding:'utf8',timeout:5000});
  assert.equal(child.status,2);assert.equal(JSON.parse(child.stdout).code,'explicit_runtime_authorization_required');assert.equal(child.stderr,'');
});

import { PostgresSession, compile_filters, EXPECTED_HISTORY, _ROLE_SQL, _CATALOG_SQL, _HISTORY_SQL, _COLLECTION_SQL, _SCOPE_SQL } from '../dist/postgres-session.js';
import { parse_request, parse_scope } from '../dist/contracts.js';
import { UnauthorizedScope, UnsupportedCapability } from '../dist/errors.js';
const request=()=>parse_request({query:'synthetic',collection:'collection'});
const scope=tenant=>parse_scope({tenant_id:tenant,principal_id:'principal',authorization_revision:'revision',grant_ids:['grant']});
class SessionClient extends Client {
  role=[[true]];catalog=[[true]];history=EXPECTED_HISTORY.map(row=>[...row]);collection=[['0.1','native_fts.v1']];documents=[['document','revision','native_fts.v1']];gucs=[];failure;rollbackBad=false;
  async query(query) {
    this.queries.push(query);assert.equal(query.rowMode,'array');
    if(this.failure?.text===query.text)throw this.failure.error;
    if(query.text.startsWith('BEGIN'))this.status='T';
    if(query.text==='ROLLBACK'){this.status=this.rollbackBad?'E':'I';this.gucs=[];}
    const rows=query.text===_ROLE_SQL?this.role:query.text===_CATALOG_SQL?this.catalog:query.text===_HISTORY_SQL?this.history:query.text===_COLLECTION_SQL?this.collection:query.text.includes('SELECT d.document_id')?this.documents:[];
    if(query.text===_SCOPE_SQL)this.gucs=[...query.values];
    return {rows};
  }
}
function sessionFixture() {
  const client=new SessionClient();const pool=new Pool();pool.connect=async()=>client;
  const resource=new PoolResource(config(),{pool});return {client,pool,resource,session:new PostgresSession(resource)};
}
test('session validates runtime role, catalog and exact history then rolls back',async()=>{
  const {client,resource,session}=sessionFixture();await session.validate(options());
  assert.equal(client.status,'I');assert.equal(client.queries.at(-1).text,'ROLLBACK');assert.deepEqual(client.releases,[false]);await resource.close();
});
for(const [field,value,kind] of [['role',[[false]],UnauthorizedScope],['catalog',[[false]],UnsupportedCapability],['history',[],UnsupportedCapability],['collection',[['0.1','other']],UnsupportedCapability],['documents',[['document','revision','other']],UnsupportedCapability]]) {
  test(`fail closed for ${field}`,async()=>{
    const {client,resource,session}=sessionFixture();client[field]=value;
    await assert.rejects(session.transaction(request(),{...options(),scope:scope('tenant')},handle=>handle.visible_documents()),kind);
    assert.equal(client.status,'I');await resource.close();
  });
}
test('trusted scopes bind separately and rollback clears all local values',async()=>{
  const {client,resource,session}=sessionFixture();
  for(const tenant of ['tenant_a','tenant_b','tenant_a']) {
    await session.transaction(request(),{...options(),scope:scope(tenant)},async handle=>{
      assert.deepEqual(client.gucs,[tenant,'principal','revision','["grant"]']);
      const rows=await handle.visible_documents();assert.deepEqual(rows,[['document','revision']]);assert.ok(Object.isFrozen(rows)&&Object.isFrozen(rows[0]));
    });assert.deepEqual(client.gucs,[]);assert.equal(client.status,'I');
  }await resource.close();
});
test('filter compiler parameterizes malicious identifiers and nested membership',()=>{
  const filters=parse_request({query:'synthetic',collection:'collection',required_filters:[{op:'and',filters:[{op:'eq',field:'document_id',value:"x' OR TRUE --"},{op:'not',filter:{op:'in',field:'revision_id',values:['r1','r2']}}]}]}).required_filters;
  const [sql,values]=compile_filters(filters,7);assert.ok(sql.includes('$7')&&sql.includes('$8'));assert.ok(!sql.includes('OR TRUE'));assert.deepEqual(values,["x' OR TRUE --",['r1','r2']]);
});
test('unsupported filter capabilities reject before acquisition',async()=>{
  const {client,resource,session}=sessionFixture();const input=parse_request({query:'synthetic',collection:'collection',required_filters:[{op:'eq',field:'language',value:'en'}]});
  await assert.rejects(session.transaction(input,{...options(),scope:scope('tenant')},async()=>{}),UnsupportedCapability);assert.equal(client.queries.length,0);await resource.close();
});
test('document SQL values carry scope, filters and bounded limit',async()=>{
  const {client,resource,session}=sessionFixture();const input=parse_request({query:'synthetic',collection:'collection',required_filters:[{op:'eq',field:'document_id',value:'needle'}]});
  await session.transaction(input,{...options(),scope:scope('tenant')},handle=>handle.visible_documents({limit:3}));
  const query=client.queries.find(query=>query.text.includes('SELECT d.document_id'));assert.deepEqual(query.values,['tenant','collection','revision','revision','principal',['grant'],'needle',3]);assert.ok(query.text.includes('$7'));await resource.close();
});
test('escaped handles and invalid limits cannot issue queries',async()=>{
  const {resource,session}=sessionFixture();let saved;
  await session.transaction(request(),{...options(),scope:scope('tenant')},async handle=>{saved=handle;await assert.rejects(handle.visible_documents({limit:0}),InvalidRequest);});
  await assert.rejects(saved.visible_documents(),InvalidRequest);await resource.close();
});
test('existing caller transaction is rejected without rollback or query',async()=>{
  const {client,resource,session}=sessionFixture();client.status='T';await assert.rejects(session.validate(options()),InvalidRequest);assert.deepEqual(client.queries,[]);await resource.close();
});
test('rollback that returns nonidle destroys connection and fails safely',async()=>{
  const {client,resource,session}=sessionFixture();client.rollbackBad=true;await assert.rejects(session.validate(options()),ProviderUnavailable);assert.deepEqual(client.releases,[true]);await resource.close();
});
test('session body exception retains explicit cause after rollback',async()=>{
  const {client,resource,session}=sessionFixture();const cause=new Error('synthetic cause');const error=new Error('body',{cause});
  await assert.rejects(session.transaction(request(),{...options(),scope:scope('tenant')},async()=>{throw error;}),actual=>actual===error&&actual.cause===cause);assert.equal(client.status,'I');await resource.close();
});
for(const [code,kind] of [['57014',DeadlineExceeded],['42501',UnauthorizedScope],['42703',UnsupportedCapability],['XX000',ProviderUnavailable]])test(`driver SQLSTATE ${code} redacts details`,async()=>{
  const {client,resource,session}=sessionFixture();client.failure={text:_ROLE_SQL,error:Object.assign(new Error('private-source-password'),{code})};
  await assert.rejects(session.validate(options()),error=>error instanceof kind&&!String(error).includes('private'));await resource.close();
});
test('statement limits are positive integer millisecond strings',async()=>{
  const {client,resource,session}=sessionFixture();await session.validate(options());
  const timeouts=client.queries.filter(query=>query.text.includes("set_config('statement_timeout'"));assert.ok(timeouts.length>=3);for(const item of timeouts)assert.match(item.values[0],/^[1-9][0-9]*$/);await resource.close();
});
test('late body completion still rejects the absolute session deadline',async()=>{
  const {resource,session}=sessionFixture();await assert.rejects(session.transaction(request(),{deadline:now()+0.02,scope:scope('tenant')},async()=>{const until=now()+0.03;while(now()<until){};}),DeadlineExceeded);await resource.close();
});
test('synchronous driver connect failure is redacted',async()=>{
  const pool=new Pool();pool.connect=()=>{throw new Error('private-provider');};const resource=new PoolResource(config(),{pool});
  await assert.rejects(resource.withLease(options(),async()=>{}),error=>error instanceof ProviderUnavailable&&!String(error).includes('private'));await resource.close();
});
test('internal module imports have no optional driver, network or filesystem writes',()=>{
  const script=`
    import { registerHooks } from 'node:module';
    import { syncBuiltinESMExports } from 'node:module';
    import fs from 'node:fs'; import net from 'node:net'; import tls from 'node:tls'; import child from 'node:child_process';
    const deny=()=>{throw new Error('import side effect');};
    for(const name of ['writeFile','writeFileSync','appendFile','appendFileSync','mkdir','mkdirSync','unlink','unlinkSync','rm','rmSync'])fs[name]=deny;
    for(const name of ['writeFile','appendFile','mkdir','unlink','rm'])fs.promises[name]=deny;
    net.connect=deny;net.createConnection=deny;tls.connect=deny;
    child.spawn=deny;child.exec=deny;child.execFile=deny;child.spawnSync=deny;syncBuiltinESMExports();
    registerHooks({resolve(specifier,context,next){if(specifier==='pg'||specifier.startsWith('pg/'))throw new Error('optional driver import');return next(specifier,context);}});
    await import('./dist/index.js'); await import('./dist/postgres-pool.js'); await import('./dist/postgres-session.js');
  `;
  const result=spawnSync(process.execPath,['--input-type=module','-e',script],{cwd:new URL('..',import.meta.url),encoding:'utf8',timeout:5000});
  assert.equal(result.status,0,result.stderr);assert.equal(result.stdout,'');
});
