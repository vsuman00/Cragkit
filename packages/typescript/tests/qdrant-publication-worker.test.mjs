import test from 'node:test';
import assert from 'node:assert/strict';
import childProcess from 'node:child_process';
import {syncBuiltinESMExports} from 'node:module';
import {EventEmitter} from 'node:events';
import {Duplex,PassThrough} from 'node:stream';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {ManagedQdrantPublicationWorkerHost,OwnedPublicationWorker,OrdinaryWorkerController,
  PublicationWorkerFrameDecoder,encode_worker_frame,strict_worker_json,publication_worker_job,
  is_worker_controller,is_publication_controller,publication_attempt_binding,publication_controller_profile,
  publication_issue_attempt,publication_transport_for,publication_before_write,publication_finalization,
  publication_worker_http_request,publication_worker_http_status} from '../dist/qdrant-publication-worker.js';
import {ManagedQdrantSupervisor} from '../dist/qdrant-supervisor.js';
import {ExecutionLedger,BudgetExhausted} from '../dist/execution.js';
import {now} from '../dist/postgres-pool.js';
import {InvalidRequest,ProviderUnavailable,UnsupportedCapability,DeadlineExceeded} from '../dist/errors.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_publication.json',import.meta.url),'utf8'));
const config={...fixture.physical,dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse};
const scope={tenant_id:'tenant-a',principal_id:'reader-a',grant_ids:['grant-a'],authorization_revision:'auth-1'};
const reference={collection:'docs',document_id:'doc-1',intent_id:'intent-2'};
const pool={host:'localhost',port:5432,dbname:'fixture',user:'writer',sslrootcert:'/tmp/test-root.pem',passfile:'/tmp/test-passfile',max_size:1};
const job=()=>({writer_pool:{...pool},config:structuredClone(config),scope:structuredClone(scope),reference:{...reference},limits:{deadline_ms:60000,max_attempts:1,max_provider_calls:0}});
const options=()=>({deadline:now()+3});
const ledger=()=>new ExecutionLedger({limits:{deadline_ms:60000,max_attempts:1,max_provider_calls:0},deadline:now()+3});
const canonical=value=>Array.isArray(value)?'['+value.map(canonical).join(',')+']':value&&typeof value==='object'?'{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonical(value[key])).join(',')+'}':JSON.stringify(value);
const sha=value=>createHash('sha256').update(value).digest('hex');
const result=()=>({intent_id:reference.intent_id,operation:'publish',state:'published',revision_id:'rev-1',generation_id:'gen-1',authority_committed:true,replica_complete:true,published:true,purge_complete:false});
function supervisor(){
  const actual=new ManagedQdrantSupervisor('/tmp/qdrant','/tmp/cragkit-worker-test','instance-fixture',config);
  const state={identity:{instance_id:'instance-fixture',backend_namespace:config.backend_namespace,storage_identity:'storage-fixture',supervisor_id:'supervisor-fixture',epoch:1,credential_generation:'generation-1',recovery:null,sealed:false,alive:true},issued:0,credentials:0,closed:0,session:false};
  actual.profile_binding=()=>({...state.identity});
  const attempts=new Map();
  actual.issue_attempt=data=>{assert.equal(state.session,false);state.issued++;const attempt=Object.freeze({});attempts.set(attempt,{...data,...Object.fromEntries(['instance_id','storage_identity','supervisor_id','credential_generation'].map(key=>[key,state.identity[key]]))});return attempt;};
  actual.attempt_binding=attempt=>{const binding=attempts.get(attempt);if(!binding)throw new InvalidRequest();if(binding.credential_generation!==state.identity.credential_generation)throw new UnsupportedCapability();return {...binding};};
  actual.deliver_worker_credential=async(attempt,sink)=>{actual.attempt_binding(attempt);state.credentials++;await sink({endpoint:'http://127.0.0.1:12345',api_key:'a'.repeat(64),epoch:1,instance_id:'instance-fixture'});};
  actual.control_session=async body=>{assert.equal(state.session,false);state.session=true;try{return await body({});}finally{state.session=false;}};
  actual.close=async()=>{state.closed++;};
  return {actual,state};
}
/** A scripted IPC peer exercises the real host; it is not publication/crash evidence. */
function fakeSpawn(t,script,{killFails=false}={}){
  let spawned=0,child,request,reply,exit;const boot=[];let bootValue;
  const parentFrames=new PublicationWorkerFrameDecoder();
  const socket=new Duplex({read(){},write(chunk,_encoding,callback){
    try{for(const frame of parentFrames.push(chunk)){
      if(frame.op==='boot_begin')boot.length=0;
      else if(frame.op==='boot_chunk')boot.push(Buffer.from(frame.data,'base64'));
      else if(frame.op==='boot_end'){
        bootValue=JSON.parse(Buffer.concat(boot).toString('utf8'));
        queueMicrotask(()=>{void script({rpc,child,boot:bootValue,die:exit,socket}).catch(error=>{if(reply){reply.reject(error);reply=null;}socket.destroy();});});
      }else{assert(reply);const pending=reply;reply=null;frame.ok?pending.resolve(frame.data):pending.reject(Object.assign(new Error(),{name:frame.error}));}
    }callback();}catch(error){callback(error);}
  }});
  let id=0;
  const rpc=(op,data,override={})=>new Promise((resolve,reject)=>{assert.equal(reply,null);reply={resolve,reject};socket.push(encode_worker_frame({v:1,id:++id,op,remaining_ms:2000,data,...override}));});
  const original=childProcess.spawn;
  childProcess.spawn=(executable,args,opts)=>{
    spawned++;assert.equal(executable,process.execPath);assert.equal(args.length,2);assert(args[0].endsWith('/qdrant-publication-worker.js'));assert.equal(args[1],'--cragkit-publication-worker-r1');
    for(const key of Object.keys(opts.env))assert(['HOME','TMPDIR','LANG','LC_ALL','TZ'].includes(key));assert.deepEqual(opts.stdio,['ignore','pipe','pipe','pipe']);
    child=new EventEmitter();child.pid=987654;child.stdout=new PassThrough();child.stderr=new PassThrough();child.stdio=[null,child.stdout,child.stderr,socket];
    let exited=false;exit=(code=0,signal=null)=>{if(!exited){exited=true;queueMicrotask(()=>child.emit('exit',code,signal));}};
    child.kill=signal=>{assert.equal(signal,'SIGKILL');if(killFails)return false;exit(null,'SIGKILL');return true;};reply=null;return child;
  };
  syncBuiltinESMExports();t.after(()=>{childProcess.spawn=original;syncBuiltinESMExports();socket.destroy();});
  return {count:()=>spawned,releaseKill:()=>{child.kill=()=>{exit(null,'SIGKILL');return true;};},boot:()=>bootValue};
}

