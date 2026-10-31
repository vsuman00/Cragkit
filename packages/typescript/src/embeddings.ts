import { z } from 'zod';
import { deep_freeze } from './shared.js';
import { DeadlineExceeded, EmbeddingProfileMismatch, InvalidRequest, ProviderUnavailable, UnsupportedCapability } from './errors.js';

const fake = { profile_id: 'fake_embedding_1536_v1', provider: 'fake', model: 'fake_embedding_model_v1', dimensions: 1536, tokenizer: 'fake-byte-v1', normalization: 'l2' } as const;
const openai = { profile_id: 'openai_te3small_1536_r1', provider: 'openai', model: 'text-embedding-3-small', dimensions: 1536, tokenizer: 'cl100k_base', normalization: 'l2' } as const;
export const EmbeddingProfileSchema = z.strictObject({ profile_id: z.string(), provider: z.string(), model: z.string(), dimensions: z.number().int(), tokenizer: z.string(), normalization: z.string() }).refine(value => [fake, openai].some(profile => Object.entries(profile).every(([key, expected]) => value[key as keyof typeof value] === expected))).transform(deep_freeze);
export type EmbeddingProfile = z.infer<typeof EmbeddingProfileSchema>;
export const FAKE_PROFILE = deep_freeze(EmbeddingProfileSchema.parse(fake));
export const OPENAI_PROFILE = deep_freeze(EmbeddingProfileSchema.parse(openai));
const limit = (maximum: number, fallback: number) => z.number().int().positive().max(maximum).default(fallback);
export const EmbeddingLimitsSchema = z.strictObject({ max_items: limit(8, 8), max_input_bytes: limit(8192, 8192), max_batch_bytes: limit(32768, 32768), max_input_tokens: limit(8192, 2048), max_batch_tokens: limit(32768, 8192), max_response_bytes: limit(2097152, 1048576) }).transform(deep_freeze);
export type EmbeddingLimits = z.infer<typeof EmbeddingLimitsSchema>;
const costNumber = z.number().nonnegative().max(1000000);
export const EmbeddingPolicySchema = z.strictObject({ allow_live: z.boolean().default(false), max_cost_usd: costNumber.default(0), usd_per_million_tokens: costNumber.positive().nullable().default(null) }).transform(deep_freeze);
export type EmbeddingPolicy = z.infer<typeof EmbeddingPolicySchema>;
export const EmbeddingUsageSchema = z.strictObject({ prompt_tokens: z.number().int().nullable(), total_tokens: z.number().int().nullable(), cost_usd: z.number().nullable(), cost_kind: z.enum(['known', 'estimated', 'unknown']) }).transform(deep_freeze);
export type EmbeddingUsage = z.infer<typeof EmbeddingUsageSchema>;
export const EmbeddingBatchSchema = z.strictObject({ profile: EmbeddingProfileSchema, vectors: z.array(z.array(z.number()).readonly()).readonly(), usage: EmbeddingUsageSchema, provider_calls: z.literal(1).default(1), synthetic: z.boolean() }).transform(deep_freeze);
export type EmbeddingBatch = z.infer<typeof EmbeddingBatchSchema>;
export interface TokenCounter { readonly name: string; count(text: string): number }
export type EmbeddingTransport = (body: Uint8Array, options: { deadline: number; signal: AbortSignal; max_response_bytes: number }) => Promise<Uint8Array>;
export interface EmbeddingOptions { deadline: number; signal?: AbortSignal; on_dispatch?: () => void }

// Decimal coefficients keep admission exact even for subnormal configured prices.
function decimal(value: number): { coefficient: bigint; scale: number } {
  const [mantissa, exponent = '0'] = value.toString().split('e');
  const [whole, fraction = ''] = mantissa.split('.');
  return { coefficient: BigInt(whole + fraction), scale: fraction.length - Number(exponent) };
}
function exceedsCost(tokens: number, price: number, allowance: number): boolean {
  const a = decimal(price), b = decimal(allowance);
  const scale = Math.max(a.scale + 6, b.scale);
  return BigInt(tokens) * a.coefficient * 10n ** BigInt(scale - a.scale - 6) > b.coefficient * 10n ** BigInt(scale - b.scale);
}
function estimatedCost(tokens: number, price: number): number {
  const value = decimal(price);
  return Number(`${BigInt(tokens) * value.coefficient}e${-value.scale - 6}`);
}
const floatToken = Symbol('float JSON token');
type FloatToken = { [floatToken]: number };
function object(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === 'object' && !Array.isArray(value); }
function integer(value: unknown, positive = false): value is number { return typeof value === 'number' && Number.isInteger(value) && value >= (positive ? 1 : 0) && value <= 2147483647; }

