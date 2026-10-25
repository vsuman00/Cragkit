# V4 verification and security follow-ups

Status: COMPLETE for the scoped internal V4 follow-ups and verification. Scope is the internal V4 milestone and V4-AUD-01/V4-AUD-02, not production certification. The original user audit files remain unchanged. This report will record current evidence separately from the earlier V4 exit snapshot.

## Boundaries and fixes

V4-AUD-02 adds closed operation/stage/category labels and validated SQLSTATE diagnostics. Primary and cleanup failures remain separate. Exception messages, SQL, credentials, arbitrary exception class names and private query/source text are excluded. Native cancellation and failed cleanup cannot produce a passing result.

V4-AUD-01 adds an immutable private journal before fixture mutation, a target fingerprint and a role ownership marker committed with role creation. Recovery closes old clients before opening one fresh verified connection, uses a shared 25-second cleanup deadline and at most two serial attempts, checks ownership/history/policies/schema before mutation, and deletes only exact fixture rows, policies, privileges and the role. A failed or interrupted run retains its journal for explicit later recovery. No migration, permanent grant or core package API changed.

A native staging run exposed an overly strict inbound-membership check. The new fixture role had all restricted attributes and no membership in another role; PostgreSQL had granted the creating administrator membership in the fixture role. Recovery now permits only that inbound grant to the currently authenticated configured administrator. Other inbound memberships and every outbound role membership remain refused. The retained fixture was recovered explicitly with unchanged history checks. This was an integration failure fixed before final acceptance, not a passing first run.

Independent source review found two additional cleanup defects: stopping after the first close failure could leave another owned pool unclosed, and unbounded child/transaction cleanup could prevent reaching the parent's recovery deadline. Quiescence now attempts remaining owned closes within the shared budget, aggregates failures, and blocks fresh recovery if any closure fails. Child and administrator cleanup have one bounded owner. A separate review identified SQLSTATE-less psycopg failures on closed connections; only the actual optional driver error type plus a proven closed/broken handle maps to a retryable connection failure.

