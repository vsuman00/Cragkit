import { createHash } from 'node:crypto';
import { setImmediate } from 'node:timers/promises';
import { count_context, type ContextOptions, type CountedContext } from './context.js';
import { ContextBudgetTooSmall, DeadlineExceeded, IntegrityViolation, InvalidRequest } from './errors.js';
import { EvidenceSchema, type Evidence } from './results.js';
import { deep_freeze, valid_native_json } from './shared.js';

export type PackingOptions = ContextOptions & { deadline: number; signal?: AbortSignal; surrounding_bytes?: number; facet_evidence?: readonly (readonly string[])[] };
export type PackedEvidence = CountedContext & { readonly evidence: readonly Evidence[]; readonly omitted_count: number; readonly merged_count: number; readonly expanded_count: number; readonly aliases: Readonly<Record<string, readonly string[]>> };
type Source = { collection: string; document_id: string; revision_id: string; source_sha256: string; text: string };
type Group = { item: Evidence; start: number; end: number; seedStart: number; seedEnd: number; ranks: number[] };
const hash = (value: string | Uint8Array) => createHash('sha256').update(value).digest('hex');
const key = (value: { collection: string; document_id: string; revision_id: string }) => JSON.stringify([value.collection, value.document_id, value.revision_id]);
function check(deadline: number, signal?: AbortSignal): void {
  if (signal?.aborted) { const error = new Error('Operation aborted.'); error.name = 'AbortError'; throw error; }
  if (performance.now() / 1000 >= deadline) throw new DeadlineExceeded();
}
const identity = (value: unknown): value is string => typeof value === 'string' && value.length <= 256 && Buffer.byteLength(value) <= 256 && /[^ \t\r\n\f\v]/.test(value);

function fenced_spans(data: Buffer): [number, number][] {
  const spans: [number, number][] = [];
  let opening: { marker: string; length: number; offset: number } | undefined;
  let offset = 0;
  for (const line of data.toString('latin1').split('\n')) {
    const match = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line.replace(/\r$/, ''));
    if (match) {
      const marker = match[1], tail = match[2];
      if (!opening) opening = { marker: marker[0], length: marker.length, offset };
      else if (marker[0] === opening.marker && marker.length >= opening.length && /^[ \t]*$/.test(tail)) {
        spans.push([opening.offset, offset + line.length]); opening = undefined;
      }
    }
    offset += line.length + 1;
  }
  if (opening) spans.push([opening.offset, data.length]);
  return spans;
}

