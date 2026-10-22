# V2: Hybrid retrieval

Status: V2-01 design decision complete: hosted opt-in OpenAI text-embedding-3-small, 1536 dimensions, with routine fake providers and live access disabled until separately configured. Metadata/synthetic interface evidence is distinct from unrun live verification. V2-02 Python embedding boundary has passed its local deterministic checks. V2-03 TypeScript embedding parity and V2-C1 have passed local deterministic/conformance/artifact checks. V2-04 vector generations/reindex is next; hybrid retrieval and live-provider validation remain unimplemented/unrun. Progress is tracked only in [todo.md](../todo.md).

## Outcome and boundaries

Direct Neon development target/security/native acceptance is complete under [DB-NEON-01](../../docs/neon-migration-plan.md); see [the evidence](../../evaluation/reports/V2/DB-NEON-01.md). Prior Supabase results are separate evidence; pooling and production remain unvalidated. This host change does not implement V2-04: pgvector installation, profile tables, generation publication and vector acceptance retain their existing dependencies. Use the [Neon runbook](../../docs/neon.md) and tracker for actual host state.

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

Dependency: V2-03 and V2-C1 local acceptance; [DB-NEON-01](../../evaluation/reports/V2/DB-NEON-01.md) supplies the accepted direct Neon development/native lexical baseline. V2-04A is COMPLETE on the dedicated direct development target; [its report](../../evaluation/reports/V2/V2-04A.md) records the explicit managed security profile and limits. V2-04B-G remain PLANNED. This does not complete V2-04. Supabase retirement, pooled-endpoint acceptance and production acceptance are separate work, not prerequisites for the next development slice.

