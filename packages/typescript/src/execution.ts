import { performance } from 'node:perf_hooks';
import { z } from 'zod';
import { LimitsSchema, type Limits } from './requests.js';
import { DeadlineExceeded, IntegrityViolation, InvalidRequest, UnsupportedCapability } from './errors.js';
import { integer, safe_number, valid_native_json } from './shared.js';

const count = integer(0, Number.MAX_SAFE_INTEGER);
const amount = safe_number.min(0).nullable().default(null);
const ReserveSchema = z.strictObject({ provider_calls: count.default(0), candidates: count.default(0),
  attempts: count.default(0), cost_upper_usd: amount });
const ActualSchema = z.strictObject({ input_tokens: count.nullable().default(null),
  output_tokens: count.nullable().default(null), cost_usd: amount });
function parse<T>(schema: z.ZodType<T>, value: unknown): T {
  try { if (!valid_native_json(value)) throw new InvalidRequest(); return schema.parse(value); }
  catch { throw new InvalidRequest(); }
}
export class BudgetExhausted extends Error {
  constructor() { super('Execution budget exhausted.'); this.name = 'BudgetExhausted'; }
}
const brand: unique symbol = Symbol('reservation');
export type Reservation = Readonly<{ [brand]: true }>;
type Entry = z.infer<typeof ReserveSchema> & { state: 'reserved' | 'dispatched' | 'completed' };
export type ExecutionSnapshot = Readonly<{provider_calls: number; candidates: number; attempts: number;
  input_tokens: number | null; output_tokens: number | null; cost_usd: number | null;
  cost_kind: 'known' | 'unknown'; pending: number}>;

/** Atomic request-local accounting; each transport retry reserves separately. */
export class ExecutionLedger {
  readonly #limits: Limits;
  readonly #deadline: number;
  readonly #entries = new WeakMap<object, Entry>();
  readonly #pending = new Set<Reservation>();
  #calls = 0; #candidates = 0; #attempts = 0;
  #input: number | null = 0; #output: number | null = 0; #cost: number | null = 0;
  #heldCost = 0;
  #knownInput = 0; #knownOutput = 0; #knownCost = 0;
  #closed = false;
  #poisoned = false;

