# V3: Evidence selection and honest coverage

Status: in progress. V3-01 defines the reranker contract and shortlist; runtime adapters and later evidence-selection work remain pending. Progress is tracked only in [todo.md](../todo.md).

## Outcome and boundaries

Returned excerpts fit a defined context representation and expose supported, missing, unknown and conflicting facets.

Entry: V2 complete with a measured hybrid baseline.

Architecture mapping: Architecture phase 3; sections 8-10, 12-13.

Artifact goal: Local 0.3.0-alpha.1 candidate.

Follow the [master plan](../plan.md), [learning workflow](../LEARNING.md), and [edge-case inventory](../EDGE_CASES.md). Respect task dependency order and run one language suite at a time on the development machine. Independent authorized agent lanes follow [the coordination protocol](../../docs/agents/WORKFLOW.md); dependent work keeps one writer. A task has a target scope of 1-5 implementation/test files; if it expands beyond one focused session, split it into child tasks before proceeding. Paths below identify expected areas, not permission to rewrite entire directories.

## Tasks

### V3-01: Reranker contract and shortlist

Dependency: V2-08. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Document model score semantics, input limits, truncation rules and optional local/API dependencies using a small development sample.

Acceptance: No score is renamed a truth probability; configuration records model/version and raw score direction.

Verification: Probe one candidate configuration or recorded responses; record compatibility and resource observations.

Learning exercise: Explain a logit, rank and calibrated decision as different concepts.

Expected areas: `docs/decisions/`, `reranker contract fixtures`.

### V3-02: Bounded reranking adapters

Dependency: V3-01. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement the chosen adapter contract in both runtimes with a hard candidate cap and nonblocking CPU-worker boundary where needed.

Acceptance: Malformed scores, missing candidate IDs and duplicates fail; optional fallback is visible and all calls observe cancellation.

Verification: Use fake rerankers with out-of-order, truncated and invalid outputs, plus an explicit live comparison.

Learning exercise: Explain why a high score on one passage cannot answer a two-part question.

Expected areas: `Both reranker adapters`, `shared ranking tests`.

### V3-03: Tokenizer and renderer contract

Dependency: V3-02. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Choose one supported tokenizer/renderer pair and define exactly which context bytes, citations and wrapper allowance are counted.

Acceptance: Strict counting rejects unsupported tokenizers; estimated mode is labelled; a too-small mandatory envelope has a typed error.

Verification: Compare shared serialized fixtures in both runtimes, including escapes, Unicode and citation labels.

Learning exercise: Count tokens before and after adding a citation wrapper.

Expected areas: `Both token-counter adapters`, `renderer fixtures`.

### Checkpoint V3-C1

After tasks through V3-03, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V3-04: Extractive packing

Dependency: V3-03. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement overlap merging, surrounding-context expansion and facet-aware span selection using authorized immutable revisions.

Acceptance: Every excerpt remains an exact source slice; disjoint spans stay visibly separate and final rendered context fits the selected limit.

Verification: Test overlapping chunks, negation, code, headings, tiny budgets and UTF-8 cut boundaries.

Learning exercise: Explain how a true quote can become misleading when its context is removed.

Expected areas: `Both packers`, `source and budget fixtures`.

### V3-05: Facet assessment policy

Dependency: V3-04. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Define and implement a conservative assessor contract with required facets, evidence IDs, conflicts and unknown states; select a first method from development labels.

Acceptance: Unknown/missing/conflicting required evidence cannot produce sufficient; invented evidence IDs are rejected.

Verification: Review labelled one-facet and two-facet questions; test contradictory applicable revisions and malformed judge output.

Learning exercise: Label the evidence needed to answer each part of a question.

Expected areas: `Coverage fixtures`, `both assessor paths`, `policy record`.

### V3-06: Post-packing reassessment

Dependency: V3-05. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Assess coverage using only emitted evidence and implement one bounded rebalance attempt if configured.

Acceptance: Dropping the only supporting span changes the result to partial/insufficient; reassessment cannot recursively retry forever.

Verification: Construct a budget that removes one facet; verify status and limitations match the actual returned text.

Learning exercise: Explain why pre-compression coverage can be misleading.

Expected areas: `Both pack/assess orchestrators`, `multi-facet tests`.

### Checkpoint V3-C2

After tasks through V3-06, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V3-07: Calibrate evidence policy

Dependency: V3-06. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Evaluate thresholds/methods against human-reviewed development labels; record false-sufficient, abstention and conflict errors.

Acceptance: Policy/model versions and denominators are recorded; thresholds are selected on development data rather than held-out examples.

Verification: Manually inspect false-sufficient cases and compare reranked hybrid with the V2 baseline.

Learning exercise: Explain false acceptance versus excessive abstention.

Expected areas: `evaluation/policies/`, `evaluation/reports/V3/`.

### V3-08: Evidence release checkpoint

Dependency: V3-07. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Run shared source, authorization, token and coverage fixtures from built artifacts; update examples to explain limitations.

Acceptance: Both runtimes return equivalent deterministic outputs; local-model extras are absent from core installation.

Verification: Install artifacts cleanly and run a partial-result example plus a strict-budget example.

Learning exercise: Demonstrate why citation fidelity does not establish source truth.

Expected areas: `Examples`, `artifact smoke tests`, `V3 report`.

### Checkpoint V3-C3

After tasks through V3-08, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

## Version exit

Demonstrate: Returned excerpts fit a defined context representation and expose supported, missing, unknown and conflicting facets. Record results for owned edge cases and any unresolved operational/live-provider checks. Build the stated local artifact when applicable. A planned feature, fake-provider pass or unrun hosted CI job must not be reported as production evidence.

If blocked, reduce the failing case to one document/request and preserve the current working slice. Keep required scope checks, citation integrity and honest statuses. Escalate only the missing decision or external dependency; do not redesign the project to bypass it.
