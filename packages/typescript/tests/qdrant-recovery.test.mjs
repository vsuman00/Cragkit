import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PoolResource,parse_pool_config,now} from '../dist/postgres-pool.js';
import {PostgresQdrantWriter} from '../dist/qdrant-writer.js';
import {ManagedQdrantSupervisor} from '../dist/qdrant-supervisor.js';
import {QdrantReconciliationVerifier} from '../dist/qdrant-reconciliation.js';
import {PostgresQdrantRecovery,RECOVERY_ROLE_SQL,RECOVERY_SECURITY_GUARD_ROLE_SQL,settlement_data,recovery_components} from '../dist/qdrant-recovery.js';
import {AUTHORITY_HISTORY_SQL,AUTHORITY_PUBLICATION_HISTORY,AUTHORITY_PUBLICATION_CATALOG_SQL,
  AUTHORITY_FINGERPRINT_SQL,EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT} from '../dist/qdrant-authority.js';
import {AUTHORITY_ATTESTATION_HISTORY,AUTHORITY_ATTESTATION_CATALOG_SQL,EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT,
  AUTHORITY_SECURITY_GUARD_HISTORY,AUTHORITY_SECURITY_GUARD_CATALOG_SQL,EXPECTED_SECURITY_GUARD_AUTHORITY_FINGERPRINT,SECURITY_GUARD_OWNER_SQL,publication_schema_profile} from '../dist/qdrant-authority.js';
import {InvalidRequest,UnsupportedCapability,ProviderUnavailable,UnauthorizedScope,IndexNotReady,DeadlineExceeded} from '../dist/errors.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_publication.json',import.meta.url),'utf8'));
const config={...fixture.physical,dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse};
const options=()=>({deadline:now()+5});
const context={scope:{tenant_id:'tenant-a',principal_id:'reader-a',grant_ids:[],authorization_revision:'auth-1'},
  collection:'docs',document_id:'doc-1',intent_id:'intent-1',owner_token:'00000000-0000-4000-8000-000000000001'};

