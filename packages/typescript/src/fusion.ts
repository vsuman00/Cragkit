/** Bounded deterministic weighted reciprocal rank fusion (IF-r1). */
import { z } from 'zod';
import { DenseCandidateSchema, IdentifierCandidateSchema } from './postgres-session.js';
import { IntegrityViolation, InvalidRequest } from './errors.js';
import { valid_native_json } from './shared.js';

const Base = z.strictObject({
  tenant_id: z.string(), collection: z.string(), document_id: z.string(), revision_id: z.string(),
  generation_id: z.string(), chunk_id: z.string(),
  start_byte: z.number().int().min(0).max(Number.MAX_SAFE_INTEGER),
  end_byte: z.number().int().positive().max(Number.MAX_SAFE_INTEGER),
  text_sha256: z.string().regex(/^[0-9a-f]{64}$/), score: z.number().finite().min(0),
});
const schemas = { dense: DenseCandidateSchema, lexical: Base, identifier: IdentifierCandidateSchema };
type Family = keyof typeof schemas;
type Candidate = z.infer<typeof Base> & {
  embedding_profile?: string; identifier_profile?: string; score_direction?: string;
};
export interface Contribution {
  facet_id: string;
  family: Family;
  weight: number;
  rank: number;
  list_id: string;
  raw_score: number;
  score_direction: string;
  profile: string;
}
export interface FusedCandidate {
  candidate: Candidate;
  score: number;
  contributions: Contribution[];
}
type FamilyWeight = { facet: string; family: Family; weight: number };
type Vote = { facet: string; family: Family; rank: number; list_id: string; candidate: Candidate };

const fields = ['tenant_id', 'collection', 'document_id', 'revision_id', 'chunk_id'] as const;
const immutable = ['generation_id', 'start_byte', 'end_byte', 'text_sha256'] as const;
const compare = (a: string, b: string): number => Buffer.compare(Buffer.from(a), Buffer.from(b));
const identity = (candidate: Candidate): string => JSON.stringify(fields.map(field => candidate[field]));
const familyKey = (facet: string, family: Family): string => JSON.stringify([facet, family]);
const familyOrder = (a: { facet: string; family: string }, b: { facet: string; family: string }): number =>
  compare(a.facet, b.facet) || compare(a.family, b.family);
// JavaScript's $ also matches before a final newline; require the actual end here.
const ascii = z.string().min(1).max(128).regex(/^[!-~]+(?![\s\S])/);
const Envelope = z.strictObject({
  list_id: ascii, facet_id: ascii, family: z.enum(['dense', 'lexical', 'identifier']),
  weight: z.number().finite().positive().max(1e6), candidates: z.array(z.unknown()).max(1000),
});

function dataArray(value: unknown, maximum: number): value is unknown[] {
  return Array.isArray(value) && Object.getPrototypeOf(value) === Array.prototype && value.length <= maximum
    && Object.keys(value).length === value.length
    && Object.keys(value).every((key, index) => key === String(index))
    && Object.getOwnPropertySymbols(value).length === 0
    && Object.entries(Object.getOwnPropertyDescriptors(value)).every(([key, descriptor]) =>
      key === 'length' || ('value' in descriptor && descriptor.enumerable));
}

function snapshot(value: unknown, family: Family): Candidate {
  if (!valid_native_json(value)) throw new InvalidRequest();
  const schema = schemas[family];
  const parsed = schema.safeParse(value);
  if (!parsed.success || Object.keys(value as object).length !== Object.keys(schema.shape).length) {
    throw new InvalidRequest();
  }
  const candidate = parsed.data;
  const malformedIdentity = [...fields, 'generation_id' as const].some(field =>
    !/[^ \t\r\n\f\v]/.test(candidate[field]) || candidate[field].includes('\0')
    || Buffer.byteLength(candidate[field]) > (field === 'collection' ? 128 : 256));
  if (malformedIdentity || candidate.end_byte <= candidate.start_byte) throw new InvalidRequest();
  return candidate;
}

