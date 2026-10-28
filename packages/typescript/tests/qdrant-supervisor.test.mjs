import test,{mock} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import childProcess from 'node:child_process';
import http from 'node:http';
import net from 'node:net';
import crypto from 'node:crypto';
import {EventEmitter} from 'node:events';
import {readFileSync} from 'node:fs';
import {ManagedQdrantSupervisor} from '../dist/qdrant-supervisor.js';
import {now} from '../dist/postgres-pool.js';
import {InvalidRequest,UnsupportedCapability,ProviderUnavailable,UnauthorizedScope,IndexNotReady,DeadlineExceeded} from '../dist/errors.js';

const fixture=JSON.parse(readFileSync(new URL('../../../contracts/fixtures/qdrant_candidates.json',import.meta.url),'utf8'));
const config={backend_namespace:'fixture-local',physical_collection:'managed_fixture',collection_incarnation:'inc-1',
  dense_profile:fixture.profiles.dense,sparse_profile:fixture.profiles.sparse};
const options=()=>({deadline:now()+5});
const attempt=(epoch=1)=>({intent_id:'intent-1',owner_token:'00000000-0000-4000-8000-000000000001',epoch,dispatch_id:'dispatch-1'});
const bytes=value=>Array.from(Buffer.from(JSON.stringify(value)));

/** Fake OS/HTTP behavior tests local invariants, never actual process exclusion. */
function runtime(){
  const state={directories:new Set(),files:new Map(),pendingConfig:null,key:null,children:[],requests:[],collections:new Map(),
    nextPid:12000,listenerWrong:false,wait:null,stops:0,spawns:0,oldKeyAccepted:false,
    binaryHash:'830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3',binaryClosed:0};
  const mocks=[];
  const replace=(object,key,implementation)=>mocks.push(mock.method(object,key,implementation));
  replace(fs,'realpath',async path=>path);
  replace(fs,'mkdir',async path=>{if(state.directories.has(path))throw Object.assign(Error('private'),{code:'EEXIST'});state.directories.add(path);});
  replace(fs,'lstat',async path=>({dev:1,ino:path.length,uid:process.getuid(),size:path==='/owned/qdrant'?1:0,mode:path==='/owned/qdrant'?0o100700:0o40700,
    isFile:()=>path==='/owned/qdrant',isDirectory:()=>path!=='/owned/qdrant',isSymbolicLink:()=>false}));
  replace(fs,'open',async(path,flags,mode)=>{
    if(path==='/owned/qdrant'){
      let read=false;
      return {async read(buffer){if(read)return {bytesRead:0};read=true;buffer[0]=97;return {bytesRead:1};},async close(){state.binaryClosed++;}};
    }
    assert.equal(mode,0o600);
    return {async writeFile(value){state.files.set(path,value);},async sync(){},async close(){}};
  });
  replace(crypto,'createHash',()=>{const hash={update(){return hash;},digest(){return state.binaryHash;}};return hash;});
  replace(fs,'rename',async(from,to)=>{state.files.set(to,state.files.get(from));state.files.delete(from);state.pendingConfig=JSON.parse(state.files.get(to));});
  replace(net,'createServer',()=>{
    const server=new EventEmitter();server.listen=(_port,_host,callback)=>queueMicrotask(callback);
    server.address=()=>({port:32123});server.close=callback=>queueMicrotask(callback);return server;
  });
  replace(childProcess,'spawn',(binary,args,settings)=>{
    assert.equal(binary,'/owned/qdrant');assert.equal(args[0],'--config-path');
    assert.equal(Object.keys(settings.env).some(key=>key.startsWith('QDRANT')),false);
    assert.equal(JSON.stringify(args).includes(state.pendingConfig.service.api_key),false);
    const child=new EventEmitter();Object.assign(child,{pid:state.nextPid++,exitCode:null,signalCode:null});
    child.kill=signal=>{state.stops++;child.signalCode=signal;queueMicrotask(()=>child.emit('exit',null,signal));return true;};
    state.children.push(child);state.spawns++;state.key=state.pendingConfig.service.api_key;return child;
  });
  replace(childProcess,'execFile',(_binary,args,_options,callback)=>{
    const child={exitCode:0,signalCode:null,kill(){return true;}};
    queueMicrotask(()=>callback(null,'p'+args[3]+'\nn127.0.0.1:'+(state.listenerWrong?32124:32123)+'\n',''));
    return child;
  });
  replace(http,'request',(settings,callback)=>{
    const request=new EventEmitter();let body=Buffer.alloc(0),destroyed=false;
    request.write=value=>{body=Buffer.from(value);};
    request.destroy=()=>{destroyed=true;};
    request.end=()=>queueMicrotask(async()=>{
      state.waitStarted?.();
      if(state.wait)await state.wait;
      if(destroyed)return;
      state.requests.push({method:settings.method,path:settings.path,key:settings.headers['api-key']});
      let status=200,payload;
      const accepted=settings.headers['api-key']===state.key||state.oldKeyAccepted;
      const parsed=body.length?JSON.parse(body):null;
      const path=settings.path.split('?')[0];
      const parts=path.split('/');const name=parts[2];
      if(!accepted){status=401;payload={status:'error'};}
      else if(path==='/')payload={version:'1.20.0'};
      else if(path==='/cluster')payload={status:'ok',result:{status:'disabled'}};
      else if(path==='/collections')payload={status:'ok',result:{collections:[...state.collections.keys()].map(name=>({name}))}};
      else if(parts.length===3&&settings.method==='PUT'){
        state.collections.set(name,{params:{vectors:parsed.vectors,sparse_vectors:parsed.sparse_vectors??null,
          replication_factor:parsed.replication_factor,write_consistency_factor:parsed.write_consistency_factor},
          optimizer_config:parsed.optimizers_config,points:new Map()});payload={status:'ok',result:true};
      }else if(parts.length===3&&settings.method==='GET'){
        const collection=state.collections.get(name);
        payload={status:'ok',result:{status:'green',optimizer_status:'ok',config:{params:collection.params,optimizer_config:collection.optimizer_config}}};
      }else if(parts[3]==='points'&&settings.method==='PUT'){
        const collection=state.collections.get(name);for(const point of parsed.points)collection.points.set(point.id,point);
        payload={status:'ok',result:{status:'completed'}};
      }else if(parts[3]==='points'&&settings.method==='POST'){
        payload={status:'ok',result:parsed.ids.map(id=>state.collections.get(name).points.get(id)).filter(Boolean)};
      }else throw Error('unexpected synthetic HTTP path');
      const incoming=new EventEmitter();incoming.headers={};incoming.statusCode=status;incoming.destroy=()=>{};
      callback(incoming);queueMicrotask(()=>{incoming.emit('data',Buffer.from(JSON.stringify(payload)));incoming.emit('end');});
    });
    return request;
  });
  return {state,restore(){for(const item of mocks.reverse())item.mock.restore();}};
}
async function provision(admin,probe){
  await admin.request('PUT','/collections/'+config.physical_collection,{...options(),body:bytes({
    vectors:{dense:{size:1536,distance:'Cosine'}},sparse_vectors:{sparse:{}},optimizers_config:{prevent_unoptimized:false},
    replication_factor:1,write_consistency_factor:1})});
  await admin.request('PUT','/collections/'+probe.collection,{...options(),body:bytes(probe.collection_config)});
  await admin.request('PUT','/collections/'+probe.collection+'/points?wait=true&ordering=strong',{...options(),body:bytes({points:[probe.point]})});
}

