# Maintenance checklist

For example, a regression test can inject a synthetic transport exception and
assert that no private exception text survives. Fixing that boundary must retain
its error classification and usage accounting in both runtimes.

Use this checklist with [support](support.md), [contribution guidance](../CONTRIBUTING.md)
and the governing [architecture](architecture/ARCHITECTURE.md). The [current roadmap](roadmap.md) owns completion state. V6-09 handoff and checkpoint C3 do not waive the pending formal
version-exit and public benchmark-disclosure acceptance.

## Reproduce and classify

1. Capture a safe minimal report: exact installed version/origin, runtime,
   optional backend/profile, synthetic input, expected versus actual behavior,
   stable errors, evidence/execution states and last known working version.
2. Reproduce on the declared supported configuration with fake providers first.
   Keep the original failing artifact and command. Run one test process and only
   required services; live-provider or model evaluation needs its explicit budget
   and disclosure decision. A failed setup is not a failed product assertion.
3. Identify the contract and owned edge case. Authorization, required filters,
   exact source spans/digests, cancellation/deadlines, resource limits, privacy
   and honest coverage/execution are release gates. Any required invariant case
   failing blocks the affected release; a better average score cannot offset it.

## Patch and verify

1. Add a regression for the smallest failing behavior before patching. Keep
   meaningful shared deterministic fixtures and native Python/TypeScript parity;
   schemas alone do not establish behavioral parity. Test denied/failure paths,
   not only successful retrieval. Preserve caller-owned configuration and dirty
   work, existing contract guards and immutable source revisions.
2. Run the focused checks in [development](development.md), then the relevant
   typing, shared conformance, optional integration and installed-artifact checks.
   Use one language integration suite at a time. Record actual commands, inputs,
   versions, results and limits; distinguish local/fake, native, live, CI and
   registry evidence. Stop task-owned services and record resource observations.
3. Assess the full impact before promotion: core changes can affect adapters,
   filters must hold in every branch, and packed evidence needs reassessment.
   Record unresolved issues and unsupported modes rather than weakening checks.

Record a maintainer and next action for each accepted report in the roadmap handoff.
Keep the reproduction command, regression path, patch review, release decision
and communication status together. If the existing regression passes, record
"not reproduced" and ask for a smaller safe failing example; do not invent a
patch or mark the report fixed. A different failing path may still exist.

## Release and communicate

Review semantic-version impact before changing manifests: distinguish compatible
fixes, compatible additions and breaking public API changes. Record the chosen
version and compatibility decision with the [release guide](releasing.md).
Distinguish prerelease from stable and public API compatibility from
database/profile compatibility. A model, embedding
identity or tokenizer change may require explicit reindexing or changed context
budgets; document migration and rollback restrictions before deployment.
Migrations remain explicit operator actions, with preserved checksums/history;
rollback must not restore revoked access.

For a published regression, prepare a reviewed corrective version under its
specific authorized scope; never overwrite a released artifact or reuse a
published name/version. Follow [publication](publication.md) for exact products,
permission/admission, missing-only recovery, registry download comparison and
clean installed smoke. Yanks, deprecation, unpublish and tag changes need their
specific scope. Keep repository visibility and file/archive decisions separate.

Update release notes and the issue with affected versions/profiles, impact,
workaround, fix version, migration steps, tests and remaining limits. For a
security problem, coordinate the safe disclosure path before sharing details.
Do not publish private logs or imply an independent audit, universal safety,
measured user adoption or production acceptance without that evidence.

## Dependency and policy review triggers

| Trigger | Required review before promotion |
| --- | --- |
| Python/Node, Pydantic/Zod, driver, framework or transport update | Verify APIs and lock changes; run affected typing, parity, failure, optional-profile and installed-package checks. Core import must remain free of optional I/O and model downloads. |
| PostgreSQL/pgvector/Qdrant or schema/profile change | Check capabilities, filters, publication/recovery, migration and revoked-access behavior on the declared backend; record unsupported upgrades. |
| Provider/model/version, embedding dimensions or reranker change | Recheck output validation, deadlines, usage/cost, redaction and profile identity; invalidate stale compatibility or quality evidence and assess reindexing. |
| Tokenizer, renderer, wrapper, prompt/planner policy or assessment threshold change | Recheck actual serialized token ceilings and deterministic fixtures; recalibrate coverage and conflict behavior on an explicitly reviewed evaluation packet. Never carry sufficiency claims forward automatically. |
| Price, retention, training-use, region, subprocessor or data-disclosure policy change | Reassess caller consent/configuration, disclosure, budget and telemetry before further affected provider use; no silent provider switch or broadened data release. |
| Vulnerability notice or unexpected package contents/provenance | Determine affected versions, inspect exact artifacts/dependencies, add a bounded regression and plan an authorized corrective release; a clean scanner does not prove universal safety. |

Keep evaluation source/tape, reviewer exposure, dataset rights and contamination
records intact. New live quality claims need separate reviewed evidence; replay
or fake-provider success cannot replace it. Record who owns follow-up and the
next smallest testable action in the roadmap handoff. Learning exercise: identify one
change that requires reindexing and one that requires a privacy-policy review.
