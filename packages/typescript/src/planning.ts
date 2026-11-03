import { z } from 'zod';
import { performance } from 'node:perf_hooks';
import { ExecutionLedger } from './execution.js';
import { DeadlineExceeded, IntegrityViolation, InvalidRequest, ProviderUnavailable } from './errors.js';
import { extract_identifiers } from './identifiers.js';
import { deep_freeze, identity, input_text, integer, safe_number, valid_native_json, type DeepReadonly } from './shared.js';

const VariantSchema = z.strictObject({facet_id: identity, variant_id: identity, query: input_text(16384)});
const ConfigSchema = z.strictObject({query: input_text(16384), variants: z.array(VariantSchema).max(16),
  missing_facets: z.array(identity).max(32), max_subqueries: integer(1, 16)});
const PlanSchema = z.strictObject({queries: z.array(z.strictObject({facet_id: identity, variant_id: identity})).max(16)});
const UsageSchema = z.strictObject({input_tokens: integer(0, Number.MAX_SAFE_INTEGER).nullable(),
  output_tokens: integer(0, Number.MAX_SAFE_INTEGER).nullable(), cost_usd: safe_number.min(0).nullable()});
const ResponseSchema = z.strictObject({plan: z.unknown(), usage: UsageSchema});
export type ApprovedVariant = Readonly<z.infer<typeof VariantSchema>>;
type Config = z.infer<typeof ConfigSchema>;
export type PlanningResult = Readonly<{queries: readonly ApprovedVariant[]; fallback: boolean}>;
export type PlannerTransport = (payload: DeepReadonly<Config>, options: {deadline: number; signal: AbortSignal}) => Promise<unknown>;
function checked<T>(schema: z.ZodType<T>, value: unknown): T {
  try { if (!valid_native_json(value)) throw new InvalidRequest(); return schema.parse(value); }
  catch { throw new InvalidRequest(); }
}
function config(value: unknown): Config {
  const c = checked(ConfigSchema, value);
  if (new Set(c.missing_facets).size !== c.missing_facets.length
    || new Set(c.variants.map(v => v.variant_id)).size !== c.variants.length) throw new InvalidRequest();
  const required = extract_identifiers(c.query);
  for (const variant of c.variants) {
    const identifiers = new Set(extract_identifiers(variant.query));
    if (required.some(token => !identifiers.has(token))) throw new InvalidRequest();
  }
  return c;
}
/** Select approved hypotheses while preserving original exact identifiers. */
export function validate_plan(value: unknown, options: unknown): readonly ApprovedVariant[] {
  const c = config(options), plan = checked(PlanSchema, value);
  if (plan.queries.length > c.max_subqueries - 1) throw new InvalidRequest();
  const seen = new Set<string>();
  const queries = plan.queries.map(selection => {
    const variant = c.variants.find(v => v.variant_id === selection.variant_id && v.facet_id === selection.facet_id);
    if (!variant || !c.missing_facets.includes(selection.facet_id) || seen.has(selection.variant_id)) throw new InvalidRequest();
    seen.add(selection.variant_id); return {...variant};
  });
  return deep_freeze(queries);
}
function dataOptions(value: unknown, keys: readonly string[]): Record<string, unknown> {
  try {
    if (value === null || typeof value !== 'object' || Object.getPrototypeOf(value) !== Object.prototype
      || Object.getOwnPropertySymbols(value).length) throw new InvalidRequest();
    const descriptors = Object.getOwnPropertyDescriptors(value);
    if (Object.entries(descriptors).some(([key, d]) => !keys.includes(key) || !('value' in d) || !d.enumerable)) throw new InvalidRequest();
    return value as Record<string, unknown>;
  } catch { throw new InvalidRequest(); }
}
function check(deadline: number, signal?: AbortSignal): void {
  signal?.throwIfAborted();
  if (performance.now() / 1000 >= deadline) throw new DeadlineExceeded();
}

