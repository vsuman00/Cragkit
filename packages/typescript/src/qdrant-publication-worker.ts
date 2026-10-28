/** Optional fixed native publication workers. Private IPC never carries SQL or source bodies. */
import {spawn,execFile,type ChildProcess} from 'node:child_process';
import {createHash} from 'node:crypto';
import {Socket} from 'node:net';
import * as http from 'node:http';
import {fileURLToPath} from 'node:url';
import {types} from 'node:util';
import {AsyncLocalStorage} from 'node:async_hooks';
import {ManagedQdrantSupervisor,type SupervisorTransport} from './qdrant-supervisor.js';
import {PoolResource,parse_pool_config,bounded,now,check_options,type LeaseOptions} from './postgres-pool.js';
import {ExecutionLedger,BudgetExhausted,type Reservation} from './execution.js';
import {parse_scope,LimitsSchema,type TrustedScope} from './requests.js';
import {parse_config,same,type QdrantConfig} from './qdrant-contract.js';
import {fields,metadata,text,count,uuid,type Data} from './qdrant-writer-contract.js';
import {InvalidRequest,ProviderUnavailable,UnsupportedCapability,UnauthorizedScope,IntegrityViolation,DeadlineExceeded,IndexNotReady} from './errors.js';

const VERSION=1,FRAME_MAX=65536,BOOT_MAX=262144,TOTAL_MAX=1048576;
const ERROR_TYPES={BudgetExhausted,InvalidRequest,ProviderUnavailable,UnsupportedCapability,UnauthorizedScope,IntegrityViolation,DeadlineExceeded,IndexNotReady};
function safe(error:unknown):Error {
  if(error instanceof DOMException&&error.name==='AbortError')return new DOMException('Operation aborted.','AbortError');
  for(const Kind of Object.values(ERROR_TYPES))if(error instanceof Kind)return new Kind();
  return new ProviderUnavailable();
}
function code(error:unknown):string{return safe(error).name;}
function fromCode(value:unknown):Error{
  if(value==='AbortError')return new DOMException('Operation aborted.','AbortError');
  if(typeof value!=='string'||!Object.hasOwn(ERROR_TYPES,value))throw new InvalidRequest();
  return new ERROR_TYPES[value as keyof typeof ERROR_TYPES]();
}
function exact(value:unknown,prototype:object):boolean{return typeof value==='object'&&value!==null&&!types.isProxy(value)&&Object.getPrototypeOf(value)===prototype;}
function need(value:unknown):asserts value{if(!value)throw new InvalidRequest();}
function canonical(value:unknown):string{
  if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
  if(value&&typeof value==='object')return '{'+Object.keys(value).sort().map(key=>JSON.stringify(key)+':'+canonical((value as Data)[key])).join(',')+'}';
  const result=JSON.stringify(value);if(result===undefined)throw new InvalidRequest();return result;
}
const sha=(value:Uint8Array|string)=>createHash('sha256').update(value).digest('hex');
const identityKeys=['instance_id','backend_namespace','storage_identity','supervisor_id','epoch','credential_generation','recovery','sealed','alive'];
function identity(value:unknown):Readonly<Data>{
  const data=fields(value,identityKeys);
  for(const key of identityKeys.slice(0,4).concat('credential_generation'))text(data[key]);
  count(data.epoch,1);need(data.recovery===null&&data.sealed===false&&data.alive===true);
  return Object.freeze({...data});
}
function binding(value:unknown):Readonly<Data>{
  if(typeof value==='object'&&value!==null&&!types.isProxy(value)&&Object.hasOwn(value,'recovery_id'))throw new UnsupportedCapability();
  const data=fields(value,['instance_id','storage_identity','supervisor_id','epoch','credential_generation','intent_id','owner_token','dispatch_id']);
  for(const key of ['instance_id','storage_identity','supervisor_id','credential_generation','intent_id','dispatch_id'])text(data[key]);
  uuid(data.owner_token);count(data.epoch,1);return Object.freeze({...data});
}
function reference(value:unknown):Readonly<Data>{const data=fields(value,['collection','document_id','intent_id']);return Object.freeze({collection:text(data.collection,true),document_id:text(data.document_id),intent_id:text(data.intent_id)});}
function snapshotJob(input:unknown):unknown{
  let nodes=0,bytes=0;const ancestors=new Set<object>();
  function add(size:number){bytes+=size;need(bytes<=BOOT_MAX-4096);}
  function visit(value:unknown,depth:number):unknown{
    need(++nodes<=4096&&depth<=32);
    if(typeof value==='string'){need(Buffer.byteLength(value)<=4096&&!/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(value));add(Buffer.byteLength(JSON.stringify(value)));return value;}
    if(value===null||typeof value==='boolean'){add(5);return value;}
    if(typeof value==='number'){need(Number.isFinite(value)&&Math.abs(value)<=Number.MAX_SAFE_INTEGER);add(32);return value;}
    need(typeof value==='object'&&value!==null&&!types.isProxy(value)&&!ancestors.has(value));ancestors.add(value);
    try{
      const array=Array.isArray(value);need(Object.getPrototypeOf(value)===(array?Array.prototype:Object.prototype));
      const keys=Reflect.ownKeys(value);need(keys.length<=4097);add(2+keys.length);
      const result:Data|unknown[]=array?[]:{};
      if(array)need((value as unknown[]).length<=4096&&Object.keys(value).length===(value as unknown[]).length);
      for(const key of keys){if(array&&key==='length')continue;need(typeof key==='string');const descriptor=Object.getOwnPropertyDescriptor(value,key);need(descriptor&&'value'in descriptor&&descriptor.enumerable);if(!array)add(Buffer.byteLength(JSON.stringify(key))+1);Object.defineProperty(result,key,{value:visit(descriptor.value,depth+1),enumerable:true,configurable:true,writable:true});}
      return result;
    }finally{ancestors.delete(value);}
  }
  return visit(input,0);
}
export function publication_worker_job(value:unknown):Readonly<Data>{
  const data=fields(snapshotJob(value),['writer_pool','config','scope','reference','limits']);
  const pool=parse_pool_config(data.writer_pool);
  need(Buffer.byteLength(pool.passfile)<=4096&&Buffer.byteLength(pool.sslrootcert)<=4096);
  let limits;try{limits=Object.freeze(LimitsSchema.parse(data.limits));}catch{throw new InvalidRequest();}
  const job=Object.freeze({writer_pool:pool,config:parse_config(data.config),scope:parse_scope(data.scope),reference:reference(data.reference),limits});
  need(Buffer.byteLength(canonical(job),'utf8')<=BOOT_MAX-4096);return job;
}

