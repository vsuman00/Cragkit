/** Optional macOS reference controller. It never represents a SQL recovery gate. */
import fs from 'node:fs/promises';
import childProcess, { type ChildProcess } from 'node:child_process';
import http from 'node:http';
import net from 'node:net';
import { constants } from 'node:fs';
import crypto, { randomBytes, randomUUID } from 'node:crypto';
import { dirname, basename, isAbsolute, join } from 'node:path';
import { bounded, now, type LeaseOptions } from './postgres-pool.js';
import { parse_config, parse_response, same, type QdrantConfig } from './qdrant-contract.js';
import { fields, metadata, native_array, options as lease_options, text, uuid, count } from './qdrant-writer-contract.js';
import { DeadlineExceeded, IndexNotReady, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope, UnsupportedCapability } from './errors.js';
import { settlement_data } from './qdrant-recovery.js';

export type Attempt = Readonly<Record<never, never>>;
export type PhysicalRecovery = Readonly<Record<never, never>>;
export type RecoveryBarrier = Readonly<Record<never, never>>;
export type SupervisorControlSession = Readonly<{
  block_ordinary():void;
  recover(input:unknown,options:unknown):Promise<PhysicalRecovery>;
  seal_recovery(proof:unknown,options:unknown):Promise<RecoveryBarrier>;
  finish_recovery(barrier:unknown,settlement:unknown,options:unknown):void;
}>;
type ProbeSpec = Readonly<{collection:string;collection_config:Readonly<Record<string,unknown>>;point:Readonly<Record<string,unknown>>}>;
type Identity = Readonly<{instance_id:string;storage_identity:string;supervisor_id:string;endpoint:string;probe_spec:ProbeSpec}>;
type Binding = Readonly<{intent_id:string;owner_token:string;epoch:number;dispatch_id:string;recovery_id?:string}>;
type AttemptData = Readonly<{binding:Binding;key:string;credential_generation:string;recovery:boolean;proof?:PhysicalRecovery}>;
type ProofData = Readonly<{recovery_id:string;old_epoch:number;new_epoch:number;credential_generation:string}>;
type Options = LeaseOptions & {max_response_bytes?:number};
type RequestOptions = Readonly<{body?:readonly number[];deadline:number;signal?:AbortSignal;max_response_bytes?:number}>;
export interface SupervisorTransport {
  request(method:string,path:string,options:RequestOptions):Promise<readonly number[]>;
  close():Promise<void>;
}
type ManagedHandle = SupervisorTransport & {inflight:()=>boolean};
const KEY_LIMIT=1048576;
const RESPONSE_LIMIT=1048576;
const BINARY_SHA256='830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3';
const CHILD_ENV=Object.freeze({PATH:'/usr/bin:/bin'});