/** These doubles exercise coordinator ordering; actual PostgreSQL/process proof is separate. */
function setup(){
  const state={backend:null,owner:['instance-1',context.intent_id,context.owner_token,1],role:true,
    pending:false,lost:false,queries:[],clients:[],physical:0,sealed:false,gate:true,ended:0,
    history:AUTHORITY_PUBLICATION_HISTORY.map(row=>[...row]),catalog:true,fingerprint:EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT};
  const pool={async end(){state.ended++;},async connect(){
    const client={status:'I',release(discard){this.discard=discard;},getTransactionStatus(){return this.status;},
      async query(query){
        const sql=query.text,p=query.values??[];
        state.queries.push(sql);
        if(sql.startsWith('BEGIN')){this.status='T';this.before=structuredClone({backend:state.backend,owner:state.owner});return {rows:[]};}
        if(sql==='ROLLBACK'){Object.assign(state,this.before);this.status='I';return {rows:[]};}
        if(sql==='COMMIT'){this.status='I';if(state.lost){state.lost=false;state.afterLost?.();throw Object.assign(Error('private'),{code:'08006'});}return {rows:[]};}
        if(sql===RECOVERY_ROLE_SQL||sql===RECOVERY_SECURITY_GUARD_ROLE_SQL)return {rows:state.roleRows??[[state.role]]};
        if(sql===AUTHORITY_HISTORY_SQL)return {rows:state.history};
        if([AUTHORITY_PUBLICATION_CATALOG_SQL,AUTHORITY_ATTESTATION_CATALOG_SQL,AUTHORITY_SECURITY_GUARD_CATALOG_SQL].includes(sql))return {rows:state.catalogRows??[[state.catalog]]};
        if(sql===AUTHORITY_FINGERPRINT_SQL)return {rows:[[state.fingerprint]]};
        if(sql===SECURITY_GUARD_OWNER_SQL){if(state.ownerWait)await state.ownerWait;return {rows:state.ownerRows??[[true]]};}
        if(sql.startsWith('SET ')||sql.startsWith('SELECT set_config'))return {rows:[]};
        if(sql.startsWith('INSERT INTO cragkit_qdrant.backend_instances')){
          state.backend=[p[0],p[1],p[2],p[3],1,'open',null];return {rows:[]};
        }
        if(sql.startsWith('SELECT instance_id FROM cragkit_qdrant.backend_instances'))return {rows:state.backend?[[state.backend[0]]]:[]};
        if(sql.startsWith('SELECT instance_id,backend_namespace'))return {rows:state.backend?[[...state.backend]]:[]};
        if(sql.startsWith('UPDATE cragkit_qdrant.backend_instances')){
          if(sql.includes("state='recovery_blocked'")){state.backend[4]++;state.backend[5]='recovery_blocked';state.backend[6]=p[1];}
          else{state.backend[5]='open';state.backend[6]=null;}
          return {rows:[]};
        }
        if(sql.startsWith('SELECT instance_id,intent_id,owner_token'))return {rows:[[...state.owner]]};
        if(sql.startsWith('UPDATE cragkit_qdrant.document_owners')){state.owner[3]=p[3];return {rows:[]};}
        if(sql.startsWith('SELECT 1 FROM cragkit_qdrant.dispatch_journal'))return {rows:state.pending?[[1]]:[]};
        throw Error('Unexpected SQL in bounded double');
      }};
    state.clients.push(client);return client;
  }};
  const resource=new PoolResource(parse_pool_config({host:'host.invalid',dbname:'fixture',user:'supervisor',
    sslrootcert:'/fake/ca',passfile:'/fake/pass',release_timeout:.05,close_timeout:.1}),{pool});
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  let epoch=1,recovery=null,proof=null,barrier=null,binding=null;
  supervisor.control_binding=()=>({instance_id:'instance-1',backend_namespace:config.backend_namespace,
    storage_identity:'storage-1',supervisor_id:'supervisor-1',epoch,credential_generation:`key-${state.physical}`,
    recovery,sealed:state.sealed,alive:true});
  supervisor.block_ordinary=()=>{state.gate=false;};
  supervisor.recover=async input=>{
    assert.equal(state.clients.at(-1).status,'I');
    assert.equal(state.backend[5],'recovery_blocked');
    if(state.beforePhysical)await state.beforePhysical();
    state.physical++;epoch=input.new_epoch;recovery={...input};proof=Object.freeze({});
    binding=Object.freeze({instance_id:'instance-1',storage_identity:'storage-1',supervisor_id:'supervisor-1',
      ...input,credential_generation:`key-${state.physical}`});
    return proof;
  };
  supervisor.recovery_binding=value=>{if(value!==proof||!proof||state.sealed)throw new UnsupportedCapability();return binding;};
  supervisor.seal_recovery=async value=>{
    if(value!==proof||!proof)throw new UnsupportedCapability();
    state.sealed=true;barrier??=Object.freeze({});return barrier;
  };
  supervisor.barrier_binding=value=>{if(value!==barrier||!state.sealed)throw new UnsupportedCapability();return binding;};
  supervisor.finish_recovery=(actual,token)=>{
    assert.equal(state.backend[5],'open');
    assert.deepEqual(settlement_data(token,supervisor,actual),binding);
    state.gate=true;state.sealed=false;recovery=null;
  };
  // A nominal, nonreentrant session double. Native facade lifetime/origin is
  // independently tested by the real supervisor suite and native consumer.
  const mutations=Object.fromEntries(['block_ordinary','recover','seal_recovery','finish_recovery']
    .map(name=>[name,supervisor[name].bind(supervisor)]));
  let currentSession=null;
  for(const name of Object.keys(mutations)){
    supervisor[name]=(...args)=>{
      if(currentSession)throw new ProviderUnavailable();
      return mutations[name](...args);
    };
  }
  supervisor.control_session=async body=>{
    if(currentSession)throw new ProviderUnavailable();
    const token={};currentSession=token;
    const facade=Object.freeze(Object.fromEntries(Object.keys(mutations).map(name=>[name,(...args)=>{
      if(currentSession!==token)throw new ProviderUnavailable();
      return mutations[name](...args);
    }])));
    try{return await body(facade);}finally{currentSession=null;}
  };
  const writer=new PostgresQdrantWriter(resource,config,'instance-1');
  const verifier=new QdrantReconciliationVerifier(writer,supervisor);
  const coordinator=new PostgresQdrantRecovery(resource,config,supervisor,verifier);
  return {state,resource,writer,supervisor,verifier,coordinator};
}

