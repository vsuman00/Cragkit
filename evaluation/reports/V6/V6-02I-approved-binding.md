# V6-02I approved recovery binding

Status: COMPLETE for I1 human approval/sealing, I2 known-profile binding and I3
parent label-loading integration. Candidate/source/runtime refreeze and genuine
recovery evaluation remain OPEN; full V6 is incomplete.

For example, replacing a manifest and the seal beside it cannot approve a new
packet: the chosen seal must still match its independently pinned source digest.
The original and recovery profiles retain separate pins.

## Actual approval and immutable inputs

The project user replied "I approved" to the concrete six-question/eight-facet
review request on 3 November 2026. Root verified all eight pre-approval review
file hashes before changing metadata. The question list and all five source
revisions are unchanged. Only the dataset review state/reviewer and guide status
were updated; no support, filter, answerability or facet judgment was altered.

The [approval record](../../review/retrieval-recovery/approval.json) preserves the
actual reply, scope, reviewer and pre-approval review revision. The separate
[nine-file seal](../../review/retrieval-recovery/seal.json) has SHA256
`46a7e1bba338ff205d6d5e49f45a61db9cca3f0c8acb81b9c70d51870fd5e195`.
Its approved label file has SHA256
`33453432a95d3e48b501ac007053e190007bbb480684625c770d41c1d1dd6da7`.
The original seal remains
`210ddce9237847d271db35dbff1d7c74a1ba1f30323a3f4119f939a604a83f81`.
Agent author/reviewer/root and human exposure are disclosed; this is still a
small, pre-exposed synthetic packet rather than a blind external benchmark.

All nine sealed file hashes passed. The existing corpus checker passed
`require_human_review=True`: five source revisions, six questions, eight facets
and seven support references. The temporary empty development dataset was only
a synthetic checker-layout adapter, removed after validation and never proposed
as execution input. Human judgment came from the actual user, not that checker.

## Implementation and verification

The [EPR-r1 contract](../../../contracts/EVALUATION_PACKET_REVISIONS_V6.md)
assigns root the pure profile registry, shared approval data and parent integration.
Sol binder owned its binder/test pair; Sol checker owned its checker/test pair
and assembled. Both resolved shared interfaces directly and returned ownership
before root combined tests. Root inspected their source and reports.

Only known `original-r1` and `recovery-r1` identities are accepted. Omitting the
optional revision preserves original configuration behavior. Development remains
the original nine-document/24-question approved packet. Recovery adds two bounded
manifest/seal preregistration paths to the original six. Neither held-out question
file is opened by preregistration checking. The binder retains source verification
before held-out decoding and emits a label-free native runtime projection.

An issued immutable binding privately records its source root, selected label
path/digest and profile. The parent accepts only the exact native binding type
and calls `reviewed_questions(root)` after execution for independent scoring.
Forged/duck-typed objects, wrong roots, changed labels and unapproved state fail.
Returned copies cannot mutate the private binding. Provenance adds `packet_revision`
and `labels_path`; this is evaluation metadata, not a public library API change.

Actual commands, run serially from the project root:

```sh
uv run --project packages/python --frozen --no-sync python -B -m pytest tools/tests/test_evaluation_packet.py tools/tests/test_check_release_readiness.py tools/tests/test_run_release_evaluation.py tools/tests/test_evaluation_runtime.py -q
uv run --project packages/python --frozen --no-sync python -B -m pytest packages/python/tests tools/tests -q
```

**179 focused tests passed**; **3,780 Python/tool tests passed**, with four existing
intentional Pydantic warnings. Synthetic cases cover both profiles, unchanged
original development, unknown/malformed revisions, replaced/pending/mismatched
seals, swapped paths, unsafe/oversized inputs, source-before-label ordering,
label tampering, copy mutation, forgeries and wrong-root scoring access.
No real recovery labels were used in routine runtime tests. The synthetic
original-profile fixture was made explicit before later candidate selection;
its 46 packet tests also passed in isolation.

Root also constructed an unactivated recovery configuration and ran the actual
checker with an explicit held-out-read guard. It accepted eight preregistration
inputs and the complete requirement/edge-case index without either held-out
question read. The [verification record](V6-02I-approved-verification.json)
separates this offline acceptance from a fresh runtime and live quality.

## Remaining execution boundary

The active candidate was not rewritten during implementation. Original failed
observations, unsealed recordings and the durable admission remain unchanged.
Next: preserve the original candidate as history, select the new reviewed profile
with unchanged targets/call/spend/resource limits, refreeze source and prepare a
fresh isolated execution identity. Do not resume the original admission or infer
live/replay acceptance from these unit checks. Credential configuration and the
explicit bounded live decision remain separate; this approval records labels.

No core package, migration, lockfile, model profile or scoring metric changed.
Resource observation: 25.2 GiB free disk and 52 percent free system memory.
No service, install, provider call or model download was needed. Development
checks used one test process at a time. Learning practice remains unassessed.
Optional exercise: explain why an editable adjacent seal is insufficient without
an independent approval pin.