// Syntax is checked first; this bounded scan preserves duplicate keys and numeric spelling.
function parseResponse(text: string): unknown {
  JSON.parse(text);
  let cursor = 0;
  const whitespace = () => { while (/\s/.test(text[cursor] ?? '') && cursor < text.length) cursor++; };
  function string(): string {
    const start = cursor++;
    while (text[cursor] !== '"') { if (text[cursor] === '\\') cursor++; cursor++; }
    cursor++;
    return JSON.parse(text.slice(start, cursor)) as string;
  }
  function value(depth = 0): unknown {
    if (depth > 32) throw new Error();
    whitespace();
    if (text[cursor] === '"') return string();
    if (text[cursor] === '{') {
      cursor++; whitespace();
      const result: Record<string, unknown> = Object.create(null);
      if (text[cursor] === '}') { cursor++; return result; }
      for (;;) {
        whitespace(); const key = string(); whitespace(); cursor++;
        if (Object.hasOwn(result, key)) throw new Error();
        result[key] = value(depth + 1); whitespace();
        if (text[cursor++] === '}') return result;
      }
    }
    if (text[cursor] === '[') {
      cursor++; whitespace(); const result: unknown[] = [];
      if (text[cursor] === ']') { cursor++; return result; }
      for (;;) { result.push(value(depth + 1)); whitespace(); if (text[cursor++] === ']') return result; }
    }
    const start = cursor;
    while (cursor < text.length && !/[\s,\]}]/.test(text[cursor])) cursor++;
    const token = text.slice(start, cursor);
    if (token === 'null') return null;
    if (token === 'true') return true;
    if (token === 'false') return false;
    if (token.length > 128) throw new Error();
    const number = Number(token);
    return /[.eE]/.test(token) ? { [floatToken]: number } : number;
  }
  return value();
}
function abortError(): Error { const error = new Error('Operation aborted.'); error.name = 'AbortError'; return error; }