test('worker framing accepts fragmented strict UTF8 and ordered multiple frames',()=>{
  const decoder=new PublicationWorkerFrameDecoder(),raw=Buffer.concat([encode_worker_frame({v:1,text:'café 雪'}),encode_worker_frame({v:1,id:2})]);const frames=[];
  for(const byte of raw)frames.push(...decoder.push(Buffer.from([byte])));
  assert.deepEqual(frames,[{text:'café 雪',v:1},{id:2,v:1}]);decoder.end();
});
test('worker framing rejects zero/oversize lengths before body, truncation and cumulative overflow',()=>{
  for(const size of [0,65537,4294967295]){const decoder=new PublicationWorkerFrameDecoder(),header=Buffer.alloc(4);header.writeUInt32BE(size);assert.throws(()=>decoder.push(header),InvalidRequest);assert.throws(()=>decoder.push(Buffer.from([1])),InvalidRequest);}
  const decoder=new PublicationWorkerFrameDecoder();decoder.push(Buffer.from([0,0]));assert.throws(()=>decoder.end(),InvalidRequest);
  assert.throws(()=>new PublicationWorkerFrameDecoder().push(Buffer.alloc(1048577)),InvalidRequest);
});
test('strict JSON rejects duplicate escaped keys, nonfinite/trailing values and malformed UTF8',()=>{
  for(const value of ['{"id":1,"id":2}','{"id":1,"\\u0069d":2}','[1e999]','{} {}','{"a":NaN}','{"x":01}','[1,]','{"a":1,}'])assert.throws(()=>strict_worker_json(Buffer.from(value)));
  assert.throws(()=>strict_worker_json(Buffer.from([0xff])));
  assert.deepEqual(strict_worker_json(Buffer.from('{"__proto__":{"x":1}}')),JSON.parse('{"__proto__":{"x":1}}'));
  assert.equal({}.x,undefined);
});
test('job snapshots retain supported large scopes and reject credentials, extra fields and path overflow',()=>{
  const raw=job(),selected=publication_worker_job(raw);raw.scope.grant_ids[0]='changed';assert.equal(selected.scope.grant_ids[0],'grant-a');
  for(const override of [{binary:'/bin/sh'},{code:'x'},{writer_pool:{...pool,password:'secret'}},{writer_pool:{...pool,passfile:'/'+('a'.repeat(4096))}},{limits:{max_attempts:0}}])assert.throws(()=>publication_worker_job({...job(),...override}),InvalidRequest);
  const large=job();large.scope.grant_ids=Array.from({length:64},(_,i)=>String(i).padStart(3,'0')+'\u0001'.repeat(250));
  assert(Buffer.byteLength(canonical(publication_worker_job(large)))>65536-4096);
});
test('constructors and forged local diagnostic/controller handles perform no work',async()=>{
  const fixture=supervisor(),host=new ManagedQdrantPublicationWorkerHost(fixture.actual,async()=>true);assert.equal(fixture.state.issued,0);await host.close();assert.equal(fixture.state.closed,0);
  for(const value of [{},Object.create(OrdinaryWorkerController.prototype),new Proxy(fixture.actual,{})])assert.equal(is_worker_controller(value),false);
  assert.equal(is_publication_controller({}),false);assert.throws(()=>new OrdinaryWorkerController(null,null,null,null,0),InvalidRequest);assert.throws(()=>new OwnedPublicationWorker(null,{}),InvalidRequest);
  await assert.rejects(OwnedPublicationWorker.prototype.terminate.call({},options()));
});
test('parent ledger exhaustion, deadline and abort prevent spawn',async t=>{
  const fake=fakeSpawn(t,async()=>{}),fixture=supervisor(),host=new ManagedQdrantPublicationWorkerHost(fixture.actual,async()=>true),spent=ledger();
  const token=spent.reserve({attempts:1});spent.dispatch(token);spent.reconcile(token);
  await assert.rejects(host.publish(job(),spent,options()),BudgetExhausted);
  await assert.rejects(host.publish(job(),ledger(),{deadline:now()-1}),DeadlineExceeded);
  await assert.rejects(host.publish(job(),ledger(),{...options(),signal:AbortSignal.abort()}),error=>error.name==='AbortError');assert.equal(fake.count(),0);await host.close();
});
test('real host bootstraps large scope, pins authorizer data and waits successful child exit',async t=>{
  const fixture=supervisor();let callbacks=0;
  fakeSpawn(t,async({rpc,boot,die})=>{
    assert.equal(boot.v,1);assert.equal(boot.identity.credential_generation,'generation-1');assert(boot.remaining_ms>0);
    const authorized=await rpc('authorize',{reference:boot.job.reference,scope_sha256:sha(canonical(boot.job.scope))});assert.equal(authorized.allowed,true);
    assert.deepEqual(await rpc('profile',{config_sha256:sha(canonical(boot.job.config))}),fixture.state.identity);
    await rpc('done',{result:result(),error:null,cleanup:[]});die();
  });
  const host=new ManagedQdrantPublicationWorkerHost(fixture.actual,async(selected,collection,document)=>{callbacks++;assert.equal(selected.tenant_id,scope.tenant_id);assert.equal(collection,'docs');assert.equal(document,'doc-1');return true;});
  const large=job();large.scope.grant_ids=Array.from({length:64},(_,i)=>String(i).padStart(3,'0')+'\u0001'.repeat(250));
  const accounting=ledger();assert.equal((await host.publish(large,accounting,options())).state,'published');assert.equal(callbacks,1);assert.equal(accounting.snapshot().attempts,1);assert.equal(accounting.snapshot().pending,0);await host.close();assert.equal(fixture.state.closed,0);
});
test('host rejects wrong scope digest and out-of-order envelopes without calling authorizer',async t=>{
  const fixture=supervisor();let callbacks=0;
  fakeSpawn(t,async({rpc,boot})=>{await assert.rejects(rpc('authorize',{reference:boot.job.reference,scope_sha256:'0'.repeat(64)}));});
  const host=new ManagedQdrantPublicationWorkerHost(fixture.actual,async()=>{callbacks++;return true;});await assert.rejects(host.publish(job(),ledger(),options()),InvalidRequest);assert.equal(callbacks,0);await host.close();
});
test('host retains genuine attempts, delivers key once, holds actual finalization while servicing validation',async t=>{
  const fixture=supervisor();
  fakeSpawn(t,async({rpc,die})=>{
    const issued=await rpc('issue',{intent_id:reference.intent_id,owner_token:'00000000-0000-4000-8000-000000000001',epoch:1,dispatch_id:'publication-test'});
    assert.equal(issued.api_key,'a'.repeat(64));await rpc('finalize_begin',{attempt_id:issued.attempt_id});assert.equal(fixture.state.session,true);
    const fresh=await rpc('validate',{attempt_id:issued.attempt_id});assert.deepEqual(fresh.binding,issued.binding);
    await rpc('finalize_end',{});assert.equal(fixture.state.session,false);await rpc('done',{result:result(),error:null,cleanup:[]});die();
  });
  const host=new ManagedQdrantPublicationWorkerHost(fixture.actual,async()=>true);await host.publish(job(),ledger(),options());assert.equal(fixture.state.credentials,1);await host.close();
});
test('retired before-write ACK keeps captured credential and allows only closed write diagnostic',async t=>{
  const fixture=supervisor(),events=[];
  fakeSpawn(t,async({rpc,die})=>{
    const issued=await rpc('issue',{intent_id:reference.intent_id,owner_token:'00000000-0000-4000-8000-000000000001',epoch:1,dispatch_id:'publication-test'});
    await rpc('before_write',{attempt_id:issued.attempt_id,dispatch_id:'publication-test',sequence:1,request_sha256:'a'.repeat(64)});
    await rpc('write_observed',{attempt_id:issued.attempt_id,dispatch_id:'publication-test',status:401});await rpc('done',{result:null,error:'UnauthorizedScope',cleanup:[]});die();
  });
  const host=new ManagedQdrantPublicationWorkerHost(fixture.actual,async()=>true);
  await assert.rejects(host.publish(job(),ledger(),{...options(),observer:async event=>{events.push(event.kind);if(event.kind==='before_write')fixture.state.identity.credential_generation='retired';}}),error=>error.name==='UnauthorizedScope');
  assert.deepEqual(events,['before_write','write_observed']);assert.equal(fixture.state.credentials,1);await host.close();
});
test('kill failure retains finalization ownership until close can reap exact child',async t=>{
  const fixture=supervisor();let enteredResolve;const entered=new Promise(resolve=>{enteredResolve=resolve;});
  const fake=fakeSpawn(t,async({rpc,socket})=>{
    const issued=await rpc('issue',{intent_id:reference.intent_id,owner_token:'00000000-0000-4000-8000-000000000001',epoch:1,dispatch_id:'publication-test'});
    await rpc('finalize_begin',{attempt_id:issued.attempt_id});enteredResolve();socket.destroy();
  },{killFails:true});
  const host=new ManagedQdrantPublicationWorkerHost(fixture.actual,async()=>true),pending=host.publish(job(),ledger(),options());await entered;
  await assert.rejects(pending,ProviderUnavailable);assert.equal(fixture.state.session,true);
  await assert.rejects(host.close(),ProviderUnavailable);assert.equal(fixture.state.session,true);
  fake.releaseKill();await host.close();assert.equal(fixture.state.session,false);assert.equal(fixture.state.closed,0);
});

