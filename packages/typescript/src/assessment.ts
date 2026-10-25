import { createHash } from 'node:crypto';
import { z } from 'zod';
import { render_context } from './context.js';
import { InvalidRequest } from './errors.js';
import { EvidenceSchema, FacetSchema, type Evidence, type Facet } from './results.js';
import { deep_freeze, identity, integer, text, valid_native_json } from './shared.js';

const hash = (value: string) => createHash('sha256').update(value, 'utf8').digest('hex');
const digest = z.string().regex(/^[0-9a-f]{64}$/);
const Anchor = z.strictObject({
  claim_id: identity, collection: identity, document_id: identity, revision_id: identity,
  source_sha256: digest, start_byte: integer(0, Number.MAX_SAFE_INTEGER),
  end_byte: integer(0, Number.MAX_SAFE_INTEGER), text: text(32768, false),
}).refine(value => value.end_byte > value.start_byte && Buffer.byteLength(value.text) === value.end_byte - value.start_byte);
const PolicyFacet = z.strictObject({
  facet_id: identity, question: text(2048), required: z.boolean(), absence: z.enum(['missing', 'unknown']),
  anchors: z.array(Anchor).max(16).refine(values => new Set(values.map(value => JSON.stringify(value))).size === values.length),
});
const Policy = z.strictObject({
  policy_id: identity, version: identity, query_sha256: digest, facets: z.array(PolicyFacet).min(1).max(32),
}).refine(value => Buffer.byteLength(`${value.policy_id}:${value.version}`) <= 256
  && new Set(value.facets.map(facet => facet.facet_id)).size === value.facets.length
  && value.facets.reduce((sum, facet) => sum + facet.anchors.length, 0) <= 64
  && value.facets.reduce((sum, facet) => sum + facet.anchors.reduce((bytes, anchor) => bytes + Buffer.byteLength(anchor.text), 0), 0) <= 262144);

function evidence_snapshot(input: unknown): readonly Evidence[] {
  render_context(input);
  return (input as unknown[]).map(item => EvidenceSchema.parse(item));
}

/** Validate wire consistency and emitted references; this does not judge source truth. */
export function validate_assessment(evidence: unknown, facets: unknown): readonly Facet[] {
  try {
    const items = evidence_snapshot(evidence);
    if (!valid_native_json(facets) || !Array.isArray(facets) || facets.length > 32) throw new InvalidRequest();
    const normalized = facets.map(value => FacetSchema.parse(value));
    const ids = new Set(items.map(item => item.evidence_id));
    if (new Set(normalized.map(facet => facet.facet_id)).size !== normalized.length
      || normalized.some(facet => facet.evidence_ids.some(id => !ids.has(id)))) throw new InvalidRequest();
    return deep_freeze(normalized);
  } catch { throw new InvalidRequest(); }
}

export type Assessment = Readonly<{facets: readonly Facet[]; status: 'sufficient' | 'partial' | 'insufficient'; policy: string}>;

/** Assess only exact emitted source spans against a trusted, query-bound policy. */
export function assess_evidence(query: unknown, evidence: unknown, policy: unknown = null): Assessment {
  try {
    const original = text(16384).parse(query);
    const items = evidence_snapshot(evidence);
    let facets: readonly Facet[], policyVersion = 'unassessed.v0';
    if (policy === null) {
      facets = [FacetSchema.parse({facet_id: 'query', question: 'Original query', required: true,
        state: 'unknown', evidence_ids: [], assessment_method: 'none', assessment_version: '0'})];
    } else {
      if (!valid_native_json(policy)) throw new InvalidRequest();
      const configured = Policy.parse(policy);
      if (configured.query_sha256 !== hash(original)) throw new InvalidRequest();
      policyVersion = `${configured.policy_id}:${configured.version}`;
      facets = configured.facets.map(facet => {
        const declared = new Set(facet.anchors.map(anchor => anchor.claim_id));
        const matched = new Set<string>(), references: string[] = [];
        for (const item of items) {
          let found = false;
          for (const anchor of facet.anchors) {
            if (item.collection !== anchor.collection || item.document_id !== anchor.document_id
              || item.revision_id !== anchor.revision_id || item.source_sha256 !== anchor.source_sha256
              || item.start_byte > anchor.start_byte || item.end_byte < anchor.end_byte) continue;
            const slice = Buffer.from(item.text).subarray(anchor.start_byte - item.start_byte, anchor.end_byte - item.start_byte);
            if (!slice.equals(Buffer.from(anchor.text))) continue;
            matched.add(anchor.claim_id); found = true;
          }
          if (found) references.push(item.evidence_id);
        }
        const state = matched.size === 0 ? facet.absence
          : matched.size >= 2 && references.length >= 2 ? 'conflicting'
          : declared.size > 1 ? 'unknown' : 'supported';
        return FacetSchema.parse({facet_id: facet.facet_id, question: facet.question, required: facet.required,
          state, evidence_ids: references, assessment_method: 'reviewed-span', assessment_version: configured.version});
      });
    }
    const required = facets.filter(facet => facet.required);
    const status = items.length === 0 ? 'insufficient'
      : required.length > 0 && required.every(facet => facet.state === 'supported') ? 'sufficient' : 'partial';
    return deep_freeze({facets, status, policy: policyVersion});
  } catch { throw new InvalidRequest(); }
}
