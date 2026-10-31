/** Optional corrective PostgreSQL backend; application owns the reusable resource. */
import { z } from 'zod';
import { isDeepStrictEqual } from 'node:util';
import { configuration, profile_snapshot, select } from './hybrid.js';
import { PostgresSession, DenseCandidateSchema, IdentifierCandidateSchema, type LexicalCandidate } from './postgres-session.js';
import { source_snapshot } from './postgres-source.js';
import { type PoolResource, bounded, check_options, type LeaseOptions } from './postgres-pool.js';
import { parse_request, parse_scope, type RetrievalRequest, type TrustedScope } from './contracts.js';
import { EmbeddingAdapter, type EmbeddingProfile } from './embeddings.js';
import { RerankingAdapter, RerankProfileSchema, type RerankResult } from './reranking.js';
import { extract_identifiers } from './identifiers.js';
import { BudgetExhausted, ExecutionLedger } from './execution.js';
import type { Evidence } from './results.js';
import { deep_freeze, valid_native_json, text } from './shared.js';
import { IntegrityViolation, InvalidRequest } from './errors.js';
const LexicalSchema = z.strictObject({tenant_id:z.string(),collection:z.string(),document_id:z.string(),revision_id:z.string(),generation_id:z.string(),chunk_id:z.string(),
  start_byte:z.number().int().min(0).max(Number.MAX_SAFE_INTEGER),end_byte:z.number().int().positive().max(Number.MAX_SAFE_INTEGER),text_sha256:z.string().regex(/^[0-9a-f]{64}$/),score:z.number().finite().min(0)});
