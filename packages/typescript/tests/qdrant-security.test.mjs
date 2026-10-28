import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {QdrantSecurityManager} from '../dist/qdrant-security.js';
import {PostgresQdrantWriter} from '../dist/qdrant-writer.js';
import {PoolResource,parse_pool_config,now} from '../dist/postgres-pool.js';
import {ExecutionLedger,BudgetExhausted} from '../dist/execution.js';
import {InvalidRequest,UnauthorizedScope,ProviderUnavailable,IndexNotReady,DeadlineExceeded} from '../dist/errors.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_publication.json',import.meta.url),'utf8'));
const config={...fixture.physical,dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse};
const scope=()=>({tenant_id:'tenant-a',principal_id:'reader-a',grant_ids:['grant-a'],authorization_revision:'auth-1'});
const options=()=>({deadline:now()+5});
const book=(limits={},deadline=now()+5)=>new ExecutionLedger({limits:{max_provider_calls:0,max_attempts:1,...limits},deadline});
const change=(action='update_authorization')=>({action,intent_id:'security-1',tenant_id:'tenant-a',collection:'docs',document_id:'doc-1',
  expected_authorization_revision:'auth-1',expected_mutation_epoch:1,
  authorization:{authorization_revision:'auth-2',principal_ids:[],grant_ids:[],language:null,kind:null,tag:null,tombstoned:action==='tombstone'}});
const deferred=()=>{let resolve;const promise=new Promise(done=>{resolve=done;});return {promise,resolve};};

/** Exact borrowed native writer with method spies; no SQL or physical proof. */
function setup(authorize=async()=>true){
  const state={initialized:0,applied:[],writerClosed:0,poolEnded:0,checkouts:0,
    result:{state:'authority_committed',revision_id:null,generation_id:null,authority_committed:true,replica_complete:false,purge_complete:false}};
  const pool={async connect(){state.checkouts++;throw Error('unexpected checkout');},async end(){state.poolEnded++;}};
  const resource=new PoolResource(parse_pool_config({host:'host.invalid',dbname:'fixture',user:'writer',
    sslrootcert:'/fake/ca',passfile:'/fake/pass',release_timeout:.05,close_timeout:.1}),{pool});
  const writer=new PostgresQdrantWriter(resource,config,'fixture-instance');
  writer.initialize=async lease=>{state.initialized++;state.initializeOptions=lease;await state.initializeWait?.promise;};
  writer.apply_security=async(record,trusted,lease)=>{
    state.applied.push({record,trusted,lease});await state.applyWait?.promise;return Object.freeze({...state.result});
  };
  const originalClose=writer.close.bind(writer);writer.close=async()=>{state.writerClosed++;await originalClose();};
  const manager=new QdrantSecurityManager(writer,authorize);
  return {state,writer,resource,manager,async finish(){await manager.close();assert.equal(state.writerClosed,0);await writer.close();await resource.close();}};
}

test('constructor validates native provenance without I/O and idle close preserves borrowed lifetime',async()=>{
  const f=setup();
  try{
    for(const writer of [{},Object.create(PostgresQdrantWriter.prototype),new Proxy(f.writer,{})])
      assert.throws(()=>new QdrantSecurityManager(writer,async()=>true),InvalidRequest);
    assert.throws(()=>new QdrantSecurityManager(f.writer,null),InvalidRequest);
    assert.equal(f.state.checkouts,0);assert.equal(f.state.initialized,0);
    await f.manager.close();assert.equal(f.state.writerClosed,0);assert.equal(f.state.poolEnded,0);
    await assert.rejects(f.manager.initialize(options()),ProviderUnavailable);
  }finally{await f.finish();}
});