test('recovery components return exactly the original verifier without I/O or resource disclosure',async()=>{
  const f=setup();
  const equivalent=new QdrantReconciliationVerifier(f.writer,f.supervisor);
  try{
    const actual=recovery_components(f.coordinator,f.writer,f.supervisor,structuredClone(config));
    assert.equal(actual,f.verifier);
    assert.notEqual(actual,equivalent);
    assert.equal(f.state.queries.length,0);
    assert.equal(f.state.clients.length,0);
    assert.equal(f.state.ended,0);
    assert.equal('resource'in actual,false);
  }finally{await equivalent.close();await f.coordinator.close();await f.writer.close();}
});

test('recovery component graph rejects copied types, wrong identities and profile contradictions',async()=>{
  const f=setup();
  const otherWriter=new PostgresQdrantWriter(f.resource,config,'instance-1');
  const otherSupervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/other','instance-1',config);
  class Foreign extends PostgresQdrantRecovery {}
  const child=new Foreign(f.resource,config,f.supervisor,f.verifier);
  const mismatch=new PostgresQdrantRecovery(f.resource,{...config,collection_incarnation:'different'},f.supervisor,f.verifier);
  try{
    for(const value of [null,{}, {...f.coordinator},Object.create(PostgresQdrantRecovery.prototype),child,new Proxy(f.coordinator,{})]){
      assert.throws(()=>recovery_components(value,f.writer,f.supervisor,config),InvalidRequest);
    }
    assert.throws(()=>recovery_components(f.coordinator,otherWriter,f.supervisor,config),InvalidRequest);
    assert.throws(()=>recovery_components(f.coordinator,f.writer,otherSupervisor,config),InvalidRequest);
    assert.throws(()=>recovery_components(f.coordinator,new Proxy(f.writer,{}),f.supervisor,config),InvalidRequest);
    assert.throws(()=>recovery_components(f.coordinator,f.writer,new Proxy(f.supervisor,{}),config),InvalidRequest);
    assert.throws(()=>recovery_components(f.coordinator,f.writer,f.supervisor,{}),InvalidRequest);
    assert.throws(()=>recovery_components(f.coordinator,f.writer,f.supervisor,{...config,physical_collection:'other_valid_collection'}),UnsupportedCapability);
    assert.throws(()=>recovery_components(mismatch,f.writer,f.supervisor,{...config,collection_incarnation:'different'}),UnsupportedCapability);
    assert.equal(f.state.queries.length,0);
    assert.equal(f.state.clients.length,0);
  }finally{
    await child.close();await mismatch.close();await f.coordinator.close();
    await otherWriter.close();await f.writer.close();await otherSupervisor.close();
  }
});

test('explicit initialization, committed block, repeated same-ID physical fencing and borrowed ownership',async()=>{
  const f=setup();
  await assert.rejects(f.coordinator.recover('recovery-1',options()),IndexNotReady);
  await f.coordinator.initialize(options());
  const first=await f.coordinator.recover('recovery-1',options());
  assert.equal(f.state.backend[4],2);
  assert.equal(f.state.gate,false);
  const second=await f.coordinator.recover('recovery-1',options());
  assert.notEqual(first,second);
  assert.equal(f.state.backend[4],2);
  assert.equal(f.state.physical,2);
  const queriesBefore=f.state.queries.length;
  const clientsBefore=f.state.clients.length;
  await assert.rejects(f.coordinator.recover('other-recovery',options()),ProviderUnavailable);
  assert.equal(f.state.queries.length,queriesBefore);
  assert.equal(f.state.clients.length,clientsBefore);
  assert.deepEqual(await f.coordinator.advance_owner(second,context,options()),{owner_token:context.owner_token,backend_epoch:2});
  await f.coordinator.close();
  await f.coordinator.close();
  assert.equal(f.state.ended,0);
});

