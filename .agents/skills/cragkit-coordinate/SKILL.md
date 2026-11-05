---
name: cragkit-coordinate
description: Coordinate bounded independent Cragkit work lanes with explicit ownership, direct peer communication, evidence reports and final integration. Use for every coordinated project task; use cragkit-manager alongside it when two peers share one outcome.
---

# Coordinate Cragkit work

For example, separate Python and TypeScript fixture consumers can proceed in parallel after one owner freezes their shared contract. Both lanes report to one final integrator.

Read [AGENTS.md](../../../AGENTS.md), the current [roadmap](../../../docs/roadmap.md), relevant architecture and contract failure cases, and [the coordination protocol](../../../docs/agents/WORKFLOW.md). Apply [cragkit-manager](../cragkit-manager/SKILL.md) when assigning two peers one shared concrete outcome. These project skills guide all future coordinated or managed tasks; they do not authorize unrelated work.

## Establish bounded lanes

- Inspect the actual workspace and existing changes. Select the smallest authorized task with satisfied dependencies; state its ID, intended behavior and acceptance evidence before editing.
- Use the user's standing authorization for independent project lanes within the accepted outcome. Keep one writer when work cannot be separated safely. Record each lane's outcome, task ID, owner, writable paths, read-only dependencies, contract revision, checks, resource limits and handoff state in the roadmap handoff through its designated owner.
- Give each file one active writer. Shared contracts, schemas, fixtures, migrations, manifests and lockfiles need an explicit owner; freeze their revision before dependent work. Assign a primary coordinator and one final integrator, which may be the same agent. Workers never concurrently edit the roadmap handoff.
- Sol workers must do substantive work in their lanes. Use `gpt-6.1-sol` for peer lanes; verify model and tool availability before starting. Do not silently substitute another model. If the requested model or delegation tools are unavailable, report the limitation and keep only work that the primary can safely perform under existing authorization; otherwise leave the affected lane blocked.
- Start with one local test process, fake providers and small fixtures. Parallel writers require independent, nonoverlapping paths and affordable machine load. Serialize integration suites and resource-heavy checks; allocate ports, test data and outputs explicitly. Do not start services, install tools, download models or incur provider costs merely to create a lane.

## Resolve dependencies directly

Message the relevant peer directly through the available collaboration tool when a concrete dependency appears. Include task IDs, affected paths or contract revision, the needed decision and its acceptance impact. Resolve routine details together; do not wait for the primary to relay peer messages.

Within an assigned subsystem, peers may revise their split only after explicitly agreeing on the transfer, the previous owner stops writing, and the new owner acknowledges ownership. Notify the primary of the new split before dependent edits. A message or handoff entry is a convention, not an atomic file lock. Preserve unexpected edits and stop overlapping writes while resolving ownership.

Report findings that change the plan immediately: explain the observed evidence, affected dependency or acceptance criterion, and smallest proposed adjustment. Changes to the shared outcome, protected architecture or authorization boundaries, or another lane's ownership require the primary coordinator's decision before dependent work.

If peers cannot resolve a material issue, send the primary the competing options, evidence and specific decision needed. The primary asks `gpt-6-astra` only when the issue still needs escalation; Astra receives the bounded question and relevant artifacts. Astra advice cannot expand user scope, authorize costs or external actions, or override project boundaries. If Astra or messaging is unavailable, report that fact, preserve safe independent progress and leave the disputed work blocked. Do not loop on the same disagreement or silently choose a replacement model.

## Integrate evidence

Each worker reports actual changed paths, decisions and contract revision, commands actually run with results and configuration, covered failures, remaining limitations, resource observations and the next action. Distinguish implementation from validation and local/fake evidence from integration, live-provider or publication evidence. Notify the assembler when ready; a peer report is input for inspection.

The designated final integrator reads the assembled files and diffs, reconciles contracts and ownership, then runs relevant combined checks serially. Documentation work needs link, skill structure and consistency checks rather than artificial product tests. Return a failed check to the smallest responsible lane. Only the handoff owner records completion after acceptance passes; use `IMPLEMENTED_UNVALIDATED` when required checks are missing.

Apply the installed `clean-user-facing-text` skill to reader-facing prose and preserve protected code, claims and links. Close task-owned processes and record the session handoff, learning gaps and next smallest action. Explain one design choice and one failure case: two workers changing the same fixture invalidate an independent-lane split and require ownership resolution before either continues. Offer a small learning exercise without blocking progress on a quiz.
