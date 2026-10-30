# Cragkit implementation tracker

This is the single implementation completion tracker. All tasks start unchecked. Plan creation is not implementation completion. Read [the master plan](plan.md) and [edge-case inventory](EDGE_CASES.md).

V0: COMPLETE locally. V1: COMPLETE for the native lexical library milestone, including V1-10/V1-11/V1-12, V1-C4 and V1-EXIT. Local and hosted acceptance, artifact observations and limitations are recorded in [the final V1 report](../evaluation/reports/V1/V1-10-12.md). V2-01: COMPLETE as a design decision; hosted opt-in OpenAI text-embedding-3-small (1536 dimensions), routine fakes and live access disabled. V2-02/V2-03/V2-C1: COMPLETE locally. V2-04A-G: COMPLETE for optional setup, profile storage and native bounded generation staging/publication on the dedicated direct development target; [final evidence](../evaluation/reports/V2/V2-04G.md). V2-05: COMPLETE for internal exact dense candidates in both runtimes; [evidence](../evaluation/reports/V2/V2-05.md). V2-06/V2-C2: COMPLETE for internal exact identifiers and deterministic rank fusion in both runtimes; [evidence](../evaluation/reports/V2/V2-06.md). V2-07/V2-08/V2-C3/V2-EXIT: COMPLETE for the native/synthetic development milestone; [exit evidence](../evaluation/reports/V2/V2-07-08-exit.md). V3-01: COMPLETE as a documented contract/shortlist with recorded mechanical compatibility evidence; [report](../evaluation/reports/V3/V3-01.md). V3-02: COMPLETE for native injectable adapters and the bounded Cohere comparison; [evidence](../evaluation/reports/V3/V3-02D.md). V3-03/V3-C1: COMPLETE for standalone strict context accounting. V3-04: COMPLETE for PK-r1 packing/native opt-in source snapshots. V3-05: COMPLETE for AS-r1 curated coverage. V3-06/V3-C2: COMPLETE for EP-r1. V3-07: COMPLETE for the frozen development comparison. V3-08/V3-C3/V3-EXIT: COMPLETE for the declared native/curated development milestone; [exit evidence](../evaluation/reports/V3/V3-08-exit.md). Next: V4-01 shared execution ledger. Registry publication, generalized live-model quality and hosted CI evidence remain pending.
V4: COMPLETE for the internal native/synthetic development milestone, all tasks/checkpoints through V4-EXIT. [Final evidence and limits](../evaluation/reports/V4/V4-08-exit.md).


Use status notes when needed: READY, IN_PROGRESS, BLOCKED, IMPLEMENTED_UNVALIDATED, COMPLETE. Check a box only for COMPLETE and attach evidence. Public publication remains pending until actually authorized and verified.

## DB-NEON-01: Neon migration

Neon is the selected and verified direct development PostgreSQL host, following the user decision and authorized execution on 22 October 2026. PostgreSQL with pgvector and native FTS remains the selected backend; pgvector 0.8.0 is installed in the private vector namespace with checksummed optional profile storage under V2-04. The user selected a new dedicated Cragkit project in VAIBHAV's Free organization, Singapore, PostgreSQL 17. Existing Supabase acceptance remains evidence for its original target. Direct Neon development acceptance passed; see [the evidence](../evaluation/reports/V2/DB-NEON-01.md). V4 is complete for the internal native/synthetic milestone; [exit evidence](../evaluation/reports/V4/V4-08-exit.md). V5-03 source authorization and checkpoint V5-C1 are complete for the local native profile; V5-04 publication and repair is next. Supabase retirement, pooled connections and production setup are separate work and do not block this direct-endpoint development task.

- [x] DB-NEON-01: COMPLETE for direct-endpoint development and native lexical acceptance. Secure private configuration points to the verified Neon target. Vector storage remains V2-04; pooling and production acceptance are separate.
- [x] DB-NEON-01-PLAN: COMPLETE, documentation only. Saved the agreed plan; 13 local links/anchors, status/dependency consistency, whitespace, sensitive-data pattern review and self-contained prose checks passed. This planning slice did not establish hosted acceptance; subsequent B-F entries record actual direct development acceptance.
- [x] DB-NEON-01-A: COMPLETE. Both Sol peers delivered/assembled the Neon runbook and current development/storage guidance; root aligned architecture/master/version plans/README and historical Supabase banner. All 269 local links across 12 changed documents, prose hygiene and whitespace checks passed. This documentation slice did not establish hosted acceptance; the later native checks are recorded in C-E.
- [x] DB-NEON-01-B: COMPLETE. User-selected new Cragkit project `muddy-boat-55325449`, branch `br-square-surf-b3nra8du` (`development`), database `cragkit`, admin `cragkit_admin`, Singapore, PostgreSQL 17.11/UTF8, endpoint `ep-plain-queen-b37i9a2b`; plugin verified zero application tables and no Cragkit schema. Organization Free, compute fixed 0.25 CU, available pgvector 0.8.0; only synthetic fixtures, no Supabase transfer. Native TLS/security acceptance was subsequently completed in C-E.
- [x] DB-NEON-01-C: COMPLETE. Hidden credential import, owner-only external configuration, native certificate/hostname verification and SQL-created temporary restricted runtime roles passed. No administrator credentials reach Node; no permanent application policy was installed.
- [x] DB-NEON-01-D: COMPLETE. Explicit checksummed migrations and Neon hardening passed twice with unchanged ledger checksums/timestamps. Integrity, default-deny and three rolled-back negative security probes passed. Extension installation remains V2-04.
- [x] DB-NEON-01-E: COMPLETE. Native Python session 8, Node session 7 and combined ingestion/retrieval/lifecycle 32 groups passed, with independent cleanup. Local regressions: 598 Python/tool tests, 499 Node tests, both typechecks and all 16 seals passed. Pooling remains unvalidated.
- [x] DB-NEON-01-F: COMPLETE for development fixture configuration. Neon evidence, commands and limits recorded; the private direct configuration was verified after E. The fresh synthetic target required no transfer. Supabase was preserved; application provisioning and retirement remain separate.

### Execution assignment

These assignments and early next-action notes preserve their original checkpoint state. The completed C-F entries above record final direct development acceptance; that checkpoint selected V3-02 next; the current next action is recorded in the summary above.

DB-NEON-01-A-r1 shared outcome: align Neon hosting guidance without changing portable storage semantics or claiming hosted acceptance. Sol peer `neon_runbook` owns `docs/neon.md` and assembles the pair; Sol peer `neon_development` owns `docs/development.md` and `storage/postgres/README.md`, plus a read-only review of existing native/security harness compatibility. Both use `gpt-6.1-sol` and coordinate directly. Root owns architecture/master/version-plan/README, Supabase historical banner, migration-plan authorization update, tracker/evidence, serialized schema/tool changes, target provisioning and all test/Git execution. Peer modes: documentation implementation and read-only security review. No peer writes to native source, manifests, locks, migrations, corpus, credentials or tracker, and no peer runs services, installs, model calls or database operations. Acceptance: source-backed TLS/role/pooling guidance, existing commands distinguished from unrun Neon acceptance, local links/prose checks; root later runs scoped security/integration tests serially. Final integrator/escalation owner: root. State: assigned. Initial resources: 28 GiB available disk, 16 GiB RAM; lightweight work, no task services. Existing untracked security report preserved. Learning pending.

A-r1 integration: both peers stopped writing and the assembler inspected their three documents. Root inspected final diffs and ran a local Python existence check for all 269 local Markdown links, self-contained inspect/clean checks (zero suspicious characters, low/medium density, unchanged cleaned bytes) and `git diff --check`. All passed. Current host guidance is Neon; historical V0/V1 Supabase acceptance is preserved. The plugin verified VAIBHAV is Free and found no Cragkit project; unrelated projects are excluded. Official Neon roles/TLS/plans docs were read through the plugin. Findings for subsequent slices: API-created roles inherit broad administrative membership, so runtime roles use SQL; the native harness's pre-hashed SCRAM password conflicts with Neon's documented plain-password input and needs a tested explicit adaptation. No database write, dependency install, service, model or product test occurred during A. Next: provision the selected dedicated target and complete B before security configuration.

B handoff: first provisioning request was rejected with HTTP 412 because Free forbids changing the suspend interval, including an explicit five-minute value. Plugin re-list confirmed no project was created; a request omitting that setting succeeded with fixed 0.25 CU. The API reports a zero suspend field; current official Free documentation mandates five-minute scale-to-zero, so that field is not treated as proof of always-on compute. Plugin preflight reports server-side SSL off/session SSL false behind Neon's proxy; this is not native TLS evidence. C must verify client-side TLS/certificate/hostname rather than assume a backend `pg_stat_ssl` flag proves the public transport. No extension, schema, data copy or runtime roles have been created.

C-r1 assignment: same Sol pair, root final integrator and sole test/database/Git owner. `neon_development` owns `tools/save_neon_config.py` and `tools/tests/test_save_neon_config.py` for a hidden-input, exact-target, owner-only non-overwriting credential/config importer. `neon_runbook` owns `tools/check_python_postgres.py` and new `tools/tests/test_check_python_postgres.py` for an explicit Neon fixture mode: direct validated host, client-side TLS proof before plain-password SQL role creation, safe error output, existing non-Neon behavior preserved. Shared C-r1 contract: no secret in argv/logs, no TLS downgrade, no permanent broad application policy, no changes to native drivers/contracts/migrations/locks/corpus. Root owns separate Neon administrative wrapper/deployment hardening and all docs/tracker. Peers communicate directly and may review each other's disjoint files; no SQL, installs, services or tests by peers. State: assigned; local tests then native checks required for completion.

C-r1 scope refinement: `neon_runbook` also owns `tools/check_ingestion.py` for explicit Python writer transport propagation; root owns `tools/check_typescript_postgres.mjs` and `packages/typescript/tests/neon-transport.test.mjs` for native Node TLS proof. C1 importer finished; root's first 40 synthetic importer/fixture checks passed. A final importer fix rejects channel-binding parameters rather than claiming unsupported enforcement. The plugin URI contains provider-default pooled/TLS suggestions; root selected the independently listed direct host and Cragkit's fixed verify-full scalar transport policy. Channel binding is not configured or claimed. Hidden input rejected the first pooled target without writing files, then saved the selected direct credential/config as owner-only files outside the checkout. No secret entered shell argv or output. Native libpq direct TLS, exact database/admin identity and PostgreSQL17.11/UTF8 passed. Three existing pinned optional psycopg packages were restored with frozen uv sync; no new dependency or lock change.

D1 assignment after native C transport preflight: root transfers its unstarted administrative wrapper/hardening ownership to Sol `neon_development`, writable only `tools/check_neon_postgres.py`, `tools/tests/test_check_neon_postgres.py`, `storage/postgres/deployment/neon.sql`. Existing migration/security/invariant scripts are read-only dependencies. Implement bounded explicit direct-Neon admin checks using validated private config, client TLS proof, checksummed migrations, separate hardening and existing rollback probes; safe CLI errors and no secret output. No peer SQL/tests/installs/services/Git. Root owns target use, Node changes, combined tests and tracker; native runtime authorization remains pending D-E. State: assigned.

### Final execution handoff

22 October 2026: DB-NEON-01 COMPLETE within direct-endpoint development/native lexical scope. Both Sol peers finished their disjoint implementation and security reviews; root inspected the source, serialized live/local tests and retained tracker/Git ownership. Changed artifacts: private importer and synthetic tests; explicit Neon admin wrapper and hardening; Python/Node fixture TLS/password compatibility and regressions; runbook, development/storage/version/master guidance, E79-E81 and [the evidence report](../evaluation/reports/V2/DB-NEON-01.md). Core runtime APIs, applied migrations, manifests, locks and sealed inputs remain unchanged. The unrelated untracked V1 security evaluation is excluded.

Verification passed: 598 Python/tool tests, 499 Node tests, both typechecks, 16 seals, repeated native migrations/integrity/security probes and 47 overlapping native groups. Three deliberately unsafe database mutations were rejected and rolled back. Independent final inspection found zero application rows, probe roles, policies or SECURITY DEFINER functions and nine of nine tables with RLS. Initial Node guarded-socket and Python fixture-timeout failures, their corrections and final passing evidence are recorded in the report; no core authorization or deadline was weakened. Final documentation checks passed: 230 local file targets, 69 anchors, zero suspicious Unicode characters, low prose density, unchanged deterministic-cleaner output and whitespace checks. Final staged scope is reviewed before each commit.

Resources: 28 GiB available disk, 63% memory free; one test process/language integration suite at a time, maximum two native connections. Only three existing pinned optional psycopg packages were restored. No task-owned service, background process or model download remains. Credentials remain owner-only outside Git. Supabase is untouched. No production, pooled endpoint, hosted CI, live-model quality or universal zero-leakage claim. Learning remains pending; the report offers a transport-versus-authorization exercise. Next smallest action: V2-04 vector generation/reindex slice, including explicit pgvector installation under its own acceptance gate.

### Planning handoff

22 October 2026: COMPLETE for saving the plan and tracker only. Root used one writer for the dependent two-document change; no delegated lane was needed. Changed files: `docs/neon-migration-plan.md` and `tasks/todo.md`. The plan records the Neon host decision, six ordered future slices, security invariants, verification gates, data-transfer decision and separate Supabase retirement. Existing governing setup instructions and historical acceptance reports remain unchanged pending DB-NEON-01-A.

Validation: an inline local Python review checked all 13 local links/anchors in the plan and new tracker section, deferred-execution/V2 consistency, whitespace and credential patterns. `git diff --check` passed. The installed clean-user-facing-text `inspect_text.py --stylometry --json` and `clean_text.py --stats --no-normalize-spaces` checks found zero suspicious characters and byte-identical output for both documents; both density tiers were low. Final staged scope and Git synchronization are checked separately at publication. Product tests, database/native integration, hosted CI and live-provider checks were not run for this documentation task.

Resources: lightweight local file checks only; no task-owned installations, model downloads, services or background processes. The existing untracked security evaluation is excluded. No credentials, environment configuration, database resources, migration SQL, implementation, manifests, locks or sealed corpus inputs were changed by this task. Learning remains pending; the plan offers a TLS-versus-authorization exercise. Next smallest action: await an execution instruction, then begin DB-NEON-01-A; hosted work must satisfy B-D first. V2-04 remains the next product implementation task.

## GIT-01: GitHub repository and version control

State: COMPLETE. User explicitly authorized creating the GitHub repository, committing the project and pushing changes. The private [vsuman00/Cragkit repository](https://github.com/vsuman00/Cragkit) has the reviewed 119-file baseline on `main`, initial commit `feb2bdd374041d0f5bf6990c81b5b3d71fa4f229`. Matching local/remote commits, zero ahead/behind and a clean working tree were verified after the initial push. [Evidence](../evaluation/reports/V0/GIT-01.md). Package registry publication and hosted CI activation remain separate.

Shared outcome: publish a reviewed project baseline with explicit ignore rules, safe upload scope, a useful entrypoint and a repeatable commit/push workflow. `/root/coordinate_peer` (Sol), assembler, owns `README.md` and `docs/version-control.md`; `/root/manager_peer` (Sol) owns `evaluation/reports/V0/GIT-01.md` for inventory and upload review. `/root` owns Git initialization, candidate-file inventory, repository creation, staging/commit/push, ignore/configuration changes, current repository facts in docs, tracker and final verification. Peers communicate directly about scope and workflow; the Git index/configuration/remotes retain one writer. Native source, manifests/locks, approved corpus and seal are read-only. No package publication, credentials, local environments, generated artifacts, service startup or CI activation. Acceptance: staged scope reviewed, credential/ignore/whitespace/link/prose/seal checks, authenticated private repository, successful push, matching local/remote commit and zero ahead/behind. Prior V0 test evidence remains scoped to its recorded inputs.

GIT-01 handoff: initialized Git and private GitHub origin, added the repository entrypoint and version-control guide, persisted authorization for completed scoped commits plus immediate pushes, and reviewed the full upload. Ignore rules exclude environments, dependency/build output, generated artifacts and private-key files. Credential review identified only the original localhost placeholder; all 16 sealed input hashes matched the staged index. Whitespace and eight-document/124-link/prose checks passed. Root trimmed three whitespace-only historical HTML lines with substantive content preserved. No native source/lock/label changes or implementation test rerun, services, live-provider/database calls, package publication or hosted CI activation. Both peers finished their disjoint documentation/audit work; no task-owned processes remain. Learning remains pending. Next smallest product action: V1-01; future accepted changes follow docs/version-control.md. This publication record is committed and pushed as a separate documentation update, with final synchronization reported at task completion.

## V0: Foundations and learning setup

[Version plan](versions/V0-foundations.md)

- [x] V0-01: [Workspace and resource baseline](versions/V0-foundations.md#v0-01-workspace-and-resource-baseline) — COMPLETE; [measured baseline](../evaluation/reports/V0/V0-01.md) and [verified tools/policy](../docs/development.md). Final integrator inspected actual reports and links; no credentials/services/DB calls. Dedicated hosted target must be verified before use.

- [x] V0-02: [Minimal package skeletons](versions/V0-foundations.md#v0-02-minimal-package-skeletons) — COMPLETE; installed Python import smoke 1/1, TypeScript typecheck/build and import smoke 1/1, network/dependency/I/O guards active. [Commands](../docs/development.md#v0-02-package-smoke-checks).

- [x] V0-03: [Compatibility and dependency policy](versions/V0-foundations.md#v0-03-compatibility-and-dependency-policy) — COMPLETE; exact locks, dependency trees and disk sizes inspected; Pydantic/Zod strict probes passed; optional psycopg/pool and isolated npm pg import probes passed without DB connections. [Evidence](../evaluation/reports/V0/V0-03.md).

- [x] V0-C1: COMPLETE; both guarded import tests, Python strict typecheck and TypeScript typecheck/build passed after minimal dependency installs; [evidence/learning limitations](../evaluation/reports/V0/V0-03.md).

- [x] V0-04: [Request and error contracts](versions/V0-foundations.md#v0-04-request-and-error-contracts) — COMPLETE; Python 61 tests, TypeScript 41 tests, both strict typechecks/build and 34 shared normalized/error cases passed. Three structural schemas validated and drift checked. [Evidence](../evaluation/reports/V0/V0-04.md).

- [x] V0-05: [Evidence and result contracts](versions/V0-foundations.md#v0-05-evidence-and-result-contracts) — COMPLETE; Python 110 tests, TypeScript 78 tests, both strict typechecks/build, 66 shared request/result conformance cases and four schema drift checks passed. [Evidence](../evaluation/reports/V0/V0-05.md).

- [x] V0-06: [Tiny corpus and evaluation protocol](versions/V0-foundations.md#v0-06-tiny-corpus-and-evaluation-protocol) — COMPLETE; the user explicitly approved all 30 labels on 19 October 2026. Required-review check passed (30 questions/37 facets/26 spans, zero pending), 16 corpus tests and all 16 sealed hashes passed. [Evidence](../evaluation/reports/V0/V0-06.md), [approval and seal](../evaluation/review/seal.json).

- [x] V0-C2: COMPLETE; 126 Python/package-tool tests, 78 TypeScript tests, both typechecks, 66 shared conformance cases and four schema checks passed after human review. Learning remains pending; no quality or production claim.

- [x] V0-07: [Minimal CI and baseline checkpoint](versions/V0-foundations.md#v0-07-minimal-ci-and-baseline-checkpoint) — COMPLETE locally; all 12 CI stages passed, including 155 Python/tool tests, 78 TypeScript tests, typing/conformance/schema/corpus/seal checks and clean wheel/sdist/npm installation. [Evidence](../evaluation/reports/V0/V0-07.md). Hosted CI remains unrun because no repository/remote exists.

- [x] V0-C3: COMPLETE; full local pipeline, installed request/result demonstration, seal-drift and pipeline-failure regressions, scoped fresh-process resource samples and documentation checks passed. [Evidence](../evaluation/reports/V0/V0-07.md). Learning remains pending beyond completed human label review.

- [x] V0-EXIT: COMPLETE locally; both native internal packages accept shared fixtures, the 12-document/30-question corpus has explicit human approval and a 16-file seal, package artifacts install cleanly, and local CI is repeatable. Hosted CI, database integration, live models and publication remain separate pending work.

## V1: First usable lexical library

[Version plan](versions/V1-first-library.md)

- [x] V1-01: [Schema and explicit migrations](versions/V1-first-library.md#v1-01-schema-and-explicit-migrations) — COMPLETE; local and hosted migration/rerun/integrity/security checks passed, followed by authenticated native direct SQL with libpq verify-full/TLS 1.3. [Local evidence](../evaluation/reports/V1/V1-01.md), [hosted and native acceptance](../evaluation/reports/V1/V1-01-H-hosted.md#acceptance-and-next-action).

- [x] V1-02: [Python connection lifecycle](versions/V1-first-library.md#v1-02-python-connection-lifecycle) — COMPLETE; both children and final runtime-role acceptance passed.
  - [x] V1-02A: Internal optional pool resources — COMPLETE; 27 focused/199 Python-tool cases, strict typing, sealed hashes and hosted owned/borrowed TLS lifecycle smoke passed. [Evidence](../evaluation/reports/V1/V1-02A.md).
  - [x] V1-02B: Schema/capability validation, parameterized filters, transaction-local scope, statement budgets and real runtime-role verification — COMPLETE; 66 focused/238 combined cases, strict typing, final hosted runtime-login/cleanup and security probes passed. [Evidence](../evaluation/reports/V1/V1-02B.md).

- [x] V1-03: [TypeScript connection lifecycle](versions/V1-first-library.md#v1-03-typescript-connection-lifecycle) — COMPLETE; 58 focused/136 full Node cases, strict typing and seven real hosted runtime-role/cleanup groups passed. [Evidence](../evaluation/reports/V1/V1-03.md).

- [x] V1-C1: COMPLETE; Python 238/Node 136 regressions, both typechecks, 66 shared cases, four schemas, SQL parity and 16 sealed hashes passed; learning exercise offered, learning remains pending. [Evidence](../evaluation/reports/V1/V1-03.md).

- [x] V1-04: [Canonical text and source spans](versions/V1-first-library.md#v1-04-canonical-text-and-source-spans) — COMPLETE; 52 Python/72 Node focused cases, both typechecks/build and 23 exact shared fixtures passed. [Evidence](../evaluation/reports/V1/V1-04.md).

- [x] V1-05: [Python staged ingestion](versions/V1-first-library.md#v1-05-python-staged-ingestion) — COMPLETE; 37 focused/327 combined Python-tool cases, strict typing and eight hosted runtime-role ingestion/cleanup groups passed. [Evidence](../evaluation/reports/V1/V1-05.md).

- [x] V1-06: [TypeScript ingestion parity](versions/V1-first-library.md#v1-06-typescript-ingestion-parity) — COMPLETE; 58 Node/39 Python focused cases, exact shared identifier oracle and 14 hosted groups with both write/read directions passed. [Evidence](../evaluation/reports/V1/V1-06.md).

- [x] V1-C2: COMPLETE; 266 Node/329 Python-tool regressions, both typechecks/build, 66 wire cases, four schemas and 16 sealed hashes passed; hosted parity/rollback demonstrated, learning pending. [Evidence](../evaluation/reports/V1/V1-06.md).

- [x] V1-07: [Scoped lexical retrieval](versions/V1-first-library.md#v1-07-scoped-lexical-retrieval) — COMPLETE; 62 Python/87 Node focused cases, 357 Python-tool/300 Node regressions and 19 hosted groups passed, including both runtime filter-before-limit and exclusion checks. [Evidence](../evaluation/reports/V1/V1-07.md).

- [x] V1-08: [Source-backed result assembly](versions/V1-first-library.md#v1-08-source-backed-result-assembly) — COMPLETE; 50 Python/63 Node focused cases, 407 Python/tool/363 Node regressions and 24 hosted groups passed, including exact source parity, direct source denial and corruption refusal. [Evidence](../evaluation/reports/V1/V1-08.md).

- [x] V1-09: [Revision publication and deletion](versions/V1-first-library.md#v1-09-revision-publication-and-deletion) — COMPLETE; 72 Python/108 Node ingestion-lifecycle focused cases, 435 Python/tool/408 Node regressions and 30 hosted groups passed. [Evidence](../evaluation/reports/V1/V1-09.md).

- [x] V1-C3: COMPLETE; controlled update ordering, immutable retained source, tombstone/purge and reinsertion rollback demonstrated in both runtimes; regressions/typechecks, 66 wire cases/four schemas/16 sealed hashes passed. Learning exercise offered; learning remains pending. [Evidence](../evaluation/reports/V1/V1-09.md).

- [x] V1-10: [Permission changes and final authorization](versions/V1-first-library.md#v1-10-permission-changes-and-final-authorization) — COMPLETE. [Acceptance evidence](../evaluation/reports/V1/V1-10-12.md).

- [x] V1-11: [Deadlines and cancellation](versions/V1-first-library.md#v1-11-deadlines-and-cancellation) — COMPLETE. [Acceptance evidence](../evaluation/reports/V1/V1-10-12.md).

- [x] V1-12: [First library demo and artifacts](versions/V1-first-library.md#v1-12-first-library-demo-and-artifacts) — COMPLETE. [Acceptance evidence](../evaluation/reports/V1/V1-10-12.md).

- [x] V1-C4: COMPLETE. Full local profile and 32 hosted lifecycle groups passed; examples, failure case, learning explanation and resource observations recorded. User learning practice remains pending. [Evidence](../evaluation/reports/V1/V1-10-12.md).

- [x] V1-EXIT: COMPLETE for the scoped native lexical library milestone. Installed artifacts, access isolation and lifecycle acceptance passed. Publication, hosted CI and later model capabilities remain outside this acceptance. [Evidence](../evaluation/reports/V1/V1-10-12.md).

## V2: Hybrid retrieval

[Version plan](versions/V2-hybrid-search.md)

- [x] V2-01: [Embedding profile decision](versions/V2-hybrid-search.md#v2-01-embedding-profile-decision) — COMPLETE as a design decision. Owner selected hosted opt-in text-embedding-3-small, 1536 dimensions; current live allowance remains zero. [Metadata/synthetic interface evidence and live limits](../docs/decisions/0001-embedding-profile.md).

- [x] V2-02: [Python embedding adapter](versions/V2-hybrid-search.md#v2-02-python-embedding-adapter) — COMPLETE locally; 109 focused/544 Python-tool checks, strict typing 16 files, guarded import. [Evidence and live limits](../evaluation/reports/V2/V2-02.md).

- [x] V2-03: [TypeScript embedding adapter](versions/V2-hybrid-search.md#v2-03-typescript-embedding-adapter) — COMPLETE locally; 88 focused Node cases, 41 shared embedding cases and installed entry-point checks. [Evidence](../evaluation/reports/V2/V2-03-C1.md).

- [x] V2-C1: COMPLETE locally; 13 serial stages, 544 Python/tool and 496 Node cases, typing/build, shared parity, clean artifacts and resource/learning notes. [Evidence and live limits](../evaluation/reports/V2/V2-03-C1.md).

- [x] V2-04: [Vector generations and reindex](versions/V2-hybrid-search.md#v2-04-vector-generations-and-reindex) — COMPLETE A-G for dedicated direct development and local package acceptance; [final evidence and limits](../evaluation/reports/V2/V2-04G.md). Dense retrieval remains V2-05.
  - [x] V2-04A: [Explicit pgvector setup](versions/V2-hybrid-search.md#v2-04a-explicit-pgvector-setup) — COMPLETE on dedicated direct development target under explicit A-r2 managed profile. [Evidence and security limits](../evaluation/reports/V2/V2-04A.md).
  - [x] V2-04B: [Profile-specific vector storage](versions/V2-hybrid-search.md#v2-04b-profile-specific-vector-storage) — COMPLETE with B1 optional runner; [evidence](../evaluation/reports/V2/V2-04B.md).
  - [x] V2-04C: [Python bounded vector staging](versions/V2-hybrid-search.md#v2-04c-python-bounded-vector-staging) — COMPLETE; [native/local evidence](../evaluation/reports/V2/V2-04C.md).
  - [x] V2-04D: [Python safe generation publication](versions/V2-hybrid-search.md#v2-04d-python-safe-generation-publication) — COMPLETE; [native/local evidence](../evaluation/reports/V2/V2-04D.md).
  - [x] V2-04E: [TypeScript bounded vector staging](versions/V2-hybrid-search.md#v2-04e-typescript-bounded-vector-staging) — COMPLETE; [native/local evidence](../evaluation/reports/V2/V2-04E.md).
  - [x] V2-04F: [TypeScript safe generation publication](versions/V2-hybrid-search.md#v2-04f-typescript-safe-generation-publication) — COMPLETE; [publication evidence](../evaluation/reports/V2/V2-04F.md).
  - [x] V2-04G: [Integrated generation acceptance](versions/V2-hybrid-search.md#v2-04g-integrated-generation-acceptance) — COMPLETE; [integrated acceptance](../evaluation/reports/V2/V2-04G.md).

- [x] V2-05: [Scoped dense retrieval](versions/V2-hybrid-search.md#v2-05-scoped-dense-retrieval) — COMPLETE A-D for internal native adapters, shared parity and dedicated direct development acceptance; [evidence and limits](../evaluation/reports/V2/V2-05.md).

- [x] V2-06: [Identifier search and rank fusion](versions/V2-hybrid-search.md#v2-06-identifier-search-and-rank-fusion) — internal native adapters/fusion complete; [evidence](../evaluation/reports/V2/V2-06.md).

- [x] V2-C2: Demonstration, regression/parity/native/artifact checks, learning explanation and resource note through V2-06; [evidence](../evaluation/reports/V2/V2-06.md). User practice pending.

- [x] V2-07: [Hybrid orchestration and fallbacks](versions/V2-hybrid-search.md#v2-07-hybrid-orchestration-and-fallbacks) — COMPLETE, both public native runtimes under HY-r1; [evidence](../evaluation/reports/V2/V2-07-08-exit.md).

- [x] V2-08: [Hybrid evaluation and checkpoint](versions/V2-hybrid-search.md#v2-08-hybrid-evaluation-and-checkpoint) — COMPLETE for the frozen development-only synthetic comparison; [metrics and limitations](../evaluation/reports/V2/V2-07-08-exit.md).

- [x] V2-C3: Demonstration, regression/parity/native/clean-artifact checks, failure explanation and resource note passed; [evidence](../evaluation/reports/V2/V2-07-08-exit.md). User practice pending.

- [x] V2-EXIT: COMPLETE for the V2 native/synthetic development milestone; [acceptance and remaining limits](../evaluation/reports/V2/V2-07-08-exit.md).

## V3: Evidence selection and honest coverage

[Version plan](versions/V3-evidence-quality.md)

- [x] V3-01: [Reranker contract and shortlist](versions/V3-evidence-quality.md#v3-01-reranker-contract-and-shortlist) — COMPLETE, documented RK-r1, local/API shortlist and recorded-example inspection; [evidence](../evaluation/reports/V3/V3-01.md).

- [x] V3-02: [Bounded reranking adapters](versions/V3-evidence-quality.md#v3-02-bounded-reranking-adapters) — COMPLETE for injectable native adapters plus bounded hosted comparison; [evidence](../evaluation/reports/V3/V3-02.md).
  - [x] V3-02A/B: native injectable adapters and focused failure checks.
  - [x] V3-02C: shared 11-case parity, guarded installed imports and 18-stage regression checkpoint.
  - [x] V3-02D: configured Cohere comparison passed in both runtimes; [observations](../evaluation/reports/V3/V3-02D-results.json).

- [x] V3-03: [Tokenizer and renderer contract](versions/V3-evidence-quality.md#v3-03-tokenizer-and-renderer-contract) — COMPLETE for TK-r1; [evidence](../evaluation/reports/V3/V3-03-C1.md).

- [x] V3-C1: Corrected tokenizer pair, 20-stage serial checkpoint, demonstration and resource notes; [evidence](../evaluation/reports/V3/V3-03-C1.md). Learning practice pending.

- [x] V3-04: [Extractive packing](versions/V3-evidence-quality.md#v3-04-extractive-packing) — COMPLETE; [evidence](../evaluation/reports/V3/V3-04.md).

- [x] V3-05: [Facet assessment policy](versions/V3-evidence-quality.md#v3-05-facet-assessment-policy) — COMPLETE for reviewed-span.v1; [evidence](../evaluation/reports/V3/V3-05.md).

- [x] V3-06: [Post-packing reassessment](versions/V3-evidence-quality.md#v3-06-post-packing-reassessment) — COMPLETE for EP-r1; [evidence](../evaluation/reports/V3/V3-06-C2.md).

- [x] V3-C2: 23-stage local and 16-group native checkpoint passed; [evidence](../evaluation/reports/V3/V3-06-C2.md). Learning practice pending.

- [x] V3-07: [Calibrate evidence policy](versions/V3-evidence-quality.md#v3-07-calibrate-evidence-policy) — COMPLETE for the frozen curated development comparison; [evidence](../evaluation/reports/V3/V3-07.md).

- [x] V3-08: [Evidence release checkpoint](versions/V3-evidence-quality.md#v3-08-evidence-release-checkpoint) — COMPLETE with installed/native source, authorization, token and coverage checks; [evidence](../evaluation/reports/V3/V3-08-exit.md).

- [x] V3-C3: Final 23-stage and installed/native acceptance passed; [evidence](../evaluation/reports/V3/V3-08-exit.md). Learning practice pending.

- [x] V3-EXIT: COMPLETE for the native/curated development milestone; [evidence and limits](../evaluation/reports/V3/V3-08-exit.md).

## V4: Corrective retrieval alpha

[Version plan](versions/V4-corrective-alpha.md)

- [x] V4-01: [Shared execution ledger](versions/V4-corrective-alpha.md#v4-01-shared-execution-ledger) — evidence: [local acceptance](../evaluation/reports/V4/V4-01.md).

- [x] V4-02: [Optional structured planning](versions/V4-corrective-alpha.md#v4-02-optional-structured-planning) — evidence: [local acceptance](../evaluation/reports/V4/V4-02.md).

- [x] V4-03: [Targeted corrective search](versions/V4-corrective-alpha.md#v4-03-targeted-corrective-search) — evidence: [local core acceptance](../evaluation/reports/V4/V4-03-05.md); final source checkpoint follows branch-budget regression.

- [x] V4-C1: Demonstration, relevant regression checks, learning review and resource note through V4-03.

- [x] V4-04: [Loop termination and fault recovery](versions/V4-corrective-alpha.md#v4-04-loop-termination-and-fault-recovery) — evidence: [local core acceptance](../evaluation/reports/V4/V4-03-05.md); final source checkpoint follows branch-budget regression.

- [x] V4-05: [Privacy-controlled events](versions/V4-corrective-alpha.md#v4-05-privacy-controlled-events) — evidence: [local core acceptance](../evaluation/reports/V4/V4-03-05.md); final source checkpoint follows branch-budget regression.

- [x] V4-06: [Python framework adapter](versions/V4-corrective-alpha.md#v4-06-python-framework-adapter) — evidence: [native SDK and installed-artifact acceptance](../evaluation/reports/V4/V4-06-07.md).

- [x] V4-C2: Demonstration, relevant regression checks, learning review and resource note through V4-06.

- [x] V4-07: [TypeScript framework adapter](versions/V4-corrective-alpha.md#v4-07-typescript-framework-adapter) — evidence: [native SDK and installed-artifact acceptance](../evaluation/reports/V4/V4-06-07.md).

- [x] V4-08: [Corrective quality and alpha packaging](versions/V4-corrective-alpha.md#v4-08-corrective-quality-and-alpha-packaging) — evidence: [complete native/synthetic milestone](../evaluation/reports/V4/V4-08-exit.md).

- [x] V4-C3: Demonstration, relevant regression checks, learning review and resource note through V4-08.

- [x] V4-EXIT: Version acceptance complete; evidence and limitations recorded.

### Post-exit operational follow-ups

[Readiness recheck](../evaluation/reports/V4/V4-READINESS.md): the feature milestone remains accepted. V5-01 design may begin; resolve these before V5 backend implementation/native acceptance.

- [x] V4-AUD-02: Bounded redacted primary/cleanup diagnostics, hostile-error and secret-canary regressions accepted in the final 34-stage checkpoint. [Evidence](../evaluation/reports/V4/V4-SECURITY-VERIFICATION.md).
- [x] V4-AUD-01: Private exact-ownership journal, bounded fresh-connection recovery, safe deletion-graph refusal, real interruption/replay/canary probes and final empty inventory accepted. Full native functionality passed the explicit 60,000 ms administrative profile; current default 10,000 ms native attempts remain failed performance evidence. The historical cleanup cause remains unproven. [Evidence](../evaluation/reports/V4/V4-SECURITY-VERIFICATION.md).


## V5: Backend and transport extensions

[Version plan](versions/V5-integrations.md)

- [x] V5-01: [Alternative-store consistency specification](versions/V5-integrations.md#v5-01-alternative-store-consistency-specification) — [ADR 0003](../docs/decisions/0003-qdrant-consistency.md), [QD-r1](../contracts/QDRANT_V5.md) and [26 normative scenarios](../contracts/fixtures/qdrant_consistency.json); 21 failure boundaries walked through, independent review resolved, JSON/row/link/prose checks passed. Design acceptance only; adapter execution remains V5-02 through V5-04.

- [x] V5-02: [Qdrant scoped candidate adapter](versions/V5-integrations.md#v5-02-qdrant-scoped-candidate-adapter) — [initial B/C/D acceptance](../evaluation/reports/V5/V5-02.md) and [E dense-profile/batch/example acceptance](../evaluation/reports/V5/V5-02E.md). Source authorization/publication remain V5-03/04.

  - [x] V5-02A: Candidate/filter/profile contract, deterministic identity and isolated reference target selected and verified. [QC-r1](../contracts/QDRANT_CANDIDATES_V5.md), [fixtures](../contracts/fixtures/qdrant_candidates.json), [version/target/prototype evidence](../evaluation/reports/V5/V5-02A.md). Native candidate implementation and full adapter integration remain B/C/D.
  - [x] V5-02B: Native Python candidate adapter and focused negative cases accepted for initial QC-r1 profiles.
  - [x] V5-02C: Native TypeScript candidate adapter and focused negative cases, including E83, accepted for initial QC-r1 profiles.
  - [x] V5-02D: Serial isolated Qdrant candidate acceptance and final resource shutdown verified for initial profiles.
  - [x] V5-02E: Selected OpenAI dense-only profile, full-profile embedding batch binding, accounting and bounded examples accepted; no paid call made. [Evidence](../evaluation/reports/V5/V5-02E.md).

- [x] V5-03: [Source resolution and authorization](versions/V5-integrations.md#v5-03-source-resolution-and-authorization) — native reader/source/disclosure acceptance complete for the isolated local profile; [V5-03D/C1](../evaluation/reports/V5/V5-03D.md).
  - [x] V5-03A: QS-r1, 40 normative scenarios and isolated optional PostgreSQL schema; 20 focused tests, 1615 Python/tool regressions and six rolled-back native SQL groups passed. [Evidence](../evaluation/reports/V5/V5-03A.md).
  - [x] V5-03B/C: Native source readers, verification and private request bindings; 97 focused/1692 full Python-tool tests, strict types and 57 focused/975 full Node tests passed. [Evidence](../evaluation/reports/V5/V5-03BC.md).
  - [x] V5-03D: Actual restricted reader LOGIN, 14 PostgreSQL/Qdrant source/provider-spy/final-release/outage cases per runtime, full parity and negative TLS checks. [Evidence](../evaluation/reports/V5/V5-03D.md).

- [x] V5-C1: Native demonstration, 1725 Python/tool and 980 Node package regressions, strict types/build and scoped security checks passed; learning practice unassessed. [Evidence](../evaluation/reports/V5/V5-03D.md).

- [ ] V5-04: [Publication and repair](versions/V5-integrations.md#v5-04-publication-and-repair) — implementation and native fault acceptance pending.
  - [x] V5-04A: QW-r1 publication/recovery boundary, 43 fault scenarios, 14 numeric cases and computed cross-runtime goldens; [design acceptance](../evaluation/reports/V5/V5-04A.md).
  - [x] V5-04B1: Pure native vector encoders and readback validators; 71 focused Python/25 Node cases, 1796 Python/tool and 1005 Node regressions, strict types and 21 cross-runtime comparisons passed. [Evidence](../evaluation/reports/V5/V5-04B1.md).
  - [x] V5-04B2: Immutable generation/intent manifests and portable replay serialization; 41 focused Python/27 Node cases, 1837 Python/tool and 1032 Node regressions, strict types and 33 parity cases passed. [Evidence](../evaluation/reports/V5/V5-04B2.md).
  - [x] V5-04C: Additive authority schema, writer privileges and exact reader/catalog compatibility; C1/C2 accepted. Native writer/coordinator/recovery operations remain D-H.
    - [x] V5-04C1: Additive publication migration; 17 local PostgreSQL acceptance groups, 27 focused tests, 1864 Python/tool and 1032 Node regressions plus strict types/build passed. [Evidence](../evaluation/reports/V5/V5-04C1.md).
    - [x] V5-04C2: Exact old/new native reader profiles; 66 focused Python/tool and 17 Node tests, 1899 Python/tool and 1038 Node regressions, strict types/build and 56 final native source-case executions passed. [Evidence](../evaluation/reports/V5/V5-04C2.md).
  - [x] V5-04D: Native authoritative writers; 70 focused Python/tool and 17 Node cases, 1969 Python/tool and 1055 Node regressions, strict types/build, 42 local SQL/native authority checks and 16 seals passed. [Evidence](../evaluation/reports/V5/V5-04D.md).
  - [x] V5-04E: Exclusive supervisor and durable instance recovery; E1/E2 accepted within the selected native profile.
    - [x] V5-04E1: Native controller/immutable credentials; 32 focused Python/tool and nine Node groups, 2001 Python/tool and 1064 Node regressions, strict types/build, 18 actual process/key checks and 16 seals passed. [Evidence](../evaluation/reports/V5/V5-04E1.md).
    - [x] V5-04E2: Durable recovery gate, per-document authorized reconciliation and private settlement admission.
      - [x] V5-04E2a: Authority-bound full readback; 2054 Python/tool and 1078 Node regressions, strict types/build, 36 native readback checks, normalized witness parity, 42 native D regression checks and 16 seals passed. [Evidence](../evaluation/reports/V5/V5-04E2a.md).
      - [x] V5-04E2b: Durable instance control and private admission; 2108 Python/tool and 1094 Node regressions, strict types/build, 50 native SQL/recovery checks, 54 native controller/readback regression checks and 16 seals passed. [Evidence](../evaluation/reports/V5/V5-04E2b.md).
  - [x] V5-04F: Actual bounded staged writes, full readback/publication and native ordinary worker profile; F1/F2/F3 accepted. Repair and the full fault matrix remain G/H.
    - [x] V5-04F1: Ordinary current-authority projections and private full-readback receipts; 2,136 Python/tool and 1,106 Node regressions, strict types/build, 38 native ordinary cases with witness parity, 36 native readback regression cases and 16 seals passed. [Evidence](../evaluation/reports/V5/V5-04F1.md).
    - [x] V5-04F2: Authenticated dispatch and public stage/publish manager operations, including fixed native workers.
      - [x] V5-04F2a1: Private manager authority snapshot, original-fence admission and dispatch outcome lookup; 2,157 Python/tool and 1,117 Node regressions, strict types/build, 58 native SQL checks with ordered case parity and 16 seals passed. [Evidence](../evaluation/reports/V5/V5-04F2a1.md).
      - [x] V5-04F2a2: Native attempt transport and public in-process stage/publish manager; accepted within the in-process native profile. F2b supplies the separately accepted worker profile; repair remains G.
        - [x] V5-04F2a2i: Private native dependency and registered-profile bindings; 2,173 Python/tool and 1,123 Node regressions, strict types/build, 68 native controller/recovery checks and 16 seals passed. [Evidence](../evaluation/reports/V5/V5-04F2a2i.md).
        - [x] V5-04F2a2ii: Bounded native transport and public stage/publish operations; 2,207 Python/tool and 1,136 Node regressions, strict types/build, 28 actual public-manager cases with nineteen-result parity and 16 seals passed. [Evidence](../evaluation/reports/V5/V5-04F2a2ii.md).
      - [x] V5-04F2b: Native ordinary-worker channel for a surviving supervisor; 2,245 Python/tool and 1,160 Node regressions, strict types/build, 18 actual process checks with result parity, 44 native manager/source regressions and 16 seals passed. [Evidence](../evaluation/reports/V5/V5-04F2b.md). Installed artifacts and full H remain separate.
    - [x] V5-04F3: Native staged-publication source acceptance and previous-generation preservation; 16 actual native checks, exact source-observation parity, 167 affected Python/tool and 73 Node regressions, TypeScript build and 16 seals passed. [Evidence](../evaluation/reports/V5/V5-04F3.md). Full process/fault acceptance remains H.
  - [ ] V5-04G: Repair, current security convergence, tombstones and scoped purge.
    - [x] V5-04G0: Additive append-only current-epoch preparation attestations and exact authority compatibility, before cross-epoch prepared repair.
    - [x] V5-04G1a: Public native repair for prepared and verified complete uncertain stages; 18 native cases, full local suites and 46 manager/worker regressions passed. [Evidence](../evaluation/reports/V5/V5-04G1a.md).
    - [x] V5-04G1b: Journaled recovery dispatch for genuinely partial replicas; exact old-write fencing and same-intent completion. [Evidence](../evaluation/reports/V5/V5-04G1b-B2b-B3.md).
      - [x] V5-04G1b-B0: Exact supervisor SQL permission proof; 24 focused and12 actual PostgreSQL checks passed. [Evidence](../evaluation/reports/V5/V5-04G1b-B0.md).
      - [x] V5-04G1b-B1: Actual session-owned recovery attempts and draining transports; full local suites,10nativecases and68controller/recoveryregressions passed. [Evidence](../evaluation/reports/V5/V5-04G1b-B1.md).
      - [x] V5-04G1b-B2: Opaque writer plans and proof-bound supervisor recovery dispatch.
        - [x] B2a1: Bounded missing-only inspection and fixed shared verification byte budget.
        - [x] B2a2: Wire one verification budget through manager/F1/E2 readback phases. [Evidence](../evaluation/reports/V5/V5-04G1b-B2a.md).
        - [x] B2b: Actual-proof-bound writer plans and supervisor journal/ACK transitions.
      - [x] V5-04G1b-B3: Native partial repair integration and failure acceptance; 16 native cases and full local suites passed. [Evidence](../evaluation/reports/V5/V5-04G1b-B2b-B3.md).
    - [x] V5-04G2: Current ACL/filter replica convergence and authority-first public security changes; [public/native acceptance](../evaluation/reports/V5/V5-04G2c.md).
      - [x] G2a1: Exact read-only lost-COMMIT confirmation parity for authority-only security writes. [Evidence](../evaluation/reports/V5/V5-04G2a1.md).
      - [x] G2a2: Public authority-only update_authorization/tombstone admission with explicit replica-pending outcomes. [Evidence](../evaluation/reports/V5/V5-04G2a2.md).
      - [x] G2b: Bounded current-security projection, actual old-write reconciliation and ownership handoff; children below passed.
        - [x] G2b1: Read-only current-security claim projection, raw inventory bounds, immutable graph/RLS and staging-lock proof. [Evidence](../evaluation/reports/V5/V5-04G2b1.md).
        - [x] G2b2: Multi-generation/full-document readback and actual security-bound old-owner settlement/handoff; children below passed.
          - [x] G2b2a: Actual restricted-supervisor denied-owner recovery reservation and cross-generation membership permission proof. [Evidence](../evaluation/reports/V5/V5-04G2b2a.md).
          - [x] G2b2b: Bounded full-document security inspection and exact-current readback primitives, including native corruption/drift checks. [Evidence](../evaluation/reports/V5/V5-04G2b2b.md).
          - [x] G2b2c1: Authentic active recovery-session binding and conservative activity tracking. [Evidence](../evaluation/reports/V5/V5-04G2b2c1.md).
          - [x] G2b2c2: Private same-session security receipt bound to fresh current projection and physical proof. [Evidence](../evaluation/reports/V5/V5-04G2b2c2.md).
          - [x] G2b2d0: Native separate-connection guard counterexample and retained-lock control. [Evidence](../evaluation/reports/V5/V5-04G2b2d0.md).
          - [x] G2b2d1: Same-transaction restricted SQL guard, operator/rollback and atomic-lock acceptance. [Evidence](../evaluation/reports/V5/V5-04G2b2d1.md).
          - [x] G2b2d2: Exact native profile-4 source/writer/recovery admission and guard-owner permission drift checks. [Final admission evidence](../evaluation/reports/V5/V5-04G2b2d2b2.md).
          - [x] G2b2d3: Private transaction-owned guard and full nonlocking current-security graph validation. [Evidence](../evaluation/reports/V5/V5-04G2b2d3.md).
          - [x] G2b2d4: Private retired security settlement and exact historical read-only lost-COMMIT confirmation. [Evidence](../evaluation/reports/V5/V5-04G2b2d4.md).
          - [x] G2b2d5: Current-security recovery plans, journaled full-point dispatch and genuine acknowledgment/receipt handoff; D5a-D5c passed.
            - [x] D5a: Private current-security plans and stale/missing full-point dispatch with genuine acknowledgment and retired-settlement acceptance. [Evidence](../evaluation/reports/V5/V5-04G2b2d5a.md).
            - [x] D5b: Initial security-owner handoff and genuine ordinary current-security completion. [Evidence](../evaluation/reports/V5/V5-04G2b2d5b.md).
            - [x] D5c: Repeated-update recovery anchored to a previous/current security owner and ownerless bootstrap; [evidence](../evaluation/reports/V5/V5-04G2b2d5c.md).
      - [x] G2c: Journaled full-point replica convergence and actual native failure/source acceptance; [evidence](../evaluation/reports/V5/V5-04G2c.md).
    - [x] V5-04G3: Tombstone-bound scoped purge, late-write safety, cleanup and native acceptance. COMPLETE for the supported native single-node profile; [evidence](../evaluation/reports/V5/V5-04G3.md) records both runtimes, fault refusals and limits.
  - [ ] V5-04H: Complete actual native QW fault matrix and final publication/repair acceptance.

- [ ] V5-05: [Existing-index contract example](versions/V5-integrations.md#v5-05-existing-index-contract-example) — evidence: pending.

- [ ] V5-06: [Optional MCP host](versions/V5-integrations.md#v5-06-optional-mcp-host) — evidence: pending.

- [ ] V5-C2: Demonstration, relevant regression checks, learning review and resource note through V5-06.

- [ ] V5-07: [Backend and transport parity](versions/V5-integrations.md#v5-07-backend-and-transport-parity) — evidence: pending.

- [ ] V5-08: [Beta installation and operations guide](versions/V5-integrations.md#v5-08-beta-installation-and-operations-guide) — evidence: pending.

- [ ] V5-C3: Demonstration, relevant regression checks, learning review and resource note through V5-08.

- [ ] V5-EXIT: Version acceptance complete; evidence and limitations recorded.

## V6: Release, validation and maintenance

[Version plan](versions/V6-release.md)

- [ ] V6-01: [Freeze release scope and thresholds](versions/V6-release.md#v6-01-freeze-release-scope-and-thresholds) — evidence: pending.

- [ ] V6-02: [Held-out retrieval evaluation](versions/V6-release.md#v6-02-held-out-retrieval-evaluation) — evidence: pending.

- [ ] V6-03: [Concurrency and resource testing](versions/V6-release.md#v6-03-concurrency-and-resource-testing) — evidence: pending.

- [ ] V6-C1: Demonstration, relevant regression checks, learning review and resource note through V6-03.

- [ ] V6-04: [Security and failure audit](versions/V6-release.md#v6-04-security-and-failure-audit) — evidence: pending.

- [ ] V6-05: [Developer usability trial](versions/V6-release.md#v6-05-developer-usability-trial) — evidence: pending.

- [ ] V6-06: [Release artifacts and CI](versions/V6-release.md#v6-06-release-artifacts-and-ci) — evidence: pending.

- [ ] V6-C2: Demonstration, relevant regression checks, learning review and resource note through V6-06.

- [ ] V6-07: [Migration and rollback rehearsal](versions/V6-release.md#v6-07-migration-and-rollback-rehearsal) — evidence: pending.

- [ ] V6-08: [Publication and post-release smoke](versions/V6-release.md#v6-08-publication-and-post-release-smoke) — evidence: pending.

- [ ] V6-09: [Maintenance handoff](versions/V6-release.md#v6-09-maintenance-handoff) — evidence: pending.

- [ ] V6-C3: Demonstration, relevant regression checks, learning review and resource note through V6-09.

- [ ] V6-EXIT: Version acceptance complete; evidence and limitations recorded.

## Session handoff

### V5-04G0: Current-epoch preparation attestations

State: COMPLETE for G0; full G and V5 remain incomplete. Initial assignment followed F completed/pushed as cc36b2eeaa4559078bdb7016ab7ea79285392afd, synchronized 0/0. Root froze G0-r1: additive0003, immutable old preparation, exact live owner/epoch attestation selection, native receipt/finalization provenance and explicit three-profile source compatibility. Schema pair first: Sol f3_python owns new0003 migration plus optional migration test and assembles; Sol f3_node owns new tools/qdrant_attestation_schema.py plus its focused test. Both implement substantive disjoint artifacts and coordinate SQL interfaces directly. Root owns QW, catalog capture, parent checker, later runtime ownership, docs/tracker, all serial execution and Git. Existing migrations/runtime/locks/seals/user audits protected. No peer tests/process/services/network/DB/install/Git. Schema checks max2clients/default5slots, synthetic metadata only; no Qdrant/model/provider for SQL probes. Schema-only success cannot complete G0; native F1 provenance, cross-epoch same-intent publication, compatibility/permission drift and interrupted/lost-ACK acceptance still required. Unresolved material reasoning goes to Astra after peer/root review; no expansion beyond G0.

G0 schema gate: root accepted27focused/18actualSQLchecks afterfixingstaticregex/SQLfixture spelling, flushingdeferredFKevents aroundadministrativefaultALTERs andpreservingprobe primary/cleanuperrors. Frozen0003checksum8c6791cd0fd65ff09758c068ebc90a895a4ac21d9713512486d3daf9cb7c8433; capturedexactcatalog7ffd3b585b1fe32bc3476a3dc4390b022f5dcfd6c5ed186c9964fec4ffd72848 in contracts/fixtures/qdrant_attestation_catalog.json. Preparedsource/generation/oldprep preserved; exacttuple/permissions/fence/malformedgraph/rollback andfreshRR/SERIALIZABLEdenialpassed. SQLonly, notphysicalproof. RuntimeassignmentG0-r1: mainSolPython f3_python owns authority/writer/recovery+authority/writertests(fivepaths), mainSolNode f3_node correspondingfive; Pythonassembles. BindingSol f3_review owns Pythonworker/F1 sources+worker/F1tests(fourpaths), rootcorrespondingNodefour. Rootalsoownsallshared/native/Git. Privateattestation_receipt_data requiresactualoriginalF1receipt andactive realfinalization; mainpairaddsstrict1/2/3readcompat,2ordinary/3attestwriter/recovery, newmetadata/attestmethods andeffectivepreparedpublishpreflight. Alllanesnonoverlap/noexecution; schema/migrations/corpus/audits/locks protected. FullG0 stillIN_PROGRESS pendingruntime/nativeacceptance.

Resume: previous runtime writers stopped and transferred ownership to root. Native acceptance pair assigned: Sol `/root/g0_python_native` owns new `tools/qdrant_attestation_cases.py` and `tools/check_qdrant_attestation.py`, shared inputs/checks and assembly; Sol `/root/g0_node_native` owns new `tools/check_typescript_qdrant_attestation.mjs`. Both deliver actual G0 same-intent cross-epoch acceptance, coordinate interfaces directly and escalate protected/outcome changes. Root owns existing files, optional fixture upgrade, all serial checks, final integration and Git. No worker services/tests/network/DB/Git; frozen G0-r1 and protected migrations/audits apply. Last Python check:313 passed/3 fixture failures; mypy46 passed. Required native acceptance remains pending.

G1 planning pair (implementation waits for G0 acceptance and root contract freeze): Sol g0_python_native owns `artifacts/V5/V5-04G1/REPAIR-DESIGN.md` and assembly; Sol g0_node_native owns `artifacts/V5/V5-04G1/REPAIR-TEST-PLAN.md`. Shared outcome is a bounded public repair algorithm using actual E2/G0, original fences and authorized target scopes. Root owns contracts/product/tracker/execution/Git. Peers coordinate directly; no product edits, tests, services or network.

G0 final acceptance COMPLETE. Root integrated the stopped native pair and static reviewer, corrected two regression fixture assumptions and Python terminal-state ordering, then passed 2,318 Python/tool tests (four existing warnings), 1,181 Node tests/build, mypy46, 27 schema-focused/18 actual PostgreSQL schema checks, 20 actual native attestation cases, nine real role-drift probes per disposable server for both predicates, 16 source cases on each old/new publication schema and 18 worker regressions. See [G0 report](../evaluation/reports/V5/V5-04G0.md). Original preparation and prior active pointer survive recovery/interruption; actual lost COMMIT acknowledgment confirms the same attestation key; same prepared intent/generation publishes only after fresh verification. No full repair, ACL convergence, purge or H claim. All task-owned processes/listeners stopped; failed private storage removed after absence check. Protected migrations/audits and16seals unchanged; locks/core dependencies unchanged. Resource37GiB disk/57percent free memory; observations only. No providers/models/hosted mutation/install/release. Learning exercise unassessed. Root owns final prose/link/staged review, commit and immediate push; next G1a public prepared/already-complete repair, then genuine partial recovery dispatch and remaining G/H/V5 gates.

G0 committed/pushed as e5630638653ee2437a5ac06ff5e79494d47eab6d; origin/main verified identical, 0/0. G1a assignment: Sol g0_python_native owns `packages/python/src/cragkit/qdrant_publication.py`, `_qdrant_writer.py`, tests `test_qdrant_publication.py`, `test_qdrant_writer.py` and assembles. Sol g0_node_native owns corresponding `qdrant-publication.ts`, `qdrant-writer.ts`, `qdrant-publication.test.mjs`, `qdrant-writer.test.mjs`. Shared outcome: bounded public native repair per frozen G1a QW, original identity/fences, exact E2/G0 provenance and one ledger attempt; no partial repair completion claim. Root owns contracts/shared fixtures/native tools/docs/tracker/tests execution/Git; migrations/F1/controller/recovery/locks/seals/audits protected. Both peers implement substantive separate runtime/test paths and resolve interfaces directly. No worker tests/services/network/DB/Git. Escalate protected/outcome changes before dependent edits; unresolved material choices go to Astra through root. State running; full G/V5 incomplete.

G1a final handoff: COMPLETE for prepared/already-complete uncertain stage repair. Python and Node Sol peers implemented disjoint writer/public-manager/test paths; Python assembled and then performed an independent read-only source review. A separate Sol wrote the native Node consumer; root owns shared inputs, Python/parent tools and all execution. Root passed 2,336 Python/tool tests with four existing warnings, 1,195 Node tests/build, mypy46, three protocol guards, 18 actual native repair cases plus nine role probes per server using both predicates, 28 manager and 18 worker native regressions, and16seals. See [G1a report](../evaluation/reports/V5/V5-04G1a.md). Native interruption points differ by runtime; no exact full fault parity or genuine partial repair success claim. Original owner/intent/generation/preparation/fences survive; unknown complete writes settle before bounded ordinary replay; foreign uncertainty keeps reopening blocked. Full G/V5 remains incomplete. No protected migration/F1/controller/recovery/lock/seal/audit edits, provider calls, installs, hosted writes or releases. Post-run process inventory empty; task fixtures cleaned. Resource36GiB disk/52percent free memory; learning unassessed. Root owns prose/link/staged review and commit/push. Next G1b: actual partial recovery dispatcher; design proposes writer-issued opaque plans, existing supervisor-role recovery journal permissions and a narrow actual-session transport facade, with source/dispatch validation in sequential short leases and atomic final publication fences. This design is unimplemented and requires the next bounded freeze/SQL proof.

G1a committed/pushed as 0208fd0f9fc130788615508b11fa0331ac2b2827; synchronization verified 0/0 (remote ID check pending tool completion). G1b-B0 assigned SQL permission proof before dispatcher code: Sol g0_node_native owns new `tools/qdrant_recovery_dispatch_sql.py` and `tools/check_qdrant_recovery_dispatch_sql.py` and assembles; Sol g0_python_native owns new `tools/tests/test_qdrant_recovery_dispatch_sql.py`. Shared outcome: rollback-only actual PostgreSQL supervisor recovery reservation/marker permissions, writer denial and supervisor source/request-body SELECT denial, unchanged schema/grants. Root owns all existing/shared/product files, all runs and final integration. Fixed interface `run_probes(connection, state)` uses the existing synthetic `AttestationProbeState`; metadata SQL probes are not physical recovery proof. Peers coordinate finite checks and tests directly; no worker process/tests/network/DB/Git. Exact old migrations, role maps, sealed inputs/audits protected. G1b runtime/provenance/session extension remains unimplemented and awaits this evidence plus its contract freeze.

G1b-B1 independent controller lane assigned after root froze QW session-owned recovery transport. Sol g0_review owns only Python `_qdrant_supervisor.py` and `test_qdrant_supervisor.py`; SQL pair stopped and transferred all three B0 files. Sol g0_node_native now owns only TypeScript `qdrant-supervisor.ts` and `qdrant-supervisor.test.mjs`; Python controller peer assembles their shared B1 outcome. Outcome: actual control-facade-issued recovery attempts/transports with current proof and per-facade provenance, eight live handles, request drain and owned-handle cleanup before session release. Existing raw APIs and proof/gate semantics preserved. Root owns shared contracts, all native/execution/tracker/Git. No worker tests/process/network/DB/Git. SQL B0 and controller B1 are independent prerequisites; neither completes G1b partial repair.

G1b-B0 final handoff COMPLETE: root inspected the stopped SQL/protocol pair and passed24focused/12actualPostgreSQL checks. [Report](../evaluation/reports/V5/V5-04G1b-B0.md). Exact supervisor recovery insert/markers and writer denial succeeded without grant/schema changes; supervisor request/source/replay SELECT remained denied. Synthetic SQL completion metadata is not a physical proof or actual HTTP acknowledgment. Full rollback inventory/catalog and owned fixture stop/data removal passed. No model/provider/install/hosted mutation/release. Root owns final prose/link/scoped commit/push. B1 controller sources are separately owned ongoing work and excluded from B0 staging; full G1b/G/V5 remains incomplete. Last resource observation36GiB disk/52percent free memory; B0 used one connection and lightweight fixtures. Learning unassessed. Next finish B1, then freeze B2 opaque plans/journal mechanics.

B0 committed/pushed as ec6f14c828dbdedea7a44a90603941860eef44c7; remote/main matched with0/0. B1 final handoff COMPLETE: two Sol peers implemented separate native controller/test files, and a third Sol wrote the Node native consumer. All stopped/transferred; root inspected source and the targeted review, passed39Python/27Nodefocused, 2,370Python/tool and1,204Nodefull tests (four existing Python warnings), strict build/mypy46, two closed-diagnostic protocol tests,10actualnative session cases,18raw supervisor and50durable recovery native regressions, plus16seals. [Report](../evaluation/reports/V5/V5-04G1b-B1.md). Actual write/readback/provenance/slot/expiry/borrowed cleanup passed; wire-stall cancellation has unit timing coverage only. No SQL dispatch/partial-repair/publication claim. Task processes/listeners stopped and private fixture storage removed; post-run inventory empty. Protected migrations/audits/locks/seals unchanged; no provider/model/install/hosted write/release. Resource36GiB disk/46percent free memory; observations only. Root owns prose/link/scoped commit/push. Next B2 must distinguish a missing-only replica from corrupt/unexpected members before recovery replay, then bind writer plans and genuine ACKs to supervisor journals. Full G1b/G/H/V5 remains incomplete; learning exercise unassessed.

B1 committed/pushed as 912426a; remote synchronization check running. B2a1 assignment after root source review found separate readback passes reset their byte counters: Sol g0_review owns Python `_qdrant_reconciliation.py` and `test_qdrant_reconciliation.py` and assembles; Sol g0_node_native owns matching Node `qdrant-reconciliation.ts` and `qdrant-reconciliation.test.mjs`. Shared outcome per frozen QW B2a: missing-only inspection rejects corruption/extras and returns diagnostic missing IDs without receipt authority; fixed shared VerificationBudget is monotonic across passes and existing strict behavior stays unchanged. Root owns contracts/shared fixtures/native tools, B2a2 wiring, all execution/tracker/Git. No worker execution/tests/services/network/DB/Git. Protected migrations/controller/F1/writer/recovery/manager/locks/seals/audits readonly in this lane. Counter reset remains an OPEN resource-bound finding until B2a2 wires the manager phases; no completion claim from helper alone. Escalate protected/outcome changes before edits; unresolved material reasoning goes to Astra through root.

B2a2 F1 lane assignment: Sol g0_python_native owns only Python `_qdrant_publication_verification.py`, `test_qdrant_publication_verification.py`, and matching Node `qdrant-publication-verification.ts` / `.test.mjs`. Outcome is optional native shared-budget admission and forwarding in F1, preserving all receipt/finalization authority and exact HTTP options. Coordinate budget normalization/API with B2a1 peers directly. Root owns manager source/tests and will pass one object through E2/F1/shared publish bodies, inspect combined behavior and run all checks serially. No worker execution/network/services/DB/Git. Full manager resource finding stays open until combined validation.

B1 synchronization confirmed: 912426ad322fbaed74186b2b30dbdd837aea8847 matched remote/main,0/0. B2a1/B2a2 final handoff COMPLETE: root integrated the stopped reconciliation pair, F1 lane and native Node consumer, and wired one budget through managers. Shared-counter reset finding is CLOSED by code plus cross-phase identity/exhaustion tests. Full suites passed2,391Python/tool (four existing warnings) and1,216Node, strict build/mypy46, focused integrity/byte-budget and two native-parent protocol guards,10actual missing-inspection cases,18managed-repair and38F1 native regressions, plus16seals. [Report](../evaluation/reports/V5/V5-04G1b-B2a.md). Native faults are real backend mutations and observed response bytes; wire exhaustion/cancellation timing remain unit evidence, not native fault results. Missing IDs mint no receipt/settlement authority. All task-owned listeners/processes stopped and private fixture data removed; post-run inventory empty. Protected migrations/audits/locks/seals unchanged; no provider/model/install/hosted mutation/release. Resource37GiB disk/47percent free memory; learning unassessed. Root owns final prose/link/staged review and commit/push. Next B2b must use this inspector before replay and bind actual native proof/ACK provenance to supervisor journal transitions. Full G1b/G/H/V5 incomplete.

B2a committed/pushed as4bd7670; synchronization verification pending. B2b implementation pair assigned under frozen QW: Sol g0_review owns Python `_qdrant_writer.py`, `_qdrant_recovery.py` and existing writer/recovery tests (four paths), and assembles; Sol g0_node_native owns matching Node writer/recovery sources and tests. Shared outcome: native proof/session-bound immutable writer plans, missing-only inspection, existing supervisor-role recovery journals and exact genuine-ACK transitions. Root owns contracts/shared fixtures/native tools, later public-manager B3 integration, all execution/tracker/Git. No peer tests/process/services/network/DB/Git. Migrations, role maps, controller/F1/reconciliation/codecs/locks/seals/audits protected. Extract request construction within owned writer source only, preserving ordinary behavior. Peers agree exact authorization/plan shapes directly and stop on transfers. Report outcome/protected/ownership changes before edits; unresolved material reasoning goes to Astra through root. B2b remains IMPLEMENTED_UNVALIDATED if native acceptance has not run; no full G1b/G/H/V5 completion claim.

B2b pair stopped and transferred eight source/test paths to root. Initial validation:206focusedPython passed; Node build passed, Python mypy found one Any-return annotation now corrected; root aligned expired/wrong-deadline authorization errors to InvalidRequest without changing retired physical proof errors. Root starts B3 manager source/test integration on its own four paths: on failed strict E2 integrity, invoke missing-only recovery dispatch under the exact target callback, then require fresh complete E2 receipt/retired settlement before reopen. Corruption remains an error through the inspector; no generic integrity-failure upsert. Root owns shared nine-member native fixtures and Python/parent consumer; Sol g0_python_native will own only a new Node partial-repair consumer. Native acceptance and full regressions remain pending; B2b/B3 not complete.

### V5-04F2b: Native ordinary publisher worker

State: COMPLETE for ordinary-worker-r1 after F3 accepted/pushed as e62374fa6947d17d9da05f149eb10f05d424801c (0/0 synchronized). [Evidence](../evaluation/reports/V5/V5-04F2b.md). Sol f3_python implemented Python worker/public-manager/F1 sources plus worker/manager tests and assembled; Sol f3_node implemented corresponding five Node paths. They agreed wire/API directly and transferred all ownership. Sol f3_review implemented the Node native consumer and reviewed final safety/evidence boundaries. Root owns shared contracts/exports, Python/native parent tools, all serial execution, docs/tracker and Git. Root hardened ownership, channel cleanup/redaction and terminal-result validation, then accepted 2,245 Python/tool and 1,160 Node tests, mypy 46/build, 18 actual worker cases with exact result parity, 28 native manager and 16 source regressions plus 16 seals. Actual SIGKILL/SIGSTOP, fixed child channel EOF and resumed old key HTTP 401 passed; no claim actual parent death or full H or G settlement. Existing applied migrations/reader/writer/recovery/controller sources, locks, seals and audits unchanged; a bounded test-only PostgreSQL fixture option preserves default 5 slots and permits 6 for three runtime clients during paused E2 (three superuser slots remain reserved). Otherwise max 2 clients/one process, synthetic data; no providers/models/install/hosted mutation/release. Native fixtures/listeners/children shut down; owned failed storage removed after absence checks. Resource 44 GiB disk/60 percent free memory; learning unassessed. Root commits/pushes, then G0 current-epoch attestations and repair/security/purge, H and remaining V5 tasks. Full V5 remains incomplete.

### V5-04F3: Public publication and source acceptance

State: COMPLETE for in-process source-facing acceptance after verified/pushed F2a2ii (b804d4e). [Evidence](../evaluation/reports/V5/V5-04F3.md). F3-r1 isolated source acceptance while F2b worker ABI remained design-only. Sol Python `f3_python` implemented tools/qdrant_publication_source_cases.py and assembled; Sol Node `f3_node` implemented tools/check_typescript_qdrant_publication_source.mjs; Sol `f3_review` reviewed the evidence boundary. Both writers stopped and transferred ownership. Root owns shared inputs/parent/tests/report/tracker, all execution and Git. Root corrected the final Python callback scope assertion, inspected assembled sources, passed 3 protocol guards, build, 16 actual native checks with identical source-observation hashes, 167 affected Python/tool and 73 Node regressions plus 16 seals. Stage/prepared source denial, current publication admission, retained stale exact evidence and foreign scope refusal passed. No library/migration/lock/seal/user-audit bytes changed. Max 1 writer+supervisor pools, supervisor pool closed before max 1 reader opens; setup admin released; one test process/language at a time. Both native fixtures/listeners shut down and owned private storage removed; no task-owned service remains. Final snapshot 44 GiB disk/62 percent free memory. No hosted/provider calls, model download, install or release. Learning exercise unassessed. Root commits/pushes accepted scope, then F2b native worker isolation/finalization ownership, G0 repair attestations, repair/security/purge, H and remaining V5 gates; full V5 incomplete.

### V5-04F2a2ii: Public ordinary stage/publish manager

State: COMPLETE for public in-process stage/publish; F2b/F3/G/H and full V5 remain incomplete. [Evidence](../evaluation/reports/V5/V5-04F2a2ii.md). Started after F2a2i accepted/pushed as 387102384ec07ed928cb7dde2fdda54cf74f6a0c, synchronized 0/0. Frozen QW native manager dependency profile and F2a2ii-r1 assignment define actual stage/publish, explicit borrowed authority/transport, strict acknowledgment provenance, original-fence CAS, same-epoch prepared resume and supervisor session during final SQL. Sol Python `/root/v5_candidate_contract` owns new public module/test plus writer source/test (four paths) and assembles; Sol Node `/root/v5_candidate_fixtures` owns corresponding four. Root owns package export, shared/native contracts/harnesses, docs/tracker, serial checks and Git. Controller/recovery/F1, migrations/codecs/readers/locks/seals/user audits protected. No worker tests/services/network/database/providers/installs/Git. At most two native database clients and one test process; synthetic vectors only. Cross-epoch attestation remains G0; worker actual process-crash profile F2b/H. Handoff pending.

Final F2a2ii handoff: Sol runtime pair transferred its public modules/tests and writer helper/tests; Python assembled, independent Sol reviewed critical ACK, cancellation and prepared/finalization paths, and delivered the Node native consumer. Root integrated the Python consumer, closed parent protocol, shared synthetic inputs, package export, guide/report and native comparison. Final evidence: 130 focused Python/tool, mypy 45 files, 50 focused Node/build, 2,207 Python/tool (four existing deliberate warnings), 1,136 Node, fourteen actual public-manager cases per runtime and nineteen exact public-result tuples with matching hashes, plus 16 seals. Cancellation suppression was a real source bug and now has a latched-stop regression; a Node SQL-double predicate bug and native Python pool/cleanup setup errors were corrected. Native failed storage was removed only after independent listener absence; successful fixtures removed their owned storage. Source readers, controllers, recovery, F1, codecs, migrations, locks, seals and user audits remain protected. Resource snapshot: 34 GiB disk/54 percent memory free; no task-owned listener, hosted/provider call, install/download, release or persistent service. Practice unassessed. Root commits/pushes and verifies synchronization, then proceeds to the native worker channel/finalization lease, source-facing F3 acceptance, G0 attestation/repair/security/purge, H actual fault matrix and remaining V5 examples/MCP/parity/packaging; no V5 completion claim yet.

### V5-04F2a2i: Native dependency bindings

State: COMPLETE for private dependency metadata; public manager/full V5 remain incomplete. [Evidence](../evaluation/reports/V5/V5-04F2a2i.md). Started after F2a1 accepted/pushed as f07d1121110bf2deccbcf17f7e93be0989cbceaf, synchronized 0/0. Outcome: exact original writer/recovery dependency metadata and supervisor registered-profile binding for the later explicit manager bundle. F2a2i-r1 assignment: Sol Python `/root/v5_candidate_contract` owns writer/recovery source/test (four paths) and assembles; Sol Node `/root/v5_candidate_fixtures` owns corresponding four paths; independent Sol `/root/v5_manifest_security_review` owns both supervisor sources/tests (four paths). Root owns shared contract/tracker/docs, serial checks, native regression and Git. No overlap, worker tests/services/network/database/providers/installs/Git or pool/resource getters. All other product boundaries, migrations, fixtures/codecs, manifests/locks, sealed inputs and user audits protected. Existing E2 physical capabilities remain exact actual supervisor; accessors expose no readiness/proof. Manager authority is an explicit borrowed writer/recovery bundle, with original verifier identity preserved. Handoff pending.

Final F2a2i handoff: runtime and independent controller lanes transferred all twelve owned source/test paths; Python assembly found no remaining mismatch. Root added actual binding assertions to four existing native consumers and passed 182 focused Python, 66 focused Node, mypy 44 files/build, 2,173 Python/tool (four existing warnings), 1,123 Node, 18 controller + 50 durable recovery native checks and 16 seals. Metadata accessors expose no resource/readiness/proof; physical/SQL rules remain unchanged. Changed scope: writer/recovery/controller source/tests, four native consumers, development/report/tracker. No migration, codec, reader, manifest/lock, sealed input or user audit changed. Tests ran serially with at most two database clients and owned fixture cleanup. No hosted/provider call, install/download, release or persistent service. Practice unassessed. Public-manager review found preparation immutability prevents same-intent publication after global epoch advance; two Sol audits and Astra agree on separate G0 append-only attestation evolution, not replacing the intent or weakening epoch checks. Root commits/pushes, verifies synchronization, then freezes F2a2ii public manager/transport with bounded same-epoch prepared resume, followed by F2b/F3/G0/G/H and remaining V5 tasks.

### V5-04F2a1: Manager authority admission

State: COMPLETE for private manager authority admission; F2/public manager/full V5 remain incomplete. [Evidence](../evaluation/reports/V5/V5-04F2a1.md). Started after accepted F1 commit 90b5662f72d344040e67e74c1162cab245044916, pushed and synchronized 0/0. Concrete outcome: private authority snapshots, durable original-fence outcomes before takeover, and exact dispatch metadata for known-acknowledgment SQL reconciliation. No HTTP/public-manager claim in this child. F2a1-r1 assignment is recorded in the ignored assignment artifact. Sol Python `/root/v5_candidate_contract` owns only `_qdrant_writer.py` and its test and assembles; Sol Node `/root/v5_candidate_fixtures` owns only `qdrant-writer.ts` and its test. Both review the shared shape directly before edits. Root owns contracts/fixtures, native harnesses, documentation/tracker, serial tests and Git; other sources, migrations, manifests/locks, evaluation seals and user audits remain protected. No worker tests/services/network/database/provider calls/installs/Git. At most two native database clients, setup admin released and one test process. Root will resolve protected/public-boundary issues before dependent edits; unresolved material decisions go to Astra. Handoff pending.

Final F2a1 handoff: Sol peers transferred their two owned runtime files each; Python assembled without a remaining parity mismatch. Root integrated eight native SQL groups per runtime into the existing D checker, preserving its authority-only proof scope and all original groups. Actual committed acknowledgment loss discarded the native client and reconciled the same private owner. Final checks: 91 focused Python, 35 focused Node, mypy 44 files/build, 2,157 Python/tool (four existing deliberate warnings), 1,117 Node, 58 native groups (14 SQL + 22 per runtime), exact ordered case parity and 16 seals. Runtime regression fixtures corrected a role-SQL match and copying exceptions before BEGIN; source review corrected a post-owner-wait stale intent and aligned confirmed-read reconciliation. Changed scope: both writer sources/tests, three existing native checker/consumer paths, development/report/tracker. No schema, codec, source reader, controller/recovery, lock, sealed input or user audit change. Resource snapshot: 33 GiB disk/54 percent memory free; native fixtures shut down and removed; no model/provider/hosted calls, installs/downloads, release or persistent service. Learning practice unassessed. Root commits/pushes, verifies synchronization, then continues F2a2 transport/authority bundle/public stage/publish, F2b/F3/G/H and V5-05 through V5-EXIT without routine permission prompts.

### V5-04F1: Ordinary publication readback

State: COMPLETE for ordinary readback; public manager/publication and full V5 remain incomplete. [F1 evidence](../evaluation/reports/V5/V5-04F1.md). E2b accepted/committed/pushed as 0c6e4a0d473e0e58179c4f10d152db42a7d9a63e, synchronized 0/0. Concrete outcome: exact current-authority stage projections and full native Qdrant readback under an actual ordinary immutable attempt capability, issuing a private receipt after fresh authority/capability checks. Any unresolved document dispatch remains operationally unavailable. F2/F3 still own production dispatch/public manager publication and acceptance; F/full V5 remain incomplete.

F1-r1 runtime pair delivered and transferred its files to root. Python focused checks passed 136 tests and strict typing of 44 files. Node's first focused run passed 40/41; its cancellation fixture incorrectly counted a destroyed historical database connection as a live lease. Sol `/root/v5_candidate_fixtures` owns only the Node publication-verifier module/test for that correction and bounded-close error handling, then transfers them back. Existing writer files and shared Node readback extraction remain root-owned.

F1 native pair: Sol `/root/v5_candidate_contract` owns new `tools/qdrant_publication_verification_cases.py` and assembles; Sol `/root/v5_manifest_security_review` owns new `tools/qdrant_publication_verification_node.mjs`. Their shared outcome is real ordinary readback receipts and negative current-authority/vector cases using primitive pre-journaled writes, completed acknowledgments and explicit fixture settlement. The envelope is the existing native readback shape; result scope is `ordinary_readback_only`, with physical witness nonces normalized at positions 2, 3 and 5. Root owns the new parent checker, tool tests, documentation/tracker, serial acceptance and Git. Peers agree the case list directly before editing. Migrations, codecs, source readers, supervisor/recovery modules, shared fixtures, manifests/locks, seals and user audits remain protected. Workers run no tests/processes/services/network/database/provider calls/installs/Git. Root uses one test process and at most two native database clients after releasing setup administration. F2's full manager-process crash profile remains a separate owned child; killing an HTTP dispatcher alone will not satisfy it.


F1 final handoff: runtime pair and native pair transferred all owned paths to root. Final local checks: 2,136 Python/tool tests (four existing deliberate warnings), 1,106 Node tests, mypy 44 files, strict build, 38 native ordinary checks with witness parity, 36 E2a native regression checks with parity and 16 seals. Root fixed the cancellation fixture and an extracted helper forwarding an undefined owner option to strict native HTTP; the final focused and native runs passed. Two failed private fixtures were removed only after independent native listener absence; successful runs removed their own storage after cleanup. Changed scope: both writer sources/tests, both new ordinary-verifier sources/tests, Node shared readback extraction, four native harness/test paths, report/development guidance, E102 and tracker. Protected migrations, codecs, manifests/locks, source readers, supervisor/recovery, seals and three user audit drafts remain unchanged. Resource snapshot: 35 GiB disk, 45 percent memory free; no model/hosted calls, installs/downloads, release or persistent service. Practice unassessed. Root commits/pushes this accepted scope, verifies synchronization, then continues F2a manager admission/transport/stage/publish, F2b explicit native worker channel, F3/G/H and remaining V5 tasks. Astra's bounded worker-boundary advice requires fresh asynchronous parent validation and keeps all E2 physical capabilities parent-local; it does not change crash acceptance.


### V5-04E2b: Durable recovery settlement and admission

State: COMPLETE within the selected native controller profile; E2 and parent E are complete. V5-04 and full V5 remain incomplete. [E2b evidence](../evaluation/reports/V5/V5-04E2b.md). E2a was accepted/committed/pushed as 791ebb8c090b66a46ad6d980dbfc2a15d2cfd8f6, synchronized 0/0. Continue through V5-EXIT without routine permission prompts.

Shared outcome: exact restricted supervisor SQL control commits the instance block before actual fencing, advances only existing owners, settles retired-credential effects using actual scoped receipts and reopens native admission only through a sealed private committed handoff. Current-generation and foreign-document uncertainty remain blocked. Sol `/root/v5_candidate_contract` owned new Python recovery source/tests and assembled; Sol `/root/v5_candidate_fixtures` owned corresponding Node paths. Sol `/root/v5_manifest_security_review` owned the Node native consumer, transferred it, then reviewed independently authored control/guard code. Peers coordinated API, privilege map and findings directly. Root owned supervisor barriers/session hooks and tests (I1), private verifier-authority helpers/tests (I2), shared contract, remaining native tools/tests, documentation/tracker, serial validation and Git. All paths transferred to root before final checks.

Serial checks exposed no failure, but root and peers then found a cross-coordinator race. Root reproduced a failed native competing-reopen refusal and added E2b-r2: an actual-supervisor exclusive session spans the whole SQL/physical/handoff operation. Its expiring private facade rejects competing/nested/raw/inherited calls, preexisting native lifecycle work and stale authority, and drains started native work before release. Pair/reviewer consensus resolved the fix; no material issue required Astra. This sequencing guard is separate from actual physical proof and private SQL settlement.

Root passed 124 focused Python/tool cases, 35 Node groups, full suites of 2108 Python/tool tests (four existing deliberate warnings) and 1094 Node tests, mypy43files, build and all 16 seals. Final native E2b passed 50 checks: eight SQL permission groups plus 21 real recovery cases per runtime. Actual SQL commit acknowledgment loss was injected after the real commit; read-only reconciliation, a sealed native gate and one open UPDATE were observed. Competing coordinators were paused at the real durable-block/physical boundary; competing/raw calls were refused before SQL, then manager handoff resumed. Existing native E1 and E2a checks passed again (18 and 36). These are not H's 43 process/fault cases or model-quality evidence.

Changed scope: two native recovery modules/tests, root supervisor/barrier/session and verifier-authority source/tests, four native checker/consumer/test paths, QW/development guidance, E101, report and tracker. Migrations, existing writer/codec/reader source, shared fixtures, manifests/locks, seals and all three user audits remain unchanged. At most two clients after setup, one test process and serial services; final resource observation 36 GiB disk/44 percent memory free on M4/16 GiB. Successful runs verified listener absence and removed owned fixture storage; the failed concurrency fixture was separately removed only after independent absence verification. No hosted mutation, provider call, install/download, registry publication or persistent service. Learning practice unassessed. Root commits/pushes this accepted scope and continues V5-04F bounded staged writes, full readback and safe generation publication, then G/H and remaining V5 tasks.

### V5-04E2a: Authority-bound recovery readback

State: COMPLETE for exact recovery readback; parent E2/E/V5-04 and full V5 remain incomplete. [E2a evidence](../evaluation/reports/V5/V5-04E2a.md). E1 was committed/pushed as 9898c4204c067020c012e892770a873aa49ab38e and synchronized 0/0. Continue through V5-EXIT without routine permission prompts.

Shared outcome: exact current-authority stage projections, complete bounded native Qdrant readback and privately issued receipts in both runtimes. Sol `/root/v5_candidate_contract` owned the four Python writer/verifier/test paths and assembled. Sol `/root/v5_candidate_fixtures` owned the corresponding four Node paths. Both coordinated interfaces and taxonomy directly and froze/transferred all paths to root. Sol `/root/v5_manifest_security_review` wrote only the Node native consumer, transferred it, then reviewed the independent implementations read-only. Root owned the shared contract, remaining harness/test paths, E2a-T Node transport allowance/test, docs/report/tracker, serial acceptance and Git. No unresolved material issue required Astra.

Root passed final full suites: 2054 Python/tool tests with four existing deliberate warnings, 1078 Node tests, mypy42files, Node build and 16 seals. Final native E2a passed 18 checks per runtime plus normalized witness parity; D regression passed 42 SQL/native checks. Administrative clients closed before each two-client runtime window. Actual fixture interventions tested wrong membership/vectors/profiles, immediate authority changes and tombstone absence; they did not settle journals, reopen gates or count as production repair. All successful runs independently verified listener absence and removed owned fixture storage. Review corrections covered hidden raw members, row-order dependence, parsed JSON prototypes, cleanup failures, streaming remaining-byte caps and cross-runtime error distinctions.

Changed scope: native writer/reconciliation modules/tests, additive Node response allowance/test, four native harness/consumer/test paths, QW/development guidance, E99-E100, report and tracker. Both migrations, shared fixtures, manifests/locks, all seals and three user audit drafts remain unchanged. Last resource observation: 36 GiB disk/60 percent memory free on M4/16 GiB; one test process and serial services. Learning practice remains unassessed. Root commits/pushes this accepted scope and continues E2b: current-credential uncertainty cannot be cleared by readback alone; only retired effects plus verified durable settlement and a sealed transport handoff can reopen admission. Unavailable foreign document scopes keep instance recovery blocked.

### V5-04E1: Exclusive controller and credential capabilities

State: COMPLETE for the physical controller primitive; parent E and full V5 remain incomplete. [E1 evidence](../evaluation/reports/V5/V5-04E1.md). D was accepted/pushed as bfbf6980376a1699f429b5dccb5c50edd23a18b4, synchronized 0/0. Continue through V5-EXIT without routine confirmation prompts.

Sol v5_candidate_contract wrote Python _qdrant_supervisor.py/test_qdrant_supervisor.py and assembled. Sol v5_candidate_fixtures wrote Node qdrant-supervisor.ts/test and coordinated directly. Sol v5_manifest_security_review wrote only tools/check_typescript_qdrant_supervisor.mjs, then independently reviewed the other peers' controllers. All paths transferred to root before final integration; root added Python consumer/parent/harness tests, fixed review findings and owns tracker/Git. No worker executed code or used services/network/install/Git. No unresolved material issue required Astra.

Final checks: 26 Python controller plus six harness tests, nine Node groups, full 2001 Python/tool tests (four existing deliberate warnings), 1064 Node tests, mypy41files/TypeScript build and 16 unchanged seals. Actual native-verified-01 ran nine Python and nine Node physical checks serially: explicit provisioning/profile/listener ownership, competing-controller refusal, immutable ordinary key delivery, same-storage restart, captured old-key 401, recovery-only admission, copied-proof rejection, current-key full point/vector readback, forbidden recovery-key delivery and repeated same-ID physical fencing. Both controllers closed, listener absence checked independently and fixture storage removed. No SQL settlement, actual manager/supervisor kill, full H matrix, provider/hosted call, download, registry publication or persistent service is claimed.

Native probes first failed the design's incorrect 403 assumption: unchanged real HTTP and pinned authentication/HTTP source proved retired invalid-key 401. QW and implementations now require exactly 401 for this profile; generic 401/403 transport errors remain authorization failures. Earlier Python typing and Node mock cleanup failures were fixed. Independent review corrected invalid-epoch admission poisoning, retained closed handles and known-dead-child guards, with regressions before final acceptance. These were concrete failures/corrections, not passing earlier runs.

Changed scope: four native controller/test paths, four acceptance/consumer/test paths, QW factual status correction, development guidance, E97-E98, report and tracker. Existing migrations, writer/reader source, manifests/locks, all seals and three untracked user audit drafts remain unchanged. Reference profile: macOS arm64/pinned Qdrant, new private directory, no supervisor takeover or adoption, surviving caller-owned controller. Physical proof never implies SQL quiescence and has no ordinary reopen API. Last resource observation: 36 GiB disk/61 percent memory free, one test process and serial services. Learning practice unassessed. Next E2 supplies durable gating, authorized per-document reconciliation and the private verified settlement handoff; unavailable foreign document owners keep the whole instance blocked. Root commits/pushes this accepted scope and continues.

### V5-04D: Native publication writer operations

State: COMPLETE for authoritative writer transactions, with [D evidence](../evaluation/reports/V5/V5-04D.md). Parent V5-04 and full V5 remain incomplete. The user requested uninterrupted completion through V5-EXIT; continue after this accepted child without routine permission prompts.

Sol v5_candidate_contract owned Python _qdrant_writer.py, _qdrant_writer_contract.py and test_qdrant_writer.py and assembled. Sol v5_candidate_fixtures owned Node qdrant-writer.ts, qdrant-writer-contract.ts and qdrant-writer.test.mjs. They coordinated directly and transferred frozen paths to root. Independent Sol v5_manifest_security_review inspected source and native harness paths. Root integrated, resolved concrete parity/fence/role/cleanup findings, added native regressions and owns all D files, tracker and Git. No unresolved material issue required Astra; one transient Sol capacity failure was retried with the same model.

Actual final verification: 70 focused Python/tool cases, 17 Node writer cases, 1969 full Python/tool tests (four existing deliberate serializer warnings), 1055 Node tests, strict mypy40files and TypeScript build; all 16 seals remained valid. Final native-verified-03 passed 42 checks: 14 SQL/role/committed-boundary, 14 native Python and 14 native Node authority checks, including real dedicated LOGINs, an observed gate lock wait/fresh epoch, post-commit dispatch membership freezing, unsafe fixed-capability grants/flags/memberships, complete request/vector/ACL comparison, same-set replay, blocked work, publication/owner interleavings, revocation, historical receipts, stale security denial and purge binding. Administrative setup closes before two runtime clients. All private servers/directories and task clients closed. No Qdrant/provider/hosted call ran. Synthetic completion digests exercise authority SQL only, not actual replica completion or the separate 43-case H matrix.

Changed scope: six native writer/admission/test paths; five native harness/driver/test paths; development/storage guidance, E95-E96, report and tracker. Protected migrations, old/new reader profiles, manifests/locks, 16 sealed inputs and three untracked user audit drafts remain unchanged. Last resource observation: 38 GiB disk, 47 percent system memory free on M4/16 GiB; one test process, native suites serial. Learning practice remains unassessed; historical success versus current active pointer was explained. Root commits this verified scope, immediately pushes and checks synchronization, then continues V5-04E exclusive caller-owned supervisor/credential epochs and the remaining V5 tasks.

### V5-04C2: Explicit source-reader upgrade

State: COMPLETE for native reader compatibility; parent V5-04C is complete. C1 was accepted, committed/pushed as f149276 and synchronized 0/0. Shared outcome: both native source readers accept only the exact source-only or publication history/catalog pair, retain source-only behavior, and reject writer/supervisor or excess operational privileges on every read lease. The new catalog fixture is captured from C1's actual PostgreSQL result; the original fixture/query and both migrations are protected.

- Sol v5_candidate_contract owns only packages/python/src/cragkit/_qdrant_authority.py and packages/python/tests/test_qdrant_authority.py; native Python compatibility and named assembler.
- Sol v5_candidate_fixtures owns only packages/typescript/src/qdrant-authority.ts and packages/typescript/tests/qdrant-authority.test.mjs; complementary native Node compatibility.
- Root owns C2-r1 shared profile/fixture, native harness profile acceptance, all commands, tracker/docs/reports and Git. Two native lanes are bounded to two implementation/test files each (C2a); the separate native harness/profile slice is C2b. Peers coordinate exact constants, profile selection and error semantics directly, with stopped writers before ownership transfers. Scope/ownership/protected changes go to root and unresolved material decisions to Astra. No worker tests/builds/scripts/network/DB/services/install/Git.

Frozen C2-r1: preserve strict old structural/catalog checks, select one explicit profile from exact bounded history (LIMIT 3), then validate its structural check and exact fingerprint; no mixed pairs, prefix acceptance or ignored catalog objects. New profile history is the exact two migration checksums, with fingerprint e395925257def30b9d143b7210c68583d4cbbb0950d8a8e1bb4f5aba5b8be69b. Reader grants require SELECT on only the five original tables, no SELECT on new operational columns, no DML/ownership/admin or writer/supervisor membership. Initial and fresh-lease checks remain separate. Acceptance: both known profiles, crossed/unknown/extra history and drift failures, role rejection, serial actual PostgreSQL/Qdrant source/provider-gate parity and exact cleanup. One suite/process; fake providers and existing small local fixtures only. Learning unassessed; final acceptance is recorded below.

Final handoff: both native Sol peers delivered separate two-file implementations/tests, coordinated directly and froze/transferred their paths. Python peer assembled; independent Sol and root reviewed. Corrections covered Node malformed-history parity and serialization hooks, Python internal FK-trigger checks, outage reconnect and simultaneous probe/revocation failure preservation. No unresolved material issue required Astra. Root passed 66 focused Python/tool tests, 17 Node tests, 1899 full Python/tool tests (four existing deliberate warnings), 1038 Node tests, mypy38files and TypeScript build.

Final source-verified and publication-verified runs each passed 14 actual Python and 14 actual Node source cases: 56 executions across both profiles, exact result/ledger parity, current authorization/provider/final gates, TLS negatives and complete collection/process/private-directory cleanup. Both native SQL permission predicates rejected noninherited capability memberships and column writes; publication also rejected operational column reads and new helper execution. Four actual catalog drifts changed the hash; a disabled internal FK trigger preserved the hash but failed both new structural probes. Administrative source seeding restored its two exact disabled publication constraint triggers and final fingerprints before acceptance; it is not manager publication.

Changed scope: two native authority modules/tests, shared source contract/new captured catalog, four native parent/permission helper/test paths, current storage/development guidance, C1 historical snapshot pointer, C2 report, E93-E94 and tracker. Original source structural/fingerprint/data queries, catalog fixture/query, both migrations, all 16 seals, manifests/locks and three user audits remain unchanged. Root owns final prose/link/scope checks and Git. No hosted mutation, paid call, download, install or persistent service. Latest M4/16 GiB snapshot: 38 GiB disk, 51 percent memory free; one PostgreSQL/Qdrant pair and at most two database clients, all task processes closed. Learning practice unassessed. Next smallest action: V5-04D native authority writer operations; cross-commit/race/controller/Qdrant publication/repair acceptance remains D-H. Full V5 is incomplete.

### V5-04C1: Durable publication authority

State: COMPLETE for additive SQL/local acceptance. Baseline 5ffd4be was synchronized; the three user audit drafts remain untracked and excluded. Shared outcome: an additive PostgreSQL 17 publication schema for QW-r1 intents, global physical claims, document ownership, uncertain dispatches and preparation, with real local constraint, least-privilege and rollback evidence. C1 supplies storage invariants; native writer operations and Qdrant fault acceptance remain D-H. Parent C also requires C2's explicit catalog/history upgrade.

- Sol v5_candidate_contract owns only new storage/qdrant/postgres/migrations/0002_publication.sql and storage/qdrant/postgres/PUBLICATION.md; schema implementation and named assembler.
- Sol v5_candidate_fixtures owns only new tools/qdrant_publication_schema.py and tools/tests/test_qdrant_publication_schema.py; complementary SQL acceptance construction and negative cases.
- Root owns the shared schema decision, tracker, local acceptance runner, catalog/reader compatibility, all commands and Git. Both peers start with a read-only schema/security proposal and coordinate dependencies directly before the schema freezes. No worker tests, scripts, services, installs, network, database or Git actions. Outcome, protected-boundary and ownership changes go to root; unresolved material issues go to Astra after peer/root review.

Protected: migration 0001 and its exact source-only profile, reader authorization, sealed inputs, user drafts, manifests/locks and native runtime boundaries. Root alone runs one test process and one disposable PostgreSQL cluster, at most two clients; no hosted mutation, Qdrant process or model call is needed for C1. Acceptance: immutable/scoped relationships, hidden global collisions, reader/staging isolation, durable uncertainty, least-privilege roles and complete rollback/process cleanup. Learning practice remains unassessed.

C1 is executed in two bounded implementation slices: C1a owns the migration, storage guide, SQL probe builder and probe tests; C1b owns the explicit local runner and its CLI/cleanup tests. Root owns C1b. Frozen C1-SQL-r1 uses separately provisioned safe NOLOGIN writer/supervisor capability roles, role-specific policies, staged visibility through the bound stage intent, same-document predecessor journal visibility, and global metadata-only supervisor privileges. Four additional operation settings bind the trusted target/intent/owner/instance context; settings do not authenticate a database caller. Managed writes require READ COMMITTED and owner/instance locking. C1's rollback-only probe does not establish concurrent writer or remote completion correctness; D-H supply native operations and fault interleavings.

Final handoff: both substantive Sol peers coordinated directly, froze their paths and transferred ownership; the SQL peer assembled. Independent Sol/root source review corrected nullable constraints, privilege/policy construction, historical settlement, initial pointer admission, immutable dispatch membership, owner refresh, member count fences and isolation assumptions. Root's first CLI tests exposed a missing diagnostic argument. Native 01 and diagnostic 02 stopped at an overly strict probe identifier regex, with cluster cleanup; neither is acceptance. After the peer correction and regression, native 03 passed all 17 groups, exact original catalog before upgrade, complete role/schema/default rollback, verified TLS and process/private-directory removal. SQL-only positive recovery and immediate denial passed; no Qdrant proof is inferred.

Root passed 27 focused tests, 1864 Python/tool regressions (four existing deliberate warnings), 1032 Node tests, mypy38files and strict TypeScript build. Source/guide/helper/runner/tests, storage/development guidance, E91-E92, this tracker and C1 report are the changed scope. All 16 seals, original migration and three audit hashes remain unchanged. Prose inspection found zero suspicious characters and low density with unchanged deterministic output. Latest M4/16 GiB snapshot: 38 GiB disk, 52 percent system memory free; one test process/one private PostgreSQL process/one client, all closed. No hosted mutation, provider call, model/SDK install, persistent service or publication. Learning unassessed. Next: C2 must accept only exact old/new history/catalog pairs and reject writer/supervisor reader memberships; D-H still own real LOGIN/commit/race/controller/Qdrant acceptance. Full V5 remains incomplete. Root owns final scoped Git review, immediate push and synchronization.

### V5-04B2: Immutable manifests and original-vector replay

State: COMPLETE for pure native metadata/replay acceptance. Previous goal turn made verified progress: V5-04A/B1 accepted and pushed, latest 83fdde6 synchronized 0/0; three user audit drafts remain preserved. Shared outcome: exact native QW-r1 generation/stage/security/purge seals and bounded original Float64LE replay sidecars that reconstruct B1-issued expected vectors without re-admitting only rounded data.

- Sol v5_candidate_contract owns only new packages/python/src/cragkit/_qdrant_manifest.py and packages/python/tests/test_qdrant_manifest.py; Python implementation/tests and named assembler.
- Sol v5_candidate_fixtures owns only new packages/typescript/src/qdrant-manifest.ts and packages/typescript/tests/qdrant-manifest.test.mjs; complementary native TypeScript implementation/tests.
- Root owns the QW-r1 addendum, shared goldens, reports/tracker/development instructions, actual checks and Git. Existing B1/QC/QS runtime code, migrations, manifests/locks, exports and user drafts are protected. Peers coordinate concrete dependencies directly; ownership transfers require stopped writers, and outcome/protected-boundary changes escalate to root, then Astra if unresolved.
- Sol v5_manifest_security_review owned no writable paths and reviewed the new helpers for source fidelity, native guards, resource bounds, replay and parity. Findings went directly to the relevant owner and root; all commands remained root-owned.

Final handoff: both peers reviewed the frozen helper boundary, wrote substantive tests first and waited for root's actual missing-module failures. They implemented separate paths, coordinated directly, assembled and transferred ownership. Four replay/four operation goldens independently matched Node calculations. Root corrected the test span, ASCII-blank parity, kind-specific pre-copy caps and span error precedence; negative cases cover explicit hash/UUID syntax. A source-only JavaScript-anchor hypothesis was disproved by actual runtime probes and retracted, with protected QC unchanged. Final fresh checks passed 41 focused Python/27 Node cases, strict Python38files/Node build, 1837 Python/tool regressions (four existing deliberate warnings), 1032 Node package tests and all 33 cross-runtime hash/value/error cases. No native datastore/model, install or service ran. All 16 seals, migration 0001 and three user audits remain unchanged. Prose skill found no suspicious carriers and low density with byte-identical cleanup. Resource snapshot: 38 GiB disk, 47 percent system memory free; no task-owned service. Learning practice unassessed. Next: V5-04C additive authority schema, writer privileges and exact catalog/reader upgrade, then D-H native implementation and actual fault acceptance. Full V5 remains incomplete.

### V5-04A: Publication/repair execution contract

State: COMPLETE for design acceptance. Prior goal turn made verified progress: V5-03/C1 accepted and pushed in 5393b92, synchronized 0/0; three untracked user audits remain preserved. Concrete outcome: frozen native writer/authority/coordinator boundaries, immutable vector/manifest representation and bounded real-fault acceptance before dependent writer edits. This is the first required child of full V5-04, not a replacement for implementation or recovery tests.

- Sol v5_candidate_contract owns only new contracts/QDRANT_PUBLICATION_V5.md and docs/decisions/0004-qdrant-managed-writes.md; contract/protocol and named assembler.
- Sol v5_candidate_fixtures owns only new contracts/fixtures/qdrant_publication.json and docs/qdrant-publication-acceptance.md; complementary fault scenarios and native acceptance mapping.
- Root owns shared decisions/plan/tracker/edge updates, primary-source verification, all commands, integration and Git. Existing QS/QC/QD contracts, runtime source, migrations, manifests/locks and user audits remain protected. Peers coordinate concrete dependencies directly and revise only their assigned split by agreement. Outcome/protected-boundary/ownership changes to root; unresolved material choices to Astra after peer/coordinator review.

Accepted reference uses the existing single-node Qdrant 1.20.0 target and optional PostgreSQL authority, durable global physical claims, per-document CAS ownership and dispatch records written before side effects. Unresolved dispatches block successors even after lease expiry. Normal completion requires wait=true completed and complete readback. The borrowed exclusive supervisor survives worker crashes, closes instance-wide admission and proves stop/rotate/restart/reconciliation with old credentials rejected. Supervisor loss has no automatic takeover. Explicit prevent_unoptimized=false and exact readback are required; health alone does not prove full replay. Exact Float32LE input seals are separate from bounded normalized dense readback equivalence; sparse readback is exact. Migration 0001/source-only catalog remain unchanged; the upgrade requires a separate exact history/catalog profile.

Final handoff: both substantive Sol peers coordinated directly; the contract peer assembled and both transferred ownership before root corrections. Root escalated two material controller/numeric decisions to Astra, checked pinned primary source and preserved existing write-authorization and model-ledger semantics. All 43 fault cases map to the native matrix and cover 21 QD rows. Four vector seals and two ordered manifest/intent hashes independently matched Python and Node; exact source/span/UUID/tie expectations, relative links, 16 sealed inputs and three user audit hashes passed. Prose skill found no suspicious carriers and low density; deterministic output unchanged. No product test suite, native datastore process/mutation, model, install or service ran for this design-only child. Resource snapshot: 39 GiB disk, 64 percent system memory free. Learning practice unassessed. Next: V5-04B1 pure native codec, followed by B2-H implementation and native faults; full V5 remains active.

### V5-04B1: Native vector identity and readback validation

State: COMPLETE for pure native codec acceptance. V5-04A was committed/pushed in 0cacb48 and synchronized 0/0 before this implementation. Concrete shared outcome: implement QW-r1's pure exact Float32LE input encoders, full-profile seals and bounded dense/exact sparse readback checks in native Python and TypeScript. No public ingestion export or publication capability is introduced.

- Sol v5_candidate_contract owns only new packages/python/src/cragkit/_qdrant_vectors.py and packages/python/tests/test_qdrant_vectors.py; Python implementation/tests and named assembler.
- Sol v5_candidate_fixtures owns only new packages/typescript/src/qdrant-vectors.ts and packages/typescript/tests/qdrant-vectors.test.mjs; complementary TypeScript implementation/tests.
- Root owns frozen shared QW-r1/fixture revisions, reports/tracker, all commands and Git. Existing runtime files, migrations, manifests/locks, core exports and user drafts remain protected. Peers resolve routine dependencies directly and transfer any file before another writer edits; outcome/protected boundary/ownership changes go to root and unresolved material decisions to Astra.

Final handoff: both peers wrote substantive tests first; root observed the expected missing-module failures before authorizing implementation. Peers coordinated directly; the Python peer assembled, both froze their files and root reviewed/integrated. Sparse negative-zero index canonicalization, operational error classification and Node readability findings were corrected with regressions. Root passed 71 focused Python/25 Node cases, strict Python37files and Node build, 1796 Python/tool regressions (four existing deliberate Pydantic warnings), 1005 Node package tests and 21 serial native codec hash/outcome comparisons including four spread 1536-component vectors. All 14 shared numeric cases and four vector goldens pass in both runtimes. No native datastore/model/provider, install or service ran. All 16 sealed inputs, migration 0001 and three user audits remain unchanged. Prose skill found no suspicious carriers and low density, with unchanged deterministic output. Resource snapshot: 39 GiB disk, 66 percent system memory free; no task-owned service. Learning practice unassessed. Next: B2 must preserve original admitted numeric inputs plus canonical seals for portable replay; re-admitting only rounded values can reject a valid boundary input. Then C-H authority, supervision, publication, repair and actual fault acceptance remain required. Full V5 stays active.

### V5-03D: Real local PostgreSQL/Qdrant disclosure acceptance

State: COMPLETE for local native source/disclosure acceptance and checkpoint V5-C1. Dependency V5-03B/C accepted, committed/pushed in 0267ed0; remote hash matches and ahead/behind 0/0. Concrete outcome: real PostgreSQL 17.11 TLS/SCRAM restricted LOGIN and Qdrant candidate/source/provider-spy/final-release parity on isolated task-owned processes, with exact shutdown and no hosted fixture writes. Frozen internal protocol QS-native-r1 and 14 scenarios in contracts/fixtures/qdrant_source_native.json; synthetic providers only.

- Sol v5_candidate_contract owns only new tools/qdrant_source_native.py and tools/tests/test_qdrant_source_native.py: bounded private local PostgreSQL process/TLS/auth fixture. Named assembler.
- Sol v5_candidate_fixtures owns only new tools/check_typescript_qdrant_source.mjs: native Node case consumer with whitelisted parent mutation RPC. It receives only restricted reader configuration and read-only Qdrant credentials.
- Root owns shared fixture/protocol, Python cases, administrator orchestration, Qdrant seed replacement, actual serial checks, reports/tracker and Git. Existing product runtime, migrations, locks and user audits protected; changes require explicit reassignment. Peers resolve concrete fixture/protocol dependencies directly; outcome/boundary/ownership disputes to root, unresolved material decisions to Astra.

V5-03D-F1 added after native diagnosis: root verified Node 26.5 rejects an IP TLS servername with TypeError/ERR_INVALID_ARG_VALUE using an unconnected socket. Pinned pg already supplies the connection host for certificate verification and normally omits IP SNI. Root explicitly authorizes the Node peer to edit only packages/typescript/src/postgres-pool.ts and new postgres-pool.test.mjs for conditional DNS-only SNI, preserving CA trust and rejectUnauthorized=true. The same settings apply to the owned native preflight. This bounded runtime fix is required before D acceptance; all other pool behavior remains protected.

Workers write their assigned files only, no checks/processes/network/installs/Git. Root uses one integration process, at most two PostgreSQL connections, a five-connection/16 MiB shared-buffer local cluster and the existing one-worker Qdrant fixture. No model install or live provider call. Root runs focused lifecycle tests before starting services, then Python and Node serially, checks full outputs and closes both owned processes/private directories. Learning: an isolated reference fixture proves native behavior without mutating a shared hosted database. Next action: V5-04A publication/repair execution contract and bounded child-task split.

V5-03D/C1 final handoff: Sol fixture/Node lanes delivered separate owned tools; fixture peer assembled, independent Sol reviewed scope/cleanup and strengthened current-revision tombstone denial. Root integrated Python cases, parent-only administrator mutations, exact Qdrant seed inventory and whitelisted bounded child framing. Native Node startup failure was escalated to Astra read-only review; root isolated the IP-SNI TypeError with an unconnected socket and authorized D-F1. The pool and preflight now omit IP SNI while retaining trusted CA and rejectUnauthorized=true. Five option regressions and actual wrong-hostname/untrusted-private-CA probes passed.

Final native command passed 14 cases per runtime with full public source-result/candidate-ledger parity, actual source-server shutdown, real restricted LOGIN/TLS and both negative TLS probes. PostgreSQL 17.11 and Qdrant 1.20.0 were isolated local owned processes; both stopped and private data removed before success artifact. Native catalog8104 mismatch from stock PUBLIC domain usage was resolved by explicitly matching the private installation profile; migration/hash unchanged, deployment guide corrected. Earlier unit import and diagnostic stdin-timeout failures were fixed and rerun, not counted as acceptance. Root passed 33 focused fixture/protocol and 62 focused Node checks, 1725 Python/tool regressions (four deliberate existing warnings), strict Python36files and strict TypeScript build/980 Node tests. No live model, hosted writes/CI, publication or production-readiness claim. Learning practice remains unassessed. Final resource observation: 39 GiB disk and 63 percent system memory free; all 16 sealed inputs and three user audits unchanged, no owned service or PostgreSQL temporary directory remains. Next smallest task: V5-04A, freeze the durable publication/repair execution contract and bounded children before dependent ingestion edits; existing core integration remains V5-07.

### V5-03B/C: Native authoritative source readers

State: COMPLETE for implementation/local reader-contract acceptance. Actual reader LOGIN/cross-store disclosure remains V5-03D. Dependency V5-03A accepted/pushed in 62d422c, synchronized 0/0. Shared outcome: native source-only readers implement frozen QS-r1 private request bindings, active published candidate admission, fresh provider/final release, exact complete-source UTF-8/byte/profile verification and bounded clean borrowed-pool work. No source migration/publication/coordinator compatibility is inferred.

- Sol `v5_candidate_contract`, Python writer and named assembler, owns only new `packages/python/src/cragkit/qdrant_source.py`, `_qdrant_source.py`, `_qdrant_authority.py`, `packages/python/tests/test_qdrant_source.py`, `test_qdrant_authority.py`.
- Sol `v5_candidate_fixtures`, Node writer, owns only new `packages/typescript/src/qdrant-source.ts`, `qdrant-source-contract.ts`, `qdrant-authority.ts`, `packages/typescript/tests/qdrant-source.test.mjs`, `qdrant-authority.test.mjs`.
- Root owns shared QS-r1/scenarios/schema and native harnesses, package exports, manifests/locks, evidence/tracker, all check execution and Git. Peers coordinate row format/APIs/error/cancellation fixtures directly; no overlapping edits. Previous source foundation paths are transferred to root. Changes to protected contracts, outcome or another lane's ownership escalate before dependent edits; unresolved material decisions go to Astra through root.

Frozen schema checksum: 3d75cd46eb32a10864f1097a7494b01f9759150911a7cd9a1e6aab60105c1f1a; QS-r1 with 40 normative scenarios. One store/one request handle/one in-flight operation, no queue; 64 fetch slots/bindings, two purpose-specific release attempts per binding, cumulative 16 MiB canonical reads, 32 KiB excerpts and original deadline. Validate native inputs/models and driver rows before disclosure; preserve unknown outages as operational errors. Read-only scoped transactions never stay open over providers; borrow existing bounded pools without closing them. Applied old and new migrations, E/EL/QD/QC and existing core/PostgreSQL/corrective source remain protected; no fake scalar score or duplicate ledger reservation is introduced to force old backend compatibility.

Workers write owned implementation/tests only; no tests/processes/services, installs, network/database/provider calls or Git. Root starts with focused fake-connection tests and strict native types, serial runtimes and small fixtures. Source-reader acceptance against actual LOGIN/PostgreSQL/Qdrant follows V5-03D, after unit/type/fixture integration. No paid model, provider disclosure or persistent background service. Root is final integrator; learning: a genuine historical revision still needs current grants and a binding from the active selection. Next action: V5-03D actual restricted reader LOGIN and PostgreSQL/Qdrant disclosure acceptance.

V5-03B/C final handoff: both Sol runtime lanes implemented and froze five owned files each, coordinated parity directly, and the Python peer assembled. Independent Sol security review found close-during-initialization and fresh-lease role gaps; both fixed with regressions. Assembly resolved denied-row buffer type/length parity. Root integrated the optional Node export and immutable whole-source verification, ran 97 focused Python/tool checks, strict types across 36 source files, 1692 full Python/tool regressions (four existing deliberate Pydantic warnings), strict TypeScript build, 57 focused Node checks and 975 full Node package tests. All 40 shared source scenarios execute with fake authority; no real LOGIN/provider-disclosure acceptance is inferred.

Root froze the exact catalog query/reference manifest with hash 8104abeef00594e7bfa4b533a139767599b56b87d09062c0d6f52f6e2f5d0b48. Two successful fresh PostgreSQL 17.11 rollback-only probes reproduced it; eight final native groups include intentional policy/helper/constraint/PUBLIC ACL drift rejection and stable named reader grants. The initial empty ACL query failure (22023) was fixed and rerun; namespace/data/roles/memberships rolled back and existing histories/role graphs matched. All 16 sealed inputs and three user audit drafts preserved. No live provider, model install, persistent service, publication or hosted CI. Final snapshot: 39 GiB disk and 63 percent system memory free. Learning practice unassessed. Next: V5-03D; preinstalled local PostgreSQL 17.11 is available for an isolated TLS/SCRAM reference fixture alongside managed Qdrant, avoiding shared hosted fixture writes.

### V5-03A: Authoritative source foundation

State: COMPLETE for the source-only foundation after V5-02 committed/pushed in a4431bd and synchronized 0/0. Concrete outcome: freeze native authoritative source read semantics/fixtures and implement the separate optional PostgreSQL content schema, with native constraint/RLS validation and rollback cleanup before acceptance. This is the source-only foundation; V5-03B/C/D and V5-04 remain required for complete retrieval and QD-r1 publication compatibility.

- Sol `v5_candidate_contract` owns new `storage/qdrant/postgres/migrations/0001_authority.sql`, `storage/qdrant/postgres/README.md` and assembles the pair. Implement isolated schema/own history, canonical immutable revisions, scoped generation/member identity, current document authorization/metadata/tombstones and read policies. No permanent roles or writer policy is introduced by this slice; privileged staging remains administrative test setup until V5-04 writer profile freezes.
- Sol `v5_candidate_fixtures` owns new `contracts/QDRANT_SOURCES_V5.md` and `contracts/fixtures/qdrant_sources.json`: native read API, full-profile/member/source validation, source row format and authorization-before-provider/final-release expectations. Coordinate exact schema/row/profiles directly with the SQL owner.
- Root owns shared plan/tracker, migration wrapper/native SQL acceptance and focused tests, exact version/target checks, protected-scope review, evidence and Git. Peers may adjust within the two owned areas only after agreeing a stopped transfer and notifying root. Preserve existing core/PostgreSQL adapters, E/EL/QD contracts, all applied migrations/histories, provider policy, credentials, sealed data and user audits. No borrowed resources are closed by an adapter.

Frozen dependency: QD-r1 plus QC-r1 E; initial schema is `cragkit_qdrant`, PostgreSQL 17 with no pgvector/FTS dependency. Full generation identity includes backend namespace, physical collection/incarnation, tenant/logical collection/document/revision/generation/chunk and exact dense/sparse profiles. Read authority checks active published membership for new search; retained previously published content is a separate fresh-authorization path after an existing binding. Current grant/metadata/tombstone checks precede source bytes and final release. Scope stays outside query input. Public prose/schema changes may not weaken QD-r1 or imply writer fencing; durable intent/registry/dispatch/coordinator/CAS are later V5-04 work.

Workers perform substantive file work only: no tests/processes, installs, services, network/database/provider calls or Git. Root runs one check process, small fixtures, one backend profile at a time and at most two native database connections after the dedicated target/TLS/security gates. No live models or recurring services. SQL acceptance is transactional and refuses a preexisting authority namespace; existing histories/user data remain untouched. Escalate outcome/protected-boundary/other-lane ownership changes before dependent edits, unresolved material decisions to Astra. Root is final integrator; learning example: stale vector grants nominate identities but cannot authorize bytes. Next action: V5-03B/C native source readers against frozen QS-r1 and the exact schema checksum.

V5-03A final handoff: substantive Sol SQL/guide and contract/scenario lanes coordinated schema/row/identity directly; SQL peer assembled, and all writes stopped/transferred. Root computed five canonical digest expectations, verified UUID and 40 scenario identities, built the rollback-only native helper and ran 20 focused tests plus 1615 complete Python/tool regressions (four existing deliberate Pydantic warnings). Refreshed direct Neon security/vector/history gates passed. Six native source-schema groups passed under forced RLS with an isolated NOLOGIN SET LOCAL ROLE; exact digest/span/composite/profile/immutability/security-epoch/tombstone and grant-policy failures behaved as declared. NUL bytes survived exactly. Entire new namespace, seed data and role/membership rolled back; original lexical/vector histories and role/membership fingerprints matched, connection closed before success artifact. No persistent authority installation or actual reader LOGIN/source adapter/publication acceptance is claimed.

The first native probe failed honestly at SQLSTATE55006 because deferred FK events preceded ALTER TABLE. Root added explicit constraint resolution, ordering regression and bounded rollback/close diagnostics, then reran successfully. Independent Sol review found extreme numeric/deep JSON parse exceptions in scope settings; narrow catches now deny malformed settings while keeping operational cancellation/timeout/memory/connection failures explicit, with native regressions. Migration checksum: 3d75cd46eb32a10864f1097a7494b01f9759150911a7cd9a1e6aab60105c1f1a. Existing runtime sources/applied migrations/sealed inputs/user audits preserved. PostgreSQL drivers were restored from pinned cached extras; no model/provider call, download, recurring process, package publication or hosted CI. Final resource snapshot: 39 GiB disk and 62 percent system memory free; all task connections closed. [Evidence](../evaluation/reports/V5/V5-03A.md); full V5 remains active. Learning practice unassessed; next smallest implementation is B/C native source adapters, then D real disclosure/final-release gates. Existing CorrectiveRetriever internal candidate/accounting compatibility stays an explicit V5-07 dependency.

### V5-02E: Dense profile and batch binding

State: COMPLETE for E1/E2/E3. Dependency: B/C/D accepted and pushed in 1f6cc2b. Shared outcome: the accepted OpenAI E-r1 profile works as dense-only, full batch identity is checked before candidate dispatch, and examples preserve usage and deadlines without automatic live calls. Frozen contract: QC-r1 E extension. E1 native bindings, E2 bounded composition examples and E3 serial native acceptance all passed; V5-02 candidate-only acceptance is complete.

- Sol Python peer owns `packages/python/src/cragkit/qdrant.py`, `_qdrant_contract.py`, `packages/python/tests/test_qdrant.py` and new `test_qdrant_embeddings.py`; assembler for the pair.
- Sol Node peer owns `packages/typescript/src/qdrant.ts`, `qdrant-contract.ts`, `packages/typescript/tests/qdrant.test.mjs` and new `qdrant-embeddings.test.mjs`.
- Root owns contract/fixtures, E2 examples and their focused checks, E3 native harness/checkers, all manifests/locks, evidence/tracker and Git. Peers coordinate concrete interfaces directly and request ownership transfer before overlapping edits. Protected: E-r1/EL-r1 implementations, transport modules, existing PostgreSQL source/migrations, sealed data and user audits. Escalate protected-boundary/outcome changes to root; unresolved material choices to Astra.

Both peers do substantive implementation and tests but run no tests/processes, services, installs, network/provider/database calls or Git. Root runs one test process/language suite at a time with small fixtures and the already verified one-worker Qdrant target. Acceptance: full descriptor/synthetic/dimension/norm/usage failures before dispatch, real-profile routing spies, immutable batches and identities, exact accounting in fake/failed/preflight examples, real dense-only Qdrant mechanics under fake identity, regression/type/parity checks and complete shutdown. Resource policy remains M4/16 GiB; no install/model download is required. Learning example: equal dimensions do not establish compatible vector spaces. Practice unassessed; next action V5-03A source-authority contract and isolated optional schema before native source adapters.

E final handoff: both Sol peers implemented three changed runtime/test paths each and consumed the root-owned 13-case shared fixture; the Python peer assembled interfaces and found/fixed one malformed-input error-class mismatch. All peer writes stopped and transferred to root. Root reviewed sources and examples, added char-before-byte string/key bounds, and ran 190 focused Python/tool tests, strict mypy over 33 source files, Node build and 48 focused Node cases. Final regressions: 1595 Python/tool tests (four existing deliberate Pydantic warnings), 918 Node package tests and eight Node example tests. Real Qdrant 1.20.0 passed 12 dense-only and 12 hybrid cases per runtime with full nomination/ledger parity; both runs verified isolated write restrictions and complete process/config/data/collection shutdown. Real-profile behavior used in-memory spies only, never persistence; actual backend vectors kept fake identity. Independent Sol static review found no material issue; caller initialization remains explicit. No paid call, model/runtime download, remote DB mutation, hosted CI or package publication. Latest headroom: 39 GiB disk and 67 percent system memory free, snapshot only. Changed scope: native Qdrant binding helpers/tests, shared E contract/fixture, two composition examples/guide and checks, native acceptance mode and docs/tracker/report. Three user audits and sealed inputs remain protected. Full V5 remains active; source authority, publication/repair, existing-index/MCP, parity and artifact gates remain. [Evidence](../evaluation/reports/V5/V5-02E.md).

### V5-02B/C/D: Native scoped candidates

State: COMPLETE for B/C/D initial-profile acceptance. Shared outcome: native QC-r1 adapters with strict scoped preselection, text-free immutable nominations, bounded streaming transport and serial isolated-backend acceptance. Dependency: V5-02A accepted in a54ef1f; QC-r1's native-binding appendix fixes the shared interface before dependent edits.

- `/root/v5_candidate_contract`, gpt-6.1-sol, Python implementation peer and assembler: owns `packages/python/src/cragkit/qdrant.py`, `_qdrant_contract.py`, `_qdrant_transport.py` and `packages/python/tests/test_qdrant.py`, `test_qdrant_transport.py` only.
- `/root/v5_candidate_fixtures`, gpt-6.1-sol, Node implementation peer: owns `packages/typescript/src/qdrant.ts`, `qdrant-contract.ts`, `qdrant-transport.ts` and `packages/typescript/tests/qdrant.test.mjs`, `qdrant-transport.test.mjs` only.
- Root owns shared QC-r1/fixtures, manifests/locks, optional exports, test harnesses, serial execution, tracker/evidence and Git. Peers coordinate interfaces and failures directly, request corrections from the owner and escalate outcome/protected-boundary changes before dependent edits. Shared wire/core/PostgreSQL contracts, migrations, sealed inputs and user audits remain protected. No overlapping edits; assembler never rewrites the other lane without stopped-writer transfer.

Workers may read actual APIs and write owned files; no tests, installs, services, network/database/provider calls or Git. Root alone runs one test process/language suite at a time, optional HTTPX setup and the one-worker isolated synthetic Qdrant service. Acceptance: focused unit and hostile-input/stream/cancellation tests, strict types, QC-r1 native fixtures and real scoped search in both runtimes; guard core imports and close every task resource. V5-03 authority and V5-04 publication remain dependencies for complete retrieval and are not implemented by candidate nominations.

Final B/C/D handoff: peers coordinated and assembled their five-file native lanes, then stopped/transferred writes. Independent Sol review found the NODE_OPTIONS proxy gap; Node fixed it and root reran checks. Root source review also corrected credential-length, long numeric-token and unsafe deadline parity, with regressions. Focused acceptance: 131 Python/tool tests, 26 Node cases, mypy over 33 source files and Node build passed. Full regression: 1536 Python/tool tests with four existing deliberate Pydantic serializer warnings; 904 Node tests. Actual Qdrant 1.20.0: 12 cases per runtime with complete nomination/ledger parity, read-only/anonymous write denial and verified cleanup. Explicit Python/Node import guards passed. User audits and sealed inputs remain unchanged. No live model, remote DB, package release or hosted CI used. Latest headroom: 39 GiB disk/68 percent free system memory, a snapshot. [Evidence](../evaluation/reports/V5/V5-02.md); machine outputs are ignored under artifacts/V5. Learning practice unassessed. Full V5 remains active: E is next, then source authority, durable repair, existing-index/MCP, parity and artifact gates. Astra advised E because permanently fake-only support would be too narrow, while the accepted architecture permits real dense-only deployment without inventing a new sparse encoder; no provider/cost permission is inferred.

### V5-02A: Native candidate contract and reference target

State: COMPLETE for V5-02A. Outcome: freeze QC-r1 candidate/filter/profile/point identity mappings and select exact optional client/server versions plus an isolated reference target before dependent runtime edits. QD-r1 is the protected consistency dependency; no SourceStore authorization/publication implementation is claimed here.

- `/root/v5_candidate_contract`, gpt-6.1-sol, implementation mode and pair assembler: owns only `contracts/QDRANT_CANDIDATES_V5.md`, covering planned native boundary, capabilities, filter semantics, profiles, identities and fail-closed validation. Read-only dependencies: QD-r1, architecture, wire/embedding/execution contracts and peer fixtures.
- `/root/v5_candidate_fixtures`, gpt-6.1-sol, implementation mode: owns only `contracts/fixtures/qdrant_candidates.json`, covering deterministic point-ID examples, bounded filter translations and hostile response/profile cases. Coordinates concrete dependencies directly with the contract peer against QC-r1.
- Root owns tracker, contract index, exact version/target verification, check evidence and final Git integration. All product modules, package/lock files, storage/migrations, sealed inputs and existing user audits remain protected. Peers make no overlapping edits; transfers require a stopped previous writer and root notification. Outcome/boundary changes and unresolved decisions go to root, then Astra only if necessary.

Checks/resources: workers use local reads and owned writes only, no tests, services, installs, providers, databases or Git. Root may inspect official metadata/archives and run one task-owned native Qdrant reference process against synthetic data only, on loopback with explicit limits; no model/provider or cloud account. Root serializes checks, validates documentation/fixture mappings and cleans prose before acceptance. Current headroom snapshot: 39 GiB disk and 55 percent free system memory. Next: freeze QC-r1 and verify the target, then V5-02B/C native implementation on separate paths; V5-02D retains adapter integration acceptance.

25 October 2026 handoff: two Sol peers delivered QC-r1 and fixtures on separate paths, coordinated directly, assembled and transferred ownership. Root inspected exact SDK archives and selected streaming REST instead: optional HTTPX 0.28.1/Python 3.14.6 and Node 26.5.0 built-in fetch, Qdrant 1.20.0. Independent Sol review found no remaining material contradiction. Root verified eight isolated server-readiness groups, five Python and four Node transport prototype checks, and independent Python/Node UUID agreement for four identities. Strict fixture checks cover 4 point-ID, 6 filter, 21 response and 6 admission scenario records; these are design expectations, not executed adapter assertions. Local links and prose checked before commit. Server/data/private key/config and isolated HTTPX environment are closed/removed; no provider or hosted database call, project dependency change or user-audit edit. The 38464 KiB server RSS is a snapshot, not peak or performance evidence. [Evidence](../evaluation/reports/V5/V5-02A.md). V5-02 remains incomplete; next B/C implement the native adapters, then D validates them against the isolated backend. The full V5 goal remains active through source authority, repair, existing-index/MCP, parity and artifact gates.

### V5-01: Consistency specification assignment

State: COMPLETE for design acceptance. Outcome: freeze QD-r1 authority, generation publication, sparse identity and ACL synchronization before Qdrant adapter code. Dependencies: V4 exit and audit follow-ups accepted; V4 default-budget performance limitations remain unchanged.

- V5-01-A, Sol specification peer and assembler: write only `docs/decisions/0003-qdrant-consistency.md`; define authority, identity and publication protocol. Read architecture, current source contracts and the peer failure table. No implementation, schema, migration, dependency or lock changes.
- V5-01-B, Sol failure-model peer: write only `contracts/QDRANT_V5.md` and `contracts/fixtures/qdrant_consistency.json`; define bounded scenario records and every write-boundary outcome, including revocation, tombstones and ambiguous acknowledgements. Coordinate directly with A against QD-r1; escalate unresolved contract changes to root.
- Root: final integration, tracker and index links, official-source verification, local JSON/link/consistency/prose checks, scoped Git commit/push. Both peers contribute substantive artifacts; A assembles after B reports ready. Shared architecture, existing contracts, wire schemas, manifests/locks, storage and user-owned audits are protected. No overlapping edits; ownership transfers require the previous writer to stop and root notification.

Allowed resources: local reads and owned documentation/fixture writes only; no worker test processes, services, installs, databases, providers or Git actions. Root serializes checks. This task specifies behavior; it cannot establish adapter or production acceptance. QD-r1 is frozen; the next task is V5-02's native scoped candidate slices.

25 October 2026 final handoff: `/root/v5_consistency_spec` (gpt-6.1-sol) wrote the ADR and assembled `/root/v5_consistency_cases` (gpt-6.1-sol)'s substantive contract/fixture work after direct coordination. Both transferred their paths to root before integration. `/root/v5_consistency_review` (gpt-6.1-sol) independently found a cross-document physical-ID collision race; root added the shared atomic point-ownership registry, ambiguous claim reconciliation and two scenarios. The reviewer rechecked and accepted the correction. No unresolved escalation required Astra. Root also distinguished known missing/deauthorized sources from authority outages and assigned absent coordinator capability its own failure row.

Changed files: ADR 0003, QD-r1 contract and scenario JSON, contract index, active V5 plan and this tracker. Root walked all 21 table boundaries and 26 synthetic scenarios against architecture, existing retained-generation policy and official Qdrant point/completion/consistency semantics. Local checks passed strict duplicate-key JSON parsing, unique IDs, UUID example shape, row/task mappings and complete row coverage; Markdown target/anchor and prose checks passed. These are document consistency checks, not executed adapter/security tests. Deterministic prose cleaning preserves code/identifiers and claims; generated inspection/check evidence is under ignored `artifacts/V5/V5-01/`.

No product code, migration, package/lock, sealed evaluation input or user-owned audit report changed. No test suite, database/provider call, install or background service ran. SourceStore/coordinator/client versions and durable behavior still need implementation and isolated integration acceptance; V5-02 through V5-08, checkpoints and V5 exit remain open. Resource observation: 38 GiB disk and 53 percent system memory free before these small local checks, a snapshot rather than performance evidence. No task-owned process remains. Learning example: vector completion alone cannot publish a tombstoned generation; a per-document lock also cannot reserve a physical point ID across documents. Practice unassessed: explain why an ambiguous write and a tombstone must be reconciled before publication or purge completion. Next smallest action: V5-02A, freeze native candidate/filter/profile contracts and select verified versions/isolated target before parallel runtime implementation. Root owns the scoped commit, immediate push and synchronization check; the final reply records the result.

### DOC-AGENT-01: Project coordination and manager skills

State: COMPLETE. User-authorized documentation work; this does not complete a V0 implementation task.

Outcome: Persist two project skills and route future coordination and peer management through them, with direct Sol peer communication, bounded ownership and Astra escalation.

| Child task | Owner | Writable paths | Acceptance |
| --- | --- | --- | --- |
| DOC-AGENT-01-C | `/root/coordinate_peer` (Sol) | `.agents/skills/cragkit-coordinate/SKILL.md` | Independent lanes, direct dependency resolution, plan-change reporting, unresolved escalation and integration checks. |
| DOC-AGENT-01-M | `/root/manager_peer` (Sol), assembler | `.agents/skills/cragkit-manager/SKILL.md`, `docs/agents/WORKFLOW.md` | Two substantive peers share one outcome, complementary duties and explicit initial ownership; reconcile both skills and report assembly findings. |
| DOC-AGENT-01-I | `/root`, final integrator | `AGENTS.md`, `tasks/plan.md`, `tasks/todo.md`, `tasks/versions/*.md` | Persist activation and authorization rules, align resource policy, inspect assembled files, validate skills and local links, record evidence. |

Shared constraints: documentation only; no product/API changes, installations, services, commits or publication. Each peer reads the architecture, active V0 plan, agent workflow and prose-cleaning skill. Shared contracts, tracker and integration checks stay with the primary coordinator. Peers message each other about concrete dependencies and may transfer ownership only within their assigned documentation subsystem after the previous owner stops writing. Report transfers and plan changes to the primary coordinator; escalate protected boundaries and other lanes' ownership before dependent work. Run validation serially at final integration.

Integration evidence (19 October 2026): inspected all assembled guidance; both Sol peers coordinated directly and resolved explicit model naming. Ruby `YAML.safe_load` plus skill name, description, path and scaffold checks passed for both skills. The bundled `quick_validate.py` was attempted for both and could not start because PyYAML is absent; no dependency was installed. A Python local-link/heading-anchor check passed for 140 links across 13 changed Markdown files. Self-contained prose inspection and deterministic cleaning found zero suspicious characters, removals or replacements; skill and guidance density tiers were low, with the existing tracker at medium. No product tests, services or Git actions were run. The workspace has no Git checkout. Astra escalation was not needed; its execution path remains unexercised.

Learning: explicit ownership lets peers work independently; two peers editing one fixture would require stopping and agreeing on a transfer. Optional exercise: identify the sole owner of a shared contract before assigning its two consumers. Understanding remains pending.

Next action: user has authorized V0 implementation; begin V0-01 resource and workspace baseline.

### Active V0 implementation handoff

V0-01 shared outcome: record a measured workspace/resource baseline and safe development commands before package setup. Both peers use Sol and coordinate directly. `/root/coordinate_peer` owns `docs/development.md`, runtime/tool observations and assembly. `/root/manager_peer` owns `evaluation/reports/V0/V0-01.md`, hardware/resource/service observations and database isolation preconditions. `/root` owns the tracker and final acceptance. These initial paths are disjoint; no credentials, installs, service changes or live database/provider calls during this task. No product contract exists yet. Acceptance: actual observations, one-process policy, hosted Supabase choice and explicit isolation requirements before any hosted test. Report actual commands, limitations and resource observations; understanding remains pending.

V0-01 accepted: M4/16 GiB, 22 GiB free disk, kernel pressure 1 with 2855.75 MB allocated swap (growth unmeasured); Python 3.14.6, Node 26.5.0, npm 11.17.0, uv 0.11.8. Small package setup is appropriate; no model/database assets. No Git checkout.

V0-02 shared outcome: two native importable internal packages with smoke tests, no runtime dependencies or I/O at import. `/root/coordinate_peer` owns `packages/python/` (Python child and assembler); `/root/manager_peer` owns `packages/typescript/` (TypeScript child). Each owns its package manifest/lock only. `/root` owns `.gitignore`, docs, tracker and serialized installation/testing. Peers author at most five initial files per child and communicate directly about version/export conventions. Internal package version `0.0.0`; no public release or license decision. Initial runtime probes target installed Python 3.14 and Node 26, with support finalized at V0-03. No installs/tests in peers; root runs them sequentially. Acceptance: installed/compiled core imports with network blocked and no database/model/framework modules, plus one focused smoke test each. V0-03 begins only after both pass.

V0-02 accepted and V0-03/C1 accepted: both smoke tests and typechecks passed. Root assumed manifests/lock ownership for dependency compatibility work; exact locks and optional-driver checks are recorded in V0-03 evidence.

V0-04 assignments, revision `0.1`: `/root` owns `contracts/`, `tools/`, both manifests/locks, docs and tracker; 34 shared request fixtures frozen before workers began. `/root/coordinate_peer` owns Python `contracts/`, `errors.py`, `tests/test_requests.py` and is assembler; `/root/manager_peer` owns TypeScript `src/{contracts,requests,shared,errors}.ts`, `tests/requests.test.mjs`. Outcome: native request/tool/scope validation, immutable snapshots and fixed redacted typed errors. No retrieval/database/provider implementation. Installed Pydantic 2.14.1/Zod 4.6.7 are the contract libraries. Root runs tests and combined fixture parity sequentially; peers inspect/code and resolve concrete dependencies directly. Protected boundaries remain in AGENTS.md; schema changes need root coordination before dependent work.

V0-04 accepted after both peers resolved preflight bounds and regression coverage directly; final Python 61/TypeScript 41 tests, typechecks and 34-case native conformance passed. V0-05 shared result specification is now frozen in `contracts/RESULTS.md`, with 32 shared fixtures. `/root/coordinate_peer` owns Python `contracts/results.py`, `contracts/__init__.py`, `tests/test_results.py`; `/root/manager_peer` owns TypeScript `src/results.ts`, `src/contracts.ts`, `tests/results.test.mjs` and is assembler. Request sources remain read-only unless a concrete integration defect needs an explicit ownership update. Root retains shared specifications, fixtures, schemas, tools, manifests, docs, tracker and serial verification. Outcome: source-linked result models, excerpt byte/digest checks, honest coverage/execution and unknown accounting; no retrieval/tokenizer/model/DB execution. Acceptance: full native fixture output parity, focused invariant failures, strict typechecks and import regressions.

V0-05 accepted with the evidence above. V0-06 assignments: `/root/coordinate_peer` owns `evaluation/corpus/`, `evaluation/questions/`, `evaluation/review/V0-labels.md` and is assembler; `/root/manager_peer` owns `evaluation/protocol.md`, `tools/check_corpus.py` and its focused tests. Root owns task evidence, tracker, final checks and the human-review request. Shared outcome: 12 small original documents and exactly 30 labelled synthetic questions, two tenants/revisions/Unicode/identifiers/absent answers, development versus held-out family isolation and a concrete human review packet. Peers agree format directly before authoring; validator runs only in root after files freeze. No private data, services, model/provider calls or tuning on held-out labels. Architecture section 13 requires human review of synthetic questions; agent/manual inspection and structural validation cannot claim it happened. V0-07 remains dependent on V0-06 acceptance.

Previous handoff before human approval: V0-01 through V0-05 COMPLETE. V0-06 artifacts are mechanically verified (16 corpus tests, all 12 source digests, all 30 questions/37 facets/26 spans); human review is pending in both datasets and the required-review gate correctly fails. The real user was asked to review the concrete 30-question packet; no response or approval is inferred from elapsed time. V0-C2, V0-07, V0-C3 and V0-EXIT remain unchecked. Code paths: native Python `src/cragkit/contracts/` plus `errors.py`; TypeScript `src/{requests,results,shared,contracts,errors}.ts`; shared fixtures/schemas under `contracts/`; corpus/protocol/review under `evaluation/`; native conformance, schema export and corpus checker under `tools/`. Evidence and verified commands are linked above. No Git actions, hosted database/provider calls, services or task-owned background processes. Latest observed environment sizes: Python 89 MB and npm 41 MB; kernel pressure 1. Learning remains pending. Next smallest action: receive actual human label review, apply any corrections, rerun required-review checks and seal the final hashes; only then start V0-07 local CI/build/artifact acceptance. Hosted CI still has no available repository/remote and must be recorded separately.

Update after each implementation or project-guidance session:

V0-06 human approval received in this conversation: "I reviewed and approve all 30 labels". Recorded reviewer as project-user, updated review declarations without changing source text or question/facet labels, and sealed 16 inputs in `evaluation/review/seal.json`. Full C2 acceptance passed; no approval was inferred from automated tests.

V0-07 shared outcome: a single local command runs the minimal CI checks sequentially and validates clean Python/npm artifacts with measured import/setup resources. Initial ownership: `/root/coordinate_peer` (Sol), assembler, owns `tools/check_v0.py` and `tools/tests/test_check_v0.py`; `/root/manager_peer` (Sol) owns `tools/check_artifacts.py` and `tools/tests/test_check_artifacts.py`; `/root` owns `tools/check_seal.py` and its tests, documentation, tracker, report and final execution. Peers coordinate CLI/result interfaces directly. All package manifests, locks, core contracts and sealed corpus inputs are read-only unless an integration defect requires root reassignment. Root alone executes installs/tests/builds, serially. No services, live models/providers, Git actions, publication or hosted CI activation. Acceptance: fail-fast local pipeline, frozen installs, strict typing, native/unit/tool/conformance/schema/corpus/seal checks, wheel/sdist/npm archives and clean installed imports without optional database/model dependencies; preserve separate local versus hosted evidence.

Latest handoff: V0 COMPLETE locally after explicit approval of all 30 labels and the full 12-stage acceptance run. Changed this session: approval metadata in both question datasets; human review packet/protocol and 16-file seal; local pipeline, artifact and seal checkers plus focused tests; docs/ci.md, docs/development.md, V0-06/V0-07 reports and this tracker. Final results: 155 Python/tool tests, 78 TypeScript tests, both strict typechecks, 66 shared native cases, four schema drift checks, approved development-corpus checks, all sealed hashes and clean wheel/source/npm installations passed. Rebuilt wheel contents and hashes matched. Final docs: 188 local links/anchors across 25 files; prose hygiene passed with no changes. Resource snapshot: 22 GiB free disk, kernel pressure 1, swap 2767.75 MB; three separate fresh-process import samples and payload sizes are recorded in V0-07 evidence. Temporary environments removed; no task-owned background services or processes. No Git actions, database/provider calls, held-out scoring or publication. The user practiced human label review; broader learning remains pending. Next smallest action: V1-01 schema and explicit migrations; inspect its version plan and architecture before implementation and verify a dedicated database target before live use. Hosted CI is unrun because no Git repository/remote exists.

```text
Current task and state:
Files changed:
Commands actually run and results:
Edge cases covered:
Resource observations:
Learning practiced / still unclear:
Blocked decision, if any:
Next smallest action:
```


## V1-01 active assignment

Shared outcome: explicit, versioned PostgreSQL lexical storage schema with composite tenant/collection/document references and repeatable database verification. Contract V1-01-r1: private `cragkit` schema; no application package imports or automatic migrations; no vector tables/extensions, public API grants, provider calls, corpus changes or V1-02 adapter work. Administrative migrations use explicit developer tooling; native packages stay read-only. An isolated dedicated Supabase target and certificate-verified connection are required for hosted acceptance. Existing unrelated Supabase projects are excluded.

- V1-01-A: `/root/coordinate_peer`, Sol `gpt-6.1-sol`, implementation and assembler. Owns `storage/postgres/migrations/` and `storage/postgres/README.md`. Delivers immutable revision, scoped relations, lexical indexes and a documented migration contract. Read-only: architecture section 7, active V1 plan, E18 and peer tooling/tests.
- V1-01-B: `/root/manager_peer`, Sol `gpt-6.1-sol`, implementation. Owns `tools/check_postgres.py`, `tools/tests/test_check_postgres.py` and `storage/postgres/tests/`. Delivers explicit application/rerun tooling and integration assertions for scoped references, immutability, constraints and failure handling. Read-only: schema and package code.
- `/root`: coordinator, final integrator, tracker, reports, development documentation and Git. Owns manifests/lockfiles if required, pending target discovery and hosted runs. No peer Git mutations or concurrent test processes.

Peers agree exact column names and runner boundary directly before dependent edits, report contract revisions and ownership changes to root, and escalate unresolved material decisions through root to Astra. Both do substantive work; A assembles and root performs final acceptance. All paths outside the assigned subsystem are protected. One test process at a time, small synthetic SQL fixtures, no service startup or tool installation merely for a lane. Acceptance: empty isolated database migration, safe rerun, mismatched migration rejection, invalid cross-scope foreign keys, immutable revision update failure, and core import isolation. Hosted target discovery found no Cragkit project or database environment configuration; the target question is pending while local implementation proceeds. State: assigned.

Contract V1-01-r1 frozen directly by both peers: raw `0001_initial.sql`; runner owns transactions, advisory lock and checksummed `cragkit.migration_history`. Eight logical lexical tables, scoped generation/job relationships, immutable revision updates, purge deletion allowed, built-in SHA-256 and no extension install. PostgreSQL 17.11 binaries are already installed and no server was running. Root will use an explicitly configured, task-owned temporary Unix-socket cluster for additional local integration validation, then stop/remove it. This does not replace the dedicated Supabase acceptance checks. No Docker or new tool download.


V1-01 handoff: A and B completed their disjoint implementation work and direct contract coordination; A assembled the result and root inspected it. Root corrected review findings through the owning peer and ran one test process at a time. V1-01-A (schema) and V1-01-B (tooling/probes) are implemented and verified locally. Parent V1-01 remains IMPLEMENTED_UNVALIDATED; its checkbox stays open. Required hosted validation is the remaining acceptance step, and V1-02 has not started.

Changed files: storage/postgres/migrations/0001_initial.sql, storage/postgres/README.md, storage/postgres/tests/invariants.sql, tools/check_postgres.py, tools/tests/test_check_postgres.py, README.md, docs/development.md, tasks/versions/V1-first-library.md, this tracker and evaluation/reports/V1/V1-01.md. Root owns final documentation/status and Git; peers have stopped writing except requested probe corrections. Public contracts, native source, dependency locks and sealed corpus are preserved.

Actual checks: 17 focused tool tests, 172 combined Python/tool tests, TypeScript build and 78 tests passed. Real PostgreSQL 17.11 local checks passed for empty apply, rerun with unchanged ledger timestamp, read-only history check, scoped FK/immutability/byte/FTS/purge invariants, checksum and unknown-history rejection, failed-migration DDL+ledger rollback, and nonempty integration-target rejection without data loss. An initial failed emoji-vector test was corrected to the actual declared tokenizer output and rerun successfully. No hosted SQL, target provisioning, model evaluation, hosted CI or package publication. Final prose/link/whitespace/staging and push checks are recorded at integration completion.

Resources: 23 GiB disk available and 74% system-wide memory free before the run. Used existing PostgreSQL binaries, private temporary Unix sockets, 16 MB shared buffers and 10 maximum connections. No tool/model installs or Docker; every task-owned cluster stopped and removed on success/failure. Learning remains pending; optional exercise is to explain composite keys and the active-generation pointer. Next smallest action: answer the pending dedicated Supabase target question, verify connection mode/certificate/permissions/schema compatibility, run migration/rerun/invariants and advisors there, then close V1-01 before V1-02.

Final V1-01 local integration: final SQL rerun passed after the digest and exact-byte-limit probes were added; the assembler confirmed those probes by inspection. All 16 sealed hashes passed. Six prose files and 118 local links/anchors passed with zero deterministic text changes; whitespace passed. No PostgreSQL processes remain. The focused local implementation is ready for the authorized commit/push; parent acceptance still requires the dedicated hosted target.

Version-control handoff: implementation commit `24878221b872cfed67024bb665ddb8ff01760847` was pushed to `origin/main`. Fetch, matching `ls-remote` commit, zero ahead/behind and a clean working tree were verified. This final publication note is a separate documentation commit; no implementation inputs changed after acceptance. Hosted Supabase verification remains the only next V1-01 acceptance action.


## V1-01-H: Dedicated Supabase configuration

State: IN_PROGRESS. User explicitly authorized using the Supabase plugin for secure development configuration. Organization selection is required by the plugin and is pending; no provisioning or hosted writes have occurred. Shared outcome: a dedicated Cragkit development target with a private schema, minimal access, explicit migrations, safe hosted probes and an accurate connection/security handoff. Contract V1-01-H-r1 preserves the applied/local-tested 0001 bytes and native package boundaries. No costs, unrelated-project changes, new auth flows, broad runtime policies or V1-02 adapter implementation.

- V1-01-H-A: `/root/coordinate_peer`, Sol `gpt-6.1-sol`, implementation and assembler. Owns `storage/postgres/deployment/supabase.sql` and `storage/postgres/tests/security.sql`. Prepare scoped hardening and privilege/RLS probes, compatible with both fresh Supabase and an explicitly created local test role setup. No permanent application login credentials or allow-all policy. Read-only: initial migration, existing invariants/tooling, architecture and relevant E18/E22.
- V1-01-H-B: `/root/manager_peer`, Sol `gpt-6.1-sol`, implementation. Owns `docs/supabase.md`. Prepare secure target/connection/runbook documentation, distinguishing plugin-admin evidence from a native certificate-verified client, and directly review A's scripts against documented role and security claims. No secret examples or project facts without root evidence.
- Root: coordinator/final integrator, all remote actions and credentials, tracker/reports, existing development/status docs, tooling changes if required, serialized tests and Git. No peer remote mutations, tests, services, installs or credential access. Peers coordinate directly before dependent work; A assembles, root runs acceptance. One test process, small synthetic data, no model calls. Changes to the outcome/protected ownership escalate to root; unresolved material reasoning goes to Astra.

Acceptance: correct approved organization/cost/target; explicit initial migration and safe rerun; exact source bytes; security/permission inventory and deny-by-default probes; no API-role access to private tables/functions; advisors reviewed; TLS/connection mode and client verification reported separately without overstating plugin evidence. Runtime positive scoped policies remain later work. No task is marked complete while required live checks remain missing.


V1-01-H handoff: local security preparation and final integration passed. A delivered deployment/supabase.sql and tests/security.sql and assembled B's docs/supabase.md; peers resolved default-privilege and role-probe boundaries directly and stopped writing. Root added common libpq credential-file ignores, this handoff, development notes and evaluation/reports/V1/V1-01-H.md. Initial migration bytes, native source/locks and sealed corpus are unchanged. Actual checks: temporary PostgreSQL 17.11 migration/security harness passed, including unsafe-grant detection/removal/rerun, nine-table RLS, populated nonowner denial, complete probe rollback, owner/admin-attribute/RLS regression detection and unrelated-schema preservation; 17 focused tests and 16 sealed hashes passed. No persistent task processes remain. Headroom before run: 21 GiB available disk and 41% memory free; no installs/Docker/models.

Hosted configuration is WAITING_FOR_ORGANIZATION_CHOICE. Plugin tools explicitly require choosing the organization before cost/provisioning; root asked whether to use vsuman00's Org and Mumbai. No answer, cost quote, project creation, hosted SQL or advisors yet. Root opened an authenticated dashboard session for unsupported settings; no project setting was changed. Native TLS/CA/connection-mode and runtime permissions remain unverified. Parent V1-01 stays unchecked/IMPLEMENTED_UNVALIDATED; V1-02 has not started. Next: receive the organization choice, quote actual cost, obtain approval for any nonzero cost, provision dedicated target and perform hosted security/configuration checks. Learning remains pending.

Final preparation checks: four prose files/104 local links passed, no deterministic text changes, initial migration preserved, common libpq credential-file ignores verified and whitespace clean. The locally verified security preparation follows the authorized commit/push workflow; hosted state remains pending the organization choice.


## V1-01-H hosted execution: 20 October 2026

The user created the dedicated Cragkit project. Root discovered and verified project `ksvzlzklspfghrhirogt`, name Cragkit, region ap-southeast-1 (Singapore), in the existing organization, ACTIVE_HEALTHY, PostgreSQL17.11/UTF8. This supersedes the proposed new Mumbai project; no provisioning/cost action is needed from root. Read-only preflight returned no public/cragkit application tables, no cragkit schema and no recorded Supabase migrations. Server SSL is enabled and the plugin SQL session uses SSL. Native client verification remains separate and unconfigured.

Shared outcome H-r2: securely configure the user-created dedicated target, apply immutable initial migration and private-schema hardening, execute hosted relational/security probes, review advisors and record platform/client TLS evidence accurately. No new project, cost approval, unrelated project changes, new auth flow or V1-02 adapter work.

- H-r2-A: `/root/coordinate_peer`, Sol `gpt-6.1-sol`, owns docs/supabase.md and is assembler. Update the secure runbook with verified target/setup and explicit remaining native-client limitations; review root's plugin migration transaction/ledger method.
- H-r2-B: `/root/manager_peer`, Sol `gpt-6.1-sol`, owns evaluation/reports/V1/V1-01-H-hosted.md. Independently audit hosted security evidence and advisor findings supplied by root, prepare scoped acceptance/limitations and coordinate claims directly with A.
- Root owns every remote/UI/credential operation, SQL/tool artifacts, tracker, development/status docs and Git. Existing migration/deployment/probe files retain frozen revisions; one remote writer and one test process. No peer hosted calls, services, credentials, installs or Git. Root sends actual results to both; peers resolve dependencies directly, report material changes and escalate unresolved reasoning to root/Astra. Root performs final checks and tracker completion. State: running.

H-r2 corrective child V1-01-C approved: hosted advisor found one actionable unsupported_reg_types warning for stored regconfig and four unindexed-FK notices. A/B agreed a plain-text config name resolved with explicit ::regconfig at use, preserving the fixed pg_catalog search path and all lexical semantics. A now solely owns new storage/postgres/migrations/0002_portable_lexical_config.sql and storage/postgres/tests/invariants.sql in addition to its runbook; B remains sole hosted-report owner and has stopped SQL writing. Add three covering indexes for parent chunks, active document generations and job generations (the last covers the document prefix too). Preserve 0001 bytes, no new policies/global grants/public API change. Root verifies locally before hosted application and reruns hosted probes/advisors. Initial/hardening/guarded-rerun and hosted integrity/security probes passed; core ledger initial checksum/timestamp remained unchanged. Dashboard TLS enforcement enabled and visibly verified after its restart; native credentials remain unconfigured.


H-r2 integration handoff: both hosted migrations and hardening passed; the first empty-target API rollback probe failed deliberately and left no schema/table/audit entry. Initial/rerun, both version checksums/timestamps, updated relational/integrity/configuration and security probes passed. All eight application tables remain empty and temporary role/schema are absent. Supabase migration audit records are separate from the two-row Cragkit checksum ledger. V1-01-C resolved the unsupported regconfig warning with plain-text configuration names and three missing-FK covering indexes; populated local upgrade preserved vectors and the initial ledger. A owned 0002/invariants/runbook, B owned hosted evidence, communicated directly and assembled under A; root inspected and ran final checks.

Actual final security state: 9 RLS tables, no row policies (deny by default), no API-role private schema/object access, mandatory database TLS enabled and Data API disabled. Final advisors: 9 intended RLS INFO and 2 unused-GIN INFO, no WARN/ERROR; no permissive policies/index removals to silence notices. Native direct TLS1.3 required-CA/hostname verification passed and plaintext startup without password was rejected with SQLSTATE 28000; pooler CA verification failed and was not downgraded. Direct CA/nonsecret env prepared outside Git with owner-only files; private pgpass is pending. The user selected the private-save option and will reply saved; this is intent, not a successful native login.

Final regression checks rerun: 172 Python/tool tests, TypeScript build/78 tests and 16 sealed hashes passed. Temporary local PostgreSQL cluster stopped/removed; no tools/models/optional drivers installed. Native source/contracts/locks and 0001 bytes preserved. E65/E66 added for upgrade/catalog-OID and TLS failure regressions. Docs updated for actual target/configuration. Parent V1-01 remains IMPLEMENTED_UNVALIDATED and V1-02 has not started. Next: after user saves privately, run authenticated native --check/--integration, then close acceptance and choose V1-02. Learning remains pending.

Final review: ten changed prose files and 160 local links/anchors passed; deterministic prose cleanup made no changes. Whitespace and scoped credential-pattern checks passed. Both migration hashes match the hosted ledger, and 0001 remains byte-identical to the prior commit. No task-owned PostgreSQL process remains. The twelve-path change is ready for the authorized commit/push; the private password file is still absent, so authenticated native acceptance remains pending.

Native authentication follow-up, 20 October: the user confirmed saving the credential. Root verified the private password file exists, has the current owner and mode 0600; its contents were not displayed. The authenticated native --check/--integration command failed with database_check_failed. A bounded psql diagnostic classified password authentication failure, with no certificate/network error. No migration-history/integration assertion ran through that failed connection. V1-01 remains IMPLEMENTED_UNVALIDATED and V1-02 remains unstarted. Root alone handled this sequential credential-dependent check; no independent implementation lanes were needed.

Root added an explicit --replace option to the ignored workspace-only password helper, checked its help output, and asked the user to enter the correct project database password privately. The existing password file was preserved. No database password reset, hosted setting/schema change, product-source edit, package install, service startup or product-test rerun occurred. Prior regression evidence remains scoped to the preceding commit. Next: after the user replaces the local credential and replies saved, retry authenticated native verification; do not weaken TLS or advance the dependency gate. Learning remains pending; this failure illustrates that verified transport and database authentication are separate checks.

Second private-save follow-up: root verified the private file was updated after the preceding failure note, with owner/mode unchanged. Direct native verification now encounters connection refused before login; DNS is IPv6-only and the plugin reports ACTIVE_HEALTHY. Root checked the dashboard-identified session pooler: the system CA bundle was rejected, but OpenSSL and native libpq accepted the downloaded Supabase CA; libpq verify-full reached password authentication failure. No authenticated integration checks passed. The temporary owner-only pooler credential file was removed; original private file and direct configuration remain unchanged. Root stopped retries and requested correction or a user-managed database password reset followed by the hidden --replace prompt. No database password reset, schema/settings change, product edit/test rerun, install or service occurred. V1-01 remains IMPLEMENTED_UNVALIDATED. Next: receive a corrected private save, verify native login/history/invariants, then close V1-01 before starting V1-02. Learning remains pending.

Third private-save follow-up: the private file was updated again with owner/mode preserved, but verified session-pooler login still rejects authentication and the direct runner fails. Root verified the actual dashboard connection parameters match the tested endpoint/user and observed mandatory SSL still enabled. One temporary network ban is present; its address was not recorded and has not been identified as the current client. This may explain direct refusal, not the separate pooler password rejection. Root stopped retries and left Database Settings open, asking the user to unban only their recognized network address or report that it is unrecognized. No unban, password reset, schema/settings change, source edit, product test, install or service was performed. Temporary pooler credential material was removed. V1-01 remains IMPLEMENTED_UNVALIDATED; V1-02 is unstarted. Next: resolve the observed network ban with the user, then perform one bounded native login/history/invariant check. Learning remains pending; transport reachability and credential validity are distinct failure stages.

Unban follow-up: the user reported removing their network ban. One subsequent direct native check still failed. A fresh, fully loaded dashboard still lists an Unban IP control; root cannot distinguish unsuccessful removal from a new ban and has stopped connection attempts. No ban was removed by root. The user was asked to clarify whether the project database password was actually reset in the dashboard before the local save. Next action depends on that answer; V1-01 remains incomplete. No new product tests, services, installs or schema/settings writes occurred; temporary credential files were cleaned up and no credential values or client addresses were recorded.

V1-01-D diagnostic assignment: the user explicitly confirms the project database password was reset. Shared outcome D-r1 is to distinguish a local credential/runner defect from provider cache, ban or configuration behavior without another reset request or repeated login attempts. A, /root/coordinate_peer (Sol gpt-6.1-sol), audits the public helper/runner and sanitized evidence, and assembles both reviews. B, /root/manager_peer (Sol gpt-6.1-sol), researches current official reset/pooler/network-ban behavior and reviews A's conclusions directly. Both lanes are read-only: initial writable paths are none; no private credential access, hosted project calls, tests, installs, services or Git. Root alone owns provider diagnostics, credentials, all files/tracker and final verification. Peers message each other about concrete dependencies and escalate unresolved material reasoning through root to Astra; protected boundaries and task outcome remain unchanged. Acceptance: a scoped supported diagnosis or a precise remaining uncertainty, followed only by a justified bounded verification. State: running.

Final V1-01-D and parent acceptance: COMPLETE. Both Sol peers contributed substantive findings and communicated directly: A found the public helper's escaping/input checks sound; B identified current official Supabase guidance that a correct rotated password may be rejected by the shared pooler's cache. Root verified that the temporary pooler conversion preserved escaped password bytes and left no temporary credential files. Peers hit a usage limit before final assembly, so root assembled and checked the evidence. No Astra escalation was needed. Earlier claims that pooler failure proved an incorrect reset/password were too strong; cache involvement remains plausible, not proven.

The user explicitly approved root removing only the listed ban for their recognized network address and checking once. Root completed Unban IP and its separate Confirm Unban action, then observed the success notice and no banned addresses. One direct native libpq session with the existing private password file, dashboard CA and verify-full passed the canonical migration-history script, integration invariants and security probes. Actual markers: cragkit_migration_ok and cragkit_security_probe_ok; administrative postgres, SSL true, TLS 1.3 and two schema versions. No migrations, password resets or TLS downgrade were performed. Synthetic fixtures/temporary role rolled back; no raw IP or credential was recorded. The ignored result is artifacts/V1/native-direct-after-unban.json. The successful harness used the existing runner functions in one process; the multi-connection CLI was not rerun after that acceptance.

Changed this closure: current status/evidence in README, runbook, development guide, storage README, master/version plan, hosted report, E67 and this tracker. No package source, migration, contract, dependency or sealed-input changes. No product-suite rerun, installation, local service or live model; prior 172 Python/tool, 78 TypeScript and 16 sealed-hash results remain scoped to their original checkpoint. Learning remains pending; failure example: pooler credential caching plus a direct network ban can look like an incorrect new password. Next smallest action: V1-02 Python connection lifecycle, with owned versus borrowed pool closure, bounded acquisition/statements and request-scope reset tests.

Closure review: nine changed prose files and 156 local links/anchors passed, deterministic cleanup made no changes, whitespace and credential/address-pattern checks passed. Both migration hashes still match the hosted ledger. No task-owned local server or temporary pooler credential remains; native clients exited. The accepted documentation/configuration checkpoint follows the standing scoped commit and immediate-push workflow.

## V1-02A: Optional Python pool resources

Shared outcome A-r1: an internal optional PostgreSQL pool resource layer with secure scalar configuration, explicit owned startup, borrowed-pool preservation, bounded startup/acquisition, cancellation-safe lease return and idempotent bounded close. Example: closing a Cragkit-owned resource closes its driver pool; closing a borrowed resource leaves the caller's pool open. This child does not authorize retrieval, validate schema/capabilities or bind tenant scope; those remain V1-02B and parent completion stays unchecked.

Initial ownership: /root/coordinate_peer, Sol gpt-6.1-sol, owns packages/python/src/cragkit/_postgres_pool.py and is assembler; /root/manager_peer, Sol gpt-6.1-sol, owns packages/python/tests/test_postgres_pool.py. Both agree the bounded internal interface directly before dependent edits. Root owns tracker/docs/report, optional dependency environment, hosted checks and final integration/Git. Native public contracts, top-level imports, manifests/locks, migrations, TypeScript and corpus are read-only. No peer installs/tests/hosted calls/credentials/services/Git. If Sol remains unavailable due to its reported usage limit, root takes sole ownership rather than substituting a model. Acceptance: deterministic ownership/deadline/saturation/cancellation/closure/import tests, strict typing, optional-driver actual API verification and one small hosted administrative resource smoke test. One test process, at most two DB connections, no permanent runtime-role changes. Headroom: 19 GiB disk and 41% system-wide memory free. Installed the existing frozen postgres extra (psycopg 3.3.6, binary 3.3.6, pool 3.3.3) from cache; no manifest/lock change.

V1-02A handoff: COMPLETE. Both Sol peers were available, froze A-r1 directly and implemented disjoint source/tests. A assembled and both explicitly transferred ownership to root before final edits/staging. Review corrected duplicate driver close after failed startup, close/startup races, silent close failures and a doubled close budget. Root's first focused run found an import-test harness issue: asyncio's socketpair setup was being audited as module I/O. B moved loop setup before the unchanged audit guard. Root later added a post-acquisition deadline recheck and two late-return regressions after ownership transfer; E68 records that failure. No unresolved material decision required Astra.

Actual final checks: 27 focused cases, 199 Python/tool cases, strict mypy on seven source files and all 16 sealed hashes passed. Default frozen sync removed the three optional driver packages, and the full tests/typecheck passed without them. Root's ignored hosted harness was rerun on the final source and passed direct verify-full/TLS 1.3 owned reuse, saturation/deadline/cancellation, owned active-lease shutdown and repeated close, borrowed caller-pool preservation and an unrelated caller lease remaining usable. All task-owned native resources closed; no schema, role, policy or application data was changed. Only fixed synthetic SELECTs and explicit caller transactions were used, with at most two client connections and no local server/model/install beyond the cached extra.

Changed files: internal module, focused tests, V1-02A evidence, development guide, README, E68, version-plan child split and this tracker. Public core exports/contracts, manifests/locks, migrations, TypeScript and approved corpus are unchanged. No TypeScript suite, package artifact pipeline, hosted CI, runtime-role acceptance or live-model evaluation occurred. Lease deadlines currently bound acquisition only; body/statement budgets, transactions, schema and scope remain V1-02B. Borrowed pools are not reconfigured/security-validated, and wrapper limits do not constrain unrelated caller work. Learning remains pending. Failure example: closing a borrowed pool would interrupt unrelated application requests; native verification proved that pool and its unrelated lease stayed usable. Optional exercise: explain why closing a wrapper blocks its new leases while leaving the caller's driver open. Next smallest action: V1-02B; V1-03 remains gated on the full V1-02 parent.

Final integration review: six prose files and 123 local links/anchors passed with zero deterministic cleanup changes. Whitespace, scoped credential/address-pattern checks, protected-file byte comparisons and artifact ignore checks passed. The default environment has no optional PostgreSQL driver installed after the final frozen sync. Both workers stopped writing and all task-owned native clients closed. The eight-file child follows the authorized focused commit and immediate-push workflow.

## V1-02B: Complete Python connection lifecycle

State: COMPLETE after final integration. Outcome B-r1: complete parent V1-02 with explicit schema/capability validation, a nonowner runtime role, parameterized required filters, separately bound trusted scope, transaction-local settings and shared statement deadlines. No retrieval ranking, ingestion, permanent broad policies or contract/migration changes are authorized by this child.

Assignments: root coordinates, integrates, owns tracker/docs/shared files, database setup, serialized checks and Git. Sol coordinate_peer owns `packages/python/src/cragkit/_postgres_session.py` and optional `_postgres_filters.py` and assembles the pair. Sol manager_peer owns `packages/python/tests/test_postgres_session.py` and `tools/check_python_postgres.py`. Peers agree their API directly against the existing contracts and immutable migrations; they report ownership transfers or plan changes before dependent edits. Both contribute substantive code. Root escalates unresolved material reasoning to Astra. Protected files: shared contracts, errors, pool layer, migrations, locks and TypeScript. Any needed pool correction returns to root. One test process, at most two database connections, synthetic fixtures only, no model calls or services. Acceptance: success and incompatible schema, unsafe role, parameter safety, scope reuse/reset across tenants, bounded acquisition/statements/cancellation, owned/borrowed lifecycle and actual runtime-login integration, followed by strict typing/default import checks. Final results are recorded in the handoff below.


V1-02B final handoff: COMPLETE; parent V1-02 is now COMPLETE and V1-03 is READY. Both Sol peers implemented their disjoint files and coordinated the identifier-only API directly; A assembled, both stopped writing and transferred ownership to root. Root inspected all artifacts, corrected protected pool huge-integer deadline validation, replaced hosted-incompatible DROP OWNED cleanup with exact revokes, and added the driver-IDLE rollback postcondition/regression. No unresolved material reasoning required Astra. E69-E71 record the new failure cases.

Actual final checks: 66 focused pool/session cases passed with the optional extra; 238 Python/tool cases and strict mypy across nine source files passed after frozen default sync removed all three optional driver packages; 16 sealed hashes matched. A fresh native A owned/borrowed lifecycle run passed with TLS 1.3. The committed native B harness passed on final source using an actual nonowner LOGIN role, observed lock waits before deadline/cancellation, distinct tenant results on the same physical connection, unscoped RLS denial, principal/grant/stale-revision/injection checks, unsafe-admin rejection and schema restoration. Cleanup verified all eight application tables empty, no fixture policies/roles and no runtime connections. Final one-session canonical migration-history/invariants/security scripts passed and rolled back their probes. Advisors: nine INFO no-policy findings and two INFO unused lexical indexes, no WARN/ERROR. Initial failed cleanup was repaired and verified; one intermediate safe ProviderUnavailable was not reproduced by traced and canonical runs, and its cause remains unproven.

Changed paths: Python internal pool/session/filter modules, focused session tests, explicit tools/check_python_postgres.py harness, V1-02B evidence, development/runbook/README/version-plan status, E69-E71 and this tracker. Source/filter capabilities remain internal and identifier-only; no ranked retrieval or source release is implemented. Borrowed transport configuration belongs to the caller. Permanent database policies/login credentials were not provisioned. Contracts, migrations, dependency locks, TypeScript and approved corpus bytes are unchanged. No TypeScript suite, artifact pipeline, hosted CI or live-model evaluation occurred. Resource headroom before work: 19 GiB disk and 47% system memory free. At most two native client connections, one test process and no task-owned persistent services; all test clients/pools closed. Learning remains pending; exercise: explain how trusted scope, fixed predicates and transaction-local context serve different purposes. Next smallest action: V1-03 native TypeScript lifecycle using the same fixture semantics and scoped failure cases. Version-control publication follows the standing scoped commit/immediate-push policy.

## V1 continuation: V1-03 native TypeScript lifecycle

State: RUNNING. User requested completing this phase; V1 remains the outcome, delivered in dependency order with acceptance at each task/checkpoint. Current task V1-03-r1 mirrors Python's bounded pool/session and identifier-filter contract in native Node with AbortSignal propagation. Sol coordinate_peer owns `packages/typescript/src/postgres-pool.ts` and `postgres-session.ts` and assembles; Sol manager_peer owns `packages/typescript/tests/postgres.test.mjs` and `tools/check_typescript_postgres.mjs`. Root owns tracker/docs, manifests/locks/exports, shared fixture harness adaptations, final verification, database writes and Git. Peers coordinate their API directly and escalate outcome/protected-boundary changes to root; unresolved material reasoning goes to Astra. Protected: public wire contracts, immutable migrations, approved corpus and unrelated source. One test process, at most two native DB connections, no models/services. Acceptance includes optional import isolation, strict typing, real runtime-role Node scope/filter/reset/schema/deadline/abort fixtures, owned/borrowed lifecycle and Python-compatible errors. Completion remains pending final checks. After V1-03, run V1-C1 before V1-04.


V1-03/V1-C1 handoff: COMPLETE. Sol A assembled two native Node source modules, Sol B authored focused tests and child native harness; peers resolved API/driver dependencies directly. Both stopped and transferred files to root. Root verified 58 focused/136 full Node cases, TypeScript build/typecheck, 238 Python/tool cases with default optional drivers removed, strict Python typing, 66 shared cases/four schemas/16 sealed hashes and six normalized SQL constants. Final actual hosted Node run passed runtime LOGIN/TLS, unscoped RLS denial, distinct tenant same-PID scope reuse/principal/grant/revision/filter checks, real borrowed-pool survival, queued abort, observed lock waits then deadline/abort, reset/reuse, schema restoration and admin rejection. Fixture owner verified cleanup. Native clients closed; no task-owned services. Headroom before work: 18 GiB disk/54% free memory. Limitations: internal identifier probe only, borrowed TLS caller-owned, no ingestion/ranking/source release yet; no hosted CI/model/artifact publication. E19/E23/E24/E47/E68-E71 exercised in Node with scoped claims. Learning remains pending. Next: V1-04; user requested continuing through V1 in dependency order.

## V1-04: Canonical text and source spans

State: COMPLETE after final integration. Outcome C-r1: identical bounded text/Markdown normalization and structural UTF-8 chunk spans in native Python/TypeScript, with exact digests and deterministic IDs. Sol coordinate_peer owns Python `canonical.py` and `test_canonical.py`, and assembles; Sol manager_peer owns TypeScript `canonical.ts` and `canonical.test.mjs`. Root owns shared `contracts/fixtures/canonical.json`, public contract decisions, tracker/docs/Git and serialized verification. Wire schemas, approved corpus and migrations remain protected. Peers freeze semantics directly before edits, report ownership/outcome changes and unresolved issues to root/Astra. No database/model/service is needed. Acceptance: shared Unicode/CRLF/BOM/Markdown/code fixtures, exact byte reconstruction and digests, unsupported/oversized/malformed input rejection, bounded chunk count, optional declared token counter limits, both strict typechecks and native parity. Work follows completed V1-03/V1-C1 acceptance; its Git publication is owned by root separately.


V1-04 handoff: COMPLETE. Sol Python/TypeScript peers owned separate source/tests, froze C-r1 directly, assembled and transferred all files to root. Root owns shared23fixture oracle and corrected token-call ordering/byte packer and malformed async-counter cleanup. Final focused checks: 52 Python cases, strict typing ten files; 72 Node cases and strict typecheck/build. Shared fixtures preserve source/canonical hashes, profiles, IDs, byte spans and flags; 200 additional deterministic native comparisons matched. No DB/model/services/install, migration, wire-schema or sealed-corpus changes. Resource usage remained small fixtures/one test process. Learning remains pending. Next: V1-05; V1 remains in progress.

## V1-05: Python staged ingestion

State: RUNNING. Outcome I-r1: bounded explicit Python text ingestion writes immutable revisions/chunks/native FTS and publishes one ready generation atomically; same intent/payload replays, changed payload conflicts, interrupted work preserves the prior active generation. Sol coordinate_peer owns packages/python/src/cragkit/ingestion.py and assembles. Sol manager_peer owns packages/python/tests/test_ingestion.py and tools/check_ingestion.py. Root owns the shared native fixture bridge tools/check_python_postgres.py, any shared ingestion fixtures, docs/tracker/Git and all database execution. Native contracts/schema/corpus and completed canonical modules are read-only. Peers agree receipt/hash/ingestion API directly, escalate material scope/ownership changes to root/Astra, and stop before transfers. One serialized test process, at most two database connections, synthetic empty-target fixture only, no providers/models/services. Actual nonowner writer-role RLS, idempotency/conflict, pre-publication failure/rollback, scoped keys and digest/count checks are required before V1-06.


V1-05 handoff: COMPLETE. Both Sol peers reached their usage limit after writing drafts; root confirmed inactive writers and reclaimed their paths. Root integrated mandatory bound write authorization, adapter-safe input checks, stable TLV metadata identity, transaction disposal/error corrections and test-double state repairs. Actual final checks: 37 focused/327 combined Python-tool cases; strict mypy 11 source files; 16 sealed hashes; eight actual hosted ingestion groups including denied same-tenant principal, replay/conflict, Unicode/FTS, tenant isolation, rollback, CAS and cancellation/reuse. Fixture cleanup and an independent plugin query passed. Default frozen sync removed optional drivers. Changed files and exact commands/limitations are in V1-05 evidence. No migration/wire/lock/approved-corpus/TypeScript changes, services or models. Disk headroom 20 GiB; max two native clients and one test process. Untracked SECURITY-EVALUATION.md remains user/external-owned and excluded from commits; its SQLSTATE classification finding is an explicit adapter hardening follow-up. Lost COMMIT acknowledgements remain ambiguous until same-intent retry; no process-kill or simultaneous-two-transaction recovery claim. Learning pending. Next smallest action: V1-06 native TypeScript ingestion parity; V1 remains in progress.


## V1-06: Native TypeScript ingestion parity

State: RUNNING. Outcome I-r2 preserves the accepted Python write-authorizer/hash/receipt/publication semantics in native Node, with cross-runtime reads and retries on the dedicated hosted fixture. Sol peers remain unavailable after their reported usage limit; root is the sole writer and final integrator under the project skill fallback. Writable paths: TypeScript ingestion module/tests, new native child helper, existing Python native fixture/helper for serialized cross-runtime verification, shared ingestion fixture only if independent oracle additions are needed, docs/tracker/Git. Read-only: Python accepted ingestion/canonical sources, wire contracts, migrations, dependency locks and approved corpus. No replacement model, provider/model/services or registry publication. One test process, max two native clients. Acceptance: exact shared metadata/identifier parity, both runtime write/read directions, intent conflict/replay, bounded AbortSignal/deadline cleanup, strict typing and full checkpoint regressions.

V1-06 integration scope refinement: 06A owns native source/tests and shared identifier fixtures; 06B owns the serialized hosted child/bridge; C2 owns combined regression evidence/docs. Root remains their single writer. Review found an accepted Python publication gap: a policy could make the staging-to-ready UPDATE return no rows. Root authorizes the minimal matching Python/TypeScript correction and regressions before accepting parity; a missing ready barrier must roll back, not advance the active pointer. This correction preserves wire/schema/hash contracts.


V1-06/V1-C2 handoff: COMPLETE. Root integrated native Node ingestion, 58 Node/39 Python focused checks and eight independent full-identifier fixtures alongside the metadata oracle. A missing ready-transition row now fails both runtimes before active publication; real restrictive RLS confirms rollback. The added DDL test initially fetched nonexistent result rows, leaving its temporary policy and preventing cleanup. Root removed only its exact failed fixture, corrected command handling and parent cleanup, then reran all 14 hosted groups successfully. Both runtime write/read/replay directions matched. Independent plugin checks: zero fixture roles/policies/connections/documents/collections; security advisor only nine expected INFO no-policy findings. Final default driver-absent Python 329 cases/mypy 11 files, Node 266 cases/build/typecheck, 66 wire cases/four schemas/16 sealed hashes passed. Runtime pools/child processes closed, max two native clients, no services/models/publication. Headroom 20 GiB disk/49% memory free. Sol peers remained unavailable; root was sole writer, no replacement model or unverified review. Untracked SECURITY-EVALUATION.md excluded. Detailed changed paths, commands and limitations are in V1-06 evidence. Learning pending. Next: V1-H1 adapter SQLSTATE/NUL hardening identified during security review, then V1-07. V1 remains in progress.


## V1-H1: PostgreSQL adapter input and error hardening

State: RUNNING. Root is the sole writer; Sol peers remain unavailable. Outcome: backend-specific NUL input fails before leasing, and SQLSTATE class 23 failures remain typed integrity errors rather than provider outages. H1A owns Python session/filter sources and session/ingestion tests; H1B owns TypeScript session/ingestion sources and their tests. Shared public wire validators/schemas, accepted metadata hashes, migrations, manifests/locks and corpus are read-only. Root owns docs, serialized verification and Git. This bounded follow-up resolves concrete findings in the preserved external security evaluation; its other claims are not accepted as verification. Acceptance: NUL in scope/collection/query/identifier filters rejected without SQL, redacted class-23 errors through both read/write adapters, default-driver-absent regression/typechecks, unchanged wire/seal checks. No database changes or new service/model is needed.


V1-H1 handoff: COMPLETE. Root's H1A/H1B changes reject PostgreSQL-specific NUL text before SQL and map class-23 constraints to redacted IntegrityViolation in both native read/write adapters. Focused checks: 97 Python/135 Node cases. Full regressions: 348 Python-tool/285 Node cases, strict mypy 11 files and Node typecheck/build, 66 wire parity cases and 16 sealed hashes passed. First mypy narrowing failure was fixed and rerun successfully. Default Python remains driver-absent; no hosted DB/service/model/install or migration/wire/corpus changes. Eight implementation/test paths changed across the two bounded children; root owns docs/Git. Sol peers remain unavailable; no substitution or unverified agent review. External SECURITY-EVALUATION.md remains untracked and preserved. Detailed commands/scope are in V1-H1 evidence. Learning pending. Next: V1-07; V1 remains in progress.


## V1-07: Scoped lexical candidates

State: RUNNING. Root is sole writer/integrator while Sol peers remain unavailable. Outcome L-r1: native FTS candidate identifiers and scores from active ready generations, exact tenant/principal/revision/tombstone predicates and supported required filters before LIMIT, with stable ties. 07A owns both session modules and focused tests; 07B owns serialized native fixture/helper adaptations. Root owns docs, tracker/Git and shared SQL review. Migrations, public request/result schemas, approved corpus and locks remain read-only. One test process, max two native clients; no models/services. Acceptance: two-tenant identical source, grant/revision/tombstone/required-filter exclusions, deterministic ties and limit, real read-only runtime-role queries in both runtimes, bounded deadline/abort and regression/typechecks. Candidate identifiers are not released excerpts; source-backed typed result assembly remains V1-08.


V1-07 handoff: COMPLETE. Root's 07A/07B changes add native scoped FTS candidates, shared logical SQL, strict immutable candidate boundaries and explicit hosted lexical helpers. Final evidence: 62 Python/87 Node focused cases; 357 Python-tool/300 full Node cases, both strict typechecks/build, 66 wire cases/four schemas/16 sealed hashes, normalized lexical SQL parity and 19 hosted groups passed. Actual read-only LOGIN tests cover identical two-tenant text, stable ties, filter-before-limit with the second tied document, principal/revision/filter exclusions, tombstones and unready generations, and Python/Node exact candidate parity. An EXPLAIN Limit node was inspected without a performance claim. Initial Node native offset rejection exposed bigint string parsing; exact safe-integer conversion and six regressions fixed it, cleanup passed, and full native acceptance was rerun. Final default Python is driver-absent; independent plugin query confirms zero roles/policies/connections/documents/collections. No migrations/wire/lock/corpus/model/service/registry changes. Sol peers remain unavailable; root sole writer/integrator. Resource limits/headroom and changed paths are in V1-07 evidence. External security evaluation remains untracked. Learning pending. Candidates contain IDs/offsets/rank, not verified source excerpts. Next: V1-08. V1 remains in progress.

## V1-08: Authorized source spans and typed result assembly

Initial assignment (completed below). Outcome E-r1 is frozen in contracts/RETRIEVAL_V1.md: verify full canonical digest/exact UTF-8 spans under fresh scoped source authorization, then emit conservative partial/insufficient typed results with explicit estimated context bounds. V1-07 is complete. Both Sol peers confirmed availability and read governing files; root applies coordinate/manager skills. V1-08A coordinate_peer (Python, assembler) owns Python session, optional _postgres_source.py, retrieval.py and new retrieval tests. V1-08B manager_peer owns corresponding Node session/optional postgres-source.ts/retrieval.ts/new tests. Root owns shared source/result fixtures, runtime spec, native hosted helpers/bridge (08C), all execution, docs/tracker/Git and final integration. Peers coordinate directly and escalate shared/outcome/other-lane boundaries; root asks Astra only for unresolved material reasoning. No concurrent shared edits or test processes. Protected: public wire validators/schemas, migrations, manifests/locks, approved corpus and external untracked security evaluation. Root alone runs one test process and at most two native clients; no models/services. Acceptance includes both native languages, exact shared parity, Unicode source integrity, unknown coverage, unsupported strict mode, bounded packing/source reads, actual runtime-role corruption/no-match tests and verified cleanup. Worker completion is not final acceptance.


V1-08 handoff: COMPLETE. Sol Python/Node peers implemented independent native source verifiers, scoped fetch methods, retrievers and tests against root E-r1; they coordinated directly, Python assembled, and both stopped/transferred ownership. Root inspected and integrated 39 shared source/result cases, Node byte-budget snapshots/accessor/buffer guards, extra Unicode/BOM/import regressions, deadlines from call entry and native helpers. Final actual checks: 50 Python/63 Node focused cases, 407 Python/tool/363 Node full cases, strict mypy across 13 files and Node typecheck/build, 66 wire cases/four schemas/16 sealed hashes, normalized source SQL parity and 24 hosted groups passed. Both runtime logins returned exact typed results, enforced direct source principal denial and refused stored span corruption. Trigger state and valid span restored; independent plugin check reports zero roles/policies/connections/documents/collections and enabled span trigger. Nine INFO default-deny advisor findings, no WARN/ERROR. Default Python is driver-absent; all task-owned pools/children closed. No migration/wire/lock/corpus/model/service/publication changes; external security evaluation remains untracked. Headroom: 18 GiB disk / 44% memory free. Detailed changed areas, commands/limits and child split are in V1-08 evidence. Semantic coverage remains unknown; context counting estimated; lifecycle/final source-release races retain their tasks. Learning pending. Next: V1-09. V1 remains in progress.

## V1-09: Revision publication and deletion

Initial assignment: RUNNING. Shared outcome L-r1 in contracts/LIFECYCLE_V1.md: preserve CAS publication, add caller-authorized tombstone and explicit purge with a minimal deletion barrier. Caller controls retention; no automatic expiry. 09A coordinate_peer (existing gpt-6.1-sol, Python assembler) owns Python lifecycle.py/test_lifecycle.py and only necessary generic transaction reuse in ingestion.py. 09B manager_peer (existing gpt-6.1-sol) owns corresponding Node lifecycle.ts/lifecycle.test.mjs and ingestion.ts helper extraction. Root owns shared contract/fixtures, native helpers (09C), all executions, docs/tracker/Git and final integration. Peers resolve concrete dependencies directly; outcome/protected/other-lane ownership changes escalate before editing, unresolved material reasoning goes to Astra via root. Migrations, manifests/locks, public schemas, approved corpus and external SECURITY-EVALUATION.md are protected. One test process, at most two native clients, no models/services. Acceptance: controlled stale update CAS race, interruption rollback, tombstone retrieval exclusion, source/index purge including hidden child rows, unavailable historical citations, exact runtime parity and cleanup. Headroom: 21 GiB disk, 70% system memory free. Learning pending; worker reports are not final acceptance.


V1-09 handoff: COMPLETE, including V1-C3. Both Sol peers delivered their owned native lifecycle/test files and generic ingestion transaction helper, coordinated directly and transferred ownership; Python assembled and root verified. Root owns L-r1/shared 11-case fixture, native helpers/CLI, docs/tracker/Git. Actual final checks: 72 Python/108 Node focused cases, 435 Python/tool/408 Node regressions, strict mypy 14 files and Node typecheck/build, 66 wire cases/four schemas/16 sealed hashes, exact catalog SQL parity and 30 hosted groups passed. Two initial native failures were localized to missing column UPDATE privilege for FOR UPDATE; root added minimum UPDATE(created_at) with explicit revoke, fixed Node query-config use and required actual marker-statement observation. Final real-login probes cover late CAS rejection, interrupted publication rollback, immutable stale historical source, tombstone exclusion, rejected reinsertion restoring the graph, hidden-child cascade purge, minimal marker timestamps, unavailable citations and blocked resurrection. Cleanup verified independently: zero fixture roles/policies/connections/documents/collections, enabled span trigger; nine INFO default-deny advisor findings, no WARN/ERROR. Caller-controlled retention has no automatic expiry; external backup/log/cache erasure remains caller-owned. Default Python is driver-absent; all task-owned pools/children ended. Migrations/manifests/locks/wire schemas/approved corpus unchanged; external security report preserved untracked. Resource start: 21 GiB disk / 70% memory free; one test process, max two native clients, no model/service/publication. Learning pending. Next: V1-10 final authorization races. V1 remains in progress.

## V1 final handoff: 22 October 2026

V1-10, V1-11, V1-12, V1-C4 and V1-EXIT: COMPLETE. Primary owns final integration, public PostgreSQL entry points, direct examples, hosted/checker extensions, evidence, development instructions, tracker and Git. Required Sol/Astra models were unavailable; no substitute peer models were spawned. Existing runtime implementations met the new real-database probes without changing shared schemas, migrations or lockfiles. Acceptance: 435 Python/tool and 408 Node tests, strict mypy 15 files, TypeScript typecheck/build, 66 wire cases, four schemas, 16 sealed hashes, 15 artifact-checker cases, both actual retriever cancellation suites, 28 installed result/example groups and 32 full hosted lifecycle groups passed. Independent cleanup query found zero probe roles/policies/connections/documents/collections and an enabled span trigger; advisor findings were nine INFO default-deny notices with no WARN/ERROR. Changed paths: native public postgres modules, TypeScript package export, examples/postgres.py and postgres.mjs, tools/check_artifacts.py, tools/check_python_postgres.py, tools/check_retrieval.py, both native Node helpers, artifact checker tests and linked documentation. One test process and at most two database clients at a time; no model calls or persistent services. Final resource snapshot: 27 GiB disk available, 61 percent memory free. User learning practice pending. Unrelated SECURITY-EVALUATION.md preserved untracked. Next smallest task: V2-01 embedding profile decision; no V2 provider/cost choice has been inferred. [Final evidence and commands](../evaluation/reports/V1/V1-10-12.md).


## BRD-01: Business requirements document

State: COMPLETE (documentation only). User requested a BRD aligned with the existing architecture and plans. Root was sole writer for this dependent document/link/handoff slice; no independent implementation lanes were needed. Added [the BRD](../docs/product/BRD.md) and its README entry. Ten requirements map to existing milestones and edge cases; seven assumptions/open decisions separate product intent from unvalidated demand, effort savings and model quality. Success measures defer numeric targets to baseline and release evaluation. No architecture, contracts, implementation sequence or release authorization changed.

Verification: local Python link/anchor and ID checks passed for all eight BRD references, the README entry, ten requirement IDs and seven assumption IDs. Manual consistency review used architecture sections 1-4 and 13, the master/version plans and edge-case inventory. Skill inspection reported zero suspicious Unicode and low prose density; deterministic cleanup made no changes. `git diff --check` passed. Documentation acceptance does not establish product outcomes; implementation tests were not rerun for this prose-only change. README's older progress paragraph remains outside this scoped edit; the tracker remains authoritative.

Handoff: changed docs/product/BRD.md, README.md and this tracker. No installs, models, database calls or background services; only lightweight local document checks. Existing untracked evaluation/reports/V1/SECURITY-EVALUATION.md preserved and excluded. Learning practice remains pending; optional exercise: explain why a genuine excerpt need not support every facet of a question. Next smallest implementation action remains V2-01. Commit/push synchronization is verified separately at completion.


## V1-REVIEW: Ponytail review

State: COMPLETE (static review of commit `3021ba8`). Shared outcome: identify actionable correctness, security or unnecessary-complexity findings in the V1 completion slice. V1-REVIEW-A, Sol `gpt-6.1-sol` peer `review_examples`, reviewed public exports, package configuration, both examples and their native callees; it assembled the pair report. V1-REVIEW-B, Sol `gpt-6.1-sol` peer `review_acceptance`, reviewed the acceptance tools, result boundaries, cancellation probes and matching evidence. Both lanes were read-only with no writable repository paths. Shared contracts and the reviewed source revision were frozen. Peers reconciled their reports directly; root integrated the findings and owns this tracker entry. No unresolved decision required Astra escalation.

Result: no actionable findings. Existing helpers and native modules already provide the needed behavior; no new abstraction, dependency or implementation edit was justified. Cancellation reuse probes return empty evidence for both tenants, while separate session probes check visibility and reset. This review does not independently establish the earlier hosted results or broader security guarantees. No tests, database calls, installs or persistent processes were started. Only this handoff changed; unrelated product documentation and the untracked security evaluation were preserved. Verification: static call-path and diff inspection, prose cleanup and `git diff --check`. User learning practice remains pending. Next smallest implementation task remains V2-01; optional exercise: explain why successful pool reuse alone does not prove authorization isolation.


## BRD-02: Product, architecture and plan alignment

State: COMPLETE (documentation only). User authorized comparison and scoped alignment corrections. Root was sole writer/integrator for the dependent cross-document review. [Review findings](../docs/product/ALIGNMENT_REVIEW.md) record six corrected gaps: stale progress/onboarding wording, missing reciprocal product references and task crosswalk, incomplete V6 usability measurement coverage, implicit provider-disclosure/global-quota boundaries, and ambiguous later answer-support scope. Ten BRD requirements now map to architecture sections and 46 existing task IDs. No product features, task dependencies, runtime contracts or implementation completion boxes changed.

Verification: local Markdown path/anchor checks across the reviewed documents and BRD task-ID resolution passed; all ten crosswalk rows have existing owners. Manual consistency review covered all version plans, architecture, edge-case inventory and recorded V1 acceptance. Skill checks reported zero suspicious Unicode and low density for the BRD, review and changed prose; cleanup made no changes. Git whitespace checks passed. No implementation tests, provider/model evaluations, hosted database checks or CI were rerun. Recorded V1 evidence was inspected, not re-established.

Handoff: changed README.md, docs/product/BRD.md, docs/product/ALIGNMENT_REVIEW.md, docs/architecture/ARCHITECTURE.md, tasks/plan.md, tasks/versions/V0-foundations.md, tasks/versions/V6-release.md and this tracker. Only lightweight local document checks; no installs, services or background processes. Existing untracked evaluation/reports/V1/SECURITY-EVALUATION.md preserved and excluded. Market demand, comparative effort savings and later quality/release evidence remain unvalidated. Learning practice pending; optional exercise is in the review. Next smallest implementation task remains V2-01. Commit/push synchronization is checked separately at completion.


## V2-01 active assignment

Concrete outcome: choose the first embedding profile with explicit identity, dimension, normalization, provider/disclosure, cost and laptop policies. Baseline: aligned BRD, architecture and V2 plan; V1-12 dependency complete. V2-01A owner: Sol `v2_local`, local model/license/runtime research, writable `/tmp/cragkit-v2-local.md` only; assembler of the pair recommendation. V2-01B owner: Sol `v2_hosted`, hosted API/cost/privacy research, writable `/tmp/cragkit-v2-hosted.md` only. Both peers use `gpt-6.1-sol`, exchange dependencies directly and report unresolved issues to root for Astra when needed. Repository source, schemas, locks, corpus and database are read-only for peers. Root owns decision/evidence documents, tracker, version-plan status, checks and Git. No weights, installs, provider requests, private data, database writes or services are authorized by these research lanes. Hardware inspection: arm64, 16 GiB physical RAM, 27 GiB disk available and 46 percent system memory free. Acceptance: primary-source comparison, inspect existing native boundaries, record compatibility/resource limitations and run a tiny allowed model sample only after explicit configuration. State: research complete; accepted hosted policy and final checks recorded below. User learning practice pending.


V2-01 final handoff: COMPLETE as a design decision. The owner selected hosted, opt-in OpenAI text-embedding-3-small, explicit 1536 dimensions, routine fake providers and live access disabled until separately configured. Current runtime allowlist remains empty, spend allowance USD 0 and source/query disclosure denied; neither paid calls nor document disclosure was authorized. ADR 0001 records identity/alias risk, normalization, proprietary hosted terms, local Apache-2.0 alternative, bounded opt-in probe and laptop limits. Both peers reviewed the assembled ADR; one local platform attribution was corrected. The hosted peer reconciled the plan's conditional live verification with the owner's disabled-live policy: V2-01 can complete without claiming inference; no unresolved issue required Astra.

Verification: a bounded probe fetched five pinned public model configuration files and checked 384 hidden size, 256 sentence limit, the tokenizer's advertised 512 limit, mean pooling and normalization. Ignored record: artifacts/V2/V2-01-metadata.json, 1.714 seconds and 30,900,224 bytes peak RSS for that metadata process. No model inference ran. Additional native synthetic interface probe passed sequentially on Python 3.14.6 and Node v26.5.0: request construction without network transmission, JSON round-trip and one fake finite unit vector of length 1536. Ignored record: artifacts/V2/V2-01-interface.json. Separate whole-process RSS: Python 23,871,488 bytes; Node 55,754,752 bytes. These are not inference, live response validation or production benchmarks. No model/runtime installs, weights, paid calls, database writes or persistent services. Documentation links/consistency, prose cleanup and Git whitespace checks passed. Only ADR 0001, the V2 plan status/link and this tracker changed; unrelated security report preserved. Learning explanation provided, practice pending. Next smallest action: V2-02 bounded Python embedding adapter with fake responses; live use remains a separate configured opt-in. V2 as a whole remains in progress.


## V2-02 active assignment

Outcome: bounded native Python query/batch embedding adapter under [E-r1](../contracts/EMBEDDINGS_V2.md), fake defaults and no live calls. Root owns E-r1, tracker, evidence/development docs, shared fixture if needed, final integration and Git. Sol `embedding_python` owns packages/python/src/cragkit/embeddings.py and assembles the pair outcome; Sol `embedding_tests` owns packages/python/tests/test_embeddings.py. Both use gpt-6.1-sol and coordinate directly on E-r1/API details. Contract/migrations/manifests/locks, TypeScript source and approved corpus remain protected outside assigned paths. Escalate contract/outcome changes to root before edits; unresolved decisions go to Astra. No installs, weights, credentials, provider/database calls or services. Root alone runs checks serially. Acceptance: limits, finite indexed unit vectors, profile identity, unknown usage, sanitized errors, one in-flight operation, cancellation/deadline cleanup and reuse; strict typing and focused/regression checks. State: assigned. Learning practice pending.


V2-02 final handoff: COMPLETE locally under E-r1. Sol implementation/test peers delivered substantive non-overlapping source/test files and coordinated signatures, warning suppression and Decimal regressions directly; implementation peer assembled and root verified. Changed paths: contracts/EMBEDDINGS_V2.md, packages/python/src/cragkit/embeddings.py, packages/python/tests/test_embeddings.py, docs/development.md, tasks/versions/V2-hybrid-search.md, evaluation/reports/V2/V2-02.md and this tracker. Final checks: 109 focused tests (0.14s), 544 Python/tool regressions (1.60s), strict mypy 16 files and guarded source imports passed. Initial typing/serializer issues were corrected; a low-precision Decimal regression now protects estimated cost gating. Initial import guard's assumed driver absence was corrected: existing psycopg remains installed, none of the optional database/model/provider modules were loaded. No manifests/locks, TypeScript, migrations or approved corpus edits. One test process, 27 GiB free disk/51 percent memory-free snapshot; no installs, provider/database calls, models or persistent processes. Only synthetic/mocked evidence; live endpoint, TLS, actual usage/billing and quality remain unverified. Caller-owned cooperative transport/tokenizer required; no concrete HTTP transport bundled. User's conditional API authorization was unnecessary for this deterministic slice; live access remains separately configured. Learning explanation provided, practice pending. Next smallest task: V2-03 and shared vector/usage parity, then V2-C1; V2 remains in progress. [Report](../evaluation/reports/V2/V2-02.md).


## V2-03 active assignment

Shared outcome: native TypeScript E-r1 adapter, deterministic shared Python/Node vector/usage checks and V2-C1. Sol embedding_node owns packages/typescript/src/embeddings.ts and assembles; Sol embedding_node_tests owns packages/typescript/tests/embeddings.test.mjs. Root owns shared contract/fixtures, Python conformance consumer/helper CLI, package export, development/evidence/tracker/Git and serial acceptance. Both peers use gpt-6.1-sol, coordinate directly and escalate unresolved contract decisions to root/Astra. Frozen dependency: accepted E-r1 plus its native TypeScript mapping, Python adapter commit755d76e. No peer writes to schemas/manifests/locks/Python/corpus/tracker. No live API, installs/models, database, services or background checks. Root alone runs verification. TypeScript field validation, integer JSON spelling, duplicate keys, decimal cost arithmetic, cancellation/cleanup and shared normalized outputs must match E-r1. State: assigned; user learning practice pending.


V2-03 child split: V2-03A native source/tests owned by the Sol pair (two files); V2-03B shared conformance owned by root (synthetic fixtures and checker); V2-03C checkpoint/import integration owned by root (runner/unit expectation and artifact checks). Root serializes manifest/contract/Python shared edits. A bounded JSON-depth rule (root zero, max32) was made explicit to avoid different Python/Node parser recursion ceilings; root owns the Python hardening and shared depth-boundary fixtures, with Node peer informed before dependent changes. Parent remains incomplete until combined checks pass.


V2-03A/B/C and V2-C1 final handoff: COMPLETE locally. Sol native/test peers delivered their owned TypeScript files, coordinated API/depth/snapshot regressions and assembled; root inspected and ran all checks. Root added 41 synthetic shared cases/checker, explicit depth32/numeric-token128 bounds in both native implementations, optional npm export, artifact import requirements and the serial embedding checkpoint stage. Final Node focused88 passed; final full13-stage profile passed Python/tool544, Node496, strict mypy16 files, Node typecheck/build, four schemas, 34 request/32 result/41 embedding cases, approved corpus and sealed16 hashes. Four local artifacts and three guarded installed import samples passed, rebuilt/direct wheel files identical, temporary environments cleaned. Logs/acceptance: ignored artifacts/V2/V2-C1-final*. Initial full pass was repeated after fixed-index input copying and single-read counter-name regressions; final evidence supersedes earlier run.

Changed paths: TypeScript embedding source/test/export, small Python response hardening, E-r1, shared embedding fixtures/checker, serial checkpoint/artifact helpers and their existing tests, development/CI instructions, version status, report and tracker. Locks, migrations, root imports and approved corpus untouched. Frozen dependency setup ran; no new provider/model dependency, credentials, inference, provider/database calls, registry publication or persistent services. Only one test process/language suite ran at a time; final snapshot28 GiB free disk/70 percent memory free, not a benchmark. Existing untracked SECURITY-EVALUATION.md preserved. Callback cooperation/TLS/streaming/tokenization remain application-owned and live compatibility/usage/billing/quality unvalidated. User learning explanation provided; practice pending. Next smallest task: V2-04 vector generations/reindex; V2 as a whole remains in progress. [Report](../evaluation/reports/V2/V2-03-C1.md).


## V2-04-PLAN: Planning and handoff

Outcome: correct current host/status wording and split V2-04 into bounded, testable development slices before coding. Sol `v204_brd` owns docs/product/BRD.md; Sol `v204_plan` owns tasks/versions/V2-hybrid-search.md and assembles the pair. Both use gpt-6.1-sol, coordinate directly and escalate outcome/protected-boundary issues to root, then Astra if unresolved. Root owns this tracker, final review, documentation checks and Git. Reference baseline: verified DB-NEON-01 direct development/native lexical acceptance, current architecture/master plan and V2-C1; prior Supabase results remain historical. No peer writes to source, migrations, manifests/locks, approved corpus, other documentation or tracker. No database/plugin operations, extension installation, provider calls, software tests, installs or services in this documentation pass. Acceptance: linked dependency-ordered V2-04 slices, pgvector setup inside V2-04, explicit profile/interruption/isolation/previous-generation test expectations, small-machine limits and independent production/pooling/retirement work. Parent V2-04 remains unchecked. State: complete; both peers stopped writing and root integrated the result.


V2-04-PLAN final handoff: COMPLETE (documentation only). BRD now names the current Neon development choice and links recorded direct/native lexical acceptance. Tracker current-state notes replace intended/pending host wording and identify older assignment notes as historical. V2-04 is split into A pgvector setup, B profile storage/contract, C Python staging, D Python publication, E TypeScript staging, F TypeScript publication and G integrated acceptance. V2-04A is READY; the parent and all implementation children remain unchecked. Installing pgvector belongs to A. Supabase retirement, pooled endpoint and production acceptance do not block this development work.

Sol BRD and plan peers wrote separate files, coordinated directly and assembled; root owns tracker, final integration/checks and Git. Root clarified that missing vector capability must not disable existing lexical-only paths. Planned checks explicitly cover same-dimensional model/profile mismatch, changed dimension, missing/mixed vectors, interrupted batches/publication, compare-and-swap conflict, tenant/principal/grant scope with colliding IDs, prior-pointer preservation and authorized old lexical usability. Revoked grants and tombstones stay effective. Routine fixtures are synthetic with a distinct fake profile; no paid embedding run is required. Test definitions are planned, not executed acceptance.

Changed files: docs/product/BRD.md, tasks/versions/V2-hybrid-search.md and this tracker. Final checks passed: 145 local Markdown paths/anchors, all seven child IDs and dependency/status consistency, zero suspicious characters, low prose density with unchanged cleanup output, and Git whitespace checks. No implementation tests were run for this documentation pass. No code, SQL, schema, migration bytes, dependencies, credentials, provider/DB configuration or approved corpus changed. No database/plugin operations, installs, models or task-owned processes. Resource work was lightweight document inspection, following the M4/16 GiB policy for the future serial checks. Existing untracked SECURITY-EVALUATION.md preserved. Learning example/failure/exercise are in V2-04; practice pending. Next smallest action: implement V2-04A on the accepted dedicated direct development target under its explicit administrative setup and verification, then advance one accepted child at a time.


## V2-04A active assignment

Outcome A-r1: explicit, optional pgvector 0.8.0 setup in `cragkit_vector`, with a separate checksummed setup ledger so lexical migrations and runtime history remain unchanged. Root owns setup SQL, docs/tracker, final integration, all test/database execution and Git. Sol `pgvector_admin` owns `tools/check_postgres.py` and `tools/check_neon_postgres.py` and assembles the pair; Sol `pgvector_tests` owns their two focused tooling test files. Both use gpt-6.1-sol and coordinate directly on signatures and failure coverage. State: complete; peers stopped writing and root verified integration.

Protected boundaries: existing migrations, native runtime APIs, manifests/locks, approved corpus and unrelated security evaluation. Shared contract A-r1 is frozen before dependent edits; root serializes setup artifacts. No provider calls, downloads, new services or concurrent test processes. Root uses only the accepted dedicated direct Neon development target, at most two native clients including administrative probes. Peers escalate outcome/boundary changes to root; unresolved material decisions go to Astra. Acceptance includes fresh setup/rerun, typed missing/unsupported capability, rollback/interruption/lock/deadline checks, preserved lexical ledger and default-deny/restricted-role checks.

A-r2 security decision: root accepted Astra's bounded managed-extension profile after both Sol peers independently identified Neon-owned primitive ACLs. Fresh rollback-only probes showed extension/schema owner `cragkit_admin`, primitive owner `cloud_admin`, no SECURITY DEFINER functions, and no administrator membership in `cloud_admin`. Primitive REVOKEs cannot be enforced by this administrator. Strict checks stay the default; a separate explicit managed-primitives option permits only the verified extension-owned computational surface. Schema/table default denial, administrative ownership, ledger RLS/checksums and restricted-login data boundaries remain mandatory. Future runtime schema USAGE exposes retained PUBLIC primitive execution and requires a deliberate review in B/C/E; no per-function allowlist or universal primitive isolation is claimed. No production or provider scope is added.


## V2-04A final handoff

State: COMPLETE for administrative development setup under A-r2; parent V2-04 remains incomplete. Sol implementation/test peers delivered the four owned tooling paths, coordinated directly and stopped/transferred ownership; implementation peer assembled. Root integrated the numbered optional SQL artifact, fixed global default-privilege semantics and added its regression, inspected all changes and ran serial verification. Astra reviewed the managed-ownership exception; root adopted it without adding runtime grants or broadening product scope. Source/library imports, historical migrations, manifests/locks and approved corpus remain unchanged.

Actual final results: 16 sealed hashes, 214 local Markdown paths/anchors, prose cleanup and whitespace checks; 52 focused tooling tests; 623 Python/tool regressions; strict mypy 16 files; Node 499 tests/build and strict typecheck. Seven preinstall live probes passed (typed missing/unsupported, strict rejection of managed primitives, post-DDL/ledger failure rollback, statement deadline, lock timeout, interrupted connection). Seven postinstall security/history drift probes rejected and rolled back. Explicit install, unchanged rerun, read-only vector check and existing lexical hardening/invariants/security passed; both ledgers' checksums/original timestamps unchanged. Actual restricted LOGIN denied vector lookup/casts, ledger/table reads and schema DDL; temporary SELECT still returned zero ledger rows under RLS. Existing Python and Node session suites passed serially with cleanup. Independent plugin confirms installed 0.8.0/private namespace/one setup row, zero fixture roles/policies/documents/collections/task connections.

Changed paths: two administrative tools, two focused tests, storage/postgres/setup/0001_pgvector.sql, storage README, development/Neon runbooks, active version plan, this tracker and [V2-04A report](../evaluation/reports/V2/V2-04A.md). Private configs/credentials stayed outside Git; ignored task-owned live harnesses/snapshots are execution evidence only. Existing untracked evaluation/reports/V1/SECURITY-EVALUATION.md is preserved/excluded. Initial strict live failures exposed platform-owned PUBLIC primitives and ineffective per-schema default revocations; final A-r2 checks and global installer defaults address them honestly. Temporary harness issues were corrected, successful probes supersede failed attempts and cleanup verified.

Limits: Neon scalar primitives retain PUBLIC execution/type privileges under explicit managed opt-in; schema USAGE is not universal primitive isolation. Future runtime schema grants need deliberate exposure review, never a claim of narrow per-function allowance. Installer defaults are restricted across this dedicated database, not just the vector namespace; existing grants unchanged. Native vector initialization/reindex capability enforcement remains C/E work, and B owns profile storage. No production/pooling/live-provider/quality/hosted-CI evidence, HNSW, model installs or publication. Resource snapshot 28 GiB disk/67 percent free memory; one test process/native suite and max 2 native clients, all task clients/processes closed. Learning explanation given; practice pending. Next smallest action: V2-04B shared profile/generation identity and readiness fixture freeze, new storage migration and explicit runtime exposure review.


## V2-04B-G active assignment

User authorized completing the entire remaining V2-04 phase. Root owns final integration, trackers/contracts/fixtures, administrative tooling, serial tests/native database checks and Git. B Sol `v204_storage` owns numbered optional setup/0002_vector_profiles.sql and its storage README subsection and assembles the pair. Sol `v204_storage_checks` owns vectors.sql and the conditional vector inventory in security.sql, plus a focused static check only if useful. Both use gpt-6.1-sol and resolve concrete dependencies directly; root decides boundary/outcome changes and escalates unresolved material issues to Astra. State: B accepted; C running; D-G dependency-gated until the preceding child passes.

B-r1: reuse A's separate checksummed setup_history with contiguous artifact 0002, preserving lexical migration history1/2 and historical bytes. Provision one synthetic fake1536 table with exact E-r1 six-field profile identity, full scoped FKs and norm tolerance0.001; no paid calls, HNSW or dense ranking. Runtime schema USAGE intentionally exposes managed scalar primitives; application tables, scope/RLS and restricted role checks continue to own data authorization. Root implements the small administrative B1 runner child separately; storage pair has at most five implementation/test paths. One test process/native suite, at most two database clients including admin, initial28GiB disk/67 percent memory free, no services/downloads. Protected untracked V1/SECURITY-EVALUATION.md excluded.

B/B1 handoff COMPLETE: four peer-owned SQL/storage files assembled; root administrative tools/tests preserve optional lexical baseline and validate known setup prefix. Actual54 focused and625 baseline tests passed; two native apply/rerun/invariants/vector/security runs plus injectedDDL/ledger rollback passed; original history timestamps/checksums preserved. No new service/provider/cost. C pair Sol v204_python owns new native vector_ingestion.py and assembles; v204_python_tests owns staging test file, then publication test file only after C acceptance. VG-r1 identity/profile/capability query frozen by root before edits; root owns shared/native harness, trackers/contracts/exports, serial verification and Git. C substantive peers coordinate directly; no tests/DB/Git execution by workers.

C handoff COMPLETE: Sol source/test peers assembled one owned module and test; root accepted34 focused/659 full Python-tool cases, mypy17 and actual restricted native vector staging with exact prior-pointer/lexical preservation, missing-only resume, mismatch and tenant isolation. One process/max2 clients, no provider/model install/service; cleanup complete. Root owns VG-r1/canonical capability SQL and native fixtures. Initial batch-fixture/type errors fixed. D source samepeer/samefile, tests peer newpublication test only; root gates D after this acceptance, then NodeE/F use acceptedPythoncontract. Parent remains in progress.

D handoff COMPLETE: source/test Sol peers assembled publish/ingest and22 new publication cases; root accepted56 focused/681 full Python-tool cases, mypy17 and12 native vector groups with exact prior-pointer/lexical preservation, count/profile barriers, actual failed-ready RLS transaction rollback, CAS winner and revocation/tombstone denial. No provider in publication; max2 clients/oneprocess, cleanup verified. Root sharedfixture/exports/nativehelper integrated. Node E pair v204_node owns vector-ingestion.ts and assembles; v204_node_tests owns stage test, then F publication test only after E accepted. Both Sol, sameVG-r1 contract, directdependency messaging; root ownsallchecks/native/Git. E source nowreadyforvalidation; parent incomplete untilE/F/Gpass.

E handoff COMPLETE: Sol Node source/test peers assembled native staging and61 focused cases; root inspected and accepted560 full Node/build/typecheck and16 serial native groups (12Python+4Node) under restricted LOGINS, Python-to-Node identity/replay, exact prior-pointer/native lexical preservation and colliding scopes. Strict bigint normalization fixed with regressions. Root owns fixed-allowlist local fixture pipe, temporary roles/grants, allchecks/native/Git; max2clients/oneprocess and cleanupverified. F sameNodepeer source, testpeer newpublication file afterEgate; finalG acceptance stillrequired.

G review assignment: root owns all writes and combined acceptance. Sol v204_storage reviews native authorization/readiness/storage security read-only and assembles; Sol v204_storage_checks reviews executable acceptance/fixture/cleanup evidence read-only. They coordinate directly; no tests/database/Git from peers. Root owns G1a contract/parity checker+serial pipeline integration (four paths), G1b installed-artifact guards (two paths), G2 bounded native fixture acceptance enhancements and G3 final reports/handoff/Git. No child exceeds roughly five implementation/test files. Shared contracts/migrations/locks remain serialized; user-owned security draft excluded. State: reviewing/verification; parent remains incomplete until F/G pass.


G security correction assignment: review found vector initialization did not reject administrative authority over the optional vector namespace/ledger. Same bounded outcome: reject unsafe vector writers before provider dispatch while preserving A-r2 managed scalar primitives. Sol v204_storage owns both native vector modules and canonical capability SQL and assembles; Sol v204_storage_checks owns vector unit/native acceptance helpers and coordinates directly on exact guard semantics. Both preserve existing pending F/G changes. Root retains tracker, parity/artifact tools, all serial tests/database operations and final Git. No historical setup/migration, contract, dependency or outcome changes. Root runs final integration after ownership transfer; unresolved material decisions escalate to Astra. State: implementing regression correction; parent remains incomplete.


G backward-compatibility correction: the required V1 lifecycle rerun rejected purge because its strict catalog expected nine foreign keys and optional vector storage adds two valid cascades. Parent remains incomplete. Root authorizes the smallest fix within V2-04 compatibility: recognize exactly the known optional relationships and continue rejecting unknown/malformed cascade graphs. Sol v204_storage owns Python/Node lifecycle source and assembles; Sol v204_storage_checks owns corresponding unit tests and tools/check_lifecycle.py native probes. Both coordinate directly; root owns all serial checks, tracker and Git. No historical migration/setup/contract or public API change. Native vector26 groups already passed; lifecycle failure must be corrected and rerun before final acceptance.


G bounded escalation: root noticed the preexisting purge catalog's incoming-FK parent filter omitted three deleted leaf tables. Sol peers agreed on the new known vector edges; root asked read-only Astra purge_boundary whether covering those leaves belongs in this strict compatibility correction or needs deferral. No dependent ownership/outcome change before the decision. Root remains sole writer and serial verifier; current native lifecycle run retains its loaded source revision.


G escalation resolved: Astra recommended including all three deleted leaves now, as a strictness correction under existing lifecycle safety/E78, without expanding the supported graph or public API. Root accepted: expected relationships remain exactly nine or eleven; incoming references to document_grants, ingestion_jobs and chunk_lexical also reject purge. Native helper probes each of those leaves plus the vector table under the actual restricted role, preserving graph/vector counts and dropping each unique empty probe table. Root owns the edits and final rerun; peers stopped writing.


## V2-04F/G final handoff

State: COMPLETE; parent V2-04 A-G complete for dedicated direct development and local package acceptance. Sol Node implementation/test peers delivered publication/ingest, shared fixture extraction and optional API export. Sol storage/security and acceptance peers coordinated directly on the vector administrative-role guard, exact rollback assertions and native source/profile probes; root inspected and integrated. The required native lifecycle rerun exposed the original nine-FK guard rejecting the known eleven-edge vector graph. Sol peers delivered the bounded compatibility fix and tests. Astra advised including every deleted leaf in incoming-reference validation under existing L-r1/E78; root accepted, implemented the remaining probes and reran the final native revision. No supported graph, public API, privilege or product scope expansion.

Final actual results: 61 Python/90 Node focused vector cases; 29 Python/46 Node focused lifecycle cases; 26 vector native and 34 existing ingestion/retrieval/lifecycle native groups passed under real restricted roles with max 2 clients and cleanup. Final administrative migration/vector/invariant/security checks passed. Independent plugin inspection and snapshot comparisons confirmed zero probe roles/tables/policies/data/task connections, all 11 application tables RLS, setup ledger RLS, enabled span trigger, and both ledgers' original checksums/timestamps. Full serial 14-stage checkpoint passed 691 Python/tool, 590 Node, mypy 17, TypeScript typecheck/build, 4 schemas, 34 request/32 result/41 embedding parity cases, 11 vector queries plus purge catalog/3 prepared identities/setup hashes, approved corpus and 16 sealed hashes; 4 artifacts/3 guarded installed import samples passed and temporary environments cleaned. [Final report](../evaluation/reports/V2/V2-04G.md).

Changed areas: native Node generation publication/export/shared tests; Python attempt/snapshot parity fixes; both lifecycle catalog guards/tests; canonical vector capability SQL; vector/lifecycle native fixtures; shared SQL/setup/identity checker; serial checkpoint/artifact guards; contract, development/storage/Neon/CI/edge-case guidance; F/G reports and tracker. All completed peers transferred ownership to root before integration. The initial Python interruption fake treated an existing document as newly created; root corrected its flag and bounded wait. One brief local test overlap occurred during that stalled attempt; root stopped it and final acceptance ran serially. Native suites remained serial/max 2 clients. No new model, provider call, service or dependency; frozen setup restored existing default environments and removed optional Python drivers after native checks. Resource snapshot 28 GiB free disk/59 percent free memory before final setup. No task-owned process/client remains.

Historical migrations/setup bytes, approved corpus/labels and manifests/locks remain unchanged. Private configs and credentials stayed outside Git. Untracked evaluation/reports/V1/SECURITY-EVALUATION.md preserved/excluded. Managed scalar primitive PUBLIC privileges remain disclosed under A-r2; applications own grants/policies. No live model quality, billing, dense ranking, pooling, production, hosted CI or registry publication claim. Learning explanation provided; practice pending. Next smallest implementation task: V2-05 scoped exact dense retrieval. Root owns scoped commit, immediate push and synchronization verification.

Final prose/consistency acceptance: 247 local Markdown paths/anchors, zero suspicious Unicode, low density and unchanged deterministic cleanup across the eleven changed prose files; Git whitespace checks passed. Final source tests/typing/parity/package evidence above remains unchanged by these documentation-only updates.


## V2-05 active assignment

Outcome: exact cosine-distance candidate search in both native scoped read handles, with current authorization/filters/active generation before ranking/limit, exact profile validation and existing authorized source release. V2-04 dependency complete at2f271c9. DN-r1 and canonical dense SQL frozen by root before peer edits. Sol dense_python owns Python session source and new test_dense.py and assembles; Sol dense_node owns Node session source and new dense.test.mjs. Both use gpt-6.1-sol, contribute implementation/tests, resolve dependencies directly, and escalate boundary/outcome changes to root then Astra if unresolved. No overlapping writes. Root owns contracts/SQL, shared fixture/parity checker, native helpers/CLI, plans/tracker/docs, serial verification and Git.

Child split: A Python twofiles; B Node twofiles; C shared fixture/checker/checkpoint integration at most five implementation/test paths; D native helper/CLI acceptance at most five; final documentation/Git root. Parent remains incomplete until all pass. No new public wire schema, V1 default retrieval behavior, migration, approximate index, dependency, model/provider call, cloud resource or release. Session method is the internal dense adapter for later fusion/orchestration. Protected unrelated untracked V1 SECURITY-EVALUATION.md preserved/excluded.

Resource baseline:27 GiB free disk/66 percent memory free, M4/16 GiB. One test process/native suite at a time, at most two native clients including administrative fixture owner. Root alone runs tests/database checks; peers run none. Existing pinned dependencies only; no new services/watchers/downloads. Acceptance: hand vectors/order/ties, profile/dimension/unit checks, before-limit scope/filter conditions, staging/legacy exclusion, source reauthorization, task/context/busy guards, deadline/cancel/reuse, canonical/shared parity, native restricted-role cleanup and clean package checkpoint. State: implementing; user learning practice pending.


V2-05 review handoff: both Sol peers stopped/transferred their owned source/test files. Python assembler inspected Node directly and peers aligned E-r1 profile validation order; root retains all writes. Focused Python initially32 and Node38 cases passed; root fixed strict mypy identity typing. Read-only final review found three Python malformed-batch cases accepted (boolean provider_calls, NaN/Infinity usage cost); root reproduced failures and added guards/regressions, final focusedPython35 passed. Native fixture review tightened actual lexical re-read after publication and added grant-only correct/wrong authorization plus source fetch. Initial native run correctly returned UnsupportedCapability for a nonexistent collection where the fixture expected empty results; root corrected the fixture to the existing session contract. Native final rerun in progress, parent incomplete. No model/API call, permanent policy, migration/lock change or task service.


## V2-05 final handoff

State: COMPLETE A-D under DN-r1; V2 as a whole remains in progress. Sol Python and Node peers implemented disjoint session/test pairs, coordinated profile taxonomy directly, and transferred ownership before root integration. Python assembled and both peers reviewed security/parity and native acceptance read-only. Root owns final source fixes, shared contract/canonical SQL/fixtures/checker, native Python/Node harnesses, explicit --dense CLI, checkpoint integration, documentation/tracker and Git. No unresolved material issue required Astra.

Final actual checks: focused dense Python 37 and Node 43 passed; full serial 15-stage checkpoint passed 731 Python/tool, 633 Node, strict mypy 17, TypeScript typecheck/build, 4 schemas, 34 request/32 result/41 embedding parity cases, existing vector-generation parity, canonical dense SQL/seven mathematical cases, approved corpus and 16 seals. Four clean artifacts/three guarded installed import samples passed; temporary environments removed. Native dense 10 groups covered seven real ranking cases per runtime, scope/principal/grant-only access, filter-before-limit, source denial and lexical+dense snapshot continuity. Existing native ingestion/retrieval/lifecycle 34 groups passed. Final administrative migration/vector/invariant/security checks passed; independent plugin and snapshot comparisons confirmed zero fixture data/roles/tables/policies/connections, RLS/span trigger intact and unchanged exact ledger checksums/timestamps. [Report](../evaluation/reports/V2/V2-05.md).

Changed paths: both native session modules and new dense tests; DN-r1/canonical dense SQL/shared fixture; mathematical+SQL parity checker and tests; explicit native dense fixture/child/CLI regression; serial checkpoint and its test; development/CI/storage guidance, version plan, report and tracker. Review fixes reject malformed bool call counts/nonfinite usage costs/unsafe counters in Python, preserve exact lexical results through publication, and test grant-only source access. Initial native nonexistent-collection expectation was corrected to the existing typed unsupported contract; product behavior was not weakened. No new DDL/migration, public wire schema or default V1 retriever behavior changed.

Resources: M4/16 GiB; initial 27 GiB free disk/66 percent memory free, final preinstall 27 GiB/54 percent. One test process/native suite at a time and max 2 clients including owner. Three existing pinned optional PostgreSQL packages restored for native work; final frozen default sync removed them. No new dependency/model/service/watcher; no paid embedding or live model call. Task-owned pools/children/temporary configs closed/removed, fixture cleanup independently verified. No secrets/private configuration in Git; historical setup/migration bytes, manifests/locks and approved corpus/labels preserved. Untracked V1 SECURITY-EVALUATION.md excluded. Managed primitive exposure remains A-r2; model quality, live billing, pooling, production, hosted CI and registry release remain unvalidated.

Learning explanation provided: smaller cosine distance ranks first, filters/scope precede limits, fresh source access reauthorizes retained revisions. Practice pending; exercise in report. Next smallest task: V2-06 identifier search and rank fusion; public hybrid orchestration remains V2-07. Root stages only accepted scope, commits, immediately pushes and verifies remote synchronization.

Final prose/consistency check: 230 local Markdown paths/anchors passed across seven changed reader-facing files; zero suspicious Unicode, low density and unchanged deterministic cleanup. Whitespace and credential-pattern/staged-scope checks are performed before the focused commit.

## V2-06 assignment record (IF-r1, complete)

State at assignment: running; final completion is recorded below. Outcome: internal exact identifier candidate lists and bounded deterministic weighted RRF in both runtimes, followed by V2-C2. No public hybrid orchestration, migration, setup, lockfile or provider changes. Root owns contract IF-r1, shared fixtures/checkers, native acceptance, documentation/tracker, final integration and Git. Existing untracked V1/V2 security reports are user-owned and excluded.

- V2-06A, identifier peer (`/root/identifier`, `gpt-6.1-sol`, implementation): both identifier modules, ingestion/session integrations and focused identifier tests. Two serial child slices: extraction/storage, then selection/source projection. Read-only dependencies: IF-r1, current native sessions, immutable DDL. No shared files/tests/DB/Git commands without assignment.
- V2-06B, fusion peer (`/root/fusion`, `gpt-6.1-sol`, implementation/assembler): Python/Node fusion modules and focused fusion tests. Read-only IF-r1/candidate schemas; substantive pure arithmetic, boundary validation and peer assembly review. No overlapping edits. Peers communicate directly; transfer files explicitly before root changes.
- V2-06C root: shared fixtures/contract checks and scoped native validation; one test process, one language suite at a time, max two database clients including owner, synthetic data only. V2-06D root: C2/profile, prose/link checks, final report and scoped commit/push/synchronization. Material unresolved issues escalate to Astra through root.

Initial headroom: 40 GiB free disk; no install/model/service required for writers. Root restores only existing pinned PostgreSQL extras for native validation. Learning practice pending; example: an exact ERR_CONN-42 token survives FTS punctuation splitting, and RRF votes depend on ranks rather than incompatible raw scores.


V2-06 intermediate checkpoint (superseded by final handoff below): both Sol peers transferred all writes to root; fusion peer assembled and both reviewed the integrated boundaries. Root corrected Python float-Literal typing/direct extractor import, aligned canonical identifier SQL parameter order, and fixed JavaScript trailing-newline ID acceptance with shared parity cases. Added underflow rejection, subnormal and list/entry/union boundary tests, plus Node sparse-array descriptor regressions. Initial focused 47 Python/tool and 40 Node checks, strict typechecks and shared function/provenance parity passed; final expanded profile pending. Native dense+identifier+fusion 12 groups passed both runtimes, maximum 2 clients, cleanup verified. Node lexical/vector token storage assertions added to the existing vector fixture; that serial native run is in progress. No model/API calls, new dependency, permanent grant, migration/setup or sealed-input edit.

User-owned untracked security reports remain preserved and excluded. Current-code inspection confirms the existing base Node fixture still receives an administrator configuration path (F-01) and runtime guards still omit dangerous predefined-role membership denial (F-02); those pre-existing findings require a separate bounded security follow-up. The report's F-03 statement does not describe the current dense selection method: V2-05 explicitly invokes vector capability/history/profile checks before SQL. Other report findings require triage, not an assumption that they are fixed. Current synthetic fixture roles have no such memberships and identifier/fusion children receive restricted configuration only. V2-06 acceptance does not establish production security or resolve that audit.


V2-06 explicit ownership record: root retained all shared contracts/fixtures/canonical SQL/checkers/harnesses/docs/tracker and Git. Identifier peer initially owned packages/python/src/cragkit/{_identifiers.py,ingestion.py,vector_ingestion.py,_postgres_session.py}, packages/typescript/src/{identifiers.ts,ingestion.ts,vector-ingestion.ts,postgres-session.ts}, packages/python/tests/test_postgres_identifiers.py and packages/typescript/tests/postgres-identifiers.test.mjs. Fusion peer initially owned packages/python/src/cragkit/_fusion.py, packages/typescript/src/fusion.ts, packages/python/tests/test_fusion.py and packages/typescript/tests/fusion.test.mjs. Storage/extraction and candidate/source were separate child slices; shared IF-r1 was read-only for peers. Both stopped and transferred writes to root before fixes. Final read-only assembler review found no regression after the helper refactor. All actual checks remain root-owned and serial.


## V2-06 and V2-C2 final handoff

State: COMPLETE, child slices A-D, contract IF-r1. Both runtimes now populate exact identifier arrays, search them under the existing scoped snapshot and source-release contract, and perform deterministic weighted RRF with bounded unions and complete provenance. Public retrieval remains lexical until V2-07. Historical receipt identities, generations, migrations/setup artifacts, schema bytes, locks, approved labels and seals are preserved. Existing empty identifier arrays require a new ingestion intent.

Changed files: both new identifier/fusion modules and focused tests; both ingestion/vector-ingestion/session integrations; IF-r1/shared fixture/canonical identifier SQL; function/provenance/SQL checker and regressions; dense and vector native harness extensions; serial checkpoint and test; development/CI/storage/version guidance, report and tracker. Two Sol peers implemented independent responsibilities, coordinated directly and assembled read-only; root integrated after explicit ownership transfer. No unresolved escalation needed Astra.

Final actual results: focused Python/tool 52 and Node 46 passed; all 16 serial checkpoint stages passed with 776 Python/tool and 679 Node tests, strict mypy over 19 source files, Node typecheck/build, schema drift, request/result/embedding/vector/dense parity, four extraction/ten arithmetic/six typed IF-r1 failures, approved corpus, 16 seals, four clean artifacts and three guarded installed import samples. Native final-source dense/identifier/fusion repeat passed 12 groups in both runtimes. Native vector/publication and explicit Node lexical/vector token-storage acceptance passed 27 groups. Administrative migration/vector/invariant/security checks passed. Independent plugin inspection and programmatic exact snapshots were repeated after the final native run: zero fixture rows/roles/tables/policies/connections, 11 app RLS tables, setup-ledger RLS and canonical span trigger intact, exact ledger checksums/timestamps unchanged. [Full report](../evaluation/reports/V2/V2-06.md).

Resources: M4/16 GiB, 40 GiB available disk before/after; later system memory query reported 57 percent free. One test process/language native suite at a time; at most two clients including owner. No external model/API call, model download, dependency addition or new service/watcher. Only three pinned PostgreSQL extras restored, then removed by frozen default sync. Task pools/children/temp credential files closed and cleanup independently verified. Seven reader-facing files passed self-contained prose and local Markdown checks. Untracked V1 SECURITY-EVALUATION.md and V2 SECURITY-TESTING-REPORT.md remain user-owned and excluded. No hosted CI, provider-quality, pooling, registry release or production-readiness claim.

Learning: rank-based votes are comparable without adding raw scores; repeated family lists retain best ranks and cannot gain unlimited votes. Union overflow, trailing-newline list IDs, positive-vote underflow and malformed sparse arrays have explicit failures/regressions. Practice pending; optional exercise is in the report. Next product task: V2-07 hybrid orchestration and explicit degraded modes. Keep the separate existing F-01/F-02 security findings and remaining audit triage open before broader deployment work. Root commits only accepted scope, pushes immediately and verifies synchronization under standing authorization.

## V2-07/V2-08 assignment record (HY-r1, complete)

User expanded the requested outcome to complete remaining V2 through V2-C3/exit. State at assignment: implementing V2-07, then dependent V2-08; final completion is recorded below. Root owns frozen HY-r1, shared fixtures/checkers, native harness/evaluation, docs/tracker/contracts/manifests/locks/Git and final integration. Preserve both untracked user security reports. Existing F-01/F-02 remain separate open findings; do not claim production security.

- V2-07A owner `/root/hybrid_python`, gpt-6.1-sol, implementation/assembler. Writable: packages/python/src/cragkit/retrieval.py, _postgres_session.py and new _hybrid.py if useful; packages/python/tests/test_hybrid.py and test_hybrid_savepoint.py. Implement Python mode/config/selection, bounded embedding/fusion/accounting, explicit failures and same-snapshot savepoints. No shared edits.
- V2-07B owner `/root/hybrid_node`, gpt-6.1-sol, implementation. Writable: packages/typescript/src/retrieval.ts, postgres-session.ts and new hybrid.ts if useful; packages/typescript/tests/hybrid.test.mjs and hybrid-savepoint.test.mjs. Same HY-r1 outcome, complementary runtime ownership. Python assembles both read-only; peers resolve interfaces/failure details directly. Escalate outcome, protected boundaries or external ownership to root, unresolved material decisions to Astra through root.
- V2-07C root: shared/native acceptance and combined checks; V2-08 root: development metrics/evaluation and V2-C3/exit evidence. Dependent evaluation implementation begins after the runtime contract is validated. One test process and one native language suite at a time, max two clients, small synthetic data and fake providers only; no install/model/service or live call from peers. Root alone runs checks/DB/Git. All peer checks initially unrun. Deadline/filter/source/coverage boundaries and historical bytes remain protected. Next action: implement frozen HY-r1 in disjoint runtime lanes.

V2-08A independent metrics lane: owner `/root/v2_metrics`, gpt-6.1-sol, implementation, writable only evaluation/runners/v2_metrics.py and tools/tests/test_v2_metrics.py. Outcome: tested pure development-label ranking metrics, independent of runtime implementation; root owns evaluator/database seeding and integration. API score_question(question,evidence,k=5), aggregate(rows). Evidence is normalized document_id/logical revision_id/start_byte/end_byte, no provider work; preserve all labels and held-out boundary. Read-only protocol/dev label shape/HY-r1. No tests/processes/install/DB/Git; root serializes checks. No additional service/resource cost. Root final integrator/escalation owner; pair assembly remains Python peer for runtime lanes.

V2-EXIT security pair added after current-code verification of user findings F-01/F-02: bounded fixes within existing database/harness subsystem. Shared outcome: close administrator-config exposure in legacy child and explicit dangerous predefined-role denial, without schema/policy relaxation or granting dangerous roles. Root remains final integrator/Git/docs owner. `/root/v2_role_guard` gpt-6.1-sol owns only role guard SQL sections in Python _postgres_session.py/ingestion.py and Node postgres-session.ts/ingestion.ts, plus new focused guard tests. Root transfers those files while this lane runs; preserve all existing V2-07 diffs. `/root/v2_harness_security` gpt-6.1-sol owns tools/check_python_postgres.py, tools/check_typescript_postgres.mjs and tools/tests/test_check_python_postgres.py; Python-parent unsafe-admin rejection replaces child administrator access, preserving --hybrid additions. Harness peer assembles both read-only; peers coordinate directly and escalate external ownership/outcome to root. No test/build/native/Git/process run from peers; root keeps one serial suite, max two clients. No dangerous-role grants, new services, provider calls or DDL changes. Other audit items remain separately triaged; no blanket security-resolution claim.

V2 final read-only assembly review: `/root/hybrid_python` (gpt-6.1-sol, prior runtime assembler) inspects final retrieval/savepoint/failure code and security-guard integration; `/root/v2_metrics` (gpt-6.1-sol) inspects final evaluator, frozen result JSON and metric/regression methodology. No writable paths or checks/processes. Root owns all files, final verification and acceptance; reviewers report concrete findings for root resolution before Git. No additional service/DB use.


## V2-07/V2-08/V2-C3/V2-EXIT final handoff

State: COMPLETE for V2's declared native/synthetic development milestone. Both public PostgresRetriever implementations support trusted lexical/dense/hybrid modes, bounded embedding before leasing, one original query/attempt, fixed branch allocations, same-snapshot savepoints, explicit degraded recovery and fresh authorized source packing. Defaults remain lexical; fatal authorization/integrity/deadline/source/cleanup failures do not fall back. No wire/schema/setup/migration/lockfile or reviewed-input changes. Live profile provisioning/quality/billing, held-out quality, pooled operation, production, hosted CI and registry release remain unvalidated.

Coordination: two Sol runtime peers implemented disjoint files and communicated directly, Python assembled. A third Sol metrics lane delivered pure metrics/tests. A managed Sol security pair closed F-01/F-02 implementation boundaries; harness peer assembled. All stopped/transferred writes before root integration. Final read-only runtime and evaluation reviews reported no must-fix findings. Root owned shared HY-r1/fixtures/conformance, native evaluators, integration corrections, docs/tracker and Git; no unresolved material escalation needed Astra.

Changed files: both native retrieval/session integrations and hybrid helper/test modules; Python/Node reader/writer guard SQL and new guard tests; restricted legacy harness/helper/tests; shared hybrid fixture/contract and public/encoder parity tools/tests; synthetic encoders, scoring module/tests, native evaluation helper/child, structured metrics/report; development/CI/Neon/storage/protocol/contract guidance, version plan and tracker. Fixes included strict typing/profile-order alignment, invalidation on savepoint control failure and bounded adapter overrides that ignore deadlines. F-01 removes administrator paths/login from the child and checks the existing parent connection; F-02 denies five dangerous predefined MEMBER roles across both guards/runtimes. No dangerous role grants or OS-access negative fixture was performed. User security reports remain untouched and excluded; broader audit concerns retain their recorded limits.

Actual checks: focused Python/tool/security 86 passed; Node hybrid/savepoint/role 14 passed. Full 17-stage serial checkpoint passed 843 Python/tool tests and 693 Node tests, strict mypy over 20 source files, TypeScript typecheck/build, all schema/fixture parity, eight public hybrid cases/four synthetic encoders, approved development labels and 16 seals, four clean package artifacts and three guarded installed import samples. Final native hybrid/evaluation 12 groups passed both runtimes: real dense/lexical SQL failures, fail-closed and explicit recovery, transaction-local marker/snapshot preservation, filter retention, fresh source tombstone denial, 18 mode/question requests per runtime and complete normalized-result parity. Final legacy harness 8 groups passed, including parent administrator rejection and actual restricted Node TLS/RLS/login/cancellation/scope checks. Administrative migration/vector/invariant/security checks passed. Independent plugin/snapshot comparison confirmed zero fixture rows/roles/tables/policies/connections, 11 app RLS tables, setup-ledger RLS/span trigger intact and exact historical ledger checksums/timestamps unchanged. Read-only PostgreSQL FTS control matched the identifier keyword but rejected the full q01 query against the reviewed sentence. [Exit report](../evaluation/reports/V2/V2-07-08-exit.md).

Evaluation: six questions frozen before measurement, nine development revisions, identical corpus/configuration across three modes; no held-out label reads/scoring or tuning. Five positive-reference questions and one unanswerable. Recall@5/support recall: lexical 0.0, synthetic dense 0.8, hybrid 0.8; MRR@5 dense 0.8/hybrid 0.7. Documented q01 exact-identifier/semantic-context tie regression, q03 active-generation historical miss and complete-query simple FTS misses. Both dense/hybrid returned evidence for the absent-answer label; no sufficient coverage claim. Synthetic encoder is label-blind; zero model spend is known, hosting cost and live model quality unmeasured. Raw per-question ranks/digests/timing are in the sanitized structured report; latency is six sequential observations per mode, not a speed claim. Frozen metric values reproduced across native reruns.

Resources: M4/16 GiB, later 39 GiB available disk and 72 percent memory free; snapshot observations only. One test process/language native suite at a time, maximum two DB clients including owner. Only three existing pinned optional PostgreSQL packages restored for native checks, then removed by frozen default sync. No external model API, new dependency, model download, task service or watcher. Pools/children/temporary credential files closed; cleanup independently verified. Reader-facing prose/link/consistency and credential/staged-scope checks run before Git. Both untracked security reports remain excluded. Package artifacts retain internal 0.0.0 identity; milestone labels are not registry releases.

Learning: example and failure explanation delivered; user practice remains pending. Reproduce the q01 reciprocal-rank tie, then explain why same-snapshot rollback and fresh source authorization solve different problems. Next smallest task: V3-01 reranker contract and shortlist, including its model/resource/disclosure decision before adapters. Root commits the verified scope, immediately pushes and verifies remote synchronization under standing authorization.


V2 exit final prose/consistency evidence: twelve reader-facing files (including protected structured results) passed local checks: 312 Markdown paths/anchors, zero suspicious format characters, low prose density and byte-identical deterministic cleanup. Final whitespace/protected-path checks passed; manifests/locks, historical SQL/setup, wire schemas, approved source/label/seal bytes and both user reports are unchanged. All source/test changes precede the passing 17-stage checkpoint and final native acceptance; subsequent edits are documentation and derived sanitized results only. Scoped credential-pattern/index review and immediate push/synchronization are the remaining Git actions.


## V3-01 assignment record (RK-r1)

State at assignment: RUNNING; final completion is recorded below. Outcome: documented reranker score/input/truncation contract, local/API shortlist and explicitly synthetic recorded-response compatibility examples. V2-08 dependency passed. No runtime adapter, real-model quality claim or change to published wire schemas.

- V3-01A `/root/rerank_contract`, gpt-6.1-sol: implementation and pair assembler; writable contracts/RERANKER_V3.md and contracts/fixtures/reranking.json. Own RK-r1 and deterministic recorded examples.
- V3-01B `/root/rerank_shortlist`, gpt-6.1-sol: implementation; writable docs/decisions/0002-reranker-policy.md. Own primary-source local/API comparison, score semantics, optional dependency/resource/disclosure gates.
- Root: sole tracker/report/Git owner, final integration and serialized checks. Peers coordinate concrete dependencies directly; assembler reviews both artifacts, requests owner corrections and reports unresolved decisions to root for Astra if needed. Ownership transfers require agreement and stopped prior writer.

Read-only boundaries: source/runtime APIs, schemas, approved labels/corpus, migrations, locks and manifests; preserve both untracked user reports. Contract RK-r1 freezes before V3-02 dependent implementation. Acceptance: explicit model/version/direction, bounded inputs, observable truncation, malformed mapping rejection, model score never called truth probability; inspect recorded responses and source compatibility, Markdown links and prose. One local check process; no downloads, installs, model/API calls, services or database use. Learning practice pending.


## V3-01 final handoff

State: COMPLETE for design and recorded compatibility, not runtime adapters. Changed files: RK-r1 contract and synthetic recording fixture, ADR 0002 shortlist, contracts index, V3 version status, this tracker and V3-01 report. Both Sol peers did substantive nonoverlapping work and coordinated directly; contract peer assembled, then both transferred ownership to root. A delayed contract handoff message arrived after a final worker clarification edit; root stopped further worker writes, reinspected the final content and retained the bound/source clarifications before acceptance. Root inspected all artifacts. No unresolved escalation required Astra.

Actual verification: serial Python/Node task-local recorded inspectors passed eleven matching mapping/order cases, plus three native nonfinite score rejections, UTF-8 prefix/source-preservation example and published MiniLM finite-score compatibility in each runtime. No product runtime regression/integration suite, model inference or quality evaluation ran for this design slice. Final documentation check passed 167 local Markdown links/anchors across seven artifacts, zero suspicious Unicode characters, low measured prose density and byte-identical deterministic cleanup; git diff --check passed. Commands/logs: artifacts/V3/V3-01/check_docs.py and docs.log.

Resources: Python 3.14.6, Node v26.5.0, 39 GiB free disk; one check process, no installs/model downloads/provider calls/database/service/watchers. Real-model resource fit remains unmeasured. Protected runtime/schema/migration/lock/corpus/label files unchanged; both user audit reports remain untracked and excluded. Learning example/failure explanation delivered; practice pending. Next: V3-02A executable fake boundary and failure fixtures, then complementary runtime; live comparison remains a separate required V3-02 gate after explicit configuration, not satisfied by synthetic responses. Root commits accepted scope, pushes immediately and verifies synchronization.


## V3 remaining-version assignments

State: RUNNING, V3-02 first. User requested completion and full verification through V3-EXIT. Root owns shared contracts/fixtures, manifests/locks, docs/tracker/Git and final acceptance; protected historical inputs and unrelated reports preserved. Apply RK-r1, refined executable RK-r2 before consumers.

- V3-02A `/root/v3_python`, gpt-6.1-sol, implementation/assembler: Python reranking.py and test_reranking.py.
- V3-02B `/root/v3_node`, gpt-6.1-sol, implementation: Node reranking.ts and reranking.test.mjs.

Shared outcome: bounded injectable adapters, complete raw-score mapping, stable ties, observable inference truncation, shared deadline/cancel and explicit visible fallback. Peers coordinate directly; no overlapping writes. Root serializes checks, owns contract freezes and dependent work. One local test process, no worker installs/models/providers/services/DB/Git. Real comparison configuration requested from user; routine fake work proceeds. Outcome/boundary/ownership escalation to root, unresolved material decisions to Astra. Child reports are input to root validation, not completion proof.


## V3-02 session handoff

State: IMPLEMENTED_UNVALIDATED parent; A/B/C verified locally. User requested full V3, but V3-02 requires a real comparison and V3-03 depends on V3-02. Owner model choice requested asynchronously (hosted Cohere or local MiniLM); answer/configuration still pending. Do not mark V3 complete or bypass dependent task gates. Next smallest action is configure and run V3-02D once that decision arrives.

Changed: Python/Node reranking modules and tests, RK-r2 refinement, Node export, shared checker/helper/redaction test, serial pipeline/test, installed artifact import checker, development/CI/version docs, V3-02 report and tracker. Both peers transferred ownership; root integrated independent review deadline/input-bound fixes. Full final checks: 18 stages, 870 Python/tool and 701 Node tests, mypy 21 source files, TypeScript typecheck/build, 11 complete result parity cases, unchanged schemas/seals, four clean artifacts/three guarded installed imports. Focused Python26/Node8; tool pipeline/redaction8 passed. No live model, source retrieval integration or real quality claim. Documentation checks passed: six reader-facing files, 220 local paths/anchors, zero suspicious Unicode, low measured prose density and unchanged deterministic cleanup; whitespace checks passed. No source/test edits after the final checkpoint.

Resources: 39 GiB free disk, M4/16 GiB constraint, one test process, no new dependencies/models/providers/DB/services/watchers. All task test processes ended; artifact environments cleaned. Preserve both unrelated user audit reports and historical inputs. Learning example/failure explained; practice pending. Root commits only verified A/B/C scope, immediately pushes and verifies synchronization; parent and remaining V3 tasks stay unchecked.


## V3-02D hosted comparison assignment

State: RUNNING. User selected hosted setup by privately saving the Cohere key. Root verified only metadata: owned regular nonempty file0600/private parent0700, no key output. Outcome: two sequential bounded native live probes on the existing synthetic room sample, no private corpus, retries or model download. Selected identifier rerank-v5.0-fast; mutable alias/API2, max3shortASCII candidates, timeout20s/response65536, two calls admitted below USD 0.01 using the dated USD0.02/million-token Fast rate and conservative per-pair context bound. Billing remains observed/estimated, never invented known zero.

- `/root/cohere_python`, gpt-6.1-sol: implementation/assembler; tools/check_cohere_reranking.py.
- `/root/cohere_node`, gpt-6.1-sol: implementation; tools/check_typescript_cohere_reranking.mjs.

Both peers coordinate profile/output shape directly, own separate files and stop writes at handoff. Root owns runs, frozen/shared files, reports/tracker/Git and final integration. Workers may not read the key or run network/model/process/tests/Git. Secrets remain outside checkout and never in arguments/reports. One live request at a time, no automatic retries/model substitution. Escalate outcome/protected-boundary/ownership changes to root, unresolved material issues to Astra. This is a compatibility/ranking probe, not production transport, model-quality calibration or exact tokenization/truncation proof.


## V3-02D final attempt handoff

State: live comparison NOT PASSED; V3-02 parent remains IMPLEMENTED_UNVALIDATED and dependent V3-03 not started. User saved a key; owner-only metadata passed. Root made one synthetic fixed-host Cohere request with verified TLS; HTTP 401 in 481.125 ms. Node live probe not run, no provider retries. User confirmed a key from OpenAI/another provider. Rotation/revocation at the original provider advised because the token reached Cohere's authentication header once; user action still pending. No secret or raw header/body printed/committed. Replacement requested through tested hidden-entry helper; wait for valid Cohere configuration before a newly authorized attempt.

Changed: Python/Node opt-in live probes, hidden credential saver/offline tests, development instructions, attempt report and tracker. Two Sol peers wrote complementary files and coordinated directly; Python assembled and transferred ownership, root verified. Parent wall-clock bound 30s for actualPythonprobe, per-request no-retry controls and explicit pair admission estimate below USD 0.01. Only synthetic room text sent, no corpus/held-out/provider-policy guarantee. [Report](../evaluation/reports/V3/V3-02D-attempt.md).

Checks: initial13 focused tests passed, final18-stage checkpoint 884 Python/tool tests and 701 Node tests, mypy 21, Node typecheck/build, 11 shared adapter cases, unchanged schemas/seals, four artifacts/three guarded imports. Node syntax and no-opt-in zero-call guard passed. No source/test edits after final checkpoint. Prose/link check recorded below. Resources: 40 GiB free disk, no installs/models/DB/services/watchers; one check process and one live request, task children/environments cleaned. User audit reports preserved/excluded. Learning example explained; practice pending. Next: valid Cohere key, successful V3-02D, then V3-03 and remaining dependency chain. Root commits verified preparation scope, immediately pushes and verifies sync; no V3-complete claim.


## V3-02D replacement update

After the owner confirmed saved, root made one newly configured Python attempt: HTTP 401, 418.881 ms, one call. Cumulative: two Python requests/both 401, zero Node requests. Offline key-format classification (no token output) still found a recognizable OpenAI project/service key format. Added predispatch rejection to both probes/saver; no further live call. Owner chose to keep the planned Cohere reranker and create a Cohere key; save confirmation pending. Parent/dependent tasks remain incomplete.

Independent review fixed hidden-prompt echo fallback and 4,096-byte newline overflow; regressions pass. Final 18-stage checkpoint 888 Python/tool and 701 Node tests, mypy 21 and TypeScript checks, 11 adapter parity, artifacts/imports/schemas/seals passed after all source edits. Focused 18 credential/probe offline cases passed. Key revocation at original provider is a user action, not verified or performed by root. Report records both 401 attempts and provider uncertainty. Final prose checks recorded below. Next action: resolve provider/key, then required live comparison; no dependent phase bypass.


Owner decision: retain Cohere, create its key in its dashboard and save through the hidden helper; no OpenAI reranking switch. Final preparation prose checks passed three files and local links/anchors, zero suspicious Unicode, low measured density and unchanged deterministic cleanup. Next required input is confirmation that a valid Cohere key was saved; keep all remaining V3 gates open.


## V3-02D successful configuration handoff

Owner replaced the key after pausing/resuming. Local format/permission checks passed; one new Python then one Node request both returned 200. Same synthetic room sample/order, 43 billed input tokens each, max absolute raw-score difference below 1e-6. Four cumulative requests: two earlier 401, two successful 200; planned context/price admission for all four below USD 0.01, actual account billing unknown. No private/held-out text or new model dependency. Provider truncation/processed tokens remain independently unknown; this is a short-sample compatibility probe, not production hosted-token guarantees or broad quality. V3-02 complete for its injectable boundary and explicit live comparison; V3-03 dependency satisfied. Detailed observations in V3-02D-results.json supersede the historical failed-attempt gate.


## V3-03 assignment TK-r1

V3-02 satisfied after successful configured comparison. Shared outcome: exact Evidence JSON renderer and optional cl100k_base counter, strict serialized-context counting plus wrapper reserve, explicit estimated mode and typed envelope failures. `/root/context_python` gpt-6.1-sol owns context.py/test_context.py and assembles; `/root/context_node` gpt-6.1-sol owns context.ts/context.test.mjs. Peers coordinated directly on serialization/options/error semantics and stopped writes before root checks. Root owns TK-r1/shared fixtures, optional manifests/locks, explicit pinned tokenizer acquisition, parity/pipeline/artifact checkers, docs/tracker/Git and integration. No worker tests, models, installs, keys, network, DB or Git. One root test process; no automatic library asset fetch. Bounded 1.68MB verified tokenizer table and optional tokenizer dependencies are task-owned; no model runtime. Outcome/protected-boundary/ownership changes escalate to root, unresolved disputes to Astra. Acceptance: exact shared serialized outputs/counts, unsupported strict tokenizer rejection, wrapper/envelope bounds, Unicode/special literal handling and import isolation.

## V3-03 resumed integration and V3-04 ownership

V3-03 remains RUNNING until corrected tokenizer parity and checkpoint checks pass. Root resumed after interruption and confirmed the working changes. The pure JavaScript tokenizer disagreed with Python for Unicode whitespace; the optional Node WASM implementation matched the task-local 90-case probe. TK-r1 now requires both runtimes to construct from the same pinned local ranks and regex. `/root/token_node_fix` (gpt-6.1-sol) owns Node context implementation/tests/helper and assembles; `/root/token_fixture` (gpt-6.1-sol) owns shared context fixtures, Python context tests and Python parity checker. They coordinate the helper protocol directly. Root owns other files, docs/tracker, combined serial checks and Git. No worker suites, installs, network, database or provider use. This corrects a discovered acceptance defect before V3-C1 completion.

V3-04 preliminary work is IMPLEMENTED_UNVALIDATED, held behind V3-C1. The earlier Sol pair wrote disjoint native packing modules/tests, Python assembled, and both transferred writes to root. Root added private opt-in authorized full-source snapshots in both PostgreSQL session/source implementations and separate snapshot tests. Root now owns these files and will freeze PK-r1, add shared parity checks and validate before acceptance. `/root/packing_review` (gpt-6.1-sol) has read-only inspection of this work; no writable paths or processes. No SQL, schema, migration, source corpus, approved label or default source-fetch shape change is authorized by this work. Existing user security reports remain excluded. Unresolved outcome/boundary changes escalate to root, then Astra if needed.


## V3-03 / V3-C1 final handoff

State: COMPLETE for standalone context counting. Both Sol peers delivered substantive disjoint work, coordinated directly and stopped writes; Node assembled. Root inspected changes, fixed a test path conversion for spaces and ran 37 focused Python/tool tests, seven Node tests, eight context plus 127 token parity cases and the full 20-stage serial checkpoint (939 Python/tool, 715 Node, mypy 23 files, four artifacts/three guarded imports). Counts include preliminary V3-04 files still pending separate acceptance. No unresolved escalation required Astra. Changed scope: context modules/tests, pinned fixture/acquisition tool, optional manifests/locks, parity/artifact/pipeline checks, contract/development/CI/version guidance and this tracker/report. Observed 40 GiB disk available and 79 percent memory free; no database/provider/model call or task service. Learning practice pending. Next: V3-04 root integration of source snapshots/packing, including mutable-source and generated-ID regressions discovered in read-only review. Both user reports remain untouched and excluded. Root commits the verified TK-r1 scope, immediately pushes and verifies synchronization.


V3-04 resumed regression assignment: `/root/token_fixture` (gpt-6.1-sol) owned Python packing tests and assembled; `/root/token_node_fix` (gpt-6.1-sol) owned Node packing tests. Shared PK-r1 outcome: mutation isolation, collision-safe span IDs, Unicode identity separation and strict whole-span budget boundaries. They coordinated directly, inspected both artifacts and stopped writes; root now owns all files and combined checks. Four Python/six Node regression tests added; no worker suites or services. Root fixed source snapshots and deterministic collision suffixes, added bounded fenced-code/heading expansion, shared packing parity and optional exports/artifact checks. Protected SQL/schema/labels and user reports unchanged; source authorization remains caller/adapter responsibility. Final acceptance pending.


## V3-04 final handoff

State: COMPLETE for standalone PK-r1 and opt-in authorized full-source capture; post-packing coverage remains V3-06. Changed paths: both packers/tests and private source/session snapshot integrations/tests, shared packing fixture/parity tools/contract, optional Node export, acceptance runner/artifact guards, native result harness, development/CI guidance and tracker/report. Review findings fixed before acceptance: mutable source/facet inputs, generated-ID collisions, locale-sensitive grouping and malicious alias names; bounded fenced-code/heading expansion added. Both managed Sol pairs stopped writes; root inspected and integrated. No unresolved issue needed Astra.

Actual verification: 25 focused Python packing/source tests, 13 Node tests, mypy 23 files and TS typecheck/build passed. Shared 17-case complete-result parity passed. All 21 serial checkpoint stages passed (943 Python/tool, 721 Node, four clean artifacts/three guarded imports, existing parity and 16 seals). Native direct Neon --results/--typescript acceptance passed 27 groups, including captured exact-source packing, fresh grant/tombstone/revision revocation, tenant isolation and stored corruption rejection; fixture cleanup_verified true, maximum two clients. No paid calls/model download, service or task process. M4/16 GiB; latest observed 40 GiB available disk/79 percent system memory free. Learning example/failure explained; practice pending. User reports untouched and excluded. Next smallest task: V3-05 query-bound conservative facet policy, then V3-06 reassessment/rebalance; AS-r1 draft remains uncommitted for that later slice. Root commits accepted PK-r1 scope, pushes immediately and verifies synchronization.

## V3-05 assignment AS-r1

Dependency V3-04 accepted. Shared outcome: conservative query-bound reviewed-span assessor, unknown/missing/conflicting facet states and rejection of invented references. `/root/token_fixture` (gpt-6.1-sol) owns assessment.py/test_assessment.py and assembles; `/root/token_node_fix` (gpt-6.1-sol) owns assessment.ts/assessment.test.mjs. Both perform substantive implementation and coordinate API/parity directly. Root owns frozen AS-r1 contract/shared fixtures, optional export/artifact wiring, docs/tracker/Git and serial combined acceptance. No worker tests, services, network, DB, installs or Git. Protected schema/migration/labels/default retrieval behavior remain unchanged. Escalate outcome/protected boundary/other-lane ownership to root before edits; unresolved material issues go to Astra. Read-only Sol policy review found the known-conflict omission hazard; AS-r1 now forbids sufficient when only one declared incompatible claim survives. Method calibration is curated/in-sample; no general semantic quality claim. State RUNNING.


## V3-05 final handoff

State COMPLETE for curated AS-r1. Sol native pair delivered separate modules/tests, coordinated directly, Python assembled and both stopped writes. Read-only review found no remaining must-fix issue after the known-conflict omission rule was corrected in the contract before implementation; root inspected and verified. Changed scope: assessment modules/tests, AS-r1/shared 35-case fixture/checkers, Node optional export, acceptance/artifact wiring, contract/development/CI guidance and report/tracker. Actual checks: 24 Python/eight Node focused cases, strict mypy over 24 files, TS typecheck/build, 35 full-result parity; all 22 serial stages passed with 967 Python/tool and 729 Node tests, 16 seals, four artifacts/three guarded imports. Development labels only; no held-out scoring, provider call, DB, model download or services. Earlier 40 GiB/79 percent memory snapshot unchanged as last observation. Learning practice pending. Next: EP-r1 pack/reassess with one bounded rebalance and explicit PostgreSQL integration; draft contract remains separate. User security reports untouched. Root commits accepted scope, immediately pushes and verifies synchronization.

## V3-06 assignment EP-r1

Dependency V3-05 accepted. Shared outcome: pack/reassess only emitted evidence, one configured rebalance and explicit trusted PostgreSQL V3 integration with cumulative budgets and fresh source authorization after optional reranking. `/root/token_fixture` (gpt-6.1-sol) owns Python evidence.py/test_evidence.py and retrieval.py/test_retrieval_v3.py, and assembles. `/root/token_node_fix` (gpt-6.1-sol) owns Node evidence.ts/evidence.test.mjs, retrieval.ts/retrieval-v3.test.mjs and hybrid.ts. Root owns frozen EP-r1/shared fixtures, Python reranker profile snapshot property, manifests/exports, all other contracts/harnesses/docs/tracker/Git and serial acceptance. Peers implement native helper first, then dependent integration in their own lane; communicate interfaces/decisions directly and stop on ownership handoff. No worker tests/process/services/network/DB/install/provider calls/Git. Legacy defaults, scope/filter SQL, schema, migrations and approved inputs protected. Root resolves boundary/outcome changes and uses Astra only for unresolved material issues. State RUNNING.


## V3-06 / V3-C2 final handoff

State COMPLETE for EP-r1 helper and trusted PostgreSQL integration. Native Sol pair wrote disjoint helpers/retrievers/tests, coordinated directly, Python assembled and both stopped writes. Root inspected all changes, corrected score-validator parity and input-cap handling, and fixed two read-only review findings (fixture flag shadowing; mutable Node inference validation). Regression cases cover these failures. No remaining must-fix or unresolved Astra escalation. Changed scope: evidence modules/tests, V3 retrieval branches/config and profile snapshot property, shared EP-r1 fixtures/checkers/contract, optional export/artifact/pipeline wiring, explicit native harness additions, docs/tracker/report.

Actual final acceptance: 23 serial stages, 989 Python/tool tests, 747 Node tests, mypy over 25 files, TS typecheck/build, six EP-r1 parity cases, existing parity/16 seals, four artifacts/three guarded imports. Native direct Neon hybrid/evidence fixture passed 16 groups: legacy 18 requests plus six packed queries per runtime with strict accounting, model execution outside leases and committed post-model tombstone denial. Full normalized native parity matched; maximum two clients and cleanup_verified true. One test process, no paid call/model download/task service; snapshot 39 GiB disk/53 percent memory free on M4/16 GiB. Learning example/failure explained, practice pending. No hosted CI/registry publication/general semantic quality claim. User reports untouched/excluded. Next: V3-07 frozen six-query development calibration; protocol draft is separate pending work. Root commits accepted scope, immediately pushes and verifies synchronization.

## V3-07 assignment CAL-r1

Dependency V3-06/V3-C2 passed. Frozen protocol: evaluation/policies/V3-reviewed-span-v1.json, same six development questions, native hybrid cap 15, identical top two before/after, no score threshold tuning, strict TK-r1 packing and AS-r1 curated anchors. `/root/token_fixture` (gpt-6.1-sol) owns evaluation/runners/v3_calibration.py and tools/tests/test_v3_calibration.py, and assembles preparation/replay/metrics. `/root/token_node_fix` (gpt-6.1-sol) owns tools/check_typescript_v3_calibration.mjs and packages/typescript/tests/calibration-replay.test.mjs, implementing full Node replay/packing parity. They coordinate the exact interface directly. Root owns protocol, live executor, keys/provider dispatch/cost ledger, reports/shared inputs/tracker/Git and serial acceptance. Workers have no tests/process/network/keys/DB/install/Git authority. No held-out reads, schema, SQL or runtime source edits. Maximum six serial live calls/twelve documents, no retry, admission estimate USD 0.00786432 below this run's USD 0.01 budget, not observed billing. Root verified current primary pricing/context sources. Changes to selection/outcome/protected boundaries escalate before work; unresolved disputes go to Astra. State RUNNING.



## V3-07 final handoff

State COMPLETE for frozen six-query curated development calibration. Sol Python evaluator/Node replay pair delivered separate files, coordinated directly, Python assembled and stopped writes. Root owned live executor, independent label-based false-sufficient checks, before-packing versus packed metric separation, input preflight, no-retry failure accounting, reports and final verification. Actual offline checks: 34 Python and five Node tests, six-case strict complete-result replay parity. Five real Cohere HTTP200 calls/eight public synthetic documents; q03 empty caused no call. No retries or held-out reads. Admission estimate USD 0.00524288 < this run USD 0.01; reported 404 input units imply dated-cost estimate USD 0.00000808, actual bill unknown. Shared response replay is not independent Node inference.

Pre-packing MRR 0.7 to 0.8 and support recall 0.8 unchanged; packed MRR 0.8 both. False-sufficient 0/6, abstention 3/6, answerable abstention 1/4, conflict-error 0/1 before/after, with curated in-sample limitations. Manual inspection retained historical miss/unanswerable excerpts/conflict/filter/tenant distinctions. No model install/DB/task process; private key never printed or committed. Last resource snapshot 39 GiB/53 percent memory free. User reports untouched; learning practice pending. Next: V3-08 installed shared source/authorization/token/coverage fixtures and strict/partial examples, then final 23-stage/native/artifact checkpoint and V3 exit. Root commits verified scope, immediately pushes and verifies synchronization.

## V3-08 assignment INST-r1

Dependency V3-07 accepted and pushed. Shared outcome: clean installed wheel/npm evidence fixtures and partial/strict examples, then explicit native source/authorization acceptance through installed product modules. `/root/token_fixture` (gpt-6.1-sol) owns tools/check_artifacts.py and tools/tests/test_check_artifacts.py and assembles installer/probe/native wiring. `/root/token_node_fix` (gpt-6.1-sol) owns tools/probe_installed_evidence.py, tools/probe_installed_evidence.mjs, examples/evidence.py and examples/evidence.mjs. Peers coordinate CLI/report shapes directly; root owns other paths, shared data, docs/tracker/Git and serial actual checks. No worker processes/tests/network/install/DB/provider/key access/Git. Product runtime/schema/SQL/approved inputs protected. Preserve guarded default imports before optional installs. Run copied scripts outside checkout and verify installed product provenance. Native fixture uses copied harness/data links and installed product modules with restricted child credentials, maximum two clients and explicit dedicated-Neon/write flags. Root decides scope/boundary changes before edits; unresolved issues go to Astra. State RUNNING.


## V3-08 / V3-C3 / V3-EXIT final handoff

State COMPLETE for native evidence selection and scoped curated development acceptance. Managed Sol pair delivered installer/native wiring and both installed probes/examples in disjoint paths, coordinated directly, Python assembled and stopped writes. Root inspected all changes, added installed-import provenance guards, fixed macOS real-path CLI entry detection and extended the outer native bound for cleanup. Review reported no remaining must-fix or unresolved Astra issue. Changed files: artifact verifier/tests, installed evidence probes/public examples, native provenance guards/tests, replay CLI symlink regression, README/development/contract/version guidance and this report/tracker. No product runtime/schema/SQL/approved input changes in this slice.

Actual final verification: 23 serial stages passed with 1,033 Python/tool tests, 753 Node tests, mypy over 25 files, TS typecheck/build, existing shared conformance/development checks and 16 seals. Four archives/three guarded default imports; 216 installed source/context/token/packing/assessment/pipeline cases plus partial/strict examples compared completely. Installed-wheel/npm native fixture passed 16 groups including post-model tombstone denial, no model lease, scoped/filtered source checks and six V3 packed queries per runtime; maximum two clients, database cleanup and temporary environment cleanup true. No paid calls in this slice; V3-07 recorded five calls separately. Internal package identity 0.0.0 is not registry publication. Hosted CI, production, generalized semantic quality and cross-platform evidence remain unvalidated.

One test process/language integration suite at a time. Last pre-run snapshot 39 GiB disk/44 percent memory free on M4/16 GiB; no resource performance claim. Task processes/pools/temporary credentials/environments closed. Learning example and failure case delivered; practice pending. Both user security reports untouched and excluded. Next smallest task: V4-01 shared execution ledger before concurrent dispatch/corrective retrieval. Root commits this verified scope, immediately pushes and checks remote synchronization.

## SEC-REM-01 assignment: reconcile security audit findings

State RUNNING. User requested closure of security-report remnants before V4. Outcome: inspect every V1 issue and V2 finding against current code, identify remaining fixes and record current evidence without rewriting historical audits. Sol `security_runtime` owns only `artifacts/security-remnant/runtime-audit.md` (V1 issues 1-5 and V2 F-01 through F-04). Sol `security_deployment` owns only `artifacts/security-remnant/deployment-audit.md` (V2 F-05 through F-07) and assembles the pair. Both perform substantive read-only source/evidence analysis and message each other directly about concrete dependencies. Root owns all product/tool/test/SQL/doc/tracker edits, final remediation ledger, serial validation and Git. Original user security reports, checksummed migrations, sealed fixtures, credentials and provider calls are protected. No peer tests, services, installs, network, DB or Git. Acceptance: per-finding current evidence, explicit unresolved status, scoped fixes/regressions and final integrator checks; extend into named small child slices as needed. Escalate changed outcomes/boundaries/ownership to root before dependent work; unresolved material decisions go to Astra. Last known laptop constraint M4/16 GiB; lightweight inspection only. Learning and final handoff pending.

### SEC-REM-02 input contract hardening (NUL-r1)

State RUNNING after SEC-REM-01 source triage. Intended behavior: public identity/query/collection/string-filter parsers reject NUL with InvalidRequest before application use; exact source/evidence text keeps byte fidelity. Keep database prelease validation as defense in depth. Python Sol security_runtime owns contracts/_validation.py, contracts/models.py and a new test_request_nul.py; Node Sol security_node owns shared.ts, requests.ts and a new request-nul.test.mjs. Python assembles; root owns shared fixtures/specifications/schema/tool/tracker edits and serialized tests/Git. No worker processes, network, DB or provider calls. Acceptance: both native boundary tests, shared invalid fixture parity, source-text preservation, typechecks and regression checkpoint. Escalate policy/ownership changes before edits; unresolved material choices go through root to Astra.

### SEC-REM-03 / SEC-REM-04 owned follow-ups

SEC-REM-03 root owns security.sql, administrative wrappers and their tests: verify effective creator defaults (including absent global ACL rows), optional vector namespace/ledger/type/function privileges and extension ownership; retain an explicit, extension-member-only Neon managed EXECUTE exception. Generic migration success remains separate from deployment-security acceptance. No global default privilege mutation or applied migration change. Acceptance: focused wrapper tests, current dedicated Neon positive gate and rolled-back negative probes. SEC-REM-04 root owns native harness locale preflight/tests and runbook clarification: fail early with a fixed locale diagnostic before fixture mutation, preserve canonical fixture bytes, and triage informational pool discard against existing cancellation/cleanup evidence without suppressing warnings. Both RUNNING; one root writer, one test process, no model calls. Original reports remain preserved. Final report/tracker records scoped closure and outstanding evidence.


## SEC-REM-01 through SEC-REM-04 final handoff

State COMPLETE for scoped remediation and reconciliation before V4. [The ledger](../evaluation/reports/SECURITY-REMEDIATION.md) maps all five V1 issues and seven V2 findings to existing fixes, new fixes or informational triage. F07's historical exact warning branch remains unproven; current cancellation/cleanup behavior passed and no warning was suppressed. Supabase revalidation, pooled endpoints, production, hosted CI and publication remain separate unvalidated scopes.

Managed Sol audit pair produced complementary runtime/deployment analyses and coordinated directly; deployment assembled. Python/Node Sol writers delivered NUL-r1 in disjoint native files; Python assembled and transferred writes. Root owned schemas/shared fixtures, existing adapter-test updates, native negative harnesses, SQL/wrappers, locale preflight, docs/evidence and serial acceptance. Final read-only reviews found and root fixed extra-vector-object inventory and cleanup-ordering gaps; re-review found no remaining must-fix in scope. No unresolved material decision required Astra. Original user audit files remain preserved and excluded from commits; findings are addressed in the tracked ledger.

Changed scope: public input validators/tests/schemas and 17 shared invalid cases; source/evidence exact-byte behavior retained; deployment security SQL and both explicit wrappers; seven native rollback probes and cleanup tests; real dense CREATE negative checks in both runtimes; early FTS locale diagnostic; contract/development/storage/Neon guidance and remediation report. Checksummed migrations/setup, locks, sealed corpus/labels and platform ACLs unchanged.

Actual validation: all 23 serial stages passed, 1,141 Python/tool tests (four expected warnings for bypassed invalid models), 801 Node tests, both typechecks/build, 51 request/32 result parity cases, all shared conformance, 16 seals, four archives and three guarded imports. Dedicated direct Neon combined admin gate passed; seven negative security probes rejected exact unsafe states and rolled back with both ledgers/baseline preserved; 14 native Python/Node dense groups passed including real CREATE rejection, max two clients, cleanup verified. The first full run's older lifecycle test was updated for stricter parsing before the successful rerun. No paid calls or models. Final reader-facing prose/link/whitespace and staged-scope checks recorded before Git.

Resources: 39 GiB disk and 48 percent memory free observed on M4/16 GiB before runs; snapshots only. Restored three existing pinned PostgreSQL packages for native validation; final frozen default checkpoint removed the extras. One test process/language at a time, task pools/children/temp credentials closed. Learning example: reject NUL identities without rewriting evidence; missing global ACL rows can still imply PUBLIC grants. Practice remains pending. Next smallest product task: V4-01 shared execution ledger. Root commits verified scopes, pushes each immediately and verifies synchronization.

## V4-01 assignment EL-r1

State RUNNING; V3-08 and scoped security remediation accepted. Outcome: atomic request-local call/candidate/attempt/cost reservations and honest reconciliation before concurrent work. Python Sol v4_python owns packages/python/src/cragkit/execution.py and tests/test_execution.py; TypeScript Sol v4_node owns packages/typescript/src/execution.ts and tests/execution.test.mjs. Python assembles. Shared frozen contract contracts/EXECUTION_V4.md (EL-r1). Root owns fixtures/conformance, exports/manifests/locks, all integration/tracker/docs/tests/Git. Both peers coordinate native API/fixture dependencies directly; no overlapping edits, no worker tests/process/network/DB/install/provider calls/Git. No schema, migrations, sealed inputs or legacy retrieval behavior changes. Root serial verification: budget-slot races, cancellation, nested attempts, strict/unknown accounting, typechecks and native transition parity. Escalate outcome/protected boundary/ownership changes to root before edits; unresolved material decisions to Astra. One test process; initial prior M4/16 GiB limit, fresh resource check before optional installs. Learning pending. Full V4 remains planned until its ordered tasks pass.

### V4-01 local acceptance

EL-r1 native pair assembled and transferred writes. Root inspected both modules, added nine shared transition cases/probes and the optional Node execution export, and verified six Python tests, nine Node tests, strict mypy over 26 files, Node build and all nine complete native transition outputs. Covered final-slot races, nested attempts, deadline cleanup, ownership, strict unknown/overbound accounting and sticky unknown usage. No DB, SDK/model install or provider call. State COMPLETE locally for ledger; whole-version checkpoint remains pending. Next dependency V4-02 can proceed. Initial resource snapshot 39 GiB disk/41 percent memory free; one test process. Learning practice pending.

## V4-02 assignment QP-r1

State RUNNING after V4-01 acceptance. Pair shared outcome: optional planner selects only trusted, identifier-preserving variants for missing facets, with EL-r1 accounting and safe fallback. Python Sol v4_python owns planning.py/test_planning.py and assembles; Node Sol v4_node owns planning.ts/planning.test.mjs. Root owns QP-r1 contract/shared fixtures/probes, exports, checks/tracker/Git. Same no-worker-process/network/DB/provider/SDK/Git constraint. Direct peer coordination required on APIs/output/fallback; root decides boundary/outcome changes first. Existing retrieval/storage/migrations/sealed inputs protected. Acceptance: malicious/malformed/oversized output, invented intent/scope/facet, exact identifiers, source-independent planning, unknown usage, configured fallback, timeout/cancel and native parity. No paid calls or local models.

## V4-03 assignment CR-r1

QP-r1 focused acceptance passed (six Python planner tests, eleven Node planner groups, both typechecks/build); root is adding shared fixtures/checkpoint integration. V4-03 RUNNING: native CorrectiveRetriever retains bounded candidates, applies trusted missing-facet variants and freshly authorizes/repacks evidence with fixed original scope/filter/policy. Python Sol v4_python owns corrective.py/test_corrective.py and assembles; Node Sol v4_node owns corrective.ts/corrective.test.mjs. Root owns CR-r1 contract/shared fixtures, exports/manifests, final integration/checks/docs/tracker/Git. Independent trusted PostgreSQL backend lane will own only new backend modules/tests after matching the frozen interface. Same worker no-process/network/DB/install/provider/Git constraints. Implement V4-03 core first; report ready for focused verification before V4-04 transient/no-progress extension. Core basic loop must already be bounded by attempts/subqueries/deadline. Protected existing retrieval/SQL/source behavior remains unchanged; no migrations/sealed-input edits. Escalation to root then Astra if unresolved.

V4-03 backend lane: Sol v4_framework_research owns only new Python postgres_corrective.py/test_postgres_corrective.py and Node postgres-corrective.ts/postgres-corrective.test.mjs. Shared outcome CR-r1 native search/capture on existing session/fusion/source/rerank boundaries; direct dependency coordination with both core peers. Root final integrator; no worker processes/network/DB/Git. Existing SQL/migrations/retrieval protected. Native acceptance and fixture harness remain root-owned. Backend IMPLEMENTED_UNVALIDATED until serial local/native checks pass.

### V4-03 focused gate / V4-C1 preparation

CR-r1 original/targeted paths and trusted PostgreSQL backend passed 32 focused Python tests and 43 Node tests across V4 modules, strict mypy over 29 files and Node build. Retained evidence is freshly reauthorized; overridden rerank results are validated before packing, model calls hold no DB lease, duplicate revision snapshots are deduplicated with actual byte charges retained. Native DB and shared full-loop parity remain pending. V4-03 COMPLETE locally; C1 combined gate follows the shared fixtures. Review-driven EL-r1 close() revokes late dispatch even for cancellation-ignoring callbacks. No provider/DB call in these fake-driver checks.

## V4-04 assignment: CR-r1 termination and faults

State RUNNING after V4-03 focused acceptance. Same native pair owns only corrective.py/test_corrective.py and corrective.ts/corrective.test.mjs; Python assembles. Implement remaining frozen CR-r1 repeated normalized query/candidate detection, configured no-progress termination, transient-only bounded retries/backoff, exhaustion and permanent-error/cancellation distinctions. Every retry consumes ledger attempt/candidate/call reservations; no scope/filter change or stale result fallback. Root owns fixtures/contract/exports/checks/evidence/tracker/Git; backend lane stopped and root-owned. No worker processes/network/DB/SDK/provider/Git. Directly resolve parity/stop precedence with peer; root handles protected changes, Astra only unresolved material decisions.

V4-03 native-fixture preparation lane: Sol v4_framework_research now owns only tools/check_corrective_native.py and tools/check_typescript_corrective_native.mjs. It prepares existing restricted-parent hybrid fixture hooks and six reviewed development-query ablations; root owns all parent/child wiring, tests, actual database execution, evidence/tracker/Git. No worker DB/process/network/SDK/model/Git calls. Shared native backend and core interfaces remain root-owned/frozen except the explicitly assigned V4-04 core extension. Source/label seals and existing seed fixtures protected. This harness preparation does not mark V4-08 acceptance complete.

V4-04 security review follow-up: fresh authorization now follows planning even on empty/fallback/repeated-query output. Sol peers disagreed on a capture-time ranking admission refusal; bounded Astra v4_budget_escalation inspected contracts/architecture and recommended the existing bounded-result policy over a new public error. Root adopted terminal empty packing with budget limitation, no stale/unranked release, no further capture/dispatch, preserved ledger usage and operational-error precedence. Same core pair owns focused correction/tests; root owns contract, final checks/tracker. No scope/cost/permission expansion. The first native mechanics pass (18 groups, 20 Python/20 Node cases, cleanup verified) precedes this final correction and is not final source acceptance.

### V4-C1 / V4-04 local acceptance

Final local correction/fault gate passed: 27 Python corrective tests, 24 Node corrective groups, strict mypy over 29 files, Node build and 40 complete shared cases (EL 10, QP 13, CR 17). Three post-planner revocation paths and terminal capture admission are covered; source/call budgets and operational errors remain distinct. C1 and V4-04 COMPLETE locally. The earlier native 18-group run passed cleanup but predates the final planner/capture corrections; final native acceptance remains required before V4 exit. No new external calls occurred in this focused gate.

## V4-05 assignment EV-r1

State RUNNING after C1/V4-04 local acceptance. Shared pair outcome: bounded redacted event queue, explicit bounded off-path export, honest drop counts and no raw query/source data. Python Sol v4_python owns new events.py/test_events.py and assembles; Node Sol v4_node owns new events.ts/events.test.mjs. Frozen EV-r1 in EXECUTION_V4.md. Root owns both corrective integration hooks/tests, shared sink fixtures, exports/checks/docs/tracker/Git. No worker processes/network/SDK/DB/provider calls/Git. Direct peer API/ordering coordination, no overlap; escalation root then Astra if needed. Exporters are async cooperative callbacks, never invoked by emit/retrieval; no automatic background service. Acceptance: queue overflow, failing/hanging exporters, no unbounded overlapping flush, secret canaries, stable event ordering and retrieval unaffected by sink failure/drop.

V4-05 ownership transfer: after sink assembly, root transferred corrective.py/corrective.ts and new dedicated corrective-event test files to their native peers for hook integration. Python assembles; root retains shared fixtures, manifests, tracker and verification. Event signatures and drop semantics approved as proposed; Node must close the ledger immediately on terminal capture admission refusal. No worker checks/processes.

### V4-05 local acceptance / V4-06 AD-r1 assignment

EV-r1 COMPLETE locally: root inspected hooks and bounded sinks; 51 focused Python tests, 50 Node groups, mypy 30 files, TS build, CR 17 and EV four complete parity cases passed. One Node test helper initially invoked a hostile getter before the sink; corrected construction and rerun passed. No inline exporter or new provider/DB call. V4-05 changes remain part of the pending focused commit. Resource snapshot: 39 GiB disk, 42 percent memory free; one suite/process.

V4-06 RUNNING after V4-05 acceptance. Select LangChain Core 1.7.0 Python / 1.3.0 Node via AD-r1 in EXECUTION_V4.md; separate optional packages protect core imports. Python Sol v4_python owns packages/langchain-python/src/cragkit_langchain/__init__.py and assembles. Sol v4_framework_research owns packages/langchain-python/tests/test_adapter.py, substantive adversarial SDK tests; coordinate directly on frozen API before writing. Root owns manifests/locks/shared fixtures, all installs/checks/reports/tracker/Git. V4-07 implementation waits for V4-06/C2. Workers no processes/tests/install/DB/provider/Git; read pinned installed SDK sources after root installs. Shared outcome scope-bound native StructuredTool, guarded async invocations, final serializer recount, no ambient tracing/default callbacks, cancellation. Existing core/migrations/sealed inputs protected. Root decides protected/outcome/ownership changes, Astra only unresolved material decisions. Full V4 remains pending final suite, native rerun and adapter packaging.

V4-03/04 review regression follow-up: Node Sol found that dynamically remaining hybrid work below the mandatory branch count could dispatch a ledger call before configuration rejection. Root owns the pre-dispatch backend fix in both runtimes. Node Sol owns only new test_corrective_branch_budget.py and corrective-branch-budget.test.mjs (five direct matrix cases plus one full-loop case each); writes now stopped, unrun. Preserve originally invalid configurations as InvalidRequest, dynamically insufficient work as BudgetExhausted, and all required branches/filters. Native run started before this correction; final source evidence must rerun. No provider/DB dispatch is permitted for a rejected admission.

V4-03/04 branch-admission correction COMPLETE locally: six Python and six Node new regression cases passed; all 27 core stages reran successfully after the fix (1,212 Python/tool, 878 Node tests, mypy 30 source files, both builds/typechecks, all parity/seals and four archives/three guarded imports including installed V4 44 cases). Demonstration command with full outcomes also passed. Second native pass before this last fix passed 18 groups/20 native cases each and cleanup; final source refresh remains pending.

### V4-06 / V4-C2 local acceptance; V4-07 assignment

V4-06 and C2 COMPLETE locally: root inspected the real SDK adapter and assembler/test artifacts, then passed strict mypy for its source and 72 real SDK tests. Shared tool/result fixtures and an actual corrective-engine targeted recovery preserve the full direct result and trusted authority. Privacy checks enabled ambient tracing under network denial; strict final SDK message recount, oversized wrappers, native cancellation/deadline, redacted failures and alternate paths passed. Initial type failures exposed SDK overload differences; explicit unsupported boundaries were corrected without weakening validation. Clean installed SDK artifacts remain a version-exit check. No model/paid call or background service.

V4-07 RUNNING after V4-06/C2. Node Sol v4_node owns only packages/langchain-typescript/src/index.ts and assembles. Python Sol v4_python owns packages/langchain-typescript/tests/adapter.test.mjs, complementary substantive real-SDK/shared-engine tests. AD-r1 same shared outcome and authority/privacy/count/cancellation constraints; direct peer API coordination. Root owns manifests/locks/installs/shared fixtures/checks/evidence/tracker/Git. No worker processes/tests/network/SDK install/provider/DB/Git. Test fixtures/tokenizer support explicit environment paths for isolated artifact acceptance. Source/config/migrations/sealed inputs outside optional package protected. Root resolves boundary changes; Astra only unresolved material escalation.

### V4-07 local acceptance and final SDK review

V4-07 COMPLETE: root inspected the assembled Node source and real SDK tests. The first 34-stage version run passed (72 Python SDK / 66 Node SDK); independent Sol review then found a forged AbortError message leak and closed-counter pre-dispatch gap. Native peers resolved both directly, added three Node regressions and stopped writes. Root reran all 34 stages successfully against final source: 1,216 Python/tool and 878 core Node tests; 72 Python and 69 Node SDK tests; both native/SDK typechecks/builds, complete shared parity/seals, core four archives/three guarded imports, installed core 216 evidence plus 44 V4 cases, optional four archives with 72/69 SDK tests repeated in isolated installed environments. SDK locks/version/integrity and import origins passed. No live model/paid call or new service. [Adapter evidence](../evaluation/reports/V4/V4-06-07.md).

V4-08 final DB evaluation remains RUNNING. A final-source attempt failed honestly at the existing hybrid deadline; cleanup completed with an informational connection discard, no suppression/deadline increase. Its retry was interrupted by the user; inventory found exactly one task-owned role, 12 fixture policies and two fixture collections, with the advisory lock free. Root removed only that exact fixture in a transaction, verified both histories unchanged and all fixture tables/roles/policies empty, then restarted native acceptance after the successful 34-stage final check. Current resource snapshot: 38 GiB disk/54 percent memory free on M4/16 GiB; snapshots, not performance guarantees. Original untracked security reports preserved. Full V4 is pending the final DB result and exit report; no V5 implementation started.

## V4 final handoff

V4-01 through V4-08, C1-C3 and EXIT COMPLETE for the internal native/synthetic milestone. Final 34-stage acceptance passed: 1,216 Python/tool, 878 core Node, 72 Python SDK and 69 Node SDK tests; both native/SDK types/builds; complete conformance and 16 seals; four core plus four optional archives; installed 216 evidence/44 V4 cases and 72/69 real SDK tests. Final direct Neon source run passed 18 groups, 20 corrective cases per runtime, full result parity, max two clients and verified empty cleanup; stderr empty. Prior deadline failure/interruption and exact fixture cleanup are retained in the exit report. Default frozen sync removed PostgreSQL extras afterward. No paid model, hosted CI or publication claim.

Six reviewed development questions showed no recall gain from correction (0.8 document/facet recall, same reciprocal rank/nDCG in all modes), with six/11/17 synthetic calls for hybrid/reranked/corrective respectively. Correction stays opt-in. Weak-query recovery is mechanics-only; variants are label-derived, no held-out scoring. [Machine results](../evaluation/reports/V4/V4-08-results.json) include source/archive hashes, metrics, footprint and run history.

Root integrated Sol writer/test pairs with direct peer coordination and named assemblers, plus independent review; one Astra budget-policy escalation resolved within scope. Final implementation fixes and regressions accepted. Core commit beaa41b and optional SDK commit a3fe3d3 were pushed immediately and verified synchronized. Final report/prose/link/scope review precedes the exit evidence commit/push. Original two untracked security reports remain user-owned and excluded. All task test processes/pools/temp credentials closed; no persistent service started. Latest snapshot M4/16 GiB, 38 GiB disk / 54 percent memory free; snapshots only. Learning exercise unassessed, no implementation gate remains. Next smallest action: V5-01 consistency specification before store-adapter coding.

## V4 readiness recheck assignment

V4-READINESS RUNNING: user asked whether V5 can begin or V4 has remaining work. New local untracked AUDIT-V2-V4.md is review input, preserved with the original V1/V2 reports. Shared outcome: distinguish accepted V4 features from newly reported harness follow-ups and identify the next authorized slice. Two gpt-6.1-sol read-only peers: v4_readiness_harness owns cleanup source/test-gap verification and assembles; v4_readiness_exit owns plan/exit/evidence reconciliation. No writable peer paths, edits, tests, processes, network/DB calls or Git actions. Peers coordinate concrete dependencies directly; root integrates findings and owns readiness note/tracker/prose/Git. Source baseline f91eb37. Preserve product contracts, credentials, histories, user reports and existing evidence; Astra only if a material disagreement remains.

### V4 readiness recheck handoff

Assessment COMPLETE, follow-ups OPEN. Root integrated the read-only Sol pair and independently confirmed 14 source hashes, saved 34-stage acceptance, passed core/SDK artifact reports and the saved native 18-group cleanup success. Current source confirms generic cleanup diagnostics and missing parent-harness recovery coverage; new audit reports repeated cleanup failure, but this turn did not reproduce it or inspect live DB state. No demonstrated new product vulnerability. Next smallest implementation task: V4-AUD-02, then V4-AUD-01; V5-01 consistency design may proceed, with backend coding/native acceptance after these follow-ups. No tests, DB/provider calls, services or installs ran; resource use was small local reads/hash/prose checks, no new capacity claim. Learning example: recovery must converge on exact owned resources; practice unassessed. Three user-owned untracked audits preserved/excluded. Only readiness note/tracker changed; root owns prose/link/consistency checks and scoped commit/push.

## V4 audit remediation and comprehensive verification assignment

User authorized completion of current-version follow-ups and comprehensive security/unit/black-box/white-box verification. V4-AUD-02 RUNNING first: shared outcome D-r1 redacted primary/cleanup diagnostics in contracts/HARNESS_RECOVERY_V4.md. Sol diagnostic writer owns only tools/runtime_diagnostics.py and assembles; Sol test peer owns only tools/tests/test_runtime_diagnostics.py. Root owns parent/CLI integration/tests, contract, tracker, security coverage matrix, all actual processes/checks/native DB/Git. A separate Sol read-only security lane maps requirements/black-box/white-box gaps and production gates before targeted tests. Peers coordinate APIs directly, no overlapping edits; root handles protected/outcome changes, Astra only unresolved material escalation. Worker tests/process/network/DB/install/provider/Git forbidden. Preserve all three user audit files, sealed inputs, migrations, optional core dependencies and private configuration. One test process, suites serial; fresh resource snapshot M4/16 GiB, 38 GiB disk and 54 percent memory free. V4-AUD-01 recovery follows D-r1 focused acceptance. No production deployment/publication or paid model run is inferred from test authorization.

### V4-AUD-02 focused acceptance

D-r1 COMPLETE locally: root integrated the managed helper/test pair and parent CLI, inspected fixed labels, bounded records and detached snapshots, and passed 92 focused module/CLI tests. Includes simultaneous original/cleanup failures, success followed by cleanup failure, native cancellation, timeout, SQLSTATE, credential/query/SQL canaries, malformed input and hostile exception descriptors including __class__. Inner cancellation remains available to the cleanup timeout rather than being swallowed. No DB/provider/service/install work occurred. Full combined/native acceptance follows V4-AUD-01; old readiness report remains a dated pre-remediation snapshot. Changed scope: runtime_diagnostics.py, its independent tests, parent harness/CLI tests, frozen contract and tracker. Root owns serial acceptance/Git; all worker writes stopped.

## V4-AUD-01 R-r1 assignment

RUNNING after D-r1 92-test acceptance. Shared outcome: durable exact-ownership journal and bounded fresh-connection recovery, including interruption/replay security. Sol audit_diagnostics_impl now owns only new tools/runtime_recovery.py and tools/tests/test_runtime_recovery.py (stdlib journal/orchestrator) and assembles. Sol audit_diagnostics_tests now owns only new tools/runtime_recovery_postgres.py and tools/tests/test_runtime_recovery_postgres.py (optional SQL transport and focused fake-SQL tests). Frozen R-r1 in HARNESS_RECOVERY_V4.md; peers coordinate interfaces directly. Root owns all parent/CLI integration, actual native interruption probes and serial tests/security gates, contracts, reports/tracker/Git. Both lanes substantive, no overlapping edits; D-r1 files transferred to root. Workers no tests/process/network/DB/SDK/install/provider/Git. Protected schemas/migrations/legacy product contracts/sealed corpus and user audit files unchanged. Root resolves boundary/ownership changes; Astra only unresolved material decisions. R-r1 may be split into persistence, transport and parent/native acceptance child slices; parent remains unvalidated until all pass.

### V4-AUD-01 child-slice integration checkpoint

R-r1a persistence/orchestration and R-r1b optional PostgreSQL transport are integrated; R-r1c parent/CLI/native driver is integrated with final version acceptance pending. Each child owns at most four implementation/test files; root owns the three parent/CLI/driver paths after peer writes stopped. Focused diagnostics/recovery/CLI acceptance passed 186 tests. Native seven-case fault acceptance passed SIGKILL, removed-journal refusal, repeat cleanup, old administrator loss, failed first connection, proven closed recovery connection, and unavailable-then-explicit recovery; pre-existing role/profile/history snapshots matched. Both base native Python and Node runtime suites passed eight groups each, cleanup verified and stderr empty. Deployment security and seven rolled-back remnant probes passed. Four package-manager audits reported no known advisories (Python 34/47 packages, Node 39/38 dependency entries).

The first native staging cleanup refused an automatic grant of the fixture role to its creating administrator. Read-only inspection confirmed safe role attributes, no outbound membership and inbound membership only for the configured current administrator. Root corrected only that membership direction check and explicitly recovered the retained journal. Independent review also fixed remaining-client closure after one close fails, bounded child reaping, early TLS-handle ownership and actual-driver closed-connection retry classification. Two larger native hybrid attempts then failed honestly at an evaluation deadline/provider-unavailable path with cleanup completed; redacted timing diagnosis is running before any workload/configuration adjustment. One overlapping administrative start was refused by the advisory lock before mutation; subsequent commands are serialized. These are retained failures, not passing acceptance. No paid model call, core API/migration/ACL change, production or publication action occurred. Latest M4/16 GiB snapshot: 38 GiB disk and 56 percent memory free; no capacity guarantee. Full local/installed V4 acceptance and final native disposition remain required before follow-up closure.

### V4-AUD-01 acceptance-profile child assignment AP-r1

Current default-25-second full native evaluation failed under measured repeated ~230 ms execute round trips; the same product previously recorded much lower end-to-end medians. Keep these failures and do not treat a later functional pass as a baseline performance pass. Root approved an explicit bounded high_latency_admin 60-second evaluation profile, with unchanged product defaults, fixed samples/candidates/calls, short fault probes and cleanup 25. Native performance targets remain V6 work. This changes administrative acceptance configuration, not release behavior or production readiness.

Sol audit_diagnostics_impl owns AP-r1a Python hybrid/evidence/corrective harness helpers (three files) and assembles. Sol audit_diagnostics_tests owns AP-r1b Node hybrid/corrective native helpers (two files). Same shared outcome, frozen AP-r1 and direct dependency coordination; root owns parent flag/tests/contracts/tracker/final checks and Git. Previous recovery source/test ownership transferred to root. No peer processes/tests/network/DB/install/provider/Git. Run source/installed acceptance serially after integration. Root retains final decision; unresolved material disputes go to Astra.


## V4 comprehensive verification final handoff

V4-AUD-01/R-r1a-e and V4-AUD-02 COMPLETE for the internal native/synthetic milestone. Root integrated substantive Sol persistence/SQL peers and Python/Node acceptance-profile peers, with direct dependency coordination and named assemblers; independent read-only security review informed closure ordering, credential lifetime and full deletion-graph checks. No unresolved material disagreement required Astra. All worker writes stopped; root owns final integration and Git.

Final source checkpoint passed all 34 serial stages: 1,405 Python/tool tests (four expected invalid-model serializer warnings), 878 core Node tests, 72 Python SDK and 69 Node SDK tests, native/SDK types/builds, complete conformance and 16 seals. Eight archives, three guarded imports, installed 216 evidence/44 V4 cases and repeated installed SDK 72/69 passed. The first comprehensive Python pass found a test-only module reload/exception-identity split (eight failures); shared imports plus a regression corrected it before the full rerun. All 14 prior core/SDK source/lock hashes are unchanged.

Final direct native acceptance passed 22 groups with V3 evidence and 20 corrective cases per runtime, exact Node parity, two clients maximum, verified cleanup and empty stderr. Explicit profile: external 60 seconds and effective request policy 60,000 ms; parent/child 1800/960 seconds, cleanup 25 seconds, temporary role expiry 1920 seconds. Default request policy 10,000 ms is unchanged. The earlier external 25/default-effective 10,000 ms attempts and first ineffective AP-r1 override failed honestly; a filtered slow-call diagnostic did not establish an unbiased latency distribution or a unique historical cause. One pre-final AP-r2 run was deliberately interrupted to align role expiry with its longer bound; cleanup completed. These results remain in the run history; the profile pass does not establish default-budget performance.

Native recovery passed ten groups: real SIGKILL, removed-journal refusal, repeat cleanup, administrator/connection loss and bounded retry, unavailable-then-explicit recovery, exact role/membership/profile/history preservation, plus unexpected collection FK, leaf FK and optional-vector DELETE-trigger refusal with canaries preserved. Both base runtime suites passed eight groups each. Post-run deployment security and all seven rolled-back remnant probes passed. Final read-only inventory: all nine fixture tables empty, zero probe roles/policies/hidden columns/journals, lock available/released, history hashes recorded. Unknown lifecycle relations/deletion graphs require operator inspection; no automatic extra-table drop.

Four refreshed dependency audits reported no known advisories: Python 34/47 packages and Node 39/38 dependency entries. npm verified 20/37 registry signatures and 2/7 attestations for installed core/SDK graphs. Native PostgreSQL extras were removed with frozen sync after checks, and the isolated default import test passed. No paid model call, model-runtime install, persistent service, production action or publication occurred. Last resource snapshot M4/16 GiB: 38 GiB disk and 56 percent memory free; observations, not capacity guarantees. Three user-owned audits remain unmodified/untracked/excluded.

Changed paths: administrative diagnostics/recovery modules and their tests; parent/CLI/native fault driver; hybrid/evidence/corrective Python and Node acceptance helpers/profile regression tests; harness contract; development recovery/profile instructions; E82; tracker; current verification/machine evidence and historical-ledger pointers. No product source, manifests/locks, migrations, permanent grants or sealed inputs changed. [Full report](../evaluation/reports/V4/V4-SECURITY-VERIFICATION.md), [machine results](../evaluation/reports/V4/V4-SECURITY-RESULTS.json). Default-budget performance, held-out/live-model quality, V5 integrations and V6 production/release gates remain explicit. Learning exercise unassessed: explain why an external 60-second deadline still stops at10 seconds under a default 10,000 ms request policy. Next smallest authorized task: V5-01 consistency specification before backend coding. Root completed the final independent source/evidence review, zero-hit/low-density prose inspection, unchanged deterministic cleaning and 274 local Markdown target checks. All task-owned processes/pools/temporary credentials closed; latest free-memory snapshot was 55 percent with 38 GiB disk. Root owns the scoped commit, immediate push and synchronization check; the final response records that result.

B2b/B3 validation resumed: no prior task processes or worker agents remained live. Root found the Python native ACK injector observed execute(COMMIT), while psycopg commits through transaction.__aexit__; corrected the injector to withhold only a successful actual transaction exit. Fresh Python native run partial-native-02 started. Managed Sol pair: partial_protocol owns only tools/tests/test_qdrant_partial_repair_native.py; partial_review owns only artifacts/V5/V5-04G1/partial-source-review.md and assembles source/coverage review. Shared outcome actual partial repair safety; root owns all existing/shared/product files, execution, tracker and Git. No worker tests/process/network/DB/Git. Direct peer dependency resolution required; protected-boundary changes go to root, unresolved material issues to Astra. Acceptance remains pending; full V5 remains open.

### V5-04G1b B2b/B3 final handoff

COMPLETE for native single-node stage repair. Root integrated the prior Python/Node implementation pair, a new Sol protocol/source-review pair with direct coordination and named assembler, and bounded Astra callback-lifetime advice. All worker writes stopped. Actual 16 partial-repair cases passed after fixing the Python transaction-exit ACK injector; final fixture assertions also check the exact missing point, two ordinary replay batches and unchanged foreign owner. Full suites passed 2,412 Python/tool (four existing warnings) and 1,227 Node; strict build/mypy over 46 files and five protocol guards passed. Native regressions passed 18 existing repair, 50 durable recovery and 10 session transport cases, with cleanup verified. 16 seals and six migration/audit hashes unchanged. [Report](../evaluation/reports/V5/V5-04G1b-B2b-B3.md).

Changed paths: native writer/recovery/public-manager sources and tests in both runtimes; partial-repair parent/shared/native consumers and protocol tests; QW contract; development/publication docs; report/tracker. Root fixed Node callback deadline retention without weakening actual session drainage; cancellation/deadline/late-settlement tests passed. No paid provider/model/install/hosted mutation/release. Final successful fixture data removed; all task-owned processes/listeners absent. Earlier failed fixture data remains private/ignored for diagnosis. Resource 39 GiB disk / 60 percent free memory, observations only. Learning exercise unassessed: explain why current-credential readback cannot settle a still-possible late write. Root owns final prose/link/staged review, commit/push/sync. Next smallest task: G2a, freeze bounded current-security-replica projection and authority-first public security workflow before separate runtime writers; then G2 convergence, G3 tombstone/purge, H and remaining V5 gates. Full V5 remains active and incomplete.

### V5-04G2a assignment

G1b commit 42f9ce02da12b88863210ed77d71a90e8fd4cc79 pushed; exact remote/main match and 0/0 synchronization verified. G2a RUNNING before runtime edits. Shared outcome: bounded current-security-replica convergence design with immediate authority-first revocation/deletion, original identity, honest pending state and native runtime parity. Sol partial_review owns only artifacts/V5/V5-04G2/DESIGN.md and assembles; Sol partial_protocol owns only artifacts/V5/V5-04G2/TEST-PLAN.md. Both inspect actual existing writer/recovery/source/schema, communicate concrete dependencies directly and report gaps. Root owns shared contract, tracker, product files, execution and Git. No peer tests/processes/services/network/DB/Git. Migrations, existing source authority, sealed inputs, user audits and architecture boundaries protected; changes to outcome/boundaries/ownership require root, unresolved material choices go to Astra. No G2 implementation or native acceptance claimed. One writer will freeze the contract before dependent Python/Node lanes. Resource limits unchanged.

G2a design pair stopped/transferred both artifacts; no product proof is inferred. Root froze G2a1 authority-only exact security confirmation in QW, then assigned complementary runtime peers: Sol partial_protocol owns Python writer/tests and assembles; Sol partial_review owns Node writer/tests. Both now stopped/transferred all four paths. Root owns existing native writer consumers, execution and integration. Focused integration found two test-double issues: Python static role-policy SQL was mistaken for backend data reads; Node destroyed-connection rollback was not modeled. Root corrected those assertions/doubles. Root also found Node's shared transaction helper could classify COMMIT statement-cancellation as commit-unknown; a security-only opt-in preserves cancellation without altering other mutation defaults, with three COMMIT-boundary regressions. Focused 157 Python / 85 Node passed. Actual disposable PostgreSQL writer parent passed 62 checks (SQL plus both runtimes), including real lost tombstone COMMIT replies and superseded security retry; cleanup verified. Full suites and final G2a1 report/commit pending. G2a2 public authority admission and G2b/c physical convergence remain unimplemented.

G2a1 final acceptance COMPLETE: full 2,428 Python/tool tests (four existing warnings), 1,245 Node tests, strict build and mypy over 46 source files passed. Native writer acceptance passed 62 checks with verified cleanup, including actual tombstone COMMIT reply loss and exact historical retry. 16 sealed inputs and six protected migration/audit hashes unchanged. All four peer paths transferred; root owns final source review, prose/link checks, scoped commit/push/sync. Changed scope: both writer sources/tests, existing native writer consumers, QW contract, development guide, report/tracker. No persistent services, model/provider/install/hosted/release action. Source-only design artifacts remain local, not implementation proof. Learning exercise unassessed. Next G2a2 must make public authority admission independent of a physical operation; G2b/c, G3, H and later V5 tasks remain required. Full V5 goal active.

### V5-04G2a2 assignment

G2a1 commit 6f79e207bd4d613aca23a92a816639a5852f6327 pushed and synchronized 0/0 with exact remote match. G2a2 RUNNING under frozen QW independent security manager contract. Shared outcome: separate authority-only public security admission that cannot wait behind physical publication admission or recovery gate, with honest durable flags, scoped callback, native execution and bounded resource lifetime. Sol partial_protocol owns only new Python _qdrant_security.py / test_qdrant_security.py and assembles; Sol partial_review owns only new Node qdrant-security.ts / qdrant-security.test.mjs. Root owns existing exports, shared contracts/fixtures, native tools, all execution, tracker and Git. No peer tests/processes/services/network/DB/Git. Existing manager/writer behavior, migrations/role maps, sealed inputs and user audits protected. Direct peer API/dependency resolution required; outcome/boundary/ownership changes go to root, unresolved material issues to Astra. Public wrappers and native acceptance remain unvalidated until root integrates. Separate borrowed writer objects may share one bounded pool, keeping source transitions independent of physical operation slots.

G2a2 final handoff COMPLETE for independent authority admission. Sol Python/Node peers delivered separate new module/test paths and coordinated callback-error parity directly, with Python assembly and all writes transferred. Root added optional exports, public native writer consumers, safe location-only parent diagnostics and an unowned-directory regression. Full suites passed 2,449 Python/tool (four existing warnings) and 1,266 Node, strict build/mypy over 47 source files; focused 20 Python and 21 Node passed. Actual SQL/Python/Node native writer acceptance passed 68 checks, including both public methods under a blocked backend and uncertain purge reservation, preserving owner/pending facts; genuine COMMIT reply loss, one-attempt accounting and borrowed writer lifetime passed. Initial gate injection lacked the required epoch advance and was rejected; corrected setup passed without weakening SQL guards. [Report](../evaluation/reports/V5/V5-04G2a2.md).

Changed scope: new native security modules/tests, optional publication exports, native writer parent/consumers and protocol regression, QW, usage/development docs, report/tracker. Native successful fixtures and listeners/processes closed; earlier failed runs retain private redacted evidence. No Qdrant service, physical fencing/convergence/purge claim, provider/model/install/hosted/release action. 16 sealed inputs and six protected migration/audit hashes unchanged. Resource 39 GiB disk / 53 percent free memory, observations only. Learning exercise unassessed. Root owns final prose/link/staged review, scoped commit/push/sync. Next smallest required action: G2b1 freeze bounded current-security claim projection/readback and full-document enumeration, then security-bound old-owner settlement/handoff before G2c convergence; G3, H and later V5 gates remain open. Full V5 goal remains active.

### V5-04G2b1 assignment

G2a2 commit bea8f4c08f19b7e4785c70613766b42b230ac1c0 synchronized with exact GitHub main and 0/0. G2b1 RUNNING under frozen QW read-only projection contract. Sol partial_protocol owns Python writer and existing writer tests, and assembles; Sol partial_review owns Node writer and existing writer tests. Shared outcome: opaque current-security projection of all claimed generations with raw set/overflow checks, original full stage validation, scoped transaction-local RLS binding, current payloads and fresh revalidation. Root owns contracts/shared fixture/native tools, all execution/tracker/Git. No worker tests/processes/services/network/DB/Git. Migrations/role maps, source-release semantics, controller/recovery/proof APIs, sealed inputs and user audit files protected. No callbacks/HTTP in SQL or stage fence rebasing. Direct peer coordination required for exact hash/data/error parity; outcome/boundary/ownership changes go to root, unresolved material reasoning to Astra. Root independently verified staging locks document before claim insertion; actual two-connection lock proof remains required. 64 generations/2,048 IDs and 64 MiB reconstructed source/manifest ceiling are explicit support bounds, not measured capacity. Native acceptance and parent G2 remain pending.

G2b1 final acceptance COMPLETE. Sol peers delivered native writer/test pairs, coordinated exact data/hash/error/overflow semantics directly and transferred all paths; Python assembled. Root implemented native consumers/observation validation and actual two-connection staging-lock proof, corrected nominal Python vector-identity revalidation and strengthened its loader fixture to reconstruct fresh capabilities. Full suites passed 2,477 Python/tool (four existing warnings) and 1,285 Node; focused 196 Python writer/parent and 104 Node writer cases, strict build/mypy over 47 files passed. Actual SQL/Python/Node writer acceptance passed 78 checks with identical 14-point/seven-generation projection observations and hash, independent hash recomputation, pg_locks wait, fresh inventory/authority rejection and preserved stage outcomes. [Report](../evaluation/reports/V5/V5-04G2b1.md). Schema/role/controller/owner APIs unchanged; no HTTP/provider/model/install/hosted/release work. 16 seals / six protected migration/audit hashes matched. Root owns final prose/link/staged review, scoped commit/push/sync and resource inventory. Learning exercise unassessed; full G2/V5 remain active and incomplete.

G2b2 source-decision gate: root escalated actual SQL feasibility to Astra. Inspection corrected two earlier design assumptions: recovery=true journals may be inserted under a denied old intent (0002 guard_dispatch ordinary-state checks apply only to nonrecovery), and E2 read-only stage projection reconstructs current payloads without original stage publication fences; the stage dispatcher imposes those fences. Selected path A: separate private security-bound recovery plans/receipts tied to BOTH old owner/journal context and current security projection, preserving old facts. Existing guards appear sufficient; no migration is justified without a concrete native failure. Do not weaken settlement to mere quiescence/present-subset/stale ACL observations. Require exact current full inventory (or exact scoped absence for tombstone/purge), reject immutable corruption/extras, preserve current-credential uncertainty and foreign global blocks. Next smallest G2b2a is actual restricted-supervisor SQL proof for denied-owner recovery reservation plus cross-generation membership; then bounded full-document inspection/readback, private plans/dispatch and receipt settlement/handoff. Actual runtime/native evidence remains required; Astra inspection alone is no permission proof.

G2b1 resource/cleanup inventory: no task-owned database/Qdrant/acceptance process remains; successful native fixture cleanup verified. Snapshot 39 GiB disk / 65 percent system memory free, observations only. Existing three user-owned audit files remain unchanged, untracked and excluded.

### V5-04G2b2a assignment

G2b1 commit 548abb772a4ed2d65569c950310109348932f842 pushed and synchronized 0/0 with exact GitHub main. G2b2a RUNNING under frozen QW SQL permission gate. Sol partial_protocol owns tools/qdrant_recovery_dispatch_sql.py and tools/check_qdrant_recovery_dispatch_sql.py and assembles; Sol partial_review owns tools/tests/test_qdrant_recovery_dispatch_sql.py. Shared outcome: actual rollback-only denied-owner recovery journal plus two-generation membership proof with restricted roles and explicit synthetic completion scope. Keep default B0 behavior/label unchanged; add opt-in --security-owner and run_security_probes/SECURITY_CHECKS. Root owns contract/tracker, actual runs, final integration and Git. No peer tests/processes/services/network/DB/Git. Native receipt/physical/controller behavior, applied migrations, role maps, source semantics, evaluation seals and user audits protected. Peers coordinate the helper/CLI/protocol directly; report protected/outcome/ownership changes before edits, unresolved material issues go via root to Astra. Scope includes no actual HTTP, physical quiescence or runtime recovery claim.

G2b2a final handoff COMPLETE for SQL feasibility only. Sol helper/CLI peer and test peer coordinated mode/probe/rollback interfaces directly, preserved default B0 behavior and transferred all three paths. Root inspected actual role ordering, negative assertions and synthetic scope, passed 41 focused tool tests, 15 actual opt-in PostgreSQL checks, 12 actual default-mode regressions and 2,494 full Python/tool tests (four existing warnings). No product/Node source, schema/grant/migration/lock/sealed-input/user-audit changes; prior core verification remains at 548abb7. [Report](../evaluation/reports/V5/V5-04G2b2a.md). Diagnostic output now requires owned fresh artifacts and preserves the primary error if auxiliary writes fail. Actual old source/generation/preparation and full savepoint/outer inventory rollback passed; all task-owned processes closed. No HTTP, actual native physical proof, receipt, paid provider/model/install/hosted/release action. Learning exercise unassessed. Root owns final protection/prose/link/staged review and commit/push/sync. Next required child G2b2b: bounded full-document immutable inspection plus exact-current readback, with one shared byte/call allowance and native mutable/corrupt/extra/drift cases; then private security-bound plans/dispatch, genuine receipt settlement and ownership handoff. Full G2/V5 remain active and incomplete.

### V5-04G2b2b assignment

G2b2a commit 53473d46766c87b136720943868c6d152b45e708 synchronized with exact GitHub main and 0/0. G2b2b RUNNING under frozen QW pure readback contract. Sol partial_protocol owns only new Python _qdrant_security_readback.py and test_qdrant_security_readback.py and assembles; Sol partial_review owns only new Node qdrant-security-readback.ts and qdrant-security-readback.test.mjs. Shared outcome: multi-generation full-document immutable inspection, known stale-mutable classification, exact-current/tombstone verification and shared fixed byte/call allowance. Root owns all existing files, shared/native fixtures/parent/consumers, protocol guards, all execution/tracker/Git. No peer tests/processes/services/network/DB/Git. Stage/F1/E2 receipts, existing budgets/reader behavior, source/SQL/controller/proofs, migrations/role maps/seals/audits protected. No new public receipt or mutation authority. Peers directly agree exact API/data/error/counter/filter semantics; root handles protected/outcome/ownership changes and unresolved Astra escalation. Actual server checks remain required; fake fixtures cannot establish native or model quality.

G2b2b native lane: Sol security_native owns only new tools/check_typescript_qdrant_security_readback.mjs, implementing the shared eight actual-server cases against root-owned qdrant_security_readback_cases.py and its frozen pure fixture. It coordinates API dependencies directly with Node product peer partial_review. Root owns native parent, Python consumer, protocol tests and all actual processes/Git. No peer execution/network/DB/services/install. No SQL/projection-factory/receipt/settlement claims; source fields/vectors are synthetic and actual backend mechanics remain separate evidence.


G2b2b final handoff COMPLETE for pure private readback. All peer paths transferred to root; root integrated strict HTTP options, exact ACL representations and late Node byte accounting. Changed scope: new Python/Node private readback modules/tests, native fixture/parent/consumers/protocol tests, QW, development docs, report/tracker. Passed 40 focused Python, 33 Node, three harness tests, mypy48, strict build, full 2,537 Python/tool (four existing warnings) and 1,318 Node. Separate and combined serial actual Qdrant runs passed eight cases per runtime with cleanup. [Report](../evaluation/reports/V5/V5-04G2b2b.md). No SQL projection factory, receipt, dispatch, settlement or convergence claim. No paid provider/model/install/hosted/release action. Six protected hashes and 16 seals unchanged. Learning exercise unassessed; root owns final prose/link/staged review and commit/push/sync. Next smallest action: freeze genuine security receipt/proof binding and separate security-bound recovery plans under historical owner before high-level convergence. Full V5 remains active.


### V5-04G2b2c receipt-binding contract gate

Readback commit c30d21be9e2e4e56ea116f35d956842284a44d52 pushed and synchronized with exact GitHub main and 0/0. G2b2c RUNNING design gate: genuine security receipt bound to current projection, actual physical proof and retained controller session before settlement work. Sol partial_protocol owns only artifacts/V5/V5-04G2b2/security-receipt-python-design.md and assembles; Sol partial_review owns only artifacts/V5/V5-04G2b2/security-receipt-node-design.md. Both substantively inspect their native APIs and coordinate directly on exact witness/session provenance, historical/current context and minimal changes. No worker product/shared/tracker edits or execution/tests/services/network/DB/Git. Existing stage/E2 receipts, controller drain, SQL roles/migrations, public scope and sealed inputs protected. Root owns frozen contract and implementation assignment after inspection, all execution/integration/tracker/Git. Outcome/protected/ownership changes require root first; unresolved material decisions go to Astra. Last observed headroom 39 GiB disk / 57 percent free memory; lightweight analysis only. Next action: reconcile authentic session access before dependent code.


G2b2c1 root implementation: additive private authentic facade helper in both existing supervisor modules/tests, with monotonic attempt/request activity; root also extends the existing readback native consumers to compare actual session activity against three metered passes. Focused Py40 / Node28, strict mypy48/build and 16 combined actual Qdrant readback/activity cases passed with cleanup. No authority/receipt/settlement claim. G2b2c2 peers are reconciling the exact same-session receipt witness and strict no-interposed-request timing before source implementation. Root retains all shared/tracker/Git writes.


G2b2c1 final acceptance: full 2,538 Python/tool (four existing warnings), 1,319 Node, strict mypy48/build, focused40/28 and 16 actual Qdrant readback/activity cases passed. Six protected hashes/16 seals unchanged; owned native processes closed. [Report](../evaluation/reports/V5/V5-04G2b2c1.md). Root owns final prose/link/staged review and scoped commit/push/sync. No receipt/settlement claim; resource last observed 39 GiB disk /57 percent free memory, learning unassessed.

G2b2c2 assignment RUNNING after root accepted both design artifacts and froze QW section. Sol partial_protocol owns only new Python _qdrant_security_verification.py/test_qdrant_security_verification.py and assembles; Sol partial_review owns only new Node qdrant-security-verification.ts/qdrant-security-verification.test.mjs. Both implement exact same-session nominal receipt/witness, direct dependency coordination, final no-interposed-request timing and cancellation/cleanup admission. Root owns existing helpers/SQL/controller/source/shared fixtures, native acceptance, tracker and Git; no peer processes/tests/network/DB/install/Git. Existing stage receipts, public exports, SQL roles/migrations/seals/audits protected. Escalate outcome/protected/ownership changes before edits; unresolved material decisions through root to Astra. Required native source/proof/readback gate remains unvalidated until root runs it; local doubles cannot complete c2 alone.


G2b2c2 native lane: Sol security_native owned only new tools/check_typescript_qdrant_security_verification.mjs against root-owned qdrant_security_verification_cases.py/shared eight-case contract; root owns native parent and protocol. Native peer transferred file then reviewed root harness read-only in ignored native-harness-review.md. Review found Python's per-resource cleanup waits exceeded the assigned aggregate allowance; root corrected them to share twelve seconds. Parent checks semantic witness parity after excluding per-run physical/attempt/activity fields, separately from actual proof checks. No worker execution. All product/native peer paths now stopped/transferred to root after assembly. Root inspected source, added exact Node constructor/closed provenance guards and passed 16 Node focused tests/build plus eight actual PostgreSQL/Qdrant Node cases with cleanup. Python focused/type/native and final combined regressions remain pending; c2 stays IMPLEMENTED_UNVALIDATED.


G2b2c2 final handoff COMPLETE for private same-session receipts. All product/native files transferred; root inspected and passed 22 focused Python receipt +three harness tests, 16 Node, strict mypy49/build, full 2,563 Python/tool (four existing warnings) and 1,335 Node. Separate native runs and combined parent passed eight actual PostgreSQL/Qdrant cases per runtime, semantic witness digest 0094e2237098d217c904efab2e09a1d5d4b9ed4be20b9cfec444ed4927fd11ac and cleanup. [Report](../evaluation/reports/V5/V5-04G2b2c2.md). Initial Python native fixture passed an encoded security record to an API that encodes internally; corrected fixture passed without product/SQL relaxation. Root also fixed a mypy annotation, exact constructor/closed provenance and shared native cleanup allowance. Changed paths: new Python/Node verifier/test pairs, native parent/consumers/protocol, development docs/report/tracker. No SQL/role/migration/public-export change, provider/model/install/hosted/release action, settlement/convergence claim. Six protected hashes and 16 seals unchanged. No task-owned processes remain; 39 GiB disk /58 percent free memory observed, not capacity evidence. Learning unassessed. Root owns final prose/link/staged review, commit/push/sync. Next required action: G2b2d fresh writer document lock through restricted supervisor settlement commit, preserving historical exact confirmation and all current-key/foreign blocks. Full V5 remains active.

### V5-04G2b2d current-security settlement design gate

RUNNING design only. Sol partial_protocol owns ignored security-settlement-python-design.md and assembles; Sol partial_review owns security-settlement-node-design.md under artifacts/V5/V5-04G2b2c. Both substantively inspect native transaction/SQL guards and coordinate direct dependencies. No product edits/execution/tests/processes/network/DB/Git. Shared outcome: smallest current-security retired-old-stage settlement under one authentic facade; no recovery upserts or public convergence yet. Root owns shared contracts/decisions/integration. Do not weaken current authority into historical-only readback: validate genuine current projection under a writer-held document lock through actual supervisor COMMIT. Acquire supervisor backend/oldowner locks before writer document lock; avoid reverse reacquisition. Existing transaction helpers commit after callbacks, so specialized bounded transaction sequencing is required. Dispose both leases before fresh read-only exact historical confirmation of a lost COMMIT reply; do not retry DML or bypass pool reentrancy guards. Changes to roles/migrations, public scope, controller drain and another lane require root first; unresolved material questions go to Astra. Native two-connection authority/publication races remain required before acceptance. Next smallest candidate prerequisite is a private writer projection-lock helper, followed by protected settlement.


G2b2d material design escalation: Node source review found `PoolResource.withLease` can release the writer lease after callback cancellation/deadline before its actual unwind. A naive two-client document guard could therefore release current authority while supervisor COMMIT remains uncertain. Root stopped dependent implementation and assigned actual Astra security_settlement_decision to inspect native pool/driver/SQL semantics and compare bounded finalization against a narrowly versioned SQL current-tuple lock helper. No broad supervisor document/source grants or weakened current-authority invariant is authorized. Sol peers finish read-only evidence artifacts and communicate concrete findings directly to Astra. Next step is a native proof gate for the selected minimal path; source reasoning alone cannot establish the race is closed.


### V5-04G2b2d0 native necessity assignment

Receipt commit 7bf8a398051c1327b759ce8afabcfa1f055c5cf7 pushed and synchronized with exact GitHub main and 0/0. Astra source review recommends a same-supervisor-transaction narrow current-tuple guard, contingent a native counterexample to separate-connection custody. Root froze G2b2d0: actual submitted COMMIT/advisory wait, asymmetric writer connection loss and next authority commit before old settlement, plus retained-lock control. Sol partial_protocol owns only new tools/qdrant_security_lock_cases.py and assembles; Sol partial_review owns only new tools/tests/test_qdrant_security_lock_native.py. Root owns CLI/fixtures/shared QW, actual execution, tracker/Git. Pair coordinates the closed CHECKS/run/error protocol directly; no peer execution/tests/services/network/DB/Git. Production SQL/grants/migrations/controller/source behavior, seals/audits protected. Fixture-only barrier schema and LOGIN INSERT grant must stay outside production schema/capability maps and disappear with owned fixture cleanup. Two restricted runtime clients plus one harness admin; sequential writer replacement, one test process. Escalate outcome/protected/ownership changes before edits; unresolved root/Astra. Full V5 remains active; no product settlement implementation proceeds before this gate.


G2b2d0 final handoff COMPLETE for native necessity. Sol helper/test peers assembled and transferred all paths; root inspected, corrected metadata PID transaction cleanup and passed 26 focused tests, eight actual PostgreSQL counterexample/control checks twice, full 2,589 Python/tool (four existing warnings), 16 seals and six protected hashes. [Report](../evaluation/reports/V5/V5-04G2b2d0.md). Actual submitted supervisor COMMIT/advisory wait survived writer disconnection; a replacement authority change committed first and both facts became durable. Retained-lock control observed the real guard PID and blocked until release. Original immutable/denied-stage snapshot and production catalog/grants/migrations preserved. Changed scope: new SQL-only fixture helper/CLI/protocol tests plus QW/development/report/tracker. No product/Node changes; preceding 7bf8a39 receipt evidence remains applicable. No Qdrant/provider/model/install/hosted/release action. No task-owned process remains; observed 39 GiB disk /58 percent free memory. Learning unassessed. Root owns final prose/link/staged review and commit/push/sync. Next smallest required action: freeze narrowly versioned same-supervisor-transaction SQL guard ownership/RLS and helper contract, then its actual restricted-role acceptance. A separate writer lock is rejected as the current-authority safety boundary. Full V5 remains active.

G2b2d1 design follow-up: actual Astra security_settlement_decision owns only ignored artifacts/V5/V5-04G2b2d0/sql-guard-astra-design.md, specifying minimum definer role/RLS, exact invoker/target/current tuple, lock order and rollback/profile compatibility. Root has accepted that the observed counterexample justifies an additive migration design; no migration/grant/product edit proceeds before its contract freezes. Previous 0001-0003 remain protected. A same-transaction guard must not grant general supervisor document/source/vector/request reads, and later guarded writer graph validation must use genuine transaction provenance rather than a caller boolean.


### V5-04G2b2d1 SG-r1 assignment

D0 commit 03a345d8003badac486dd45fbe90955fd1517b41 pushed and synchronized with exact GitHub main and 0/0. Root read the final Astra operator/RLS design and froze contracts/QDRANT_SECURITY_GUARD_V5.md SG-r1. Outcome: additive 0004 guard with exact metadata-only definer and actual non-superuser operator/rollback/restricted-role/SQL-lock acceptance, before runtime profile-4/guarded-graph/settlement integration. Sol partial_protocol owns only new storage/qdrant/postgres/migrations/0004_security_settlement_guard.sql and tools/qdrant_security_guard_schema.py, and assembles; Sol partial_review owns only new tools/tests/test_qdrant_security_guard_schema.py. Root owns native fixture/operator bootstrap, CLI, shared contract/catalog fixture/history and all execution/docs/tracker/Git. Both peers substantively implement/match SQL/probe contracts and coordinate directly. No worker execution/tests/services/network/DB/install/Git. Existing three migrations, roles/capability rights, stage receipts, source semantics, seals/audits and public APIs protected; the only new supervisor right is exact guard EXECUTE. Dedicated role has no runtime membership or source/vector/journal rights. Target profile-4 structural/owner/ACL admission remains later; do not globally allow definers or pretend old runtime admission accepts 0004. Native waits and operator membership/ownership shape must be observed, not assumed. Escalate changed outcome/protected paths/ownership before edits; unresolved root/Astra. Three total clients maximum, serial native language/process execution, no provider or hosted writes.


G2b2d1 independent native race lane: Sol security_native owns only new tools/qdrant_security_guard_races.py and tools/tests/test_qdrant_security_guard_races.py. Root freezes datasets mapping keys commit/post_wait/abort/lost (plus separate main guard dataset), each record has arguments22, inputs, records, dispatch_id and current scope; root seeds through actual writer before applying 0004. Lane exercises same-transaction COMMIT barrier, unrelated writer loss, post-wait tuple freshness, rollback and supervisor connection loss using actual restricted SQL roles. It coordinates the exact signature/probe interfaces directly with SQL assembler. Root owns operator bootstrap, parent/CLI and all actual execution/Git. No peer tests/processes/services/network/DB/Git. No product/runtime profile-4 acceptance, receipt/fencing/convergence claim; the native profile is SQL-only. Max two restricted runtime clients plus one fixture admin; fixed owned advisory barrier outside protected schema, serialize cases and close owned resources. Protected/outcome/ownership changes require root before edits, unresolved material issues go to Astra.


SG-r2 minimum-rights correction: the SQL peer identified the existing PUBLIC scoped_document_read policy's function dependencies. Root ran actual isolated PostgreSQL probes: the restricted non-bypass guard role could not lock the document without scope_visible/scope_grants (42501); with populated scope GUCs those two alone still failed until valid_identity_array was granted. Root froze exact three read-only invoker EXECUTE dependencies for the dedicated role, preserving all old function/policy bytes and no new supervisor direct reads. Evidence: artifacts/V5/V5-04G2b2d1/public-policy-probe-01.log and public-policy-probe-02.log. No production migration was applied in these probes; owned local servers closed. Migration/test peers update only assigned new files under SG-r2; root owns shared contract and final acceptance.


G2b2d1 final handoff COMPLETE for SQL guard only. Sol SQL/helper and test peers assembled under SG-r2; independent native peer delivered six races/tests, all paths transferred. Root added non-superuser operator bootstrap, five canonical document seeds, full rollback/preexisting-role checks, CLI/private diagnostics, final catalog fixture and focused orchestration tests. Actual final native-04 passed 23 groups with cleanup; focused36 and full 2,625 Python/tool (four existing warnings) passed. [Report](../evaluation/reports/V5/V5-04G2b2d1.md). Earlier native races exposed local-close/server-end timing; explicit 100 ms client checks plus actual backend/transaction observations passed without changing library defaults or weakening lock invariants. No product/Node source, old migration/capability-right change, provider/model/install/hosted/release action, opaque receipt or settlement integration claim. Six original protected hashes/16 seals unchanged; new 0004 frozen at 44b666cb47f3bb51ac8c5f6eb05fe8aea9138a9c603ab2fa427bdd807255be0b; catalog fingerprint 352cf043dc8c19f700b8e2e9b4776dede7dd0402b2db79f7d79668cab115d8a3 captured. No owned process remains; observed 38 GiB disk /52 percent free memory. Learning unassessed. Root owns final prose/link/staged review and commit/push/sync. Next smallest required action D2: native exact profile-4 source/writer/recovery admission with one precise definer exception, dedicated owner/ACL/membership checks on leases and fifth-row overflow detection. Existing profiles stay accepted; current core has not yet admitted 0004. Guarded nonlocking graph validation and private receipt settlement follow. Full V5 remains active.


### V5-04G2b2d2a native authority assignment

D1 commit b96ef359bef8e41f3d46c32f79424d2427d7cbd2 pushed and synchronized with exact GitHub main and 0/0. Root froze SG-r2 D2a profile-4 authority foundation before writer/recovery integration. Sol partial_protocol owns only packages/python/src/cragkit/_qdrant_authority.py and packages/python/tests/test_qdrant_authority.py and assembles; Sol partial_review owns only packages/typescript/src/qdrant-authority.ts and packages/typescript/tests/qdrant-authority.test.mjs. Both substantively implement exact four-entry profile, five-row overflow, one-definer exception and complete read-only guard-owner permission predicate checked on initialized profile-4 source leases. Root owns shared contract/fixtures, all native consumers/runs, tracker/Git. Direct peer coordination on constant/query/API semantics; no worker execution/tests/processes/services/network/DB/install/Git. Four migration bytes, old profiles/rights, source scope/release, public APIs, seals/audits protected. Writer/recovery profile4 remains unsupported until D2b; no silent fallback. Native actual Py/Node reader admission and committed grant-drift/refusal/restoration are required. Scope/outcome/ownership changes go to root before edits, unresolved reasoning to Astra. Max one test process; services only explicit disposable SQL fixture, no provider or model.


D2a native consumer lane: Sol security_native owns only new tools/check_typescript_qdrant_guard_authority.mjs. Root owns shared Python cases/CLI/protocol and source-query spy factories. Shared eight checks cover real reader profile4 admission, unpublished scoped absence, committed guard-source grant drift, guard LOGIN drift, fifth history row and extra definer refusal before source SQL, restoration and borrowed resource cleanup. Root's fixture sends only synthetic nomination/config/scope plus private generated reader/operator credential-file locations; no password or source text is logged. Two child runtime clients (reader/operator) plus parent admin maximum; runtimes serial. Native consumer coordinates directly with both source peers; no worker execution/tests/processes/network/DB/install/Git, including read-only Git. SQL migration/profile fixture immutable. Root owns final integration and actual acceptance.

D2a integration pair: Sol partial_protocol owns only new native protocol test file and assembles; Sol partial_review performs read-only cross-runtime source/native review and reports directly to assembler/root. All existing paths transferred to root. Root owns runs, fixes, tracker and Git; protected boundaries and no peer execution unchanged. Native01/02 exposed source-query spy matching differences (Python JOIN versus Node FROM), corrected only harness counters. No source permission relaxation.

D2a acceptance COMPLETE for exact source-reader admission: focused201 Python/tool and29 Node, full2,776 Python/tool (four existing warnings) and1,345 Node, strict build/mypy49 passed. Actual PostgreSQL native03 passed16 checks, six safe source queries per runtime and zero denied source queries, cleanup verified. [Report](../evaluation/reports/V5/V5-04G2b2d2a.md). Root corrected only native spy syntax and hardened closed diagnostics/artifact ownership; no permission relaxation. All peer paths transferred. Sixteen seals/seven protected hashes unchanged. Native successful fixtures removed; no provider/model/install/hosted/release work. Resource40GiB disk/34percent free memory, observation only. Learning unassessed. Root owns final prose/link/staged review and commit/push/sync. Next smallest action D2b1 exact writer profile4 admission, then D2b2 recovery admission; full V5 remains active and incomplete.

### V5-04G2b2d2b1 writer admission assignment

D2a commit 9a57c6b17b551a796da91d681271e2ec57526fc7 pushed; upstream0/0 verified. D2b1 RUNNING under frozen SG-r2 D2b1. Shared outcome: exact native writer profile4 admission, unchanged attestation requirements/role rights and fresh per-lease guard-owner validation. Sol partial_protocol owns only Python _qdrant_writer.py and test_qdrant_writer.py and assembles; Sol partial_review owns only Node qdrant-writer.ts and qdrant-writer.test.mjs. Root owns shared contract, native consumers/fixture/tests, all execution/tracker/Git. Both peers coordinate concrete selector/validation/error dependencies directly, no overlapping edits. No peer execution/tests/processes/services/network/DB/install/Git; read-only file inspection allowed. Existing authority/recovery/public APIs, four migrations/catalog fixture, scopes/receipts/locks, seals/audits protected. Native writer-local profile selection only; recovery remains unsupported4. Escalate outcome/protected/ownership change to root before edits, unresolved root/Astra. One test process, serial runtimes, explicit disposable SQL only; no provider/model.

D2b1 native lane: Sol security_native owns only new tools/check_typescript_qdrant_guard_writer.mjs; root owns new Python cases/CLI/protocol tests and actual execution. Eight checks require actual restricted writer initialization/current-security projection with two complete claims, four committed guard/catalog/history faults rejected before scope binding, exact restoration and borrowed lifetime. Same generated private TLS and max two runtime clients plus parent admin; no Qdrant/provider. Concrete interfaces frozen in assignment messages, direct native/source peer coordination required; existing accepted source-reader harness remains unchanged.

D2b1 final handoff COMPLETE for writer admission only. Sol runtime pair and native consumer transferred all paths; root owns final integration. Focused 203 Python/tool and 119 Node passed; root added a catalog-error ordering regression included in final full 2,799 Python/tool (four existing warnings) and 1,361 Node. Strict build/mypy49 passed. Actual profile4 native-final-03 passed 16 checks with six safe projections and zero denied-path scope queries per runtime; existing native SQL/Python/Node writer passed 78 checks. Cleanup verified. [Report](../evaluation/reports/V5/V5-04G2b2d2b1.md). Initial native error classification and one full-suite timing failure are recorded; unchanged case/full reruns passed without timeout increases. No grant/migration/recovery/public API change or provider/model/install/hosted/release action. Sixteen seals/seven protected hashes unchanged. Resource 39 GiB disk /39 percent free memory, observation only. Learning unassessed. Root owns final prose/link/staged review and commit/push/sync. Next smallest required task D2b2 recovery admission with exact guard EXECUTE allowance; guarded graph validation and private settlement follow. Full V5 remains active and incomplete.

### V5-04G2b2d2b2 recovery admission assignment

D2b1 commit 2cf570905f67923151e95a44eb2071abf8141588 pushed and exact GitHub main/0-0 synchronization verified. D2b2 RUNNING under frozen SG-r2 D2b2. Shared outcome: exact recovery4 admission, precise guard EXECUTE exception and full fresh per-transaction metadata before backend binding; preserve attestation/proof/lost-COMMIT/resource semantics. Sol partial_protocol owns only Python _qdrant_recovery.py/test_qdrant_recovery.py and assembles; Sol partial_review owns only Node qdrant-recovery.ts/qdrant-recovery.test.mjs. Root owns shared contract, parent/Python native consumer/protocol, all execution/tracker/Git. No peer tests/processes/services/network/DB/install/Git; read-only file inspection allowed. Four migrations, source/writer paths, shared selectors, public APIs, controller/receipts, seals/audits protected. Peers resolve concrete dependencies directly; outcome/protected/ownership changes to root before edits, unresolved root/Astra. One test process, serial runtimes, bounded disposable PG/Qdrant only.

D2b2 native lane: Sol security_native owns only existing Node security-verification native consumer, adding explicit optional guard mode without changing the old receipt flow. Root owns parent/Python consumer/protocol tests. Parent's --with-security-guard explicitly installs 0004 under the non-superuser operator before runtime work; old mode remains three-profile. Native guard mode adds four committed faults before public advance_owner, using actual issued proof and SQL backend-binding spy, restores each fault and checks idempotent owner advance. Existing eight receipt checks and semantic witness remain separate; optional guard_admission reports four checks and zero denied backend queries. Three runtime clients maximum (writer/supervisor/operator), parent admin released, PostgreSQL six slots, runtimes serial. No peer process/test/service/Git. Full guard settlement remains unimplemented.

D2b2 final handoff COMPLETE for recovery admission. Sol source/test pair and native Node lane transferred all paths; Python assembled and root integrated. Focused92 Python/tool and31 Node, full2,823 Python/tool (four existing warnings) and1,379 Node, strict build/mypy49 passed. Actual PG17/Qdrant1.20 guard mode passed24 checks and original3-profile mode16, all cleanup verified; both runtimes/modes matched the accepted stable witness hash. Four committed faults were rejected before backend binding with zero denied-path binding queries and exact restored owner advances. [Report](../evaluation/reports/V5/V5-04G2b2d2b2.md). Root corrected Node initconfirmation profile check placement and initialization readiness/deadline edge cases; no SQL guard invocation or settlement behavior added. Sixteen seals/seven protected hashes unchanged; user audits excluded. Successful native fixtures/listeners/processes closed; resource39GiB disk/39percent memory free, observation only. No provider/model/install/hosted/release action. Learning unassessed. Root owns final prose/link/staged review and commit/push/sync. Next smallest required action D3: genuine transaction-bound guard capability and nonlocking full writer graph revalidation under the supervisor-held document lock, then security receipt settlement. Full V5 remains active and incomplete.

### V5-04G2b2d3 guard-lifetime decision

D2b2 commit 8335bf83651bffb0e20a56bff4ea29f038723307 pushed and exact remote/main plus 0/0 synchronization verified. Root escalated the unresolved minimum genuine guard-capability issuance/lifetime design to actual Astra guard_lifetime_design. Astra owns only ignored artifacts/V5/V5-04G2b2d3/ASTRA-GUARD-DESIGN.md, with read-only product inspection and no tests/processes/services/network/DB/Git. Decision: revalidate the complete writer graph without taking a second document lock while the same supervisor transaction holds the SQL guard; bind genuine transaction/client/session/proof/task/deadline provenance and reject copies/expiry/connection loss. No caller-controlled lock=False, supervisor source grant or separate writer lock safety boundary. Root owns contracts, all product paths, execution, tracker and Git; dependent implementation waits for the bounded issuer/lifetime design. This is a design gate within active V5, not an acceptance claim. Existing guard/receipt/admission evidence remains scoped as recorded.

D3 decision resolved by actual Astra advisory, transferred ignored artifact to root; no product execution or edits by adviser. Root accepted private Recovery registry, fixed verifier-based void driver, precise signal separation and retained inner control ownership for actual callback drainage. Root froze SG-r2 D3-r1 normative appendix, including pre-COMMIT same-client gates and mandatory E101 late-callback cases. The advisory is design input, not native proof. D3a splits into Python and Node owned runtime lanes; D3b native acceptance and final integration remain root-owned dependencies before D3 completion.

### V5-04G2b2d3a native implementation assignment

Shared outcome: SG-r2 D3-r1 fixed internal verifier-based guarded-validation driver, genuine transaction-owned token and nonlocking full graph under the same supervisor SQL guard, with actual callback lifetime ownership. Sol partial_protocol owns only Python _qdrant_recovery.py, _qdrant_writer.py, test_qdrant_recovery.py and test_qdrant_writer.py; it assembles. Sol partial_review owns only Node qdrant-recovery.ts, qdrant-writer.ts and their two tests. Root owns shared contract, native consumers/protocol, all execution/tracker/Git. Both perform substantive work and coordinate exact internal helper signatures, error/state/signal/cleanup parity directly. No worker tests/processes/services/network/DB/install/Git; read-only file commands allowed. Four migrations/catalog fixtures, source/receipt/verifier/pool/supervisor modules, public exports, old locking and user audits/seals protected. No generic factory, app callback, public lock flag, settlement or convergence. Root/Astra resolves outcome/protected/ownership changes before edits. One test process; explicit bounded native services only under root. State IMPLEMENTATION RUNNING; no native validation or D3 completion claimed.

D3 resumed after explicit pause; user requests faster execution and invoked ponytail. Root confirmed named frozen nine-field document mapping, transferred all runtime paths and ran checks: focused304 Python passed; Node first run exposed strict-options boundary owner_token:undefined, root normalized using existing deadline/signal snapshot pattern; rerun171 passed. Root fixed mypy Any return cast, pending recheck. D3b native pair outcome frozen in contract: Sol partial_protocol owns only existing Python native security-verification cases; Sol security_native owns only existing Node native security-verification consumer, Python assembles. Root owns parent/protocol, source integration, all execution/tracker/Git. Both peers reuse existing fixture/checker, no new generic framework/dependency/files; four SQL clients/seven server slots only in explicit guarded mode. No peer tests/process/services/network/DB/Git. Native9 checks cover actual guard/graph/waits, late data drift, stale authority, real Sup loss and held late callback; existing modes protected.

D3 final handoff COMPLETE for private guarded validation. All peer paths transferred; root integrated. Focused304 Python/171 Node, full2,840 Python/tool (four existing warnings)/1,399 Node, strict build/mypy49 passed. Actual final guarded PG17/Qdrant1.20 mode passed42 checks and original3-profile mode16, cleanup verified; common stable witness matched and zero forbidden supervisor COMMITs observed. [Report](../evaluation/reports/V5/V5-04G2b2d3.md). Root fixed options normalization, Python owned-wait diagnostics, exact seven-slot fixture bound, unprivileged lock observation and fault-close verification. Four-client resource profile is explicit; no dependency, generic framework, model/provider/hosted mutation/release action. Sixteen seals/seven protected hashes unchanged; user audits excluded. Successful services/fixtures closed, earlier private failed evidence retained. Resource39GiB disk/58percent memory free, observation only. Learning unassessed. User README structure retained and recorded in AGENTS.md; README-only commit7e375a975036ae0aebee93d2a0c31e201a5744fe pushed/synchronized. Root owns final prose/link/staged review and D3 commit/push/sync. Next: D4 exact security receipt settlement in this same guarded transaction, preserving unknown outcomes and foreign blockers; full V5 remains incomplete.

### V5-04G2b2d4 exact settlement assignment

D3 commit39e4973596259c3b44aaafcbbf30622717154e46 pushed and exact remote/main/0-0 verified. D4-r1 frozen in SG contract. Shared outcome: fixed internal current-security retired settlement in the existing guarded transaction, immutable exact snapshot and one read-only COMMIT-unknown confirmation, no write retry. Sol partial_protocol owns only Python _qdrant_recovery.py and test_qdrant_recovery.py and assembles; Sol partial_review owns only Node qdrant-recovery.ts and qdrant-writer.test.mjs (existing genuine guarded fixture). Root owns all other source, native consumers/protocol, contracts/execution/tracker/Git. Direct peer API/error/snapshot coordination required. No peer tests/processes/services/network/DB/install/Git; read-only file commands allowed. Reuse D3 flow, no generic framework/dependency. Migrations/roles/receipts/writer/pool/controller/public APIs/fixtures/seals/user audits protected. Escalate outcome/protected/ownership change to root before dependent edits, unresolved root/Astra. Full V5 remains incomplete; this is implementation assignment, not acceptance.


D4 native assignment: Sol security_native owns only existing tools/check_typescript_qdrant_security_verification.mjs, adding frozen security-settlement mode. Root owns parent/Python consumer/protocol and all tests/processes/Git. Coordinate actual source API with Node peer and Python assembler directly. Three runtime clients/six server slots, explicit local native services only under root. No worker execution. Preserve original eight/four/nine modes, protected files and synthetic-versus-native evidence boundaries. Acceptance requires both runtimes, exact lost-COMMIT confirmation after authority advances, repeat and current-key refusal, plus regressions. State RUNNING, no acceptance claim.


D4 runtime paths transferred to root; focused132 Python/tool and199Node, full2865Python/tool(fourexistingwarnings)/1427Node, strictbuild/mypy49 passed. Root fixed cancelled-setup reference cleanup via shared finally and explicit membership type annotation. Native pair now owns only existing Python/Node consumer files; Python assembles, root owns parent/protocol/all execution. Sixteen seals unchanged; headroom39GiB/47percent free memory observation. State IMPLEMENTED_UNVALIDATED until actual settlement and guarded/legacy regression acceptance. Next: native COMMIT-unknown/current-key refusal checks, then full accepted report/tracker/Git. Learning unassessed; fullV5 remains incomplete.


D4 final handoff COMPLETE for private retired security settlement. All source/native peer paths stopped and transferred; root integrated and verified. Changed scope: existing Python/Node recovery source and focused tests, existing native parent/consumers/protocol, SG contract, development guide, README, report/tracker. Focused132 Python/tool and199Node; full2865Python/tool(fourexistingwarnings)/1427Node; strictbuild/mypy49; native settlement32/guarded42/legacy16 across both runtimes passed. [Report](../evaluation/reports/V5/V5-04G2b2d4.md). Exact lost realCOMMIT reply confirmed once after authority advance with zero confirmationDML/guard/HTTP/writer-query replay; repeat0 preserves history; currentkeyunknown preserves rows and globalclosed admission. Synthetic dispatch metadata is distinguished from actual nativeSQL/currentreadback/COMMIT evidence. Root fixed cancellation cleanup, typing and one native fixture nested-result access; no migration/grant/publicAPI/dependency change. Sixteen seals/seven protectedhashes unchanged; three useraudits excluded. Successful fixtures/listeners/processes closed; failed privateevidence retained. Resource39GiB/48percent free memory observation; learningexercise unassessed. Root owns final prose/link/staged review and scopedcommit/immediatepush/sync. Next smallest action G2b2d5: current-security recovery plans and journaled fullpoint dispatch/acknowledgment/receipt handoff. G2b2, V5-04 and fullV5 remain incomplete; no production/release/providerquality claim.


### V5 completion run: G2b2d5

User explicitly requests fullV5 completion through EXIT; continue active dependency order without stopping after an internal slice. cb62b64657ab6fa94a647a16eb0e859c88e983e1 is accepted/pushed D4. D5-r1 frozen SG contract: current-security missing/stale completepoint replay with true recovery journal/ACK, no flags/handoff/reopen or tombstone upsert. Sol Python/Node lanes own their native writer+recovery source and existing tests only; Python assembles, root integrates. Root owns contracts/sharedfixtures/native consumers/docs/tracker/all tests/services/Git. No worker tests/processes/network/DB/install/Git, read-only commands allowed. Four migrations, roles, pool/controller/receipt modules, publicexports/seals/audits protected; gate/lifetime outcome changes go to root before dependent edits, unresolved root/Astra. Direct peer signature/error/lifetime coordination mandatory. One test process, serialruntimes. State RUNNING, not acceptance.


Independent H audit lane: Sol security_native owns only ignored artifacts/V5/V5-04H/fault-coverage-audit.md. Read-only inspect the frozen43fault scenarios, actual native runners/source and accepted reports; map exact scenarioIDs to real executed mechanisms/evidence versus missing coverage and propose minimal runnable additions after G3. No product/shared/tracker edits, tests/processes/services/network/DB/Git. This is dependency preparation, not H implementation/acceptance. Root owns final integration, next sequencing and all execution.


D5 native contract frozen: root owns parent/Python existing security-verification consumers/protocol; Node native lane to security_native after its audit transfer. Exclusive --security-dispatch profile uses four native dispatch checks plus four admission checks, separate primary proofscope from earlier eight receipt mode; threeclients/sixslots, actual replay/ACKwithhold/currentkeyblock. No peer execution, no newframework/dependency. Root approved internal constructor-registered owned projection helper reusing D3 callback custody in writer-owned paths; it preserves ordinary APIs and avoids pool changes. Final headroom31GiB/61percent free memory observation.


D5 initial Pythonfocused394/mypy49/full2885(fourexistingwarnings) and actualnativePython8 passed. InitialPythoncorruptiontest multipliedazero component; rootcorrectedfixturetonegatefullvector. Nodefocused exposed shared strictoptions parser inventingowner_token:undefined and rejecting itsownoutput; rootowns/fixes existing writer-contract.ts conditionalownerfield with roundtripregression, preserving rejection of callerextraownerfield. No parser relaxation. Allpeerproduct/nativepaths transferredtoroot. H auditready; actualAstra supplied minimum optionalrecoverychild/controller profile design, pendingrootfreeze/implementationafterG3; noHacceptance.


D5a final handoff COMPLETE for privatecurrentsecuritydispatch only. Allpeerpaths transferred, Pythonassembled, rootintegrated. Focused394Python/tool/252Node, full2885Python/tool(fourexistingwarnings)/1447Node, strictbuild/mypy49, actualnative dispatch16/settlement32/olderpartialrepair16 passed withcleanup. [Report](../evaluation/reports/V5/V5-04G2b2d5a.md). RootreusedmeteringforPUTACKs, fixedstrictoptionsoutputroundtrip withoutrelaxinginput and correctedzerovectorcorruptionfixture. Sixteenseals/sevenprotectedhashes unchanged; useraudits excluded. No dependency/migration/grant/publicpackageexport/provider/model/hosted/release change. Allsuccessfulownedservices/listeners/processes closed; resource33GiB/61percentfree memory observation. Learningunassessed. Rootownsfinalprose/link/stagedreview andcommit/immediatepush/sync, then continuesD5b ownerhandoff/ordinarysecuritycompletion andG2c publicconvergence; D5/G2b2/V5 remainincomplete. H mapping43andactualAstra recovery-processdesign are ignoredread-onlyadvisory evidence, notimplementation/acceptance. FullV5runcontinues throughEXIT.


### V5-04G2b2d5b assignment

D5a commit02a91cd2e1db9c37b72c73ffda22f182cff41297 pushed; exactremote/0-0 verified. Root froze D5b-r1: ordinary security-owner handoff afteractualreopen, genuineordinaryreceipt and same-writer-TX fullgraph completion under existing nativefinalization. Solpartial_protocol owns only Python _qdrant_writer.py,_qdrant_security_verification.py and corresponding existingtwo tests; assembler. Solpartial_review owns only Node qdrant-writer.ts,qdrant-security-verification.ts and corresponding existingtwo tests. Bothsubstantive/directdependencycoord required. Rootowns sharedcontracts/nativeparent+consumers/protocol/publicmanager/docs/tracker/alltests/services/Git. Nopeer tests/process/network/DB/install/Git, read-onlycommandsallowed. Migrations/roles/pools/supervisor/recovery/worker/publicexports/seals/audits protected. Outcome/protected/otherownershipchanges rootbeforeedits, unresolvedroot/Astra. State RUNNING, noacceptance. FullV5runcontinuespastthisslice throughEXIT.


D5b nativeassignment: rootowns parent/Python/protocol; Solsecurity_native owns ONLY existingNode security-verificationconsumer for exclusive completion_config mode underfrozen finalSGparagraph. Nopeerexecution. Completeactualhandoff/ordinaryreceipt/flags andrealwriterCOMMITreplyloss+contenderauth3 historicalconfirmation. CloseidleSupresourcebeforenewcontender so3clients/sixslots. Rootapproved awaitingactualcompletioncallbackdrain insideoriginalfinalization; callerbound belongs laterpublicmanagerownedbody. No protectedpool/worker/supervisorchange.


Independent G3 design-preparation pair while D5b/G2 native acceptance proceeds: Solpartial_protocol owns only ignored artifacts/V5/V5-04G3/authority-purge-design.md (SQL/retention/immutablehistory), assembler; Solpartial_review owns only ignored artifacts/V5/V5-04G3/physical-purge-design.md (actualfence/delete/journal/absence/claimlifetime). Sharedoutcome minimal fullG3 implementation consistentwith architecture/QW/ADR and exact grants, including source-retention semantics. Rootowns allproduct/shared/contracts, G3implementationwaitsG2acceptance. Peerscoordinate concreteconflicts directly, reportunresolvedprotected/newmigration/publicpolicy decision to root/Astra. Noproductedits/tests/process/network/DB/install/Git; readonlyfilecommandsallowed. Advisoryonly notacceptance.


D5b final handoff COMPLETE forinitialstage-ownerhandoff/ordinarycompletion. Allpeerpaths transferred, rootintegrated. Focused400Python/tool/221Node, full2910Python/tool(fourexistingwarnings)/1468Node, strictbuild/mypy49, actualnativecompletion16+dispatchregression16 passed withcleanup; ordinarysemanticSHA matchedbothruntimes. [Report](../evaluation/reports/V5/V5-04G2b2d5b.md). RootaddedlatePythonuncertainty/sequencechecks matchingNode andcorrectednativeobserverrole/counter bookkeeping. No schema/grant/dependency/publicpackageexport change. Sixteenseals/sevenprotectedhashes unchanged; useraudits excluded. Successfulownedservices/processes/listenersclosed; failedprivateevidence retained; learningunassessed. Rootownsfinalprose/link/stagedreview andcommit/immediatepush/sync, thenD5c prior-security-ownercompatibility andG2c publicmanager. ParentD5/G2b2/V5 remainopen. G3Solpair recommendsnewadditiveprofile5 withirreversible managedsource/replay/requestbodyerasure andretainednontextidentity/claims; vectors-only completion rejected. Advisoryonly, schema/runtimeimplementationnotstarted; rootfreezesafterG2acceptance.


### FullV5 parallel dependency refinement

Rootmadeexplicit implementation/acceptance dependency distinction inV5plan: existing-index/MCP read-only consumers use stableacceptedV4/V5-03 retrieval/sourceinterfaces and may buildinparallel withV5-04repair/purge; finalacceptance stillwaitsV5-04/V5-05 andcombinedC2. No productscope/writecapability/releaseexpanded and no parentgate countedcomplete.

Repeated-security protocol review pair: Solpartial_protocol owns only ignored artifacts/V5/V5-04G2c/owner-protocol-sql.md; Solpartial_review owns only ignored artifacts/V5/V5-04G2c/owner-protocol-runtime.md; Pythonassembles. Sharedoutcome chooseminimumcorrect repeatedpublicconvergence compatible0004stage-onlyguard versusnewprofileguardupgrade. Rootownsallproduct/contracts. No tests/processes/network/DB/install/Git; readonlycommandsallowed. Directpeercoord andconcreterootdecision neededbeforedependentedit; unresolvedAstra. CurrentD5baccepted02/4dd stage-ownerhandofffeature isinternal, publicconvergence notimplemented yet.

IndependentV5-05 lane: Solsecurity_native owns only new examples/existing_index.py, examples/existing_index.mjs, examples/existing_index.md, packages/python/tests/test_existing_index_example.py, packages/typescript/tests/existing-index-example.test.mjs. Reuseactualnative evidence/source/retrievalinterfaces andexistingpublicsyntheticfixtures; no core/schema/manifests/locks/sharedfixture edits. Bothnativeexamples mustsubstantively mapcallerrecords withdeclaredcapabilities, immutableprovenance, exactUTF8source spans/digests, trustedtenantfilters, honestunsupportedcapabilities. No source/identity/providerclaim beyondexample. Rootowns tests/processes/docs/tracker/Git/finalintegration. Nopeerexecution/network/DB/install/Git. State implementationassigned; acceptancegatedV5-04.

### V5 security and purge schema prerequisite

Contract preflight found that the profile-4 guard accepts only a stage owner,
so D5b ownership transfer cannot support a subsequent security update. The
ownerless stale-stage lifecycle also prevents retaining a stage anchor as a
universal workaround. Root selected the additive profile-5 prerequisite in
[QP-r1](../contracts/QDRANT_PURGE_V5.md). The same migration introduces the
managed-content erasure representation needed by G3. Installing it does not
complete G2, G3 or V5; existing migrations remain byte-frozen.

- Task: V5-04G2/D5c and G3 shared schema prerequisite, implementation in progress.
- Shared outcome: repeated committed security owners and irreversible managed
  source/replay/request erasure with actual restricted PostgreSQL probes.
- Sol `purge_schema` owns only new migration
  `storage/qdrant/postgres/migrations/0005_security_owners_and_erasure.sql` and
  assembles the pair.
- Sol `purge_probes` owns only `tools/qdrant_purge_schema.py` and
  `tools/tests/test_qdrant_purge_schema.py`.
- Root owns QP-r1, existing files, native runner, catalog pins, tracker, all
  tests/services and Git; root is final integrator and escalation owner.
- Peers resolve schema/probe dependencies directly. Protected-boundary, outcome
  and external ownership changes require root before dependent edits; unresolved
  decisions go to Astra.
- Peers may inspect files and edit their paths, but run no tests, services,
  installs, network calls, databases or Git. Root serializes native execution.
- Acceptance starts with exact installation/rollback, caller/ACL/RLS probes and
  guard/erasure failure cases. Physical Qdrant absence remains a separate gate.
- V5-05 example paths transferred to root. Focused checks passed: 10 Python and
  8 Node. Final V5-05 acceptance remains gated by V5-04/C2.

Validation policy: preflight contracts and failure mechanisms before code;
reproduce failures narrowly, fix their cause, then run focused checks. Run full
suites at integration checkpoints. No further full-suite rerun is warranted
solely by documentation or unchanged inputs.

Independent V5-06 implementation lane: Sol `mcp_host` owns only source/tests in
`packages/mcp-python/` and `packages/mcp-typescript/` against frozen
[MT-r1](../contracts/MCP_V5.md). Root owns their manifests, lockfiles, TypeScript
configuration, all execution and final integration. Pinned official SDKs were
installed only in those optional packages: Python 2.3.0 and Node 2.4.0. No core
manifest or public core API changed. The worker may inspect files and edit owned
paths, but runs no tests, services, installs, network, databases or Git. One
read-only retrieval tool binds trusted scope, filters and limits outside client
input; no write/repair/purge transport. Final V5-06 acceptance remains gated.

Native schema fixture preflight passed with cleanup in
`artifacts/V5/V5-04-profile5/seed-02/`: real profile-4 writer commits purge,
stage-owner, prior-security-owner and same-current-security-owner histories.
The first fixture attempt exposed the profile-4-only admission requirement;
the fixture now installs that exact prerequisite before constructing its writer.
This is fixture evidence, not profile-5 or physical purge acceptance. Focused
schema/probe helper checks passed, 43 tests; actual new SQL probes remain pending.
Root committed the independently verified existing-index example as `93571df`;
its report keeps final upstream acceptance separate.

Profile-5 schema prerequisite accepted as an independent implementation gate:
44 focused helper tests and 14 restricted native PostgreSQL checks passed,
including real rollback and fresh read-only historical confirmation. The
isolated fixture cleaned up. [Evidence](../evaluation/reports/V5/V5-04-profile5-schema.md).
Commit `a5323bb` was pushed. The SQL fixture's absence digest is synthetic;
runtime profile admission and actual Qdrant absence remain open.

Profile-5 runtime admission pair: Sol `purge_schema` owns Python native
authority, writer, recovery and source paths plus their existing focused tests,
and assembles the pair. Sol `purge_probes` owns the corresponding TypeScript
paths and tests. Their previous migration/probe paths transferred to root after
the SQL acceptance. They share QP-r1's pinned profile and exact capability
query; old profiles remain strict. Root owns fixtures, native consumers, all
execution, Git and final integration. Peers edit only assigned paths, run no
processes or tests, and coordinate exact SQL interfaces directly. Any protected
boundary or outcome change comes to root before implementation. Python focused
admission tests passed: 533. Native profile-5 runtime checks are pending.

Optional MCP host implementation is ready for integration, with 36 Python and
36 Node SDK tests passing and both strict builds/typechecks passing. The close
regression was reproduced and fixed; [evidence](../evaluation/reports/V5/V5-06-implementation.md).
Python child-process stdio and installed-artifact verification remain open;
V5-06 final acceptance still depends on V5-04, V5-05 and C2. No live model or
provider calls were used.

Profile-5 runtime admission handoff: both Sol peers transferred their Python
and Node authority/writer/recovery/source tests and implementations to root;
root integrated the native checker and Node child probe. Focused Python 533,
Node 331, strict Python typecheck 49 files and Node build passed. The disposable
PostgreSQL 17 run admitted actual restricted Python and Node writer/reader
logins, passed 18 checks and verified cleanup. [Evidence](../evaluation/reports/V5/V5-04-profile5-runtime.md).
The first Node focused run exposed an old explicit profile-upgrade regression;
its owner fixed the profile pin and the focused suite passed. G2 public
convergence, native erased-source retrieval, actual Qdrant absence and H fault
acceptance remain open. User audits and protected migration bytes were not
edited. One local PostgreSQL fixture and one test process ran at a time; no
model/provider/hosted run occurred. Learning practice remains unassessed. Next
smallest action: native profile-5 recovery admission, then repeated security
convergence with the current committed owner.

### V5-04G2b2d5c private runtime assignment

Task ID: V5-04G2b2d5c. Shared outcome: profile-5 private recovery, security
projection, dispatch and guarded settlement accept an actual committed prior
or current security owner, while stage owners retain their existing exact
checks. Both runtimes must reject fabricated owner metadata and old-profile
fallback. QP-r1 and migration 0005 are frozen inputs; this assignment does not
include the public manager or physical purge.

- Sol `security_owner_python` owns only `_qdrant_writer.py`,
  `_qdrant_recovery.py` and their existing Python tests. It assembles the pair.
- Sol `security_owner_node` owns only `qdrant-writer.ts`,
  `qdrant-recovery.ts` and their existing Node tests.
- Root owns shared contracts, native fixture/consumer files, execution,
  tracker, final integration and Git. Peers may read dependencies and make
  substantive edits only in their paths; no tests, services, database, network,
  installs or Git actions in peer lanes. One test process at a time under root.
- Peers coordinate exact owner binding and helper semantics directly. An agreed
  path transfer requires the previous writer to stop and root to be notified.
  Outcome, protected boundaries or another lane's ownership changes come to
  root before dependent edits; unresolved decisions go to Astra.
- Acceptance: focused tests per runtime, strict typechecks/build, then serial
  actual PostgreSQL/Qdrant recovery and repeated-owner cases with cleanup.
  State: assigned; native/public acceptance remains open.

Independent V5-06 process lane: Sol `mcp_process` owns only a new
`packages/mcp-python/tests/test_stdio_process.py` and any test-local fixture in
that file. It will exercise the installed Python host through a real child
process and official SDK stdio session with fake native retrieval. Root owns
the MCP source, manifests, builds, tests, tracker, Git and integration. The
worker may inspect dependencies but runs no processes, installs, network or
tests. It reports any needed source/API change before editing outside its file.
This lane does not alter the V5-06 upstream acceptance gate.

V5-06 process-lane handoff: the Sol worker transferred only
`packages/mcp-python/tests/test_stdio_process.py` to root. Root inspected and
ran its four child-process cases, then the 40-test Python MCP package suite;
both passed. The child used installed editable imports, an official SDK stdio
session and bounded shutdown. The wheel-install gate remains V5-08. No provider,
database or hosted service ran; task-owned children closed. Final V5-06
acceptance still waits for V5-04/V5-05/C2. Learning practice is unassessed.

Continuation check: MCP process evidence committed and pushed as `a04b3a6`,
with exact remote head and zero ahead/behind verified. Earlier D5c worker
handles are absent; their eight edited files are preserved as
IMPLEMENTED_UNVALIDATED. New Sol pair `d5c_python` / `d5c_node` receives the
same nonoverlapping Python/Node four-file ownership and QP-r1 outcome above;
Python assembles. Root retains all native tools, contracts, execution, tracker
and Git. Finish and review the actual existing edits before native acceptance;
no new scope or services are authorized by this reassignment.

D5c native repetition assignment: root owns the parent protocol and Python
consumer. Sol `d5c_native_node` owns only
`tools/check_typescript_qdrant_security_verification.mjs`, implementing the
matching exclusive `repetition_config` mode. Four observations cover initial
stage-to-security completion, same-current security owner refencing, a next
authorization using the prior security owner, and ownerless denied-stage
bootstrap. Python/Node run serially on actual disposable PostgreSQL/Qdrant.
Root freezes the protocol, integrates and runs all checks; the worker runs no
tests, processes, services, network, installs or Git. Existing modes and user
audits are protected. Runtime/API dependencies go directly to the Node/Python
peers, with outcome or protected changes escalated to root.

D5c focused integration: Python 441 passed and Node build passed. Node focused
run had 270 pass / 10 failures; root isolated obsolete admission expectation,
undefined fake mutation counter and new security-owner metadata fixture paths.
The previous Node worker handle is absent. Sol `d5c_node_fix` receives only
the four Node runtime/test paths to resolve these exact failures; root retains
the native consumer and all test execution. No acceptance claimed.

D5c final handoff: all peer paths transferred to root. Focused Python/tool
455 and Node 280 passed; strict Python typecheck (49 files) and Node build
passed. Actual repetition probes passed eight checks per runtime, with matching
semantic witness, and profile-5 lost-COMMIT completion passed 16 checks across
both runtimes. All native runs verified cleanup. [Report](../evaluation/reports/V5/V5-04G2b2d5c.md).
Root fixed the stage-only reservation assumption and three fixture defects,
then checked the affected cases before the focused suite. G2b's private
projection/dispatch/settlement/handoff is accepted; G2c public convergence,
G3 purge, H and the remaining V5 gates stay open. No schema/grant/dependency
or README change. User audits are excluded; last disk observation 24 GiB.
Learning practice remains pending. Next action: G2c public convergence using
the accepted private path, followed by native failure/source acceptance.

### G2c public manager assignment

Shared outcome: implement QSC-r1 `converge_security` on the existing publication
manager in native Python and Node. Sol `g2c_python` owns only
`qdrant_publication.py` and `test_qdrant_publication.py`; it assembles. Sol
`g2c_node` owns only `qdrant-publication.ts` and `qdrant-publication.test.mjs`.
Root owns QSC-r1, the narrow internal Node profile-5 gate, native consumers,
all execution, docs/tracker/Git and final integration. Peers coordinate exact
reference/result/owner and cleanup semantics directly. No peer tests, services,
network, DB, installs or Git. No schema/roles/public authority API changes.
Protected or outcome changes come to root before dependent edits, unresolved
root/Astra. State assigned; public/native acceptance remains open. D5c commit
`c82decb` is pushed with matching remote head and zero ahead/behind verified.

G2c native acceptance pair: Sol `g2c_native_python` owns new
`tools/qdrant_public_security_cases.py` and assembles; Sol `g2c_native_node`
owns new `tools/check_typescript_qdrant_public_security.mjs`. Shared outcome:
eight actual public-manager cases with the frozen observation protocol from
root, including repeated updates, lost completed HTTP ACK/refencing retry,
ownerless bootstrap, authority drift/tombstone and source authorization. Root
owns the existing parent verifier, protocol tests, all execution/services,
docs/tracker/Git and final integration. No worker execution, network, database,
installs or Git. Peers coordinate exact witness and fixture semantics directly;
protected/outcome changes root before edits, unresolved root/Astra. Native
runtime clients remain at most writer, supervisor and reader; run languages
serially and verify cleanup. Public implementations transferred to root;
initial Python focused suite passed 44 after replacing an unsupported asyncio
test marker with the existing project runner. Node's affected four public
tests passed after completing its stored-row fixtures and exhausting a valid
ledger instead of constructing invalid zero-attempt limits.

G2c final handoff COMPLETE: all public/native peer paths transferred to root.
Focused public manager tests passed Python 44 / Node 25; full Python/tool
3,039 passed (four existing warnings), Node 1,515 passed, strict Python49 and
Node build passed. Final combined actual PostgreSQL/Qdrant public run passed
16 checks with exact witness parity and cleanup. [Evidence](../evaluation/reports/V5/V5-04G2c.md).
Root corrected fixture pointer/row/async/ledger assumptions, strengthened exact
two-generation/four-point and unavailable-source assertions, and integrated
readable native consumers. No security predicate/schema/grant/dependency was
relaxed. Sixteen seals unchanged; user audits excluded; disk24GiB observation.
No model/provider/hosted run or release. Learning practice remains pending.
Root owns final prose/link/staged review and commit/push/sync. Next: G3
tombstone-bound exact-ID deletion, authenticated absence and managed body
erasure under QP-r1; H and remaining V5 gates remain open.

### G3 full runtime assignment

G2c commit `4ce97b7` is pushed; exact remote head and zero ahead/behind verified.
Shared outcome: implement the complete G3-r1 runtime addendum in QP-r1, from
bounded exact-ID deletion through genuine absence, atomic managed body erasure
and public idempotent purge. Sol `g3_python` owns Python writer, recovery,
security-verification and publication modules plus new `test_qdrant_purge.py`;
it assembles. Sol `g3_node` owns the corresponding four Node modules plus new
`qdrant-purge.test.mjs`. Each language has one writer for dependent work. Root
owns shared contracts/schema/native tools, all execution/services, docs/tracker,
Git and final integration. Migrations, grants, existing tests and source/store
contracts are protected; required changes come to root before edits. Peers
coordinate concrete nominal plan/receipt/erasure interfaces directly; unresolved
outcome/boundary decisions go root/Astra. No peer tests/processes/network/DB/
installs/Git. Preserve existing G2 upsert-only behavior. Acceptance requires
focused/strict checks, actual serial native end-to-end failures and the final
regression checkpoint; no G3 acceptance yet.

G3 Python split adjustment: before any recovery edits, Python assembler
transfers only `_qdrant_recovery.py` to Sol `g3_python_recovery`, with new
`test_qdrant_purge_recovery.py` for that child's focused coverage. Assembler
retains writer, security-verification, publication and main purge test. The
helper coordinates exact nominal projection/plan interfaces directly with
the assembler and Node peer; no concurrent writer on any file. Root owns
native acceptance and serial execution. This splits dependent implementation
within the authorized subsystem; the full G3 outcome and protected boundaries
are unchanged.

G3 native acceptance pair: Sol `g3_native_python` owns
`tools/qdrant_purge_cases.py` after root freezes its pure producer/header and
assembles; Sol `g3_native_node` owns new
`tools/check_typescript_qdrant_purge.mjs`. Shared eight-group protocol is
`artifacts/V5/V5-04G3/native-protocol.md`; root owns new parent checker and
independent actual read-only SQL body/metadata assertions, all execution and
Git. No worker tests/process/network/DB/install/Git. Public/native sources are
transferred; initial Python new21/strict49 and Node new2/strictbuild passed.
Those local checks do not validate the full physical/SQL purge path.

G3 final review pair: Sol `purge_review_python` owns only ignored
`artifacts/V5/V5-04G3/python-final-review.md` and assembles; Sol
`purge_review_node` owns only ignored `node-final-review.md` in that folder.
Shared outcome: identify concrete authority, lifetime, retained-history and
cross-runtime defects in the current G3 implementation against the frozen
runtime addendum. Product files are read-only; no peer execution, services,
network, database, installs or Git. Peers coordinate concrete parity findings
directly and escalate protected/outcome changes to root, then Astra if unresolved.
Root owns all implementation/native tools, serial execution and final integration.

G3 cancellation regression split: the final-review pair now owns substantive
native consumer additions within the existing handoff case. Python owns only
the consumer body in `tools/qdrant_purge_cases.py` (header/producer protected),
Node owns `tools/check_typescript_qdrant_purge.mjs`; Python assembles. Root stops
writing these paths until transfer. Shared outcome: actual caller cancellation
after genuine purge receipt/finalization entry, callback custody and controller
exclusion while held, no late erasure, drain, then successful explicit retry.
Use observed checkpoints rather than sleeps; preserve fixture/check/witness
shape. No peer execution or services. Root retains all other paths and execution.

G3 runtime checkpoint handoff: all peer paths transferred to root; no active
worker writes remain. Public purge, nominal DELETE plans/absence receipts,
guarded settlement, owner handoff, managed erasure and retained historical
confirmation are implemented in both languages. Root fixed the Python
competing document lock under the actual supervisor guard and added a native
spy that rejects recurrence. Full Python/tool suite 3,067 passed (four existing
serializer warnings), Node 1,517 passed with strict build, Python strict49
passed, final tool fixture checks7 passed, 16 seals unchanged. Actual final
native traces passed eight public scenario groups plus six independent SQL
checks per runtime, including cancellation suppression/callback custody,
rollback after real erasure, actual lost-COMMIT reply and exact read-only
confirmation. Both witnesses match; successful owned processes/listeners/pools
closed. [Checkpoint report](../evaluation/reports/V5/V5-04G3.md) names exact
private evidence paths and limitations. Disk28GiB observed; no installs/model/
provider/hosted operations. User audits and README unchanged. G3 remains
IMPLEMENTED_UNVALIDATED at full acceptance: next smallest action is actual
current-key/foreign-target pending refusal and changed authority/owner during
purge guard or finalization. H and later V5 gates remain open. No production
readiness claim. Learning practice pending: explain why physical absence cannot
settle a write whose still-valid credential can mutate the same point later.
Root owns prose/link/staged review, focused checkpoint commit/immediate push
and remote synchronization, then the remaining G3 acceptance cases.

### G3 remaining native faults assignment

Previous goal turn made concrete progress: commit `f8ecbb9` implements managed
purge and records 28 native checks; full G3 and V5 acceptance remain open.
Sol `g3_fault_python` owns only ignored `fault-python-proposal.md` in
`artifacts/V5/V5-04G3` and assembles; Sol `g3_fault_node` owns only ignored
`fault-node-proposal.md` there. Shared outcome: runnable matching native
current-key/foreign-target pending refusal and authority/owner change during
purge guard or finalization. Initial mode read-only analysis plus owned
proposal; consumer implementation ownership follows root's shared protocol
freeze. Peers coordinate directly, distinguish actual HTTP from deliberately
malformed SQL fixture state and escalate protected/outcome decisions to root,
then Astra if unresolved. No peer execution/services/network/DB/install/Git.
Root owns all product/shared fixtures/parent/tracker, serial checks and Git.

G3 fault protocol r1 frozen in ignored
`artifacts/V5/V5-04G3/fault-protocol.md`. Root extended pure fixture/header and
parent with four exact fault labels, a monotonic authority-change document,
followup purge and independent terminal/erasure checks. Python now owns only
`python_purge_cases` consumer body; Node owns its existing native consumer;
Python assembles. Actual current-key refusal uses the same genuine proof
following a completed DELETE reply loss. Foreign-intent refusal deliberately
injects one malformed historical SQL state in the isolated fixture, observes
the exact refusal branch and restores the full row/trigger before continuing;
it is not evidence of a new uncertain HTTP effect. Root authorizes only this
fixed fixture-admin fault, no product privilege or catalog changes. Owner and
authority replacement use actual writer/security APIs. Root owns shared files,
all serial execution and final integration; no peer test/process/service runs.

G3 final handoff: Python and Node Sol peers transferred their successor helper,
manager route and focused tests to root; Python assembled the cross-runtime
source review. Root integrated five native fault checks, including an actual
committed successor-handoff reply loss. The final serial PostgreSQL 17/Qdrant
1.20 parent run passed 40 checks (20 per runtime), equal semantic hashes and
task-owned cleanup. Focused Python/tool 24, full Python/tool 3,078 (four
existing warnings), Node full 1,517, strict TypeScript build and Python mypy
49 files passed. The 16 input seals matched. Changed G3 paths: contract,
Python/Node writer and publication managers, focused tests, pure/native purge
checkers and this report/tracker. No schema/grant/lockfile, live provider,
hosted database or publication change. Disk headroom 30 GiB and system memory
free 59%; owned processes and listeners closed. Unrelated retrieval/LangChain
and user audit edits remain outside this G3 scope. Learning practice remains
unassessed. Next smallest action: freeze and execute V5-04H's exact 43-case
matrix against the final source, starting with atomic stage and publication
COMMIT boundaries, then continue V5-05/06 acceptance and C2.

V5-04H-S1 assignment: two Sol peers share the native atomic stage-boundary
outcome under frozen ignored `artifacts/V5/V5-04H/stage-fault-protocol.md`.
Python `h_stage_python` owns only `tools/qdrant_publication_manager_cases.py`
and is assembler; Node `h_stage_node` owns only
`tools/check_typescript_qdrant_publication_manager.mjs`. Both implement actual
stage rollback and post-COMMIT reply loss with exact immutable row/pointer and
zero HTTP assertions, then report to root. Read-only dependencies: 43-case
fixture, public manager contract, existing native parent and tests. No product,
schema, fixture, migration, manifest, lockfile or tracker edits by peers. No
peer tests/processes/services/network/DB/install/Git. Root owns shared parent
check/test, serial native execution, final integration, tracker and Git.
Peer dependency messages go directly to the other owner; unresolved protected
decisions go to root then Astra. State: assigned, final H acceptance open.

H-S1b parity handoff: native consumer assembly exposed an existing stage
lost-COMMIT public result difference. Python returned unavailable; Node
read-only-confirmed logically but did not declare a SQL READ ONLY transaction.
Astra advised exact Python confirmation while preserving Node's established
success, plus stage-specific Node hardening. Frozen ignored protocol:
`artifacts/V5/V5-04H/stage-confirmation-parity.md`. Sol `h_parity_python`
owns only Python `_qdrant_writer.py` and `test_qdrant_writer.py`, assembler;
Sol `h_parity_node` owns only Node `qdrant-writer.ts` and
`qdrant-writer.test.mjs`. One shared outcome: exact same-intent read-only
confirmation after genuine lost stage COMMIT, no mutation replay, matching
errors/cancellation. Root retains H-S1 consumers, shared docs/fixture,
execution, tracker and Git. No peer tests/processes/network/DB/install/Git.
State: assigned; H-S1 native acceptance waits for parity integration.

H-S1 final handoff: both managed Sol pairs transferred their files; Python
assembled each cross-runtime outcome. Root corrected only observed harness
faults (a staged receipt has false authority_committed, a fresh manager needs
its own writer-bound recovery, issued replay objects require byte/hash
comparison, and an unset Node target must not match SQL NULL). The final
serial native parent passed 32 checks (16 per runtime), matching public
snapshot hashes and task-owned cleanup. Five frozen H IDs are now evidenced:
`intent_commit_failed`, `intent_ack_lost`, `source_commit_failed`,
`source_ack_lost`, `claim_ack_lost`. [Checkpoint report](../evaluation/reports/V5/V5-04H-stage.md).
Focused Python writer/tool 260 and Node writer 232 passed; full Python/tool
3,088 (four existing warnings), full Node 1,530, strict mypy 49 files and
TypeScript build passed. Sixteen sealed inputs matched. Contract/fixture/docs,
writer source/tests, native parent/consumers/test and report/tracker are the
owned change. No migration/grant/dependency/lockfile/provider/hosted/release
change. Disk headroom 28 GiB, system memory free 50%; task-owned services
closed. User audit and unrelated retrieval/adapters/README edits remain
outside scope. Learning practice unassessed. V5-04H and V5 parent remain open;
next smallest H action is genuine final publication CAS COMMIT reply loss
(fixture ID `publication_ack_lost`), then the remaining 43-ID matrix.

H-S2 assignment: shared outcome is genuine successful final publication CAS
COMMIT with its acknowledgment withheld, exact read-only historical
confirmation and zero mutation replay, mapping frozen matrix ID 19. Frozen
ignored protocol: `artifacts/V5/V5-04H/publication-commit-protocol.md`.
Sol `h_publish_python` owns only Python `_qdrant_writer.py` and writer tests,
assembler; Sol `h_publish_node` owns only Node `qdrant-writer.ts` and writer
tests. Root owns the disjoint native public-manager consumers, shared contract,
serial PostgreSQL/Qdrant integration, report/tracker and Git. Peers message
each other directly for concrete dependencies. No schema/grant/migration/
lockfile/public API change or peer tests/services/network/DB/install/Git.
State: assigned; H and V5 parent acceptance remain open.

H-S2 final handoff: both Sol peers transferred the writer and focused-test
files; Python assembled the cross-runtime source review. Root integrated the
native public-manager fault consumers and corrected an observed Python capture
collision before final validation. The final serial PostgreSQL 17/Qdrant 1.20
parent passed 34 checks (17 per runtime), with matching public snapshot hashes
and task-owned cleanup. Frozen matrix ID `publication_ack_lost` now has native
evidence: the actual final CAS commits, its reply is withheld, the retired
connection is not reused, an independent read-only observer sees the exact
terminal graph, and a fresh same-intent retry performs no mutation. [Checkpoint
report](../evaluation/reports/V5/V5-04H-publication-commit.md). Focused Python
writer/tool 265 and Node writer 248 passed; full Python/tool 3,093 (four
existing warnings), full Node 1,546, strict mypy 49 files and TypeScript build
passed. Sixteen sealed inputs matched. The owned change is the contract,
Python/Node writers and tests, native consumers, report and tracker. No schema,
grant, migration, dependency, lockfile, hosted provider or release change.
Disk headroom 28 GiB and system memory free 51%; task-owned services closed.
Unrelated retrieval/adapters/README and user audit edits remain outside scope.
Learning practice is unassessed. V5-04H and V5 remain open; next smallest action
is to freeze and exercise the next uncovered transaction-boundary matrix rows.

H-S3 assignment (V5-04H matrix ID `bootstrap_acl_changed`): shared outcome is
an actual native manager replay of the same published stage after a later
security change, with changed initial grants/metadata rejected as
`IntegrityViolation`, no new SQL/HTTP mutation, and current ACL/pointer
preserved. Sol `h_bootstrap_python` owns only
`tools/qdrant_publication_manager_cases.py` and is assembler; Sol
`h_bootstrap_node` owns only
`tools/check_typescript_qdrant_publication_manager.mjs`. Both do substantive
work under the frozen existing fixture and public-manager contract; peers
coordinate concrete interfaces directly. Root owns shared contract, parent,
serial native runs, report/tracker and Git. No product/schema/fixture/migration/
lockfile/public API changes or peer tests/processes/services/network/DB/install/
Git. Outcome, protected-boundary or other-lane ownership changes return to
root before dependent edits; unresolved design goes to Astra. State: assigned;
H and V5 parent acceptance remain open.

H-S3 final handoff: Python and Node Sol peers transferred their separate
native consumer files; Python assembled their matching grant/tag change,
checks and result order. Root found one harness order mismatch in the first
local parent run, corrected the emitted label positions, and reran the native
parent serially. The final PostgreSQL 17/Qdrant 1.20 run passed 36 checks
(18 per runtime), matching public snapshot hashes and task-owned cleanup.
Exact frozen ID `bootstrap_acl_changed` now has native evidence for rejection
after a later security update, unchanged ACL/pointer/terminal graph and zero
SQL/HTTP mutation. [Checkpoint report](../evaluation/reports/V5/V5-04H-bootstrap-acl.md).
Four focused parent validation tests and all 16 seals passed. Changed files:
the two native consumers, this report and tracker. No product/schema/grant/
fixture/dependency/lockfile/hosted/release change. Disk headroom 28 GiB,
system memory free 51%; task-owned processes closed. Unrelated user edits
remain outside scope. Learning practice unassessed. H and V5 remain open;
next smallest action is the committed partial-member graph corruption case
(matrix ID `partial_member_stage`), distinct from atomic stage rollback.

H-S4 assignment (V5-04H matrix ID `partial_member_stage`): shared outcome is
fixture-admin deletion of exactly one member from an already committed,
unpublished two-member stage, followed by actual manager publication refusal
before HTTP mutation. Preserve the prior active pointer and assert the
persisted generation still declares two expected members while only one member
row remains. This is a deliberate corrupted-graph fixture, not a public
half-commit path. Sol `h_bootstrap_python` owns only
`tools/qdrant_publication_manager_cases.py` and is assembler; Sol
`h_bootstrap_node` owns only
`tools/check_typescript_qdrant_publication_manager.mjs`. They coordinate the
exact stage target, admin SQL, check label/order and failure assertions
directly. Root owns contract, parent, serial native runs, report/tracker and
Git. No product/schema/fixture/migration/lockfile/public API changes; no peer
tests/processes/services/network/DB/install/Git. Fixture-admin corruption
uses the disposable local authority only. Changes to outcome, protected
boundaries or another lane return to root first; unresolved decision to
Astra. State: assigned; H and V5 remain open.

H-S4 final handoff: Python and Node Sol peers transferred their separate
native consumer files; Python assembled the exact one-member deletion,
persisted-graph assertions and matching check order. Root inspected both
diffs and ran the real parent serially. PostgreSQL 17/Qdrant 1.20 passed 38
checks (19 per runtime), matching public snapshot hashes and verified
task-owned cleanup. Exact frozen ID `partial_member_stage` has native evidence:
admin corruption leaves one of two declared members, real publication rejects
before HTTP, and the prior active pointer and graph remain unchanged.
[Checkpoint report](../evaluation/reports/V5/V5-04H-partial-member.md). Four
focused parent tests and all 16 seals passed. Changed files are the two
native consumers, this report and tracker. No product/schema/grant/fixture/
dependency/lockfile/hosted/release change. Disk headroom 28 GiB, system
memory free 47%; task-owned processes closed. Unrelated user edits remain
outside scope. Learning practice unassessed. H and V5 remain open; next
smallest action is to map already executed native fault evidence to exact H
IDs where the mechanism and assertions match, then implement the next missing
native boundary without relabeling adjacent evidence.

H-S5 existing-evidence handoff: root reviewed the final native parent result
and both consumer assertions, then registered exact frozen IDs
`intent_payload_changed`, `write_ack_lost`, `verified_prepared_commit_lost`
and `pointer_cas_race` in the [mapping report](../evaluation/reports/V5/V5-04H-existing-native-mapping.md).
Their actual 19-check-per-runtime PostgreSQL 17/Qdrant 1.20 run, matching
public hashes and cleanup are the H-S4 parent evidence; no new test or service
run is claimed for this mapping. The changed file scope is this report and
tracker only; user edits remain outside scope. Twelve exact H IDs now have
native evidence. Resource observation is inherited from the same parent run:
28 GiB disk headroom, 47% free system memory; no new task-owned processes.
Learning practice unassessed. H and V5 remain open. Next smallest action is
the reserved dispatch-before-HTTP process boundary (matrix IDs 8 and 9),
which the existing dispatched-state worker crash cannot substitute.

H-S6a assignment: root froze the additive private `ordinary-worker-r1`
reserved observer event in [QW-r1](../contracts/QDRANT_PUBLICATION_V5.md).
Shared outcome is a real child-to-parent event after durable reserve and
before mark-dispatched, with exact attempt/digest binding and ordered,
single-use parent validation; ordinary public output, existing later
before-write behavior and owned cleanup remain intact. Sol `h_reserved_python`
owns only Python `qdrant_publication.py`, `_qdrant_publication_worker.py` and
their two existing focused test files, and assembles. Sol `h_reserved_node`
owns only Node `qdrant-publication.ts`, `qdrant-publication-worker.ts` and
their two existing focused test files. Both make substantive source/test edits
and resolve event/error/order details directly. Root owns contract, native
consumers, all serial test/service runs, report/tracker and Git. No schema,
fixture, migration, lockfile, public manager API, recovery or supervisor
changes; no peer tests/processes/services/network/DB/install/Git. Outcome or
protected-boundary change goes to root before edits, unresolved design to
Astra. State: assigned; native reserved crash acceptance waits for S6b.

H-S6a source handoff: Python and Node Sol peers made and transferred separate
manager, worker-protocol and focused-test edits; Python assembled the two
implementations. Root integrated the frozen private contract, ran Python
focused publication/worker tests (82 passed), Node focused tests (62 passed),
strict TypeScript build and mypy (49 source files) serially. [Checkpoint
report](../evaluation/reports/V5/V5-04H-reserved-seam.md). The `reserved`
event is emitted after durable reservation and before dispatched/HTTP;
parent validation binds it to the original attempt and later before-write
metadata. Native process-death acceptance is pending, so state is
IMPLEMENTED_UNVALIDATED for H IDs 8/9. Changed files: QW contract, Python and
Node manager/worker sources and focused tests, report and tracker. No schema,
fixture, migration, grant, dependency, lockfile, provider or hosted change.
Task-owned services were not started for this source checkpoint; unrelated
user edits remain outside scope. Learning practice unassessed. Next smallest
action H-S6b: extend the native child harness with an isolated reserved-stage
fixture, kill/reap that child at the new committed barrier, and prove journal,
physical absence, prior pointer and successor refusal in both runtimes.

H-S6b assignment: shared outcome is a separate disposable native worker
scenario using the already frozen base stage and successor fixture. Publish
the base generation, stage the successor, then terminate/reap the exact child
when its `reserved` event arrives after real SQL COMMIT and before
`mark_dispatched`/HTTP. Independently observe the durable reserved journal,
absent successor points, preserved base pointer and unchanged supervisor;
an elapsed-time fresh child retry must not create a second dispatch or
publish. Sol `h_reserved_native_python` owns only new
`tools/qdrant_reserved_worker_cases.py` and is assembler; Sol
`h_reserved_native_node` owns only new
`tools/check_typescript_qdrant_reserved_worker.mjs`. They coordinate exact
result labels, safe output shape and observed boundaries directly. Root owns
`tools/check_qdrant_publication_worker.py` scenario selection, serial native
execution, report/tracker and Git. Existing worker consumer files, product,
schema, fixture, migrations, lockfiles, public APIs and supervisor/recovery
remain protected. No peer tests/processes/services/network/DB/install/Git.
Outcome/protected/other-lane changes to root first; unresolved design to
Astra. State: assigned; H IDs 8/9 and V5 remain open pending native evidence.

H-S6b ordinary-worker regression assignment: the new reserved event changes
the existing native observer stream. Shared outcome is to keep the accepted
dispatched-crash and paused-old-worker boundaries exact: assert the new
reserved event precedes the matching before-write event, then terminate/pause
only at before-write and count only actual HTTP status observations. Sol
`h_bootstrap_python` owns only
`tools/qdrant_publication_worker_cases.py` and assembles; Sol
`h_bootstrap_node` owns only
`tools/check_typescript_qdrant_publication_worker.mjs`. Both use the frozen
private event contract, preserve existing check labels/hash inputs and
coordinate the event assertions directly. Root owns serial native runs,
report/tracker and Git. No product/schema/fixture/migration/lockfile change
or peer tests/processes/services/network/DB/install/Git. Escalate outcome,
protected-boundary or other-lane changes before edits. State: assigned.

H-S6b final handoff: Python and Node Sol peers assembled the separate native
reserved-crash consumers and existing ordinary-worker observer regressions.
Root integrated the scenario-selecting parent, fixed only two observed fixture
issues (optional Python verifier close and the fixed EOF channel's new
reserved-event acknowledgment), then ran both runtimes serially on disposable
PostgreSQL 17/Qdrant 1.20. Reserved scenario: 12 checks (six per runtime),
matching public hash and verified cleanup. Ordinary worker regression: 18
checks (nine per runtime), matching public hash and verified cleanup.
[Checkpoint report](../evaluation/reports/V5/V5-04H-reserved-crash.md). Full
Python/package-tool 3,097 passed (four existing serializer warnings), full
Node 1,557 and strict build passed; mypy 49 source files and 16 seals passed.
`journal_commit_before_api` has accepted native evidence. The actual
`reserved_owner_crash` child-kill/retry trace is partial because the bounded
1.05-second wait does not cross a configured lease-expiry boundary; do not
count that ID complete. Thirteen exact H IDs have complete native evidence.
Changed files: new Python/Node reserved consumers, scenario parent, existing
ordinary consumers, this report and tracker. No product/schema/grant/fixture/
migration/dependency/lockfile/provider/hosted change in S6b. Disk headroom
28 GiB, system memory free 47%; task-owned processes/listeners closed.
Unrelated user edits remain outside scope. Learning practice unassessed.
H and V5 remain open; next smallest action is to settle the lease-boundary
interpretation for ID 9 and implement the remaining complete fault rows,
including supervisor/coordinator death, without treating elapsed time alone
as fencing.

H-S7 assignment (V5-04H matrix ID `known_completed_replay`): one root writer
owns only the existing Python native ordinary-worker consumer, the H report
and tracker. The Node consumer already checks its settled journal across the
second real child run; Python must add the same scoped read-only journal
comparison. Shared existing worker result, no new HTTP event, one logical
attempt and unchanged parent supervisor/pointer are required. Verify with
both serial native runtimes and focused parent tests. No product/schema/
fixture/migration/lockfile change; user edits remain outside scope. State:
assigned, H/V5 open.

H-S7 final handoff: root added a scoped SQL READ ONLY settled-journal
comparison to the Python second-child historical replay, matching Node's
existing assertion. The serial PostgreSQL 17/Qdrant 1.20 ordinary-worker
parent passed 18 checks (nine per runtime), matching public hash and verified
cleanup; focused parent tests passed three. Exact frozen ID
`known_completed_replay` now has [native evidence](../evaluation/reports/V5/V5-04H-known-replay.md):
a second real child returns identical durable publication without a new
reserved/before-write/HTTP event or changed settled journal. Fourteen H IDs
are complete. Changed files: Python native consumer, report and tracker.
No product/schema/fixture/grant/dependency/lockfile/provider/hosted change;
unrelated user edits remain outside scope. Disk headroom 28 GiB and system
memory free 40%; task-owned services closed. Learning practice unassessed.
H and V5 remain open; next smallest action is the next missing native matrix
boundary, while ID9 waits for an explicit no-owner-lease acceptance decision.

H-S8 assignment (V5-04H matrix ID `budget_before_dispatch`): shared outcome
is an actual manager budget refusal on the already staged base intent that
leaves the exact durable journal, staged snapshot, pointer and HTTP request
count unchanged. Sol `h_bootstrap_python` owns only
`tools/qdrant_publication_manager_cases.py` and assembles; Sol
`h_bootstrap_node` owns only
`tools/check_typescript_qdrant_publication_manager.mjs`. Both add a distinct
frozen-ID check label without changing public snapshot inventory/hash, and
coordinate assertion/order parity directly. Root owns serial native parent,
report/tracker/Git. No product/schema/fixture/migration/lockfile/provider
change, no peer tests/processes/services/network/DB/install/Git. Outcome or
protected/other-lane changes to root before edits, unresolved design to
Astra. State: assigned; H/V5 open.

Independent H-S9 read-only evidence audit: Sol `h_available_audit` owns only
ignored `artifacts/V5/V5-04H/available-native-audit-r2.md`. Map exact frozen
IDs 10, 12-16, 18, 37 and 38 to previously executed real Python/Node native
checks, source assertions, accepted reports and remaining mismatches.
No product, fixture, schema, tracker or committed report edits; no tests,
processes, services, network, DB or Git. Root integrates the audit only after
checking recorded evidence, and never marks an ID complete from a worker
claim alone. This lane does not change H-S8 ownership or acceptance. State:
assigned.

H-S8 final handoff: the Python and Node Sol peers transferred their separate
native manager consumer edits; Python assembled the same ledger/journal/
snapshot/HTTP assertions and matching check order. Root ran the serial
PostgreSQL 17/Qdrant 1.20 parent: 40 checks (20 per runtime), matching public
snapshot hashes and verified task-owned cleanup. Exact frozen ID
`budget_before_dispatch` has [native evidence](../evaluation/reports/V5/V5-04H-budget.md):
the exhausted publish raises `BudgetExhausted` with unchanged empty journal,
staged snapshot, pointer and physical HTTP counters. Four focused parent
validation tests and all 16 seals passed. Fifteen H IDs are complete.
Changed files: two native consumers, report and tracker. No product/schema/
fixture/grant/dependency/lockfile/provider/hosted change. Disk headroom
28 GiB, system memory free 47%; task-owned services closed. Unrelated user
edits remain outside scope. Learning practice unassessed. H and V5 remain
open; next action is to inspect the independent H-S9 native-evidence audit
and implement only the still-missing fault boundary.

H-S9 audit handoff: Sol `h_available_audit` produced only ignored
`artifacts/V5/V5-04H/available-native-audit-r2.md` and ran read-only source,
fixture and accepted-evidence inspection. Root checked its exact-ID mapping
against current consumers. ID 18 has an existing public source boundary;
ID 10 needs a stronger identity assertion before registration; IDs 12-16
need same-trace public manager refusal; ID 37 needs an actual unresolved
journal under a forged physical proof. ID 38 has a combined managed recovery
mechanism but still needs a fresh H run and explicit epoch adaptation.
No worker-run native result is claimed by the audit.

H-S10 final handoff (V5-04H matrix ID `prepared_not_published`): one root
integrator owned the evidence registration and serial native rerun; no peer
writer was needed for an existing scenario. The current F3 public manager
was paused at trusted authorization after durable preparation. Native
PostgreSQL 17/Qdrant 1.20 returned 16 checks (eight per runtime), identical
source-observation hashes and verified cleanup. The prepared successor was
physically searchable but could not release source; the previous active
generation remained authorized until CAS publication. [Checkpoint report](../evaluation/reports/V5/V5-04H-prepared-source.md).
Changed files: this tracker and the report only. Resource headroom: 28 GiB
disk, 53 percent system memory free; all task-owned native services closed.
No hosted/provider/model/installation action, product/schema/fixture change
or unrelated edit. Learning practice unassessed. Sixteen exact H IDs now
have accepted native evidence; H and V5 remain open. Next smallest action:
strengthen ID 10 same-intent identity assertions in the existing Python and
TypeScript partial-repair consumers, then rerun both native runtimes.

H-S11 assignment (V5-04H matrix ID `partial_qdrant_write`): two Sol peers
share one outcome: prove that the existing real nine-point 8+1 split-batch
fault preserves the previous pointer and resumes the exact original
intent/revision/generation after missing-only repair. This adapts the frozen
two-chunk illustration without changing its failure boundary; the completed
first batch loses its reply and the second batch is not sent. Python peer
`h_partial_python` owns only `tools/qdrant_partial_repair_cases.py` and is
assembler. Node peer `h_partial_node` owns only
`tools/check_typescript_qdrant_partial_repair.mjs`. Each strengthens the
same-trace returned and staged identity assertions in its own consumer and
checks prior pointer and one repair attempt without changing output shape or
check order. They coordinate assertion parity directly. Root owns shared
fixture/contract, report/tracker, serial native parent, final acceptance and
Git. Protected: product code, schema, migrations, locks, seals, other native
consumers and user edits. No peer tests/processes/services/network/DB/Git;
root alone runs serial PostgreSQL 17/Qdrant 1.20.0 native integration with
one test process at a time and synthetic vectors. Escalate changed outcome,
protected boundary or other-lane ownership to root; unresolved design goes
to Astra. State: assigned; H and V5 open.

H-S12 assignment (V5-04H matrix ID `managed_recovery_old_key_rejected`):
root owns an independent evidence-only registration while H-S11 peers edit
their separate consumers. Reinspect E1/E2b current source and rerun their
existing native parents serially in fresh ignored H artifacts. Require real
lost-ack HTTP writes, durable SQL block before physical fence, same-storage
restart with old-key HTTP 401, new-key readback and scoped settlement before
private reopen. Map frozen illustrative epochs 7-to-8 to native 1-to-2
explicitly. Root alone owns report/tracker, services, final integration and
Git. No product/fixture/schema/migration/lock/seal changes; one test process,
synthetic vectors, no provider/hosted action. State: assigned; H/V5 open.

H-S12 final handoff: root inspected E1/E2b consumers and ran both native
parents serially on fresh private fixtures. E1 passed nine checks per runtime;
E2b passed eight SQL permission checks and 21 recovery checks per runtime.
Both reported verified cleanup. The combined trace covers actual lost-reply
writes and unknown journals, committed block before fencing, old-key HTTP
401 after same-storage restart, new-key readback, scoped settlement and
private ordinary reopen. Frozen epoch 7-to-8 is an illustrative value;
native fixtures assert 1-to-2. [Checkpoint report](../evaluation/reports/V5/V5-04H-managed-recovery.md).
Changed files: tracker and report only. No product/schema/fixture/lock/seal,
provider, hosted or model action. Task-owned services closed; unrelated
user edits and H-S11 peer files remain outside this registration. Learning
practice unassessed. Seventeen exact H IDs have accepted native evidence;
H and V5 remain open. Next: integrate H-S11 exact partial-repair identity.

H-S11 final handoff: Sol Python and Node peers completed separate native
consumer assertions and coordinated the cumulative 8,8,1 ordinary trace;
Python assembled and both writers stopped before root verification. Root
inspected both diffs, added the Python actual `completed` response check,
then ran five focused parent protocol guards and a fresh serial native
PostgreSQL 17/Qdrant 1.20 parent. Eight checks per runtime passed with
verified cleanup; all 16 seals matched. The same original intent, revision,
generation and seals remain through uncertainty, denied recovery and
missing-only repair; the previous pointer holds until final publication.
[Checkpoint report](../evaluation/reports/V5/V5-04H-partial-write.md).
Changed files: two native consumers, report and tracker. No product/schema/
fixture/migration/lockfile/provider/hosted change. Resource headroom:
28 GiB disk and 54 percent system memory free; task-owned services closed.
Unrelated user edits remain outside scope. Learning practice unassessed.
Eighteen exact H IDs have accepted native evidence; H and V5 remain open.
Next smallest action: add same-trace public manager publication refusal for
the existing F1 wrong-membership/vector/profile native mutations.

H-S13 assignment (V5-04H matrix ID `forged_quiescence_proof`): the next
smaller independent boundary is an actual fabricated physical-proof refusal
while E2b has two durable unknown journals. Sol `h_forged_python` owns only
`tools/qdrant_recovery_cases.py` and assembles; Sol `h_forged_node` owns only
`tools/check_typescript_qdrant_recovery.mjs`. Both contribute the same
native assertion: after a genuine physical fence, submit serialized and
invented proof-shaped objects with matching epoch/PID/quiescence fields to
the real recovery authority boundary, require `UnsupportedCapability`,
compare exact journal and blocked SQL/native admission before/after, then
continue genuine settlement. Coordinate field shape, error and ordered
check label directly. Root owns report/tracker, serial native parent,
combined checks and Git. Contract/fixture, product, schema, migration,
locks, seals, other consumers and user edits protected. Peers run no tests,
services/network/DB/Git; root uses one local test process, synthetic data,
no hosted/provider/model action. Escalate changed outcome, protected/other
ownership to root, unresolved material decision to Astra. State: assigned;
H and V5 open. The F1 public-manager corruption group remains a later
separate fixture slice.

Independent H-S14 read-only preparation: Sol `h_public_fault_design` owns
only ignored `artifacts/V5/V5-04H/public-corruption-design.md`. Inspect
current F1 verifier and public-manager native consumers to propose the
smallest isolated actual public publish fault scenario for frozen IDs
`equal_count_wrong_set`, `wrong_dense_vector`, `wrong_sparse_vector`,
`missing_sparse_vector`, `wrong_full_profile`. Show where physical writes,
same-trace manager refusal, unchanged pointer/flags and complete-vector
repair checks belong, and note resource/fixture isolation. No code/shared
fixture/tracker/committed report edits, tests/processes/services/network/
DB/Git. This preparation does not claim H acceptance and does not overlap
H-S13; root decides sequencing after inspecting it. State: assigned.

H-S13 final handoff: Sol Python and Node peers added matched fabricated
physical-proof checks to separate E2b native consumers and coordinated the
restricted 16-column journal projection and ordered label indices. Python
assembled; both writers stopped before root integration. Root inspected
both diffs, ran four focused protocol guards, then one serial native parent
against PostgreSQL 17/Qdrant 1.20. It passed eight SQL checks plus 22 per
runtime, with verified cleanup; 16 seals matched. Copied and invented proof
objects reached `advance_owner`, raised `UnsupportedCapability`, and left
the two genuine unknown journal rows and blocked SQL/native admission
unchanged. Genuine settlement then completed. [Checkpoint report](../evaluation/reports/V5/V5-04H-forged-proof.md).
Changed files: two native consumers, report and tracker. No product/schema/
fixture/migration/lockfile/provider/hosted action. Disk headroom 28 GiB,
system memory free 54%; task-owned processes closed. Unrelated user edits
remain outside scope. Learning practice unassessed. Nineteen exact H IDs
have accepted native evidence; H and V5 remain open. Next: inspect H-S14
read-only public corruption design, then implement one isolated public
manager refusal fault before widening to the remaining related IDs.

H-S14 design handoff: Sol `h_public_fault_design` wrote only ignored
`artifacts/V5/V5-04H/public-corruption-design.md` after read-only source
inspection. It found that public publish rewrites an unprepared stage before
verification, so pre-seeded F1 corruption would be overwritten. A real
post-forward completed PUT / pre-ACK fixture mutation is required. The
existing default manager suite has fixed pointer/journal/snapshot history;
use an exclusive fresh native mode. `wrong_dense_vector` is the smallest
first case; other rows, equal-count sentinel and missing-sparse full-body
repair remain open. No native acceptance follows from the design.

H-S15 assignment (V5-04H matrix ID `wrong_dense_vector`): shared outcome
is actual public manager refusal on one same-dimension wrong dense vector,
with previous pointer and unpublished target flags preserved. Contract
`public-wrong-dense-r1` is frozen in ignored
`artifacts/V5/V5-04H/public-wrong-dense-protocol.md`. Sol
`h_dense_python` owns only `tools/qdrant_publication_manager_cases.py` and
assembles; Sol `h_dense_node` owns only
`tools/check_typescript_qdrant_publication_manager.mjs`. Both implement
the exclusive mode, exact physical post-forward fault, genuine public
refusal and matching three-snapshot hash. Root owns parent CLI/protocol
tests, reports/tracker, serial native and default regression, Git and final
integration. Product/schema/migration/lock/seal/shared fixture/other
consumer/user edits protected. Peers run no tests/processes/services/
network/DB/Git; root uses one local test process and two synthetic points
per runtime, no provider/hosted/model action. Directly resolve assertion
parity; escalate outcome/protected/ownership changes to root and unresolved
material issue to Astra. State: assigned; H and V5 open.

H-S15 final handoff: Sol Python and Node peers wrote separate public-manager
native consumer modes and coordinated e0-to-e1 same-ID fault, three public
snapshots and exact output shape; Python assembled and both writers stopped.
Root owned the parent CLI and five focused protocol guards, inspected both
diffs, diagnosed the UUID-order fixture assumption and closed-handle probe,
then corrected the consumers. The final isolated parent passed one actual
public refusal check per runtime with identical snapshot hash and verified
cleanup. The default parent passed 40 regression checks, retained its
previous snapshot hash and verified cleanup. All 16 seals matched.
[Checkpoint report](../evaluation/reports/V5/V5-04H-wrong-dense.md).
Changed files: parent, two native consumers, protocol guard, report and
tracker. No product/schema/fixture/migration/lockfile/provider/hosted
action. Disk headroom 28 GiB, system memory free 53%; task-owned services
closed. Earlier failed private fixture directories remain ignored evidence.
Unrelated user edits remain outside scope. Learning practice unassessed.
Twenty exact H IDs have accepted native evidence; H and V5 remain open.
Next smallest action: extend the isolated public corruption mode to one
sparse-vector fault, preserving default regression and explicit physical
readback/pointer checks.

H-S16 assignment (V5-04H matrix IDs `wrong_sparse_vector` and
`wrong_full_profile`): shared outcome is two fresh native public-manager
corruption modes proving genuine publication refusal and previous-pointer
preservation. Contract `public-corruption-r2` is frozen in ignored
`artifacts/V5/V5-04H/public-corruption-r2-protocol.md`. Sol
`h_sparse_python` owns only `tools/qdrant_publication_manager_cases.py`
and assembles; Sol `h_sparse_node` owns only
`tools/check_typescript_qdrant_publication_manager.mjs`. Both implement
actual post-forward completed sparse-weight and full-profile fault writes,
physical readback and matching result/check/hash semantics. Root owns
parent CLI/protocol test, reports/tracker, serial native and default
regression, Git and final integration. Product/schema/migration/locks/
seals/shared fixture/other consumer/user edits protected. Peers run no
tests/processes/services/network/DB/Git; root uses one local test process
and synthetic points, no provider/hosted/model action. Resolve dependencies
directly; escalate changed outcome/protected/ownership to root and any
unresolved material issue to Astra. State: assigned; H/V5 open.

H-S16 final handoff: Sol Python and Node peers added exclusive public-manager
fault modes in separate native consumers and coordinated their exact physical
readback and three-snapshot contract directly; Python assembled. Root reviewed
the diffs, extended the parent CLI and seven focused protocol guards, then ran
both new modes, wrong-dense regression and the default manager serially on
native PostgreSQL/Qdrant. The new modes each passed one check per runtime with
matching hashes; wrong-dense passed two and default passed 40 with their
previous hashes. All four parents verified cleanup and all 16 seals matched.
[Checkpoint report](../evaluation/reports/V5/V5-04H-sparse-profile.md).
Changed files: parent, two consumers, protocol guard, report and tracker. No
product/schema/fixture/migration/lockfile/provider/hosted action. Disk
headroom 28 GiB, system memory free 54%; one orphan from an earlier
disposable run was stopped. Unrelated user edits remain outside scope.
Learning practice unassessed. Twenty-two exact H IDs have accepted native
evidence; H and V5 remain open. Next smallest action: an isolated
`missing_sparse_vector` public fault followed by ordinary complete-vector
repair, with previous-pointer and immutable-graph checks.

H-S17 assignment (V5-04H matrix ID `missing_sparse_vector`): shared outcome
is actual public refusal after one completed sparse removal, then ordinary
same-intent complete-vector repair and publication. Contract `missing-sparse-r1`
is frozen in ignored
`artifacts/V5/V5-04H/missing-sparse-r1-protocol.md`. Sol
`h_sparse_python` owns only `tools/qdrant_publication_manager_cases.py` and
assembles; Sol `h_sparse_node` owns only
`tools/check_typescript_qdrant_publication_manager.mjs`. Both do substantive
native-consumer work and coordinate assertion parity directly. Root owns
parent CLI/protocol guard, serial native checks, report/tracker, Git and final
integration. Read-only dependencies: existing manager API, pinned fixture,
QW-r1 and the frozen acceptance row. Product/schema/migrations/locks/seals/
shared fixture/other consumers/user edits are protected. One test process,
synthetic two-point fixture, serial runtimes, no worker processes, provider,
model, hosted action or download. Escalate outcome/protected/other ownership
changes to root and unresolved material decisions to Astra. State: assigned;
H and V5 open.

H-S17 final handoff: Sol Python and Node peers wrote separate native-consumer
repair traces, resolved journal/profile assertion parity directly, and Python
assembled. Both stopped before root integration. Root inspected the diffs,
ran eight focused parent guards and syntax checks, then diagnosed the first
native `UnsupportedCapability` at the publication-only fixture profile. The
parent now installs the existing attestation migration only for this repair
mode. The final native parent passed refusal and repair in both runtimes
(four checks), matching snapshot hash and verified cleanup. Default manager
passed 40 checks with its previous hash; wrong-sparse regression passed two.
All 16 seals matched. [Checkpoint report](../evaluation/reports/V5/V5-04H-missing-sparse-repair.md).
Changed files: parent, two consumers, protocol guard, report and tracker.
No product/schema file/shared fixture/migration file/lockfile/provider/hosted
action. Disk headroom 28 GiB, system memory free 52%; no task-owned service
remains. The failed and diagnostic runs are retained as ignored evidence.
Unrelated user edits remain outside scope. Learning practice unassessed.
Twenty-three exact H IDs have accepted native evidence; H and V5 remain
open. Next smallest action: isolated `equal_count_wrong_set` public refusal,
including the required third-point sentinel and bounded enumeration check.

H-S18 assignment (V5-04H matrix ID `equal_count_wrong_set`): shared outcome
is two actual public-manager refusals, one equal-count replacement and one
third extra scoped point with observed bounded scroll. Contract `equal-set-r1`
is frozen in ignored `artifacts/V5/V5-04H/equal-set-r1-protocol.md`. Sol
`h_sparse_python` owns only `tools/qdrant_publication_manager_cases.py` and
assembles; Sol `h_sparse_node` owns only
`tools/check_typescript_qdrant_publication_manager.mjs`. Both do substantive
native-consumer work and resolve dependencies directly. Root owns parent
CLI/protocol, serial native/checkpoint verification, report/tracker, Git and
final integration. Existing manager API, acceptance row and fixture are
read-only dependencies. Product/schema/migrations/locks/seals/shared
fixture/other consumers/user edits are protected. One test process, small
synthetic points, serial runtimes, no worker processes, provider, hosted
action or download. Escalate outcome/protected/other ownership changes to
root and unresolved material decisions to Astra. State: assigned; H/V5 open.

H-S18 final handoff: Sol Python and Node peers implemented separate native
public-manager equal-set consumers, coordinated direct dependency details,
and Python assembled before both stopped. Root inspected the diffs and ran
nine focused parent guards and syntax checks. The first combined run failed
at Node's overly broad base-graph assertion; root used the failure location
and Python diagnostic to narrow it to immutable records and publication
fences. The accepted native parent passed equal-count replacement and
third-point bounded-scroll refusal in both runtimes (four checks), matched
snapshot hash and verified cleanup. Default manager passed 40 checks and
missing-sparse repair passed four, each with its prior hash and cleanup. All
16 seals matched. [Checkpoint report](../evaluation/reports/V5/V5-04H-equal-set.md).
Changed files: parent, two consumers, protocol guard, report and tracker.
No product/schema/shared fixture/migration/lockfile/provider/hosted action.
Disk headroom 31 GiB, system memory free 62%; no task-owned service remains.
Failed and diagnostic directories stay ignored. Unrelated user edits remain
outside scope. Learning practice unassessed. Twenty-four exact H IDs have
accepted native evidence; H and V5 remain open. Next smallest action: inspect
the remaining frozen matrix IDs and take one independent native fault whose
dependencies are already satisfied.

H-S19 assignment (V5-04H matrix IDs `mixed_revision_member`,
`malformed_utf8_span`, `unsupported_sparse_encoder`): shared outcome is
three native public-manager admission refusals with typed errors and zero
target writes. Contract `invalid-input-r1` is frozen in ignored
`artifacts/V5/V5-04H/invalid-input-r1-protocol.md`. Sol `h_sparse_python`
owns only `tools/qdrant_publication_manager_cases.py` and assembles; Sol
`h_sparse_node` owns only `tools/check_typescript_qdrant_publication_manager.mjs`.
Both do substantive work and coordinate directly. Root owns parent
CLI/protocol, serial native verification, report/tracker, Git and final
integration. Existing manager/manifest validators, pinned fixture and
acceptance rows are read-only dependencies. Product/schema/migrations/
locks/seals/shared fixture/other consumers/user edits are protected.
One test process, two-point fake vectors, serial runtimes, no worker
processes, provider, hosted action or download. Escalate changed outcome,
protected/other ownership to root and unresolved material decisions to
Astra. State: assigned; H/V5 open.

H-S19 final handoff: Sol Python and Node peers implemented separate native
public-manager invalid-input modes, coordinated typed errors and absence
assertions directly, and Python assembled before both stopped. Root inspected
the diffs and ran ten focused parent guards and syntax checks. The first
native run passed; root then limited Node's attempt observer to this mode
and reran the accepted path. The final native parent passed three typed
refusals per runtime (six checks), matching snapshot hash and verified
cleanup. Default manager passed 40 checks with its previous hash and
cleanup. All 16 seals matched. [Checkpoint report](../evaluation/reports/V5/V5-04H-invalid-input.md).
Changed files: parent, two consumers, protocol guard, report and tracker.
No product/schema/shared fixture/migration/lockfile/provider/hosted action.
Disk headroom 32 GiB, system memory free 54%; no task-owned service remains.
Unrelated user edits remain outside scope. Learning practice unassessed.
Twenty-seven exact H IDs have accepted native evidence; H and V5 remain
open. Next smallest action: select one unmet native matrix fault after
checking its dependency and resource profile; retain final H integration
and later V5 gates as open.

H-S20 assignment (V5-04H exact ID `backend_wide_recovery_gate`): shared
outcome is a real backend-wide mutation block across a third document while
independent authoritative revocation commits during the same two-unknown
recovery window. Contract `backend-gate-r1` is frozen in ignored
`artifacts/V5/V5-04H/backend-gate-r1-protocol.md`. Sol `h_gate_python` owns
only `tools/qdrant_recovery_cases.py` and assembles; Sol `h_gate_node` owns
only `tools/check_typescript_qdrant_recovery.mjs`. Both do substantive native
consumer work and coordinate concrete dependencies directly. Root owns
focused parent tests, report/tracker, serial native verification, Git and
final integration. Existing QW-r1/E2b contract, actual native recovery API,
PostgreSQL 17 and pinned Qdrant 1.20 are read-only dependencies. Product,
schema/migrations, sealed/shared fixtures, locks, unrelated consumers and
user edits are protected. One test process, serial runtimes, small fake
points, no worker tests/services/network/DB/Git, provider, model or hosted
action. Outcome/protected/other ownership changes return to root; unresolved
material decisions go to Astra. State: assigned; H/V5 open.

Independent V5-downstream read-only lane: Sol `v5_gate_audit` owns only
ignored `artifacts/V5/downstream-gates-audit.md`. It inspects actual V5-05,
V5-06 and V5-C2 implementation/tests/docs against the active plan, then
returns exact remaining acceptance checks and runnable serial commands.
No source/tracker/shared fixture edits, tests/processes/services/network/DB/
Git. It does not declare acceptance or overlap H-S20; root owns decisions,
execution and final integration. Report dependency changes promptly. State:
assigned; V5-05/06/C2 remain open.

H-S20 final handoff: Sol Python and Node peers extended separate E2b native
recovery consumers with a third staged document; Python assembled after both
writers stopped. Root inspected both diffs and passed four focused protocol
tests, Python compile and Node syntax checks. The serial native parent passed
eight SQL plus 23 checks per runtime (54 total) with verified cleanup; all
16 seals matched. During two genuine unknown journals and a durable backend
block, third-document owner/native attempts were refused, while a separate
authority transaction committed grant revocation and survived final reopen.
[Checkpoint report](../evaluation/reports/V5/V5-04H-backend-gate.md).
Changed files: two recovery consumers, protocol guard, report and tracker.
No product/schema/migration/sealed fixture/lockfile/provider/hosted action.
The E2b trace checks old-scope authority refusal, not final source release;
that remains a separate G2c/H integration boundary. Disk headroom 29 GiB,
system memory free 34%; no owned service remains. Unrelated user edits stay
outside scope. Learning practice unassessed. Twenty-eight exact H IDs have
accepted native evidence; H and V5 remain open. Next smallest H action:
native cancellation after dispatched side effect, bounded without weakening
the durable unknown state.

V5-downstream read-only handoff: Sol `v5_gate_audit` wrote only ignored
`artifacts/V5/downstream-gates-audit.md`; no tests or services ran in that
lane. It found V5-05/06 implementations and focused tests present, with final
acceptance still gated by H/C2. It identified a stale MCP test-count sentence
in `docs/development.md`, a duplicate Python `_SafeWrite.aclose()` delegation
and incomplete MCP docstring examples for root review. Root has not treated
the audit as acceptance. Next downstream action after H: run V5-05/06 focused
suites serially, fix confirmed issues, then complete C2.

H-S21 assignment (V5-04H exact ID `cancellation_after_dispatch`): shared
outcome is a real completed Qdrant point PUT followed by caller cancellation
before ordinary acknowledgment, with durable uncertainty and the previous
active generation preserved. The frozen ignored protocol is
`artifacts/V5/V5-04H/cancel-after-dispatch-r1-protocol.md`. Sol
`h_cancel_python` owns only `tools/qdrant_publication_manager_cases.py` and
assembles; Sol `h_cancel_node` owns only
`tools/check_typescript_qdrant_publication_manager.mjs`. Both perform
substantive native consumer work, coordinate the cancellation barrier and
result shape directly, and may adjust their split only after explicit transfer
and notice to root. Root owns parent CLI/tests, report/tracker, serial native
integration, Git and escalation. QW-r1, source authority, product modules,
schema/migrations, sealed/shared fixtures, lockfiles and user edits are
protected. Peers run no tests/processes/services/network/DB/Git; root runs one
local suite at a time on small synthetic fixtures. Outcome or protected
boundary changes return to root; unresolved material decisions go to Astra.
State: assigned; H/V5 open. Verification: focused parent protocol test,
serial actual PostgreSQL 17 and pinned Qdrant 1.20 per runtime, exact state
and cleanup, seals, then scoped commit/push after review.

H-S21 final handoff: the exact `cancellation_after_dispatch` case passed on
disposable PostgreSQL 17 and pinned Qdrant 1.20 in Python and Node, with
identical public snapshot SHA-256 and verified cleanup. A real completed
successor point PUT was cancelled before manager acknowledgment; both runtimes
retained one `unknown` journal, the previous active pointer, exact physical
points and original intent identity. A new manager could not resend. The
first Python diagnostic isolated an early fixture control and expected
document-owner transfer; Node diagnostics identified a cancelled cleanup
signal that left `dispatched`. Root changed only the Node manager's bounded
conservative journal cleanup, then reran both. [Checkpoint report](../evaluation/reports/V5/V5-04H-cancel-after-dispatch.md).
Changed paths: two native consumers, parent CLI/protocol test, Node product
manager, report and tracker; the stale MCP test-count sentence was corrected
in `docs/development.md`. Node build and 25 focused publication regressions,
11 Python protocol tests, native parity and all 16 seals passed. Earlier
failed runs are diagnostic only. No model/provider/hosted call, migration,
shared fixture or lockfile changed. No owned service remains; disk headroom
was 28 GiB before the final native run. V5-05 focused tests/demos passed
(10 Python, 8 Node), and V5-06 focused tests/types passed (40 Python, 36 Node);
their final acceptance remains gated by V5-04 and V5-C2. User-owned dirty
files, including MCP sources, remain untouched. Learning practice is
unassessed. Twenty-nine of 43 exact H IDs now have accepted native evidence;
next smallest H action is one unresolved fault ID after reviewing the frozen
matrix and current native harnesses. H, V5-05/06, C2 and full V5 stay open.

H-S22 assignment (V5-04H exact ID `tombstone_before_purge`): shared outcome
is a committed tombstone that immediately denies retained and fresh source
release while actual old Qdrant points still exist and managed purge remains
incomplete. The frozen ignored protocol is
`artifacts/V5/V5-04H/tombstone-before-purge-r1-protocol.md`. Sol
`h_tombstone_python` owns only `tools/qdrant_purge_cases.py` and assembles;
Sol `h_tombstone_node` owns only `tools/check_typescript_qdrant_purge.mjs`.
Both do substantive native consumer work and coordinate exact observations
directly. Root owns the shared parent test, report/tracker, serial native
integration, Git and escalation. Product, SQL/schema/migrations, QW/ QP
contracts, sealed/shared fixtures, locks and user edits are read-only
protected boundaries. One local test process at a time; peers run no tests,
services, network, database or Git commands. Ownership transfer requires
agreement and root notice. Outcome/protected changes return to root;
unresolved material decisions go to Astra. State: assigned; H/V5 open.

H-S22 final handoff: Sol Python and Node peers extended separate native purge
consumers, coordinated the exact pre-purge scoped readback and witness order,
and Python assembled. Root inspected both diffs. After a real tombstone
commit, retained and fresh source reads denied release while a bounded
six-field Qdrant scroll still found all four expected base/successor points;
authority showed purge incomplete and successor publication was denied.
The existing purge trace then completed. [Checkpoint report](../evaluation/reports/V5/V5-04H-tombstone-before-purge.md).
Changed files: two native purge consumers, focused parent protocol test,
report and tracker. Seven focused tests passed. The serial native parent
passed 42 checks across Python/Node, matched semantic witness hashes and
verified cleanup. Final full local suites passed 3,104 Python/package-tool
tests (four existing serializer warnings) and 1,557 Node tests; strict
Python/TypeScript types and all 16 seals passed. The earlier full Python
suite ran against an in-progress split and failed the then-new nine-check
assertion; the assembled rerun passed. No provider/hosted call, product or
SQL/schema edit, migration, lockfile, shared sealed fixture or user edit.
Disk headroom 28 GiB; no owned service remains. Learning practice unassessed.
Thirty of 43 exact H IDs now have accepted native evidence. Next smallest
action: map an unresolved H fault to the existing actual process/security
harness, freeze its boundary and run both native runtimes. H and V5 remain
open; downstream V5-05/06/C2 acceptance is still gated.
