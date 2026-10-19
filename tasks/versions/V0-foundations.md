# V0: Foundations and learning setup

This document defines V0 scope. Implementation and verification progress is tracked only in [todo.md](../todo.md).

## Outcome and boundaries

A minimal package in each runtime accepts the same fixtures; a small corpus and resource baseline exist.

Entry: No prerequisite implementation. Read the architecture and master plan.

Architecture mapping: Architecture phase 0; sections 1-5, 12-16.

Artifact goal: Internal only; no registry release.

Follow the [master plan](../plan.md), [learning workflow](../LEARNING.md), and [edge-case inventory](../EDGE_CASES.md). Respect task dependency order and run one language suite at a time on the development machine. Independent authorized agent lanes follow [the coordination protocol](../../docs/agents/WORKFLOW.md); dependent work keeps one writer. A task has a target scope of 1-5 implementation/test files; if it expands beyond one focused session, split it into child tasks before proceeding. Paths below identify expected areas, not permission to rewrite entire directories.

## Tasks

### V0-01: Workspace and resource baseline

Dependency: None; read governing architecture first. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Inspect governing files, existing work, runtime availability, disk headroom and services without changing services automatically.

Acceptance: Record actual observations and a one-process test policy; record hosted Supabase as the selected development database and identify an isolated test target before using it. Provisioning and credential validation remain separate pending work; no local database installation is required.

Verification: Review the baseline with actual command outputs; ensure no credentials were captured.

Learning exercise: Explain why process memory, model assets and database size are different costs.

Expected areas: `docs/development.md`, `evaluation/reports/V0/`.

### V0-02: Minimal package skeletons

Dependency: V0-01. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Create minimal Python and TypeScript package entry points and scoped test commands; establish Git workflow if requested or needed for implementation, preserving existing work.

Acceptance: Both core imports run without network calls, database drivers or model downloads; a tiny smoke test passes in each runtime.

Verification: Run clean local import tests and one focused test per runtime; record exact commands in development.md.

Learning exercise: Import your own library and explain the difference between source code and an installed package.

Expected areas: `packages/python/`, `packages/typescript/`.

### V0-03: Compatibility and dependency policy

Dependency: V0-02. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Check minimal Pydantic/Zod, test tooling and planned PostgreSQL drivers; choose supported runtime versions based on successful probes.

Acceptance: Record tested versions and lock strategy; heavy inference/framework dependencies remain optional.

Verification: Install only the minimal test environment and inspect its dependency graph and disk size.

Learning exercise: Explain direct versus transitive dependencies and why a lockfile matters.

Expected areas: `docs/development.md`, `package manifests and locks`.

### Checkpoint V0-C1

After tasks through V0-03, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V0-04: Request and error contracts

Dependency: V0-03. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Define the minimal versioned request, trusted-scope boundary, filter AST and typed error codes from architecture section 5.

Acceptance: Both runtimes accept valid fixtures and reject invalid or oversized input; the tool-facing schema cannot set scope.

Verification: Run shared valid/invalid fixtures, including empty queries, unknown filter operators and nonfinite numbers.

Learning exercise: Change a field type and observe compile-time versus runtime rejection.

Expected areas: `contracts/`, `Python contracts`, `TypeScript contracts`.

### V0-05: Evidence and result contracts

Dependency: V0-04. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Define immutable source IDs, UTF-8 byte spans, facet states, execution state and usage fields; describe temporary V1 behavior.

Acceptance: Both runtimes serialize matching fixture results; unknown coverage cannot become sufficient and unknown usage is not zero.

Verification: Compare canonical JSON fixtures including Unicode, large string IDs and typed errors.

Learning exercise: Explain partial evidence versus an operational failure.

Expected areas: `contracts/`, `both runtime result models`.

### V0-06: Tiny corpus and evaluation protocol

Dependency: V0-05. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Write 10-20 small original documents and about 30 manually reviewed questions; label expected passages, facets and intentionally absent answers.

Acceptance: Fixtures include two tenants, revisions, identifiers, Unicode and missing facets; development and held-out roles are recorded.

Verification: Review labels against actual source spans and check for accidental private data; keep a sealed subset for later evaluation.

Learning exercise: Label one answerable and one unanswerable question yourself.

Expected areas: `evaluation/corpus/`, `evaluation/questions/`, `evaluation/protocol.md`.

### Checkpoint V0-C2

After tasks through V0-06, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V0-07: Minimal CI and baseline checkpoint

Dependency: V0-06. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Add or document CI jobs for contracts, typing and focused unit tests; configure actual hosted CI only when a repository is available.

Acceptance: The same commands work locally; a hosted CI run is recorded separately from local success, and model calls are excluded.

Verification: Run the local equivalent sequentially and record package import/resource baselines.

Learning exercise: Read a failing test report and locate the smallest responsible fixture.

Expected areas: `CI config`, `docs/development.md`, `evaluation/reports/V0/`.

### Checkpoint V0-C3

After tasks through V0-07, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

## Version exit

Demonstrate: A minimal package in each runtime accepts the same fixtures; a small corpus and resource baseline exist. Record results for owned edge cases and any unresolved operational/live-provider checks. Build the stated local artifact when applicable. A planned feature, fake-provider pass or unrun hosted CI job must not be reported as production evidence.

If blocked, reduce the failing case to one document/request and preserve the current working slice. Keep required scope checks, citation integrity and honest statuses. Escalate only the missing decision or external dependency; do not redesign the project to bypass it.
