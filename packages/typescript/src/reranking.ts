import { z } from 'zod';
import { deep_freeze, text } from './shared.js';
import { CragkitError, ContextBudgetTooSmall, DeadlineExceeded, EmbeddingProfileMismatch,
  IndexNotReady, IntegrityViolation, InvalidRequest, ProviderUnavailable, UnauthorizedScope,
  UnsupportedCapability } from './errors.js';

const transportErrors = [InvalidRequest, UnauthorizedScope, UnsupportedCapability,
  IndexNotReady, EmbeddingProfileMismatch, ProviderUnavailable, DeadlineExceeded,
  ContextBudgetTooSmall, IntegrityViolation];

export const RerankProfileSchema = z.strictObject({
  profile_id: text(256), provider: text(256), model: text(256), model_revision: text(256),
  score_kind: text(256), score_direction: z.enum(['higher_is_better', 'lower_is_better']),
  preprocessing_revision: text(256), truncation_policy: z.enum(['reject', 'utf8_prefix']),
}).transform(deep_freeze);
export type RerankProfile = z.infer<typeof RerankProfileSchema>;
export const FAKE_RERANK_PROFILE = RerankProfileSchema.parse({ profile_id: 'fake_reranker_v1', provider: 'fake', model: 'synthetic-recorded-reranker', model_revision: 'synthetic-r1', score_kind: 'synthetic_raw_logit', score_direction: 'higher_is_better', preprocessing_revision: 'utf8-prefix-r1', truncation_policy: 'reject' });
const CandidateSchema = z.strictObject({ candidate_id: text(512, false).refine(value => value.length > 0), text: z.string().refine(value => !/[\uD800-\uDFFF]/u.test(value)) });
const ScoreSchema = z.strictObject({ candidate_id: text(512, false).refine(value => value.length > 0), raw_score: z.number().finite() });
export type RerankCandidate = z.infer<typeof CandidateSchema>;
export type RerankScore = z.infer<typeof ScoreSchema>;
export type RerankResult = Readonly<{ profile: RerankProfile; order: readonly string[]; scores: readonly Readonly<RerankScore>[]; truncations: readonly Readonly<{ candidate_id: string; original_bytes: number; view_bytes: number }>[]; degraded: boolean; provider_calls: number; synthetic: boolean }>;
export type RerankTransport = (body: Uint8Array, options: { deadline: number; signal: AbortSignal; max_response_bytes: number }) => Promise<Uint8Array>;
export interface RerankOptions { deadline: number; signal?: AbortSignal; max_provider_calls?: number; allow_fallback?: boolean }

// Inspect descriptors before schema access so getters and custom prototypes cannot run.
function native(value: unknown, seen = new Set<object>(), depth = 0): boolean {
  if (depth > 8) return false;
  if (value === null || typeof value === 'boolean') return true;
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value === 'string') return value.length <= 262144 && !/[\uD800-\uDFFF]/u.test(value);
  if (typeof value !== 'object' || seen.has(value)) return false;
  if (Object.getPrototypeOf(value) !== (Array.isArray(value) ? Array.prototype : Object.prototype) && Object.getPrototypeOf(value) !== null) return false;
  if (Object.getOwnPropertySymbols(value).length) return false;
  let fields = 0;
  for (const key in value) { if (Object.hasOwn(value, key) && ++fields > 128) return false; }
  const descriptors = Object.getOwnPropertyDescriptors(value);
  if (Object.keys(descriptors).length > 128) return false;
  if (Array.isArray(value) && (value.length > 40 || Object.keys(value).length !== value.length)) return false;
  seen.add(value);
  try { return Object.entries(descriptors).every(([key, descriptor]) => Array.isArray(value) && key === 'length' || ('value' in descriptor && descriptor.enumerable && native(descriptor.value, seen, depth + 1))); }
  finally { seen.delete(value); }
}
function checked<T>(schema: z.ZodType<T>, value: unknown): T {
  try { if (!native(value)) throw new Error(); return schema.parse(value); } catch { throw new InvalidRequest(); }
}
function aborted(): Error { const error = new Error('Operation aborted.'); error.name = 'AbortError'; return error; }
function check(deadline: number, signal?: AbortSignal): void {
  if (signal?.aborted) throw aborted();
  if (performance.now() / 1000 >= deadline) throw new DeadlineExceeded();
}
// Parse bounded JSON while rejecting duplicate object keys before they are lost.
function responseJSON(source: string): unknown {
  JSON.parse(source);
  let cursor = 0;
  const space = () => { while (cursor < source.length && /\s/.test(source[cursor])) cursor++; };
  const string = () => {
    const start = cursor++;
    while (source[cursor] !== '"') { if (source[cursor] === '\\') cursor++; cursor++; }
    cursor++;
    return JSON.parse(source.slice(start, cursor)) as string;
  };
  function value(depth = 0): unknown {
    if (depth > 8) throw new Error();
    space();
    if (source[cursor] === '"') return string();
    if (source[cursor] === '{') {
      cursor++; space(); const object: Record<string, unknown> = Object.create(null);
      if (source[cursor] === '}') { cursor++; return object; }
      for (;;) { space(); const key = string(); space(); cursor++; if (Object.hasOwn(object, key)) throw new Error(); object[key] = value(depth + 1); space(); if (source[cursor++] === '}') return object; }
    }
    if (source[cursor] === '[') {
      cursor++; space(); const array: unknown[] = [];
      if (source[cursor] === ']') { cursor++; return array; }
      for (;;) { array.push(value(depth + 1)); if (array.length > 40) throw new Error(); space(); if (source[cursor++] === ']') return array; }
    }
    const start = cursor; while (cursor < source.length && !/[\s,\]}]/.test(source[cursor])) cursor++;
    const token = source.slice(start, cursor);
    if (token.length > 128) throw new Error();
    return token === 'null' ? null : token === 'true' ? true : token === 'false' ? false : Number(token);
  }
  return value();
}