Build: Explicitly install/check pgvector, add profile-specific vector storage, then implement bounded staging and safe shadow-generation publication in both native runtimes. Follow [architecture sections 6-7](../../docs/architecture/ARCHITECTURE.md#6-ingestion-and-document-lifecycle), the [storage contract](../../storage/postgres/README.md) and the [Neon runbook](../../docs/neon.md). Existing applied migrations stay byte-for-byte unchanged; new DDL uses new numbered migrations and the checksummed administrative runner. Core import, initialization and retrieval never install extensions or apply migrations.

Use shared deterministic synthetic vectors and fake embedding providers for routine verification. Give the fake profile its own identity, distinct from the approved hosted `text-embedding-3-small` profile at 1536 dimensions; equal dimensions alone never establish compatibility. No paid provider calls, model downloads or model-quality claims are required. Dense ranking belongs to V2-05; hybrid orchestration, HNSW, new SDKs and deployment expansion are outside this task.

Run one ingestion job and one test process, with small batches bounded by items and bytes/tokens. Serialize native language integration suites and use at most two native database clients including the administrative fixture owner. Reuse clients, bound waits/deadlines/cancellation and close task-owned resources. Start with a tiny synthetic corpus; shrink workload if headroom or responsiveness deteriorates. Each child targets at most roughly five implementation/test files; split again before exceeding that limit. Expected areas identify likely files, not permission to rewrite them all.

#### V2-04A: Explicit pgvector setup

Dependency: V2-03, V2-C1 and the accepted direct development baseline above. Administrative setup and verification are complete; profile storage in B is the next smallest implementation slice.

Build: Extend explicit administrative tooling to inspect available/installed extension versions and target identity, then install pgvector only through a deliberate dedicated-target operation. Record the supported extension/schema capability contract; vector-enabled initialization/reindex checks it and fails with a typed compatibility error when absent or unsupported. Existing lexical-only paths remain usable without vector capability.

Acceptance and planned verification: Exercise fresh setup, unchanged rerun, unsupported/missing capability, lock/deadline failure and interrupted application. Check the migration ledger/checksums and original timestamps; inject a failed transactional application and verify no partial migration or ledger entry persists. Recheck default-deny privileges, RLS and restricted native-role behavior after new objects are created. Never drop/reinstall an existing extension or weaken security to recover. DB-NEON-01 advertised pgvector but did not install it; availability is not installation evidence (E06/E22).

Expected areas: `tools/check_postgres.py`, `tools/check_neon_postgres.py`, their focused tests and a new administrative migration/setup artifact. Keep extension setup distinct from application runtime APIs.

Accepted A-r2: separate numbered setup artifact/ledger preserves lexical migration history. Strict checks remain default; Neon requires explicit managed primitive acceptance, with platform-owned PUBLIC computational privileges disclosed and private schema/ledger denial verified. Future installer-created objects use restrictive database-wide defaults because per-schema revocation cannot subtract global defaults. Native vector initialization/reindex APIs are not implemented by A: C/E must enforce the recorded capability contract through native read-only checks before vector work. B must review runtime schema USAGE exposure before any grant. [Evidence](../../evaluation/reports/V2/V2-04A.md).

#### V2-04B: Profile-specific vector storage

Dependency: V2-04A. Freeze shared profile/generation/chunk identity, composite foreign keys, the readiness contract and the synthetic fixture revision before native consumers proceed.

Build: Add new numbered migration(s) for explicit profile-keyed `vector(d)` storage linked to the full tenant/collection/document/revision/generation/chunk identity. One physical table for the first provisioned profile is enough; additional profiles require explicit provisioning. Do not hardcode one dimension across the library. Validate model/profile identity, dimension, finite values and declared normalization at the boundary; allowlist physical identifiers and parameterize values. Add no approximate index.

Acceptance and planned verification: Prove new tables preserve composite foreign keys, uniqueness, default-deny grants and RLS. Reject a cross-tenant chunk/generation reference even when document/chunk IDs collide. Reject wrong dimensions and a different model with the same dimension; never relabel synthetic vectors as the approved hosted profile. Check migration reruns and failure rollback without editing historical migrations (E06/E15/E18/E22).

Expected areas: new `storage/postgres/migrations/` artifact, `storage/postgres/tests/invariants.sql`, `storage/postgres/tests/security.sql`, shared profile/vector fixtures and storage guidance. Serialize migration/fixture ownership.

#### V2-04C: Python bounded vector staging

Dependency: V2-04B and its frozen profile/fixture contract; existing V2-02 embedding boundary is reused.

Build: Extend native Python ingestion with profile-bound shadow-generation staging and idempotent bounded vector batches. Bind trusted scope before any database/provider branch. Model work runs outside the short publication transaction. No staging operation changes the active pointer.

Acceptance and planned verification: Use fake-provider fixtures for same-intent replay, changed-payload rejection, missing/duplicate vectors, wrong model at the same dimension, dimension change, provider failure, deadline and cancellation between batches. Verify staged content stays invisible and previous authorized lexical retrieval still works. Validate the A-r2 extension/schema capability through native read-only checks before vector work. Bound attempts, batches and resource release; return typed operational failure rather than missing evidence (E06/E12/E15/E23/E24).

Expected areas: `packages/python/src/cragkit/ingestion.py`, a focused internal vector-staging module if needed, Python ingestion/staging tests and the Python native fixture path. Keep this slice separate from publication.

#### V2-04D: Python safe generation publication

Dependency: V2-04C.

Build: Validate the complete scoped generation manifest, matching chunk/lexical/vector counts and one exact profile before marking ready and atomically publishing via expected-active-generation compare-and-swap. Reject mixed-profile/mixed-generation vectors and incomplete builds. Reuse immutable revisions and existing authorization/tombstone checks; no provider call runs inside publication.

Acceptance and planned verification: Interrupt before readiness and during publication, fail a count/profile check, and finish two competing revisions out of order. The transaction must preserve the prior active pointer on failure and reject stale publication. After every failed reindex, verify the old authorized lexical generation remains usable; if a grant was revoked or a tombstone applied, it stays denied. Retaining an old generation never rolls back security changes. Readers must never observe partial readiness or mixed revision text (E12/E13/E15/E20/E25).

Expected areas: Python ingestion/publication module(s), focused publication tests and Python native lifecycle fixture. Split fixtures from implementation if the slice exceeds the file budget.

#### V2-04E: TypeScript bounded vector staging

Dependency: V2-04C and V2-04D accepted Python behavior plus the frozen V2-04B contract; reuse the V2-03 embedding boundary.

Build: Implement native Node.js staging against the same profile, batch, intent and failure contract. No Python service or required model runtime is introduced.

Acceptance and planned verification: Run the same synthetic staging success/failure fixtures as Python, including equal-dimension model mismatch, changed dimension, partial batches, cancellation and cross-tenant colliding IDs. Compare normalized outcomes and ensure scope is bound before every branch; staging cannot publish (E06/E12/E15/E18/E23/E24).

Expected areas: `packages/typescript/src/ingestion.ts`, focused internal staging module if needed, TypeScript staging tests and `tools/check_typescript_ingestion.mjs`.

#### V2-04F: TypeScript safe generation publication

Dependency: V2-04D and V2-04E.

Build: Implement the same native readiness barrier and atomic expected-pointer publication contract, preserving restricted access and immutable revisions.

Acceptance and planned verification: Reuse Python publication fixtures for count/profile mismatch, interruption, failed publication and out-of-order completion. Verify identical typed outcomes, prior-pointer preservation and authorized lexical usability; revoked grants and tombstones remain effective. Exercise generation changes around source release without mixing text (E12/E13/E15/E20/E25).

Expected areas: TypeScript ingestion/publication module(s), focused publication tests and native lifecycle fixture. Shared fixture changes retain one owner.

#### V2-04G: Integrated generation acceptance

Dependency: V2-04A through V2-04F. This gate completes the parent only after all required checks pass.

Planned verification: Run administrative migration/security checks and each native suite serially on the dedicated direct Neon development target, using restricted runtime logins and synthetic data. Verify supported/missing profile capability, same-dimensional model mismatch, dimension changes, incomplete/mixed generations, interrupted reindex, publication rollback and compare-and-swap conflict. Assert the exact prior pointer and authorized lexical result after each failed rebuild. Scope tenant/collection/principal/grants and required filters before branch selection or limits; colliding tenant document IDs cannot leak vectors, metadata or source text. Recheck reused-connection scope, revocation, tombstones, empty authorized results, unsafe roles, bounded waits, close behavior and publication/source snapshot policy (E06/E12/E13/E15/E17-E25). Dense ranking assertions remain V2-05.

Independently inspect fixture cleanup, unchanged historical ledger entries, final RLS/ACLs, temporary roles/policies and closed clients. Record actual commands, fixture/profile revision, local versus hosted/native evidence, failures and resource observations. Do not infer live-provider quality, pooling, production or hosted CI acceptance. Update the tracker only after acceptance passes; partial code without required validation is `IMPLEMENTED_UNVALIDATED`.

Expected areas: focused shared/native fixture checker, `tools/check_python_postgres.py` and the Node lifecycle helper, V2 evidence report and development commands. Keep one final integrator for verification and tracker updates.

Learning example: if generation G2 has only two of three required vectors, G1 remains active. Explain why counts plus profile identity must pass before the pointer changes. Failure case: a slower G2 build cannot overwrite a newer G3 publication, and falling back to G1 cannot restore a revoked grant. Exercise: sketch the expected pointer after an interrupted batch and after a compare-and-swap conflict.

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