test('constructor and registration are pure and reject unknown profiles or lifecycle capabilities',async()=>{
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  assert.throws(()=>supervisor.identity(),IndexNotReady);
  assert.throws(()=>supervisor.issue_attempt(attempt(),options()),ProviderUnavailable);
  assert.throws(()=>supervisor.transport_for({}),InvalidRequest);
  assert.throws(()=>supervisor.recovery_binding({drained:true}),UnsupportedCapability);
  assert.throws(()=>supervisor.register_profile({...config,backend_namespace:'foreign'}),InvalidRequest);
  assert.throws(()=>new ManagedQdrantSupervisor('relative','/private/work','instance-1',config),InvalidRequest);
  await supervisor.close();await supervisor.close();
});

test('profile binding requires the complete registered descriptor before returning control metadata',async()=>{
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  const secondary={...config,physical_collection:'secondary',collection_incarnation:'inc-2'};
  supervisor.register_profile(secondary);
  assert.throws(()=>supervisor.profile_binding(config),ProviderUnavailable);
  assert.throws(()=>supervisor.profile_binding(secondary),ProviderUnavailable);
  for(const malformed of [null,{}, {...config,physical_collection:'invalid/name'}]){
    assert.throws(()=>supervisor.profile_binding(malformed),InvalidRequest);
  }
  let hooks=0;
  const accessor={...config};Object.defineProperty(accessor,'backend_namespace',{enumerable:true,get(){hooks++;return 'fixture-local';}});
  const proxy=new Proxy(config,{get(){hooks++;throw Error('hook');}});
  for(const malformed of [accessor,proxy])assert.throws(()=>supervisor.profile_binding(malformed),InvalidRequest);
  assert.equal(hooks,0);
  for(const changed of [{...config,backend_namespace:'other'}, {...config,physical_collection:'unregistered'},
    {...config,collection_incarnation:'other'}, {...config,sparse_profile:null},
    {...config,dense_profile:{...config.dense_profile,model:'other'}}]){
    assert.throws(()=>supervisor.profile_binding(changed),UnsupportedCapability);
  }
  await supervisor.close();
  assert.throws(()=>supervisor.profile_binding(config),ProviderUnavailable);
});