for(const action of ['update_authorization','tombstone'])test(`${action} initializes only writer and returns closed historical flags with one attempt`,async()=>{
  const f=setup(async(trusted,collection,document)=>{
    assert.equal(trusted.authorization_revision,'auth-1');assert.equal(collection,'docs');assert.equal(document,'doc-1');return true;
  });
  try{
    await assert.rejects(f.manager[action](change(action),scope(),book(),options()),IndexNotReady);
    await f.manager.initialize(options());assert.equal(f.state.initialized,1);
    const ledger=book(),result=await f.manager[action](change(action),scope(),ledger,options());
    assert.deepEqual(result,{intent_id:'security-1',operation:action,state:'authority_committed',revision_id:null,generation_id:null,
      authority_committed:true,replica_complete:false,published:false,purge_complete:false});
    assert.equal(Object.isFrozen(result),true);
    const snapshot=ledger.snapshot();assert.equal(snapshot.attempts,1);assert.equal(snapshot.provider_calls,0);assert.equal(snapshot.candidates,0);assert.equal(snapshot.pending,0);
    assert.match(f.state.applied[0].lease.owner_token,/^[0-9a-f-]{36}$/);
    Object.assign(f.state.result,{state:'complete',replica_complete:true});
    assert.equal((await f.manager[action](change(action),scope(),book(),options())).replica_complete,true);
    assert.equal(f.state.checkouts,0);
  }finally{await f.finish();}
});

test('independent managers admit authority while another borrowed writer operation is stalled',async()=>{
  const blocked=setup(),security=setup();
  try{
    await blocked.manager.initialize(options());await security.manager.initialize(options());
    blocked.state.applyWait=deferred();
    const old=blocked.manager.update_authorization(change(),scope(),book(),options());
    await new Promise(resolve=>setImmediate(resolve));assert.equal(blocked.state.applied.length,1);
    const result=await security.manager.tombstone(change('tombstone'),scope(),book(),options());
    assert.equal(result.authority_committed,true);assert.equal(blocked.state.applied.length,1);
    blocked.state.applyWait.resolve();await old;
  }finally{await blocked.finish();await security.finish();}
});

test('canonical input and trusted scope are copied before authorization awaits',async()=>{
  const wait=deferred(),entered=deferred();const f=setup(async trusted=>{entered.resolve();await wait.promise;assert.equal(trusted.grant_ids[0],'grant-a');return true;});
  try{
    await f.manager.initialize(options());const record=change(),trusted=scope();
    const work=f.manager.update_authorization(record,trusted,book(),options());await entered.promise;
    record.authorization.principal_ids.push('intruder');record.document_id='other-doc';trusted.grant_ids[0]='intruder';trusted.authorization_revision='auth-2';
    wait.resolve();await work;
    assert.equal(f.state.applied[0].record.document_id,'doc-1');assert.deepEqual(f.state.applied[0].record.authorization.principal_ids,[]);
    assert.equal(f.state.applied[0].trusted.authorization_revision,'auth-1');
  }finally{wait.resolve();await f.finish();}
});

for(const invalid of ['action','tenant','shape','ledger','budget'])test(`invalid ${invalid} refuses before authorization or writer mutation`,async()=>{
  let callbacks=0;const f=setup(async()=>{callbacks++;return true;});
  try{
    await f.manager.initialize(options());const record=change(),trusted=scope();let ledger=book();
    if(invalid==='action')record.action='tombstone';
    if(invalid==='tenant')trusted.tenant_id='other';
    if(invalid==='shape')record.extra='private';
    if(invalid==='ledger')ledger={};
    if(invalid==='budget'){const used=ledger.reserve({attempts:1});ledger.dispatch(used);ledger.reconcile(used);}
    await assert.rejects(f.manager.update_authorization(record,trusted,ledger,options()),
      invalid==='tenant'?UnauthorizedScope:invalid==='budget'?BudgetExhausted:InvalidRequest);
    assert.equal(callbacks,0);assert.equal(f.state.applied.length,0);
  }finally{await f.finish();}
});

for(const mode of ['false','nonboolean','synchronous','throw'])test(`callback ${mode} is closed and never applies security`,async()=>{
  const authorize=mode==='false'?async()=>false:mode==='nonboolean'?async()=>1:mode==='synchronous'?()=>true:async()=>{throw Error('private callback text');};
  const f=setup(authorize);
  try{
    await f.manager.initialize(options());const ledger=book();
    await assert.rejects(f.manager.update_authorization(change(),scope(),ledger,options()),error=>{
      assert.equal(String(error).includes('private callback text'),false);
      return error instanceof (mode==='false'?UnauthorizedScope:mode==='throw'?ProviderUnavailable:InvalidRequest);
    });
    assert.equal(f.state.applied.length,0);assert.equal(ledger.snapshot().pending,0);
  }finally{await f.finish();}
});