test('initialization accepts only compatible local and durable recovery states',async()=>{
  const tuple={recovery_id:'recovery-1',old_epoch:1,new_epoch:2};
  const cases=[
    {local:{epoch:1,recovery:null,sealed:false},sql:[1,'open',null],accepted:true},
    {local:{epoch:1,recovery:null,sealed:false},sql:[2,'recovery_blocked','recovery-1'],accepted:true},
    {local:{epoch:2,recovery:tuple,sealed:false},sql:[2,'recovery_blocked','recovery-1'],accepted:true},
    {local:{epoch:1,recovery:tuple,sealed:false},sql:[2,'recovery_blocked','recovery-1'],accepted:true},
    {local:{epoch:2,recovery:tuple,sealed:true},sql:[2,'open',null],accepted:true},
    {local:{epoch:2,recovery:tuple,sealed:false},sql:[2,'open',null],accepted:false},
    {local:{epoch:1,recovery:null,sealed:false},sql:[3,'recovery_blocked','recovery-1'],accepted:false},
    {local:{epoch:2,recovery:tuple,sealed:false},sql:[2,'recovery_blocked','other'],accepted:false},
    {local:{epoch:1,recovery:null,sealed:false},sql:[2,'open',null],accepted:false},
  ];
  for(const item of cases){
    const f=setup();
    const original=f.supervisor.control_binding.bind(f.supervisor);
    f.supervisor.control_binding=()=>({...original(),...item.local});
    f.state.backend=['instance-1',config.backend_namespace,'storage-1','supervisor-1',...item.sql];
    if(item.accepted){
      await f.coordinator.initialize(options());
      assert.equal(f.state.gate,item.sql[1]!=='recovery_blocked',JSON.stringify(item));
    }else{
      await assert.rejects(f.coordinator.initialize(options()),ProviderUnavailable,JSON.stringify(item));
    }
    await f.coordinator.close();
  }
});

test('initialization after a lost reopen handoff preserves the seal for explicit reconciliation',async()=>{
  const f=setup();
  await f.coordinator.initialize(options());
  const proof=await f.coordinator.recover('recovery-1',options());
  await f.supervisor.seal_recovery(proof,options());
  // Durable open is visible, but native finish did not run in the interrupted caller.
  f.state.backend[5]='open';
  f.state.backend[6]=null;
  const resumed=new PostgresQdrantRecovery(f.resource,config,f.supervisor,f.verifier);
  await resumed.initialize(options());
  assert.equal(f.state.sealed,true);
  assert.equal(f.state.gate,false);
  assert.deepEqual(await resumed.reopen(proof,options()),{state:'open',epoch:2});
  assert.equal(f.state.gate,true);
  await resumed.close();
  await f.coordinator.close();
});

test('reopen seals before global pending check and does not reopen on foreign uncertainty',async()=>{
  const f=setup();await f.coordinator.initialize(options());
  const proof=await f.coordinator.recover('recovery-1',options());
  f.state.pending=true;
  await assert.rejects(f.coordinator.reopen(proof,options()),ProviderUnavailable);
  assert.equal(f.state.sealed,true);
  assert.equal(f.state.gate,false);
  assert.equal(f.state.backend[5],'recovery_blocked');
  f.state.pending=false;
  assert.deepEqual(await f.coordinator.reopen(proof,options()),{state:'open',epoch:2});
  assert.equal(f.state.gate,true);
  await f.coordinator.close();
});

test('lost open COMMIT acknowledgment reconciles without repeating mutation',async()=>{
  const f=setup();await f.coordinator.initialize(options());
  const proof=await f.coordinator.recover('recovery-1',options());
  f.state.lost=true;
  assert.deepEqual(await f.coordinator.reopen(proof,options()),{state:'open',epoch:2});
  assert.equal(f.state.queries.filter(sql=>sql.includes("SET state='open'")).length,1);
  assert.ok(f.state.clients.some(client=>client.discard===true));
  await f.coordinator.close();
});

test('fresh role rejection precedes each mutation and copied receipts cannot settle',async()=>{
  const f=setup();await f.coordinator.initialize(options());
  const proof=await f.coordinator.recover('recovery-1',options());
  await assert.rejects(f.coordinator.settle_retired(proof,{},options()),InvalidRequest);
  f.state.role=false;
  await assert.rejects(f.coordinator.advance_owner(proof,context,options()),UnauthorizedScope);
  assert.equal(f.state.owner[3],1);
  assert.throws(()=>settlement_data({},f.supervisor,{}),UnsupportedCapability);
  await f.coordinator.close();
});