/** Pack exact source slices; source authorization belongs to the caller. */
export async function pack_evidence(input: unknown, sourceInput: unknown, options: PackingOptions): Promise<PackedEvidence> {
  if (!options || Object.getPrototypeOf(options) !== Object.prototype || Object.getOwnPropertySymbols(options).length) throw new InvalidRequest();
  const descriptors = Object.getOwnPropertyDescriptors(options);
  if (Object.entries(descriptors).some(([field, descriptor]) => !['deadline', 'signal', 'max_tokens', 'reserve', 'counter', 'counting_mode', 'surrounding_bytes', 'facet_evidence'].includes(field) || !('value' in descriptor) || !descriptor.enumerable)) throw new InvalidRequest();
  const { deadline, signal } = options;
  const surrounding = options.surrounding_bytes === undefined ? 256 : options.surrounding_bytes;
  if (typeof deadline !== 'number' || !Number.isFinite(deadline) || Math.abs(deadline) > Number.MAX_SAFE_INTEGER || signal !== undefined && !(signal instanceof AbortSignal)
    || !Number.isSafeInteger(surrounding) || surrounding < 0 || surrounding > 4096) throw new InvalidRequest();
  check(deadline, signal);
  if (!Array.isArray(input) || input.length > 64 || !valid_native_json(input)
    || !Array.isArray(sourceInput) || sourceInput.length > 64 || !valid_native_json(sourceInput)) throw new InvalidRequest();
  let evidence: Evidence[];
  try { evidence = input.map(item => EvidenceSchema.parse(item)); } catch { throw new InvalidRequest(); }
  const ids = evidence.map(item => item.evidence_id);
  if (new Set(ids).size !== ids.length) throw new InvalidRequest();
  const facetInput = options.facet_evidence === undefined ? [] : options.facet_evidence;
  const facets = facetInput;
  if (!valid_native_json(facets) || !Array.isArray(facets) || facets.length > 32 || facets.some(facet => !Array.isArray(facet) || facet.length > 64 || new Set(facet).size !== facet.length || facet.some(id => typeof id !== 'string' || !ids.includes(id)))) throw new InvalidRequest();
  const facetSnapshot = facets.map(facet => [...facet]);
  const sourceSnapshot = sourceInput.map(value => ({ ...value }));
  const counting: ContextOptions = { max_tokens: options.max_tokens };
  for (const field of ['reserve', 'counter', 'counting_mode'] as const) if (descriptors[field]) Object.assign(counting, { [field]: descriptors[field].value });
  let counted = count_context([], counting);
  const sources = new Map<string, { source: Source; bytes: Buffer; fences: [number, number][] }>();
  let sourceBytes = 0;
  for (const value of sourceSnapshot) {
    await setImmediate(); check(deadline, signal);
    const source = value as Source;
    if (source === null || typeof source !== 'object' || Array.isArray(source) || Object.keys(source).length !== 5
      || Object.keys(source).some(field => !['collection', 'document_id', 'revision_id', 'source_sha256', 'text'].includes(field))
      || !identity(source.collection) || !identity(source.document_id) || !identity(source.revision_id)
      || typeof source.source_sha256 !== 'string' || !/^[0-9a-f]{64}$/.test(source.source_sha256) || typeof source.text !== 'string' || source.text.length > 16777216) throw new InvalidRequest();
    sourceBytes += Buffer.byteLength(source.text);
    if (sourceBytes > 16777216) throw new InvalidRequest();
    const bytes = Buffer.from(source.text, 'utf8');
    if (hash(bytes) !== source.source_sha256) throw new IntegrityViolation();
    const previous = sources.get(key(source));
    if (previous && (previous.source.source_sha256 !== source.source_sha256 || previous.source.text !== source.text)) throw new IntegrityViolation();
    sources.set(key(source), { source, bytes, fences: fenced_spans(bytes) });
  }
  const locators = new Map<string, string>();
  const groups: Group[] = [];
  for (const [rank, item] of evidence.entries()) {
    check(deadline, signal);
    const source = sources.get(key(item));
    if (!source || source.source.source_sha256 !== item.source_sha256 || item.end_byte > source.bytes.length
      || !source.bytes.subarray(item.start_byte, item.end_byte).equals(Buffer.from(item.text))) throw new IntegrityViolation();
    const locator = locators.get(key(item));
    if (locator !== undefined && locator !== item.source_locator) throw new IntegrityViolation();
    locators.set(key(item), item.source_locator);
    let start = item.start_byte, end = item.end_byte;
    const before = source.bytes.lastIndexOf('\n\n', start - 2);
    if (before >= Math.max(0, start - surrounding) && before + 2 <= start) start = before + 2;
    else if (start <= surrounding) start = 0;
    const after = source.bytes.indexOf('\n\n', end);
    if (after !== -1 && after <= Math.min(source.bytes.length, end + surrounding)) end = after;
    else if (source.bytes.length - end <= surrounding) end = source.bytes.length;
    for (const [fenceStart, fenceEnd] of source.fences) {
      if (fenceStart <= item.start_byte && item.end_byte <= fenceEnd) {
        if (item.start_byte - fenceStart <= surrounding && fenceEnd - item.end_byte <= surrounding) {
          start = fenceStart; end = fenceEnd;
        }
        break;
      }
    }
    if (start > 0 && surrounding) {
      let beforeEnd = start;
      while (beforeEnd > 0 && source.bytes[beforeEnd - 1] === 10) beforeEnd--;
      const headingStart = source.bytes.lastIndexOf('\n', beforeEnd - 1) + 1;
      const heading = source.bytes.subarray(headingStart, beforeEnd).toString('latin1');
      if (/^ {0,3}#{1,6}[ \t]+/.test(heading) && item.start_byte - headingStart <= surrounding) start = headingStart;
    }
    groups.push({ item, start, end, seedStart: item.start_byte, seedEnd: item.end_byte, ranks: [rank] });
  }
  groups.sort((a, b) => Buffer.compare(Buffer.from(key(a.item)), Buffer.from(key(b.item))) || a.start - b.start || a.end - b.end);
  const merged: Group[] = [];
  for (const group of groups) {
    const previous = merged.at(-1);
    if (previous && key(previous.item) === key(group.item) && group.start <= previous.end) {
      previous.end = Math.max(previous.end, group.end); previous.seedStart = Math.min(previous.seedStart, group.seedStart); previous.seedEnd = Math.max(previous.seedEnd, group.seedEnd); previous.ranks.push(...group.ranks);
    } else merged.push({ ...group, ranks: [...group.ranks] });
  }
  merged.forEach(group => group.ranks.sort((a, b) => a - b));
  merged.sort((a, b) => a.ranks[0] - b.ranks[0]);
  const priority: Group[] = [];
  const selected = new Set<Group>();
  for (const facet of facetSnapshot) {
    if (priority.some(group => group.ranks.some(rank => facet.includes(ids[rank])))) continue;
    const group = merged.find(candidate => candidate.ranks.some(rank => facet.includes(ids[rank])));
    if (group) { priority.push(group); selected.add(group); }
  }
  priority.push(...merged.filter(group => !selected.has(group)));
  const packed: Evidence[] = [], aliases: Record<string, string[]> = {};
  const usedIds = new Set(ids);
  let mergedCount = 0, expandedCount = 0, included = 0;
  for (const group of priority) {
    await setImmediate(); check(deadline, signal);
    if (group.end - group.start > 32768) continue;
    const bytes = sources.get(key(group.item))!.bytes.subarray(group.start, group.end);
    const changed = group.ranks.length > 1 || group.start !== group.item.start_byte || group.end !== group.item.end_byte;
    const baseId = 'span-' + hash(JSON.stringify([group.item.collection, group.item.document_id, group.item.revision_id, group.item.source_sha256, group.start, group.end]));
    let spanId = baseId;
    for (let suffix = 1; changed && usedIds.has(spanId); suffix++) spanId = `${baseId}-${suffix}`;
    const item: Evidence = { ...group.item, evidence_id: changed ? spanId : group.item.evidence_id, chunk_id: changed ? spanId : group.item.chunk_id, start_byte: group.start, end_byte: group.end, text: bytes.toString('utf8'), text_sha256: hash(bytes) };
    if (Buffer.byteLength(JSON.stringify([...packed, item])) > 262144) continue;
    let proposal: CountedContext;
    try { proposal = count_context([...packed, item], counting); } catch (error) { if (error instanceof ContextBudgetTooSmall) continue; throw error; }
    usedIds.add(item.evidence_id);
    packed.push(item); counted = proposal; Object.defineProperty(aliases, item.evidence_id, { value: group.ranks.map(rank => ids[rank]), enumerable: true });
    included += group.ranks.length; mergedCount += group.ranks.length - 1;
    if (group.start !== group.seedStart || group.end !== group.seedEnd) expandedCount++;
  }
  check(deadline, signal);
  return deep_freeze({ ...counted, evidence: packed, omitted_count: evidence.length - included, merged_count: mergedCount, expanded_count: expandedCount, aliases });
}
