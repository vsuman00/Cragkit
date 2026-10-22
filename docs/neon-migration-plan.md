# Neon migration plan

Decision date: 22 October 2026. Task: DB-NEON-01. Completion state is recorded in [the tracker](../tasks/todo.md#db-neon-01-neon-migration).

The user selected Neon as the intended development host for PostgreSQL with `pgvector` and native full-text search. The plan was initially saved without execution. On 22 October 2026, the user authorized implementation with the Neon skill/plugin and security tests, and selected a new dedicated Cragkit development project in VAIBHAV's Free organization, Singapore, PostgreSQL 17. The ordered slices below passed for direct-endpoint development/native lexical use; [the evidence](../evaluation/reports/V2/DB-NEON-01.md) records actual execution and verified private development configuration. Vector storage remains V2-04; pooling and production remain separate.

For example, a successful administrative connection to Neon would establish connectivity for that role. It would not demonstrate that a restricted retrieval role can read authorized documents while rejecting another tenant's documents.

## Baseline and boundaries

The [architecture](architecture/ARCHITECTURE.md), [master plan](../tasks/plan.md), [development guide](development.md) and [Supabase runbook](supabase.md) describe the existing PostgreSQL design and recorded Supabase acceptance. Those results remain historical evidence for their tested target. The initial planning task verified no Neon resources or behavior. Subsequent authorized execution is recorded separately in DB-NEON-01 evidence.

Keep native Python and TypeScript execution, optional `psycopg` and Node `pg` drivers, explicit migrations, immutable source revisions, canonical UTF-8 byte spans, tenant isolation and bounded request handling. Native PostgreSQL full-text search remains the lexical method; it is not BM25. Hosting selection does not add Neon Auth, a Data API, Functions, an AI Gateway or a new model provider.

V2-03 and V2-C1 have recorded local acceptance. [V2-04](../tasks/versions/V2-hybrid-search.md#v2-04-vector-generations-and-reindex) remains the next product implementation task. Saving this plan neither implements vector storage nor advances V2 acceptance. Qdrant remains in its planned V5 phase.

## Ordered execution slices

The user has authorized the slices below; the tracker owns their completion state. Keep each slice focused; split cross-runtime implementation if it exceeds the project's reviewable scope. Do not proceed past an unmet dependency or substitute administrator success for runtime security evidence.

### DB-NEON-01-A: Align governing documents

Dependency: saved plan and a user instruction to begin execution.

Update the architecture, master plan, active V2 plan, development guide, README and PostgreSQL storage documentation to distinguish the selected Neon host from the previously verified Supabase target. Prepare a Neon setup/security runbook. Retain Supabase reports and their original results; label any superseded setup guidance without rewriting history.

Acceptance: links and host/status references agree; Neon setup and acceptance are explicitly pending. The library remains portable across compatible PostgreSQL hosts. No hosted success, cost saving or performance improvement is inferred from provider selection.

### DB-NEON-01-B: Identify the development target

Dependency: A.

Confirm the intended account, organization, project, branch, database, region and current free-plan limits before provisioning. Choose a dedicated nonproduction target and isolated synthetic fixtures. Inventory existing Supabase data and decide whether a fresh development database is sufficient or data transfer is needed. Branching or copying private data requires an explicit disclosure decision.

Acceptance: the exact nonproduction target and permitted data are recorded without credentials. Free-plan storage, compute, suspend/resume and recovery limits are checked against current official documentation. Paid upgrades and additional services are separate decisions; do not create them to bypass a free-plan limit.

### DB-NEON-01-C: Configure secure connections and roles

Dependency: B.

Use a direct connection for migrations and initial native acceptance. Require certificate and hostname verification, including `verify-full` and a valid trust source for libpq. Preserve the existing runner's validated scalar connection configuration. Keep credentials in protected, ignored configuration and never put passwords or credential-bearing URLs in commands, reports, fixtures or Git.

Separate migration/administrative, ingestion and retrieval privileges. Preserve the private `cragkit` schema, restricted grants, deny-by-default RLS and application-bound authorization. Inspect effective role memberships and ownership; reject owner, superuser or RLS-bypass access for normal runtime work. Keep authorization context transaction-local and reauthorize source release.

Acceptance: the native clients verify the intended endpoint; a certificate failure cannot trigger a TLS downgrade. Effective privileges and policies are reviewed for the actual roles. If a required platform security control is unavailable on the chosen plan, resolve that requirement before proceeding rather than silently weakening it.

### DB-NEON-01-D: Prepare the database explicitly

Dependency: C.

Inspect and apply existing checksummed migrations through the [explicit administrative runner](../tools/check_postgres.py). Preserve applied migration bytes and the Cragkit history ledger. Review platform-specific deployment hardening and adapt role handling for Neon; do not assume Supabase API roles or advisors exist there.

Verify the available `pgvector` version. Enable the extension through an explicit administrative step when the V2 vector implementation requires it; do not create profile tables or advance V2-04 in this migration slice. Core import, initialization and retrieval must not apply migrations or install extensions.

Acceptance: initial application, unchanged rerun, checksum/history validation, [integrity invariants](../storage/postgres/tests/invariants.sql) and [security probes](../storage/postgres/tests/security.sql) pass on the isolated target. Run probes only after inspecting their privileges, empty-target preconditions and rollback behavior. Preserve unrelated schemas and data.

### DB-NEON-01-E: Verify native behavior and isolation

Dependency: D.

Reinspect the verified commands in [development.md](development.md) and their actual tool interfaces before running them. Run one language integration suite at a time with small synthetic fixtures. Exercise ingestion, lexical retrieval, immutable source release, updates/deletion, migration compatibility and the actual restricted runtime roles in both Python and TypeScript.

Verify cross-tenant denial, same-tenant write restrictions, grant revocation, transaction-local scope cleanup, bounded pool waits, request deadlines, cancellation, rollback and connection cleanup. Administrative SQL and control-plane results are separate from native runtime acceptance. Existing fake-provider checks do not establish live model quality or Neon integration.

Start with direct connections. Validate transaction pooling separately before adopting it, including scope isolation, driver behavior and cleanup. Keep connection/model concurrency bounded. A suspended endpoint or exhausted free allowance must produce an operational failure, not a false claim of missing evidence or permission relaxation.

Acceptance: record exact commands, target configuration without secrets, results, resource observations, rollback/fixture cleanup and limitations. Use [the edge-case inventory](../tasks/EDGE_CASES.md), especially E17-E25, E47, E51, E58, E66, E69 and E73-E75. Vector-specific checks remain subject to V2-04 and later dependencies.

### DB-NEON-01-F: Record acceptance and cut over

Dependency: E, plus any required data-transfer decision and verified transfer.

Record Neon evidence and remaining limitations in the tracker and development documentation. Switch the development configuration only after native security/integration acceptance passes. If data is transferred, verify canonical digests, immutable revisions, scoped relationships, grants and active-generation consistency before using the destination.

Keep the existing Supabase project until the transition is verified. Deletion or retirement is a separate authorized action. Failure recovery must preserve source data and revoked permissions; it must not automatically fall back to a stale authorization state on the old host.

Acceptance: the selected configuration points to the verified Neon target; both native runtimes pass the required checks, and the migration's evidence is distinguishable from prior Supabase acceptance. Registry publication, hosted CI, live model evaluation and production readiness remain separate outcomes.

## Verification and handoff

This planning change needs local link, consistency, whitespace, sensitive-data and prose-hygiene checks. It does not require database calls, installations, model requests or product test runs. Completed historical milestones retain their recorded status; saving the plan does not complete DB-NEON-01.

After an execution instruction, begin with A. Before hosted testing, complete target and security preconditions B-D. Keep V2 implementation dependencies intact and record any new blocker rather than bypassing it. Use the project's resource policy and [coordination protocol](agents/WORKFLOW.md) if later work has independent lanes.

Failure case: an owner connection passes a query while a runtime role bypasses tenant policies. Acceptance must fail until the real restricted role passes both allowed-access and denial checks. Optional exercise: explain why a saved credential, a verified TLS connection and a verified authorization boundary are three different pieces of evidence.

## Official references to recheck before execution

- [Neon connection pooling](https://neon.com/docs/connect/connection-pooling): direct versus pooled connection behavior.
- [Neon security overview](https://neon.com/docs/security/security-overview): transport verification and platform protections.
- [Neon pgvector documentation](https://neon.com/docs/extensions/pgvector): extension availability and explicit installation.
- [Neon pricing](https://neon.com/pricing): current plan limits; this plan freezes no numeric allowance or price.
