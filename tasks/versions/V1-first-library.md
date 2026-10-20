# V1: First usable lexical library

Status: V1-01 and V1-02 are complete after local and authenticated native hosted verification, including Python runtime-login scope and cleanup tests. V1-03 native TypeScript connection lifecycle is next. Completion is tracked only in [todo.md](../todo.md).

## Outcome and boundaries

Both native libraries can ingest, retrieve, update and delete small documents with exact citations and access isolation.

Entry: V0 complete; use a dedicated hosted Supabase development PostgreSQL target with isolated test data. Verify connection mode, TLS, runtime-role permissions and extension/schema compatibility before integration tests. Use disposable PostgreSQL in CI when configured; local Docker remains optional.

Architecture mapping: Architecture phase 1; sections 3-7, 9, 11-12.

Artifact goal: Local wheel/sdist and npm tarball; tentative 0.1.0-alpha.1.

Follow the [master plan](../plan.md), [learning workflow](../LEARNING.md), and [edge-case inventory](../EDGE_CASES.md). Respect task dependency order and run one language suite at a time on the development machine. Independent authorized agent lanes follow [the coordination protocol](../../docs/agents/WORKFLOW.md); dependent work keeps one writer. A task has a target scope of 1-5 implementation/test files; if it expands beyond one focused session, split it into child tasks before proceeding. Paths below identify expected areas, not permission to rewrite entire directories.

## Tasks

### V1-01: Schema and explicit migrations

Dependency: V0-07. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Create the initial collections, documents, immutable revisions, generations, chunks, grants and ingestion-job schema needed for lexical retrieval.

Acceptance: Composite keys reject cross-tenant references; migrations are explicit and versioned, never triggered by import or retrieve.

Verification: Apply migrations to an empty isolated database; test invalid foreign keys and supported migration reruns.

Learning exercise: Explain a primary key, foreign key and active-generation pointer.

Expected areas: `storage/postgres/migrations/`, `database integration tests`.

### V1-02: Python connection lifecycle

Dependency: V1-01. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement the Python pool adapter, capability checks, parameterized filters and transaction-local scope with runtime-role tests.

Implementation children: V1-02A provides the internal optional-driver pool resource layer, explicit owned startup, borrowed-pool preservation and bounded lifecycle. V1-02B adds schema/capability validation, parameterized scope/filter handling and real runtime-role tests. Both children are required for this parent; an administrative resource smoke check alone does not establish scoped application access.

Acceptance: Owned resources close idempotently; caller pools remain open; statement and pool acquisition timeouts are bounded.

Verification: Test a successful query, invalid schema, pool exhaustion and scope reuse across tenants.

Learning exercise: Trace acquire, begin, query, release and close through one request.

Expected areas: `Python store adapter`, `Python database tests`.

### V1-03: TypeScript connection lifecycle

Dependency: V1-02. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement the equivalent Node adapter with abort propagation and the same capability/filter contract.

Acceptance: Scope is reset between pooled requests; borrowed pools remain caller-owned; error codes match Python fixtures.

Verification: Run the same database fixtures from TypeScript, including timeout and abort cases.

Learning exercise: Explain promises, AbortSignal and why a pool is reused.

Expected areas: `TypeScript store adapter`, `TypeScript database tests`.

### Checkpoint V1-C1

After tasks through V1-03, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V1-04: Canonical text and source spans

Dependency: V1-03. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement basic text/Markdown input normalization and structural chunking in small steps, with identical byte-offset semantics.

Acceptance: Every chunk resolves to its canonical UTF-8 slice; unsupported input, oversized documents and invalid boundaries fail explicitly.

Verification: Use accented text, emoji, CRLF, headings, code blocks and oversized blocks; compare both runtimes.

Learning exercise: Demonstrate why JavaScript string length is not a UTF-8 byte offset.

Expected areas: `contracts/source fixtures`, `both ingestion modules`.

### V1-05: Python staged ingestion

Dependency: V1-04. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Write one immutable revision and lexical generation with stable intent IDs, payload digests and atomic publication.

Acceptance: Retrying the same intent is idempotent; changed payload under the same key fails; interrupted work leaves the prior generation active.

Verification: Inject failure before publication and replay the ingestion intent.

Learning exercise: Explain why model or parsing work should happen outside publication transactions.

