/** Optional dense Qdrant composition for the native corrective engine. */
import {EmbeddingAdapter,type EmbeddingTransport,type TokenCounter,type EmbeddingPolicy} from './embeddings.js';
import {EmbeddingProfileMismatch,IntegrityViolation,InvalidRequest,UnsupportedCapability} from './errors.js';
import {ExecutionLedger,type Reservation} from './execution.js';
import {parse_request,parse_scope,type RetrievalRequest} from './requests.js';
import {QdrantSearchStore,bind_embedding_batch,compile_filter,type QdrantNomination} from './qdrant.js';
import {PostgresQdrantSourceStore} from './qdrant-source.js';
import {native_options,validate_nomination} from './qdrant-source-contract.js';
import {check_deadline} from './qdrant-transport.js';
import {same} from './qdrant-contract.js';
import {deep_freeze,valid_native_json} from './shared.js';
import type {CorrectiveBackend,CorrectiveBackendOptions,CorrectiveCandidate} from './corrective.js';
import type {Evidence} from './results.js';

type Candidate=Extract<CorrectiveCandidate,{backend:'qdrant'}>;
type Source={collection:string;document_id:string;revision_id:string;source_sha256:string;text:string};
function candidate(nomination:QdrantNomination):Candidate {
  const p=nomination.payload;
  return deep_freeze({backend:'qdrant',tenant_id:p.tenant_id,collection:p.collection,document_id:p.document_id,
    revision_id:p.revision_id,generation_id:p.generation_id,chunk_id:p.chunk_id,start_byte:p.start_byte,
    end_byte:p.end_byte,text_sha256:p.text_sha256,score:nomination.score,nomination});
}

export class QdrantCorrectiveBackend implements CorrectiveBackend {
  readonly candidate_accounting='backend' as const;
  readonly #candidates:QdrantSearchStore;
  readonly #sources:PostgresQdrantSourceStore;
  readonly #transport:EmbeddingTransport;
  readonly #counter:TokenCounter;
  readonly #policy:EmbeddingPolicy;
  constructor(candidates:QdrantSearchStore,sources:PostgresQdrantSourceStore,options:{
    embedding_transport:EmbeddingTransport;token_counter:TokenCounter;policy?:Partial<EmbeddingPolicy>;mode?:string}) {
    native_options(options,['embedding_transport','token_counter','policy','mode']);
    if((options.mode===undefined?'dense':options.mode)!=='dense')throw new UnsupportedCapability();
    if(!(candidates instanceof QdrantSearchStore)||Object.getPrototypeOf(candidates)!==QdrantSearchStore.prototype
      ||!(sources instanceof PostgresQdrantSourceStore)||Object.getPrototypeOf(sources)!==PostgresQdrantSourceStore.prototype)throw new InvalidRequest();
    if(!same(candidates.config.dense_profile,sources.config.dense_profile))throw new EmbeddingProfileMismatch();
    if(!same(candidates.config,sources.config))throw new UnsupportedCapability();
    const validated=new EmbeddingAdapter(options.embedding_transport,options.token_counter,{profile:candidates.config.dense_profile,policy:options.policy});
    this.#candidates=candidates;this.#sources=sources;this.#transport=options.embedding_transport;
    this.#counter=options.token_counter;this.#policy=validated.policy;
  }
  capabilities(){return deep_freeze({dense:true,lexical:false,hybrid:false,current_source_authority:true,publication:false,repair:false,owns_resources:false});}

