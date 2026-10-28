/** Optional authority-only security admission; resources remain application-owned. */
import {randomUUID} from 'node:crypto';
import {types} from 'node:util';
import {PostgresQdrantWriter,writer_binding,type IntentView} from './qdrant-writer.js';
import {ExecutionLedger,BudgetExhausted,type Reservation} from './execution.js';
import {bounded,now,type LeaseOptions} from './postgres-pool.js';
import {operation as parse_operation,options as parse_options} from './qdrant-writer-contract.js';
import {type TrustedScope} from './requests.js';
import {InvalidRequest,IntegrityViolation,UnauthorizedScope,UnsupportedCapability,ProviderUnavailable,
  DeadlineExceeded,IndexNotReady,EmbeddingProfileMismatch} from './errors.js';

type Action='update_authorization'|'tombstone';
type Authorizer=(scope:TrustedScope,collection:string,document_id:string)=>Promise<boolean>;
export type SecurityResult=Readonly<{intent_id:string;operation:Action;state:string;revision_id:string|null;
  generation_id:string|null;authority_committed:boolean;replica_complete:boolean;published:boolean;purge_complete:boolean}>;
function exact(value:unknown,prototype:object):boolean {
  return typeof value==='object'&&value!==null&&!types.isProxy(value)&&Object.getPrototypeOf(value)===prototype;
}
function safe(error:unknown):Error {
  try{
    if(typeof error==='object'&&error!==null&&types.isProxy(error))return new ProviderUnavailable();
    for(const Kind of [InvalidRequest,IntegrityViolation,UnauthorizedScope,UnsupportedCapability,ProviderUnavailable,
      DeadlineExceeded,IndexNotReady,EmbeddingProfileMismatch,BudgetExhausted])if(error instanceof Kind)return new Kind();
    if(error instanceof DOMException&&error.name==='AbortError')return new DOMException('Operation aborted.','AbortError');
  }catch{/* Error inspection must not execute a private error escape path. */}
  return new ProviderUnavailable();
}
function callback_error(error:unknown):Error {
  try{
    if(typeof error==='object'&&error!==null&&types.isProxy(error))return new ProviderUnavailable();
    if(error instanceof InvalidRequest)return new InvalidRequest();
    if(error instanceof DOMException&&error.name==='AbortError')return new DOMException('Operation aborted.','AbortError');
  }catch{/* Untrusted callback errors remain redacted. */}
  return new ProviderUnavailable();
}

export class QdrantSecurityManager {
  readonly #writer:PostgresQdrantWriter;
  readonly #authorize:Authorizer;
  #ready=false;
  #closed=false;
  #active?:Readonly<{controller:AbortController;done:Promise<void>}>;
  #pending=new Set<Promise<unknown>>();

  constructor(writer:PostgresQdrantWriter,authorize_write:Authorizer){
    writer_binding(writer);
    if(typeof authorize_write!=='function'||types.isProxy(authorize_write))throw new InvalidRequest();
    this.#writer=writer;this.#authorize=authorize_write;
  }
  #admit(initializing=false):void {
    if(this.#closed||this.#active)throw new ProviderUnavailable();
    if(!initializing&&!this.#ready)throw new IndexNotReady();
  }
  async #await<T>(work:Promise<T>,options:LeaseOptions):Promise<T>{
    this.#pending.add(work);
    void work.then(()=>this.#pending.delete(work),()=>this.#pending.delete(work));
    const value=await bounded(work,options);parse_options(options);return value;
  }
  async #operation<T>(options:LeaseOptions,body:(lease:LeaseOptions)=>Promise<T>,initializing=false):Promise<T>{
    this.#admit(initializing);
    const controller=new AbortController(),relay=()=>controller.abort();
    options.signal?.addEventListener('abort',relay,{once:true});
    if(options.signal?.aborted)controller.abort();
    let finish!:()=>void;
    const done=new Promise<void>(resolve=>{finish=resolve;});
    this.#active={controller,done};
    try{return await body({deadline:options.deadline,signal:controller.signal});}
    catch(error){throw safe(error);}
    finally{
      controller.abort();options.signal?.removeEventListener('abort',relay);
      const drain=Promise.allSettled([...this.#pending]);
      try{await bounded(drain,{deadline:now()+2});}
      catch{
        this.#closed=true;
        void drain.then(()=>{this.#active=undefined;finish();});
      }
      if(this.#pending.size===0){this.#active=undefined;finish();}
    }
  }
  async initialize(rawOptions:unknown):Promise<void>{
    const options=parse_options(rawOptions);
    await this.#operation(options,async lease=>{
      await this.#await(this.#writer.initialize(lease),lease);this.#ready=true;
    },true);
  }
  async #change(action:Action,input:unknown,inputScope:unknown,ledger:ExecutionLedger,rawOptions:unknown):Promise<SecurityResult>{
    // Copy canonical inputs before application code can mutate them during an await.
    const change=parse_operation(input,inputScope,randomUUID());
    if(change.record.action!==action)throw new InvalidRequest();
    if(!exact(ledger,ExecutionLedger.prototype))throw new InvalidRequest();
    const caller=parse_options(rawOptions);
    const options=parse_options({deadline:Math.min(caller.deadline,ledger.deadline),signal:caller.signal});
    return this.#operation(options,async lease=>{
      let reservation:Reservation|undefined=ledger.reserve({attempts:1});
      try{
        ledger.dispatch(reservation);
        const pending=Promise.resolve().then(async()=>{
          parse_options(lease);
          try{
            const value=this.#authorize(change.scope,String(change.record.collection),String(change.record.document_id));
            if(!(value instanceof Promise)||types.isProxy(value))throw new InvalidRequest();
            return await value;
          }catch(error){throw callback_error(error);}
        });
        const allowed=await this.#await(pending,lease);
        if(typeof allowed!=='boolean')throw new InvalidRequest();
        if(!allowed)throw new UnauthorizedScope();
        parse_options(lease);
        const result:IntentView=await this.#await(this.#writer.apply_security(change.record,change.scope,
          {...lease,owner_token:change.owner_token}),lease);
        parse_options(lease);
        const output=Object.freeze({intent_id:String(change.record.intent_id),operation:action,state:result.state,
          revision_id:result.revision_id,generation_id:result.generation_id,authority_committed:result.authority_committed,
          replica_complete:result.replica_complete,published:result.state==='published',purge_complete:result.purge_complete});
        ledger.reconcile(reservation);reservation=undefined;return output;
      }finally{if(reservation)ledger.abandon(reservation);}
    });
  }
  async update_authorization(record:unknown,scope:unknown,ledger:ExecutionLedger,options:unknown):Promise<SecurityResult>{
    return this.#change('update_authorization',record,scope,ledger,options);
  }
  async tombstone(record:unknown,scope:unknown,ledger:ExecutionLedger,options:unknown):Promise<SecurityResult>{
    return this.#change('tombstone',record,scope,ledger,options);
  }
  async close():Promise<void>{
    this.#closed=true;const active=this.#active;active?.controller.abort();
    if(active)await bounded(active.done,{deadline:now()+2});
  }
}
