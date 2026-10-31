/** Minimal lexical evidence assembly; coverage and model-token counts remain estimates. */
import { z } from 'zod';
import { isDeepStrictEqual } from 'node:util';
import { assess_evidence } from './assessment.js';
import { count_context, render_context } from './context.js';
import { pack_and_assess } from './evidence.js';
import { source_snapshot } from './postgres-source.js';
import { RerankProfileSchema, type RerankResult } from './reranking.js';
import { configuration, select, profile_snapshot, type RetrieverOptions } from './hybrid.js';
import { PoolResource, bounded, check_options, now, type LeaseOptions } from './postgres-pool.js';
import { PostgresSession } from './postgres-session.js';
import { parse_request, parse_scope, type RetrievalRequest, type TrustedScope } from './contracts.js';
import { parse_result, type Evidence, type RetrievalResult } from './results.js';
import { deep_freeze, valid_native_json, text } from './shared.js';
import { ContextBudgetTooSmall, IntegrityViolation, InvalidRequest, UnsupportedCapability } from './errors.js';

export class PostgresRetriever {
  private readonly config: ReturnType<typeof configuration>;
  constructor(private readonly resource: PoolResource, options: RetrieverOptions = {}) { this.config = configuration(options); }
  async retrieve(input: RetrievalRequest, options: LeaseOptions & {scope: TrustedScope}): Promise<RetrievalResult> {
    const started = now();
    check_options(options);
    const request = parse_request(input);
    const scope = parse_scope(options.scope);
    if (this.config.evidence_options !== null) return this.retrieve_evidence(request, scope, options, started);
    const profile = request.output_profile;
    if (profile.renderer !== 'cragkit.context.v1' || profile.counting_mode !== 'estimated' || profile.tokenizer !== null) throw new UnsupportedCapability();
    if (profile.envelope_reserve_tokens >= request.limits.max_context_tokens) throw new ContextBudgetTooSmall();
    const deadline = Math.min(options.deadline, started + request.limits.deadline_ms / 1000);
    const bound = {scope, deadline, signal:options.signal};
    check_options(bound);
    const session = new PostgresSession(this.resource,this.config.embedding_profile);
    const selection = this.config.mode === 'lexical' ? null : await select(session,request,bound,this.config,profile_snapshot(this.config.embedder!,this.config.embedding_profile));
    const candidates = selection?.candidates ?? await session.transaction(request,bound,handle=>handle.lexical_candidates({limit:Math.min(65,request.limits.max_candidates)}));
    if (candidates.length > Math.min(65,request.limits.max_candidates)) throw new IntegrityViolation();
    const candidateKeys = new Set<string>();
    for (const candidate of candidates) {
      const key = JSON.stringify([candidate.tenant_id,candidate.collection,candidate.document_id,candidate.revision_id,candidate.generation_id,candidate.chunk_id]);
      if (candidateKeys.has(key)) throw new IntegrityViolation();
      candidateKeys.add(key);
    }
    const capacity = Math.min(262144,4*(request.limits.max_context_tokens-profile.envelope_reserve_tokens));
    const evidence: Evidence[] = [];
    const ids = new Set<string>();
    let context = '';
    let sourceRemaining = 16777216;
    let stale = false;
    let truncated = selection?.truncated ?? candidates.length > 64;
    let exhausted = false;
    if (candidates.length) await session.transaction(request,bound,async handle=>{
      for (const candidate of candidates.slice(0,64)) {
        check_options(bound);
        if (sourceRemaining === 0) { exhausted = true; break; }
        const fetched = await handle.fetch_evidence(candidate,{max_source_bytes:sourceRemaining});
        if (fetched.state === 'budget_exhausted') { exhausted = true; break; }
        if (fetched.state === 'unavailable') { stale = true; continue; }
        if (!Number.isSafeInteger(fetched.source_bytes) || fetched.source_bytes < 1 || fetched.source_bytes > sourceRemaining) throw new IntegrityViolation();
        sourceRemaining -= fetched.source_bytes;
        if (sourceRemaining < 0 || fetched.evidence === null) throw new IntegrityViolation();
        stale ||= fetched.stale;
        const item = fetched.evidence;
        if (ids.has(item.evidence_id)) throw new IntegrityViolation();
        ids.add(item.evidence_id);
        const proposed = JSON.stringify([...evidence,item]);
        if (Buffer.byteLength(proposed,'utf8') > capacity) { truncated = true; exhausted = true; continue; }
        evidence.push(item);
        context = proposed;
      }
    });
    check_options(bound);
    const limitations: {code:'coverage_unknown'|'stale_evidence'|'truncated_evidence'|'budget_exhausted'|'degraded_search'}[] = [{code:'coverage_unknown'}];
    if (selection?.degraded) limitations.push({code:'degraded_search'});
    if (stale) limitations.push({code:'stale_evidence'});
    if (truncated) limitations.push({code:'truncated_evidence'});
    if (exhausted) limitations.push({code:'budget_exhausted'});
    let result: RetrievalResult;
    try { result = parse_result({request_id:request.request_id,status:evidence.length?'partial':'insufficient',execution:selection?.degraded?'degraded':'complete',
      evidence,facets:[],context,limitations,trace_id:null,
      usage:{attempt_count:1,provider_calls:selection?selection.provider_calls:0,provider_input_tokens:selection?selection.input_tokens:0,provider_output_tokens:selection?selection.output_tokens:0,cost_usd:selection?.cost_usd??(selection?.cost_kind==='unknown'?null:0),cost_kind:selection?.cost_kind??'known',
        context_tokens:Math.ceil(Buffer.byteLength(context,'utf8')/4),context_counting:'estimated',stage_durations:selection?.stages ?? []},
      versions:{engine:'0.0.0',policy:'unassessed.v0',model:selection?this.config.embedding_profile.model:null,tokenizer:null,index:selection?(this.config.mode==='dense'?(this.config.embedding_profile.provider==='fake'?'dense_fake.v1':'dense_openai.v1'):'hybrid_rrf.v1'):'native_fts.v1'}}); } catch { throw new IntegrityViolation(); }
    check_options(bound);
    return deep_freeze(result);
  }
  private async retrieve_evidence(request: RetrievalRequest, scope: TrustedScope, options: LeaseOptions, started: number): Promise<RetrievalResult> {
    const configured = this.config.evidence_options!;
    const deadline = Math.min(options.deadline, started + request.limits.deadline_ms / 1000);
    const bound = {scope, deadline, signal:options.signal};
    check_options(bound);
    const profile = request.output_profile;
    if (profile.renderer !== 'cragkit.context.v2' || (profile.counting_mode === 'strict' ? profile.tokenizer !== 'cl100k_base' : profile.tokenizer !== null)) throw new UnsupportedCapability();
    const counting = {max_tokens:request.limits.max_context_tokens,reserve:profile.envelope_reserve_tokens,
      counting_mode:profile.counting_mode,counter:profile.counting_mode === 'strict' ? configured.counter : null};
    count_context([], counting);
    assess_evidence(request.query, [], configured.policy);
    const reranker = configured.reranker;
    let rerankProfile: ReturnType<typeof RerankProfileSchema.parse> | null = null;
    if (reranker) {
      try {
        if (!valid_native_json(reranker.profile)) throw new Error();
        rerankProfile = RerankProfileSchema.parse(reranker.profile);
        text(8192).parse(request.query);
      } catch { throw new InvalidRequest(); }
      if (rerankProfile.provider !== 'fake' && request.limits.max_spend_usd !== null) throw new UnsupportedCapability();
    }
    const reserved = (this.config.mode === 'lexical' ? 0 : 1) + (reranker ? 1 : 0);
    if (request.limits.max_provider_calls < reserved) throw new InvalidRequest();
    const session = new PostgresSession(this.resource,this.config.embedding_profile);
    const selection = this.config.mode === 'lexical' ? null : await select(session,request,bound,this.config,profile_snapshot(this.config.embedder!,this.config.embedding_profile));
    const candidates = selection?.candidates ?? await session.transaction(request,bound,handle=>handle.lexical_candidates({limit:Math.min(65,request.limits.max_candidates)}));
    if (candidates.length > Math.min(65,request.limits.max_candidates)) throw new IntegrityViolation();
    const candidateKeys = new Set<string>();
    for (const item of candidates) {
      const key = JSON.stringify([item.tenant_id,item.collection,item.document_id,item.revision_id,item.generation_id,item.chunk_id]);
      if (candidateKeys.has(key)) throw new IntegrityViolation();
      candidateKeys.add(key);
    }
    const limit = reranker ? configured.rerank_limit : 64;
    let stale = false, exhausted = false, truncated = (selection?.truncated ?? false) || candidates.length > limit;
    let sourceRemaining = 16777216;
    const stages = [...(selection?.stages ?? [])];
    type Candidate = typeof candidates[number];
    const capture = async (ordered: readonly Candidate[]) => {
      const evidence: Evidence[] = [], sources: ReturnType<typeof source_snapshot>[] = [], mapping = new Map<string,Candidate>();
      let serializedBytes = 2, viewBytes = reranker ? Buffer.byteLength(request.query) : 0;
      if (ordered.length) await session.transaction(request,bound,async handle=>{
        for (const candidate of ordered) {
          check_options(bound);
          if (sourceRemaining === 0) { exhausted = true; break; }
          const fetched = await handle.fetch_evidence(candidate,{max_source_bytes:sourceRemaining,include_source:true});
          if (fetched.state === 'budget_exhausted') { exhausted = true; break; }
          if (fetched.state === 'unavailable') { stale = true; continue; }
          if (!Number.isSafeInteger(fetched.source_bytes) || fetched.source_bytes < 1 || fetched.source_bytes > sourceRemaining || !fetched.evidence) throw new IntegrityViolation();
          sourceRemaining -= fetched.source_bytes; stale ||= fetched.stale;
          if (mapping.has(fetched.evidence.evidence_id)) throw new IntegrityViolation();
          const itemBytes = Buffer.byteLength(render_context([fetched.evidence])) - 2;
          let nextViewBytes = 0;
          if (reranker) for (const character of fetched.evidence.text) {
            const bytes = Buffer.byteLength(character); if (nextViewBytes + bytes > 16384) break; nextViewBytes += bytes;
          }
          if (serializedBytes + itemBytes + (evidence.length ? 1 : 0) > 262144 || reranker && viewBytes + nextViewBytes > 262144) {
            truncated = true; exhausted = true; continue;
          }
          serializedBytes += itemBytes + (evidence.length ? 1 : 0); viewBytes += nextViewBytes;
          evidence.push(fetched.evidence); sources.push(source_snapshot(fetched)); mapping.set(fetched.evidence.evidence_id,candidate);
        }
      });
      check_options(bound);
      return {evidence,sources,mapping};
    };
    let captured = await capture(candidates.slice(0,limit));
    let rerankCalls = 0, degraded = selection?.degraded ?? false;
    if (reranker && captured.evidence.length) {
      const start = now();
      const views = captured.evidence.map(item=>({candidate_id:item.evidence_id,text:item.text}));
      const validationViews = deep_freeze(views.map(item=>({...item})));
      const controller = new AbortController();
      const onAbort = () => controller.abort();
      bound.signal?.addEventListener('abort',onAbort,{once:true});
      let ranked: RerankResult;
      try {
        check_options(bound); rerankCalls = 1;
        const raw = await bounded(Promise.resolve().then(()=>{check_options(bound);return reranker.rank(request.query,views,{deadline,signal:controller.signal,max_provider_calls:1,allow_fallback:configured.rerank_fallback});}),bound,()=>controller.abort());
        ranked = validate_rerank(raw, validationViews, rerankProfile!, configured.rerank_fallback);
      } finally { bound.signal?.removeEventListener('abort',onAbort); }
      check_options(bound);
      degraded ||= ranked.degraded; truncated ||= ranked.truncations.length > 0;
      stages.push({stage:'reranking_complete',duration_ms:Math.min(300000,(now()-start)*1000)});
      captured = await capture(ranked.order.map(id=>captured.mapping.get(id)!));
    }
    check_options(bound);
    const packingStart = now();
    const packed = await pack_and_assess(request.query,captured.evidence,captured.sources,{...counting,deadline,signal:bound.signal,
      policy:configured.policy,rebalance:configured.rebalance,surrounding_bytes:configured.surrounding_bytes});
    check_options(bound);
    stages.push({stage:packed.rebalance_count?'packing_rebalance_complete':'packing_complete',duration_ms:Math.min(300000,(now()-packingStart)*1000)});
    if (packed.omitted_count) {truncated = true; exhausted = true;}
    const limitations: {code:'coverage_unknown'|'incomplete_facets'|'stale_evidence'|'truncated_evidence'|'budget_exhausted'|'degraded_search'}[] = [];
    if (packed.facets.some(facet=>facet.required && facet.state === 'unknown')) limitations.push({code:'coverage_unknown'});
    if (packed.facets.some(facet=>facet.required && facet.state !== 'supported')) limitations.push({code:'incomplete_facets'});
    if (degraded) limitations.push({code:'degraded_search'});
    if (stale) limitations.push({code:'stale_evidence'});
    if (truncated) limitations.push({code:'truncated_evidence'});
    if (exhausted) limitations.push({code:'budget_exhausted'});
    const live = rerankCalls > 0 && rerankProfile!.provider !== 'fake' || selection?.cost_kind==='unknown';
    let result: RetrievalResult;
    try { result = parse_result({request_id:request.request_id,status:packed.status,execution:degraded?'degraded':'complete',evidence:packed.evidence,
      context:packed.context,facets:packed.facets,limitations,trace_id:null,
      usage:{attempt_count:1,provider_calls:(selection?.provider_calls??0)+rerankCalls,provider_input_tokens:rerankCalls?null:selection?selection.input_tokens:0,
        provider_output_tokens:rerankCalls?null:selection?selection.output_tokens:0,cost_usd:live?null:0,cost_kind:live?'unknown':'known',context_tokens:packed.context_tokens,
        context_counting:packed.counting_mode,stage_durations:stages},
      versions:{engine:'0.0.0',policy:packed.policy,model:rerankProfile?.profile_id ?? (selection?this.config.embedding_profile.model:null),tokenizer:packed.tokenizer,
        index:selection?(this.config.mode==='dense'?(this.config.embedding_profile.provider==='fake'?'dense_fake.v1':'dense_openai.v1'):'hybrid_rrf.v1'):'native_fts.v1'}}); } catch { throw new IntegrityViolation(); }
    check_options(bound);
    return deep_freeze(result);
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
