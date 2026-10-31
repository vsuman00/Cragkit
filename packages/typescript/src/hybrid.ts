/** Internal HY-r1 configuration and bounded candidate orchestration. */
import { createHash } from 'node:crypto';
import { Cl100kCounter } from './context.js';
import { RerankingAdapter } from './reranking.js';
import { assess_evidence } from './assessment.js';
import { isDeepStrictEqual } from 'node:util';
import { EmbeddingAdapter, EmbeddingProfileSchema, FAKE_PROFILE, type EmbeddingBatch, type EmbeddingProfile, type EmbeddingUsage } from './embeddings.js';
import { snapshot_profile } from './postgres-profiles.js';
import { CandidateCleanupFailure, dense_batch, type PostgresSession, type LexicalCandidate, type DenseCandidate, type IdentifierCandidate } from './postgres-session.js';
import { fuse } from './fusion.js';
import { extract_identifiers } from './identifiers.js';
import { deep_freeze, valid_native_json } from './shared.js';
import { bounded, check_options, now, type LeaseOptions } from './postgres-pool.js';
import type { RetrievalRequest, TrustedScope } from './contracts.js';
import { EmbeddingProfileMismatch, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability } from './errors.js';
export type EvidenceConfiguration = Readonly<{policy: unknown; counter: Cl100kCounter | null; rebalance: boolean; surrounding_bytes: number; reranker: RerankingAdapter | null; rerank_fallback: boolean; rerank_limit: number}>;
export interface RetrieverOptions { mode?: 'lexical'|'dense'|'hybrid'; embedding_profile?: EmbeddingProfile; embedder?: EmbeddingAdapter; allow_degraded?: boolean; identifiers?: boolean; evidence_options?: Partial<EvidenceConfiguration> | null }
function evidence_configuration(input: unknown): EvidenceConfiguration | null {
  if (input === null) return null;
  if (!input || typeof input !== 'object' || Object.getPrototypeOf(input) !== Object.prototype || Object.getOwnPropertySymbols(input).length) throw new InvalidRequest();
  const fields = Object.getOwnPropertyDescriptors(input);
  if (Object.entries(fields).some(([key, field]) => !['policy','counter','rebalance','surrounding_bytes','reranker','rerank_fallback','rerank_limit'].includes(key) || !('value' in field) || !field.enumerable || field.value === undefined)) throw new InvalidRequest();
  const value = input as Partial<EvidenceConfiguration>;
  const policy = value.policy ?? null, counter = value.counter ?? null, reranker = value.reranker ?? null;
  if (!valid_native_json(policy) || counter !== null && !(counter instanceof Cl100kCounter) || reranker !== null && !(reranker instanceof RerankingAdapter)
    || value.rebalance !== undefined && typeof value.rebalance !== 'boolean' || value.rerank_fallback !== undefined && typeof value.rerank_fallback !== 'boolean'
    || value.rerank_limit !== undefined && (!Number.isSafeInteger(value.rerank_limit) || value.rerank_limit < 1 || value.rerank_limit > 40)
    || value.surrounding_bytes !== undefined && (!Number.isSafeInteger(value.surrounding_bytes) || value.surrounding_bytes < 0 || value.surrounding_bytes > 4096)) throw new InvalidRequest();
  const snapshot = structuredClone(policy) as Record<string,unknown> | null;
  if (snapshot !== null) {
    if (typeof snapshot !== 'object' || Array.isArray(snapshot) || typeof snapshot.query_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(snapshot.query_sha256)) throw new InvalidRequest();
    assess_evidence('configuration', [], {...snapshot, query_sha256:createHash('sha256').update('configuration').digest('hex')});
  }
  return Object.freeze({policy:deep_freeze(snapshot),counter,reranker,rebalance:value.rebalance ?? false,surrounding_bytes:value.surrounding_bytes ?? 256,rerank_fallback:value.rerank_fallback ?? false,rerank_limit:value.rerank_limit ?? 40});
}
export function configuration(input: RetrieverOptions): {mode:'lexical'|'dense'|'hybrid'; allow_degraded:boolean; identifiers:boolean; embedder?:EmbeddingAdapter; embedding_profile:EmbeddingProfile; evidence_options:EvidenceConfiguration|null} {
  if (input === null || typeof input !== 'object' || Array.isArray(input) || ![Object.prototype,null].includes(Object.getPrototypeOf(input))) throw new InvalidRequest();
  const descriptors = Object.getOwnPropertyDescriptors(input);
  if (Object.getOwnPropertySymbols(input).length || Object.entries(descriptors).some(([key,d]) => !['mode','embedder','allow_degraded','identifiers','evidence_options','embedding_profile'].includes(key) || !('value' in d) || !d.enumerable)) throw new InvalidRequest();
  const json = Object.fromEntries(Object.entries(descriptors).filter(([key])=>key!=='embedder' && key!=='evidence_options' && key!=='embedding_profile').map(([key,d])=>[key,d.value]));
  if (!valid_native_json(json) || (Object.hasOwn(json,'mode') && typeof json.mode !== 'string') || ['allow_degraded','identifiers'].some(key=>Object.hasOwn(json,key) && typeof json[key] !== 'boolean')) throw new InvalidRequest();
  const mode = input.mode ?? 'lexical', allow_degraded = input.allow_degraded ?? false, identifiers = input.identifiers ?? true;
  if (!['lexical','dense','hybrid'].includes(mode) || typeof allow_degraded !== 'boolean' || typeof identifiers !== 'boolean'
    || (Object.hasOwn(input,'mode') && input.mode === undefined) || (Object.hasOwn(input,'embedder') && !(input.embedder instanceof EmbeddingAdapter))
    || (mode === 'lexical' ? input.embedder !== undefined || allow_degraded : !(input.embedder instanceof EmbeddingAdapter))
    || (mode === 'dense' && allow_degraded)) throw new InvalidRequest();
  const selected=snapshot_profile(input.embedding_profile);
  return Object.freeze({mode,allow_degraded,identifiers,embedding_profile:selected,embedder:input.embedder,evidence_options:Object.hasOwn(input,'evidence_options')?evidence_configuration(input.evidence_options):null});
}
export function profile_snapshot(embedder: EmbeddingAdapter, selected: EmbeddingProfile = FAKE_PROFILE) {
  let snapshot;
  try { snapshot = EmbeddingProfileSchema.parse(embedder.profile); } catch { throw new InvalidRequest(); }
  if (!isDeepStrictEqual(snapshot,snapshot_profile(selected))) throw new EmbeddingProfileMismatch();
  return snapshot;
}
type Candidate = LexicalCandidate|DenseCandidate|IdentifierCandidate;
export async function select(session: PostgresSession, request: RetrievalRequest, bound: LeaseOptions & {scope:TrustedScope}, config:ReturnType<typeof configuration>, snapshot: ReturnType<typeof profile_snapshot>, on_dispatch?:()=>void, on_usage?:(usage:EmbeddingUsage)=>void) {
  const stages: {stage:string;duration_ms:number}[] = [];
  const token = config.mode === 'hybrid' && config.identifiers ? extract_identifiers(request.query)[0] : undefined;
  const families: ('dense'|'lexical'|'identifier')[] = config.mode === 'dense' ? ['dense'] : token === undefined ? ['dense','lexical'] : ['dense','lexical','identifier'];
  const cap = Math.min(request.limits.max_candidates,200);
  if (cap < families.length || request.limits.max_provider_calls < 1) throw new InvalidRequest();
  const budgets = families.map((_,index)=>Math.min(40,Math.floor(cap/families.length)+(index < cap%families.length ? 1:0)));
  let firstFailure: unknown, degraded = false, batch: EmbeddingBatch|undefined;
  const recover = (error:unknown): boolean => config.mode === 'hybrid' && config.allow_degraded && !(error instanceof CandidateCleanupFailure) && (error instanceof ProviderUnavailable || error instanceof UnsupportedCapability);
  const failed = (family:string,error:unknown,start:number): void => {
    check_options(bound);
    if (!recover(error)) throw error;
    firstFailure ??= error; degraded = true;
    stages.push({stage:`${family}_failed_${(error as ProviderUnavailable).code}`,duration_ms:Math.min(300000,(now()-start)*1000)});
  };
  const live=snapshot.provider!=='fake';
  let dispatched=0;
  if (live) {
    if (request.limits.max_spend_usd!==null) throw new UnsupportedCapability();
    await session.admit_embedding(request,bound);
  }
  let start = now();
  try {
    const raw = await bounded(config.embedder!.embed_query(request.query,live ? {...bound,on_dispatch:()=>{on_dispatch?.();dispatched++;}} : bound),bound);
    check_options(bound);
    batch = dense_batch(raw,snapshot);
    if (!isDeepStrictEqual(batch.profile,snapshot)) throw new EmbeddingProfileMismatch();
    const usage = batch.usage;
    if ([usage.prompt_tokens,usage.total_tokens].some(value=>value !== null && (!Number.isSafeInteger(value) || value < 0))
      || (usage.prompt_tokens !== null && usage.total_tokens !== null && usage.total_tokens < usage.prompt_tokens)
      || (usage.cost_usd!==null && (!Number.isFinite(usage.cost_usd)||usage.cost_usd<0))
      || (live ? !['estimated','unknown'].includes(usage.cost_kind) || batch.synthetic : usage.cost_kind !== 'known' || usage.cost_usd !== 0 || !batch.synthetic)) throw new InvalidRequest();
    if (live) on_usage?.(usage);
    stages.push({stage:'embedding_complete',duration_ms:Math.min(300000,(now()-start)*1000)});
  } catch(error) { failed('embedding',error,start); }
  const lists: {list_id:string;facet_id:string;family:'dense'|'lexical'|'identifier';weight:number;candidates:readonly Candidate[]}[] = [];
  await session.transaction(request,bound,async handle=>{
    for (let index=0;index<families.length;index++) {
      const family = families[index];
      if (family === 'dense' && !batch) continue;
      start = now();
      try {
        const candidates = await handle.candidate_branch<readonly Candidate[]>(()=>family === 'dense' ? handle.dense_candidates(batch!,{limit:budgets[index]})
          : family === 'lexical' ? handle.lexical_candidates({limit:budgets[index]}) : handle.identifier_candidates(token!,{limit:budgets[index]}));
        check_options(bound);
        if (candidates.length > budgets[index]) throw new IntegrityViolation();
        lists.push({list_id:family,facet_id:'original',family,weight:1,candidates});
        stages.push({stage:`${family}_complete`,duration_ms:Math.min(300000,(now()-start)*1000)});
      } catch(error) { failed(family,error,start); }
    }
  });
  if (!lists.length) throw firstFailure;
  const candidates = fuse(lists,{max_candidates:cap}).map(item=>item.candidate as Candidate);
  const output_tokens=live && dispatched!==0 ? batch!==undefined && batch.usage.total_tokens!==null && batch.usage.prompt_tokens!==null
    ? batch.usage.total_tokens-batch.usage.prompt_tokens : null : 0;
  return {candidates:candidates.slice(0,65),truncated:candidates.length>64,degraded,stages,input_tokens:live && dispatched===0 ? 0 : batch?.usage.prompt_tokens ?? null,
    output_tokens,provider_calls:live?dispatched:1,cost_usd:live&&dispatched?null:0,cost_kind:live&&dispatched?'unknown' as const:'known' as const};
}