Role comments are not secret storage, and a privileged database administrator can forge them. The marker protects against accidental wrong-resource cleanup; it is not a security boundary against administrator compromise. [PostgreSQL COMMENT documentation](https://www.postgresql.org/docs/17/sql-comment.html). Driver cancellation and transaction cleanup require separate handling from application timeouts. [Psycopg asynchronous operation documentation](https://www.psycopg.org/psycopg3/docs/advanced/async.html).

A further final-integration review found that a parent DELETE could follow an unexpected foreign key or execute a DELETE trigger even when the fixture names and history matched. R-r1e now validates the complete canonical document cascade, every inbound collections foreign key, relation kinds/inheritance and DELETE triggers/rules before any role or row mutation. Installed vector storage is checked even for nonvector manifests. Three native rolled-back probes added an unexpected collection FK, leaf FK and vector DELETE trigger; all refused before mutation, preserved canary rows and retained the journal. This closes a recovery-tool deletion-boundary defect; core lifecycle code already had its own document cascade check.

## Administrative timing profile

Three full native attempts with an external 25-second deadline and default 10,000 ms request policy failed: deadline exceeded, provider unavailable, and a redacted diagnostic run that again reached its deadline. Cleanup completed. The diagnostic retained only bounded timings and closed error labels: the bounded diagnostic retained only slow execute calls above 200 ms and errors (last 32 observations), including repeated values around 227-270 ms, slower calls around 380-713 ms and cancellation at deadline; it did not retain SQL or query/source text. This filtered sample is not an unbiased round-trip distribution. It shows observed budget consumption, not a proven environment-only cause of the failures, a proven cause of the historical audit failures or a production benchmark.

AP-r1 adds an explicit `--evaluation-deadline-seconds 60` administrative profile. The default remains 25. Only successful synthetic evaluation/revocation/mechanics requests receive the chosen deadline; the fixed questions, candidate/call/attempt limits, deliberate 20-second fault probes and shared 25-second cleanup budget remain unchanged. Results carry the exact profile and deadline, and both runtimes must agree. The higher-latency parent/child run ceilings are 1,800/960 seconds. These are bounded administrative waits, not production latency targets. The first AP-r1 attempt changed only the external deadline and still failed: the library correctly enforced the earlier default 10,000 ms request policy. AP-r2 explicitly sets that policy to 60,000 ms for the opt-in profile and records `effective_evaluation_deadline_ms` in both runtime reports; tests reject mismatches. Default request limits remain 10,000 ms. For example, an external 60-second deadline with a 10,000 ms request policy still stops at 10 seconds; both must be configured for the explicit profile. The restricted temporary role expires after 32 minutes for the bounded 30-minute administrative run, with immediate normal cleanup; default expiry remains 10 minutes. Root interrupted one earlier AP-r2 run after source review found its old expiry could lapse before the longer Node phase. Cleanup completed; this was an interruption, not a proven expiry failure or passing result. A pass under `high_latency_admin` does not establish successful default-budget native acceptance. The final combined run passed under that explicit profile, as recorded below. Core code and product defaults are unchanged.

## Verification layers

| Layer | Evidence to record | Scope and limitation |
| --- | --- | --- |
| White-box unit and fault injection | Diagnostics, journals, exact SQL transport and parent cleanup tests | Malformed/duplicate/oversized journals, path substitution, ownership mismatch, unsafe roles/policies/history/schema, serial attempts, deadline/cancellation, late handles, redaction and separate failures. Fake SQL does not prove actual PostgreSQL behavior. |
| Black-box interfaces | CLI authorization/refusal, full shared fixtures, installed package and real SDK tests | Inspect observable result/error contracts, tool-scope rejection, final wrapper counting, import origins and optional dependency isolation. No production service is deployed. |
| Native integration | Dedicated direct Neon target, real restricted Python/Node roles and RLS | Hybrid/evidence/corrective mechanics, interruption/recovery, unchanged histories and pre-existing role/profile snapshots, final empty fixture inventory. Synthetic providers do not establish model quality. |
| Deployment security regressions | Combined migration/vector/storage/invariant/security checks and seven rolled-back negative probes | Creator defaults, PUBLIC ACLs, unexpected vector objects, setup-ledger RLS and SECURITY DEFINER refusal. The explicit managed primitive exception remains documented. |
| Dependency and artifact review | Frozen graphs and clean installed archives | Known advisory snapshot and inspected archive contents; no guarantee against unknown vulnerabilities or future advisories. |

## Requirement coverage through V4

These are the current implementation boundaries from the [BRD crosswalk](../../../docs/product/BRD.md#requirement-crosswalk). A deterministic pass does not complete later production or live-quality requirements.

| Requirement | Maintained executable evidence | Current scope; later requirement |
| --- | --- | --- |
| BR-01 native APIs | Native typechecks, request/result schemas, complete shared fixtures, installed archives and both SDK adapter suites | Local Python/Node environment; supported-platform CI and an independent developer trial remain V6. |
| BR-02 source integrity | Source-snapshot, packing, corrective and PostgreSQL corrective tests in both runtimes; native source authorization and revision checks | Exact canonical spans/digests and authorized release; source truth and relevance are separate questions. |
| BR-03 trusted scope | Planner/corrective/session tests, post-planner and post-search revocation cases, forged SDK/tool input, real runtime RLS branches | Scope and required filters remain fixed. V5 external store/source adapters need their own authorization evidence. |
| BR-04 honest result state | Assessment/packing/corrective fixtures, operational failure demo and primary/cleanup CLI diagnostics | Unknown support remains unknown; operational failure is distinct from missing evidence. Live assessment calibration remains separately evaluated. |
| BR-05 quality/cost comparison | Existing V4 stage ablations on six reviewed development questions, with explicit synthetic call counts | No correction gain was measured; correction stays opt-in. Held-out reviewed evaluation and thresholds remain V6. |
| BR-06 bounded work | Execution-ledger final-slot races, branch admission, nested retries, cancellation, pool/resource tests and native recovery probes | Deadline/call/attempt limits and honest unknown accounting. Sustained load and performance targets remain V6. |
| BR-07 final representation | Packing/assessment tests, shared token fixtures and actual Python/Node SDK wrapper recount | Uses the declared tokenizer/serialized representation; arbitrary application wrappers need their own recount. |
| BR-08 revision consistency | Ingestion/vector publication/lifecycle tests, profile mismatch/interrupted publication and native storage invariants | PostgreSQL generations and tombstones; V5 cross-store publication/repair is not implemented. |
| BR-09 privacy and untrusted data | Planner allowlists, hostile provider output, bounded events/exporter failures, SDK ambient tracing under network denial, diagnostic secret canaries | Default telemetry remains redacted. Provider use still requires configured disclosure/cost policy; no new live call ran here. |
| BR-10 optional integrations | Guarded core imports, separate SDK environments/locks, installed archive origin/dependency checks | Current optional integrations only. V5 adapters and V6 supported matrix/release provenance remain planned. |

Owned edge cases include E03, E05, E23-E24, E28, E33-E34, E38-E42, E44-E51 and the new E82 harness interruption/refusal case. Earlier ingestion/source/profile invariants remain covered by the complete regression suite. Conditional V5/V6 cases remain planned rather than being marked passed by mocks.

### V4-owned invariant checks

| Cases | Executable checks included in the final regression pipeline |
| --- | --- |
| E44 constraints and original intent | Both planning suites, corrective required-filter/revocation cases, QP/CR shared fixtures and real SDK forged-authority denial. |
| E45 repeat/no-progress termination | Normalized-query repeats, repeated candidate recapture, bounded distinct no-progress rounds and retained evidence in both corrective suites. |
| E46 final budget slot | Atomic reservation races and nested SDK retry charging in both execution-ledger suites. |
| E47 timeout/cancellation | Late backend/planner/exporter work, closed-ledger dispatch denial, SDK uncooperative engines and both native base runtime wait/query cancellation groups. |
| E48 selective retries | Permanent/transient fault matrices, retry admission/exhaustion, bounded backoff and native recovery transport attempts. |
| E49 honest unknown usage | Cancellation before/after dispatch, unknown cost holds, reconciliation overflow and strict unsupported accounting. |
| E50 bounded telemetry | Full queues, drop counters, failing/hanging exporters, concurrent flushes and at most one unsettled exporter. |
| E51 privacy | Closed event fields, secret/SQL/query canaries, hostile exception methods, SDK ambient tracing under network denial and redacted native diagnostic records. |
| E03/E38-E42 tool/packing boundaries | Shared direct/full-engine cases, strict declared tokenizer, final real SDK wrapper serialization and recount, source membership/digests and post-packing reassessment. |
| E82 administrative recovery | Private file substitution/target mismatch, exact SQL/inventory checks, real SIGKILL/admin loss, bounded retry/replay and three unsafe deletion-graph refusals with preserved canaries. |

Source suites are in [Python](../../../packages/python/tests), [Node](../../../packages/typescript/tests), [Python SDK](../../../packages/langchain-python/tests/test_adapter.py), [Node SDK](../../../packages/langchain-typescript/tests/adapter.test.mjs) and [administrative tooling](../../../tools/tests). The table identifies covered invariants; the results below identify the commands and actual passes.

## Production gates

| Gate | Current disposition |
| --- | --- |
| V4 features and audit follow-ups | COMPLETE for internal native/synthetic functionality, with the explicit timing-profile limitation recorded below. |
| V5 stores, source authorization, cross-store consistency and transports | Planned; complete V5 before V6 entry. No V5 implementation is inferred from this audit. |
| V6-01 supported matrix, frozen targets and evidence owners | Planned. Current local environment is one macOS arm64 configuration. |
| V6-02 held-out quality and uncertainty | Planned. Reviewed development fixtures and synthetic calls cannot substitute. |
| V6-03 sustained load/backpressure measurements | Planned. Small fixture/resource snapshots are not performance guarantees. |
| V6-04 release-candidate security/failure audit | This V4 audit supplies evidence; the later candidate still requires its full boundary/artifact review. |
| V6-05 independent developer trial | Not performed. |
| V6-06 CI, license/provenance and supported artifact matrix | Local archives checked in V4; hosted CI, supported matrix and release metadata remain separate. |
| V6-07 upgrade, backup/restore and rollback rehearsal | Planned; harness fixture recovery does not establish production migration recovery. |
| V6-08 publication/post-release smoke; V6-09 maintenance | Not performed or authorized by testing. |

## Results and run history

The final 34-stage local/installed pipeline passed with 1,405 Python/tool tests (four expected serializer warnings from deliberately bypassed invalid models), 878 core Node tests, 72 Python SDK and 69 Node SDK tests, all native/SDK typechecks and builds, complete shared conformance and 16 seals. Clean core archives passed three guarded import samples, 216 installed evidence cases and 44 installed V4 cases; clean optional archives repeated 72/69 real SDK tests. The first combined Python run exposed eight failures caused by a test reloading the diagnostics module and splitting exception-class identity; tests now import one shared module, a regression asserts that identity, and all 34 stages passed on rerun. This was test assembly, not a product error-policy change.

Final combined native acceptance passed 22 groups under `high_latency_admin`, external deadline 60 seconds and effective request policy 60,000 ms. It included six V3 packed-assessment cases and 20 corrective cases per runtime (18 labelled and two separate mechanics cases), full Node result parity, post-model source revocation, no model-held leases, maximum two clients and verified cleanup. Stderr was empty. Both base Python and Node runtime checks separately passed eight groups each, including wait/query cancellation and schema restoration; their stderr was empty.

The ten-group native recovery run passed SIGKILL, removed-journal denial, repeated completed cleanup before journal removal, old administrator loss, one failed connection, a proven closed recovery connection, unavailable-then-explicit recovery, three unsafe deletion-graph refusals and pre-existing role/membership/profile/history snapshots. Its stderr was empty. The post-run combined migration/vector/storage/invariant/security gate and all seven rolled-back remnant probes passed again. Final read-only inventory found zero fixture rows in all nine tables, zero runtime probe roles, zero application policies, no hidden authorization column, no remaining journals and an available/released advisory lock. Both history hashes are recorded in the machine results.

Four refreshed native package-manager audits reported no known advisories: Python core 34 packages, Python SDK 47; Node core 39 dependency entries, Node SDK 38. npm verified 20/37 registry signatures and 2/7 attestations for the installed core/SDK graphs respectively. These observations do not establish provenance for every future platform or absence of unknown vulnerabilities. The existing frozen default Python environment was restored after native work, removing the three optional PostgreSQL driver packages; the isolated core import test passed again.

All 14 prior core/SDK implementation and lock identities remain unchanged. [Machine results](V4-SECURITY-RESULTS.json) record 15 current tool/test hashes, eight archive hashes, final metrics, commands and failed/interrupted run history. Raw local logs are under `artifacts/V4/audit-verification`; credentials and connection strings are excluded from the committed report. The command entrypoints and recovery instructions are in [development.md](../../../docs/development.md#recovering-interrupted-native-fixtures).

Correction again showed no gain on the six reviewed development questions: document/facet recall 0.8 and zero questions with improved facet recall; labelled synthetic call totals were six/11/17 for hybrid/reranked/corrective. One unanswerable question still retrieved evidence in these modes, while the invariants prevented a sufficient status. Correction stays opt-in; fake providers and label-derived variants do not establish live model quality.

The current default 10,000 ms full native attempts remain FAILED evidence. The successful 60,000 ms administrative profile validates functionality and security under that configuration, without establishing default-budget performance or production latency. The historical audit failure's exact cause remains unproven. Unexpected lifecycle relations/deletion graphs fail closed and require operator inspection. These limits are retained rather than converted into passing claims. Results will distinguish passing final runs from the staging cleanup refusal and injected failures. No paid API call, model download, persistent service, production deployment or package publication is part of this verification.

## Final integration review

Independent Sol review found no remaining must-fix in the scoped deletion guard or evidence claims. Root checked all changed prose with the installed self-contained workflow: zero suspicious Unicode, low density and byte-identical deterministic cleaner output. All 274 local Markdown file targets in the reviewed documents passed; JSON parsed and the final tool/test identities matched the native run snapshot. All task-owned processes, pools and temporary credentials closed. Final resource snapshot: M4/16 GiB, 38 GiB free disk and 55 percent free memory; these are observations, not hardware or performance guarantees. The three user-owned audit reports remain unmodified and excluded from the verified change scope.

## Learning

For example, a process can finish its retrieval assertions and still fail because cleanup could not be verified. The CLI must report failure in that case. A durable journal makes later recovery possible, while exact ownership and history checks stop an operator from deleting a similarly named resource. Failure case: changing the role marker or history hash causes refusal before row deletion. Practice: explain why a missing journal cannot prove that a previous run cleaned up.