export class EmbeddingAdapter {
  readonly profile: EmbeddingProfile;
  readonly limits: EmbeddingLimits;
  readonly policy: EmbeddingPolicy;
  private inflight = false;
  private readonly transport: EmbeddingTransport;
  private readonly counter: TokenCounter;
  constructor(transport: EmbeddingTransport, token_counter: TokenCounter, options: { profile?: EmbeddingProfile; limits?: z.input<typeof EmbeddingLimitsSchema>; policy?: z.input<typeof EmbeddingPolicySchema> } = {}) {
    let counterName: unknown;
    try {
      this.profile = deep_freeze(EmbeddingProfileSchema.parse(options.profile === undefined ? FAKE_PROFILE : options.profile));
      this.limits = deep_freeze(EmbeddingLimitsSchema.parse(options.limits ?? {}));
      this.policy = deep_freeze(EmbeddingPolicySchema.parse(options.policy ?? {}));
      counterName = token_counter.name;
      if (typeof transport !== 'function' || typeof counterName !== 'string' || typeof token_counter.count !== 'function') throw new Error();
    } catch { throw new InvalidRequest(); }
    if (counterName !== this.profile.tokenizer) throw new UnsupportedCapability();
    this.transport = transport; this.counter = token_counter;
  }
  private check(deadline: number, signal?: AbortSignal): void {
    if (signal?.aborted) throw abortError();
    if (performance.now() / 1000 >= deadline) throw new DeadlineExceeded();
  }
  private inputs(texts: readonly string[]): { snapshot: string[]; counted: number } {
    if (!Array.isArray(texts)) throw new InvalidRequest();
    const length = texts.length;
    if (!Number.isInteger(length) || length < 1 || length > this.limits.max_items) throw new InvalidRequest();
    const snapshot: string[] = [];
    for (let index = 0; index < length; index++) snapshot.push(texts[index]);
    let bytes = 0, counted = 0;
    for (const text of snapshot) {
      if (typeof text !== 'string' || !text.length || text.length > this.limits.max_input_bytes || /[\uD800-\uDFFF]/u.test(text)) throw new InvalidRequest();
      const size = Buffer.byteLength(text, 'utf8');
      if (size > this.limits.max_input_bytes) throw new InvalidRequest();
      let count: unknown;
      try { count = this.counter.count(text); } catch { throw new InvalidRequest(); }
      if (!integer(count, true)) throw new InvalidRequest();
      bytes += size; counted += count;
      if (count > this.limits.max_input_tokens || bytes > this.limits.max_batch_bytes || counted > this.limits.max_batch_tokens) throw new InvalidRequest();
    }
    return { snapshot, counted };
  }
  private response(raw: unknown, size: number, counted: number): EmbeddingBatch {
    let parsed: unknown;
    try {
      if (!(raw instanceof Uint8Array) || raw.byteLength > this.limits.max_response_bytes) throw new Error();
      parsed = parseResponse(new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(raw));
    } catch { throw new ProviderUnavailable(); }
    if (!object(parsed)) throw new ProviderUnavailable();
    if (parsed.model !== this.profile.model) throw new EmbeddingProfileMismatch();
    if (!Array.isArray(parsed.data) || parsed.data.length !== size) throw new ProviderUnavailable();
    const vectors: number[][] = new Array(size);
    for (const item of parsed.data) {
      if (!object(item) || !integer(item.index) || item.index >= size || vectors[item.index] !== undefined || !Array.isArray(item.embedding)) throw new ProviderUnavailable();
      if (item.embedding.length !== this.profile.dimensions) throw new EmbeddingProfileMismatch();
      const vector: number[] = [];
      for (const component of item.embedding) {
        const number = object(component) && floatToken in component ? (component as unknown as FloatToken)[floatToken] : component;
        if (typeof number !== 'number' || !Number.isFinite(number)) throw new ProviderUnavailable();
        vector.push(number);
      }
      const norm = Math.sqrt(vector.reduce((sum, number) => sum + number * number, 0));
      if (!Number.isFinite(norm) || Math.abs(norm - 1) > 0.001) throw new ProviderUnavailable();
      vectors[item.index] = vector;
    }
    let prompt: number | null = null, total: number | null = null;
    if (parsed.usage !== undefined && parsed.usage !== null) {
      const usage = parsed.usage;
      if (!object(usage) || !integer(usage.prompt_tokens) || !integer(usage.total_tokens) || usage.total_tokens < usage.prompt_tokens) throw new ProviderUnavailable();
      prompt = usage.prompt_tokens; total = usage.total_tokens;
      if (this.profile.provider === 'openai' && total > counted) throw new ProviderUnavailable();
    }
    const synthetic = this.profile.provider === 'fake';
    const cost = synthetic ? 0 : total === null ? null : estimatedCost(total, this.policy.usd_per_million_tokens!);
    return deep_freeze({ profile: this.profile, vectors, usage: { prompt_tokens: prompt, total_tokens: total, cost_usd: cost, cost_kind: synthetic ? 'known' : cost === null ? 'unknown' : 'estimated' }, provider_calls: 1 as const, synthetic });
  }
  async embed_query(text: string, options: EmbeddingOptions): Promise<EmbeddingBatch> { return this.embed_batch([text], options); }
  async embed_batch(texts: readonly string[], options: EmbeddingOptions): Promise<EmbeddingBatch> {
    if (!options || typeof options.deadline !== 'number' || !Number.isFinite(options.deadline) || (options.signal !== undefined && !(options.signal instanceof AbortSignal))) throw new InvalidRequest();
    const { deadline, signal, on_dispatch } = options;
    if (on_dispatch !== undefined && (typeof on_dispatch !== 'function' || on_dispatch.constructor.name === 'AsyncFunction')) throw new InvalidRequest();
    this.check(deadline, signal);
    if (this.inflight) throw new ProviderUnavailable();
    this.inflight = true;
    try {
      const { snapshot, counted } = this.inputs(texts);
      this.check(deadline, signal);
      if (this.profile.provider === 'openai' && (!this.policy.allow_live || this.policy.usd_per_million_tokens === null || exceedsCost(counted, this.policy.usd_per_million_tokens, this.policy.max_cost_usd))) throw new UnsupportedCapability();
      const body = new TextEncoder().encode(JSON.stringify({ model: this.profile.model, dimensions: this.profile.dimensions, encoding_format: 'float', input: snapshot }));
      const controller = new AbortController();
      const state: { failure?: 'abort' | 'deadline' } = {};
      const cancel = (reason: 'abort' | 'deadline') => { if (!state.failure) { state.failure = reason; controller.abort(reason === 'abort' ? abortError() : new DeadlineExceeded()); } };
      const onAbort = () => cancel('abort');
      signal?.addEventListener('abort', onAbort, { once: true });
      let timer: ReturnType<typeof setTimeout> | undefined;
      const schedule = () => {
        const remaining = (deadline - performance.now() / 1000) * 1000;
        if (remaining <= 0) cancel('deadline');
        else timer = setTimeout(schedule, Math.min(remaining, 2147483647));
      };
      schedule();
      let raw: unknown;
      try {
        if (state.failure === 'deadline') throw new DeadlineExceeded();
        // Admission observers run immediately before dispatch, outside provider error mapping.
        this.check(deadline,signal);
        if (on_dispatch !== undefined) {
          const observed: unknown=on_dispatch();
          if (observed !== undefined) {
            void Promise.resolve(observed).catch(()=>{});
            throw new InvalidRequest();
          }
        }
        // Caller-owned callbacks must cooperate with abort; settlement precedes reuse.
        try { raw = await this.transport(body, { deadline, signal: controller.signal, max_response_bytes: this.limits.max_response_bytes }); }
        catch (error) {
          if (!state.failure && error instanceof Error && (error.name === 'TimeoutError' || error.name === 'DeadlineExceeded')) cancel('deadline');
          if (!state.failure) throw new ProviderUnavailable();
        }
        if (state.failure === 'abort') throw abortError();
        if (state.failure === 'deadline') throw new DeadlineExceeded();
      } finally {
        if (timer !== undefined) clearTimeout(timer);
        signal?.removeEventListener('abort', onAbort);
      }
      this.check(deadline, signal);
      const result = this.response(raw, snapshot.length, counted);
      this.check(deadline, signal);
      return result;
    } finally { this.inflight = false; }
  }
}