  async search(input:RetrievalRequest,options:CorrectiveBackendOptions&{limit:number}):Promise<{candidates:readonly Candidate[];degraded:boolean}> {
    native_options(options,['scope','deadline','ledger','signal','limit']);
    const request=parse_request(input),scope=parse_scope(options.scope),ledger=options.ledger;
    if(!(ledger instanceof ExecutionLedger)||Object.getPrototypeOf(ledger)!==ExecutionLedger.prototype
      ||!Number.isSafeInteger(options.limit)||options.limit<1||options.limit>Math.min(64,request.limits.max_candidates))throw new InvalidRequest();
    const deadline=Math.min(options.deadline,ledger.deadline);check_deadline(deadline,options.signal);compile_filter(request,scope);
    let token:Reservation|undefined,admissionError:unknown;
    const adapter=new EmbeddingAdapter(async(body,transportOptions)=>{
      try {token=ledger.reserve({provider_calls:1,cost_upper_usd:this.#candidates.config.dense_profile.provider==='fake'?0:this.#policy.max_cost_usd});ledger.dispatch(token);}
      catch(error){admissionError=error;throw error;}
      return this.#transport(body,transportOptions);
    },this.#counter,{profile:this.#candidates.config.dense_profile,policy:this.#policy,limits:{max_items:1}});
    let batch;
    try {
      batch=bind_embedding_batch(await adapter.embed_query(request.query,{deadline,signal:options.signal}),adapter.profile,{expected_items:1});
      if(!token)throw new IntegrityViolation();
      const usage=batch.usage;
      ledger.reconcile(token,{input_tokens:usage.prompt_tokens,
        output_tokens:usage.total_tokens!==null&&usage.prompt_tokens!==null?usage.total_tokens-usage.prompt_tokens:null,
        cost_usd:usage.cost_kind==='known'?usage.cost_usd:null});token=undefined;
    } catch(error){if(admissionError!==undefined)throw admissionError;throw error;}
    finally{if(token)ledger.abandon(token);}
    const nominations=await this.#candidates.search_candidates(request,{scope,deadline,signal:options.signal,
      dense:batch,branch_limits:{dense:options.limit},ledger});
    return {candidates:nominations.map(n=>candidate(validate_nomination(n,request,scope,this.#candidates.config))),degraded:false};
  }

  async capture(input:readonly CorrectiveCandidate[],options:CorrectiveBackendOptions&{request:RetrievalRequest;max_source_bytes:number}) {
    native_options(options,['scope','deadline','ledger','signal','request','max_source_bytes']);
    const request=parse_request(options.request),scope=parse_scope(options.scope),ledger=options.ledger;
    if(!(ledger instanceof ExecutionLedger)||Object.getPrototypeOf(ledger)!==ExecutionLedger.prototype
      ||!Number.isSafeInteger(options.max_source_bytes)||options.max_source_bytes<0||options.max_source_bytes>16777216
      ||!Array.isArray(input)||input.length>64)throw new InvalidRequest();
    const deadline=Math.min(options.deadline,ledger.deadline);check_deadline(deadline,options.signal);
    const selected=input.map(raw=>{
      try{
        if(!valid_native_json(raw)||!('nomination'in raw)||raw.backend!=='qdrant')throw new IntegrityViolation();
        const value=candidate(validate_nomination(raw.nomination,request,scope,this.#candidates.config));
        if(!same(value,raw))throw new IntegrityViolation();return value;
      }catch{throw new IntegrityViolation();}
    });
    if(new Set(selected.map(c=>c.nomination.point_id)).size!==selected.length)throw new IntegrityViolation();
    const handle=this.#sources.open_request(request,{scope,deadline,signal:options.signal});
    let loaded=0,stale=false,exhausted=false;const evidence:Evidence[]=[],sources=new Map<string,Source>();
    try {
      for(const item of selected){
        if(loaded>=options.max_source_bytes){exhausted=true;break;}
        const fetched=await handle.fetch_candidate(item.nomination,{max_source_bytes:options.max_source_bytes-loaded});loaded+=fetched.source_bytes;
        if(fetched.state!=='verified'){stale||=fetched.state==='unavailable';exhausted||=fetched.state==='budget_exhausted';continue;}
        const released=await handle.release(fetched.binding,{purpose:'final',max_source_bytes:options.max_source_bytes-loaded,include_source:true});loaded+=released.source_bytes;
        if(released.state!=='verified'){stale||=released.state==='unavailable';exhausted||=released.state==='budget_exhausted';continue;}
        if(!released.evidence||!released.private_source)throw new IntegrityViolation();
        const row=released.evidence,source={collection:row.collection,document_id:row.document_id,revision_id:row.revision_id,
          source_sha256:row.source_sha256,text:released.private_source.canonical_text};
        const key=JSON.stringify([row.collection,row.document_id,row.revision_id]);
        if(sources.has(key)&&!same(sources.get(key),source))throw new IntegrityViolation();
        sources.set(key,source);evidence.push(row);stale||=fetched.stale||released.stale;
      }
      check_deadline(deadline,options.signal);
      return {evidence,sources:[...sources.values()],source_bytes:loaded,stale,budget_exhausted:exhausted};
    }finally{await handle.close();}
  }
}