test('profile binding preserves dead and recovery metadata without HTTP or lifecycle mutation', {skip:process.platform!=='darwin'||process.arch!=='arm64'},async()=>{
  const fake=runtime();const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  const secondary={...config,physical_collection:'secondary',collection_incarnation:'inc-2'};
  supervisor.register_profile(secondary);
  try{
    await supervisor.initialize({...options(),provision:async(admin,probe)=>{
      await provision(admin,probe);
      await admin.request('PUT','/collections/secondary',{...options(),body:bytes({
        vectors:{dense:{size:1536,distance:'Cosine'}},sparse_vectors:{sparse:{}},
        optimizers_config:{prevent_unoptimized:false},replication_factor:1,write_consistency_factor:1})});
    }});
    const snapshot=()=>[fake.state.requests.length,fake.state.spawns,fake.state.stops];
    const before=snapshot();
    const metadata=supervisor.profile_binding(structuredClone(config));
    assert.deepEqual(metadata,supervisor.control_binding());assert.ok(Object.isFrozen(metadata));
    assert.deepEqual(supervisor.profile_binding(secondary),metadata);
    assert.equal('api_key'in metadata,false);assert.equal('endpoint'in metadata,false);
    assert.throws(()=>{metadata.epoch=2;},TypeError);
    assert.deepEqual(snapshot(),before);
    const proof=await supervisor.recover({recovery_id:'profile-r',old_epoch:1,new_epoch:2},options());
    await supervisor.seal_recovery(proof,options());
    const recoveryBefore=snapshot();
    const recovery=supervisor.profile_binding(config);
    assert.deepEqual(recovery,supervisor.control_binding());assert.equal(recovery.sealed,true);
    assert.equal(recovery.recovery.recovery_id,'profile-r');assert.ok(Object.isFrozen(recovery.recovery));
    assert.throws(()=>{recovery.recovery.new_epoch=3;},TypeError);
    assert.deepEqual(snapshot(),recoveryBefore);
    assert.throws(()=>supervisor.issue_attempt(attempt(2),options()),ProviderUnavailable);
    fake.state.children.at(-1).kill('SIGKILL');
    assert.equal(supervisor.profile_binding(config).alive,false);
  }finally{await supervisor.close();fake.restore();}
});

test('initialize independently verifies provisioned profiles and opaque ordinary capabilities', {skip:process.platform!=='darwin'||process.arch!=='arm64'}, async()=>{
  const fake=runtime();const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  let retainedAdmin;
  try{
    await supervisor.initialize({...options(),provision:async(admin,probe)=>{retainedAdmin=admin;await provision(admin,probe);return {drained:true};}});
    const identity=supervisor.identity();assert.ok(Object.isFrozen(identity));assert.ok(Object.isFrozen(identity.probe_spec.point));
    assert.equal(Object.keys(identity).includes('api_key'),false);
    assert.throws(()=>supervisor.register_profile(config),InvalidRequest);
    const cap=supervisor.issue_attempt(attempt(),options());assert.deepEqual(JSON.parse(JSON.stringify(cap)),{});
    assert.ok(Object.isFrozen(supervisor.attempt_binding(cap)));
    assert.throws(()=>supervisor.transport_for({...cap}),InvalidRequest);
    const handle=supervisor.transport_for(cap);
    await handle.request('GET','/collections/'+config.physical_collection,options());
    await assert.rejects(handle.request('GET','http://foreign.invalid/',options()),InvalidRequest);
    await assert.rejects(handle.request('PUT','/collections/'+identity.probe_spec.collection+'/points?wait=true',
      {...options(),body:bytes({points:[identity.probe_spec.point]})}),InvalidRequest);
    await assert.rejects(retainedAdmin.request('GET','/',options()),InvalidRequest);
    let delivered=false;
    await supervisor.deliver_worker_credential(cap,credential=>{
      delivered=true;assert.equal(credential.endpoint,identity.endpoint);assert.equal(typeof credential.api_key,'string');
      assert.equal(Object.isFrozen(credential),true);
    },options());assert.equal(delivered,true);
    await handle.close();
  }finally{await supervisor.close();fake.restore();}
});

test('recovery refences physically, keeps ordinary gate closed, and never exports recovery credentials', {skip:process.platform!=='darwin'||process.arch!=='arm64'},async()=>{
  const fake=runtime();const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  try{
    await supervisor.initialize({...options(),provision});
    const old=supervisor.issue_attempt(attempt(),options());const oldHandle=supervisor.transport_for(old);
    const proof=await supervisor.recover({recovery_id:'recovery-1',old_epoch:1,new_epoch:2},options());
    assert.ok(Object.isFrozen(proof));assert.deepEqual(JSON.parse(JSON.stringify(proof)),{});
    assert.throws(()=>supervisor.issue_attempt(attempt(2),options()),ProviderUnavailable);
    assert.throws(()=>supervisor.recovery_binding({...proof}),UnsupportedCapability);
    await assert.rejects(oldHandle.request('GET','/',options()),InvalidRequest);
    await assert.rejects(supervisor.deliver_worker_credential(old,()=>{},options()),ProviderUnavailable);
    const recovery=supervisor.issue_recovery_attempt(proof,{...attempt(2),recovery_id:'recovery-1'},options());
    await assert.rejects(supervisor.deliver_worker_credential(recovery,()=>{},options()),UnsupportedCapability);
    const metadata=supervisor.recovery_binding(proof);assert.equal(metadata.new_epoch,2);assert.equal(Object.keys(metadata).includes('api_key'),false);
    const generation=metadata.credential_generation;
    const replacement=await supervisor.recover({recovery_id:'recovery-1',old_epoch:1,new_epoch:2},options());
    assert.notEqual(supervisor.recovery_binding(replacement).credential_generation,generation);
    assert.throws(()=>supervisor.recovery_binding(proof),UnsupportedCapability);
    assert.equal(fake.state.spawns,3);assert.equal(fake.state.stops,2);
    assert.equal(fake.state.requests.some(request=>request.method==='PUT'&&request.key!==fake.state.key),true);
  }finally{await supervisor.close();fake.restore();}
});