test('abort is latched despite late callback approval; overlap rejects and active work unwinds before reuse',async()=>{
  const entered=deferred(),wait=deferred(),controller=new AbortController();
  const f=setup(async()=>{entered.resolve();await wait.promise;return true;});
  try{
    await f.manager.initialize(options());const ledger=book();
    const work=f.manager.update_authorization(change(),scope(),ledger,{...options(),signal:controller.signal});
    const refusal=assert.rejects(work,error=>error.name==='AbortError');await entered.promise;controller.abort();
    await assert.rejects(f.manager.tombstone(change('tombstone'),scope(),book(),options()),ProviderUnavailable);
    wait.resolve();await refusal;assert.equal(f.state.applied.length,0);assert.equal(ledger.snapshot().pending,0);
    await f.manager.update_authorization(change(),scope(),book(),options());
  }finally{wait.resolve();await f.finish();}
});

test('minimum ledger deadline blocks late callback mutation and close cancels only own operation',async()=>{
  const wait=deferred(),entered=deferred();const f=setup(async()=>{entered.resolve();await wait.promise;return true;});
  try{
    await f.manager.initialize(options());const ledger=book({},now()+.02);
    const work=f.manager.update_authorization(change(),scope(),ledger,options());
    const expired=assert.rejects(work,DeadlineExceeded);await entered.promise;
    await new Promise(resolve=>setTimeout(resolve,35));wait.resolve();await expired;
    assert.equal(f.state.applied.length,0);
  }finally{wait.resolve();await f.finish();}
  const blocked=deferred(),started=deferred(),g=setup(async()=>{started.resolve();await blocked.promise;return true;});
  try{
    await g.manager.initialize(options());const work=g.manager.update_authorization(change(),scope(),book(),options());
    const cancelled=assert.rejects(work,error=>error.name==='AbortError');await started.promise;
    const closing=g.manager.close();await assert.rejects(g.manager.initialize(options()),ProviderUnavailable);
    blocked.resolve();await cancelled;await closing;assert.equal(g.state.writerClosed,0);assert.equal(g.state.poolEnded,0);
  }finally{blocked.resolve();await g.finish();}
});

for(const kind of ['invalid','typed','proxy','hostile-dom'])test(`callback ${kind} error follows closed callback policy`,async()=>{
  const makeError=()=>{
    if(kind==='invalid')return new InvalidRequest();
    if(kind==='typed')return new UnauthorizedScope();
    if(kind==='proxy')return new Proxy({}, {getPrototypeOf(){throw Error('private proxy prototype');}});
    const error=new DOMException('private DOM message','AbortError');
    Object.defineProperty(error,'name',{get(){throw Error('private DOM name');}});return error;
  };
  const f=setup(async()=>{throw makeError();});
  try{
    await f.manager.initialize(options());
    await assert.rejects(f.manager.update_authorization(change(),scope(),book(),options()),error=>{
      assert.equal(String(error).includes('private'),false);
      return error instanceof (kind==='invalid'?InvalidRequest:ProviderUnavailable);
    });
    assert.equal(f.state.applied.length,0);
  }finally{await f.finish();}
});

test('hostile writer error inspection cannot leak proxy or DOM getter failures',async()=>{
  for(const hostile of [new Proxy({}, {getPrototypeOf(){throw Error('private prototype hook');}}),
    Object.defineProperty(new DOMException('private message','AbortError'),'name',{get(){throw Error('private name hook');}})]){
    const f=setup();
    try{
      await f.manager.initialize(options());f.writer.apply_security=async()=>{throw hostile;};
      await assert.rejects(f.manager.update_authorization(change(),scope(),book(),options()),error=>{
        assert.equal(error instanceof ProviderUnavailable,true);assert.equal(String(error).includes('private'),false);return true;
      });
    }finally{await f.finish();}
  }
});
