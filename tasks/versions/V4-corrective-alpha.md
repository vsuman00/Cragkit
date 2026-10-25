# V4: Corrective retrieval alpha

Status: in progress; ledger/planning and focused corrective paths have local evidence. Full-version acceptance is pending. Progress is tracked only in [todo.md](../todo.md).

## Outcome and boundaries

Both libraries support bounded corrective retrieval, useful diagnostics and one optional framework adapter each.

Entry: V3 complete; development assessment policy and context accounting recorded.

Architecture mapping: Architecture phases 4-5; sections 3-5, 8, 10-13.

Artifact goal: 0.4.0-alpha.1 candidate; public alpha publication is separately authorized.

Follow the [master plan](../plan.md), [learning workflow](../LEARNING.md), and [edge-case inventory](../EDGE_CASES.md). Respect task dependency order and run one language suite at a time on the development machine. Independent authorized agent lanes follow [the coordination protocol](../../docs/agents/WORKFLOW.md); dependent work keeps one writer. A task has a target scope of 1-5 implementation/test files; if it expands beyond one focused session, split it into child tasks before proceeding. Paths below identify expected areas, not permission to rewrite entire directories.

## Tasks

### V4-01: Shared execution ledger

Dependency: V3-08. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement request-local reservations for provider calls, candidate work, attempts and deadlines before concurrent dispatch.

Acceptance: Concurrent work cannot overspend configured enforceable limits; unknown usage/cost stays unknown and strict unsupported cost accounting fails.

Verification: Race fake calls at the final budget slot; test nested SDK retries and cancellation after dispatch.

Learning exercise: Explain reservation versus reconciliation of a budget.

Expected areas: `Both ledger modules`, `shared concurrency fixtures`.

### V4-02: Optional structured planning

Dependency: V4-01. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Add bounded decomposition while preserving the original question, exact identifiers and required constraints.

Acceptance: Invalid/oversized plans use the documented fallback or typed failure; agent text cannot edit scope or limits.

Verification: Test malformed JSON, invented intent, too many facets and prompt-injection content.

Learning exercise: Explain the difference between a hypothesis and a user-provided fact.

Expected areas: `Both planner adapters`, `adversarial plan fixtures`.

### V4-03: Targeted corrective search

Dependency: V4-02. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Implement targeted rewrites or candidate expansion for missing facets, retaining useful evidence and fixed scope.

Acceptance: Each recovery consumes the shared budget; caller constraints remain identical and repeated candidate votes are not accumulated without bound.

Verification: Recover a deliberately weak query with a fake planner; verify retained evidence and unchanged filters.

Learning exercise: Draw the state transitions for one failed and one successful retry.

Expected areas: `Both recovery policies`, `retry fixtures`.

### Checkpoint V4-C1

After tasks through V4-03, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V4-04: Loop termination and fault recovery

Dependency: V4-03. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Add repeated-query/candidate detection, no-progress stops, transient-only retries and exhaustion outcomes.

Acceptance: A never-improving provider terminates; timeout/cancellation stays distinct from insufficient evidence.

Verification: Test repeated normalized queries, rate limits, provider failures and exhausted budget across both runtimes.

Learning exercise: Explain why a retry needs a reason and a stop condition.

Expected areas: `Both state machines`, `fault-injection tests`.

### V4-05: Privacy-controlled events

Dependency: V4-04. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Emit bounded redacted stage events with stable IDs, attempt numbers, timing and stop reasons.

Acceptance: Raw source/query text is off by default; exporter failure cannot block retrieval or create an unbounded queue.

Verification: Inject exporter failure and inspect traces for DSNs, keys and source text; record dropped-event counts.

Learning exercise: Explain why unresolved retrieval is only a documentation-gap hypothesis.

Expected areas: `Both event sinks`, `trace fixtures`.

### V4-06: Python framework adapter

Dependency: V4-05. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Select one Python framework at this phase and expose a narrow tool schema backed by the existing engine.

Acceptance: Trusted scope is bound outside tool arguments; model-visible output is recounted after final serialization.

Verification: Compare direct-library and tool results; try forged scope and an oversized wrapper.

Learning exercise: Explain what an adapter adds without changing core retrieval.

Expected areas: `Optional Python integration package`, `adapter tests`.

### Checkpoint V4-C2

After tasks through V4-06, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V4-07: TypeScript framework adapter

Dependency: V4-06. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Select one TypeScript framework and implement the matching optional adapter with Zod validation.

Acceptance: Core installation remains framework-free; direct and tool calls preserve statuses, limits and citations.

Verification: Run shared engine fixtures through the adapter and test scope injection and cancellation.

Learning exercise: Trace the boundary between Zod validation and execution policy.

Expected areas: `Optional TypeScript integration package`, `adapter tests`.

### V4-08: Corrective quality and alpha packaging

Dependency: V4-07. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Run stage ablations, package smoke tests and a complete demo with success, partial, insufficient and operational failure outcomes.

Acceptance: Report whether correction earns its extra calls; full-loop invariants pass and alpha limitations are explicit.

Verification: Compare hybrid/reranked/corrective modes on development data; measure calls, latency, memory and install footprint.

Learning exercise: Explain when skipping correction is the better configured choice.

Expected areas: `evaluation/reports/V4/`, `examples`, `release notes`.

### Checkpoint V4-C3

After tasks through V4-08, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

## Version exit

Demonstrate: Both libraries support bounded corrective retrieval, useful diagnostics and one optional framework adapter each. Record results for owned edge cases and any unresolved operational/live-provider checks. Build the stated local artifact when applicable. A planned feature, fake-provider pass or unrun hosted CI job must not be reported as production evidence.

If blocked, reduce the failing case to one document/request and preserve the current working slice. Keep required scope checks, citation integrity and honest statuses. Escalate only the missing decision or external dependency; do not redesign the project to bypass it.
