# V6-09 maintenance handoff acceptance

4 November 2026. COMPLETE for the maintenance handoff; C3 verification and formal
V6 exit remain separate. [V6-08 registry acceptance](V6-08D-publication.md)
passed before this task. The [machine record](V6-09-maintenance.json) captures
the actual commands, simulation and limits.

[Contributing](../../../CONTRIBUTING.md), the
[bug form](../../../.github/ISSUE_TEMPLATE/bug_report.yml),
[support scope](../../../docs/support.md) and
[maintenance checklist](../../../docs/maintenance.md) now define synthetic issue
reproduction, safe diagnostics, support boundaries, invariant regressions,
Python/Node parity, dependency updates, migration/version decisions, provider/
model/tokenizer/prompt/pricing/data-policy triggers and corrective release
communication. The checklist assigns a maintainer and next action, and records
not-reproduced reports without inventing a patch or delivery promise.

## Actual simulated report walkthrough

The report alleges an unknown reranker transport exception leaks its private
message with fallback enabled. This is a hypothetical report, not an observed
current vulnerability. The existing fake-transport regression was exercised in
both runtimes:

```sh
uv run --project packages/python --frozen --no-sync pytest packages/python/tests/test_reranking.py::test_unknown_transport_error_is_redacted_and_fatal -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 --test-name-pattern='unknown transport error is redacted and fatal' packages/typescript/tests/reranking.test.mjs
```

Python passed two parametrizations in 0.08 seconds; Node passed two, with zero
failures. Both fallback settings retained a canonical operational error, one
transport dispatch and no synthetic private marker or exception chain. The
triage disposition is not reproduced in this regression. A different reachable
path is not disproved; request a smaller synthetic reproducer before patching.

No product code was changed to manufacture a bug. For a confirmed regression,
the documented path adds a failing case, makes a narrow contract-preserving fix,
checks both runtimes/affected profiles, and prepares a separately authorized
corrective version with exact artifact/registry acceptance. Communication names
actual affected versions, workaround, correction and remaining limits; it never
claims a fix shipped before registry verification.

## Integration and scope

Both Sol peers performed substantive document work and coordinated directly;
guidance assembled before root integration. The interruption left their drafts
intact; recovered peers finished the same nonoverlapping paths and stopped
writing before root review. Root checked the actual commands and source
assertions, parsed the issue-form YAML and inspected its schema against
[GitHub's official form documentation](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-githubs-form-schema).
Required-field enforcement is documented for public repositories; private
collaborators and maintainers review completeness/redaction manually. A live
GitHub form render is not claimed.

Root performed prose and link checks before commit. One local test process was
used; no service, provider call, model download, package upload or paid CI ran for
this task. Resource observations before C3 were 15GiB available disk and
62 percent free system memory, not a workload benchmark. Existing private user
edits and immutable release products were preserved.

The repository stays private. These guides provide a maintenance path for
collaborators with access; they do not establish a public support inbox,
response SLA or independent adoption evidence. C3 must still run the complete
reviewed-source acceptance suite. Formal exit also requires public limitations
and benchmark evidence, deferred to the user's file/publication decision.

Learning example: an unknown provider failure is an operational error even when
fallback is enabled; it cannot become an empty successful search. Exercise:
identify one profile change that requires reindexing and one provider-policy
change that requires reviewing disclosure. Practice remains unassessed.
