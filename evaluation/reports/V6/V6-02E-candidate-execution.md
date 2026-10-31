# Candidate execution and scoring checkpoint

V6-02E offline implementation checkpoint: PASS. Actual clean-candidate runtime
preparation is IMPLEMENTED_UNVALIDATED. Original held-out quality and V6 release
acceptance remain open.

For example, a worker that omits the corrective row must fail the entire stage
with all five mode denominators. It cannot disappear from the benchmark. The
parent now retains the malformed raw wire separately and records explicit
operational failures for that stage.

## Implementation and ownership

The [ECR-r1 contract](../../../contracts/EVALUATION_CANDIDATE_V6.md) binds the
candidate source, installed runtimes/dependencies, tokenizer and a fresh native
TypeScript compilation. The runtime helper refuses checkout bytecode because
Python `-B` disables writes but can still read an existing cache. It never deletes
user caches. Preparation and verification have explicit local-only CLI commands.

Sol runtime implemented the runtime helper/tests; Sol scoring implemented the
independent scorer/tests and assembled their work. They resolved dependencies
directly. Root integrated the audit callback, pricing gate, native parent,
contracts, tests and final acceptance. The final review added label-free
observation validation after finding the missing-mode denominator failure.

The parent runs five native modes, retains the actual rerank-input order for a
same-shortlist comparison, replays healthy sealed live recordings in both
runtimes, verifies full result parity and recounts the actual serialized context.
Malformed workers, unused replay entries, cleanup failures and incomplete stages
remain operational failures with complete denominators. Reviewed support labels
enter independent scoring only after execution.

Live execution requires an explicit flag, both privately configured providers,
a current dated price review, matching clean runtime identity and a durable
single-use admission. No automatic provider retry is implemented. Admission
attempts, completed responses, replay calls and uncertain physical HTTP counts
are reported separately. Account billing is not inferred.

## Actual verification

The final focused helper/parent/hook/pricing suite passed 161 tests. The complete
Python/tool suite then passed 3,598 tests, with four intentional malformed-model
serializer warnings. The unchanged native Node evaluation/replay suites passed
65 tests in the immediately preceding current-checkout verification.

The final real PostgreSQL17.11/pgvector0.8.0 development rehearsal used nine
approved document revisions and 24 questions. Python and Node each returned
120 ordered mode rows and nine receipts. Normalized wire parity and every
same-shortlist comparison passed. There were zero observed identity,
authorization, fidelity, invariant or operational failures in this rehearsal.
Owned database/pool cleanup passed. Fake profiles made zero HTTP calls; the
parent explicitly returned `live_quality_accepted: false`.

[Structured verification](V6-02E-candidate-verification.json) records actual
commands, changed-source digests, artifact/log hashes, mode denominators and
synthetic paired deltas. Raw results are under
`artifacts/V6/V6-02E/mechanics-03/`; serial logs are in
`artifacts/V6/V6-02E/final-checks/`. Fake deltas validate the harness and cannot
be used as model-quality measurements. The independent frozen benchmark module,
reviewed labels, quality targets and seal bytes were not changed.

## Remaining acceptance

The release manifest declares RC1 while package metadata still declares
`0.0.0`. The peer review recommends a recorded RC metadata and engine-identity
prerequisite before opening the original held-out packet. Retaining the old
engine number by inventing a new protocol meaning is not an accepted shortcut.
V6-06 still owns exact artifact/CI/license/install acceptance; publication remains
V6-08. A source/runtime receipt cannot be relabelled after metadata changes.

After the prerequisite, prepare a fresh isolated checkout with the frozen
preinstalled dependencies and pinned tokenizer, then run the following from that
checkout. These actual preparation commands have not yet passed on a real clean
candidate:

```sh
uv run --project packages/python --frozen --no-sync python -B tools/evaluation_runtime.py prepare --output artifacts/V6/runtime-identity
uv run --project packages/python --frozen --no-sync python -B tools/evaluation_runtime.py verify --receipt artifacts/V6/runtime-identity/runtime.json
```

Complete secure OpenAI setup before paid execution. The user already selected
the hosted embedding profile and delegated the new-key recommendation; no key
was read or written in this checkpoint. The once-admission and price gates must
pass before the separately recorded genuine run. No model installation, original
held-out interpretation, live inference, hosted write/CI or publication occurred.
Local verification used macOS arm64, Python3.14.6 and Node26.5.0, with one test or
native process at a time. Existing user edits and reports remain protected.

Optional exercise: remove a mode from a synthetic worker result and explain why
it becomes five operational failures rather than one missing benchmark row.
Learning practice remains unassessed.
