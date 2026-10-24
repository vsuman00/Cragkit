/** Internal HY-r1 configuration and bounded candidate orchestration. */
import { isDeepStrictEqual } from 'node:util';
import { EmbeddingAdapter, EmbeddingProfileSchema, FAKE_PROFILE, type EmbeddingBatch } from './embeddings.js';
import { CandidateCleanupFailure, dense_batch, type PostgresSession, type LexicalCandidate, type DenseCandidate, type IdentifierCandidate } from './postgres-session.js';
import { fuse } from './fusion.js';
import { extract_identifiers } from './identifiers.js';
import { valid_native_json } from './shared.js';
import { bounded, check_options, now, type LeaseOptions } from './postgres-pool.js';
import type { RetrievalRequest, TrustedScope } from './contracts.js';
import { EmbeddingProfileMismatch, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnsupportedCapability } from './errors.js';
export interface RetrieverOptions { mode?: 'lexical'|'dense'|'hybrid'; embedder?: EmbeddingAdapter; allow_degraded?: boolean; identifiers?: boolean }
export function configuration(input: RetrieverOptions): Required<Omit<RetrieverOptions,'embedder'>> & {embedder?: EmbeddingAdapter} {
  if (input === null || typeof input !== 'object' || Array.isArray(input) || ![Object.prototype,null].includes(Object.getPrototypeOf(input))) throw new InvalidRequest();
  const descriptors = Object.getOwnPropertyDescriptors(input);
  if (Object.getOwnPropertySymbols(input).length || Object.entries(descriptors).some(([key,d]) => !['mode','embedder','allow_degraded','identifiers'].includes(key) || !('value' in d) || !d.enumerable)) throw new InvalidRequest();
  const json = Object.fromEntries(Object.entries(descriptors).filter(([key])=>key!=='embedder').map(([key,d])=>[key,d.value]));
  if (!valid_native_json(json) || (Object.hasOwn(json,'mode') && typeof json.mode !== 'string') || ['allow_degraded','identifiers'].some(key=>Object.hasOwn(json,key) && typeof json[key] !== 'boolean')) throw new InvalidRequest();
  const mode = input.mode ?? 'lexical', allow_degraded = input.allow_degraded ?? false, identifiers = input.identifiers ?? true;
  if (!['lexical','dense','hybrid'].includes(mode) || typeof allow_degraded !== 'boolean' || typeof identifiers !== 'boolean'
    || (Object.hasOwn(input,'mode') && input.mode === undefined) || (Object.hasOwn(input,'embedder') && !(input.embedder instanceof EmbeddingAdapter))
    || (mode === 'lexical' ? input.embedder !== undefined || allow_degraded : !(input.embedder instanceof EmbeddingAdapter))
    || (mode === 'dense' && allow_degraded)) throw new InvalidRequest();
  return Object.freeze({mode,allow_degraded,identifiers,embedder:input.embedder});
}
export function profile_snapshot(embedder: EmbeddingAdapter) {
  let snapshot;
  try { snapshot = EmbeddingProfileSchema.parse(embedder.profile); } catch { throw new InvalidRequest(); }
  if (!isDeepStrictEqual(snapshot,FAKE_PROFILE)) throw new EmbeddingProfileMismatch();
  return snapshot;
}
type Candidate = LexicalCandidate|DenseCandidate|IdentifierCandidate;
export async function select(session: PostgresSession, request: RetrievalRequest, bound: LeaseOptions & {scope:TrustedScope}, config:ReturnType<typeof configuration>, snapshot: ReturnType<typeof profile_snapshot>) {
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
  let start = now();
  try {
    const raw = await bounded(config.embedder!.embed_query(request.query,bound),bound);
    check_options(bound);
    batch = dense_batch(raw);
    if (!isDeepStrictEqual(batch.profile,snapshot)) throw new EmbeddingProfileMismatch();
    const usage = batch.usage;
    if ([usage.prompt_tokens,usage.total_tokens].some(value=>value !== null && (!Number.isSafeInteger(value) || value < 0))
      || (usage.prompt_tokens !== null && usage.total_tokens !== null && usage.total_tokens < usage.prompt_tokens)
      || usage.cost_kind !== 'known' || usage.cost_usd !== 0 || !batch.synthetic) throw new InvalidRequest();
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
  return {candidates:candidates.slice(0,65),truncated:candidates.length>64,degraded,stages,input_tokens:batch?.usage.prompt_tokens ?? null};
}
