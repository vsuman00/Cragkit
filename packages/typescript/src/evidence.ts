import { assess_evidence, type Assessment } from './assessment.js';
import { pack_evidence, type PackedEvidence, type PackingOptions } from './packing.js';
import { check_options } from './postgres-pool.js';
import { deep_freeze, valid_native_json } from './shared.js';
import { InvalidRequest } from './errors.js';

export type EvidenceOptions = Omit<PackingOptions, 'facet_evidence'> & {policy?: unknown; rebalance?: boolean};
export type AssessedEvidence = PackedEvidence & Assessment & {readonly rebalance_count: number};

export async function pack_and_assess(query: unknown, evidence: unknown, sources: unknown, options: EvidenceOptions): Promise<AssessedEvidence> {
  if (!options || Object.getPrototypeOf(options) !== Object.prototype || Object.getOwnPropertySymbols(options).length) throw new InvalidRequest();
  const fields = Object.getOwnPropertyDescriptors(options);
  if (Object.entries(fields).some(([key, field]) => !['deadline','signal','max_tokens','reserve','counter','counting_mode','surrounding_bytes','policy','rebalance'].includes(key) || !('value' in field) || !field.enumerable)) throw new InvalidRequest();
  const {policy = null, rebalance = false, ...packing} = options;
  if (typeof rebalance !== 'boolean' || !valid_native_json(policy) || !valid_native_json(sources)) throw new InvalidRequest();
  check_options(packing);
  const policySnapshot = structuredClone(policy), sourceSnapshot = structuredClone(sources);
  const seeds = assess_evidence(query, evidence, policySnapshot);
  // Rendering during assessment validates and snapshots evidence before any yield.
  const evidenceSnapshot = structuredClone(evidence);
  const required = seeds.facets.filter(facet => facet.required);
  const priority = required.map(facet => [...facet.evidence_ids]);
  let packed = await pack_evidence(evidenceSnapshot, sourceSnapshot, {...packing, facet_evidence: priority});
  check_options(packing);
  let assessed = assess_evidence(query, packed.evidence, policySnapshot), rebalance_count = 0;
  check_options(packing);
  const unresolved = assessed.facets.filter(facet => facet.required && facet.state !== 'supported');
  const unresolvedIds = new Set(unresolved.map(facet => facet.facet_id));
  if (rebalance && policySnapshot !== null && required.some(facet => unresolvedIds.has(facet.facet_id) && facet.evidence_ids.length)) {
    rebalance_count = 1;
    const reordered = [...required.filter(facet => unresolvedIds.has(facet.facet_id)), ...required.filter(facet => !unresolvedIds.has(facet.facet_id))].map(facet => [...facet.evidence_ids]);
    const candidate = await pack_evidence(evidenceSnapshot, sourceSnapshot, {...packing, facet_evidence: reordered});
    check_options(packing);
    const candidateAssessment = assess_evidence(query, candidate.evidence, policySnapshot);
    check_options(packing);
    const quality = (assessment: Assessment, pack: PackedEvidence) => [assessment.facets.filter(facet => facet.required && facet.state === 'supported').length, -assessment.facets.filter(facet => facet.required && facet.state === 'conflicting').length, pack.evidence.length];
    const before = quality(assessed, packed), after = quality(candidateAssessment, candidate);
    const firstDifference = after.findIndex((value, index) => value !== before[index]);
    if (firstDifference >= 0 && after[firstDifference] > before[firstDifference]) { packed = candidate; assessed = candidateAssessment; }
  }
  check_options(packing);
  return deep_freeze({...packed, ...assessed, rebalance_count});
}