export class RerankingAdapter {
  readonly profile: RerankProfile;
  private readonly allow_live: boolean;
  private readonly transport: RerankTransport;
  private inflight = false;
  constructor(transport: RerankTransport, options: { profile?: RerankProfile; allow_live?: boolean } = {}) {
    const parsed = checked(z.strictObject({ profile: RerankProfileSchema.optional(), allow_live: z.boolean().optional() }), options);
    if (typeof transport !== 'function') throw new InvalidRequest();
    this.transport = transport; this.profile = parsed.profile ?? FAKE_RERANK_PROFILE; this.allow_live = parsed.allow_live ?? false;
    Object.defineProperty(this, 'profile', { writable: false, configurable: false });
  }
  async rank(query: string, candidates: readonly RerankCandidate[], options: RerankOptions): Promise<RerankResult> {
    // AbortSignal is a native control object, kept outside the JSON boundary.
    let deadline: number, signal: AbortSignal | undefined, allowance: number, fallback: boolean;
    try {
      if (!options || Object.getPrototypeOf(options) !== Object.prototype || Object.getOwnPropertySymbols(options).length) throw new Error();
      const descriptors = Object.getOwnPropertyDescriptors(options);
      if (Object.entries(descriptors).some(([key, descriptor]) => !['deadline', 'signal', 'max_provider_calls', 'allow_fallback'].includes(key) || !('value' in descriptor) || !descriptor.enumerable)) throw new Error();
      deadline = options.deadline; signal = options.signal; allowance = options.max_provider_calls === undefined ? 1 : options.max_provider_calls; fallback = options.allow_fallback === undefined ? false : options.allow_fallback;
      if (typeof deadline !== 'number' || !Number.isFinite(deadline) || signal !== undefined && !(signal instanceof AbortSignal) || typeof allowance !== 'number' || !Number.isInteger(allowance) || allowance < 0 || allowance > 1000 || typeof fallback !== 'boolean') throw new Error();
    } catch { throw new InvalidRequest(); }
    check(deadline, signal);
    if (this.inflight) throw new InvalidRequest();
    checked(RerankProfileSchema, this.profile);
    const question = checked(text(8192), query);
    const snapshot = checked(z.array(CandidateSchema).max(40), candidates);
    if (new Set(snapshot.map(item => item.candidate_id)).size !== snapshot.length) throw new InvalidRequest();
    let total = Buffer.byteLength(question, 'utf8');
    const truncations: { candidate_id: string; original_bytes: number; view_bytes: number }[] = [];
    const views = snapshot.map(item => {
      const original_bytes = Buffer.byteLength(item.text, 'utf8');
      if (original_bytes > 262144) throw new InvalidRequest();
      let view = item.text;
      if (original_bytes > 16384) {
        if (this.profile.truncation_policy !== 'utf8_prefix') throw new InvalidRequest();
        let bytes = 0; view = '';
        for (const character of item.text) { const size = Buffer.byteLength(character, 'utf8'); if (bytes + size > 16384) break; view += character; bytes += size; }
        truncations.push({ candidate_id: item.candidate_id, original_bytes, view_bytes: bytes });
      }
      total += Buffer.byteLength(view, 'utf8');
      if (total > 262144) throw new InvalidRequest();
      return { candidate_id: item.candidate_id, text: view };
    });
    const result = (scores: RerankScore[], degraded: boolean, provider_calls: number): RerankResult => {
      const order = [...scores].sort((a, b) => (this.profile.score_direction === 'higher_is_better' ? b.raw_score - a.raw_score : a.raw_score - b.raw_score)).map(item => item.candidate_id);
      return deep_freeze({ profile: this.profile, order: degraded ? snapshot.map(item => item.candidate_id) : order, scores, truncations, degraded, provider_calls, synthetic: this.profile.provider === 'fake' });
    };
    check(deadline, signal);
    if (!snapshot.length) return result([], false, 0);
    if (!allowance) throw new InvalidRequest();
    if (this.profile.provider !== 'fake' && !this.allow_live) throw new UnsupportedCapability();
    const body = new TextEncoder().encode(JSON.stringify({ query: question, candidates: views, profile: this.profile }));
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let rejectControl: (reason: unknown) => void = () => {};
    const control = new Promise<never>((_, reject) => { rejectControl = reject; });
    const cancel = (error: Error) => { controller.abort(error); rejectControl(error); };
    const onAbort = () => cancel(aborted());
    signal?.addEventListener('abort', onAbort, { once: true });
    const schedule = () => { const remaining = (deadline - performance.now() / 1000) * 1000; if (remaining <= 0) cancel(new DeadlineExceeded()); else timer = setTimeout(schedule, Math.min(remaining, 2147483647)); };
    this.inflight = true;
    let settled = false;
    const pending = Promise.resolve().then(() => { check(deadline, signal); return this.transport(body, { deadline, signal: controller.signal, max_response_bytes: 65536 }); }).finally(() => { settled = true; this.inflight = false; });
    schedule();
    try {
      let raw: unknown;
      let transportFailure: (new () => CragkitError) | undefined;
      let fallbackEligible = false;
      let transportCancelled = false;
      try { raw = await Promise.race([pending, control]); }
      catch (error) {
        transportCancelled = error instanceof Error && error.name === 'AbortError'
          || error instanceof DOMException && error.name === 'AbortError';
        if (!transportCancelled) {
          fallbackEligible = error instanceof ProviderUnavailable || error instanceof UnsupportedCapability;
          transportFailure = transportErrors.find(kind => error instanceof kind) ?? ProviderUnavailable;
        }
      }
      check(deadline, signal);
      // Preserve classification and declared fallback, never provider error objects.
      if (transportCancelled) throw aborted();
      if (transportFailure) {
        if (fallback && fallbackEligible) { const recovered = result([], true, 1); check(deadline, signal); return recovered; }
        throw new transportFailure();
      }
      let scores: RerankScore[];
      try {
        if (!(raw instanceof Uint8Array) || raw.byteLength > 65536) throw new Error();
        const parsed = responseJSON(new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(raw));
        if (!native(parsed)) throw new Error();
        scores = z.array(ScoreSchema).length(snapshot.length).parse(parsed);
        const mapping = new Map(scores.map(item => [item.candidate_id, item]));
        if (mapping.size !== snapshot.length || snapshot.some(item => !mapping.has(item.candidate_id))) throw new Error();
        scores = snapshot.map(item => mapping.get(item.candidate_id)!);
      } catch { throw new IntegrityViolation(); }
      check(deadline, signal);
      const ranked = result(scores, false, 1);
      check(deadline, signal);
      return ranked;
    } finally {
      if (timer !== undefined) clearTimeout(timer);
      signal?.removeEventListener('abort', onAbort);
      // An uncooperative injected operation retains the sole slot until settlement.
      if (settled) this.inflight = false;
    }
  }
}