  constructor(options: {limits: unknown; deadline: number}) {
    const configured = parse(z.strictObject({limits: LimitsSchema, deadline: safe_number}), options);
    this.#limits = configured.limits;
    this.#deadline = Math.min(configured.deadline, performance.now() / 1000 + this.#limits.deadline_ms / 1000);
  }
  get deadline(): number { return this.#deadline; }
  close(): void { this.#closed = true; }
  #admit(): void {
    if (this.#closed) throw new InvalidRequest();
    if (this.#poisoned) throw new IntegrityViolation();
    if (performance.now() / 1000 >= this.#deadline) throw new DeadlineExceeded();
  }
  #entry(token: unknown, states: Entry['state'][]): Entry {
    const entry = typeof token === 'object' && token !== null ? this.#entries.get(token) : undefined;
    if (!entry || !states.includes(entry.state)) throw new InvalidRequest();
    return entry;
  }
  reserve(options: {provider_calls?: number; candidates?: number; attempts?: number; cost_upper_usd?: number | null} = {}): Reservation {
    const value = parse(ReserveSchema, options);
    if (!(value.provider_calls || value.candidates || value.attempts)
      || (!value.provider_calls && value.cost_upper_usd !== null && value.cost_upper_usd !== 0)) throw new InvalidRequest();
    this.#admit();
    if (value.provider_calls && this.#limits.max_spend_usd !== null && value.cost_upper_usd === null) throw new UnsupportedCapability();
    if (value.provider_calls > this.#limits.max_provider_calls - this.#calls
      || value.candidates > this.#limits.max_candidates - this.#candidates
      || value.attempts > this.#limits.max_attempts - this.#attempts
      || (this.#limits.max_spend_usd !== null && (value.cost_upper_usd ?? 0) > this.#limits.max_spend_usd - this.#heldCost)) throw new BudgetExhausted();
    const held = this.#heldCost + (value.cost_upper_usd ?? 0);
    if (!Number.isFinite(held) || held > Number.MAX_SAFE_INTEGER) { this.#poisoned = true; throw new IntegrityViolation(); }
    const token = Object.freeze({}) as Reservation;
    this.#entries.set(token, {...value, state: 'reserved'}); this.#pending.add(token);
    this.#calls += value.provider_calls; this.#candidates += value.candidates; this.#attempts += value.attempts; this.#heldCost = held;
    return token;
  }
  dispatch(reservation: Reservation): void {
    const entry = this.#entry(reservation, ['reserved']); this.#admit(); entry.state = 'dispatched';
  }
  reconcile(reservation: Reservation, options: {input_tokens?: number | null; output_tokens?: number | null; cost_usd?: number | null} = {}): void {
    if (!options || typeof options !== 'object') throw new InvalidRequest();
    const entry = this.#entry(reservation, ['dispatched']);
    const actual = parse(ActualSchema, options);
    if (!entry.provider_calls && Object.values(actual).some(value => value !== null && value !== 0)) throw new InvalidRequest();
    const add = (total: number | null, value: number | null) => total === null || value === null ? null : total + value;
    const input = entry.provider_calls ? add(this.#input, actual.input_tokens) : this.#input;
    const output = entry.provider_calls ? add(this.#output, actual.output_tokens) : this.#output;
    const cost = entry.provider_calls ? add(this.#cost, actual.cost_usd) : this.#cost;
    const knownInput = this.#knownInput + (entry.provider_calls ? actual.input_tokens ?? 0 : 0);
    const knownOutput = this.#knownOutput + (entry.provider_calls ? actual.output_tokens ?? 0 : 0);
    const knownCost = this.#knownCost + (entry.provider_calls ? actual.cost_usd ?? 0 : 0);
    const overflow = [knownInput, knownOutput, knownCost].some(value => value !== null && (!Number.isFinite(value) || value > Number.MAX_SAFE_INTEGER));
    entry.state = 'completed'; this.#pending.delete(reservation);
    if (overflow) {
      this.#input = null; this.#output = null; this.#cost = null; this.#poisoned = true;
      throw new IntegrityViolation();
    }
    this.#knownInput = knownInput; this.#knownOutput = knownOutput; this.#knownCost = knownCost;
    this.#input = input; this.#output = output; this.#cost = cost;
    if (entry.provider_calls && actual.cost_usd !== null) this.#heldCost += actual.cost_usd - (entry.cost_upper_usd ?? 0);
    if (actual.cost_usd !== null && entry.cost_upper_usd !== null && actual.cost_usd > entry.cost_upper_usd) {
      this.#poisoned = true; throw new IntegrityViolation();
    }
  }
  abandon(reservation: Reservation): void {
    const entry = this.#entry(reservation, ['reserved', 'dispatched']);
    if (entry.state === 'reserved') {
      this.#calls -= entry.provider_calls; this.#candidates -= entry.candidates; this.#attempts -= entry.attempts;
      this.#heldCost -= entry.cost_upper_usd ?? 0;
    } else if (entry.provider_calls) { this.#input = null; this.#output = null; this.#cost = null; }
    entry.state = 'completed'; this.#pending.delete(reservation);
  }
  snapshot(): ExecutionSnapshot {
    const unknown = [...this.#pending].some(token => this.#entries.get(token)!.provider_calls > 0);
    const cost = unknown ? null : this.#cost;
    return Object.freeze({provider_calls: this.#calls, candidates: this.#candidates, attempts: this.#attempts,
      input_tokens: unknown ? null : this.#input, output_tokens: unknown ? null : this.#output,
      cost_usd: cost, cost_kind: cost === null ? 'unknown' : 'known', pending: this.#pending.size});
  }
}
