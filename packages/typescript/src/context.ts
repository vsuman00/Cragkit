import { createHash } from 'node:crypto';
import { open } from 'node:fs/promises';
import { ContextBudgetTooSmall, InvalidRequest, UnsupportedCapability } from './errors.js';
import { EvidenceSchema } from './results.js';
import { valid_native_json } from './shared.js';

export const CONTEXT_RENDERER = 'cragkit.context.v2';
const issued = new WeakSet<Cl100kCounter>();
const construction = Symbol();
const SHA256 = '223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7';
const PATTERN = String.raw`'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}++|\p{N}{1,3}+| ?[^\s\p{L}\p{N}]++[\r\n]*+|\s++$|\s*[\r\n]|\s+(?!\S)|\s`;
type Encoder = { encode(text: string, allowed: string[], disallowed: string[]): Uint32Array; free(): void };
export class Cl100kCounter {
  readonly tokenizer = 'cl100k_base';
  #encoder: Encoder;
  #closed = false;
  private constructor(encoder: Encoder, token: symbol) { if (token !== construction) throw new UnsupportedCapability(); this.#encoder = encoder; issued.add(this); Object.freeze(this); }
  static async create(path: string | URL): Promise<Cl100kCounter> {
    let ranks: string;
    try {
      if (typeof path !== 'string' && !(path instanceof URL)) throw new InvalidRequest();
      const stream = await open(path, 'r');
      try {
        if (!(await stream.stat()).isFile()) throw new InvalidRequest();
        const buffer = Buffer.alloc(2_000_001);
        let size = 0;
        while (size < buffer.length) {
          const { bytesRead } = await stream.read(buffer, size, buffer.length - size, size);
          if (bytesRead === 0) break;
          size += bytesRead;
        }
        const data = buffer.subarray(0, size);
        if (size > 2_000_000 || createHash('sha256').update(data).digest('hex') !== SHA256) throw new InvalidRequest();
        ranks = data.toString('ascii');
      } finally { await stream.close(); }
    } catch { throw new InvalidRequest(); }
    try {
      const name = 'tiktoken/lite';
      const module = await import(name) as { Tiktoken: new (ranks: string, special: Record<string, number>, pattern: string) => Encoder };
      return new Cl100kCounter(new module.Tiktoken(ranks, {}, PATTERN), construction);
    } catch { throw new UnsupportedCapability(); }
  }
  close(): void { if (!this.#closed) { this.#encoder.free(); this.#closed = true; issued.delete(this); } }
  count(value: unknown): number {
    if (this.#closed) throw new UnsupportedCapability();
    if (typeof value !== 'string' || value.length > 262144 || !valid_native_json(value) || Buffer.byteLength(value, 'utf8') > 262144) throw new InvalidRequest();
    try { return this.#encoder.encode(value, [], []).length; }
    catch { throw new UnsupportedCapability(); }
  }
}

export function render_context(input: unknown): string {
  if (!Array.isArray(input) || input.length > 64 || !valid_native_json(input)) throw new InvalidRequest();
  try {
    const items = input.map(value => EvidenceSchema.parse(value));
    const ids = new Set<string>(), digests = new Map<string, string>();
    const ordered = items.map(item => {
      if (ids.has(item.evidence_id)) throw new InvalidRequest();
      ids.add(item.evidence_id);
      const key = JSON.stringify([item.collection, item.document_id, item.revision_id]);
      if (digests.has(key) && digests.get(key) !== item.source_sha256) throw new InvalidRequest();
      digests.set(key, item.source_sha256);
      return {
        evidence_id: item.evidence_id, collection: item.collection, document_id: item.document_id,
        revision_id: item.revision_id, chunk_id: item.chunk_id, source_locator: item.source_locator,
        start_byte: item.start_byte, end_byte: item.end_byte, text: item.text,
        source_sha256: item.source_sha256, text_sha256: item.text_sha256,
      };
    });
    const rendered = JSON.stringify(ordered);
    if (Buffer.byteLength(rendered, 'utf8') > 262144) throw new InvalidRequest();
    return rendered;
  } catch { throw new InvalidRequest(); }
}

export type ContextOptions = {
  max_tokens: number; reserve?: number;
  counter?: Cl100kCounter | null; counting_mode?: 'strict' | 'estimated';
};
export type CountedContext = Readonly<{
  context: string; context_tokens: number; total_tokens: number;
  renderer: typeof CONTEXT_RENDERER; tokenizer: 'cl100k_base' | null; counting_mode: 'strict' | 'estimated';
}>;
export function count_context(input: unknown, options: ContextOptions): CountedContext {
  if (!options || typeof options !== 'object' || Object.getPrototypeOf(options) !== Object.prototype
    || Object.getOwnPropertySymbols(options).length) throw new InvalidRequest();
  const fields = Object.getOwnPropertyDescriptors(options);
  if (Object.entries(fields).some(([key, value]) => !['max_tokens', 'reserve', 'counter', 'counting_mode'].includes(key)
    || !('value' in value) || !value.enumerable)) throw new InvalidRequest();
  const maximum = fields.max_tokens?.value;
  const reserve = fields.reserve ? fields.reserve.value : 256;
  const mode = fields.counting_mode ? fields.counting_mode.value : 'estimated';
  if (typeof maximum !== 'number' || !Number.isInteger(maximum) || maximum < 1 || maximum > 1000000
    || typeof reserve !== 'number' || !Number.isInteger(reserve) || reserve < 0 || reserve > 1000000
    || (mode !== 'strict' && mode !== 'estimated')) throw new InvalidRequest();
  const counter = fields.counter?.value;
  if (mode === 'estimated' && fields.counter && counter !== null) throw new InvalidRequest();
  if (mode === 'strict' && (!(counter instanceof Cl100kCounter) || !issued.has(counter))) throw new UnsupportedCapability();
  const count = (value: string): number => {
    if (mode === 'estimated') return Math.ceil(Buffer.byteLength(value, 'utf8') / 4);
    try {
      const result = Cl100kCounter.prototype.count.call(counter, value);
      if (!Number.isSafeInteger(result) || result < 0) throw new UnsupportedCapability();
      return result;
    } catch { throw new UnsupportedCapability(); }
  };
  const context = render_context(input);
  if (count('[]') + reserve > maximum) throw new ContextBudgetTooSmall();
  const context_tokens = count(context);
  if (context_tokens + reserve > maximum) throw new ContextBudgetTooSmall();
  return Object.freeze({ context, context_tokens, total_tokens: context_tokens + reserve,
    renderer: CONTEXT_RENDERER, tokenizer: mode === 'strict' ? 'cl100k_base' : null, counting_mode: mode });
}