test('constructors reject subclass and proxy authority objects without work',()=>{
  const f=setup();
  class Foreign extends ManagedQdrantSupervisor {}
  assert.throws(()=>new PostgresQdrantRecovery(f.resource,config,new Foreign('/owned/qdrant','/private/other','other',config),f.verifier),InvalidRequest);
  assert.throws(()=>new PostgresQdrantRecovery(new Proxy(f.resource,{}),config,f.supervisor,f.verifier),InvalidRequest);
  assert.throws(()=>new PostgresQdrantRecovery(null,config,f.supervisor,f.verifier),InvalidRequest);
});

test('two recovery objects cannot interleave SQL-to-physical recovery or inherited raw mutation',async()=>{
  const f=setup();
  await f.coordinator.initialize(options());
  const proof=await f.coordinator.recover('recovery-1',options());
  const competing=new PostgresQdrantRecovery(f.resource,config,f.supervisor,f.verifier);
  await competing.initialize(options());
  let entered,release;
  const paused=new Promise(resolve=>{entered=resolve;});
  const resume=new Promise(resolve=>{release=resolve;});
  f.state.beforePhysical=async()=>{entered();await resume;};
  const recovering=f.coordinator.recover('recovery-1',options());
  await paused;
  const queryCount=f.state.queries.length;
  await assert.rejects(competing.reopen(proof,options()),ProviderUnavailable);
  await assert.rejects(Promise.resolve().then(()=>f.supervisor.recover({recovery_id:'recovery-1',old_epoch:1,new_epoch:2},options())),ProviderUnavailable);
  assert.equal(f.state.queries.length,queryCount);
  assert.equal(f.state.backend[5],'recovery_blocked');
  release();
  await recovering;
  await competing.close();
  await f.coordinator.close();
});

test('cancelled SQL operation unwinds its session before another coordinator enters',async()=>{
  const f=setup();
  await f.coordinator.initialize(options());
  const other=new PostgresQdrantRecovery(f.resource,config,f.supervisor,f.verifier);
  const abort=new AbortController();
  abort.abort();
  await assert.rejects(f.coordinator.recover('recovery-1',{...options(),signal:abort.signal}),error=>error.name==='AbortError');
  await other.initialize(options());
  const proof=await other.recover('recovery-1',options());
  assert.ok(proof);
  await other.close();
  await f.coordinator.close();
});

test('recovery dispatch is inert before initialization and rejects malformed callback without SQL',async()=>{
  const f=setup();try{
    const start=f.state.queries.length;
    await assert.rejects(f.coordinator.dispatch_stage_recovery({},context,async()=>true,options()),IndexNotReady);
    await assert.rejects(f.coordinator.dispatch_stage_recovery({},context,()=>true,options()),IndexNotReady);
    await assert.rejects(f.coordinator.dispatch_stage_recovery({},context,null,options()),InvalidRequest);
    assert.equal(f.state.queries.length,start);
  }finally{await f.coordinator.close();await f.verifier.close();await f.writer.close();await f.resource.close();}
});

test('ordinary authority cannot enter recovery dispatcher or invoke its authorizer',async()=>{
  const f=setup();let calls=0;
  try{
    await f.coordinator.initialize(options());const start=f.state.queries.length;
    await assert.rejects(f.coordinator.dispatch_stage_recovery({},context,async()=>{calls++;return true;},options()),UnsupportedCapability);
    assert.equal(calls,0);assert.equal(f.state.queries.length,start);
  }finally{await f.coordinator.close();await f.verifier.close();await f.writer.close();await f.resource.close();}
});

function guardProfile(f){f.state.history=AUTHORITY_SECURITY_GUARD_HISTORY.map(row=>[...row]);f.state.fingerprint=EXPECTED_SECURITY_GUARD_AUTHORITY_FINGERPRINT;}
function attestProfile(f){f.state.history=AUTHORITY_ATTESTATION_HISTORY.map(row=>[...row]);f.state.fingerprint=EXPECTED_ATTESTATION_AUTHORITY_FINGERPRINT;}
async function closeFixture(f){await f.coordinator.close();await f.verifier.close();await f.writer.close();await f.resource.close();}
const backendBinding="SELECT set_config('cragkit_qdrant.backend_instance_id'";