type Bound = LeaseOptions & {scope:TrustedScope;ledger:ExecutionLedger};
function candidates(input:unknown, request:RetrievalRequest, scope:TrustedScope): LexicalCandidate[] {
  try {
    if (!valid_native_json(input) || !Array.isArray(input) || input.length>64) throw new Error();
    const seen = new Set<string>();
    return input.map(raw=>{
      const item = (Object.hasOwn(raw,'embedding_profile')?DenseCandidateSchema:Object.hasOwn(raw,'identifier_profile')?IdentifierCandidateSchema:LexicalSchema).parse(raw);
      const key=JSON.stringify([item.tenant_id,item.collection,item.document_id,item.revision_id,item.generation_id,item.chunk_id]);
      if(seen.has(key)||item.tenant_id!==scope.tenant_id||item.collection!==request.collection||item.end_byte<=item.start_byte)throw new Error();
      seen.add(key);return deep_freeze(item);
    });
  } catch { throw new IntegrityViolation(); }
}
export class PostgresCorrectiveBackend {
  readonly result_versions?:Readonly<{model:string|null;index:string|null}>;
  private readonly session:PostgresSession;
  private readonly config:ReturnType<typeof configuration>;
  private readonly profile:ReturnType<typeof profile_snapshot>|null;
  private readonly reranker:RerankingAdapter|null;
  private readonly rerankProfile:ReturnType<typeof RerankProfileSchema.parse>|null;
  constructor(options:{resource:PoolResource;mode?:'lexical'|'dense'|'hybrid';embedder?:EmbeddingAdapter;embedding_profile?:EmbeddingProfile;reranker?:RerankingAdapter}) {
    if(!options||Object.getOwnPropertySymbols(options).length||Object.entries(Object.getOwnPropertyDescriptors(options)).some(([key,d])=>!['resource','mode','embedder','reranker','embedding_profile'].includes(key)||!('value'in d)||!d.enumerable))throw new InvalidRequest();
    const {resource,reranker,...config}=options;
    if(reranker!==undefined&&!(reranker instanceof RerankingAdapter))throw new InvalidRequest();
    this.config=configuration(config);this.session=new PostgresSession(resource,this.config.embedding_profile);this.profile=this.config.embedder?profile_snapshot(this.config.embedder,this.config.embedding_profile):null;
    if(this.profile?.provider==='openai') this.result_versions=Object.freeze({model:this.profile.model,index:this.config.mode==='dense'?'dense_openai.v1':'hybrid_rrf.v1'});
    this.reranker=reranker??null;this.rerankProfile=reranker?deep_freeze(RerankProfileSchema.parse(reranker.profile)):null;
  }
  async search(input:RetrievalRequest, options:Bound & {limit:number}) {
    const request=parse_request(input),scope=parse_scope(options.scope);
    const bound={scope,deadline:Math.min(options.deadline,options.ledger.deadline),signal:options.signal};check_options(bound);
    if(!Number.isSafeInteger(options.limit)||options.limit<1||options.limit>request.limits.max_candidates)throw new InvalidRequest();
    if(this.config.mode==='hybrid'){
      const minimum=extract_identifiers(request.query).length?3:2;
      if(request.limits.max_candidates<minimum)throw new InvalidRequest();
      if(options.limit<minimum)throw new BudgetExhausted();
    }
    const selectedRequest=parse_request({...request,limits:{...request.limits,max_candidates:options.limit}});
    if(this.config.mode==='lexical') {
      const raw=await this.session.transaction(selectedRequest,bound,h=>h.lexical_candidates({limit:Math.min(64,options.limit)}));
      return deep_freeze({candidates:candidates(raw,request,scope),degraded:false});
    }
    const live=this.profile!.provider!=='fake';
    let token:ReturnType<ExecutionLedger['reserve']>|undefined, settled=false;
    const dispatch=()=>{token=options.ledger.reserve({provider_calls:1,cost_upper_usd:live?null:0});options.ledger.dispatch(token);};
    const reported=(usage:import('./embeddings.js').EmbeddingUsage)=>{
      if (!token) throw new IntegrityViolation();
      settled=true;
      options.ledger.reconcile(token,{input_tokens:usage.prompt_tokens,output_tokens:usage.total_tokens!==null&&usage.prompt_tokens!==null?usage.total_tokens-usage.prompt_tokens:null,cost_usd:null});
    };
    if (!live) dispatch();
    let selection:Awaited<ReturnType<typeof select>>;
    try {selection=await select(this.session,selectedRequest,bound,this.config,this.profile!,live?dispatch:undefined,live?reported:undefined);}
    catch(error){if(token&&!settled)options.ledger.abandon(token);throw error;}
    if(token&&!settled) options.ledger.reconcile(token,{input_tokens:selection.input_tokens,output_tokens:selection.output_tokens,cost_usd:selection.cost_usd});
    return deep_freeze({candidates:candidates(selection.candidates.slice(0,64),request,scope),degraded:selection.degraded});
  }
  async capture(input:readonly LexicalCandidate[], options:Bound & {request:RetrievalRequest;max_source_bytes:number}) {
    const request=parse_request(options.request),scope=parse_scope(options.scope);
    const bound={scope,deadline:Math.min(options.deadline,options.ledger.deadline),signal:options.signal};check_options(bound);
    if(!Number.isSafeInteger(options.max_source_bytes)||options.max_source_bytes<0||options.max_source_bytes>16777216)throw new InvalidRequest();
    const selected=candidates(input,request,scope),sourceBudget=options.max_source_bytes;
    let loaded=0,stale=false,exhausted=false;
    const fetch=async(ordered:readonly LexicalCandidate[])=>{
      const evidence:Evidence[]=[];
      const sources:ReturnType<typeof source_snapshot>[]=[],mapping=new Map<string,LexicalCandidate>(),sourceMap=new Map<string,ReturnType<typeof source_snapshot>>();
      if(ordered.length && loaded===sourceBudget)exhausted=true;
      if(ordered.length && loaded<sourceBudget)await this.session.transaction(request,bound,async handle=>{
        for(const candidate of ordered){
          check_options(bound);const remaining=sourceBudget-loaded;
          if(!remaining){exhausted=true;break;}
          const value=await handle.fetch_evidence(candidate,{max_source_bytes:remaining,include_source:true});
          if(value.state==='unavailable'){stale=true;continue;}
          if(value.state==='budget_exhausted'){exhausted=true;break;}
          if(!value.evidence||!Number.isSafeInteger(value.source_bytes)||value.source_bytes<1||value.source_bytes>remaining)throw new IntegrityViolation();
          loaded+=value.source_bytes;stale||=value.stale;
          if(mapping.has(value.evidence.evidence_id))throw new IntegrityViolation();
          evidence.push(value.evidence);
          const snapshot=source_snapshot(value),key=JSON.stringify([snapshot.collection,snapshot.document_id,snapshot.revision_id]);
          if(sourceMap.has(key)){if(!isDeepStrictEqual(sourceMap.get(key),snapshot))throw new IntegrityViolation();}
          else{sourceMap.set(key,snapshot);sources.push(snapshot);}
          mapping.set(value.evidence.evidence_id,candidate);
        }
      });
      return {evidence,sources,mapping};
    };
    let captured=await fetch(this.reranker?selected.slice(0,40):selected);
    if(this.reranker&&captured.evidence.length){
      let size=Buffer.byteLength(request.query);const views:{candidate_id:string;text:string}[]=[];
      for(const item of captured.evidence){
        let bytes=0;for(const c of item.text){const n=Buffer.byteLength(c);if(bytes+n>16384)break;bytes+=n;}
        if(size+bytes>262144){exhausted=true;continue;}size+=bytes;views.push({candidate_id:item.evidence_id,text:item.text});
      }
      if(views.length){
        const validationViews=deep_freeze(views.map(view=>({...view})));
        const fake=this.rerankProfile!.provider==='fake',token=options.ledger.reserve({provider_calls:1,cost_upper_usd:fake?0:null});options.ledger.dispatch(token);
        const controller=new AbortController(),abort=()=>controller.abort();bound.signal?.addEventListener('abort',abort,{once:true});
        let ranked:Awaited<ReturnType<RerankingAdapter['rank']>>;
        try {check_options(bound);ranked=await bounded(this.reranker.rank(request.query,views,{deadline:bound.deadline,signal:controller.signal,max_provider_calls:1,allow_fallback:false}),bound,abort);}
        catch(error){options.ledger.abandon(token);throw error;}
        finally{bound.signal?.removeEventListener('abort',abort);}
        options.ledger.reconcile(token,{input_tokens:fake?0:null,output_tokens:fake?0:null,cost_usd:fake?0:null});
        ranked=validate_rerank(ranked,validationViews,this.rerankProfile!,false);
        captured=await fetch(ranked.order.map(id=>captured.mapping.get(id)!));
      }else captured={evidence:[],sources:[],mapping:new Map()};
    }
    check_options(bound);return deep_freeze({evidence:captured.evidence,sources:captured.sources,source_bytes:loaded,stale,budget_exhausted:exhausted});
  }
}

