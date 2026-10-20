# Cragkit implementation tracker

This is the single implementation completion tracker. All tasks start unchecked. Plan creation is not implementation completion. Read [the master plan](plan.md) and [edge-case inventory](EDGE_CASES.md).

V0: COMPLETE locally. Next smallest task: V1-01 (IMPLEMENTED_UNVALIDATED; hosted schema/security passed, native authenticated check pending). Complete each task's acceptance before starting its dependents.

Use status notes when needed: READY, IN_PROGRESS, BLOCKED, IMPLEMENTED_UNVALIDATED, COMPLETE. Check a box only for COMPLETE and attach evidence. Public publication remains pending until actually authorized and verified.

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

- [ ] V1-01: [Schema and explicit migrations](versions/V1-first-library.md#v1-01-schema-and-explicit-migrations) — IMPLEMENTED_UNVALIDATED; schema/tooling, hosted migrations and security checks passed; native authenticated connection verification pending. [Evidence](../evaluation/reports/V1/V1-01.md).

- [ ] V1-02: [Python connection lifecycle](versions/V1-first-library.md#v1-02-python-connection-lifecycle) — evidence: pending.

- [ ] V1-03: [TypeScript connection lifecycle](versions/V1-first-library.md#v1-03-typescript-connection-lifecycle) — evidence: pending.

- [ ] V1-C1: Demonstration, relevant regression checks, learning review and resource note through V1-03.

- [ ] V1-04: [Canonical text and source spans](versions/V1-first-library.md#v1-04-canonical-text-and-source-spans) — evidence: pending.

- [ ] V1-05: [Python staged ingestion](versions/V1-first-library.md#v1-05-python-staged-ingestion) — evidence: pending.

- [ ] V1-06: [TypeScript ingestion parity](versions/V1-first-library.md#v1-06-typescript-ingestion-parity) — evidence: pending.

- [ ] V1-C2: Demonstration, relevant regression checks, learning review and resource note through V1-06.

- [ ] V1-07: [Scoped lexical retrieval](versions/V1-first-library.md#v1-07-scoped-lexical-retrieval) — evidence: pending.

- [ ] V1-08: [Source-backed result assembly](versions/V1-first-library.md#v1-08-source-backed-result-assembly) — evidence: pending.

- [ ] V1-09: [Revision publication and deletion](versions/V1-first-library.md#v1-09-revision-publication-and-deletion) — evidence: pending.

- [ ] V1-C3: Demonstration, relevant regression checks, learning review and resource note through V1-09.

- [ ] V1-10: [Permission changes and final authorization](versions/V1-first-library.md#v1-10-permission-changes-and-final-authorization) — evidence: pending.

- [ ] V1-11: [Deadlines and cancellation](versions/V1-first-library.md#v1-11-deadlines-and-cancellation) — evidence: pending.

- [ ] V1-12: [First library demo and artifacts](versions/V1-first-library.md#v1-12-first-library-demo-and-artifacts) — evidence: pending.

- [ ] V1-C4: Demonstration, relevant regression checks, learning review and resource note through V1-12.

- [ ] V1-EXIT: Version acceptance complete; evidence and limitations recorded.

## V2: Hybrid retrieval

[Version plan](versions/V2-hybrid-search.md)

- [ ] V2-01: [Embedding profile decision](versions/V2-hybrid-search.md#v2-01-embedding-profile-decision) — evidence: pending.

- [ ] V2-02: [Python embedding adapter](versions/V2-hybrid-search.md#v2-02-python-embedding-adapter) — evidence: pending.

- [ ] V2-03: [TypeScript embedding adapter](versions/V2-hybrid-search.md#v2-03-typescript-embedding-adapter) — evidence: pending.

- [ ] V2-C1: Demonstration, relevant regression checks, learning review and resource note through V2-03.

- [ ] V2-04: [Vector generations and reindex](versions/V2-hybrid-search.md#v2-04-vector-generations-and-reindex) — evidence: pending.

- [ ] V2-05: [Scoped dense retrieval](versions/V2-hybrid-search.md#v2-05-scoped-dense-retrieval) — evidence: pending.

- [ ] V2-06: [Identifier search and rank fusion](versions/V2-hybrid-search.md#v2-06-identifier-search-and-rank-fusion) — evidence: pending.

- [ ] V2-C2: Demonstration, relevant regression checks, learning review and resource note through V2-06.

- [ ] V2-07: [Hybrid orchestration and fallbacks](versions/V2-hybrid-search.md#v2-07-hybrid-orchestration-and-fallbacks) — evidence: pending.

- [ ] V2-08: [Hybrid evaluation and checkpoint](versions/V2-hybrid-search.md#v2-08-hybrid-evaluation-and-checkpoint) — evidence: pending.

- [ ] V2-C3: Demonstration, relevant regression checks, learning review and resource note through V2-08.

- [ ] V2-EXIT: Version acceptance complete; evidence and limitations recorded.

## V3: Evidence selection and honest coverage

[Version plan](versions/V3-evidence-quality.md)

- [ ] V3-01: [Reranker contract and shortlist](versions/V3-evidence-quality.md#v3-01-reranker-contract-and-shortlist) — evidence: pending.

- [ ] V3-02: [Bounded reranking adapters](versions/V3-evidence-quality.md#v3-02-bounded-reranking-adapters) — evidence: pending.

- [ ] V3-03: [Tokenizer and renderer contract](versions/V3-evidence-quality.md#v3-03-tokenizer-and-renderer-contract) — evidence: pending.

- [ ] V3-C1: Demonstration, relevant regression checks, learning review and resource note through V3-03.

- [ ] V3-04: [Extractive packing](versions/V3-evidence-quality.md#v3-04-extractive-packing) — evidence: pending.

- [ ] V3-05: [Facet assessment policy](versions/V3-evidence-quality.md#v3-05-facet-assessment-policy) — evidence: pending.

- [ ] V3-06: [Post-packing reassessment](versions/V3-evidence-quality.md#v3-06-post-packing-reassessment) — evidence: pending.

- [ ] V3-C2: Demonstration, relevant regression checks, learning review and resource note through V3-06.

- [ ] V3-07: [Calibrate evidence policy](versions/V3-evidence-quality.md#v3-07-calibrate-evidence-policy) — evidence: pending.

- [ ] V3-08: [Evidence release checkpoint](versions/V3-evidence-quality.md#v3-08-evidence-release-checkpoint) — evidence: pending.

- [ ] V3-C3: Demonstration, relevant regression checks, learning review and resource note through V3-08.

- [ ] V3-EXIT: Version acceptance complete; evidence and limitations recorded.

## V4: Corrective retrieval alpha

[Version plan](versions/V4-corrective-alpha.md)

- [ ] V4-01: [Shared execution ledger](versions/V4-corrective-alpha.md#v4-01-shared-execution-ledger) — evidence: pending.

- [ ] V4-02: [Optional structured planning](versions/V4-corrective-alpha.md#v4-02-optional-structured-planning) — evidence: pending.

- [ ] V4-03: [Targeted corrective search](versions/V4-corrective-alpha.md#v4-03-targeted-corrective-search) — evidence: pending.

- [ ] V4-C1: Demonstration, relevant regression checks, learning review and resource note through V4-03.

- [ ] V4-04: [Loop termination and fault recovery](versions/V4-corrective-alpha.md#v4-04-loop-termination-and-fault-recovery) — evidence: pending.

- [ ] V4-05: [Privacy-controlled events](versions/V4-corrective-alpha.md#v4-05-privacy-controlled-events) — evidence: pending.

- [ ] V4-06: [Python framework adapter](versions/V4-corrective-alpha.md#v4-06-python-framework-adapter) — evidence: pending.

- [ ] V4-C2: Demonstration, relevant regression checks, learning review and resource note through V4-06.

- [ ] V4-07: [TypeScript framework adapter](versions/V4-corrective-alpha.md#v4-07-typescript-framework-adapter) — evidence: pending.

- [ ] V4-08: [Corrective quality and alpha packaging](versions/V4-corrective-alpha.md#v4-08-corrective-quality-and-alpha-packaging) — evidence: pending.

- [ ] V4-C3: Demonstration, relevant regression checks, learning review and resource note through V4-08.

- [ ] V4-EXIT: Version acceptance complete; evidence and limitations recorded.

## V5: Backend and transport extensions

[Version plan](versions/V5-integrations.md)

- [ ] V5-01: [Alternative-store consistency specification](versions/V5-integrations.md#v5-01-alternative-store-consistency-specification) — evidence: pending.

- [ ] V5-02: [Qdrant scoped candidate adapter](versions/V5-integrations.md#v5-02-qdrant-scoped-candidate-adapter) — evidence: pending.

- [ ] V5-03: [Source resolution and authorization](versions/V5-integrations.md#v5-03-source-resolution-and-authorization) — evidence: pending.

- [ ] V5-C1: Demonstration, relevant regression checks, learning review and resource note through V5-03.

- [ ] V5-04: [Publication and repair](versions/V5-integrations.md#v5-04-publication-and-repair) — evidence: pending.

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
