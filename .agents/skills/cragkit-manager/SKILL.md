---
name: cragkit-manager
description: Manage two Cragkit peers delivering one concrete outcome through complementary work, direct coordination and a named assembler. Use for a shared outcome requiring both peers; use cragkit-coordinate to organize independent lanes.
---

# Cragkit peer management

For example, one peer defines a contract while the other builds its consumer against an agreed revision; one of them assembles the result. Both contribute substantive work.

Read [AGENTS.md](../../../AGENTS.md) and the [coordination protocol](../../../docs/agents/WORKFLOW.md). Apply the project plans, resource limits and current authorization. Use [cragkit-coordinate](../cragkit-coordinate/SKILL.md) when organizing independent lanes around this shared outcome.

Give the two peers the same concrete outcome and shared constraints. Assign complementary responsibilities and explicit initial writable paths. Name one peer as assembler before work begins. Give both the acceptance conditions, protected boundaries, contract revision, resource limits and escalation owner; use the protocol's assignment record. Avoid creating a second peer for work that cannot usefully be divided.

Use `gpt-6.1-sol` for peers when available. Send reasoning decisions that remain unresolved after peer and coordinator review to `gpt-6-astra` through the coordinator. Astra advice cannot expand user scope, authorize costs or external actions, or override project boundaries. Check actual tool and model availability; report a missing capability and resolve the affected assignment without silently substituting a model or assuming additional authority.

Peers communicate directly about concrete dependencies, interfaces and findings. They may revise the split within their authorized subsystem after agreeing who owns each affected file. The previous writer must stop before a transfer takes effect. Preserve existing work and notify the coordinator of transfers and plan changes. Escalate a change to the outcome, a protected boundary or another lane's ownership before dependent work. If peers cannot resolve a decision, give the coordinator the options, evidence and precise blocker for Astra escalation.

Each peer produces substantive artifacts within its writable paths and reports actual files, checks, findings and limitations. Shared schemas, migrations, lockfiles, tracker edits and tests retain their assigned single owner. Serialize test processes and other shared resources; two peers do not authorize two test suites.

The assembler reads both peers' artifacts and reports, reconciles interfaces and checks the agreed outcome. Request corrections from the owning peer; edit its files only after an explicit transfer and the previous writer stops. Resolve integration findings within the authorized subsystem, then send the assembled files and remaining limitations to the final integrator. Assembly is evidence for final verification; the final integrator owns combined acceptance and tracker completion.
