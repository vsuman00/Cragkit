# V6: Release, validation and maintenance

Status: in progress. Task acceptance and remaining gates are tracked in [todo.md](../todo.md).

## Outcome and boundaries

Cleanly installable supported packages with reproducible evidence, migration guidance and a maintenance path.

Entry: V5 complete; freeze the candidate, supported matrix and evaluation targets.

Architecture mapping: Architecture phase 7; sections 1, 9, 11-16.

Artifact goal: 1.0.0-rc.1 followed by authorized 1.0.0 publication if all gates pass.

Follow the [master plan](../plan.md), [learning workflow](../LEARNING.md), and [edge-case inventory](../EDGE_CASES.md). Respect task dependency order and run one language suite at a time on the development machine. Independent authorized agent lanes follow [the coordination protocol](../../docs/agents/WORKFLOW.md); dependent work keeps one writer. A task has a target scope of 1-5 implementation/test files; if it expands beyond one focused session, split it into child tasks before proceeding. Paths below identify expected areas, not permission to rewrite entire directories.

## Tasks

### V6-01: Freeze release scope and thresholds

Dependency: V5-08. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Record the supported runtime/backend/provider matrix and quality/resource targets from prior baselines before the held-out run.

Acceptance: Every promised feature has a test/evidence owner; unresolved required choices block readiness rather than becoming assumed facts.