function snapshotBranch(item: unknown): z.infer<typeof Envelope> {
  // Inspect descriptors before Zod reads caller input. Validate each candidate
  // separately so the general JSON node ceiling does not reject a bounded list.
  if (item === null || typeof item !== 'object' || Array.isArray(item)
      || (Object.getPrototypeOf(item) !== Object.prototype && Object.getPrototypeOf(item) !== null)) {
    throw new InvalidRequest();
  }
  const descriptors = Object.getOwnPropertyDescriptors(item);
  if (Object.getOwnPropertySymbols(item).length
      || Object.values(descriptors).some(descriptor => !('value' in descriptor) || !descriptor.enumerable)) {
    throw new InvalidRequest();
  }
  const metadata = Object.fromEntries(Object.entries(descriptors)
    .filter(([key]) => key !== 'candidates').map(([key, descriptor]) => [key, descriptor.value]));
  if (!valid_native_json(metadata) || !dataArray(descriptors.candidates?.value, 1000)) {
    throw new InvalidRequest();
  }
  const parsed = Envelope.safeParse(item);
  if (!parsed.success) throw new InvalidRequest();
  return { ...parsed.data, candidates: parsed.data.candidates.map(value => snapshot(value, parsed.data.family)) };
}

export function fuse(input: unknown, options: { k?: number; max_candidates?: number } = {}): FusedCandidate[] {
  if (options === null || typeof options !== 'object' || Array.isArray(options) || !valid_native_json(options)
      || Object.keys(options).some(key => key !== 'k' && key !== 'max_candidates')) throw new InvalidRequest();
  const { k = 60, max_candidates = 200 } = options;
  if (!Number.isInteger(k) || k < 0 || k > 1e6 || !Number.isInteger(max_candidates)
      || max_candidates < 1 || max_candidates > 1000 || !dataArray(input, 36)) throw new InvalidRequest();

  const weights = new Map<string, FamilyWeight>();
  const listIds = new Set<string>();
  const branches = input.map(item => {
    const branch = snapshotBranch(item);
    if (listIds.has(branch.list_id)) throw new InvalidRequest();
    listIds.add(branch.list_id);
    const key = familyKey(branch.facet_id, branch.family);
    const previous = weights.get(key);
    if (previous && previous.weight !== branch.weight) throw new InvalidRequest();
    weights.set(key, { facet: branch.facet_id, family: branch.family, weight: branch.weight });
    // snapshotBranch validated each candidate using this family's complete schema.
    return { ...branch, candidates: branch.candidates as Candidate[] };
  });

  const union = new Map<string, { candidate: Candidate; votes: Map<string, Vote> }>();
  for (const branch of branches.sort((a, b) => compare(a.list_id, b.list_id))) {
    const seen = new Set<string>();
    for (const candidate of branch.candidates) {
      const id = identity(candidate);
      let entry = union.get(id);
      const previous = entry?.candidate;
      if (previous && immutable.some(field => previous[field] !== candidate[field])) throw new IntegrityViolation();
      if (!entry) {
        entry = { candidate, votes: new Map() };
        union.set(id, entry);
        if (union.size > max_candidates) throw new InvalidRequest();
      }
      if (seen.has(id)) continue;
      seen.add(id);
      const key = familyKey(branch.facet_id, branch.family);
      const oldVote = entry.votes.get(key);
      if (!oldVote || seen.size < oldVote.rank
          || (seen.size === oldVote.rank && compare(branch.list_id, oldVote.list_id) < 0)) {
        entry.votes.set(key, {
          facet: branch.facet_id, family: branch.family, rank: seen.size, list_id: branch.list_id, candidate,
        });
      }
    }
  }
  const totals = new Map<string, number>();
  for (const weight of [...weights.values()].sort(familyOrder)) {
    totals.set(weight.facet, (totals.get(weight.facet) ?? 0) + weight.weight);
  }
  const results: FusedCandidate[] = [];
  for (const entry of union.values()) {
    let score = 0;
    const contributions: Contribution[] = [];
    for (const vote of [...entry.votes.values()].sort(familyOrder)) {
      const weight = weights.get(familyKey(vote.facet, vote.family))!.weight / totals.get(vote.facet)!;
      const contribution = weight / (k + vote.rank);
      if (weight === 0 || contribution === 0) throw new InvalidRequest();
      score += contribution;
      contributions.push({
        facet_id: vote.facet, family: vote.family, weight, rank: vote.rank, list_id: vote.list_id,
        raw_score: vote.candidate.score, score_direction: vote.candidate.score_direction ?? 'higher_is_better',
        profile: vote.candidate.embedding_profile ?? vote.candidate.identifier_profile ?? 'native_fts.v1',
      });
    }
    results.push({ candidate: entry.candidate, score, contributions });
  }
  return results.sort((a, b) => b.score - a.score
    || fields.map(field => compare(a.candidate[field], b.candidate[field])).find(order => order !== 0) || 0);
}