test('configuration drift or a tampered sentinel blocks recovery before any control mutation', {skip:process.platform!=='darwin'||process.arch!=='arm64'},async()=>{
  for(const mode of ['configuration','sentinel','foreign-collection']){
    const fake=runtime();const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
    try{
      await supervisor.initialize({...options(),provision});const probe=supervisor.identity().probe_spec;
      if(mode==='configuration')fake.state.collections.get(config.physical_collection).optimizer_config.prevent_unoptimized=true;
      if(mode==='sentinel')fake.state.collections.get(probe.collection).points.get(probe.point.id).payload={foreign:true};
      if(mode==='foreign-collection')fake.state.collections.set('foreign_collection',{});
      const count=fake.state.requests.length;
      await assert.rejects(supervisor.recover({recovery_id:'recovery-1',old_epoch:1,new_epoch:2},options()),UnsupportedCapability);
      assert.equal(fake.state.requests.slice(count).some(request=>request.method==='PUT'),false);
      assert.throws(()=>supervisor.issue_attempt(attempt(2),options()),ProviderUnavailable);
    }finally{await supervisor.close();fake.restore();}
  }
});

test('existing owner marker cannot be adopted and cleanup never deletes storage', {skip:process.platform!=='darwin'||process.arch!=='arm64'},async()=>{
  const fake=runtime();const first=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  const second=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  try{
    await first.initialize({...options(),provision});await first.close();
    await assert.rejects(second.initialize({...options(),provision}),ProviderUnavailable);
    assert.ok(fake.state.directories.has('/private/work/storage'));assert.equal(fake.state.spawns,1);
  }finally{await first.close();await second.close();fake.restore();}
});

test('wrong listener ownership and missing provision cannot mint a capability', {skip:process.platform!=='darwin'||process.arch!=='arm64'},async()=>{
  for(const mode of ['listener','provision']){
    const fake=runtime();fake.state.listenerWrong=mode==='listener';
    const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
    try{
      await assert.rejects(supervisor.initialize({...options(),...(mode==='listener'?{provision}:{})}),UnsupportedCapability);
      assert.equal(fake.state.stops,1,'failed initialization automatically stops its owned child');
      assert.notEqual(fake.state.children[0].signalCode,null);
      assert.throws(()=>supervisor.issue_attempt(attempt(),options()),ProviderUnavailable);
    }finally{await supervisor.close();fake.restore();}
  }
});

test('pinned binary mismatch fails before workdir creation or child launch', {skip:process.platform!=='darwin'||process.arch!=='arm64'},async()=>{
  const fake=runtime();fake.state.binaryHash='0'.repeat(64);
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  try{
    await assert.rejects(supervisor.initialize({...options(),provision}),UnsupportedCapability);
    assert.equal(fake.state.binaryClosed,1);assert.equal(fake.state.spawns,0);assert.equal(fake.state.directories.size,0);
  }finally{await supervisor.close();fake.restore();}
});

test('provision failure stops and reaps the child without exposing callback messages', {skip:process.platform!=='darwin'||process.arch!=='arm64'},async()=>{
  const fake=runtime();const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  try{
    await assert.rejects(supervisor.initialize({...options(),provision:()=>{throw Error('private credential canary');}}),
      error=>error instanceof ProviderUnavailable&&!String(error).includes('private'));
    assert.equal(fake.state.stops,1);assert.notEqual(fake.state.children[0].signalCode,null);
    assert.ok(fake.state.directories.has('/private/work/storage'));
  }finally{await supervisor.close();fake.restore();}
});

test('expired options and fake proofs are rejected without launching a process',async()=>{
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  await assert.rejects(supervisor.initialize({deadline:now()-1}),DeadlineExceeded);
  assert.throws(()=>supervisor.issue_recovery_attempt({drained:true},{...attempt(2),recovery_id:'recovery-1'},options()),UnsupportedCapability);
  await supervisor.close();
});

