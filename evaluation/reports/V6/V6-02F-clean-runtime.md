# Clean candidate execution identity

V6-02F4 and the actual V6-02E runtime preparation gate: PASS. Genuine held-out
model evaluation and the remaining V6 release gates are still open.

For example, a byte-identical source checkout with stale Node output must fail
preparation. This run compiled checked source in a fresh temporary directory,
compared every emitted file, and verified the export only from that scratch build.

## Actual candidate and preparation

A fresh detached checkout at `9c227411ce86e1e79372f2bf6a7bf3a8d8aec00e` uses frozen
source `16f70cfc2d0400706056eb24745cccd40c1403e3`, package tree
`05fdc769488f496ef71ec6b988383fa8d1f18b1c`. The configuration changed only source
identities before original held-out access. Model choices, limits, quality and
resource targets, reviewed inputs and metric/seal digests were preserved.

Python and Node dependencies were explicitly installed offline from frozen locks
into the new checkout; the pinned tokenizer was copied and hash-verified. Node
was built before preparation. No original user changes or caches were removed.
The tools-only npm probe correction then fast-forwarded the same owned checkout;
its package tree and frozen installed dependencies were unchanged.

Actual ECR `prepare` and independent `verify` both passed. The receipt binds
9,411 inventory files, 100 emitted Node files, tokenizer, source/configuration
and Python3.14.6/Node26.5.0/npm11.17.0/TypeScript7.0.2. Its directory is owner-only
`0700`; the receipt is `0600`. The common verified execution identity is:

```text
51f3525a40076eccec0fca739675eadb82b6335c27a9ccde4139c884398fc8a4
```

The first attempt failed safely at the npm version probe, before any receipt or
held-out access. Root validated npm's double-config error, introduced distinct
empty private config files and cleanup, then reran from the corrected frozen
source. The focused runtime/parent suite passed 85 tests and the final full
Python/tool suite passed 3,621 tests with four deliberate serializer warnings.

## Native rehearsal and evidence

The actual parent ran with the prepared receipt in that isolated checkout. It
reverified identity before and after both native stages. Python and Node each
returned 120 development mode rows and nine receipts. All 240 result wires use
engine `1.0.0-rc.1`. Exact normalized parity, actual same-shortlist comparisons,
metric harness targets and owned cleanup passed. Source status remained clean.
No live HTTP or original held-out interpretation occurred; fake metric results
are not genuine model-quality evidence.

The development packet binder reports its own source/compiled flags false,
since it does not perform ECR verification. The parent separately records the
verified runtime identity above. These are distinct proof scopes, not a reason
to relabel packet provenance.

[Structured verification](V6-02F-clean-verification.json) records actual commands,
receipt/configuration identities, permissions, runtime versions and hashes of
all retained evidence. Raw installation/failed-probe logs are under
`artifacts/V6/V6-02F/clean-checks/`, final checks under `clean-verification/`, and
the prepared checkout is retained at `artifacts/V6/candidate-rc1/` for the next
explicit live comparison. Task-owned database and subprocess resources closed.

This closes clean runtime preparation, not artifact publication or V6. Secure
OpenAI target/destination confirmation remains necessary before creating a key;
the existing Cohere file passed only local presence/format/permission checks.
No provider credential validation or model call is inferred from those checks.
After configuration, the genuine run still requires the dated official-price
review, once-admission and frozen limits, followed by healthy complete native
replay and independent held-out scoring. All later V6 gates remain required.

Optional exercise: explain why a clean source status, matching compiled files
and an explicit dependency installation prove different parts of this identity.
Learning practice remains unassessed.
