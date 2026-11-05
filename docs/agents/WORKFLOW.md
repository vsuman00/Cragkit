# Coordination for Cragkit development agents

Read [AGENTS.md](../../AGENTS.md) first. The user's standing authorization permits independent bounded project lanes when the active task benefits from them. Follow plan dependencies and resource limits. Use one writer for indivisible work.

## Select the workflow

Load the applicable project skill for each future coordinated or managed task:

- [cragkit-coordinate](../../.agents/skills/cragkit-coordinate/SKILL.md) organizes independent lanes, direct peer dependency resolution, plan-change reports and unresolved Astra escalation.
- [cragkit-manager](../../.agents/skills/cragkit-manager/SKILL.md) gives two substantive peers one concrete outcome, complementary responsibilities, an initial writable split and a named assembler.

These skills define the role-specific steps. This protocol holds the shared assignment, ownership and integration rules. Coordination may include a managed pair when one bounded lane needs a shared outcome.

## Assign work before editing

The coordinator selects tasks whose dependencies are satisfied and assigns each an owner and explicit writable paths. Record assignments in the session handoff in [the roadmap handoff](../roadmap.md#session-handoff). Workers report changes to the coordinator; the handoff retains one owner.

Use this small assignment record:

```text
Task or child-task ID:
Concrete outcome and shared constraints:
Owner / agent identifier / model:
Mode: implementation / read-only review
Writable paths:
Read-only dependencies and protected boundaries:
Contract or fixture revision:
Acceptance checks:
Allowed services and resource limits:
Assembler, when managing a pair:
Final integrator and escalation owner:
State: assigned / running / blocked / ready-for-integration / complete
Handoff: changed files, actual checks/results, limitations, next action
```

These are logical roles; use only the roles the task needs:

| Role | Responsibility |
| --- | --- |
| Coordinator/final integrator | Own the current roadmap, assignments, shared-file changes, combined acceptance and roadmap handoff. |
| Peer | Deliver substantive work within assigned paths and resolve concrete dependencies directly with the relevant peer. |
| Assembler | Reconcile a managed pair's artifacts and report the shared outcome to the final integrator. |
| Reviewer | Inspect contracts, edge-case coverage and evidence; report concrete locations. |

## Avoid collisions

Do not assign concurrent writes to the same files. Treat shared schemas, fixtures, migrations, manifests and lockfiles as single-owner resources. Freeze the shared contract before separate Python/TypeScript tasks. A peer ownership adjustment requires agreement, a stopped previous writer and a report to the coordinator. Changes outside the authorized subsystem or across protected boundaries require escalation before dependent work.

If an unexpected edit appears, preserve it, stop overlapping edits and coordinate ownership. Do not automatically revert another worker's changes. The coordinator resolves stale assignments after checking actual work. A Markdown assignment is a coordination convention, not an atomic lock.

Worktrees isolate checkouts; ports, databases, model caches and filesystem outputs remain shared. Give integration runs isolated test data. Keep one test process and one language integration suite active at a time, bound other resource use, and reduce concurrent lanes if machine responsiveness deteriorates. Do not start services, downloads or live-provider runs without task authorization.

## Integrate and teach

The final integrator reads the assembled artifacts and worker reports, checks contract revisions and runs the relevant combined acceptance checks. Worker success and assembly alone do not complete a task. Return failures to the smallest responsible slice and mark complete only after acceptance passes. Explain one important design choice and one failure case to the learner at the checkpoint.

Before ending, record task state, changed files, actual checks/results, resource observations, learning gaps and the next smallest action in the roadmap handoff. Before a new session, inspect that handoff, actual files and existing changes. Reuse evidence only while its inputs and configuration match. Never carry an unverified worker claim forward as a release result.