test('transport enforces the remaining response allowance before buffering a larger body', {skip:process.platform!=='darwin'||process.arch!=='arm64'},async()=>{
  const fake=runtime();
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  try{
    await supervisor.initialize({...options(),provision});
    const handle=supervisor.transport_for(supervisor.issue_attempt(attempt(),options()));
    const before=fake.state.requests.length;
    for(const maximum of [0,-1,1.5,1048577,Infinity,true]){
      await assert.rejects(handle.request('GET','/',{...options(),max_response_bytes:maximum}),InvalidRequest);
    }
    assert.equal(fake.state.requests.length,before,'invalid allowances never dispatch');
    await assert.rejects(handle.request('GET','/',{...options(),max_response_bytes:1}),ProviderUnavailable);
    const expected=Buffer.from(JSON.stringify({version:'1.20.0'}));
    assert.deepEqual(Buffer.from(await handle.request('GET','/',{...options(),max_response_bytes:expected.length})),expected);
    await handle.close();
  }finally{await supervisor.close();fake.restore();}
});

test('control metadata can block ordinary admission but does not represent fencing', {skip:process.platform!=='darwin'||process.arch!=='arm64'},async()=>{
  const fake=runtime();
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  try{
    assert.throws(()=>supervisor.control_binding(),ProviderUnavailable);
    await supervisor.initialize({...options(),provision});
    const metadata=supervisor.control_binding();
    assert.equal(metadata.epoch,1);assert.equal(metadata.alive,true);assert.equal(metadata.recovery,null);
    assert.equal('api_key'in metadata,false);
    supervisor.block_ordinary();
    assert.throws(()=>supervisor.issue_attempt(attempt(),options()),ProviderUnavailable);
    assert.equal(fake.state.stops,0);
    fake.state.children.at(-1).kill('SIGKILL');
    assert.equal(supervisor.control_binding().alive,false);
  }finally{await supervisor.close();fake.restore();}
});

test('sealed recovery closes handles and requires private SQL settlement before reopening', {skip:process.platform!=='darwin'||process.arch!=='arm64'},async()=>{
  const fake=runtime();
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  try{
    await supervisor.initialize({...options(),provision});
    const recovery={recovery_id:'r',old_epoch:1,new_epoch:2};
    const proof=await supervisor.recover(recovery,options());
    const cap=supervisor.issue_recovery_attempt(proof,{...attempt(2),recovery_id:'r'},options());
    const handle=supervisor.transport_for(cap);
    const physical=supervisor.recovery_binding(proof);
    const barrier=await supervisor.seal_recovery(proof,options());
    assert.deepEqual(supervisor.barrier_binding(barrier),physical);
    assert.equal(await supervisor.seal_recovery(proof,options()),barrier);
    assert.equal(supervisor.control_binding().sealed,true);
    await assert.rejects(handle.request('GET','/',options()),InvalidRequest);
    assert.throws(()=>supervisor.recovery_binding(proof),UnsupportedCapability);
    assert.throws(()=>supervisor.barrier_binding({...barrier}),UnsupportedCapability);
    assert.throws(()=>supervisor.finish_recovery(barrier,{},options()),UnsupportedCapability);
    assert.throws(()=>supervisor.issue_attempt(attempt(2),options()),ProviderUnavailable);
    const replacement=await supervisor.recover(recovery,options());
    assert.notEqual(supervisor.recovery_binding(replacement).credential_generation,physical.credential_generation);
    assert.throws(()=>supervisor.barrier_binding(barrier),UnsupportedCapability);
    assert.equal(supervisor.control_binding().sealed,false);
  }finally{await supervisor.close();fake.restore();}
});

test('exclusive sessions do not authorize raw calls in the callback or inherited sibling context', {skip:process.platform!=='darwin'||process.arch!=='arm64'},async()=>{
  const fake=runtime();
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  let escaped;
  try{
    await supervisor.initialize({...options(),provision});
    const cap=supervisor.issue_attempt(attempt(),options());
    const handle=supervisor.transport_for(cap);
    await supervisor.control_session(async control=>{
      escaped=control;
      await assert.rejects(supervisor.control_session(async()=>{}),ProviderUnavailable);
      assert.throws(()=>supervisor.block_ordinary(),ProviderUnavailable);
      assert.throws(()=>supervisor.issue_attempt(attempt(),options()),ProviderUnavailable);
      assert.throws(()=>supervisor.transport_for(cap),ProviderUnavailable);
      await assert.rejects(supervisor.close(),ProviderUnavailable);
      await assert.rejects(handle.request('GET','/',options()),ProviderUnavailable);
      const request={recovery_id:'r',old_epoch:1,new_epoch:2};
      await assert.rejects(supervisor.recover(request,options()),ProviderUnavailable);
      await assert.rejects(Promise.resolve().then(()=>supervisor.recover(request,options())),ProviderUnavailable);
      control.block_ordinary();
    });
    assert.throws(()=>escaped.block_ordinary(),ProviderUnavailable);
    await supervisor.control_session(async()=>{});
    await handle.close();
  }finally{await supervisor.close();fake.restore();}
});