test('out-of-order request and terminal cleanup refusal cannot return success',async t=>{
  const fixture=supervisor();
  fakeSpawn(t,async({rpc,boot})=>{await assert.rejects(rpc('profile',{config_sha256:sha(canonical(boot.job.config))},{id:2}));});
  const host=new ManagedQdrantPublicationWorkerHost(fixture.actual,async()=>true);await assert.rejects(host.publish(job(),ledger(),options()),InvalidRequest);await host.close();
});
test('authorization freshness is checked again after the trusted callback returns',async t=>{
  const fixture=supervisor();
  fakeSpawn(t,async({rpc,boot})=>{await assert.rejects(rpc('authorize',{reference:boot.job.reference,scope_sha256:sha(canonical(boot.job.scope))}));});
  const host=new ManagedQdrantPublicationWorkerHost(fixture.actual,async()=>{fixture.state.identity.credential_generation='changed';return true;});await assert.rejects(host.publish(job(),ledger(),options()),UnsupportedCapability);await host.close();
});
test('abort kills child but finalization stays held until actual host callback drain',async t=>{
  const fixture=supervisor(),abort=new AbortController();let release,entered;
  const callbackEntered=new Promise(resolve=>{entered=resolve;}),callbackGate=new Promise(resolve=>{release=resolve;});
  fakeSpawn(t,async({rpc,boot})=>{
    const issued=await rpc('issue',{intent_id:reference.intent_id,owner_token:'00000000-0000-4000-8000-000000000001',epoch:1,dispatch_id:'publication-test'});
    await rpc('finalize_begin',{attempt_id:issued.attempt_id});
    await rpc('authorize',{reference:boot.job.reference,scope_sha256:sha(canonical(boot.job.scope))});
  });
  const host=new ManagedQdrantPublicationWorkerHost(fixture.actual,async()=>{entered();await callbackGate;return true;});
  const pending=host.publish(job(),ledger(),{...options(),signal:abort.signal});void pending.catch(()=>{});
  await callbackEntered;abort.abort();await new Promise(resolve=>setImmediate(resolve));assert.equal(fixture.state.session,true);
  release();await assert.rejects(pending,error=>error.name==='AbortError');assert.equal(fixture.state.session,false);await host.close();
});

