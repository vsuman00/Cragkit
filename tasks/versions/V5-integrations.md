# V5: Backend and transport extensions

Status: active implementation. Progress and acceptance evidence are tracked only in [todo.md](../todo.md).

## Outcome and boundaries

Qdrant and existing-index profiles honor declared capabilities; optional MCP invokes the same native library.

Entry: V4 complete; activate only the adapter currently being developed.

Architecture mapping: Architecture phase 6; sections 3-7, 11-12.

Artifact goal: 0.5.0-beta.1 candidate after adapter conformance.

Follow the [master plan](../plan.md), [learning workflow](../LEARNING.md), and [edge-case inventory](../EDGE_CASES.md). Respect task dependency order and run one language suite at a time on the development machine. Independent authorized agent lanes follow [the coordination protocol](../../docs/agents/WORKFLOW.md); dependent work keeps one writer. A task has a target scope of 1-5 implementation/test files; if it expands beyond one focused session, split it into child tasks before proceeding. Paths below identify expected areas, not permission to rewrite entire directories.

## Tasks

### V5-01: Alternative-store consistency specification

Dependency: V4-08. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Define the Qdrant SourceStore authority, generation manifest, publication barrier, sparse encoder identity and ACL synchronization rules.

Acceptance: The design explains each partial-write outcome and prevents stale candidates reaching external providers before authorization.

Verification: Walk through failure at each write boundary using a table; resolve any conflict with architecture before coding.

Learning exercise: Explain why two stores cannot share one PostgreSQL transaction.

Expected areas: `docs/decisions/`, `Qdrant contract fixtures`.

Design artifacts: [ADR 0003](../../docs/decisions/0003-qdrant-consistency.md), [QD-r1](../../contracts/QDRANT_V5.md) and [normative scenarios](../../contracts/fixtures/qdrant_consistency.json). These specify the optional single-node reference profile; they do not establish native Qdrant acceptance. Distributed profiles require separate declared consistency and conformance evidence.

### V5-02: Qdrant scoped candidate adapter

Dependency: V5-01. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement candidate search for the declared dense/sparse profile with tenant/collection filters and bounded results in each runtime.

Acceptance: Unsupported capabilities fail explicitly; sparse encoding is named accurately; revision IDs survive round trips.

Verification: Run small adapter fixtures one runtime at a time against an isolated Qdrant collection.

Learning exercise: Explain backend capability negotiation.

Expected areas: `Both optional Qdrant search adapters`, `adapter tests`.

Execute as bounded child slices after QD-r1 acceptance:

- V5-02A: freeze the candidate/profile/filter mapping, point-ID derivation and capability boundary; verify exact client/server versions and select an isolated reference target before dependent adapter edits.
- V5-02B: native Python candidate adapter and its focused negative cases, against the frozen shared fixtures.
- V5-02C: native TypeScript candidate adapter and its focused negative cases, on separate owned paths. B and C may proceed in parallel only after A freezes their contract.
- V5-02D: one integrator runs each runtime serially against the isolated Qdrant collection, verifies bounded filtering, identity and capability failures, closes task resources and records acceptance. Synthetic transport tests do not replace this integration gate.
- V5-02E: extend the initial synthetic profile to the already accepted E-r1 OpenAI dense profile, with a genuine dense-only configuration, full-profile batch binding and explicit embedding usage accounting. Verify real-profile routing with spies and actual backend mechanics with fake-profile vectors; no paid inference or synthetic vectors stored under real model identity. Sparse text encoding remains unsupported for that real deployment. Complete E before V5-02 exits and before the source-authority profile freezes.

### V5-03: Source resolution and authorization

Dependency: V5-02. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement authoritative source resolution and candidate authorization before provider disclosure and final release.

Acceptance: Stale ACL payloads and unpublished generations never release unauthorized text; source unavailability is operationally explicit.

Verification: Revoke a grant while a stale vector remains and verify no provider receives the text.

Learning exercise: Explain source authority versus search-index replicas.