test('recovery4 role map adds exactly private guard EXECUTE and no data privileges',()=>{
 const addition="p.oid IS NOT DISTINCT FROM to_regprocedure('cragkit_qdrant.lock_current_security(text,text,text,text,text,bigint,text,text,text,text,uuid,text,text,text,text,bigint,text[],text[],text,text,text,boolean)') OR\n   ";
 assert.equal(RECOVERY_SECURITY_GUARD_ROLE_SQL.replace(addition,''),RECOVERY_ROLE_SQL);
 assert.throws(()=>publication_schema_profile(AUTHORITY_SECURITY_GUARD_HISTORY),UnsupportedCapability);
});

test('recovery4 admits exact metadata before role and instance binding and preserves proof flow',async()=>{
 const f=setup();guardProfile(f);
 try{
  await f.coordinator.initialize(options());
  const bindingAt=f.state.queries.findIndex(sql=>sql.startsWith(backendBinding));
  const roleAt=f.state.queries.indexOf(RECOVERY_SECURITY_GUARD_ROLE_SQL);
  for(const sql of [AUTHORITY_HISTORY_SQL,AUTHORITY_SECURITY_GUARD_CATALOG_SQL,AUTHORITY_FINGERPRINT_SQL,SECURITY_GUARD_OWNER_SQL])assert.ok(f.state.queries.indexOf(sql)>=0&&f.state.queries.indexOf(sql)<roleAt);
  assert.ok(roleAt<bindingAt);assert.equal(f.state.queries.includes(RECOVERY_ROLE_SQL),false);
  const proof=await f.coordinator.recover('recovery-1',options());
  const result=await f.coordinator.advance_owner(proof,context,options());assert.deepEqual(result,{owner_token:context.owner_token,backend_epoch:2});
  assert.equal(f.state.physical,1);assert.equal(f.state.ended,0);
  assert.equal(f.state.queries.some(sql=>/^SELECT cragkit_qdrant\.lock_current_security\(/.test(sql)),false);
 }finally{await closeFixture(f);}
});

for(const fault of ['owner_grant','owner_login','catalog','fingerprint','suffix','checksum','downgrade','extra_function','role'])test(`recovery4 ${fault} drift refuses before instance binding`,async()=>{
 const f=setup();guardProfile(f);
 try{
  await f.coordinator.initialize(options());const proof=await f.coordinator.recover('recovery-1',options());
  if(fault==='owner_grant'||fault==='owner_login')f.state.ownerRows=[[false]];
  if(fault==='catalog'||fault==='extra_function')f.state.catalog=false;
  if(fault==='extra_function')f.state.role=false;
  if(fault==='fingerprint')f.state.fingerprint='wrong';
  if(fault==='suffix')f.state.history.push(['0005_unknown','f'.repeat(64)]);
  if(fault==='checksum')f.state.history[3][1]='f'.repeat(64);
  if(fault==='downgrade')attestProfile(f);
  if(fault==='role')f.state.role=false;
  const start=f.state.queries.length;
  await assert.rejects(f.coordinator.advance_owner(proof,context,options()),fault==='role'?UnauthorizedScope:UnsupportedCapability);
  assert.equal(f.state.queries.slice(start).some(sql=>sql.startsWith(backendBinding)),false);
  assert.equal(f.state.owner[3],1);
  guardProfile(f);f.state.ownerRows=[[true]];f.state.catalog=true;f.state.role=true;
  assert.equal((await f.coordinator.advance_owner(proof,context,options())).backend_epoch,2);
 }finally{await closeFixture(f);}
});

test('recovery profile changes require explicit initialization and sticky4 survives failed reinitialization',async()=>{
 const f=setup();attestProfile(f);
 try{
  await f.coordinator.initialize(options());guardProfile(f);
  await assert.rejects(f.coordinator.recover('recovery-1',options()),UnsupportedCapability);
  await f.coordinator.initialize(options());attestProfile(f);
  await assert.rejects(f.coordinator.initialize(options()),UnsupportedCapability);
  await assert.rejects(f.coordinator.recover('recovery-1',options()),IndexNotReady);
  guardProfile(f);f.state.ownerRows=[[false]];await assert.rejects(f.coordinator.initialize(options()),UnsupportedCapability);
  attestProfile(f);await assert.rejects(f.coordinator.initialize(options()),UnsupportedCapability);
  guardProfile(f);f.state.ownerRows=[[true]];await f.coordinator.initialize(options());
 }finally{await closeFixture(f);}
});

for(const changed of [false,true])test(`recovery4 lost initialization COMMIT ${changed?'changed-history refusal':'read-only exact confirmation'}`,async()=>{
 const f=setup();guardProfile(f);f.state.lost=true;
 if(changed)f.state.afterLost=()=>attestProfile(f);
 try{
  if(changed)await assert.rejects(f.coordinator.initialize(options()),UnsupportedCapability);else await f.coordinator.initialize(options());
  const firstCommit=f.state.queries.indexOf('COMMIT'),confirmation=f.state.queries.slice(firstCommit+1);
  assert.equal(f.state.queries.filter(sql=>sql.startsWith('INSERT INTO cragkit_qdrant.backend_instances')).length,1);
  assert.equal(confirmation.some(sql=>/^(INSERT|UPDATE|DELETE) /.test(sql)),false);
  assert.ok(confirmation.includes(AUTHORITY_HISTORY_SQL));
  if(changed){assert.equal(confirmation.some(sql=>sql.startsWith(backendBinding)),false);await assert.rejects(f.coordinator.recover('recovery-1',options()),IndexNotReady);}
  else assert.ok(confirmation.includes(SECURITY_GUARD_OWNER_SQL));
 }finally{await closeFixture(f);}
});

test('recovery4 rejects malformed native metadata without serialization hooks',async()=>{
 let hooks=0;const cell={toJSON(){hooks++;return true;}},accessor=[];
 Object.defineProperty(accessor,'0',{get(){hooks++;return true;},enumerable:true});
 for(const rows of [[],[[1]],[[cell]],[accessor],new Proxy([[true]],{get(){hooks++;return [];}})]){
  const f=setup();guardProfile(f);f.state.ownerRows=rows;
  try{await assert.rejects(f.coordinator.initialize(options()),UnsupportedCapability);assert.equal(f.state.queries.some(sql=>sql.startsWith(backendBinding)),false);}
  finally{await closeFixture(f);}
 }
 assert.equal(hooks,0);
});

for(const mode of ['cancel','deadline'])test(`recovery4 ${mode} during metadata never binds backend`,async()=>{
 const f=setup();guardProfile(f);let finish;f.state.ownerWait=new Promise(resolve=>{finish=resolve;});const controller=new AbortController();
 try{
  const work=f.coordinator.initialize({deadline:mode==='deadline'?now()+.02:now()+5,signal:controller.signal});
  const refused=assert.rejects(work,mode==='deadline'?DeadlineExceeded:error=>error.name==='AbortError');
  await new Promise(resolve=>setImmediate(resolve));if(mode==='cancel')controller.abort();await refused;
  assert.equal(f.state.queries.some(sql=>sql.startsWith(backendBinding)),false);assert.equal(f.state.ended,0);finish();
 }finally{finish();await closeFixture(f);}
});


test('initialization session cleanup failure closes readiness while malformed options preserve healthy admission',async()=>{
 const f=setup();guardProfile(f);const original=f.supervisor.control_session.bind(f.supervisor);let fail=true;
 f.supervisor.control_session=async body=>{
  const result=await original(body);
  if(fail){fail=false;throw new ProviderUnavailable();}
  return result;
 };
 try{
  await assert.rejects(f.coordinator.initialize(options()),ProviderUnavailable);
  await assert.rejects(f.coordinator.recover('recovery-1',options()),IndexNotReady);
  await f.coordinator.initialize(options());const before=f.state.queries.length;
  await assert.rejects(f.coordinator.initialize({deadline:NaN}),InvalidRequest);
  assert.equal(f.state.queries.length,before);
  await f.coordinator.recover('recovery-1',options());assert.equal(f.state.physical,1);
 }finally{await closeFixture(f);}
});