test('held finalization rejects attempt issuance rather than exposing another supervisor operation',async t=>{
  const fixture=supervisor();
  fakeSpawn(t,async({rpc})=>{
    const issue={intent_id:reference.intent_id,owner_token:'00000000-0000-4000-8000-000000000001',epoch:1,dispatch_id:'publication-test'};
    const issued=await rpc('issue',issue);await rpc('finalize_begin',{attempt_id:issued.attempt_id});assert.equal(fixture.state.session,true);
    await assert.rejects(rpc('issue',{...issue,dispatch_id:'publication-forbidden'}));
  });
  const host=new ManagedQdrantPublicationWorkerHost(fixture.actual,async()=>true);
  await assert.rejects(host.publish(job(),ledger(),options()),InvalidRequest);assert.equal(fixture.state.issued,1);assert.equal(fixture.state.session,false);await host.close();
});
test('before-write validates the retained actual attempt against every captured binding field',async t=>{
  const fixture=supervisor();let observerCalls=0;
  fakeSpawn(t,async({rpc})=>{
    const issued=await rpc('issue',{intent_id:reference.intent_id,owner_token:'00000000-0000-4000-8000-000000000001',epoch:1,dispatch_id:'publication-test'});
    const original=fixture.actual.attempt_binding.bind(fixture.actual);
    fixture.actual.attempt_binding=attempt=>({...original(attempt),owner_token:'00000000-0000-4000-8000-000000000002'});
    await assert.rejects(rpc('before_write',{attempt_id:issued.attempt_id,dispatch_id:'publication-test',sequence:1,request_sha256:'a'.repeat(64)}));
  });
  const host=new ManagedQdrantPublicationWorkerHost(fixture.actual,async()=>true);
  await assert.rejects(host.publish(job(),ledger(),{...options(),observer:async()=>{observerCalls++;}}),UnsupportedCapability);assert.equal(observerCalls,0);await host.close();
});
test('worker HTTP preserves the one-MiB request ceiling and admits exactly status200',()=>{
  const base='/collections/'+config.physical_collection;
  for(const size of [262145,1048576])assert.equal(publication_worker_http_request(config,'PUT',base+'/points?wait=true&ordering=strong',{deadline:now()+1,body:Array(size).fill(32)}).body.length,size);
  assert.throws(()=>publication_worker_http_request(config,'PUT',base+'/points?wait=true&ordering=strong',{deadline:now()+1,body:Array(1048577).fill(32)}),InvalidRequest);
  assert.throws(()=>publication_worker_http_request(config,'PUT',base+'/points?wait=true',{deadline:now()+1,body:[32]}),InvalidRequest);
  assert.doesNotThrow(()=>publication_worker_http_status(200));
  for(const status of [201,202,204,299,301,500])assert.throws(()=>publication_worker_http_status(status),ProviderUnavailable);
  for(const status of [401,403])assert.throws(()=>publication_worker_http_status(status),error=>error.name==='UnauthorizedScope');
});
test('done cannot report a nonterminal prepared result as success',async t=>{
  const fixture=supervisor();fakeSpawn(t,async({rpc})=>{await assert.rejects(rpc('done',{result:{...result(),state:'prepared',published:false},error:null,cleanup:[]}));});
  const host=new ManagedQdrantPublicationWorkerHost(fixture.actual,async()=>true);await assert.rejects(host.publish(job(),ledger(),options()),InvalidRequest);await host.close();
});
test('terminal result rejects contradictory flags and missing stage identities',async t=>{
  for(const changes of [{published:false},{revision_id:null},{generation_id:null}])await t.test(JSON.stringify(changes),async child=>{
    const fixture=supervisor();fakeSpawn(child,async({rpc})=>{await assert.rejects(rpc('done',{result:{...result(),...changes},error:null,cleanup:[]}));});
    const host=new ManagedQdrantPublicationWorkerHost(fixture.actual,async()=>true);await assert.rejects(host.publish(job(),ledger(),options()),InvalidRequest);await host.close();
  });
});
test('all dispatch helpers reject structural, subclass and proxy controllers before invoking methods',async()=>{
  let invoked=0;
  const structural={profile_binding(){invoked++;},attempt_binding(){invoked++;},issue_attempt(){invoked++;},transport_for(){invoked++;},control_session(){invoked++;}};
  class Subclass extends ManagedQdrantSupervisor{}
  const actual=supervisor().actual;
  const values=[structural,new Proxy(actual,{}),new Subclass('/tmp/qdrant','/tmp/worker-subclass','instance-fixture',config)];
  for(const value of values){
    assert.equal(is_publication_controller(value),false);
    await assert.rejects(publication_controller_profile(value,config,options()),InvalidRequest);
    await assert.rejects(publication_attempt_binding(value,{},options()),InvalidRequest);
    await assert.rejects(publication_issue_attempt(value,{},options()),InvalidRequest);
    assert.throws(()=>publication_transport_for(value,{}),InvalidRequest);
    await assert.rejects(publication_before_write(value,{}, {dispatch_id:'x',sequence:1,request_bytes:[32]},options()),InvalidRequest);
    await assert.rejects(publication_finalization(value,{},async()=>{invoked++;},options()),InvalidRequest);
  }
  assert.equal(invoked,0);
});
