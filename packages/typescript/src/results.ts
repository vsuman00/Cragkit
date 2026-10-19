import { createHash } from 'node:crypto';
import { z } from 'zod';
import { InvalidRequest } from './errors.js';
import { deep_freeze, identity, integer, safe_number, text, valid_native_json } from './shared.js';

const unique = (values: readonly string[]) => new Set(values).size === values.length;
const ids = (maximum: number) => z.array(identity).max(maximum).refine(unique).default([]);
const hash = z.string().regex(/^[0-9a-f]{64}$/);
const guarded = <T extends z.ZodType>(schema: T) => z.custom<unknown>(valid_native_json).pipe(schema).transform(deep_freeze);

const EvidenceObject = z.strictObject({
  evidence_id: identity, collection: identity, document_id: identity, revision_id: identity,
  chunk_id: identity, source_locator: identity,
  start_byte: integer(0, Number.MAX_SAFE_INTEGER), end_byte: integer(0, Number.MAX_SAFE_INTEGER),
  text: text(32768, false).refine(value => value.length > 0),
  source_sha256: hash, text_sha256: hash,
}).refine(value => value.end_byte > value.start_byte
  && value.end_byte - value.start_byte === Buffer.byteLength(value.text, 'utf8')
  && createHash('sha256').update(value.text, 'utf8').digest('hex') === value.text_sha256);
export const EvidenceSchema = guarded(EvidenceObject);

const FacetObject = z.strictObject({
  facet_id: identity, question: text(2048),
  state: z.enum(['supported', 'missing', 'unknown', 'conflicting']),
  required: z.boolean().default(true), evidence_ids: ids(64),
  assessment_method: identity.default('none'), assessment_version: identity.default('0'),
}).refine(value => (value.state === 'unknown' || value.assessment_method !== 'none')
  && (value.state !== 'supported' || value.evidence_ids.length > 0)
  && (value.state !== 'conflicting' || value.evidence_ids.length >= 2)
  && (value.state !== 'missing' || value.evidence_ids.length === 0));
export const FacetSchema = guarded(FacetObject);

const LimitationObject = z.strictObject({
  code: z.enum(['coverage_unknown', 'incomplete_facets', 'stale_evidence', 'truncated_evidence', 'budget_exhausted', 'degraded_search']),
  facet_ids: ids(32), evidence_ids: ids(64),
});
export const LimitationSchema = guarded(LimitationObject);
const StageDurationObject = z.strictObject({ stage: identity, duration_ms: safe_number.min(0).max(300000) });
export const StageDurationSchema = guarded(StageDurationObject);
const UsageObject = z.strictObject({
  attempt_count: integer(0, 10).default(0), provider_calls: integer(0, 1000).default(0),
  provider_input_tokens: integer(0, Number.MAX_SAFE_INTEGER).nullable().default(null),
  provider_output_tokens: integer(0, Number.MAX_SAFE_INTEGER).nullable().default(null),
  cost_usd: safe_number.min(0).max(1000000).nullable().default(null),
  cost_kind: z.enum(['unknown', 'estimated', 'known']).default('unknown'),
  context_tokens: integer(0, 1000000).nullable().default(null),
  context_counting: z.enum(['unknown', 'estimated', 'strict']).default('unknown'),
  stage_durations: z.array(StageDurationObject).max(32).default([]),
}).refine(value => (value.cost_kind === 'unknown') === (value.cost_usd === null)
  && (value.context_counting === 'unknown') === (value.context_tokens === null)
  && unique(value.stage_durations.map(stage => stage.stage)));
export const UsageSchema = guarded(UsageObject);
const VersionsObject = z.strictObject({
  engine: identity.default('0.0.0'), policy: identity.default('unassessed.v0'),
  model: identity.nullable().default(null), tokenizer: identity.nullable().default(null), index: identity.nullable().default(null),
});
export const VersionsSchema = guarded(VersionsObject);

const ResultObject = z.strictObject({
  schema_version: z.literal('0.1').default('0.1'), request_id: identity,
  status: z.enum(['sufficient', 'partial', 'insufficient']), execution: z.enum(['complete', 'degraded']).default('complete'),
  evidence: z.array(EvidenceObject).max(64).default([]), facets: z.array(FacetObject).max(32).default([]),
  context: text(262144, false).default(''), usage: UsageObject.prefault({}),
  limitations: z.array(LimitationObject).max(32).default([]), trace_id: identity.nullable().default(null),
  versions: VersionsObject.prefault({}),
}).refine(value => {
  const evidenceIds = value.evidence.map(item => item.evidence_id);
  const facetIds = value.facets.map(item => item.facet_id);
  if (!unique(evidenceIds) || !unique(facetIds)) return false;
  const evidenceSet = new Set(evidenceIds);
  const facetSet = new Set(facetIds);
  if (value.facets.some(facet => facet.evidence_ids.some(id => !evidenceSet.has(id)))) return false;
  if (value.limitations.some(limit => limit.evidence_ids.some(id => !evidenceSet.has(id))
    || limit.facet_ids.some(id => !facetSet.has(id)))) return false;
  const digests = new Map<string, string>();
  for (const item of value.evidence) {
    const key = JSON.stringify([item.collection, item.document_id, item.revision_id]);
    const existing = digests.get(key);
    if (existing !== undefined && existing !== item.source_sha256) return false;
    digests.set(key, item.source_sha256);
  }
  if (value.execution === 'degraded' && !value.limitations.some(limit => limit.code === 'degraded_search')) return false;
  if (value.usage.context_counting === 'strict' && value.versions.tokenizer === null) return false;
  if (value.status === 'partial' && value.evidence.length === 0) return false;
  if (value.status === 'sufficient') {
    const required = value.facets.filter(facet => facet.required);
    if (required.length === 0 || required.some(facet => facet.state !== 'supported') || value.versions.policy === 'unassessed.v0') return false;
  }
  return true;
});
export const ResultSchema = guarded(ResultObject);
export type RetrievalResult = z.infer<typeof ResultSchema>;
export type Evidence = z.infer<typeof EvidenceSchema>;
export type Facet = z.infer<typeof FacetSchema>;
export type Usage = z.infer<typeof UsageSchema>;
export type Versions = z.infer<typeof VersionsSchema>;
export type Limitation = z.infer<typeof LimitationSchema>;
export type StageDuration = z.infer<typeof StageDurationSchema>;
export function parse_result(input: unknown): RetrievalResult {
  try { return ResultSchema.parse(input); } catch { throw new InvalidRequest(); }
}