Verification: Audit BRD-to-architecture-to-task and edge-case coverage using the [BRD crosswalk](../../docs/product/BRD.md#requirement-crosswalk); review threshold definitions and corpus split integrity. Record the developer-trial comparison, measures and success criteria before running V6-05; unresolved numeric targets remain explicit until supported by baseline observations.

Learning exercise: Explain why targets must be fixed before seeing final evaluation results.

Expected areas: `Release manifest`, `evaluation protocol`, `decision records`.

### V6-02: Held-out retrieval evaluation

Dependency: V6-01. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Run declared baselines and the full library on held-out reviewed questions using a fixed corpus and configuration.

Preparation prerequisite (31 October 2026 amendment): V6-02F aligns the six
library manifests/internal pins, public package versions and common native
engine identity with the preregistered RC1 labels before source refreeze and
original held-out access. Split the work into contract/core, dependent metadata,
artifact guard and clean-identity slices. This moves version preparation earlier;
V6-06 still owns exact artifacts, notices, supported installs and actual CI
acceptance after V6-05. See [the identity decision](../../docs/decisions/0005-release-candidate-identity.md).

Recovery after the failed 3 November original held-out attempt: V6-02H adds
offline bounded provider pacing and safe status diagnostics in separate H1/H2
lanes followed by root H3 integration. Preserve the original failed admission,
tape and labels. V6-02I prepares a separate pending human-review packet and
records contamination before a later candidate/input refreeze; no approval or
new live dispatch is implied. Original evaluation targets remain unchanged.
See [the failed attempt](../../evaluation/reports/V6/V6-02E3-live-attempt.md) and
[ETP-r1](../../contracts/EVALUATION_TRANSPORT_V6.md).

Acceptance: Report sample sizes, retrieval/coverage metrics, uncertainty, calls/cost and known failures; keep downstream answer claims separate.

Verification: Reproduce one evaluation run and manually review unsupported acceptance and abstention examples.

Learning exercise: Explain leakage and the limits of a small benchmark.

Expected areas: `evaluation/reports/V6/`, `benchmark manifests`.

### V6-03: Concurrency and resource testing

Dependency: V6-02. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Measure cold/warm imports, bounded ingestion, contention, cancellation and sustained retrieval on declared hardware/concurrency.

Acceptance: Resource use stays within frozen targets or readiness fails; overload produces bounded backpressure rather than unbounded growth.

Verification: Increase load in small steps and stop at local pressure; run broader supported-platform tests in CI where available.

Learning exercise: Explain p50/p95, cold starts and why throughput depends on concurrency.

Expected areas: `Performance harness`, `resource reports`.

### Checkpoint V6-C1

After tasks through V6-03, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V6-04: Security and failure audit

Dependency: V6-03. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Review every implemented boundary using the edge-case inventory: filters, source spans, provider outputs, logs, deletion and model assets.

Acceptance: All required invariant cases pass; secrets/assets are excluded from packages and unsupported modes are documented.

Verification: Run adversarial fixtures and inspect built artifacts; record residual limitations without claiming universal safety.

Learning exercise: Explain the difference between a security invariant and a quality estimate.

Expected areas: `Boundary tests`, `artifact audit`, `V6 report`.

4 November 2026 reassessment: V6-04R adds separate native consumer/error,
release-hold and production-guide slices under
[CSR-r1](../../contracts/CONSUMER_SECURITY_REVIEW.md). Corrections after a frozen
candidate require new exact-artifact acceptance; historical CI receipts do not
cover changed products. CSO helper coverage and deployed-target checks remain
separate from local engineering results. See the
[reassessment](../../evaluation/reports/V6/V6-04R-consumer-security.md).

V6-04R-CLOSE: retained scanner findings and later reachable-history leads have
inspected dispositions; installed-security test selection gaps are fixed.
[Local acceptance](../../evaluation/reports/V6/V6-04R-closure.md) passed for the
replacement products. [Replacement candidate CI](../../evaluation/reports/V6/V6-08C-CI2.md)
also passed. Qualified CSO coverage remains partial; release-packet review,
registry and production gates remain separate.

### V6-05: Developer usability trial

Dependency: V6-04. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Have a developer unfamiliar with the code complete installation, ingestion, retrieval and partial-result handling from docs; if unavailable, record the limitation. Use the BRD measures within this trial: compare an explicit baseline on the same corpus and required behavior, distinguish missing evidence from provider failure, and include one bounded update/configuration task.

Acceptance: Record actual time, errors, help required, failed attempts and confusing steps against the predeclared criteria. Record reasons to continue or abandon the integration as exploratory feedback. Fix documentation/API problems without inventing adoption evidence; a missing participant or baseline leaves comparative effort claims unvalidated.

Verification: Repeat failed steps from a fresh environment and capture a short task report.

Learning exercise: Explain the public API without referring to internal implementation details.

Expected areas: `Quickstarts`, `usability report`, `regression fixtures`.

### V6-06: Release artifacts and CI

Dependency: V6-05. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Check package names, license, dependency/model notices and provenance; build wheel/sdist and npm tarballs with supported CI checks.

Acceptance: Artifacts install on the supported matrix and their dependency/content audits pass; local and CI evidence are distinguished.

Verification: Install the exact candidate artifacts, run examples and verify hashes and release metadata.

Learning exercise: Explain artifact identity versus a source checkout.

Expected areas: `Release workflow`, `package metadata`, `artifact smoke tests`.

### Checkpoint V6-C2

After tasks through V6-06, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

### V6-07: Migration and rollback rehearsal

Dependency: V6-06. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Document and test explicit schema/profile upgrades, package downgrade compatibility and backup/restore on disposable data.

Acceptance: No import performs migrations; failed upgrades preserve recoverability; rollback never restores revoked access.

Verification: Rehearse upgrade, interrupted migration and documented recovery from a test backup.

3 November 2026 amendment: V6-07F1 addresses the natively confirmed populated
0001-to-0002 lexical alias incompatibility through a separate explicit LCR-r1
operator repair. Applied migration/package bytes and histories are preserved;
the unmodified upgrade is recorded as rejected. Check/apply, writer exclusion,
interruption, exact source/vector/security preservation and current/historical
runtime compatibility passed under [MRR-r2](../../contracts/RECOVERY_REHEARSAL_V6.md).
See [the scoped acceptance](../../evaluation/reports/V6/V6-07-recovery.md). This
maintenance step has separate local evidence; it is not covered by the earlier
paid candidate CI and does not authorize publication.

Learning exercise: Explain application rollback versus database rollback.

Expected areas: `Migration guide`, `operations fixtures`, `recovery report`.

### V6-08: Publication and post-release smoke

Dependency: V6-07. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Prepare a changelog and evidence bundle, obtain publication authorization if not already given, then publish through the configured workflow.

Implementation slices: A/B prepare and verify separate local RC1 products and
disclosure/release notes under [PPR-r1](../../contracts/PUBLICATION_PREPARATION_V6.md).
C establishes verified registry permissions, secure bootstrap and a reviewed
publication workflow/product transport. D obtains the specific authorization,
publishes and verifies clean registry downloads/install/source access. Preparation
does not remove tracked npm guards or complete the parent publication task.

Acceptance: Local readiness and publication are separate tracker states; published versions install and pass a source-linked smoke query.

Verification: Before publication inspect exact artifacts; afterward fetch published packages into clean environments and verify version/hash policy.

Learning exercise: Explain why a published broken artifact needs a new corrective release.

Expected areas: `Release notes`, `publication workflow`, `release evidence`.

### V6-09: Maintenance handoff

Dependency: V6-08. Target: one focused slice; split cross-runtime work into explicit child tasks if needed.

Build: Document issue reproduction, support scope, regression handling, dependency updates and model-policy re-evaluation triggers.

Acceptance: The project has a clear next-maintenance workflow; optional research remains outside completed release claims.

Verification: Walk through a simulated bug report and identify its test, patch, release and communication steps.

Learning exercise: Explain what makes a library maintainable after its first release.

Expected areas: `CONTRIBUTING.md`, `support guide`, `maintenance checklist`.

### Checkpoint V6-C3

After tasks through V6-09, run focused regression tests and the shared fixtures touched by this group. Demonstrate the current behavior, inspect one failure case, and record resource observations. Discuss one learning takeaway. Fix failures before adding the next capability. Run the complete version acceptance suite at the final checkpoint.

## Version exit

Demonstrate: Cleanly installable supported packages with reproducible evidence, migration guidance and a maintenance path. Record results for owned edge cases and any unresolved operational/live-provider checks. Build the stated local artifact when applicable. A planned feature, fake-provider pass or unrun hosted CI job must not be reported as production evidence.

If blocked, reduce the failing case to one document/request and preserve the current working slice. Keep required scope checks, citation integrity and honest statuses. Escalate only the missing decision or external dependency; do not redesign the project to bypass it.
