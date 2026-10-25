import {PostgresQdrantAuthority} from './qdrant-authority.js';
import {PoolResource,bounded,now,abort_error} from './postgres-pool.js';
import {check_deadline} from './qdrant-transport.js';
import {parse_config,type QdrantConfig,type QdrantNomination} from './qdrant-contract.js';
import {parse_request,parse_scope,type RetrievalRequest,type TrustedScope} from './requests.js';
import {SourceFetch,source_result,verify_source,validate_nomination,compile_source_filters,fetch_options,native_options,row_provenance,MAX_SOURCE_BYTES,type Provenance} from './qdrant-source-contract.js';
import {deep_freeze} from './shared.js';
import {DeadlineExceeded,IndexNotReady,IntegrityViolation,InvalidRequest,ProviderUnavailable} from './errors.js';
export {SourceFetch} from './qdrant-source-contract.js';
type DeadlineOptions={deadline:number;signal?:AbortSignal};
type ReadOptions={max_source_bytes:number;include_source?:boolean};
type BindingState={nomination:QdrantNomination;provenance:Provenance;provider:boolean;final:boolean;attempts:number};

class SourceRequest {
  readonly #authority:PostgresQdrantAuthority;
  readonly #config:QdrantConfig;
  readonly #original:DeadlineOptions;
  readonly #onClose:()=>void;
  readonly #bindings=new WeakMap<object,BindingState>();
  readonly #controller=new AbortController();
  readonly #request:RetrievalRequest;
  readonly #scope:TrustedScope;
  readonly #deadline:number;
  #closed=false;
  #busy=false;
  #fetches=0;
  #issued=0;
  #reads=0;
  #loaded=0;
  #pending:Promise<unknown>|undefined;
  readonly #relay:()=>void;
  constructor(authority:PostgresQdrantAuthority,config:QdrantConfig,request:RetrievalRequest,scope:TrustedScope,original:DeadlineOptions,onClose:()=>void){
    this.#authority=authority;
    this.#config=config;
    this.#original=original;
    this.#onClose=onClose;
    this.#request=request;
    this.#scope=scope;
    this.#deadline=original.deadline;
    this.#relay=()=>this.#controller.abort();
    original.signal?.addEventListener('abort',this.#relay,{once:true});
  }
  #check(){
    if(this.#closed)throw new InvalidRequest();
    check_deadline(this.#deadline,this.#controller.signal);
    if(this.#busy)throw new ProviderUnavailable();
  }
  async #read(nomination:QdrantNomination,options:ReturnType<typeof fetch_options>,retained:boolean,provenance?:Provenance):Promise<{result:SourceFetch;provenance?:Provenance}>{
    this.#check();
    if(this.#reads>=192)return {result:source_result('budget_exhausted')};
    this.#reads++;
    this.#busy=true;
    const max_source_bytes=Math.min(options.max_source_bytes,MAX_SOURCE_BYTES-this.#loaded);
    const work=(async()=>{
      const rows=await this.#authority.read(nomination,this.#request,this.#scope,this.#config,{retained,max_source_bytes,deadline:this.#deadline,signal:this.#controller.signal});
      check_deadline(this.#deadline,this.#controller.signal);
      // Charge actual loaded canonical buffers even if later verification fails.
      const loaded=rows.reduce((sum,r)=>sum+(r.canonical_utf8 instanceof Uint8Array?r.canonical_utf8.byteLength:0),0);
      this.#loaded+=loaded;
      if(this.#loaded>MAX_SOURCE_BYTES||loaded>max_source_bytes)throw new IntegrityViolation();
      const result=verify_source(nomination,rows,this.#request,this.#scope,this.#config,{retained,max_source_bytes,include_source:options.include_source,bound_provenance:provenance});
      check_deadline(this.#deadline,this.#controller.signal);
      return {result,provenance:result.state==='verified'?row_provenance(rows[0]):undefined};
    })();
    this.#pending=work;
    try{
      return await work;
    }finally{
      this.#busy=false;
      if(this.#pending===work)this.#pending=undefined;
    }
  }
  async fetch_candidate(input:unknown,options:ReadOptions):Promise<SourceFetch>{
    this.#check();
    const parsed=fetch_options(options);
    const nomination=validate_nomination(input,this.#request,this.#scope,this.#config);
    if(this.#fetches>=64||this.#issued>=64)return source_result('budget_exhausted');
    this.#fetches++;
    const {result,provenance}=await this.#read(nomination,parsed,false);
    if(result.state!=='verified')return result;
    if(this.#closed)throw new InvalidRequest();
    const binding=Object.freeze(Object.defineProperty({},'toJSON',{value:()=>{throw new InvalidRequest();},enumerable:false}));
    this.#bindings.set(binding,{nomination,provenance:provenance!,provider:false,final:false,attempts:0});
    this.#issued++;
    return new SourceFetch(result.state,result.evidence,binding,result.source_bytes,result.stale,result.private_source);
  }
  async release(binding:unknown,options:ReadOptions&{purpose:'provider'|'final'}):Promise<SourceFetch>{
    this.#check();
    native_options(options,['purpose','max_source_bytes','include_source']);
    const parsed=fetch_options({max_source_bytes:options.max_source_bytes,...(options.include_source===undefined?{}:{include_source:options.include_source})});
    if(options.purpose!=='provider'&&options.purpose!=='final')throw new InvalidRequest();
    const state=typeof binding==='object'&&binding!==null?this.#bindings.get(binding):undefined;
    if(!state||state.attempts>=2||state.final||(options.purpose==='provider'&&state.provider))throw new InvalidRequest();
    state.attempts++;
    state[options.purpose]=true;
    const {result}=await this.#read(state.nomination,parsed,true,state.provenance);
    return new SourceFetch(result.state,result.evidence,result.state==='verified'?binding as object:null,result.source_bytes,result.stale,result.private_source);
  }
  async close():Promise<void>{
    if(this.#closed)return;
    this.#closed=true;
    this.#controller.abort();
    this.#original.signal?.removeEventListener('abort',this.#relay);
    try{
      if(this.#pending)await bounded(this.#pending.then(()=>undefined,()=>undefined),{deadline:now()+1});
    }catch{
      // The pending operation already owns its sanitized failure and client cleanup.
    }finally{
      this.#onClose();
    }
  }
  toJSON(){throw new InvalidRequest();}
}
export class PostgresQdrantSourceStore {
  readonly config:QdrantConfig;
  readonly #authority:PostgresQdrantAuthority;
  #ready=false;
  #closed=false;
  #initializing=false;
  #handle:SourceRequest|undefined;
  #controller:AbortController|undefined;
  #pending:Promise<unknown>|undefined;
  constructor(resource:PoolResource,config:unknown){
    this.config=parse_config(config);
    this.#authority=new PostgresQdrantAuthority(resource);
  }
  capabilities(){return deep_freeze({source_authority:true,candidate_replica_only:false,qd_r1_compatible:false,publication:false,repair:false});}
  async initialize(options:DeadlineOptions):Promise<void>{
    native_options(options,['deadline','signal']);
    if(this.#closed)throw new InvalidRequest();
    if(this.#initializing||this.#handle)throw new ProviderUnavailable();
    if(options.signal!==undefined&&!(options.signal instanceof AbortSignal))throw new InvalidRequest();
    check_deadline(options.deadline,options.signal);
    const controller=new AbortController();
    const relay=()=>controller.abort();
    options.signal?.addEventListener('abort',relay,{once:true});
    this.#controller=controller;
    this.#initializing=true;
    this.#ready=false;
    const pending=this.#authority.initialize({deadline:options.deadline,signal:controller.signal});
    this.#pending=pending;
    try{
      await pending;
      check_deadline(options.deadline,controller.signal);
      if(this.#closed)throw new InvalidRequest();
      this.#ready=true;
    }finally{
      options.signal?.removeEventListener('abort',relay);
      this.#initializing=false;
      this.#controller=undefined;
      this.#pending=undefined;
    }
  }
  open_request(input:unknown,options:DeadlineOptions&{scope:unknown}):SourceRequest{
    const entered=now();
    native_options(options,['scope','deadline','signal']);
    if(this.#closed)throw new InvalidRequest();
    if(this.#handle||this.#initializing)throw new ProviderUnavailable();
    if(!this.#ready)throw new IndexNotReady();
    if(options.signal!==undefined&&!(options.signal instanceof AbortSignal))throw new InvalidRequest();
    check_deadline(options.deadline,options.signal);
    const request=parse_request(input);
    const scope=parse_scope(options.scope);
    compile_source_filters(request.required_filters);
    const deadline=Math.min(options.deadline,entered+request.limits.deadline_ms/1000);
    check_deadline(deadline,options.signal);
    const handle=new SourceRequest(this.#authority,this.config,request,scope,{deadline,signal:options.signal},()=>{
      if(this.#handle===handle)this.#handle=undefined;
    });
    this.#handle=handle;
    return handle;
  }
  async close():Promise<void>{
    if(this.#closed)return;
    this.#closed=true;
    this.#ready=false;
    this.#controller?.abort();
    await this.#handle?.close();
    if(this.#pending){
      try{
        await bounded(this.#pending.then(()=>undefined,()=>undefined),{deadline:now()+1});
      }catch{
        // Caller-owned pools remain open; initialization owns its cleanup.
      }
    }
  }
  toJSON(){return {capabilities:this.capabilities()};}
}
