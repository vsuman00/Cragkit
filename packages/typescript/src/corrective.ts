import { version } from './index.js';
import { z } from 'zod';
import { createHash } from 'node:crypto';
import { performance } from 'node:perf_hooks';
import { assess_evidence } from './assessment.js';
import { Cl100kCounter, count_context } from './context.js';
import { pack_and_assess, type AssessedEvidence } from './evidence.js';
import { EventSink, new_trace, type EventStage, type EventSnapshot } from './events.js';
import { ExecutionLedger, BudgetExhausted } from './execution.js';
import { CragkitError, DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability } from './errors.js';
import { validate_plan, type ApprovedVariant, PlannerAdapter } from './planning.js';
import { parse_request, parse_scope, type RetrievalRequest, type TrustedScope } from './requests.js';
import { EvidenceSchema, ResultSchema, VersionsSchema, type Evidence, type RetrievalResult } from './results.js';
import { deep_freeze, identity, integer, safe_number, valid_native_json } from './shared.js';
import {QdrantPayloadSchema,point_id,payload_tuple} from './qdrant-contract.js';

// Match native candidate wire boundaries without importing the optional database module.
const base = z.strictObject({tenant_id: identity, collection: identity, document_id: identity, revision_id: identity,
  generation_id: identity, chunk_id: identity, start_byte: integer(0, Number.MAX_SAFE_INTEGER),
  end_byte: integer(1, Number.MAX_SAFE_INTEGER), text_sha256: z.string().regex(/^[0-9a-f]{64}$/), score: safe_number.min(0)});
const nomination=z.strictObject({point_id:z.string().regex(/^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/),
  branch:z.enum(['dense','sparse']),score:safe_number,score_kind:z.enum(['cosine_similarity','dot_product']),
  score_direction:z.literal('higher_is_better'),verification:z.literal('UNVERIFIED'),payload:QdrantPayloadSchema});
const qdrantCandidate=base.extend({backend:z.literal('qdrant'),score:safe_number,nomination}).refine(candidate=>{
  const n=candidate.nomination,p=n.payload;
  return ['tenant_id','collection','document_id','revision_id','generation_id','chunk_id','start_byte','end_byte','text_sha256']
    .every(key=>candidate[key as keyof typeof candidate]===p[key as keyof typeof p])
    &&candidate.score===n.score&&n.point_id===point_id(payload_tuple(p))
    &&p.dense_profile_id===p.dense_profile.profile_id&&p.sparse_profile_id===(p.sparse_profile?.profile_id??'')
    &&(n.branch==='dense'?n.score_kind==='cosine_similarity'&&n.score>=-1.000001&&n.score<=1.000001:n.score_kind==='dot_product'&&p.sparse_profile!==null);
});
const CandidateSchema = z.union([base, base.extend({score: safe_number.min(0).max(2), embedding_profile: z.enum(['fake_embedding_1536_v1','openai_te3small_1536_r1']),
  score_direction: z.literal('lower_is_better'), score_kind: z.literal('cosine_distance')}),
base.extend({score: z.literal(1), score_kind: z.literal('exact_identifier'), score_direction: z.literal('higher_is_better'),
  identifier_profile: z.literal('identifier_ascii_v1')}),qdrantCandidate]).refine(c => c.end_byte > c.start_byte && Buffer.byteLength(c.collection) <= 128);
export type CorrectiveCandidate = Readonly<z.infer<typeof CandidateSchema>>;
export type CorrectiveBackendOptions = {scope: TrustedScope; deadline: number; ledger: ExecutionLedger; signal: AbortSignal};
export interface CorrectiveBackend {
  readonly candidate_accounting?: 'outer'|'backend';
  readonly result_versions?: Readonly<{model:string|null;index:string|null}>;
  search(request: RetrievalRequest, options: CorrectiveBackendOptions & {limit: number}): Promise<unknown>;
  capture(candidates: readonly CorrectiveCandidate[], options: CorrectiveBackendOptions & {request: RetrievalRequest; max_source_bytes: number}): Promise<unknown>;
}
export type CorrectiveResponse = Readonly<{result: RetrievalResult; diagnostics: Readonly<{stop_reason: string;
  queries_executed: number; candidate_work: number; planning_fallback: boolean; ledger: ReturnType<ExecutionLedger['snapshot']>; events?: EventSnapshot & {trace_id:string}}>}>;