test('an existing raw lifecycle excludes new shared admission', {skip:process.platform!=='darwin'||process.arch!=='arm64'},async()=>{
  const fake=runtime();
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  let release;
  try{
    await supervisor.initialize({...options(),provision});
    const started=new Promise(resolve=>{fake.state.waitStarted=resolve;});
    fake.state.wait=new Promise(resolve=>{release=resolve;});
    const work=supervisor.recover({recovery_id:'r',old_epoch:1,new_epoch:2},options());
    await started;
    await assert.rejects(supervisor.control_session(async()=>{}),ProviderUnavailable);
    release();await work;
  }finally{release?.();await supervisor.close();fake.restore();}
});

test('session release waits for started facade work even when its callback returned', {skip:process.platform!=='darwin'||process.arch!=='arm64'},async()=>{
  const fake=runtime();
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  let release,escaped,finished=false;
  try{
    await supervisor.initialize({...options(),provision});
    const started=new Promise(resolve=>{fake.state.waitStarted=resolve;});
    fake.state.wait=new Promise(resolve=>{release=resolve;});
    const work=supervisor.control_session(async control=>{
      escaped=control;
      void control.recover({recovery_id:'r',old_epoch:1,new_epoch:2},options());
      await started;
    }).then(()=>{finished=true;});
    await started;await new Promise(resolve=>setImmediate(resolve));
    assert.equal(finished,false);
    await assert.rejects(supervisor.control_session(async()=>{}),ProviderUnavailable);
    assert.throws(()=>escaped.block_ordinary(),ProviderUnavailable);
    release();await work;
    assert.throws(()=>escaped.block_ordinary(),ProviderUnavailable);
  }finally{release?.();await supervisor.close();fake.restore();}
});

test('cancellation retains native unwind before another session can enter', {skip:process.platform!=='darwin'||process.arch!=='arm64'},async()=>{
  const fake=runtime();
  const supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  let release;
  try{
    await supervisor.initialize({...options(),provision});
    const started=new Promise(resolve=>{fake.state.waitStarted=resolve;});
    fake.state.wait=new Promise(resolve=>{release=resolve;});
    const cancellation=new AbortController();
    const work=supervisor.control_session(async control=>{
      await control.recover({recovery_id:'r',old_epoch:1,new_epoch:2},{...options(),signal:cancellation.signal});
    });
    await started;cancellation.abort();
    await assert.rejects(work,error=>error.name==='AbortError');
    await supervisor.control_session(async control=>{control.block_ordinary();});
  }finally{release?.();await supervisor.close();fake.restore();}
});

const recoveryInput={recovery_id:'session-recovery',old_epoch:1,new_epoch:2};
const recoveryAttempt=()=>({...attempt(2),recovery_id:recoveryInput.recovery_id});
const nativeDouble={skip:process.platform!=='darwin'||process.arch!=='arm64'};

test('session recovery transport accepts only attempts issued by its exact live facade',nativeDouble,async()=>{
  const fake=runtime(),supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  try{
    await supervisor.initialize({...options(),provision});
    const ordinary=supervisor.issue_attempt(attempt(),options());
    const proof=await supervisor.recover(recoveryInput,options());
    const raw=supervisor.issue_recovery_attempt(proof,recoveryAttempt(),options());
    let escaped,issued;
    await supervisor.control_session(async control=>{
      escaped=control;
      for(const foreign of [ordinary,raw,{},JSON.parse(JSON.stringify(raw))])assert.throws(()=>control.recovery_transport_for(foreign),InvalidRequest);
      assert.throws(()=>control.issue_recovery_attempt({...proof},recoveryAttempt(),options()),UnsupportedCapability);
      issued=control.issue_recovery_attempt(proof,recoveryAttempt(),options());
      assert.throws(()=>supervisor.issue_recovery_attempt(proof,recoveryAttempt(),options()),ProviderUnavailable);
      assert.throws(()=>supervisor.transport_for(issued),ProviderUnavailable);
      const handle=control.recovery_transport_for(issued);
      assert.ok((await handle.request('GET','/',options())).length>0);
      await handle.close();
    });
    assert.throws(()=>escaped.issue_recovery_attempt(proof,recoveryAttempt(),options()),ProviderUnavailable);
    assert.throws(()=>escaped.recovery_transport_for(issued),ProviderUnavailable);
    await supervisor.control_session(async control=>assert.throws(()=>control.recovery_transport_for(issued),InvalidRequest));
  }finally{await supervisor.close();fake.restore();}
});

test('session handles retain eight live slots and close frees a slot without closing borrowed transport',nativeDouble,async()=>{
  const fake=runtime(),supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  let borrowed,escaped;
  try{
    await supervisor.initialize({...options(),provision});const proof=await supervisor.recover(recoveryInput,options());
    const raw=supervisor.issue_recovery_attempt(proof,recoveryAttempt(),options());borrowed=supervisor.transport_for(raw);
    await supervisor.control_session(async control=>{
      const cap=control.issue_recovery_attempt(proof,recoveryAttempt(),options());
      const handles=Array.from({length:8},()=>control.recovery_transport_for(cap));escaped=handles[0];
      assert.throws(()=>control.recovery_transport_for(cap),ProviderUnavailable);
      await handles[1].close();
      const replacement=control.recovery_transport_for(cap);
      assert.ok((await replacement.request('GET','/',options())).length>0);
      await assert.rejects(borrowed.request('GET','/',options()),ProviderUnavailable);
    });
    await assert.rejects(escaped.request('GET','/',options()),ProviderUnavailable);
    assert.ok((await borrowed.request('GET','/',options())).length>0);
  }finally{await borrowed?.close();await supervisor.close();fake.restore();}
});

