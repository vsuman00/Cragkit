import { z } from 'zod';
import { ExecutionLedger, type Reservation } from './execution.js';
import { parse_request, parse_scope } from './requests.js';
import { deep_freeze, valid_native_json } from './shared.js';
import { DeadlineExceeded, EmbeddingProfileMismatch, IndexNotReady, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability } from './errors.js';
import { bind_embedding_batch, compile_filter, dense_vector, sparse_vector, parse_config, parse_response, validate_payload, same, PAYLOAD_FIELDS, type QdrantConfig, type QdrantNomination, type Branch } from './qdrant-contract.js';
import { abort_error, abortable, check_deadline, drain, type QdrantTransport } from './qdrant-transport.js';
export { FetchQdrantTransport } from './qdrant-transport.js';
export type { QdrantTransport, QdrantTransportOptions } from './qdrant-transport.js';
export { bind_embedding_batch, point_id, compile_filter, SPARSE_PROFILE, QdrantConfigSchema, QdrantPayloadSchema } from './qdrant-contract.js';
export type { QdrantConfig, QdrantPayload, QdrantNomination } from './qdrant-contract.js';

type OperationOptions={deadline:number;signal?:AbortSignal};
export type QdrantSearchOptions=OperationOptions&{scope:unknown;dense?:unknown;sparse?:unknown;branch_limits:unknown;ledger:ExecutionLedger};
function object(v:unknown):v is Record<string,unknown>{return typeof v==='object'&&v!==null&&!Array.isArray(v);}
function options_shape(v:unknown,keys:readonly string[]):void {
  try {
    if(!object(v)||(Object.getPrototypeOf(v)!==Object.prototype&&Object.getPrototypeOf(v)!==null)||Object.getOwnPropertySymbols(v).length)throw new Error();
    for(const [key,d]of Object.entries(Object.getOwnPropertyDescriptors(v)))if(!keys.includes(key)||!('value'in d)||!d.enumerable)throw new Error();
  }catch{throw new InvalidRequest();}
}

