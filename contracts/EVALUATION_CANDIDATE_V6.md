# Candidate execution and scoring ECR-r1

State: frozen for V6-02E implementation before original held-out access. This contract does not authorize registry publication or a live provider call by itself.

For example, matching TypeScript source does not prove that an existing `dist/` directory was built from it. Compile the frozen source into a fresh temporary directory and compare the complete emitted file set before accepting an execution identity.

## Ownership

Sol runtime owns `tools/evaluation_runtime.py` and `tools/tests/test_evaluation_runtime.py`. Sol scoring owns `tools/evaluation_scoring.py` and `tools/tests/test_evaluation_scoring.py`, and assembles the pair. Root owns this contract, shared fixtures, the additive Python rerank-input audit hook, live/replay parent, candidate refreeze, tracker/Git and combined verification. Core packages, migrations, frozen metrics, labels, provider primitives and locks remain read-only. Peers resolve concrete dependencies directly; protected/outcome changes go to root, unresolved decisions to Astra. Serialize tests and builds; no provider/key/held-out access during implementation.

## Runtime identity

`prepare_runtime(root=ROOT, *, output)` requires matching clean EPB candidate source, exact declared runtime versions and preinstalled frozen dependencies. It makes no installations or network requests. It builds Node output from the checked source, refuses stale/extra emitted files rather than silently adopting them, fingerprints the pinned tokenizer and execution dependencies, writes an exclusive private receipt in a fresh owner-only output directory, and returns its JSON-compatible record.

`verify_runtime(root, receipt)` accepts a receipt mapping or private receipt path. It independently rechecks candidate source, runtime/dependency/tokenizer identities and complete file inventories. A fresh temporary TypeScript compilation must match both the current emitted files and the recorded identity; a forged digest of stale output cannot substitute for a build. Temporary builds close and clean up. It returns the verified record, never trust based solely on a caller boolean. Source or dependency drift, missing/extra output, symlinks escaping the owned roots, malformed receipts and version mismatches fail with fixed content-free errors. Routine tests use tiny synthetic layouts and injected build/Git/version boundaries; actual clean-candidate preparation is a separate run. File inventories and byte reads must be capped; Git/build processes have finite deadlines. Fingerprints describe execution identity, while the explicit frozen installs establish dependency provenance.

Receipt minimum identity: `revision: "ECR-r1"`, `source_commit`, `package_tree`, `configuration_sha256`, `runtime_versions`, `tokenizer_sha256`, `files` (relative category/path to digest) and `identity_sha256` over canonical identity JSON. Category names/complete schema are runtime-peer owned and must be reported to root before parent integration. Do not record credentials, source/query text or credential-bearing paths. Verification must execute from the same checkout/import origin as the worker. Compiled/dependency fingerprints are checked immediately before and after each execution stage; a changed identity invalidates the run. Python preparation/verification runs with `-B`, and any checkout `.pyc` in tools, runners or package source areas is refused: disabling writes does not disable cache reads. Do not delete user caches to satisfy this gate; prepare a fresh checkout. Installed dependency/stdlib bytecode remains part of the declared runtime fingerprint and frozen-install provenance scope.

The [RC identity prerequisite](../docs/decisions/0005-release-candidate-identity.md)
requires all six library manifest versions and internal core pins to match the
declared candidate. Verify loaded Python package/engine identities and the actual
Node public export as well. Matching byte fingerprints cannot excuse a package
that still declares the old prototype version. The common wire engine uses
`1.0.0-rc.1`; Python package metadata/export uses `1.0.0rc1`.
Read the Node export only from freshly compiled scratch output after the
complete emitted-file comparison passes; never execute unchecked existing
`dist/` while trying to verify it.

## Independent scoring

`score_observation(packet, reviewed_questions, observation, *, rerank_inputs=(), k=5)` is pure and returns a JSON-compatible per-mode report. It consumes the frozen independent `benchmark_metrics.py` functions without modifying that module. Validate all question/mode denominators and receipt aliases. Bind native IDs to logical revisions in a separate copied metric view; preserve the original result wire. Unknown identities stay invalid, never map by text alone. Use full trusted tenant/collection/document/revision source snapshots. Reject mismatched labels versus packet query/scope/filter identity. Operational failures remain explicit and count under frozen denominators; never turn them into an insufficient response or omit a mode.

Each mode reports individual scores and the frozen aggregate. Also report rerank same-shortlist verification, its original-order baseline and comparison delta, using the audit described below. Incomplete or altered candidate membership/text, dropped packing spans or ambiguous aliases must leave the comparison unverified and fail readiness; do not invent a baseline. A successful empty reranked result with no dispatched reranker has an empty baseline. Report invariant/operational/false-sufficient counts and the three predeclared paired deltas, with undefined denominators explicit. Readiness requires all frozen targets and verified same-shortlist comparisons; fake/recorded origin alone never proves live quality. The parent records origin separately. Positive held-out unit tests use synthetic questions only.

`validate_observation(packet, observation)` validates the closed native envelope,
complete ordered question/mode matrix and receipt aliases without reviewed
labels. The parent calls it before accepting a stage. A malformed worker wire
is retained separately where serializable and becomes an explicit failed stage
with every question/mode denominator, rather than aborting scoring without rows.

## Rerank audit and parent

Python EVX gains optional trusted keyword `on_rerank_input`, a synchronous void callback. It receives a fresh snapshot with exactly `question_id`, `mode`, `query_sha256`, `profile_id`, `candidates`; each candidate is exactly `candidate_id`, `text_sha256`, in actual adapter input order. Capture immediately before the configured rerank transport, after native authorization/source verification. No labels, rewritten policy or raw text are added. Context is request-local, including cancellation paths. The default callback is absent and existing EVX output fields remain unchanged. The callback cannot authorize a provider call or change candidates. Callback failure is operational failure. The parent stores this separate audit; Node output parity must retain identical native evidence identities.

The root parent will bind the packet, verify prepared runtime identity, run the actual Python provider worker once on disposable upgraded PostgreSQL with `RecordedProviderSend`, require healthy sealed recordings and cleanup, then replay on separate fresh Python and Node databases. Only explicitly selected original public input may enter the gate; root adds query-only variants without labels. Preserve all raw results and operational failures, verify replay consumption and normalized parity, score in the parent and report frozen targets. No automatic live retry/resend; interrupted journals remain unreplayable. A durable exclusive admission in the explicitly selected shared directory prevents a second live start for the same frozen configuration, even with a fresh output path; it is never automatically removed. Costs/calls retain actual recorder accounting; replay is not another independent inference. Paid execution remains disabled until secure provider configuration and the explicit live admission flag are present. Models stay hosted; no laptop model installation.
