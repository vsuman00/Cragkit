# AS-r1: Conservative reviewed-span assessment

For example, a reviewed support anchor for a retry limit can be covered while the required delay anchor is absent. The result remains partial even if the covered passage ranks first.

## First method and scope

V3's first assessor is a deterministic lookup of application-reviewed source anchors, `reviewed-span.v1`. It is useful for curated reference material and development calibration. It does not generalize labels to unseen text, infer truth from a model score or certify that a corpus is complete. Routine checks require no model call. Human-reviewed development annotations supply the initial method examples; evaluation on those same anchors is explicitly in-sample.

The caller supplies a trusted policy bound to the SHA-256 of the exact original query. Policy configuration is outside agent-editable request data. No policy means one required unknown query facet, never sufficient. Reranking affects order; it cannot establish a facet's state.

## Policy shape

All objects reject unknown keys. Required policy fields: `policy_id`, `version`, `query_sha256`, `facets`. IDs obey existing identity bounds; `policy_id:version` must fit 256 UTF-8 bytes, and the digest is lowercase SHA-256. Facets number 1-32 and have unique IDs. Each has exactly `facet_id`, `question`, `required`, `absence`, `anchors`; question is nonblank and at most 2,048 UTF-8 bytes, required is boolean, absence is `missing` or `unknown`. Absence describes the configured method's conclusion when no reviewed anchor is emitted; it does not prove global absence.

Each facet has at most 16 anchors; a policy has at most 64 anchors and 262,144 anchor-text UTF-8 bytes. Anchor fields are exactly `claim_id`, `collection`, `document_id`, `revision_id`, `source_sha256`, `start_byte`, `end_byte`, `text`. Identities follow existing bounds, offsets are safe nonnegative integers, end is greater than start, and UTF-8 text length equals the span length with a 32,768-byte cap. Anchor text contains valid Unicode scalar values and is preserved exactly. Duplicate anchors within a facet are invalid. All collection values used here obey the existing Evidence identity bound.

`claim_id` groups compatible alternatives. Different claim IDs in the same facet declare mutually incompatible assertions according to the reviewer, including applicability. The assessor does not decide whether historical revisions are applicable; the trusted policy must encode that decision. A query digest mismatch is `InvalidRequest`, preventing reuse of a policy for another question. Configuration, evidence and facet arrays are copied/revalidated before use.

## Assessment

`query` uses the existing nonblank 16,384 UTF-8 byte bound and valid scalar values. `assess_evidence(query, evidence, policy=None)` validates at most 64 Evidence items using TK-r1's renderer boundary. Matching requires the same collection/document/revision/source digest, containment of the entire anchor within an emitted span, and equality of the exact UTF-8 slice at the anchor's offset. Partial overlap and merely matching words are insufficient.

One matching claim group yields supported only when the policy declares no incompatible applicable claim group for that facet, referencing matching emitted IDs in input order. If the policy declares multiple incompatible groups but only one is emitted, return unknown: omitting a known contradiction cannot create sufficient coverage. Two or more claim groups with at least two distinct emitted IDs yield conflicting. Multiple incompatible groups found only in one emitted item yield unknown, since the wire contract requires two references for conflicting. No matches use the policy's declared absence with no evidence references. Facets retain their configured required flag and carry method `reviewed-span` and the policy version.

The return contains `facets`, `status`, and `policy` (`policy_id` plus `:` plus version). Status is sufficient only with emitted evidence and at least one required facet, all required facets supported. Otherwise it is partial when evidence exists and insufficient when none exists. Missing, unknown or conflicting required facets cannot produce sufficient. No policy returns `policy: unassessed.v0`, one unknown `query` facet whose question is `Original query`, with method `none`/version `0` and the same partial/insufficient rule.

`validate_assessment(evidence, facets)` validates the existing wire Facet shape, at most 32 unique facet IDs and references only actual emitted Evidence IDs. It rejects malformed output and invented references as `InvalidRequest`. It checks consistency, not the semantic correctness of an external judge. Assessment itself uses the built-in deterministic method above and does not dispatch a judge.

## Limits and integration

Assessment is bounded synchronous work over already authorized emitted text. It neither searches nor fetches sources. V3-06 must reassess after packing and may perform at most one configured rebalance. Standalone assessment does not confer authorization; the caller must verify source integrity and scope before release. A genuine quote can still be outdated or false, and a reviewed annotation can be wrong.

Applicability is a caller responsibility: select and version the policy for the bound tenant, filters and time. Query identity alone cannot make old anchors current. Compatible anchors are alternatives; jointly necessary premises require separate required facets. Necessary qualifiers must be included in reviewed anchors. Unannotated contradictions are not detected. An anchor split between disjoint emitted spans does not match. Development results measure in-sample lookup behavior, not general semantic quality.
