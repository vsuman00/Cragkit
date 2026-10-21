/** Bounded native text normalization and exact canonical UTF-8 chunk spans. */
import { createHash } from 'node:crypto';
import { InvalidRequest } from './errors.js';

export type CanonicalOptions = Readonly<{
  format?: string; max_source_bytes?: number; target_bytes?: number; max_chunk_bytes?: number;
  token_counter?: ((text: string) => number) | null; tokenizer_id?: string | null; token_target?: number | null; max_tokens?: number | null;
}>;
export type CanonicalChunk = Readonly<{
  chunk_id: string; ordinal: number; start_byte: number; end_byte: number; text: string;
  text_sha256: string; oversized_split: boolean; token_count: number | null;
}>;
export type CanonicalDocument = Readonly<{
  canonical_text: string; source_sha256: string; canonical_sha256: string; parser_id: string;
  chunker_profile: string; format: string; tokenizer_id: string | null; token_count: number | null;
  chunks: readonly CanonicalChunk[];
}>;
const hash = (value: string | Uint8Array): string => createHash('sha256').update(value).digest('hex');
const blank = (value: string): boolean => !/[^ \t\r\n\f\v]/.test(value);
const scalar = (value: string): boolean => !/[\uD800-\uDFFF]/u.test(value);
const integer = (value: unknown, min: number, max: number): value is number => typeof value === 'number' && Number.isSafeInteger(value) && value >= min && value <= max;
const bytes = (value: string): number => Buffer.byteLength(value, 'utf8');
function structural_blocks(text: string, markdown: boolean): string[] {
  const lines = text.match(/[^\n]*\n|[^\n]+$/g) ?? [];
  const output: string[] = [];
  const blankLine = (line: string): boolean => /^[ \t]*(?:\n)?$/.test(line);
  const heading = (line: string): boolean => /^ {0,3}#{1,6}(?:[ \t]|\n|$)/.test(line);
  const fence = (line: string): RegExpExecArray | null => /^ {0,3}(`{3,}|~{3,})/.exec(line);
  let index = 0;
  while (index < lines.length) {
    if (blankLine(lines[index])) {
      const start = index;
      while (index < lines.length && blankLine(lines[index])) index++;
      const value = lines.slice(start, index).join('');
      if (output.length) output[output.length - 1] += value; else output.push(value);
      continue;
    }
    const start = index;
    const opening = markdown ? fence(lines[index]) : null;
    if (opening) {
      index++;
      const closing = new RegExp('^ {0,3}' + opening[1][0] + '{' + opening[1].length + ',}[ \\t]*(?:\\n|$)');
      while (index < lines.length) { const closed = closing.test(lines[index]); index++; if (closed) break; }
    } else if (markdown && heading(lines[index])) index++;
    else {
      index++;
      while (index < lines.length && !blankLine(lines[index]) && !(markdown && (heading(lines[index]) || fence(lines[index])))) index++;
    }
    while (index < lines.length && blankLine(lines[index])) index++;
    output.push(lines.slice(start, index).join(''));
  }
  return output;
}

export function canonicalize(input: string | Uint8Array, options: CanonicalOptions = {}): CanonicalDocument {
  try { return canonicalize_checked(input, options); }
  catch { throw new InvalidRequest(); }
}
function canonicalize_checked(input: string | Uint8Array, options: CanonicalOptions): CanonicalDocument {
  if (!options || typeof options !== 'object' || ![Object.prototype, null].includes(Object.getPrototypeOf(options))) throw new InvalidRequest();
  const allowed = new Set(['format', 'max_source_bytes', 'target_bytes', 'max_chunk_bytes', 'token_counter', 'tokenizer_id', 'token_target', 'max_tokens']);
  for (const key of Reflect.ownKeys(options)) {
    const descriptor = Object.getOwnPropertyDescriptor(options, key)!;
    if (typeof key !== 'string' || !allowed.has(key) || !('value' in descriptor) || !descriptor.enumerable) throw new InvalidRequest();
  }
  const format = options.format === undefined ? 'text/plain' : options.format;
  if (typeof format !== 'string') throw new InvalidRequest();
  if (!['text/plain', 'text/markdown'].includes(format)) throw new InvalidRequest();
  const maximum = options.max_source_bytes === undefined ? 1_048_576 : options.max_source_bytes;
  const target = options.target_bytes === undefined ? 2048 : options.target_bytes;
  const hard = options.max_chunk_bytes === undefined ? 32768 : options.max_chunk_bytes;
  if (!integer(maximum, 1, 16_777_216) || !integer(hard, 4, 32768) || !integer(target, 1, hard)) throw new InvalidRequest();
  const tokenValues = [options.token_counter, options.tokenizer_id, options.token_target, options.max_tokens];
  const tokenMode = tokenValues.some(value => value !== undefined && value !== null);
  if (tokenMode && (typeof options.token_counter !== 'function' || typeof options.tokenizer_id !== 'string'
    || !/^[A-Za-z0-9_.:-]{1,64}$/.test(options.tokenizer_id) || !integer(options.token_target, 1, 1_000_000)
    || !integer(options.max_tokens, 1, 1_000_000) || options.token_target > options.max_tokens)) throw new InvalidRequest();
  let raw: Uint8Array;
  if (typeof input === 'string') {
    if (input.length > maximum || !scalar(input) || bytes(input) > maximum) throw new InvalidRequest();
    raw = Buffer.from(input, 'utf8');
  } else if (input instanceof Uint8Array) {
    if (input.byteLength > maximum) throw new InvalidRequest();
    raw = Uint8Array.from(input);
  } else throw new InvalidRequest();
  const source_sha256 = hash(raw);
  let text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(raw);
  if (text.startsWith('\uFEFF')) text = text.slice(1);
  text = text.replace(/\r\n?/g, '\n');
  if (!scalar(text) || text.includes('\0') || blank(text)) throw new InvalidRequest();
  const canonical_sha256 = hash(text);
  const profile = tokenMode
    ? `cragkit.structure.tokens.v1:target_bytes=${target}:max_bytes=${hard}:tokenizer=${options.tokenizer_id}:target=${options.token_target}:max=${options.max_tokens}`
    : `cragkit.structure.bytes.v1:target=${target}:max=${hard}`;
  let counterCalls = 0;
  const count = (value: string): number | null => {
    if (!tokenMode) return null;
    if (++counterCalls > 65536) throw new InvalidRequest();
    let result: unknown;
    try { result = options.token_counter!(value); } catch { throw new InvalidRequest(); }
    if (result instanceof Promise) {
      // Invalid asynchronous counters must not leave an unhandled rejection behind.
      void result.catch(() => {});
      throw new InvalidRequest();
    }
    if (!integer(result, 0, Number.MAX_SAFE_INTEGER)) throw new InvalidRequest();
    return result;
  };
  const chunks: CanonicalChunk[] = [];
  let offset = 0;
  const emit = (value: string, oversized: boolean): void => {
    if (chunks.length >= 1024) throw new InvalidRequest();
    const end = offset + bytes(value);
    const token_count = count(value);
    if (tokenMode && token_count! > options.max_tokens!) throw new InvalidRequest();
    chunks.push(Object.freeze({ chunk_id: hash(`${canonical_sha256}:${offset}:${end}:${profile}`), ordinal: chunks.length,
      start_byte: offset, end_byte: end, text: value, text_sha256: hash(value), oversized_split: oversized, token_count }));
    offset = end;
  };
  let pending: string[] = [];
  let pendingBytes = 0;
  let pendingSplit = false;
  const flush = (): void => {
    if (pending.length) emit(pending.join(''), pendingSplit);
    pending = []; pendingBytes = 0; pendingSplit = false;
  };
  const pack = (value: string, split: boolean): void => {
    const valueBytes = bytes(value);
    if (pending.length) {
      // Match Python's work budget: impossible byte combinations never call a tokenizer.
      if (pendingBytes + valueBytes <= target
          && (!tokenMode || count(pending.join('') + value)! <= options.token_target!)) {
        pending.push(value); pendingBytes += valueBytes; pendingSplit ||= split; return;
      }
      flush();
    }
    pending = [value]; pendingBytes = valueBytes; pendingSplit = split;
  };
  for (const block of structural_blocks(text, format === 'text/markdown')) {
    const blockCount = count(block);
    if (bytes(block) > hard || (tokenMode && blockCount! > options.max_tokens!)) {
      // Only oversized structures are split; every split ends at a Unicode scalar boundary.
      let piece = '';
      let pieceBytes = 0;
      for (const point of block) {
        const combined = piece + point;
        const pointBytes = bytes(point);
        const combinedBytes = pieceBytes + pointBytes;
        const candidateCount = count(combined);
        if (piece && (combinedBytes > target || combinedBytes > hard || (tokenMode && (candidateCount! > options.token_target! || candidateCount! > options.max_tokens!)))) {
          pack(piece, true); piece = point; pieceBytes = pointBytes;
          if (pieceBytes > hard || (tokenMode && count(piece)! > options.max_tokens!)) throw new InvalidRequest();
        } else {
          if (combinedBytes > hard || (tokenMode && candidateCount! > options.max_tokens!)) throw new InvalidRequest();
          piece = combined; pieceBytes = combinedBytes;
        }
      }
      if (piece) pack(piece, true);
    } else pack(block, false);
  }
  flush();
  return Object.freeze({ canonical_text: text, source_sha256, canonical_sha256, parser_id: format === 'text/markdown' ? 'cragkit.markdown.v1' : 'cragkit.text.v1',
    chunker_profile: profile, format, tokenizer_id: tokenMode ? options.tokenizer_id! : null, token_count: count(text), chunks: Object.freeze(chunks) });
}