const SOURCE_BUDGET = 16777216;
const identityKey = (c: CorrectiveCandidate) => JSON.stringify([c.tenant_id, c.collection, c.document_id, c.revision_id, c.generation_id, c.chunk_id]);
const sourceKey = (c: {collection: string; document_id: string; revision_id: string}) => JSON.stringify([c.collection,c.document_id,c.revision_id]);
function optionsObject(value: unknown, keys: readonly string[]): Record<string, unknown> {
  try {
    if (!value || typeof value !== 'object' || Object.getPrototypeOf(value) !== Object.prototype || Object.getOwnPropertySymbols(value).length) throw new InvalidRequest();
    if (Object.entries(Object.getOwnPropertyDescriptors(value)).some(([k,d]) => !keys.includes(k) || !('value' in d) || !d.enumerable)) throw new InvalidRequest();
    return value as Record<string, unknown>;
  } catch { throw new InvalidRequest(); }
}
function checked<T>(schema: z.ZodType<T>, value: unknown): T {
  try { if (!valid_native_json(value)) throw new InvalidRequest(); return schema.parse(value); }
  catch { throw new InvalidRequest(); }
}
export class CorrectiveRetriever {
  readonly #backend: CorrectiveBackend;
  readonly #resultVersions:Readonly<{model:string|null;index:string|null}>;
  readonly #candidateAccounting:'outer'|'backend';
  readonly #policy: unknown;
  readonly #variants: unknown;
  readonly #planner: PlannerAdapter | null;
  readonly #counter: Cl100kCounter | null;
  readonly #batch: number;
  readonly #retries: number;
  readonly #backoff: number;
  readonly #noProgress: number;
  readonly #events:EventSink|null;
  constructor(options: {backend: CorrectiveBackend; policy?: unknown; variants?: unknown; planner?: PlannerAdapter | null;
    counter?: Cl100kCounter | null; event_sink?:EventSink|null; batch_size?: number; max_retries?: number; backoff_ms?: number; no_progress_limit?: number}) {
    const o = optionsObject(options, ['backend','policy','variants','planner','counter','batch_size','max_retries','backoff_ms','no_progress_limit','event_sink']);
    const b = o.backend as CorrectiveBackend;
    if (!b || typeof b.search !== 'function' || typeof b.capture !== 'function'
      || (o.planner != null && (!(o.planner instanceof PlannerAdapter) || Object.getPrototypeOf(o.planner)!==PlannerAdapter.prototype))) throw new InvalidRequest();
    const declaredAccounting=b.candidate_accounting;
    const accounting=declaredAccounting===undefined?'outer':declaredAccounting;
    if(accounting!=='outer'&&accounting!=='backend')throw new InvalidRequest();
    this.#candidateAccounting=accounting;
    const declaredVersions=b.result_versions;
    if (declaredVersions===undefined) this.#resultVersions=Object.freeze({model:null,index:null});
    else {
      const selected=optionsObject(declaredVersions,['model','index']);
      if (Object.keys(selected).length!==2) throw new InvalidRequest();
      const wire=checked(VersionsSchema,selected);
      this.#resultVersions=Object.freeze({model:wire.model,index:wire.index});
    }
    const c = checked(z.strictObject({policy: z.unknown().default(null), variants: z.array(z.unknown()).max(16).default([]),
      batch_size: integer(1,64).default(16), max_retries: integer(0,2).default(0), backoff_ms: integer(0,1000).default(0),
      no_progress_limit: integer(1,3).default(1)}), Object.fromEntries(Object.entries(o).filter(([key]) => !['backend','planner','counter','event_sink'].includes(key))));
    if (o.counter != null && (!(o.counter instanceof Cl100kCounter) || Object.getPrototypeOf(o.counter)!==Cl100kCounter.prototype)) throw new InvalidRequest();
    if(o.event_sink!=null&&(!(o.event_sink instanceof EventSink)||Object.getPrototypeOf(o.event_sink)!==EventSink.prototype))throw new InvalidRequest();
    if(o.event_sink!=null){try{EventSink.prototype.snapshot.call(o.event_sink);}catch{throw new InvalidRequest();}}
    this.#events=o.event_sink as EventSink??null;
    validate_plan({queries:[]},{query:'validation',variants:c.variants,missing_facets:[],max_subqueries:16});
    if(c.policy!==null){
      if(!c.policy||typeof c.policy!=='object'||!z.string().regex(/^[0-9a-f]{64}$/).safeParse((c.policy as Record<string,unknown>).query_sha256).success)throw new InvalidRequest();
      assess_evidence('validation',[],{...c.policy,query_sha256:createHash('sha256').update('validation').digest('hex')});
    }
    this.#backend = b; this.#policy = structuredClone(c.policy); this.#variants = structuredClone(c.variants);
    this.#planner = o.planner as PlannerAdapter ?? null; this.#counter = o.counter as Cl100kCounter ?? null; this.#batch = c.batch_size;
    this.#retries=c.max_retries;this.#backoff=c.backoff_ms;this.#noProgress=c.no_progress_limit;
  }
  async retrieve(input: unknown, options: {scope: unknown; deadline: number; signal?: AbortSignal}): Promise<CorrectiveResponse> {
    const o = optionsObject(options, ['scope','deadline','signal']);
    const request = parse_request(input), scope = parse_scope(o.scope);
    if (!safe_number.safeParse(o.deadline).success || (o.signal !== undefined && !(o.signal instanceof AbortSignal))) throw new InvalidRequest();
    const policy = structuredClone(this.#policy), variants = structuredClone(this.#variants);
    const packing = {max_tokens: request.limits.max_context_tokens, reserve: request.output_profile.envelope_reserve_tokens,
      counting_mode: request.output_profile.counting_mode, counter: this.#counter};
    const ledger = new ExecutionLedger({limits: request.limits, deadline: o.deadline as number});
    const trace=this.#events?new_trace():null,started=performance.now();
    const event=(stage:EventStage,stop_reason:string|null=null)=>{
      if(!this.#events||!trace)return;
      try{const state=ledger.snapshot();EventSink.prototype.emit.call(this.#events,stage,{trace_id:trace,attempt:state.attempts,
        elapsed_ms:Math.max(0,Math.min(300000,performance.now()-started)),candidate_count:state.candidates,provider_calls:state.provider_calls,stop_reason});}catch{}
    };
    const deadline = ledger.deadline, external = o.signal as AbortSignal | undefined;
    const controller = new AbortController();
    const abort = () => controller.abort(external!.reason);
    external?.addEventListener('abort', abort, {once:true}); if (external?.aborted) abort();
    const check = () => { controller.signal.throwIfAborted(); if (performance.now()/1000 >= deadline) throw new DeadlineExceeded(); };
    const bounded = async <T>(callback: () => Promise<T>): Promise<T> => {
      check(); let timer: ReturnType<typeof setTimeout> | undefined, listener: (() => void) | undefined;
      try {
        const boundary = new Promise<never>((_,reject) => {
          timer = setTimeout(() => { reject(new DeadlineExceeded()); controller.abort(); }, Math.max(0,(deadline-performance.now()/1000)*1000));
          listener = () => reject(controller.signal.reason); controller.signal.addEventListener('abort',listener,{once:true});
        });
        const value = await Promise.race([Promise.resolve().then(() => {check(); return callback();}),boundary]); check(); return value;
      } finally { if (timer !== undefined) clearTimeout(timer); if (listener) controller.signal.removeEventListener('abort',listener); }
    };
    const backendOptions = {scope,deadline,ledger,signal:controller.signal};
    const retained = new Map<string, CorrectiveCandidate>();
    const queryKey=(query:string)=>query.replace(/[A-Z]/g,c=>c.toLowerCase()).replace(/[ \t\r\n\f\v]+/g,' ').replace(/^ | $/g,'');
    const executed=new Set<string>(), batchHistory=new Set<string>();
    let repeatedCandidates=false, terminalCaptureBudget=false;
    const pause=async()=>{
      if(!this.#backoff)return;
      await bounded(()=>new Promise<void>((resolve,reject)=>{
        const done=()=>{clearTimeout(timer);controller.signal.removeEventListener('abort',cancel);resolve();};
        const cancel=()=>{clearTimeout(timer);controller.signal.removeEventListener('abort',cancel);reject(controller.signal.reason);};
        const timer=setTimeout(done,this.#backoff);controller.signal.addEventListener('abort',cancel,{once:true});
      }));
    };
    let queries = 0, loaded = 0, degraded = false, stale = false, captureBudget = false, planningFallback = false;
    let packed: AssessedEvidence;
    const currentStatus = (): AssessedEvidence['status'] => packed.status;
    const capture = async () => {
      if(terminalCaptureBudget)return;
      event('capture');
      const remaining = SOURCE_BUDGET-loaded;
      let raw:unknown;
      try{raw=await bounded(()=>this.#backend.capture(deep_freeze([...retained.values()]),{...backendOptions,request,max_source_bytes:remaining}));}
      catch(error){
        if(!(error instanceof BudgetExhausted))throw error;
        captureBudget=true;terminalCaptureBudget=true;ledger.close();
        packed=await bounded(()=>pack_and_assess(request.query,[],[],{...packing,deadline,signal:controller.signal,policy,rebalance:true}));
        return;
      }
      try {
        const response = checked(z.strictObject({evidence:z.array(EvidenceSchema).max(64),sources:z.array(z.unknown()).max(64),
          source_bytes:integer(0,remaining),stale:z.boolean(),budget_exhausted:z.boolean()}),raw);
        const refs = [...retained.values()], keys = new Set(refs.map(sourceKey));
        for (const e of response.evidence) if (!refs.some(c => c.collection===e.collection && c.document_id===e.document_id && c.revision_id===e.revision_id
          && c.chunk_id===e.chunk_id && c.start_byte===e.start_byte && c.end_byte===e.end_byte && c.text_sha256===e.text_sha256)) throw new IntegrityViolation();
        let bytes=0; const sourceKeys=new Set<string>();
        for (const source of response.sources) {
          if (!source || typeof source!=='object' || !keys.has(sourceKey(source as {collection:string;document_id:string;revision_id:string}))
            || typeof (source as {text?: unknown}).text !== 'string') throw new IntegrityViolation();
          const key=sourceKey(source as {collection:string;document_id:string;revision_id:string});
          if(sourceKeys.has(key))throw new IntegrityViolation();sourceKeys.add(key);
          bytes+=Buffer.byteLength((source as {text:string}).text);
        }
        if (bytes>response.source_bytes) throw new IntegrityViolation();
        loaded+=response.source_bytes; stale ||=response.stale; captureBudget ||=response.budget_exhausted;
        packed = await bounded(() => pack_and_assess(request.query,response.evidence,response.sources,{...packing,deadline,signal:controller.signal,policy,rebalance:true}));
      } catch(error) { if (error instanceof InvalidRequest) throw new IntegrityViolation(); throw error; }
    };
    const search = async (query: string): Promise<boolean> => {
      let failure:ProviderUnavailable|undefined;
      for(let retry=0;retry<=this.#retries;retry++){
        check();
        const state=ledger.snapshot(), limit=Math.min(this.#batch,request.limits.max_candidates-state.candidates,64-retained.size);
        if(limit<=0){if(failure)throw failure;return false;}
        let token;
        try{token=ledger.reserve({attempts:1,candidates:this.#candidateAccounting==='backend'?0:limit});}
        catch(error){if(error instanceof BudgetExhausted){if(failure)throw failure;return false;}throw error;}
        try{ledger.dispatch(token);}catch(error){ledger.abandon(token);throw error;}
        if(!executed.has(queryKey(query))){executed.add(queryKey(query));queries++;}
        event('search');
        const candidateStart=ledger.snapshot().candidates;
        try{
          const raw=await bounded(()=>this.#backend.search(deep_freeze({...request,query}),{...backendOptions,limit}));
          if(this.#candidateAccounting==='backend'&&ledger.snapshot().candidates-candidateStart!==limit)throw new IntegrityViolation();
          let batch;
          try{batch=checked(z.strictObject({candidates:z.array(CandidateSchema).max(limit),degraded:z.boolean()}),raw);}
          catch{throw new IntegrityViolation();}
          const seen=new Set<string>();
          for(const c of batch.candidates){const key=identityKey(c);if(seen.has(key)||c.tenant_id!==scope.tenant_id||c.collection!==request.collection)throw new IntegrityViolation();seen.add(key);}
          const batchKey=JSON.stringify([...seen].sort());repeatedCandidates=batchHistory.has(batchKey);batchHistory.add(batchKey);
          for(const c of batch.candidates)if(!retained.has(identityKey(c)))retained.set(identityKey(c),deep_freeze(c));
          degraded ||=batch.degraded;ledger.reconcile(token);token=undefined;
        }catch(error){
          if(error instanceof BudgetExhausted){if(failure)throw failure;return false;}
          if(!(error instanceof ProviderUnavailable))throw error;
          failure=error;if(retry>=this.#retries)throw error;
        }finally{if(token)ledger.abandon(token);}
        if(failure&&token){event('retry');await pause();continue;}
        await capture();return true;
      }
      throw failure ?? new ProviderUnavailable();
    };
    try {
      event('start');check();
      if (request.output_profile.renderer !== 'cragkit.context.v2') throw new UnsupportedCapability();
      const seed = assess_evidence(request.query, [], policy);
      validate_plan({queries: []}, {query: request.query, variants, missing_facets: seed.facets.filter(f => f.required && f.state !== 'supported').map(f => f.facet_id), max_subqueries: request.limits.max_subqueries});
      if (request.output_profile.counting_mode === 'strict' && request.output_profile.tokenizer !== 'cl100k_base') throw new UnsupportedCapability();
      count_context([], packing);
      let reason='plan_complete';
      if(!await search(request.query)){reason='budget_exhausted';await capture();}
      else if(packed!.status==='sufficient')reason='sufficient';
      else if(captureBudget)reason='budget_exhausted';
      else if(ledger.snapshot().candidates>=request.limits.max_candidates||retained.size>=64)reason='budget_exhausted';
      else if(ledger.snapshot().attempts>=request.limits.max_attempts)reason='attempts_exhausted';
      else if(queries>=request.limits.max_subqueries)reason='subqueries_exhausted';
      else {
        const missing=() => packed!.facets.filter(f=>f.required&&f.state!=='supported').map(f=>f.facet_id);
        let selected:readonly ApprovedVariant[]=[];
        let supported=packed!.facets.filter(f=>f.required&&f.state==='supported').length,noProgress=0;
        if(this.#planner && (variants as unknown[]).length && request.limits.max_subqueries>1){
          try {
            event('planning');
            const plan=await bounded(()=>this.#planner!.plan({query:request.query,variants,missing_facets:missing(),max_subqueries:request.limits.max_subqueries,ledger,deadline,signal:controller.signal}));
            selected=validate_plan({queries:plan.queries.map(v=>({facet_id:v.facet_id,variant_id:v.variant_id}))},{query:request.query,variants,missing_facets:missing(),max_subqueries:request.limits.max_subqueries});planningFallback=plan.fallback;
            await capture();
            supported=packed!.facets.filter(f=>f.required&&f.state==='supported').length;
            if(currentStatus()==='sufficient')reason='sufficient';
            else if(captureBudget)reason='budget_exhausted';
          }catch(error){if(error instanceof BudgetExhausted){reason='budget_exhausted';await capture();}else throw error;}
        }
        if(reason!=='budget_exhausted'&&reason!=='sufficient'){
          if(!selected.length)reason=policy===null?'coverage_unknown':'no_plan';
          for(const variant of selected){
            if(!missing().includes(variant.facet_id))continue;
            if(executed.has(queryKey(variant.query))){reason='repeated_query';break;}
            if(queries>=request.limits.max_subqueries){reason='subqueries_exhausted';break;}
            if(ledger.snapshot().attempts>=request.limits.max_attempts){reason='attempts_exhausted';break;}
            if(!await search(variant.query)){reason='budget_exhausted';await capture();break;}
            if(currentStatus()==='sufficient'){reason='sufficient';break;}
            if(captureBudget){reason='budget_exhausted';break;}
            if(repeatedCandidates){reason='repeated_candidates';break;}
            const nextSupported=packed!.facets.filter(f=>f.required&&f.state==='supported').length;
            noProgress=nextSupported>supported?0:noProgress+1;supported=nextSupported;
            if(noProgress>=this.#noProgress){reason='no_progress';break;}
          }
        }
      }
      const p=packed!, usage=ledger.snapshot();
      const limitations:{code:'coverage_unknown'|'incomplete_facets'|'stale_evidence'|'truncated_evidence'|'budget_exhausted'|'degraded_search'}[]=[];
      if(p.facets.some(f=>f.required&&f.state==='unknown'))limitations.push({code:'coverage_unknown'});
      if(p.facets.some(f=>f.required&&f.state!=='supported'))limitations.push({code:'incomplete_facets'});
      if(degraded)limitations.push({code:'degraded_search'});
      if(stale)limitations.push({code:'stale_evidence'});if(p.omitted_count)limitations.push({code:'truncated_evidence'});
      if(captureBudget||reason==='budget_exhausted'||p.omitted_count)limitations.push({code:'budget_exhausted'});
      let result:RetrievalResult;
      try {result=ResultSchema.parse({request_id:request.request_id,status:p.status,execution:degraded?'degraded':'complete',evidence:p.evidence,facets:p.facets,context:p.context,limitations,
        usage:{attempt_count:usage.attempts,provider_calls:usage.provider_calls,provider_input_tokens:usage.input_tokens,provider_output_tokens:usage.output_tokens,cost_usd:usage.cost_usd,cost_kind:usage.cost_kind,
          context_tokens:p.context_tokens,context_counting:p.counting_mode},versions:{engine:version,policy:p.policy,model:this.#resultVersions.model,index:this.#resultVersions.index,tokenizer:p.tokenizer}});}catch{throw new IntegrityViolation();}
      check();
      event('stop',reason);
      const events=this.#events&&trace?{trace_id:trace,...EventSink.prototype.snapshot.call(this.#events)}:null;
      return deep_freeze({result,diagnostics:{...(events?{events}:{}),stop_reason:reason,queries_executed:queries,candidate_work:usage.candidates,planning_fallback:planningFallback,ledger:usage}});
    } catch(error){
      if(!(error instanceof DeadlineExceeded)&&(external?.aborted||(error instanceof Error&&error.name==='AbortError')))event('cancelled','cancelled');
      else event('error',error instanceof CragkitError?error.code:'provider_unavailable');
      throw error;
    } finally {ledger.close();external?.removeEventListener('abort',abort);controller.abort();}
  }
}
