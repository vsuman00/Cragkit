import { createHash } from 'node:crypto';
import type { Evidence } from './results.js';
import type { LexicalCandidate } from './postgres-session.js';
import { IntegrityViolation, InvalidRequest, UnsupportedCapability } from './errors.js';

export type SourceFetch = Readonly<{ state: 'verified' | 'unavailable' | 'budget_exhausted'; evidence: Readonly<Evidence> | null; source_bytes: number; stale: boolean }>;
const sha = (value: string | Uint8Array): string => createHash('sha256').update(value).digest('hex');
const digest = /^[0-9a-f]{64}$/;
const identity = (value: unknown): value is string => typeof value === 'string' && value.length <= 256 && !/[\uD800-\uDFFF\0]/u.test(value) && Buffer.byteLength(value) <= 256 && /[^ \t\r\n\f\v]/.test(value);
export function exact_integer(value: unknown): number {
  if (typeof value === 'string' && /^(0|[1-9][0-9]*)$/.test(value)) value = Number(value);
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new IntegrityViolation();
  return value;
}
export function verify_source(candidate: LexicalCandidate, rows: unknown[][], budget: number): SourceFetch {
  if (!Number.isSafeInteger(budget) || budget < 0 || budget > 16777216) throw new InvalidRequest();
  if (!rows.length) return Object.freeze({ state: 'unavailable', evidence: null, source_bytes: 0, stale: false });
  if (rows.length !== 1 || rows[0].length !== 17) throw new IntegrityViolation();
  const row = rows[0];
  for (const [index, key] of ['tenant_id','collection','document_id','revision_id','generation_id','chunk_id'].entries()) {
    if (!identity(row[index]) || row[index] !== candidate[key as keyof LexicalCandidate]) throw new IntegrityViolation();
  }
  if (row[15] !== 'native_fts.v1') throw new UnsupportedCapability();
  if (typeof row[16] !== 'boolean' || typeof row[6] !== 'string' || !digest.test(row[6]) || typeof row[13] !== 'string' || !digest.test(row[13]) || !identity(row[14])) throw new IntegrityViolation();
  const size = exact_integer(row[7]); const start = exact_integer(row[9]); const end = exact_integer(row[10]); const chunkBytes = exact_integer(row[11]);
  if (size < 1 || size > 16777216 || start >= end || end > size || chunkBytes < 1 || chunkBytes > 32768 || end-start !== chunkBytes || start !== candidate.start_byte || end !== candidate.end_byte || row[13] !== candidate.text_sha256) throw new IntegrityViolation();
  const excerpt = row[12];
  if (typeof excerpt !== 'string' || excerpt.length > 32768 || /[\uD800-\uDFFF\0]/u.test(excerpt) || Buffer.byteLength(excerpt) !== chunkBytes || sha(excerpt) !== row[13]) throw new IntegrityViolation();
  if (size > budget) {
    if (row[8] !== null) throw new IntegrityViolation();
    return Object.freeze({ state: 'budget_exhausted', evidence: null, source_bytes: 0, stale: false });
  }
  const text = row[8];
  if (typeof text !== 'string' || text.length > size || typeof excerpt !== 'string' || /[\uD800-\uDFFF\0]/u.test(text) || /[\uD800-\uDFFF\0]/u.test(excerpt)) throw new IntegrityViolation();
  const raw = Buffer.from(text); const chunk = Buffer.from(excerpt);
  if (raw.length !== size || sha(raw) !== row[6] || chunk.length !== chunkBytes || sha(chunk) !== row[13]) throw new IntegrityViolation();
  let slice: string;
  try { slice = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(raw.subarray(start,end)); } catch { throw new IntegrityViolation(); }
  if (slice !== excerpt) throw new IntegrityViolation();
  const evidence: Evidence = { evidence_id: sha(JSON.stringify(['cragkit.evidence.v1',candidate.tenant_id,candidate.collection,candidate.document_id,candidate.revision_id,candidate.chunk_id,String(start),String(end),row[13]])), collection: candidate.collection, document_id: candidate.document_id, revision_id: candidate.revision_id, chunk_id: candidate.chunk_id, source_locator: row[14], start_byte: start, end_byte: end, text: excerpt, source_sha256: row[6], text_sha256: row[13] };
  return Object.freeze({ state:'verified', evidence:Object.freeze(evidence), source_bytes:size, stale:!row[16] });
}