Expected areas: `Python indexer`, `PostgreSQL ingestion tests`.

### V1-06: TypeScript ingestion parity

Dependency: V1-05. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement the same ingestion contract and canonical generation identifiers in TypeScript.

Acceptance: A document ingested in either runtime is readable by the other; canonical source and digest fixtures agree.

Verification: Run Python-write/TypeScript-read and TypeScript-write/Python-read integration cases.

Learning exercise: Explain why shared database schema alone does not guarantee shared behavior.

Expected areas: `TypeScript indexer`, `cross-runtime ingestion fixtures`.

### Checkpoint V1-C2

After tasks through V1-06, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V1-07: Scoped lexical retrieval

Dependency: V1-06. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement native FTS candidate retrieval in each adapter, applying scope and required filters before candidate selection.

Acceptance: Only active, authorized, non-tombstoned chunks are returned; ordering has a stable tie-break and FTS is labelled accurately.

Verification: Query two tenants with deliberately identical documents and test required-filter mismatches.

Learning exercise: Inspect the SQL plan and explain lexical ranking versus semantic similarity.

Expected areas: `Both store search methods`, `scoped SQL fixtures`.

### V1-08: Source-backed result assembly

Dependency: V1-07. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Fetch authorized immutable source spans and return a minimal typed evidence result without claiming semantic sufficiency.

Acceptance: Useful evidence returns partial with unknown coverage; no evidence returns insufficient; digest mismatch cannot be silently accepted.

Verification: Mutate a stored span/digest in an isolated fixture and verify the integrity-error policy.

Learning exercise: Follow a citation from result to exact stored bytes.

Expected areas: `Both result assemblers`, `source integrity tests`.

### V1-09: Revision publication and deletion

Dependency: V1-08. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Add compare-and-swap updates, tombstones and documented cleanup behavior; retain old revisions only under the chosen retention policy.

Acceptance: A slower concurrent update cannot overwrite a newer publication; deleted documents disappear from retrieval immediately after tombstoning.

Verification: Race two controlled updates; simulate a crash and test unavailable historical citations after purge.

Learning exercise: Explain immutability versus active visibility.

Expected areas: `Ingestion lifecycle module`, `SQL update/delete tests`.

### Checkpoint V1-C3

After tasks through V1-09, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V1-10: Permission changes and final authorization

Dependency: V1-09. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Recheck authorization revision and tombstones at final source fetch; configure/test RLS with the real runtime role where used.

Acceptance: Revoked evidence is excluded before release; pooled contexts and document-grant references cannot cross tenants.

Verification: Revoke permission between candidate retrieval and fetch; test owner/bypass-role misconfiguration detection.

Learning exercise: Explain why filtering only after top-k is inadequate.

Expected areas: `Both authorized source fetch paths`, `access tests`.

### V1-11: Deadlines and cancellation

Dependency: V1-10. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Propagate request-local deadlines through pool wait, queries and child tasks; cap queued work.

Acceptance: Cancellation releases connections and stops new work; no stale request state is reused by the next caller.

Verification: Cancel while waiting and while querying, then successfully reuse the retriever and pool.

Learning exercise: Explain cooperative cancellation and cleanup in finally blocks.

Expected areas: `Both orchestrators`, `fault/cancellation fixtures`.

### V1-12: First library demo and artifacts

Dependency: V1-11. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Add one direct-library example per runtime and build local artifacts with the current supported capabilities documented.

Acceptance: A clean environment installs each artifact and runs an authorized lexical query; importing core requires no DB/model side effects.

Verification: Run demos sequentially from installed artifacts; record size, cold import and resource observations.

Learning exercise: Explain the complete path from ingest to cited result in five minutes.

Expected areas: `Examples`, `package build configuration`, `V1 report`.

### Checkpoint V1-C4

After tasks through V1-12, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

## Version exit

Demonstrate: Both native libraries can ingest, retrieve, update and delete small documents with exact citations and access isolation. Record results for owned edge cases and any unresolved operational/live-provider checks. Build the stated local artifact when applicable. A planned feature, fake-provider pass or unrun hosted CI job must not be reported as production evidence.

If blocked, reduce the failing case to one document/request and preserve the current working slice. Keep required scope checks, citation integrity and honest statuses. Escalate only the missing decision or external dependency; do not redesign the project to bypass it.