test('session recovery handle keeps existing routes body response limits and one request at a time',nativeDouble,async()=>{
  const fake=runtime(),supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  let release;
  try{
    await supervisor.initialize({...options(),provision});const proof=await supervisor.recover(recoveryInput,options());
    await supervisor.control_session(async control=>{
      const handle=control.recovery_transport_for(control.issue_recovery_attempt(proof,recoveryAttempt(),options()));
      for(const [method,path,opts] of [['PUT','/collections/foreign/points?wait=true',{...options(),body:bytes({points:[]})}],
        ['GET','/',{...options(),body:[]}],['POST','/collections/managed_fixture/points',options()],
        ['GET','/',{...options(),max_response_bytes:1048577}]])await assert.rejects(handle.request(method,path,opts),InvalidRequest);
      const started=new Promise(resolve=>{fake.state.waitStarted=resolve;});fake.state.wait=new Promise(resolve=>{release=resolve;});
      const pending=handle.request('GET','/',options());
      await assert.rejects(handle.request('GET','/',options()),ProviderUnavailable);
      await started;release();await pending;fake.state.wait=null;
      await handle.close();await assert.rejects(handle.request('GET','/',options()),InvalidRequest);
    });
  }finally{release?.();await supervisor.close();fake.restore();}
});

test('session callback return drains unawaited recovery HTTP before releasing exclusion',nativeDouble,async()=>{
  const fake=runtime(),supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  let release,escaped,handle,finished=false;
  try{
    await supervisor.initialize({...options(),provision});const proof=await supervisor.recover(recoveryInput,options());
    const started=new Promise(resolve=>{fake.state.waitStarted=resolve;});fake.state.wait=new Promise(resolve=>{release=resolve;});
    const session=supervisor.control_session(async control=>{
      escaped=control;handle=control.recovery_transport_for(control.issue_recovery_attempt(proof,recoveryAttempt(),options()));
      void handle.request('GET','/',options());await started;
    }).then(()=>{finished=true;});
    await started;await new Promise(resolve=>setImmediate(resolve));
    assert.equal(finished,false);await assert.rejects(supervisor.control_session(async()=>{}),ProviderUnavailable);
    await assert.rejects(handle.request('GET','/',options()),ProviderUnavailable);
    assert.throws(()=>escaped.issue_recovery_attempt(proof,recoveryAttempt(),options()),ProviderUnavailable);
    await assert.rejects(supervisor.close(),ProviderUnavailable);
    release();await session;fake.state.wait=null;
    await supervisor.control_session(async()=>{});
    await assert.rejects(handle.request('GET','/',options()),ProviderUnavailable);
  }finally{release?.();await supervisor.close();fake.restore();}
});

test('late inherited facade work cannot start recovery HTTP after callback exit',nativeDouble,async()=>{
  const fake=runtime(),supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  let late,handle;
  try{
    await supervisor.initialize({...options(),provision});const proof=await supervisor.recover(recoveryInput,options());
    await supervisor.control_session(async control=>{
      const cap=control.issue_recovery_attempt(proof,recoveryAttempt(),options());handle=control.recovery_transport_for(cap);
      late=()=>handle.request('GET','/',options());
    });
    const count=fake.state.requests.length;
    await assert.rejects(Promise.resolve().then(late),ProviderUnavailable);
    assert.equal(fake.state.requests.length,count);
  }finally{await supervisor.close();fake.restore();}
});

test('session recovery handle rejects retired proof and does not refresh its captured key',nativeDouble,async()=>{
  const fake=runtime(),supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  try{
    await supervisor.initialize({...options(),provision});const proof=await supervisor.recover(recoveryInput,options());
    await supervisor.control_session(async control=>{
      const cap=control.issue_recovery_attempt(proof,recoveryAttempt(),options());const handle=control.recovery_transport_for(cap);
      const replacement=await control.recover(recoveryInput,options());
      assert.throws(()=>control.issue_recovery_attempt(proof,recoveryAttempt(),options()),UnsupportedCapability);
      assert.throws(()=>control.recovery_transport_for(cap),UnsupportedCapability);
      await assert.rejects(handle.request('GET','/',options()),UnsupportedCapability);
      const fresh=control.recovery_transport_for(control.issue_recovery_attempt(replacement,recoveryAttempt(),options()));
      assert.ok((await fresh.request('GET','/',options())).length>0);
    });
  }finally{await supervisor.close();fake.restore();}
});