Expected areas: `SourceStore implementations`, `cross-store authorization tests`.

Execute V5-03 as bounded children after V5-02:

- V5-03A: freeze authoritative read/source identity and canonical row fixtures, and implement an isolated optional PostgreSQL source schema with its own migration ledger and read policies. No applied `cragkit` migration/history changes. Native SQL validation must prove schema/constraint/read-policy behavior and rollback cleanup before acceptance.
- V5-03B/C: native Python and TypeScript source adapters on separate owned paths, with immutable source verification, fresh authorization, bounded reads and matching failure semantics. Reuse pools/deadlines, not the existing read-only session as a writer.
- V5-03D: serial real PostgreSQL plus Qdrant stale-grant/provider-spy/final-release acceptance, including source outage, unpublished/superseded/malformed references and retained previously published bindings. Source-only checks do not establish publication/coordinator compatibility; V5-04 supplies those capabilities.

### Checkpoint V5-C1

After tasks through V5-03, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V5-04: Publication and repair

Dependency: V5-03. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement idempotent staged writes, completion manifests and bounded repair of partial ingestion/deletion operations.

Acceptance: Readers see only complete published generations; replay and failure preserve identity without duplicate active content.

Verification: Crash between source/vector/manifest writes, replay jobs, and delete during repair.

Learning exercise: Explain at-least-once retry and why idempotency matters.

Expected areas: `Qdrant ingestion adapter`, `repair integration tests`.

### V5-05: Existing-index contract example

Dependency: V5-04. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Provide an example adapter mapping caller-owned records to the source/profile/filter capability contract.

Acceptance: Missing provenance or required filtering capabilities are rejected or explicitly unsupported; no silent claim of full compatibility.

Verification: Map a tiny existing fixture index; test missing revision IDs and insufficient source resolution.

Learning exercise: Explain why arbitrary vector stores are not interchangeable without contracts.

Expected areas: `Existing-index example`, `capability tests`.

### V5-06: Optional MCP host

Dependency: V5-05. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Select the supported MCP implementation at this phase; bind trusted identity outside tool input and propagate cancellation and limits.

Acceptance: The host invokes the same library; it does not change status semantics or expose DB credentials; supported transports are documented.

Verification: Test a local client round trip, malformed requests, unauthorized scope attempts and client disconnect.

Learning exercise: Explain library execution versus a transport process.

Expected areas: `Optional MCP package`, `host integration tests`.

### Checkpoint V5-C2

After tasks through V5-06, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V5-07: Backend and transport parity

Dependency: V5-06. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Run common conformance fixtures across PostgreSQL, Qdrant and direct/tool/MCP entry points, allowing documented backend score differences.

Acceptance: Identity, authorization, statuses and budget semantics agree; capability differences are explicit.

Verification: Use identical deterministic provider fixtures and injected partial-write failures; record tested combinations.

Learning exercise: Explain semantic parity versus identical raw ranking scores.

Expected areas: `Conformance runner`, `V5 compatibility report`.

### V5-08: Beta installation and operations guide

Dependency: V5-07. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Build optional adapter artifacts and document connection ownership, consistency, migrations and local process shutdown.

Acceptance: Core stays small; users can install only one backend; deployment examples state required services and credentials.

Verification: Clean-install core and each supported optional profile separately; execute shutdown and recovery examples.

Learning exercise: Choose the smallest deployment profile for a sample application.

Expected areas: `Package metadata`, `operations docs`, `V5 report`.

### Checkpoint V5-C3

After tasks through V5-08, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

## Version exit

Demonstrate: Qdrant and existing-index profiles honor declared capabilities; optional MCP invokes the same native library. Record results for owned edge cases and any unresolved operational/live-provider checks. Build the stated local artifact when applicable. A planned feature, fake-provider pass or unrun hosted CI job must not be reported as production evidence.

If blocked, reduce the failing case to one document/request and preserve the current working slice. Keep required scope checks, citation integrity and honest statuses. Escalate only the missing decision or external dependency; do not redesign the project to bypass it.
