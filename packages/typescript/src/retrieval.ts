/** Minimal lexical evidence assembly; coverage and model-token counts remain estimates. */
import { configuration, select, profile_snapshot, type RetrieverOptions } from './hybrid.js';
import { PoolResource, check_options, now, type LeaseOptions } from './postgres-pool.js';
import { PostgresSession } from './postgres-session.js';
import { parse_request, parse_scope, type RetrievalRequest, type TrustedScope } from './contracts.js';
import { parse_result, type Evidence, type RetrievalResult } from './results.js';
import { deep_freeze } from './shared.js';
import { ContextBudgetTooSmall, IntegrityViolation, UnsupportedCapability } from './errors.js';

export class PostgresRetriever {
  private readonly config: ReturnType<typeof configuration>;
  constructor(private readonly resource: PoolResource, options: RetrieverOptions = {}) { this.config = configuration(options); }
  async retrieve(input: RetrievalRequest, options: LeaseOptions & {scope: TrustedScope}): Promise<RetrievalResult> {
    const started = now();
    check_options(options);
    const request = parse_request(input);
    const scope = parse_scope(options.scope);
    const profile = request.output_profile;
    if (profile.renderer !== 'cragkit.context.v1' || profile.counting_mode !== 'estimated' || profile.tokenizer !== null) throw new UnsupportedCapability();
    if (profile.envelope_reserve_tokens >= request.limits.max_context_tokens) throw new ContextBudgetTooSmall();
    const deadline = Math.min(options.deadline, started + request.limits.deadline_ms / 1000);
    const bound = {scope, deadline, signal:options.signal};
    check_options(bound);
    const session = new PostgresSession(this.resource);
    const selection = this.config.mode === 'lexical' ? null : await select(session,request,bound,this.config,profile_snapshot(this.config.embedder!));
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
      usage:{attempt_count:1,provider_calls:selection?1:0,provider_input_tokens:selection?selection.input_tokens:0,provider_output_tokens:0,cost_usd:0,cost_kind:'known',
        context_tokens:Math.ceil(Buffer.byteLength(context,'utf8')/4),context_counting:'estimated',stage_durations:selection?.stages ?? []},
      versions:{engine:'0.0.0',policy:'unassessed.v0',model:selection?'fake_embedding_model_v1':null,tokenizer:null,index:selection?(this.config.mode==='dense'?'dense_fake.v1':'hybrid_rrf.v1'):'native_fts.v1'}}); } catch { throw new IntegrityViolation(); }
    check_options(bound);
    return deep_freeze(result);
  }
}