/** Scoped index nominations only. SourceStore authorization is a separate gate. */
export class QdrantSearchStore {
  readonly config:QdrantConfig;
  readonly #transport:QdrantTransport;
  #ready=false;#closed=false;
  #controller:AbortController|undefined;
  #pending:Promise<unknown>|undefined;
  constructor(config:unknown,transport:QdrantTransport){
    this.config=parse_config(config);
    if(!transport||transport.bounded_responses!==true||transport.cancellation_safe!==true||typeof transport.request!=='function')throw new UnsupportedCapability();
    this.#transport=transport;
  }
  capabilities(){return deep_freeze({candidate_replica_only:true,source_authority:false,qd_r1_compatible:false,dense:true,sparse:this.config.sparse_profile!==null,identifier:false,native_fusion:false,publication:false,filters:['eq','in','and','or']});}
  async #operation<T>(options:OperationOptions,work:(deadline:number,signal:AbortSignal)=>Promise<T>):Promise<T>{
    if(this.#closed)throw new InvalidRequest();if(this.#controller)throw new ProviderUnavailable();
    if(options.signal!==undefined&&!(options.signal instanceof AbortSignal))throw new InvalidRequest();
    check_deadline(options.deadline,options.signal);
    const controller=new AbortController();this.#controller=controller;
    const external=()=>controller.abort();options.signal?.addEventListener('abort',external,{once:true});
    let expired=false;
    const timer=setTimeout(()=>{expired=true;controller.abort();},Math.min(2147483647,Math.max(1,Math.ceil((options.deadline-performance.now()/1000)*1000))));
    const pending=work(options.deadline,controller.signal);this.#pending=pending;
    try {const result=await abortable(pending,controller.signal);check_deadline(options.deadline,options.signal);return result;}
    catch(error){
      if(expired||performance.now()/1000>=options.deadline)throw new DeadlineExceeded();
      if(options.signal?.aborted||this.#closed)throw abort_error();
      throw error;
    }finally{
      controller.abort();clearTimeout(timer);options.signal?.removeEventListener('abort',external);if(!await drain(pending))this.#closed=true;
      if(this.#controller===controller){this.#controller=undefined;this.#pending=undefined;}
    }
  }
  async #request(method:string,path:string,body:unknown,deadline:number,signal:AbortSignal):Promise<unknown>{
    check_deadline(deadline,signal);
    const bytes=body===undefined?undefined:Buffer.from(JSON.stringify(body),'utf8');
    if(bytes!==undefined&&bytes.byteLength>262144)throw new InvalidRequest();
    let raw:Uint8Array;
    try{raw=await this.#transport.request(method,path,{body:bytes,deadline,max_response_bytes:1048576,signal});}
    catch(e){if(signal.aborted)throw abort_error();if(e instanceof DeadlineExceeded)throw new DeadlineExceeded();if(e instanceof UnsupportedCapability)throw new UnsupportedCapability();if(e instanceof InvalidRequest)throw new InvalidRequest();throw new ProviderUnavailable();}
    check_deadline(deadline,signal);return parse_response(raw);
  }
  async initialize(options:OperationOptions):Promise<void>{
    options_shape(options,['deadline','signal']);
    return this.#operation(options,async(deadline,signal)=>{
      this.#ready=false;
      const root=await this.#request('GET','/',undefined,deadline,signal);
      if(!object(root)||typeof root.version!=='string')throw new IntegrityViolation();
      if(root.version!=='1.20.0')throw new UnsupportedCapability();
      const cluster=await this.#request('GET','/cluster',undefined,deadline,signal);
      if(!object(cluster)||cluster.status!=='ok'||!object(cluster.result))throw new IntegrityViolation();
      if(cluster.result.status!=='disabled')throw new UnsupportedCapability();
      const collection=await this.#request('GET',`/collections/${this.config.physical_collection}`,undefined,deadline,signal);
      if(!object(collection)||collection.status!=='ok'||!object(collection.result))throw new IntegrityViolation();
      if(!object(collection.result.config)||!object(collection.result.config.params))throw new UnsupportedCapability();
      const params=collection.result.config.params;
      if(params.replication_factor!==1||params.write_consistency_factor!==1||!object(params.vectors)||Object.keys(params.vectors).length!==1||!object(params.vectors.dense)||params.vectors.dense.size!==1536||params.vectors.dense.distance!=='Cosine'||(params.vectors.dense.multivector_config!==null&&params.vectors.dense.multivector_config!==undefined))throw new UnsupportedCapability();
      const sparse=params.sparse_vectors;
      if(this.config.sparse_profile!==null){if(!object(sparse)||Object.keys(sparse).length!==1||!object(sparse.sparse)||(sparse.sparse.modifier!==undefined&&sparse.sparse.modifier!==null&&sparse.sparse.modifier!=='none'))throw new UnsupportedCapability();}
      else if(sparse!==undefined&&sparse!==null&&(!object(sparse)||Object.keys(sparse).length!==0))throw new UnsupportedCapability();
      check_deadline(deadline,signal);this.#ready=true;
    });
  }
  async search_candidates(input:unknown,options:QdrantSearchOptions):Promise<readonly QdrantNomination[]>{
    const entered=performance.now()/1000;
    options_shape(options,['scope','dense','sparse','branch_limits','ledger','deadline','signal']);
    const request=parse_request(input),scope=parse_scope(options.scope);
    const filter=compile_filter(request,scope);
    let dense:readonly number[]|undefined;
    if(options.dense!==undefined&&options.dense!==null){
      if(Array.isArray(options.dense)){
        if(this.config.dense_profile.provider!=='fake')throw new EmbeddingProfileMismatch();
        dense=dense_vector(options.dense);
      }else dense=bind_embedding_batch(options.dense,this.config.dense_profile,{expected_items:1}).vectors[0];
    }
    const sparse=options.sparse===undefined||options.sparse===null?undefined:sparse_vector(options.sparse);
    if(!dense&&!sparse)throw new InvalidRequest();if(sparse&&!this.config.sparse_profile)throw new UnsupportedCapability();
    let limits:Partial<Record<Branch,number>>;
    try{
      if(!valid_native_json(options.branch_limits))throw new Error();
      limits=z.strictObject({dense:z.number().int().min(1).max(64).optional(),sparse:z.number().int().min(1).max(64).optional()}).parse(options.branch_limits);
      if((dense!==undefined)!==(limits.dense!==undefined)||(sparse!==undefined)!==(limits.sparse!==undefined))throw new Error();
    }catch{throw new InvalidRequest();}
    const total=(limits.dense??0)+(limits.sparse??0);
    if(total>64||total>request.limits.max_candidates||!(options.ledger instanceof ExecutionLedger))throw new InvalidRequest();
    if(!this.#ready)throw new IndexNotReady();
    if(typeof options.deadline!=='number'||!Number.isFinite(options.deadline)||Math.abs(options.deadline)>Number.MAX_SAFE_INTEGER)throw new InvalidRequest();
    const deadline=Math.min(options.deadline,options.ledger.deadline,entered+request.limits.deadline_ms/1000);
    const ledger=options.ledger;
    return this.#operation({deadline,signal:options.signal},async(effective,signal)=>{
      let token:Reservation|undefined;
      const result:QdrantNomination[]=[];
      const across=new Map<string,QdrantNomination>();
      try{
        token=ledger.reserve({candidates:total});ledger.dispatch(token);
        for(const branch of ['dense','sparse']as const){
          const vector=branch==='dense'?dense:sparse;if(vector===undefined)continue;
          check_deadline(effective,signal);
          const body={query:vector,using:branch,filter,limit:limits[branch],with_payload:[...PAYLOAD_FIELDS],with_vector:false};
          const response=await this.#request('POST',`/collections/${this.config.physical_collection}/points/query`,body,effective,signal);
          if(!object(response)||response.status!=='ok'||!object(response.result)||Object.keys(response.result).some(k=>k!=='points')||!Array.isArray(response.result.points)||response.result.points.length>limits[branch]!)throw new IntegrityViolation();
          const ids=new Set<string>(),chunks=new Set<string>();
          for(const point of response.result.points){
            if(!object(point)||Object.keys(point).some(k=>!['id','score','payload','version','order_value','shard_key'].includes(k))||typeof point.id!=='string'||typeof point.score!=='number'||!Number.isFinite(point.score)||(branch==='dense'&&(point.score < -1.000001||point.score > 1.000001)))throw new IntegrityViolation();
            const payload=validate_payload(point.payload,this.config,request,scope,point.id);
            const chunk=JSON.stringify([payload.tenant_id,payload.collection,payload.document_id,payload.revision_id,payload.generation_id,payload.chunk_id]);
            if(ids.has(point.id)||chunks.has(chunk))throw new IntegrityViolation();ids.add(point.id);chunks.add(chunk);
            const prior=across.get(point.id);if(prior&&!same(prior.payload,payload))throw new IntegrityViolation();
            const nomination=deep_freeze({point_id:point.id,branch,score:point.score,score_kind:branch==='dense'?'cosine_similarity' as const:'dot_product' as const,score_direction:'higher_is_better' as const,verification:'UNVERIFIED' as const,payload});
            across.set(point.id,nomination);result.push(nomination);
          }
        }
        check_deadline(effective,signal);ledger.reconcile(token);token=undefined;return Object.freeze(result);
      }finally{if(token!==undefined)ledger.abandon(token);}
    });
  }
  async close():Promise<void>{this.#closed=true;this.#ready=false;this.#controller?.abort();if(this.#pending)await drain(this.#pending);}
}