function safe(error:unknown):Error {
  if(error instanceof DeadlineExceeded)return new DeadlineExceeded();
  if(error instanceof InvalidRequest)return new InvalidRequest();
  if(error instanceof UnauthorizedScope)return new UnauthorizedScope();
  if(error instanceof UnsupportedCapability)return new UnsupportedCapability();
  if(error instanceof IndexNotReady)return new IndexNotReady();
  if(error instanceof DOMException&&error.name==='AbortError')return new DOMException('Operation aborted.','AbortError');
  return new ProviderUnavailable();
}
function freeze(value:unknown):unknown {
  if(value!==null&&typeof value==='object'){
    for(const child of Object.values(value))freeze(child);
    Object.freeze(value);
  }
  return value;
}
function response(bytes:readonly number[]):Record<string,unknown>{
  const parsed=parse_response(Buffer.from(bytes));
  if(typeof parsed!=='object'||parsed===null||Array.isArray(parsed))throw new ProviderUnavailable();
  return parsed as Record<string,unknown>;
}
function result(bytes:readonly number[]):Record<string,unknown>{
  const parsed=response(bytes);
  if(parsed.status!=='ok'||typeof parsed.result!=='object'||parsed.result===null||Array.isArray(parsed.result))throw new ProviderUnavailable();
  return parsed.result as Record<string,unknown>;
}
function path_string(input:unknown):string {
  if(typeof input!=='string'||input.length>4096||!isAbsolute(input)||/[\0\r\n]/.test(input))throw new InvalidRequest();
  return input;
}
function binding(input:unknown,recovery=false):Binding {
  const value=fields(input,['intent_id','owner_token','epoch','dispatch_id',...(recovery?['recovery_id']:[])]);
  return Object.freeze({intent_id:text(value.intent_id),owner_token:uuid(value.owner_token),epoch:count(value.epoch,1),
    dispatch_id:text(value.dispatch_id),...(recovery?{recovery_id:text(value.recovery_id)}:{})});
}
function byte_body(input:unknown):Buffer|undefined {
  if(input===undefined)return undefined;
  return Buffer.from(native_array(input,0,KEY_LIMIT).map(value=>count(value,0,255)));
}
function startup_profile():void {
  const flags=[process.env.NODE_OPTIONS??'',...process.execArgv].join(' ').replace(/["'\\\s]/g,'');
  if(process.env.NODE_USE_ENV_PROXY==='1'||/--use[-_]env[-_]proxy/i.test(flags)
    ||process.env.NODE_TLS_REJECT_UNAUTHORIZED==='0')throw new UnsupportedCapability();
}

export class ManagedQdrantSupervisor {
  readonly #binary:string;
  readonly #requestedWork:string;
  readonly #instance:string;
  readonly #profiles=new Map<string,QdrantConfig>();
  readonly #attempts=new WeakMap<object,AttemptData>();
  readonly #proofs=new WeakMap<object,ProofData>();
  readonly #handles=new Set<ManagedHandle>();
  #identity?:Identity;
  #work?:string;
  #storageStamp?:Readonly<{dev:number;ino:number}>;
  #workStamp?:Readonly<{dev:number;ino:number}>;
  #child?:ChildProcess;
  #exit?:Promise<void>;
  #key='';
  #credentialGeneration='';
  #epoch=1;
  #ordinaryOpen=false;
  #state:'new'|'initializing'|'open'|'recovering'|'recovery_only'|'recovery_sealed'|'failed'|'closed'='new';
  #active?:Readonly<{controller:AbortController;done:Promise<void>}>;
  #closing?:Promise<void>;
  #recovery?:ProofData;
  #recoveryOldKey?:string;
  #currentProof?:PhysicalRecovery;
  #currentBarrier?:RecoveryBarrier;
  readonly #barriers=new WeakMap<object,Readonly<{proof:PhysicalRecovery;binding:Readonly<Record<string,unknown>>}>>();
  #controlToken?:object;
  #controlDraining=false;
  readonly #controlWork=new Set<Promise<unknown>>();
  constructor(binary:unknown,work_dir:unknown,instance_id:unknown,config:unknown){
    this.#binary=path_string(binary);this.#requestedWork=path_string(work_dir);this.#instance=text(instance_id);
    const primary=parse_config(metadata(config));this.#profiles.set(primary.physical_collection,primary);
  }
  register_profile(input:unknown):void {
    this.#controlAccess();
    if(this.#state!=='new')throw new InvalidRequest();
    const profile=parse_config(metadata(input)),primary=this.#profiles.values().next().value!;
    if(profile.backend_namespace!==primary.backend_namespace)throw new InvalidRequest();
    const old=this.#profiles.get(profile.physical_collection);
    if(old&&!same(old,profile))throw new InvalidRequest();
    if(!old&&this.#profiles.size>=16)throw new InvalidRequest();
    this.#profiles.set(profile.physical_collection,profile);
  }
  identity():Identity {
    if(!this.#identity)throw new IndexNotReady();
    return this.#identity;
  }
  control_binding():Readonly<Record<string,unknown>> {
    if(!this.#identity||this.#state==='new'||this.#state==='initializing'||this.#state==='closed'){
      throw new ProviderUnavailable();
    }
    const identity=this.#identity;
    const recovery=this.#recovery?Object.freeze({
      recovery_id:this.#recovery.recovery_id,
      old_epoch:this.#recovery.old_epoch,
      new_epoch:this.#recovery.new_epoch,
    }):null;
    return Object.freeze({
      instance_id:identity.instance_id,
      backend_namespace:this.#profiles.values().next().value!.backend_namespace,
      storage_identity:identity.storage_identity,
      supervisor_id:identity.supervisor_id,
      epoch:this.#epoch,
      credential_generation:this.#credentialGeneration,
      recovery,
      sealed:this.#state==='recovery_sealed',
      alive:this.#alive(),
    });
  }
  profile_binding(input:unknown):Readonly<Record<string,unknown>> {
    const profile=parse_config(metadata(input));
    const registered=this.#profiles.get(profile.physical_collection);
    if(!registered||!same(registered,profile))throw new UnsupportedCapability();
    return this.control_binding();
  }
  #controlAccess(token?:object):void {
    if(token!==this.#controlToken||(token!==undefined&&this.#controlDraining)){
      throw new ProviderUnavailable();
    }
  }
  async control_session<T>(body:(control:SupervisorControlSession)=>Promise<T>):Promise<T> {
    if(typeof body!=='function')throw new InvalidRequest();
    if(this.#controlToken||this.#active||this.#closing||this.#state==='closed')throw new ProviderUnavailable();
    const token=Object.freeze({});
    this.#controlToken=token;
    const track=<R>(operation:()=>Promise<R>):Promise<R>=>{
      this.#controlAccess(token);
      const work=operation();
      this.#controlWork.add(work);
      void work.then(()=>this.#controlWork.delete(work),()=>this.#controlWork.delete(work));
      return work;
    };
    const control:SupervisorControlSession=Object.freeze({
      block_ordinary:()=>this.block_ordinary(token),
      recover:(input,options)=>track(()=>this.recover(input,options,token)),
      seal_recovery:(proof,options)=>track(()=>this.seal_recovery(proof,options,token)),
      finish_recovery:(barrier,settlement,options)=>this.finish_recovery(barrier,settlement,options,token),
    });
    try{
      return await body(control);
    }finally{
      this.#controlDraining=true;
      let failed=false;
      try{
        const outcomes=await Promise.allSettled([...this.#controlWork]);
        failed=outcomes.some(outcome=>outcome.status==='rejected');
      }finally{
        this.#controlToken=undefined;
        this.#controlDraining=false;
      }
      if(failed)throw new ProviderUnavailable();
    }
  }
  block_ordinary(_control?:object):void {
    this.#controlAccess(_control);
    this.control_binding();
    this.#ordinaryOpen=false;
  }
  async #run<T>(options:Options,task:(options:Options)=>Promise<T>):Promise<T>{
    if(this.#closing||this.#state==='closed'||this.#active)throw new ProviderUnavailable();
    const controller=new AbortController(),relay=()=>controller.abort();
    options.signal?.addEventListener('abort',relay,{once:true});
    if(options.signal?.aborted)controller.abort();
    let finish!:()=>void;
    const done=new Promise<void>(resolve=>{finish=resolve;});this.#active={controller,done};
    const operation=Promise.resolve().then(()=>task({deadline:options.deadline,signal:controller.signal}));
    try{return await bounded(operation,{deadline:options.deadline,signal:controller.signal});}
    catch(error){
      controller.abort();
      // Retain lifecycle and session ownership until the actual native body
      // finishes unwinding; a timeout race alone cannot release admission.
      try{await operation;}catch{ /* The primary error remains redacted below. */ }
      this.#ordinaryOpen=false;
      if(!this.#closing)this.#state='failed';
      throw safe(error);
    }
    finally{options.signal?.removeEventListener('abort',relay);this.#active=undefined;finish();}
  }
  async #port(options:Options):Promise<number>{
    const server=net.createServer();
    const listening=new Promise<number>((resolve,reject)=>{
      server.once('error',reject);
      server.listen(0,'127.0.0.1',()=>{const address=server.address();if(!address||typeof address==='string')reject(new ProviderUnavailable());else resolve(address.port);});
    });
    try{return await bounded(listening,options);}
    finally{await bounded(new Promise<void>(resolve=>server.close(()=>resolve())),{deadline:now()+1});}
  }
  async #ownedDirectories(options:Options):Promise<void>{
    if(process.platform!=='darwin'||process.arch!=='arm64')throw new UnsupportedCapability();
    const binary=await bounded(fs.lstat(this.#binary),options);
    if(!binary.isFile()||binary.isSymbolicLink()||!(binary.mode&0o111)
      ||!Number.isSafeInteger(binary.size)||binary.size<1||binary.size>536870912)throw new UnsupportedCapability();
    const executable=await bounded(fs.open(this.#binary,constants.O_RDONLY|constants.O_NOFOLLOW),options);
    try{
      const digest=crypto.createHash('sha256'),chunk=Buffer.alloc(65536);
      let size=0;
      for(;;){
        lease_options(options);
        const read=await bounded(executable.read(chunk,0,chunk.length,null),options);
        if(read.bytesRead===0)break;
        if(read.bytesRead>chunk.length||read.bytesRead>536870912-size)throw new UnsupportedCapability();
        size+=read.bytesRead;digest.update(chunk.subarray(0,read.bytesRead));
      }
      if(size!==binary.size||digest.digest('hex')!==BINARY_SHA256)throw new UnsupportedCapability();
    }finally{await bounded(executable.close(),{deadline:now()+1});}
    const parent=await bounded(fs.realpath(dirname(this.#requestedWork)),options);
    const work=join(parent,basename(this.#requestedWork));
    // mkdir is the persistent, atomic ownership marker. Existing directories
    // are never adopted, including after a dead supervisor.
    await bounded(fs.mkdir(work,{mode:0o700}),options);this.#work=work;
    const stat=await bounded(fs.lstat(work),options);
    if(!stat.isDirectory()||stat.isSymbolicLink()||stat.uid!==process.getuid?.()||(stat.mode&0o077))throw new UnsupportedCapability();
    this.#workStamp=Object.freeze({dev:stat.dev,ino:stat.ino});
    await bounded(fs.mkdir(join(work,'storage'),{mode:0o700}),options);
    await bounded(fs.mkdir(join(work,'snapshots'),{mode:0o700}),options);
    const storage=await bounded(fs.lstat(join(work,'storage')),options);
    this.#storageStamp=Object.freeze({dev:storage.dev,ino:storage.ino});
    const port=await this.#port(options),supervisor_id=randomUUID(),storage_identity=randomUUID();
    const collection='cragkit_control_'+randomBytes(8).toString('hex');
    if(this.#profiles.has(collection))throw new UnsupportedCapability();
    const probe_spec=freeze({collection,collection_config:{vectors:{control:{size:1,distance:'Cosine'}},
      optimizers_config:{prevent_unoptimized:false},replication_factor:1,write_consistency_factor:1},
      point:{id:randomUUID(),vector:{control:[1]},payload:{supervisor_id,storage_identity}}}) as ProbeSpec;
    this.#identity=freeze({instance_id:this.#instance,storage_identity,supervisor_id,endpoint:'http://127.0.0.1:'+port,probe_spec}) as Identity;
    const marker=await bounded(fs.open(join(work,'owner.json'),constants.O_WRONLY|constants.O_CREAT|constants.O_EXCL|constants.O_NOFOLLOW,0o600),options);
    try{await bounded(marker.writeFile(JSON.stringify({instance_id:this.#instance,storage_identity,supervisor_id})),options);}
    finally{await marker.close();}
  }
  async #verifyStorage(options:Options):Promise<void>{
    if(!this.#work||!this.#workStamp||!this.#storageStamp)throw new ProviderUnavailable();
    for(const [path,expected] of [[this.#work,this.#workStamp],[join(this.#work,'storage'),this.#storageStamp]] as const){
      const current=await bounded(fs.lstat(path),options);
      if(!current.isDirectory()||current.isSymbolicLink()||current.dev!==expected.dev||current.ino!==expected.ino
        ||current.uid!==process.getuid?.()||(current.mode&0o077))throw new UnsupportedCapability();
    }
  }
  async #writeConfig(key:string,options:Options):Promise<void>{
    await this.#verifyStorage(options);
    const port=new URL(this.identity().endpoint).port,work=this.#work!;
    const config={log_level:'WARN',telemetry_disabled:true,storage:{storage_path:join(work,'storage'),snapshots_path:join(work,'snapshots'),
      performance:{max_search_threads:1,optimizer_cpu_budget:1},optimizers:{max_optimization_threads:1,prevent_unoptimized:false}},
      service:{host:'127.0.0.1',http_port:Number(port),grpc_port:null,max_workers:1,max_request_size_mb:1,api_key:key,
        enable_cors:false,enable_snapshot_url_recovery:false},cluster:{enabled:false}};
    const next=join(work,'config-'+randomBytes(8).toString('hex')+'.tmp');
    const file=await bounded(fs.open(next,constants.O_WRONLY|constants.O_CREAT|constants.O_EXCL|constants.O_NOFOLLOW,0o600),options);
    try{await bounded(file.writeFile(JSON.stringify(config)),options);await bounded(file.sync(),options);}
    finally{await file.close();}
    await bounded(fs.rename(next,join(work,'config.yaml')),options);
  }
  #alive():boolean{return !!this.#child&&typeof this.#child.pid==='number'&&this.#child.exitCode===null&&this.#child.signalCode===null;}
  async #start(options:Options):Promise<void>{
    await this.#verifyStorage(options);
    if(this.#alive())throw new ProviderUnavailable();
    const child=childProcess.spawn(this.#binary,['--config-path',join(this.#work!,'config.yaml')],
      {cwd:this.#work,env:CHILD_ENV,stdio:['ignore','ignore','ignore']});
    this.#child=child;
    this.#exit=new Promise<void>((resolve,reject)=>{
      child.once('exit',()=>{
        if(this.#child===child){this.#ordinaryOpen=false;if(this.#state==='open'||this.#state==='recovery_only')this.#state='failed';}
        resolve();
      });
      child.once('error',()=>reject(new ProviderUnavailable()));
    });
    void this.#exit.catch(()=>undefined);
    for(;;){
      if(!this.#alive())throw new ProviderUnavailable();
      try{
        await this.#listener(options);
        const root=response(await this.#request(this.#key,'GET','/',undefined,options));
        const cluster=result(await this.#request(this.#key,'GET','/cluster',undefined,options));
        if(root.version!=='1.20.0'||cluster.status!=='disabled')throw new UnsupportedCapability();
        return;
      }catch(error){
        if(error instanceof UnsupportedCapability||now()>=options.deadline||options.signal?.aborted)throw error;
        await bounded(new Promise<void>(resolve=>setTimeout(resolve,25)),options);
      }
    }
  }
  async #listener(options:Options):Promise<void>{
    if(!this.#alive()||!this.#child?.pid)throw new ProviderUnavailable();
    const pid=this.#child.pid;
    let process:ChildProcess|undefined;
    const output=new Promise<string>((resolve,reject)=>{
      process=childProcess.execFile('/usr/sbin/lsof',['-nP','-a','-p',String(pid),'-iTCP','-sTCP:LISTEN','-Fpn'],
        {encoding:'utf8',env:CHILD_ENV,maxBuffer:4096,timeout:Math.max(1,Math.min(2000,(options.deadline-now())*1000))},
        (error,stdout)=>error?reject(new ProviderUnavailable()):resolve(stdout));
    });
    let value:string;
    try{value=await bounded(output,options);}
    finally{if(process&&process.exitCode===null&&process.signalCode===null)process.kill('SIGKILL');}
    const rows=value.trim().split('\n');
    if(rows.filter(row=>row.startsWith('p')).join('')!=='p'+pid
      ||rows.filter(row=>row.startsWith('n')).join('')!=='n127.0.0.1:'+new URL(this.identity().endpoint).port
      ||!this.#alive())throw new UnsupportedCapability();
  }
  async #stop(options:Options):Promise<void>{
    const child=this.#child,exit=this.#exit;
    if(!child||!exit||typeof child.pid!=='number')return;
    if(this.#alive())child.kill('SIGTERM');
    try{await bounded(exit,{deadline:Math.min(options.deadline,now()+2),signal:options.signal});}
    catch(error){
      if(this.#alive())child.kill('SIGKILL');
      await bounded(exit,{deadline:Math.min(options.deadline,now()+2),signal:options.signal});
    }
    if(this.#alive())throw new ProviderUnavailable();
  }
  #allowed(method:string,path:string,admin=false):boolean{
    if(['GET'].includes(method)&&['/','/cluster','/collections'].includes(path))return true;
    const match=/^\/collections\/([A-Za-z][A-Za-z0-9_-]{0,63})(\/points(?:\/(?:scroll|delete))?)?(\?wait=true(?:&ordering=strong)?)?$/.exec(path);
    if(!match)return false;
    const owned=(admin&&match[1]===this.#identity?.probe_spec.collection)||this.#profiles.has(match[1]);
    if(!owned)return false;
    if(method==='GET')return !match[2]&&!match[3];
    const waiting=match[3]==='?wait=true'||match[3]==='?wait=true&ordering=strong';
    if(method==='PUT')return admin?!match[2]||match[2]==='/points':match[2]==='/points'&&waiting;
    if(method==='POST')return !!match[2]&&(match[2]==='/points'||match[2]==='/points/scroll'||(match[2]==='/points/delete'&&waiting));
    return false;
  }
  async #rawRequest(key:string,method:string,path:string,body:Buffer|undefined,options:Options):Promise<{status:number;bytes:readonly number[]}>{
    startup_profile();
    if(!this.#identity||!this.#alive())throw new ProviderUnavailable();
    const endpoint=new URL(this.#identity.endpoint);
    const maximum=options.max_response_bytes??RESPONSE_LIMIT;
    let request:http.ClientRequest|undefined;
    const work=new Promise<{status:number;bytes:readonly number[]}>((resolve,reject)=>{
      request=http.request({hostname:'127.0.0.1',port:Number(endpoint.port),method,path,agent:false,maxHeaderSize:16384,
        headers:{accept:'application/json','accept-encoding':'identity','api-key':key,...(body?{'content-type':'application/json','content-length':body.length}:{})}},incoming=>{
        const chunks:Buffer[]=[];let size=0;
        const encoding=incoming.headers['content-encoding'];
        if(encoding!==undefined&&encoding!=='identity'){incoming.destroy();reject(new ProviderUnavailable());return;}
        incoming.on('error',()=>reject(new ProviderUnavailable()));
        incoming.once('aborted',()=>reject(new ProviderUnavailable()));
        incoming.on('data',(chunk:Buffer)=>{
          if(!Buffer.isBuffer(chunk)||chunk.length>maximum-size){incoming.destroy();reject(new ProviderUnavailable());return;}
          size+=chunk.length;chunks.push(Buffer.from(chunk));
        });
        incoming.once('end',()=>resolve({status:incoming.statusCode??0,bytes:Object.freeze(Array.from(Buffer.concat(chunks)))}));
      });
      request.once('error',()=>reject(new ProviderUnavailable()));
      if(body)request.write(body);request.end();
    });
    try{return await bounded(work,options);}
    finally{request?.destroy();}
  }
  async #request(key:string,method:string,path:string,body:Buffer|undefined,options:Options):Promise<readonly number[]>{
    const result=await this.#rawRequest(key,method,path,body,options);
    if(result.status===401||result.status===403)throw new UnauthorizedScope();
    if(result.status<200||result.status>=300)throw new ProviderUnavailable();
    return result.bytes;
  }
  #transport(key:string,admin=false):ManagedHandle {
    if(this.#handles.size>=256)throw new ProviderUnavailable();
    let closed=false,active:Readonly<{controller:AbortController;done:Promise<void>}>|undefined;
    const handle:ManagedHandle={
      request:async(method,path,rawOptions)=>{
        this.#controlAccess();
        if(closed)throw new InvalidRequest();
        if(active)throw new ProviderUnavailable();
        const value=fields(rawOptions,['deadline'],['body','signal','max_response_bytes']);
        const options=lease_options({deadline:value.deadline,...(value.signal===undefined?{}:{signal:value.signal})});
        const maximum=value.max_response_bytes===undefined?RESPONSE_LIMIT:count(value.max_response_bytes,1,RESPONSE_LIMIT);
        if(typeof method!=='string'||typeof path!=='string'||!this.#allowed(method,path,admin))throw new InvalidRequest();
        const body=byte_body(value.body);
        if((method==='GET'&&body!==undefined)||(method!=='GET'&&body===undefined))throw new InvalidRequest();
        const controller=new AbortController(),relay=()=>controller.abort();
        options.signal?.addEventListener('abort',relay,{once:true});
        if(options.signal?.aborted)controller.abort();
        let finish!:()=>void;
        const done=new Promise<void>(resolve=>{finish=resolve;});active={controller,done};
        try{return await this.#request(key,method,path,body,{deadline:options.deadline,signal:controller.signal,max_response_bytes:maximum});}
        catch(error){throw safe(error);}
        finally{options.signal?.removeEventListener('abort',relay);active=undefined;finish();}
      },
      close:async()=>{
        closed=true;const pending=active;pending?.controller.abort();
        if(pending)await bounded(pending.done,{deadline:now()+2});
        this.#handles.delete(handle);
      },
      inflight:()=>active!==undefined,
    };
    Object.freeze(handle);this.#handles.add(handle);return handle;
  }
  async #verifyProbe(options:Options):Promise<void>{
    const probe=this.identity().probe_spec;
    const body=Buffer.from(JSON.stringify({ids:[probe.point.id],with_payload:true,with_vector:true}));
    const parsed=response(await this.#request(this.#key,'POST','/collections/'+probe.collection+'/points',body,options));
    if(parsed.status!=='ok'||!Array.isArray(parsed.result)||parsed.result.length!==1)throw new UnsupportedCapability();
    const point=parsed.result[0];
    if(typeof point!=='object'||point===null||point.id!==probe.point.id
      ||!same(point.payload,probe.point.payload)||!same(point.vector,probe.point.vector))throw new UnsupportedCapability();
  }
  async #verifyCollections(options:Options):Promise<void>{
    await this.#verifyStorage(options);await this.#listener(options);
    const listing=result(await this.#request(this.#key,'GET','/collections',undefined,options));
    if(!Array.isArray(listing.collections)||listing.collections.length!==this.#profiles.size+1)throw new UnsupportedCapability();
    const probe=this.identity().probe_spec;
    const names=listing.collections.map((item:unknown)=>{
      if(typeof item!=='object'||item===null||!('name'in item)||typeof item.name!=='string')throw new UnsupportedCapability();
      return item.name;
    });
    if(new Set(names).size!==names.length||!names.includes(probe.collection)
      ||[...this.#profiles.keys()].some(name=>!names.includes(name)))throw new UnsupportedCapability();
    for(const name of names){
      const collection=result(await this.#request(this.#key,'GET','/collections/'+name,undefined,options));
      const config=collection.config as Record<string,unknown>|undefined;
      const params=config?.params as Record<string,unknown>|undefined;
      const optimizers=config?.optimizer_config as Record<string,unknown>|undefined;
      if(collection.status!=='green'||collection.optimizer_status!=='ok'||optimizers?.prevent_unoptimized!==false
        ||params?.replication_factor!==1||params.write_consistency_factor!==1)throw new UnsupportedCapability();
      const vectors=params.vectors as Record<string,Record<string,unknown>>|undefined;
      if(name===probe.collection){
        const sparse=params.sparse_vectors;
        if(!vectors||Object.keys(vectors).length!==1||vectors.control?.size!==1||vectors.control?.distance!=='Cosine'
          ||(vectors.control.multivector_config!==undefined&&vectors.control.multivector_config!==null)
          ||(sparse!==null&&sparse!==undefined&&(typeof sparse!=='object'||Object.keys(sparse).length!==0)))throw new UnsupportedCapability();
      }else{
        const profile=this.#profiles.get(name)!;
        if(!vectors||Object.keys(vectors).length!==1||vectors.dense?.size!==1536||vectors.dense?.distance!=='Cosine'
          ||(vectors.dense.multivector_config!==undefined&&vectors.dense.multivector_config!==null))throw new UnsupportedCapability();
        const sparse=params.sparse_vectors as Record<string,Record<string,unknown>>|null|undefined;
        if(profile.sparse_profile===null){
          if(sparse!==null&&sparse!==undefined&&Object.keys(sparse).length!==0)throw new UnsupportedCapability();
        }else if(!sparse||Object.keys(sparse).length!==1||!sparse.sparse
          ||(sparse.sparse.modifier!==undefined&&sparse.sparse.modifier!==null))throw new UnsupportedCapability();
      }
    }
    await this.#verifyProbe(options);
  }
  async initialize(rawOptions:unknown):Promise<void>{
    this.#controlAccess();
    if(this.#state!=='new')throw new InvalidRequest();
    const value=fields(rawOptions,['deadline'],['signal','provision']);
    if(value.provision!==undefined&&typeof value.provision!=='function')throw new InvalidRequest();
    const options=lease_options({deadline:value.deadline,...(value.signal===undefined?{}:{signal:value.signal})});
    const provision=value.provision as ((transport:SupervisorTransport,probe:ProbeSpec)=>unknown)|undefined;
    this.#state='initializing';
    try{await this.#run(options,async lease=>{
      startup_profile();await this.#ownedDirectories(lease);
      this.#key=randomBytes(32).toString('hex');this.#credentialGeneration=randomUUID();
      await this.#writeConfig(this.#key,lease);await this.#start(lease);
      if(provision){
        const admin=this.#transport(this.#key,true);
        try{await bounded(Promise.resolve().then(()=>provision(admin,this.identity().probe_spec)),lease);}
        finally{await admin.close();}
      }
      await this.#verifyCollections(lease);
      lease_options(lease);this.#state='open';this.#ordinaryOpen=true;
    });}catch(error){
      const primary=safe(error);
      // An unsuccessful explicit start never leaves a live owned server for
      // the caller to discover later. Persistent ownership data is retained.
      try{await this.close();}catch{throw new ProviderUnavailable();}
      throw primary;
    }
  }
  issue_attempt(input:unknown,rawOptions:unknown):Attempt {
    this.#controlAccess();
    lease_options(rawOptions);const bound=binding(input);
    if(this.#state!=='open'||!this.#ordinaryOpen||!this.#alive())throw new ProviderUnavailable();
    if(bound.epoch!==this.#epoch)throw new InvalidRequest();
    const capability=Object.freeze({});
    this.#attempts.set(capability,Object.freeze({binding:bound,key:this.#key,credential_generation:this.#credentialGeneration,recovery:false}));
    return capability;
  }
  #attempt(input:unknown):AttemptData {
    if(typeof input!=='object'||input===null||!this.#attempts.has(input))throw new InvalidRequest();
    const data=this.#attempts.get(input)!;
    if(data.recovery){
      this.#proof(data.proof);
      if(data.binding.epoch!==this.#epoch||data.credential_generation!==this.#credentialGeneration)throw new UnsupportedCapability();
    }else if(this.#state!=='open'||!this.#ordinaryOpen||!this.#alive()
      ||data.binding.epoch!==this.#epoch||data.credential_generation!==this.#credentialGeneration)throw new ProviderUnavailable();
    return data;
  }
  attempt_binding(input:unknown):Readonly<Record<string,unknown>> {
    const data=this.#attempt(input),identity=this.identity();
    return Object.freeze({instance_id:identity.instance_id,storage_identity:identity.storage_identity,supervisor_id:identity.supervisor_id,
      credential_generation:data.credential_generation,...data.binding});
  }
  transport_for(input:unknown):SupervisorTransport {
    this.#controlAccess();
    const attempt=this.#attempt(input);
    return this.#transport(attempt.key);
  }
  async deliver_worker_credential(input:unknown,sink:unknown,rawOptions:unknown):Promise<void>{
    this.#controlAccess();
    const options=lease_options(rawOptions);
    if(typeof input==='object'&&input!==null&&this.#attempts.get(input)?.recovery)throw new UnsupportedCapability();
    const data=this.#attempt(input);
    if(typeof sink!=='function')throw new InvalidRequest();
    return this.#run(options,async lease=>{
      this.#attempt(input);
      // Deliberate trusted private IPC disclosure, never ordinary serialization
      // of the capability. There is no refresh path for a retained old secret.
      const credential=Object.freeze({endpoint:this.identity().endpoint,api_key:data.key,epoch:data.binding.epoch,instance_id:this.#instance});
      await bounded(Promise.resolve().then(()=>sink(credential)),lease);
    });
  }
  #proof(input:unknown):ProofData {
    if(typeof input!=='object'||input===null||!this.#proofs.has(input)||input!==this.#currentProof
      ||this.#state!=='recovery_only'||!this.#alive())throw new UnsupportedCapability();
    const proof=this.#proofs.get(input)!;
    if(proof.new_epoch!==this.#epoch||proof.credential_generation!==this.#credentialGeneration)throw new UnsupportedCapability();
    if([...this.#handles].some(handle=>handle.inflight()))throw new ProviderUnavailable();
    return proof;
  }
  recovery_binding(input:unknown):Readonly<Record<string,unknown>> {
    const proof=this.#proof(input),identity=this.identity();
    return Object.freeze({instance_id:identity.instance_id,storage_identity:identity.storage_identity,supervisor_id:identity.supervisor_id,...proof});
  }
  barrier_binding(input:unknown):Readonly<Record<string,unknown>> {
    if(typeof input!=='object'||input===null||input!==this.#currentBarrier||this.#state!=='recovery_sealed'){
      throw new UnsupportedCapability();
    }
    const barrier=this.#barriers.get(input);
    if(!barrier||barrier.proof!==this.#currentProof||!this.#alive()||this.#active
      ||barrier.binding.new_epoch!==this.#epoch||barrier.binding.credential_generation!==this.#credentialGeneration
      ||[...this.#handles].some(handle=>handle.inflight())){
      throw new ProviderUnavailable();
    }
    return barrier.binding;
  }
  async seal_recovery(proof:unknown,rawOptions:unknown,_control?:object):Promise<RecoveryBarrier> {
    this.#controlAccess(_control);
    const options=lease_options(rawOptions);
    if(this.#currentBarrier&&this.#barriers.get(this.#currentBarrier)?.proof===proof){
      this.barrier_binding(this.#currentBarrier);
      return this.#currentBarrier;
    }
    const physical=this.recovery_binding(proof);
    this.#ordinaryOpen=false;
    this.#state='recovery_sealed';
    return this.#run(options,async lease=>{
      for(const handle of [...this.#handles]){
        await bounded(handle.close(),lease);
      }
      lease_options(lease);
      if(!this.#alive())throw new ProviderUnavailable();
      const barrier=Object.freeze({});
      this.#barriers.set(barrier,Object.freeze({proof:proof as PhysicalRecovery,binding:physical}));
      this.#currentBarrier=barrier;
      return barrier;
    });
  }
  finish_recovery(barrier:unknown,settlement:unknown,rawOptions:unknown,_control?:object):void {
    this.#controlAccess(_control);
    lease_options(rawOptions);
    const physical=this.barrier_binding(barrier);
    const committed=settlement_data(settlement,this,barrier);
    if(!same(physical,committed))throw new IntegrityViolation();
    lease_options(rawOptions);
    if(this.#currentBarrier)this.#barriers.delete(this.#currentBarrier);
    this.#currentBarrier=undefined;
    this.#currentProof=undefined;
    this.#recovery=undefined;
    this.#recoveryOldKey=undefined;
    this.#state='open';
    this.#ordinaryOpen=true;
  }
  issue_recovery_attempt(proof:unknown,input:unknown,rawOptions:unknown):Attempt {
    this.#controlAccess();
    lease_options(rawOptions);const physical=this.#proof(proof),bound=binding(input,true);
    if(bound.epoch!==physical.new_epoch||bound.recovery_id!==physical.recovery_id)throw new InvalidRequest();
    const capability=Object.freeze({});
    this.#attempts.set(capability,Object.freeze({binding:bound,key:this.#key,credential_generation:this.#credentialGeneration,
      recovery:true,proof:proof as PhysicalRecovery}));
    return capability;
  }
  async recover(input:unknown,rawOptions:unknown,_control?:object):Promise<PhysicalRecovery>{
    this.#controlAccess(_control);
    const options=lease_options(rawOptions),value=fields(input,['recovery_id','old_epoch','new_epoch']);
    const recovery_id=text(value.recovery_id),old_epoch=count(value.old_epoch,1),new_epoch=count(value.new_epoch,1);
    if(new_epoch!==old_epoch+1||!this.#identity||this.#state==='new'||this.#state==='closed')throw new InvalidRequest();
    if(this.#recovery&&(this.#recovery.recovery_id!==recovery_id||this.#recovery.old_epoch!==old_epoch||this.#recovery.new_epoch!==new_epoch))throw new InvalidRequest();
    if(!this.#recovery&&old_epoch!==this.#epoch)throw new InvalidRequest();
    this.#ordinaryOpen=false;
    return this.#run(options,async lease=>{
      this.#state='recovering';
      this.#currentProof=undefined;
      this.#currentBarrier=undefined;
      const retiredKey=this.#key;
      if(!this.#recoveryOldKey)this.#recoveryOldKey=this.#key;
      const generation=randomUUID();
      this.#recovery=Object.freeze({recovery_id,old_epoch,new_epoch,credential_generation:generation});
      await Promise.all([...this.#handles].map(handle=>bounded(handle.close(),lease)));
      await this.#stop(lease);await this.#verifyStorage(lease);
      this.#key=randomBytes(32).toString('hex');this.#credentialGeneration=generation;
      await this.#writeConfig(this.#key,lease);await this.#start(lease);
      // Verify ownership before ANY probe mutation, including old-key requests.
      await this.#verifyCollections(lease);
      const probe=this.identity().probe_spec;
      const body=Buffer.from(JSON.stringify({points:[probe.point]}));
      for(const key of new Set([retiredKey,this.#recoveryOldKey])){
        const old=await this.#rawRequest(key,'PUT','/collections/'+probe.collection+'/points?wait=true',body,lease);
        if(old.status!==401)throw new UnsupportedCapability();
      }
      const current=result(await this.#request(this.#key,'PUT','/collections/'+probe.collection+'/points?wait=true',body,lease));
      if(current.status!=='completed')throw new ProviderUnavailable();
      await this.#verifyProbe(lease);lease_options(lease);
      this.#epoch=new_epoch;this.#state='recovery_only';
      const proof=Object.freeze({});this.#currentProof=proof;this.#proofs.set(proof,this.#recovery);
      return proof;
    });
  }
  async close():Promise<void>{
    this.#controlAccess();
    if(!this.#closing){
      this.#ordinaryOpen=false;this.#state='closed';this.#active?.controller.abort();
      this.#closing=(async()=>{
        const cleanup={deadline:now()+5};
        try{
          if(this.#active)await bounded(this.#active.done,cleanup);
          await bounded(Promise.all([...this.#handles].map(handle=>handle.close())),cleanup);
          await this.#stop(cleanup);
        }catch{throw new ProviderUnavailable();}
      })();
    }
    return this.#closing;
  }
}