function validate_rerank(raw: unknown, candidates: readonly {candidate_id:string;text:string}[], profile: ReturnType<typeof RerankProfileSchema.parse>, allowFallback: boolean): RerankResult {
  try {
    if (!rerank_native(raw)) throw new Error();
    const result = z.strictObject({profile:RerankProfileSchema,order:z.array(text(512,false)).max(40),
      scores:z.array(z.strictObject({candidate_id:text(512,false),raw_score:z.number().finite()})).max(40),
      truncations:z.array(z.strictObject({candidate_id:text(512,false),original_bytes:z.number().int().min(0),view_bytes:z.number().int().min(0)})).max(40),
      degraded:z.boolean(),provider_calls:z.literal(1),synthetic:z.boolean()}).parse(raw);
    if (!isDeepStrictEqual(result.profile,profile) || result.synthetic !== (profile.provider === 'fake')) throw new Error();
    const ids = candidates.map(item=>item.candidate_id);
    if (result.order.length !== ids.length || new Set(result.order).size !== ids.length || result.order.some(id=>!ids.includes(id))) throw new Error();
    if (result.degraded) {
      if (!allowFallback || result.scores.length || !isDeepStrictEqual(result.order,ids)) throw new Error();
    } else {
      if (result.scores.length !== ids.length || new Set(result.scores.map(item=>item.candidate_id)).size !== ids.length || result.scores.some(item=>!ids.includes(item.candidate_id))) throw new Error();
      const scores = new Map(result.scores.map(item=>[item.candidate_id,item.raw_score]));
      const ordered = [...ids].sort((a,b)=>profile.score_direction === 'higher_is_better' ? scores.get(b)!-scores.get(a)! : scores.get(a)!-scores.get(b)!);
      if (!isDeepStrictEqual(ordered,result.order)) throw new Error();
    }
    const expected = candidates.filter(item=>Buffer.byteLength(item.text)>16384).map(item=>{
      let view_bytes=0; for(const character of item.text){const bytes=Buffer.byteLength(character);if(view_bytes+bytes>16384)break;view_bytes+=bytes;}
      return {candidate_id:item.candidate_id,original_bytes:Buffer.byteLength(item.text),view_bytes};
    });
    if (expected.length && profile.truncation_policy !== 'utf8_prefix' || !isDeepStrictEqual(expected,result.truncations)) throw new Error();
    return deep_freeze(result);
  } catch { throw new IntegrityViolation(); }
}

function rerank_native(input: unknown): boolean {
  const ancestors = new Set<object>(); let count = 0;
  function visit(value: unknown, depth: number): boolean {
    if (++count > 4096 || depth > 16) return false;
    if (typeof value === 'number') return Number.isFinite(value);
    if (typeof value !== 'object' || value === null) return valid_native_json(value);
    if (ancestors.has(value) || Object.getOwnPropertySymbols(value).length || (!Array.isArray(value) && ![Object.prototype,null].includes(Object.getPrototypeOf(value)))) return false;
    if (Array.isArray(value) && (value.length > 128 || Object.keys(value).length !== value.length)) return false;
    ancestors.add(value);
    try { return Object.entries(Object.getOwnPropertyDescriptors(value)).every(([key,field])=>Array.isArray(value)&&key==='length'||'value' in field&&field.enumerable&&visit(field.value,depth+1)); }
    finally { ancestors.delete(value); }
  }
  try { return visit(input,0); } catch { return false; }
}