export class PlannerAdapter {
  readonly #transport: PlannerTransport;
  readonly #bound: number | null;
  readonly #fallback: boolean;
  constructor(options: {transport: PlannerTransport; sdk_retries?: number; cost_upper_usd?: number | null; allow_fallback?: boolean}) {
    const o = dataOptions(options, ['transport', 'sdk_retries', 'cost_upper_usd', 'allow_fallback']);
    if (typeof o.transport !== 'function') throw new InvalidRequest();
    const c = checked(z.strictObject({sdk_retries: z.literal(0).default(0), cost_upper_usd: safe_number.min(0).nullable().default(null),
      allow_fallback: z.boolean().default(false)}), Object.fromEntries(Object.entries(o).filter(([key]) => key !== 'transport')));
    this.#transport = o.transport as PlannerTransport; this.#bound = c.cost_upper_usd; this.#fallback = c.allow_fallback;
  }
  async plan(options: {query: unknown; variants: unknown; missing_facets: unknown; max_subqueries: unknown;
    ledger: ExecutionLedger; deadline: number; signal?: AbortSignal}): Promise<PlanningResult> {
    const o = dataOptions(options, ['query', 'variants', 'missing_facets', 'max_subqueries', 'ledger', 'deadline', 'signal']);
    const payload = deep_freeze(config({query: o.query, variants: o.variants, missing_facets: o.missing_facets, max_subqueries: o.max_subqueries}));
    if (!(o.ledger instanceof ExecutionLedger) || !safe_number.safeParse(o.deadline).success
      || (o.signal !== undefined && !(o.signal instanceof AbortSignal))) throw new InvalidRequest();
    const ledger = o.ledger, deadline = Math.min(o.deadline as number, o.ledger.deadline), signal = o.signal as AbortSignal | undefined;
    check(deadline, signal);
    if (!payload.variants.length || !payload.missing_facets.length || payload.max_subqueries === 1) return deep_freeze({queries: [], fallback: false});
    const reservation = ledger.reserve({provider_calls: 1, cost_upper_usd: this.#bound});
    try { check(deadline, signal); ledger.dispatch(reservation); }
    catch (error) { ledger.abandon(reservation); throw error; }
    let settled = false;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    let abort: (() => void) | undefined;
    try {
      let raw: unknown;
      try {
        const boundary = new Promise<never>((_, reject) => {
          timer = setTimeout(() => { reject(new DeadlineExceeded()); controller.abort(); }, Math.max(0, (deadline - performance.now() / 1000) * 1000));
          abort = () => { reject(signal!.reason); controller.abort(signal!.reason); };
          signal?.addEventListener('abort', abort, {once: true});
        });
        raw = await Promise.race([Promise.resolve().then(() => {
          check(deadline, signal);
          return this.#transport(payload, {deadline, signal: controller.signal});
        }), boundary]);
        check(deadline, signal);
      } catch (error) {
        if (signal?.aborted) throw signal.reason;
        if (error instanceof DeadlineExceeded) throw new DeadlineExceeded();
        if (this.#fallback) return deep_freeze({queries: [], fallback: true});
        throw new ProviderUnavailable();
      }
      let response: z.infer<typeof ResponseSchema>;
      try {
        if (!valid_native_json(raw) || Buffer.byteLength(JSON.stringify(raw), 'utf8') > 16384
          || !Object.hasOwn(raw as object, 'plan')) throw new InvalidRequest();
        response = ResponseSchema.parse(raw);
      } catch {
        if (this.#fallback) return deep_freeze({queries: [], fallback: true});
        throw new IntegrityViolation();
      }
      // Reconciliation errors are accounting failures and must never use fallback.
      settled = true;
      ledger.reconcile(reservation, response.usage);
      try { return deep_freeze({queries: validate_plan(response.plan, payload), fallback: false}); }
      catch {
        if (this.#fallback) return deep_freeze({queries: [], fallback: true});
        throw new IntegrityViolation();
      }
    } finally {
      if (timer !== undefined) clearTimeout(timer);
      if (abort) signal?.removeEventListener('abort', abort);
      if (!settled) ledger.abandon(reservation);
    }
  }
}
