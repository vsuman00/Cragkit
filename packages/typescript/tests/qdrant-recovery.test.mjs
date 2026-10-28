import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {PoolResource,parse_pool_config,now} from '../dist/postgres-pool.js';
import {PostgresQdrantWriter} from '../dist/qdrant-writer.js';
import {ManagedQdrantSupervisor} from '../dist/qdrant-supervisor.js';
import {QdrantReconciliationVerifier} from '../dist/qdrant-reconciliation.js';
import {PostgresQdrantRecovery,RECOVERY_ROLE_SQL,settlement_data,recovery_components} from '../dist/qdrant-recovery.js';
import {AUTHORITY_HISTORY_SQL,AUTHORITY_PUBLICATION_HISTORY,AUTHORITY_PUBLICATION_CATALOG_SQL,
  AUTHORITY_FINGERPRINT_SQL,EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT} from '../dist/qdrant-authority.js';
import {InvalidRequest,UnsupportedCapability,ProviderUnavailable,UnauthorizedScope,IndexNotReady} from '../dist/errors.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_publication.json',import.meta.url),'utf8'));
const config={...fixture.physical,dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse};
const options=()=>({deadline:now()+5});
const context={scope:{tenant_id:'tenant-a',principal_id:'reader-a',grant_ids:[],authorization_revision:'auth-1'},
  collection:'docs',document_id:'doc-1',intent_id:'intent-1',owner_token:'00000000-0000-4000-8000-000000000001'};

/** These doubles exercise coordinator ordering; actual PostgreSQL/process proof is separate. */
function setup(){
  const state={backend:null,owner:['instance-1',context.intent_id,context.owner_token,1],role:true,
    pending:false,lost:false,queries:[],clients:[],physical:0,sealed:false,gate:true,ended:0};
  const pool={async end(){state.ended++;},async connect(){
    const client={status:'I',release(discard){this.discard=discard;},getTransactionStatus(){return this.status;},
      async query(query){
        const sql=query.text,p=query.values??[];
        state.queries.push(sql);
        if(sql.startsWith('BEGIN')){this.status='T';this.before=structuredClone({backend:state.backend,owner:state.owner});return {rows:[]};}
        if(sql==='ROLLBACK'){Object.assign(state,this.before);this.status='I';return {rows:[]};}
        if(sql==='COMMIT'){this.status='I';if(state.lost){state.lost=false;throw Object.assign(Error('private'),{code:'08006'});}return {rows:[]};}
        if(sql===RECOVERY_ROLE_SQL)return {rows:[[state.role]]};
        if(sql===AUTHORITY_HISTORY_SQL)return {rows:AUTHORITY_PUBLICATION_HISTORY.map(row=>[...row])};
        if(sql===AUTHORITY_PUBLICATION_CATALOG_SQL)return {rows:[[true]]};
        if(sql===AUTHORITY_FINGERPRINT_SQL)return {rows:[[EXPECTED_PUBLICATION_AUTHORITY_FINGERPRINT]]};
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