test('session cancellation rejects recovery request and closes owned handle before another session enters',nativeDouble,async()=>{
  const fake=runtime(),supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  let release,handle;
  try{
    await supervisor.initialize({...options(),provision});const proof=await supervisor.recover(recoveryInput,options());
    const cancellation=new AbortController(),started=new Promise(resolve=>{fake.state.waitStarted=resolve;});
    fake.state.wait=new Promise(resolve=>{release=resolve;});
    const session=supervisor.control_session(async control=>{
      handle=control.recovery_transport_for(control.issue_recovery_attempt(proof,recoveryAttempt(),options()));
      await handle.request('GET','/',{...options(),signal:cancellation.signal});
    });
    await started;cancellation.abort();await assert.rejects(session,error=>error.name==='AbortError');
    release();fake.state.wait=null;
    await supervisor.control_session(async()=>{});
    await assert.rejects(handle.request('GET','/',options()),ProviderUnavailable);
  }finally{release?.();await supervisor.close();fake.restore();}
});

test('session tracks concurrent owned handles while raw physical proof access remains excluded',nativeDouble,async()=>{
  const fake=runtime(),supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  let release;
  try{
    await supervisor.initialize({...options(),provision});const proof=await supervisor.recover(recoveryInput,options());
    await supervisor.control_session(async control=>{
      const cap=control.issue_recovery_attempt(proof,recoveryAttempt(),options());
      const first=control.recovery_transport_for(cap),second=control.recovery_transport_for(cap);
      const started=new Promise(resolve=>{fake.state.waitStarted=resolve;});fake.state.wait=new Promise(resolve=>{release=resolve;});
      const one=first.request('GET','/',options()),two=second.request('GET','/',options());
      await started;
      assert.throws(()=>supervisor.recovery_binding(proof),ProviderUnavailable);
      release();await Promise.all([one,two]);fake.state.wait=null;
    });
  }finally{release?.();await supervisor.close();fake.restore();}
});

test('callback failure still drains owned recovery request before surfacing the primary error',nativeDouble,async()=>{
  const fake=runtime(),supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  let release,finished=false;
  try{
    await supervisor.initialize({...options(),provision});const proof=await supervisor.recover(recoveryInput,options());
    const primary=new Error('synthetic callback failure');
    const started=new Promise(resolve=>{fake.state.waitStarted=resolve;});fake.state.wait=new Promise(resolve=>{release=resolve;});
    const session=supervisor.control_session(async control=>{
      const handle=control.recovery_transport_for(control.issue_recovery_attempt(proof,recoveryAttempt(),options()));
      void handle.request('GET','/',options());await started;throw primary;
    });
    const observed=session.then(()=>{throw Error('missing failure');},error=>{finished=true;assert.equal(error,primary);});
    await started;await new Promise(resolve=>setImmediate(resolve));assert.equal(finished,false);
    await assert.rejects(supervisor.control_session(async()=>{}),ProviderUnavailable);
    release();await observed;fake.state.wait=null;
    await supervisor.control_session(async()=>{});
  }finally{release?.();await supervisor.close();fake.restore();}
});

test('private session binding requires original active facade and tracks every admitted request',nativeDouble,async()=>{
  const {control_session_binding}=await import('../dist/qdrant-supervisor.js');
  const fake=runtime(),supervisor=new ManagedQdrantSupervisor('/owned/qdrant','/private/work','instance-1',config);
  let escaped;
  try{
    await supervisor.initialize({...options(),provision});const proof=await supervisor.recover(recoveryInput,options());
    await supervisor.control_session(async control=>{
      escaped=control;
      const first=control_session_binding(control,supervisor,proof);
      assert.deepEqual(Object.keys(first).sort(),['activity','physical_binding']);assert.equal(first.activity,0);
      assert.deepEqual(first.physical_binding,supervisor.recovery_binding(proof));
      for(const forged of [{},{...control},new Proxy(control,{})])assert.throws(()=>control_session_binding(forged,supervisor,proof),InvalidRequest);
      assert.throws(()=>control_session_binding(control,{},proof),InvalidRequest);
      assert.throws(()=>control_session_binding(control,supervisor,{...proof}),UnsupportedCapability);
      assert.throws(()=>{first.activity=100;},TypeError);
      const handle=control.recovery_transport_for(control.issue_recovery_attempt(proof,recoveryAttempt(),options()));
      assert.equal(control_session_binding(control,supervisor,proof).activity,1);
      await handle.request('GET','/',options());assert.equal(control_session_binding(control,supervisor,proof).activity,2);
      await handle.request('GET','/',options());assert.equal(control_session_binding(control,supervisor,proof).activity,3);
      await handle.close();assert.equal(first.activity,0);
    });
    assert.throws(()=>control_session_binding(escaped,supervisor,proof),InvalidRequest);
    await supervisor.control_session(async control=>{
      assert.equal(control_session_binding(control,supervisor,proof).activity,0);
      assert.throws(()=>control_session_binding(escaped,supervisor,proof),InvalidRequest);
    });
  }finally{await supervisor.close();fake.restore();}
});