/** Strict JSON parser: JSON.parse alone silently accepts duplicate object keys. */
export function strict_worker_json(raw:Uint8Array):unknown{
  const source=new TextDecoder('utf-8',{fatal:true}).decode(raw);let at=0,nodes=0;
  const space=()=>{while(/[\x20\x09\x0a\x0d]/.test(source[at]??'!'))at++;};
  function value(depth:number):unknown{
    need(depth<=32&&++nodes<=100000);space();const first=source[at];
    if(first==='"'){
      const begin=at++;for(;;){need(at<source.length);const c=source[at++];if(c==='"')break;if(c==='\\'){need(at<source.length);at++;}else need(c.charCodeAt(0)>=32);}
      return JSON.parse(source.slice(begin,at));
    }
    if(first==='{'){
      at++;space();const result:Data={},keys=new Set<string>();if(source[at]==='}'){at++;return result;}
      for(;;){space();need(source[at]==='"');const key=value(depth+1);need(typeof key==='string'&&!keys.has(key));keys.add(key);space();need(source[at++]===':');Object.defineProperty(result,key,{value:value(depth+1),enumerable:true});space();const end=source[at++];if(end==='}')return result;need(end===',');}
    }
    if(first==='['){at++;space();const result:unknown[]=[];if(source[at]===']'){at++;return result;}for(;;){result.push(value(depth+1));space();const end=source[at++];if(end===']')return result;need(end===',');}}
    for(const [literal,result] of [['true',true],['false',false],['null',null]] as const){if(source.slice(at,at+literal.length)===literal){at+=literal.length;return result;}}
    const number=/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?/.exec(source.slice(at));need(number);at+=number[0].length;const result=Number(number[0]);need(Number.isFinite(result));return result;
  }
  const result=value(0);space();need(at===source.length);return result;
}
export function encode_worker_frame(value:unknown):Buffer{
  const raw=Buffer.from(canonical(value),'utf8');need(raw.length>=1&&raw.length<=FRAME_MAX);const frame=Buffer.allocUnsafe(raw.length+4);frame.writeUInt32BE(raw.length);raw.copy(frame,4);return frame;
}
export class PublicationWorkerFrameDecoder{
  #header=Buffer.alloc(4);#headerBytes=0;#body:Buffer|undefined;#offset=0;#total=0;#failed=false;
  push(chunk:Uint8Array):unknown[]{
    if(this.#failed)throw new InvalidRequest();
    try{
      need(chunk instanceof Uint8Array&&chunk.length<=TOTAL_MAX-this.#total);this.#total+=chunk.length;
      let at=0;const frames:unknown[]=[];
      while(at<chunk.length){
        if(!this.#body){
          const take=Math.min(4-this.#headerBytes,chunk.length-at);this.#header.set(chunk.subarray(at,at+take),this.#headerBytes);this.#headerBytes+=take;at+=take;
          if(this.#headerBytes<4)continue;
          const size=this.#header.readUInt32BE();need(size>=1&&size<=FRAME_MAX);
          this.#body=Buffer.alloc(size);this.#offset=0;
        }
        const take=Math.min(this.#body.length-this.#offset,chunk.length-at);this.#body.set(chunk.subarray(at,at+take),this.#offset);this.#offset+=take;at+=take;
        if(this.#offset===this.#body.length){frames.push(strict_worker_json(this.#body));this.#body=undefined;this.#headerBytes=0;this.#offset=0;}
      }
      return frames;
    }catch{this.#failed=true;throw new InvalidRequest();}
  }
  end():void{need(!this.#failed&&this.#headerBytes===0&&!this.#body);}
}

class Channel{
  readonly socket:Socket;#decoder=new PublicationWorkerFrameDecoder();#queue:unknown[]=[];#failure?:Error;
  #waiting?:{resolve:(value:unknown)=>void;reject:(error:Error)=>void};#sent=0;#closed=false;#queueLimit=8;#handling=false;
  constructor(socket:Socket){
    this.socket=socket;
    socket.on('data',(chunk:Buffer)=>{try{const frames=this.#decoder.push(chunk);for(const frame of frames){need(!this.#handling);if(this.#waiting){const wait=this.#waiting;this.#waiting=undefined;wait.resolve(frame);}else{need(this.#queue.length<this.#queueLimit);this.#queue.push(frame);}}}catch{this.fail(new InvalidRequest());}});
    socket.on('error',()=>this.fail(new ProviderUnavailable()));
    socket.on('end',()=>{try{this.#decoder.end();}catch{this.fail(new InvalidRequest());}this.fail(new ProviderUnavailable());});
    socket.on('close',()=>this.fail(new ProviderUnavailable()));
  }
  ordinary():void{this.#queueLimit=1;need(this.#queue.length<=1);}
  handling(value:boolean):void{this.#handling=value;}
  fail(error:Error):void{this.#failure??=error;this.#waiting?.reject(this.#failure);this.#waiting=undefined;this.socket.destroy();}
  next(options:LeaseOptions):Promise<unknown>{
    check_options(options);if(this.#failure)return Promise.reject(this.#failure);if(this.#queue.length)return Promise.resolve(this.#queue.shift());need(!this.#waiting);
    const work=new Promise<unknown>((resolve,reject)=>{this.#waiting={resolve,reject};});return bounded(work,options,error=>this.fail(error));
  }
  async send(value:unknown,options:LeaseOptions):Promise<void>{
    check_options(options);if(this.#failure)throw this.#failure;const raw=encode_worker_frame(value);need(raw.length<=TOTAL_MAX-this.#sent);this.#sent+=raw.length;
    await bounded(new Promise<void>((resolve,reject)=>this.socket.write(raw,error=>error?reject(new ProviderUnavailable()):resolve())),options,error=>this.fail(error));
  }
  close():void{if(!this.#closed){this.#closed=true;this.fail(new ProviderUnavailable());}}
}
async function sendBoot(channel:Channel,payload:unknown,options:LeaseOptions):Promise<void>{
  const raw=Buffer.from(canonical(payload),'utf8');need(raw.length<=BOOT_MAX);
  await channel.send({v:VERSION,op:'boot_begin',total:raw.length,sha256:sha(raw)},options);
  for(let offset=0;offset<raw.length;offset+=48000)await channel.send({v:VERSION,op:'boot_chunk',offset,data:raw.subarray(offset,offset+48000).toString('base64')},options);
  await channel.send({v:VERSION,op:'boot_end'},options);
}
async function receiveBoot(channel:Channel,options:LeaseOptions):Promise<Data>{
  const first=fields(await channel.next(options),['v','op','total','sha256']);need(first.v===VERSION&&first.op==='boot_begin');const total=count(first.total,1,BOOT_MAX);need(typeof first.sha256==='string'&&/^[a-f0-9]{64}$/.test(first.sha256));
  const raw=Buffer.alloc(total);let offset=0,chunks=0;
  while(offset<total){const part=fields(await channel.next(options),['v','op','offset','data']);need(part.v===VERSION&&part.op==='boot_chunk'&&part.offset===offset&&++chunks<=6&&typeof part.data==='string');
    need(/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(part.data));const chunk=Buffer.from(part.data,'base64');need(chunk.length>0&&chunk.length<=48000&&chunk.length<=total-offset&&chunk.toString('base64')===part.data);chunk.copy(raw,offset);offset+=chunk.length;}
  const end=fields(await channel.next(options),['v','op']);need(end.v===VERSION&&end.op==='boot_end'&&sha(raw)===first.sha256);
  channel.ordinary();return fields(strict_worker_json(raw),['v','job','identity','remaining_ms']);
}

type Observer=(event:Readonly<Data>,worker:OwnedPublicationWorker)=>Promise<void>;
type WorkerState={child:ChildProcess;channel:Channel;exit:Promise<{code:number|null;signal:NodeJS.Signals|null}>;exited:boolean;paused:boolean;dead:boolean};
const ownedWorkers=new WeakMap<object,WorkerState>();const OWNED=Symbol('owned-publication-worker');
async function processState(state:WorkerState,options:LeaseOptions):Promise<string>{
  need(typeof state.child.pid==='number'&&!state.exited);
  return bounded(new Promise<string>((resolve,reject)=>execFile('/bin/ps',['-o','stat=','-p',String(state.child.pid)],{encoding:'utf8',maxBuffer:128,timeout:1000,env:{PATH:'/usr/bin:/bin'}},(error,out)=>error?reject(new ProviderUnavailable()):resolve(out.trim()))),options);
}
/** Diagnostic operations apply only to the exact child owned by this host. */
export class OwnedPublicationWorker{
  constructor(token:unknown,state:WorkerState){need(token===OWNED);ownedWorkers.set(this,state);Object.freeze(this);}
  #state():WorkerState{const state=ownedWorkers.get(this);if(!state||state.exited||state.dead)throw new InvalidRequest();return state;}
  async pause(options:LeaseOptions):Promise<void>{fields(options,['deadline'],['signal']);const state=this.#state();check_options(options);need(state.child.kill('SIGSTOP'));for(;;){if((await processState(state,options)).startsWith('T')){state.paused=true;return;}await bounded(new Promise<void>(resolve=>setTimeout(resolve,5)),options);}}
  async resume(options:LeaseOptions):Promise<void>{fields(options,['deadline'],['signal']);const state=this.#state();check_options(options);need(state.paused&&state.child.kill('SIGCONT'));for(;;){if(!(await processState(state,options)).startsWith('T')){state.paused=false;return;}await bounded(new Promise<void>(resolve=>setTimeout(resolve,5)),options);}}
  async terminate(options:LeaseOptions):Promise<void>{fields(options,['deadline'],['signal']);const state=this.#state();await terminate(state,options);}
  toJSON():never{throw new InvalidRequest();}
}
async function terminate(state:WorkerState,options:LeaseOptions):Promise<void>{
  if(!state.exited){if(!state.child.kill('SIGKILL')&&!state.exited)throw new ProviderUnavailable();await bounded(state.exit,options);}need(state.exited);state.dead=true;
}
type ParentAttempt={attempt:unknown;binding:Readonly<Data>};
type JobState={worker:WorkerState;done:Promise<void>;attempts:Map<number,ParentAttempt>;callback?:Promise<unknown>;release?:()=>void;session?:Promise<unknown>;poisoned:boolean};
// Strong ownership is deliberate: a failed reap must not release a live finalization lease via GC.
const poisonedJobs=new Set<JobState>();

export class ManagedQdrantPublicationWorkerHost{
  readonly #supervisor:ManagedQdrantSupervisor;readonly #authorize:(scope:TrustedScope,collection:string,document_id:string)=>Promise<boolean>;
  #active?:JobState;#closed=false;
  constructor(supervisor:ManagedQdrantSupervisor,authorize_write:(scope:TrustedScope,collection:string,document_id:string)=>Promise<boolean>){
    need(exact(supervisor,ManagedQdrantSupervisor.prototype)&&typeof authorize_write==='function'&&!types.isProxy(authorize_write));this.#supervisor=supervisor;this.#authorize=authorize_write;
  }
  async #cleanup(job:JobState):Promise<void>{
    const options={deadline:now()+5};
    try{
      await terminate(job.worker,options);
      if(job.callback)await bounded(job.callback.then(()=>undefined,()=>undefined),options);
      job.release?.();if(job.session)await bounded(job.session,options);
      job.worker.channel.close();job.attempts.clear();poisonedJobs.delete(job);job.poisoned=false;
    }catch{job.poisoned=true;poisonedJobs.add(job);throw new ProviderUnavailable();}
  }
  async publish(rawJob:unknown,ledger:ExecutionLedger,rawOptions:LeaseOptions&{observer?:Observer}):Promise<Readonly<Data>>{
    const optionsData=fields(rawOptions,['deadline'],['signal','observer']);
    const job=publication_worker_job(rawJob),config=job.config as QdrantConfig,scope=job.scope as TrustedScope,ref=job.reference as Data;
    need(exact(ledger,ExecutionLedger.prototype));const options={deadline:Math.min(Number(optionsData.deadline),ledger.deadline),signal:optionsData.signal as AbortSignal|undefined};check_options(options);
    const observer=optionsData.observer as Observer|undefined;need(observer===undefined||typeof observer==='function'&&!types.isProxy(observer));
    if(this.#closed||this.#active)throw new ProviderUnavailable();
    const pinned=identity(this.#supervisor.profile_binding(config));
    let reservation:Reservation|undefined=ledger.reserve({attempts:1});ledger.dispatch(reservation);
    let state:JobState|undefined,primary:unknown;
    try{
      const child=spawn(process.execPath,[fileURLToPath(import.meta.url),'--cragkit-publication-worker-r1'],{
        stdio:['ignore','pipe','pipe','pipe'],env:Object.fromEntries(['HOME','TMPDIR','LANG','LC_ALL','TZ'].filter(key=>process.env[key]!==undefined).map(key=>[key,process.env[key]!])),windowsHide:true});
      const socket=child.stdio[3] as Socket;need(socket&&typeof socket.write==='function');const channel=new Channel(socket);
      let finish!:()=>void;const done=new Promise<void>(resolve=>{finish=resolve;});
      const worker:WorkerState={child,channel,exit:Promise.resolve({code:null,signal:null}),exited:false,paused:false,dead:false};
      worker.exit=new Promise((resolve,reject)=>{child.once('error',()=>{worker.exited=true;channel.fail(new ProviderUnavailable());reject(new ProviderUnavailable());});child.once('exit',(exitCode,signal)=>{worker.exited=true;resolve({code:exitCode,signal});});});void worker.exit.catch(()=>{});
      state={worker,done,attempts:new Map(),poisoned:false};this.#active=state;
      let output=0;for(const stream of [child.stdout,child.stderr])stream?.on('data',(chunk:Buffer)=>{output+=chunk.length;if(output>65536)channel.fail(new ProviderUnavailable());});
      const owned=new OwnedPublicationWorker(OWNED,worker),scopeDigest=sha(canonical(scope)),configDigest=sha(canonical(config));
      let retired=false;
      const current=()=>{if(retired)throw new UnsupportedCapability();const fresh=identity(this.#supervisor.profile_binding(config));if(!same(fresh,pinned)){retired=true;throw new UnsupportedCapability();}return fresh;};
      await sendBoot(channel,{v:VERSION,job,identity:pinned,remaining_ms:Math.max(1,Math.floor((options.deadline-now())*1000))},options);
      channel.ordinary();
      let id=0,barriers=0,observed=0,finalized=false,result:Readonly<Data>|undefined,terminalError:Error|undefined;
      const seenWrites=new Set<number>();
      for(;;){
        const request=fields(await channel.next(options),['v','id','op','remaining_ms','data']);
        channel.handling(true);
        need(request.v===VERSION&&request.id===++id&&id<=128&&typeof request.op==='string');
        const remaining=count(request.remaining_ms,1,300000);const lease={...options,deadline:Math.min(options.deadline,now()+remaining/1000)};
        const op=request.op;let reply:unknown={};
        try{
          if(state.session)need(['authorize','validate','finalize_end'].includes(op));
          if(op==='authorize'){
            current();const data=fields(request.data,['reference','scope_sha256']);need(same(reference(data.reference),ref)&&data.scope_sha256===scopeDigest);
            const callback=Promise.resolve().then(()=>{const value=this.#authorize(scope,String(ref.collection),String(ref.document_id));need(value instanceof Promise&&!types.isProxy(value));return value;});state.callback=callback;
            const allowed=await bounded(callback,lease);state.callback=undefined;current();need(typeof allowed==='boolean');reply={allowed};
          }else if(op==='profile'){
            const data=fields(request.data,['config_sha256']);need(data.config_sha256===configDigest);reply=current();
          }else if(op==='issue'){
            current();const data=fields(request.data,['intent_id','owner_token','epoch','dispatch_id']);need(data.intent_id===ref.intent_id&&data.epoch===pinned.epoch&&state.attempts.size<8);uuid(data.owner_token);text(data.dispatch_id);
            const attempt=this.#supervisor.issue_attempt(data,lease),frozen=binding(this.#supervisor.attempt_binding(attempt));let credential:Data|undefined;
            await this.#supervisor.deliver_worker_credential(attempt,async (value:unknown)=>{need(!credential);credential=metadata(value);},lease);need(credential);
            const attempt_id=state.attempts.size+1;state.attempts.set(attempt_id,{attempt,binding:frozen});reply={attempt_id,binding:frozen,endpoint:credential.endpoint,api_key:credential.api_key};
          }else if(op==='validate'||op==='finalize_begin'){
            current();const data=fields(request.data,['attempt_id']),attempt=state.attempts.get(count(data.attempt_id,1,8));need(attempt);
            const validate=()=>{current();if(!same(binding(this.#supervisor.attempt_binding(attempt.attempt)),attempt.binding))throw new UnsupportedCapability();};
            if(op==='validate'){validate();reply={binding:attempt.binding};}
            else{
              need(!finalized&&!state.session);finalized=true;
              let arrived!:()=>void;const entered=new Promise<void>(resolve=>{arrived=resolve;});let release!:()=>void;const held=new Promise<void>(resolve=>{release=resolve;});state.release=release;
              state.session=this.#supervisor.control_session(async()=>{validate();arrived();await held;});void state.session.catch(()=>{});
              await bounded(Promise.race([entered,state.session.then(()=>{throw new ProviderUnavailable();})]),lease);
            }
          }else if(op==='finalize_end'){
            fields(request.data,[]);need(state.session&&state.release);if(state.callback)await bounded(state.callback,lease);
            state.release();await bounded(state.session,lease);state.release=undefined;state.session=undefined;
          }else if(op==='before_write'||op==='write_observed'){
            const data=fields(request.data,op==='before_write'?['attempt_id','dispatch_id','sequence','request_sha256']:['attempt_id','dispatch_id','status']);
            const attempt_id=count(data.attempt_id,1,8),attempt=state.attempts.get(attempt_id);need(attempt&&data.dispatch_id===attempt.binding.dispatch_id);
            if(op==='before_write'){current();if(!same(binding(this.#supervisor.attempt_binding(attempt.attempt)),attempt.binding))throw new UnsupportedCapability();need(++barriers<=8&&!seenWrites.has(attempt_id));count(data.sequence,1,256);need(typeof data.request_sha256==='string'&&/^[a-f0-9]{64}$/.test(data.request_sha256));seenWrites.add(attempt_id);}
            else{need(++observed<=8&&seenWrites.delete(attempt_id));count(data.status,100,599);}
            if(observer){const callback=Promise.resolve().then(()=>{const value=observer(Object.freeze({kind:op,...data}),owned);need(value instanceof Promise&&!types.isProxy(value));return value;});state.callback=callback;await bounded(callback,lease);state.callback=undefined;}
          }else if(op==='done'){
            const data=fields(request.data,['result','error','cleanup']);need(!state.session&&Array.isArray(data.cleanup)&&data.cleanup.length<=64&&data.cleanup.every(item=>typeof item==='string'&&(item==='AbortError'||Object.hasOwn(ERROR_TYPES,item))));
            need((data.result===null)!==(data.error===null));
            if(data.error!==null)terminalError=fromCode(data.error);else result=publicationResult(data.result,String(ref.intent_id));
            if(data.cleanup.length)terminalError=new ProviderUnavailable();
          }else throw new InvalidRequest();
          channel.handling(false);await channel.send({v:VERSION,id,ok:true,data:reply},lease);
        }catch(error){channel.handling(false);await channel.send({v:VERSION,id,ok:false,error:code(error)},lease);throw error;}
        if(op==='done'){
          const exit=await bounded(worker.exit,options);need(exit.code===0&&exit.signal===null);if(terminalError)throw terminalError;need(result);ledger.reconcile(reservation);reservation=undefined;return result;
        }
      }
    }catch(error){primary=error;throw safe(error);}
    finally{
      if(reservation)ledger.abandon(reservation);
      if(state){try{await this.#cleanup(state);}catch{this.#closed=true;throw new ProviderUnavailable();}finally{if(!state.poisoned){this.#active=undefined;}/* A poisoned job retains both the exact child and actual session. */}}
      void primary;
    }
  }
  async close():Promise<void>{this.#closed=true;const active=this.#active;if(active){await this.#cleanup(active);this.#active=undefined;}}
}
function publicationResult(value:unknown,intent:string):Readonly<Data>{
  const data=fields(value,['intent_id','operation','state','revision_id','generation_id','authority_committed','replica_complete','published','purge_complete']);
  need(data.intent_id===intent&&data.operation==='publish'&&['published','conflict','denied'].includes(String(data.state)));
  for(const key of ['revision_id','generation_id'])text(data[key]);
  need(data.published===(data.state==='published'));
  for(const key of ['authority_committed','replica_complete','published','purge_complete'])need(typeof data[key]==='boolean');return Object.freeze({...data});
}

type LocalAttempt={id:number;binding:Readonly<Data>;endpoint:string;key:string};
const controllers=new WeakMap<object,{channel:Channel;job:Readonly<Data>;identity:Readonly<Data>;deadline:number;next:number;busy:boolean;closed:boolean;attempts:Map<object,LocalAttempt>;handles:Set<SupervisorTransport>;issued:number;finalized:boolean}>();
const BOOTSTRAP=Symbol('fixed-native-bootstrap');
export class OrdinaryWorkerController{
  constructor(token:unknown,channel:Channel,job:Readonly<Data>,pinned:Readonly<Data>,deadline:number){need(token===BOOTSTRAP);controllers.set(this,{channel,job,identity:pinned,deadline,next:0,busy:false,closed:false,attempts:new Map(),handles:new Set(),issued:0,finalized:false});Object.freeze(this);}
  toJSON():never{throw new InvalidRequest();}
}
export type OrdinaryPublicationController=ManagedQdrantSupervisor|OrdinaryWorkerController;
export function is_worker_controller(value:unknown):value is OrdinaryWorkerController{return exact(value,OrdinaryWorkerController.prototype)&&controllers.has(value as object);}
export function is_publication_controller(value:unknown):value is OrdinaryPublicationController{return exact(value,ManagedQdrantSupervisor.prototype)||is_worker_controller(value);}
function local(controller:OrdinaryWorkerController){const state=controllers.get(controller);if(!state||state.closed)throw new InvalidRequest();return state;}
async function rpc(controller:OrdinaryWorkerController,op:string,data:unknown,options:LeaseOptions):Promise<Data>{
  const state=local(controller);check_options(options);need(!state.busy&&state.next<128);state.busy=true;
  const lease={...options,deadline:Math.min(state.deadline,options.deadline)};
  try{
    const id=++state.next;
    await state.channel.send({v:VERSION,id,op,remaining_ms:Math.max(1,Math.floor((lease.deadline-now())*1000)),data},lease);
    const response=metadata(await state.channel.next(lease));need(response.v===VERSION&&response.id===id&&typeof response.ok==='boolean');
    if(response.ok){fields(response,['v','id','ok','data']);return metadata(response.data);}
    fields(response,['v','id','ok','error']);throw fromCode(response.error);
  }catch(error){state.channel.close();state.closed=true;throw safe(error);}finally{state.busy=false;}
}
export function publication_worker_reference(controller:OrdinaryWorkerController):Readonly<Data>{
  const state=local(controller);return Object.freeze({reference:state.job.reference,scope:state.job.scope});
}
export async function publication_controller_profile(controller:OrdinaryPublicationController,config:QdrantConfig,options:LeaseOptions):Promise<Readonly<Data>>{
  need(is_publication_controller(controller));
  if(!is_worker_controller(controller))return metadata(controller.profile_binding(config));
  const state=local(controller);need(same(config,state.job.config));const result=identity(await rpc(controller,'profile',{config_sha256:sha(canonical(config))},options));need(same(result,state.identity));return result;
}
export async function publication_attempt_binding(controller:OrdinaryPublicationController,attempt:unknown,options:LeaseOptions):Promise<Readonly<Data>>{
  need(is_publication_controller(controller));
  if(!is_worker_controller(controller))return binding(controller.attempt_binding(attempt));
  const state=local(controller),issued=typeof attempt==='object'&&attempt!==null?state.attempts.get(attempt):undefined;need(issued);
  const result=fields(await rpc(controller,'validate',{attempt_id:issued.id},options),['binding']);const fresh=binding(result.binding);need(same(fresh,issued.binding));return fresh;
}
export async function publication_issue_attempt(controller:OrdinaryPublicationController,input:unknown,options:LeaseOptions):Promise<unknown>{
  need(is_publication_controller(controller));
  if(!is_worker_controller(controller))return controller.issue_attempt(input,options);
  const state=local(controller),data=fields(input,['intent_id','owner_token','epoch','dispatch_id']);need(state.issued<8);
  const response=fields(await rpc(controller,'issue',data,options),['attempt_id','binding','endpoint','api_key']);
  const frozen=binding(response.binding);need(response.attempt_id===state.issued+1&&['intent_id','owner_token','epoch','dispatch_id'].every(key=>data[key]===frozen[key]));
  need(['instance_id','storage_identity','supervisor_id','epoch','credential_generation'].every(key=>frozen[key]===state.identity[key]));
  need(typeof response.endpoint==='string'&&typeof response.api_key==='string'&&/^[a-f0-9]{64}$/.test(response.api_key));
  const endpoint=new URL(response.endpoint);need(endpoint.protocol==='http:'&&endpoint.hostname==='127.0.0.1'&&endpoint.port&&endpoint.origin===response.endpoint);
  const attempt=Object.freeze({});state.issued++;state.attempts.set(attempt,{id:state.issued,binding:frozen,endpoint:response.endpoint,key:response.api_key});return attempt;
}
/** Pure private worker HTTP admission shared with its focused boundary tests. */
export function publication_worker_http_request(config:QdrantConfig,method:string,path:string,rawOptions:unknown):Readonly<{maximum:number;body:Buffer|undefined}>{
  const opts=fields(rawOptions,['deadline'],['signal','body','max_response_bytes']);
  const base='/collections/'+parse_config(config).physical_collection;
  need(method==='GET'&&path===base||method==='POST'&&(path===base+'/points'||path===base+'/points/scroll')||method==='PUT'&&path===base+'/points?wait=true&ordering=strong');
  const maximum=opts.max_response_bytes===undefined?1048576:count(opts.max_response_bytes,1,1048576);
  let body:Buffer|undefined;
  if(opts.body!==undefined){
    need(Array.isArray(opts.body)&&!types.isProxy(opts.body)&&Object.getPrototypeOf(opts.body)===Array.prototype&&opts.body.length<=1048576);
    const data:number[]=[];
    for(let index=0;index<opts.body.length;index++){const item=Object.getOwnPropertyDescriptor(opts.body,String(index));need(item&&'value'in item);data.push(count(item.value,0,255));}
    body=Buffer.from(data);
  }
  need((method==='GET')===(body===undefined));return Object.freeze({maximum,body});
}
export function publication_worker_http_status(status:number):void{
  if(status===401||status===403)throw new UnauthorizedScope();
  if(status!==200)throw new ProviderUnavailable();
}
export function publication_transport_for(controller:OrdinaryPublicationController,attempt:unknown):SupervisorTransport{
  need(is_publication_controller(controller));
  if(!is_worker_controller(controller))return controller.transport_for(attempt);
  const state=local(controller),issued=typeof attempt==='object'&&attempt!==null?state.attempts.get(attempt):undefined;need(issued&&state.handles.size<16);
  const config=state.job.config as QdrantConfig;let closed=false,pending:Promise<unknown>|undefined,abort:AbortController|undefined;
  const handle:SupervisorTransport={
    async request(method,path,rawOptions){
      need(!closed&&!pending);const opts=fields(rawOptions,['deadline'],['signal','body','max_response_bytes']);
      const options={deadline:Math.min(Number(opts.deadline),state.deadline),signal:opts.signal as AbortSignal|undefined};check_options(options);
      const {maximum,body}=publication_worker_http_request(config,method,path,opts);
      // Current executable has no inherited options; raw native HTTP does not discover proxies.
      need(!process.env.NODE_OPTIONS&&!process.env.NODE_USE_ENV_PROXY&&process.env.NODE_TLS_REJECT_UNAUTHORIZED!=='0');
      abort=new AbortController();const relay=()=>abort?.abort();options.signal?.addEventListener('abort',relay,{once:true});
      let request:http.ClientRequest|undefined;
      const work=new Promise<{status:number;bytes:readonly number[]}>((resolve,reject)=>{
        const endpoint=new URL(issued.endpoint);
        request=http.request({hostname:'127.0.0.1',port:Number(endpoint.port),method,path,agent:false,maxHeaderSize:16384,
          headers:{accept:'application/json','accept-encoding':'identity','api-key':issued.key,...(body?{'content-type':'application/json','content-length':body.length}:{})}},incoming=>{
          const collect=()=>{
          const chunks:Buffer[]=[];let size=0;
          const encoding=incoming.headers['content-encoding'],length=incoming.headers['content-length'];
          if(encoding!==undefined&&encoding!=='identity'||length!==undefined&&(!/^\d+$/.test(length)||Number(length)>maximum)){incoming.destroy();reject(new ProviderUnavailable());return;}
          incoming.on('error',()=>reject(new ProviderUnavailable()));incoming.once('aborted',()=>reject(new ProviderUnavailable()));
          incoming.on('data',(chunk:Buffer)=>{if(!Buffer.isBuffer(chunk)||chunk.length>maximum-size){incoming.destroy();reject(new ProviderUnavailable());return;}size+=chunk.length;chunks.push(Buffer.from(chunk));});
          incoming.once('end',()=>resolve({status:incoming.statusCode??0,bytes:Object.freeze([...Buffer.concat(chunks)])}));
          };
          if(method==='PUT'){
            incoming.pause();
            void rpc(controller,'write_observed',{attempt_id:issued.id,dispatch_id:issued.binding.dispatch_id,status:incoming.statusCode??0},options).then(()=>{
              if(incoming.statusCode!==200){incoming.destroy();resolve({status:incoming.statusCode??0,bytes:Object.freeze([])});return;}
              collect();incoming.resume();
            },()=>{incoming.destroy();reject(new ProviderUnavailable());});
          }else collect();
        });request.once('error',()=>reject(new ProviderUnavailable()));if(body)request.write(body);request.end();
      });pending=work;
      const stop=()=>request?.destroy();abort.signal.addEventListener('abort',stop,{once:true});
      try{
        const response=await bounded(work,{deadline:options.deadline,signal:abort.signal},stop);
        publication_worker_http_status(response.status);return response.bytes;
      }catch(error){throw safe(error);}finally{request?.destroy();options.signal?.removeEventListener('abort',relay);abort=undefined;pending=undefined;}
    },
    async close(){closed=true;abort?.abort();if(pending)await bounded(pending.then(()=>undefined,()=>undefined),{deadline:now()+1});state.handles.delete(handle);},
  };
  state.handles.add(handle);return handle;
}
export async function publication_before_write(controller:OrdinaryPublicationController,attempt:unknown,dispatch:Readonly<{dispatch_id:string;sequence:number;request_bytes:readonly number[]}>,options:LeaseOptions):Promise<void>{
  need(is_publication_controller(controller));
  if(!is_worker_controller(controller))return;
  const issued=local(controller).attempts.get(attempt as object);need(issued);
  await rpc(controller,'before_write',{attempt_id:issued.id,dispatch_id:dispatch.dispatch_id,sequence:dispatch.sequence,request_sha256:sha(Buffer.from(dispatch.request_bytes))},options);
}
type FinalizationContext={controller:OrdinaryPublicationController;deadline:number;signal?:AbortSignal;active:boolean};
const finalizationContext=new AsyncLocalStorage<FinalizationContext>();

/** Only the native-session helper below issues this request-local authority. */
export function require_publication_finalization(controller:OrdinaryPublicationController,options:LeaseOptions):void{
  need(is_publication_controller(controller));
  const data=fields(options,['deadline'],['signal']);
  need(data.signal===undefined||typeof data.signal==='object'&&data.signal!==null&&!types.isProxy(data.signal));
  const lease={deadline:data.deadline as number,signal:data.signal as AbortSignal|undefined};
  check_options(lease);
  const context=finalizationContext.getStore();
  need(context?.active&&context.controller===controller&&lease.deadline<=context.deadline);
  need(context.signal===undefined||context.signal===lease.signal);
  check_options({deadline:context.deadline,signal:context.signal});
}

export async function publication_finalization<T>(controller:OrdinaryPublicationController,attempt:unknown,body:()=>Promise<T>,options:LeaseOptions):Promise<T>{
  need(is_publication_controller(controller)&&typeof body==='function'&&!types.isProxy(body));
  const data=fields(options,['deadline'],['signal']);
  const lease:LeaseOptions={deadline:data.deadline as number,signal:data.signal as AbortSignal|undefined};
  check_options(lease);need(!finalizationContext.getStore()?.active);
  const scoped=async()=>{
    const context:FinalizationContext={controller,...lease,active:true};
    return finalizationContext.run(context,async()=>{try{return await body();}finally{context.active=false;}});
  };
  if(!is_worker_controller(controller))return controller.control_session(scoped);
  const state=local(controller),issued=state.attempts.get(attempt as object);need(issued&&!state.finalized);state.finalized=true;
  await rpc(controller,'finalize_begin',{attempt_id:issued.id},options);
  try{return await scoped();}
  finally{await rpc(controller,'finalize_end',{}, {deadline:Math.min(state.deadline,now()+2)});}
}
async function worker_authorize(controller:OrdinaryWorkerController,scope:TrustedScope,collection:string,document_id:string):Promise<boolean>{
  const state=local(controller),ref=state.job.reference as Data;need(same(scope,state.job.scope)&&ref.collection===collection&&ref.document_id===document_id);
  const reply=fields(await rpc(controller,'authorize',{reference:ref,scope_sha256:sha(canonical(scope))},{deadline:state.deadline}),['allowed']);need(typeof reply.allowed==='boolean');return reply.allowed;
}
async function child_entry():Promise<void>{
  const channel=new Channel(new Socket({fd:3,readable:true,writable:true}));
  let controller:OrdinaryWorkerController|undefined,resource:PoolResource|undefined,manager:{close:()=>Promise<void>}|undefined,transport:{close:()=>Promise<void>}|undefined,writer:{close:()=>Promise<void>}|undefined;
  let result:unknown=null,error:unknown=null;const cleanup:string[]=[];
  let deadline=now()+5;
  try{
    const bootstrap=await receiveBoot(channel,{deadline});need(bootstrap.v===VERSION);const job=publication_worker_job(bootstrap.job),pinned=identity(bootstrap.identity);
    deadline=now()+count(bootstrap.remaining_ms,1,300000)/1000;controller=new OrdinaryWorkerController(BOOTSTRAP,channel,job,pinned,deadline);
    const module=await import('./qdrant-publication.js');resource=new PoolResource(job.writer_pool as ReturnType<typeof parse_pool_config>);
    const actualWriter=new module.PostgresQdrantWriter(resource,job.config,pinned.instance_id);writer=actualWriter;
    const authority=new module.PostgresQdrantPublicationAuthority(actualWriter,null);
    transport=new module.ManagedQdrantPublicationTransport(controller);
    const actualManager=new module.QdrantPublicationManager(authority,transport as InstanceType<typeof module.ManagedQdrantPublicationTransport>,job.config,controller,
      (scope,collection,document)=>worker_authorize(controller!,scope,collection,document));manager=actualManager;
    const options={deadline};await resource.open();await actualManager.initialize(options);
    const ledger=new ExecutionLedger({limits:job.limits,deadline});result=await actualManager.publish(job.reference,job.scope,ledger,options);
  }catch(caught){error=code(caught);}
  finally{
    const cleanupDeadline=now()+5;
    for(const owner of [manager,transport,writer,resource])if(owner){try{await bounded(owner.close(),{deadline:Math.min(cleanupDeadline,now()+2)});}catch(caught){cleanup.push(code(caught));}}
    if(controller){const state=controllers.get(controller)!;for(const handle of [...state.handles])try{await bounded(handle.close(),{deadline:Math.min(cleanupDeadline,now()+1)});}catch(caught){cleanup.push(code(caught));}}
  }
  try{need(controller);await rpc(controller,'done',{result:error===null?result:null,error,cleanup},{deadline:Math.min(deadline,now()+2)});}catch{process.exitCode=1;}
  channel.close();
}
if(process.argv[1]===fileURLToPath(import.meta.url)&&process.argv[2]==='--cragkit-publication-worker-r1'){
  void child_entry().catch(()=>{process.exitCode=1;});
}
