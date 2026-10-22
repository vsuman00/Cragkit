# V2: Hybrid retrieval

Status: V2-01 design decision complete: hosted opt-in OpenAI text-embedding-3-small, 1536 dimensions, with routine fake providers and live access disabled until separately configured. Metadata/synthetic interface evidence is distinct from unrun live verification. V2-02 Python embedding boundary has passed its local deterministic checks. V2-03 TypeScript embedding parity and V2-C1 have passed local deterministic/conformance/artifact checks. V2-04 vector generations/reindex is next; hybrid retrieval and live-provider validation remain unimplemented/unrun. Progress is tracked only in [todo.md](../todo.md).

## Outcome and boundaries

Both runtimes combine dense and lexical evidence under the same constraints and return reproducible rank-fusion fixtures.

Entry: V1 complete, including authorization and lifecycle tests.

Architecture mapping: Architecture phase 2; sections 6-8, 12-13.

Artifact goal: Local 0.2.0-alpha.1 candidate; no automatic publication.

Follow the [master plan](../plan.md), [learning workflow](../LEARNING.md), and [edge-case inventory](../EDGE_CASES.md). Respect task dependency order and run one language suite at a time on the development machine. Independent authorized agent lanes follow [the coordination protocol](../../docs/agents/WORKFLOW.md); dependent work keeps one writer. A task has a target scope of 1-5 implementation/test files; if it expands beyond one focused session, split it into child tasks before proceeding. Paths below identify expected areas, not permission to rewrite entire directories.

## Tasks

### V2-01: Embedding profile decision

Dependency: V1-12. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Choose one initial embedding profile after a small compatibility, resource and license probe; keep fake embeddings for routine tests.

Acceptance: Document model identity, dimension, normalization, allowed provider and cost policy; live and fake results are labelled separately.

Verification: Embed a tiny allowed sample only when configured; validate response shape and resource use.

Learning exercise: Explain why vectors from different models cannot be mixed.

Expected areas: `docs/decisions/`, `embedding fixtures`, `adapter config`.

Decision record: [ADR 0001](../../docs/decisions/0001-embedding-profile.md) records the owner-selected profile, local comparison, resource limits, disclosure/cost gates and outstanding live compatibility evidence. Acceptance of the profile is not adapter implementation or authorization to send data.

### V2-02: Python embedding adapter

Dependency: V2-01. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement bounded query/batch embeddings, finite-value checks, timeout behavior and profile metadata in Python.

Acceptance: Wrong dimensions and malformed provider responses fail; batches respect item and byte/token limits.

Verification: Use deterministic fake responses, transport failures and cancellation; run a small optional live smoke test separately.

Learning exercise: Explain batching and provider validation.

Expected areas: `Python embedding adapter`, `provider tests`.

### V2-03: TypeScript embedding adapter

Dependency: V2-02. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement the same embedding and error contract in TypeScript with shared vectors and usage fixtures.

Acceptance: Both runtimes accept/reject the same payloads; missing usage is marked unknown.

Verification: Run shared fixtures and compare normalized adapter output.

Learning exercise: Explain how Zod validates data returned by a third-party service.

Expected areas: `TypeScript embedding adapter`, `shared tests`.

### Checkpoint V2-C1

After tasks through V2-03, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V2-04: Vector generations and reindex

Dependency: V2-03. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Add profile-specific vector storage, bounded staging writes and shadow-generation publication.

Acceptance: Queries reject profile mismatch; incomplete vectors remain invisible; failed reindex preserves the previous active generation.

Verification: Interrupt reindex, change dimension and attempt mixed-profile retrieval; verify safe publication.

Learning exercise: Explain shadow indexes and the cost of a model change.

Expected areas: `PostgreSQL vector migration`, `both generation integration paths`.

### V2-05: Scoped dense retrieval

Dependency: V2-04. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement exact vector search first with the same authorization, active-generation and required-filter rules as lexical search.

Acceptance: Dense candidates never escape scope; empty vectors/invalid profiles fail; results carry score direction and profile.

Verification: Compare hand-built vectors against expected order and verify filtered candidates in both runtimes.

Learning exercise: Calculate a simple similarity ordering by hand.

Expected areas: `Both dense adapters`, `vector fixtures`.

### V2-06: Identifier search and rank fusion

Dependency: V2-05. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Add a distinct exact-identifier candidate list and weighted RRF with stable identities, tie-breaks and per-list deduplication.

Acceptance: Raw lexical/dense scores are never added; duplicate list entries cannot inflate votes; candidate union respects its global limit.

Verification: Use hand-calculated ranks, missing-list entries, tied scores and repeated identifiers in shared fixtures.

Learning exercise: Compute RRF for three documents and vary the smoothing constant.

Expected areas: `Shared ranking fixtures`, `both fusion modules`.

### Checkpoint V2-C2

After tasks through V2-06, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V2-07: Hybrid orchestration and fallbacks

Dependency: V2-06. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Run logical retrieval branches against the reference snapshot with bounded fan-out and explicit fallback policy.

Acceptance: Required filters are identical across branches; branch failure raises by default or returns explicitly degraded execution if configured.

Verification: Inject dense or lexical failure; verify no silent downgrade and no limit bypass.

Learning exercise: Explain logical parallel branches versus physical DB execution.

Expected areas: `Both retrieval orchestrators`, `branch-failure tests`.

### V2-08: Hybrid evaluation and checkpoint

Dependency: V2-07. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Compare lexical, dense and hybrid modes on development questions, with identical corpus revision and declared parameters.

Acceptance: Report recall/ranking metrics, latency and costs without claiming guaranteed improvement; preserve held-out labels.

Verification: Run a small sequential evaluation; investigate any regression with source examples and rerun parity tests.

Learning exercise: Explain an ablation and why the same questions must be used for comparisons.

Expected areas: `evaluation/runners/`, `evaluation/reports/V2/`, `package notes`.

### Checkpoint V2-C3

After tasks through V2-08, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

## Version exit

Demonstrate: Both runtimes combine dense and lexical evidence under the same constraints and return reproducible rank-fusion fixtures. Record results for owned edge cases and any unresolved operational/live-provider checks. Build the stated local artifact when applicable. A planned feature, fake-provider pass or unrun hosted CI job must not be reported as production evidence.

If blocked, reduce the failing case to one document/request and preserve the current working slice. Keep required scope checks, citation integrity and honest statuses. Escalate only the missing decision or external dependency; do not redesign the project to bypass it.
