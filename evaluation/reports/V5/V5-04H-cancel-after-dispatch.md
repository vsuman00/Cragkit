# V5-04H: Cancellation after a dispatched write

State: COMPLETE for frozen fault ID `cancellation_after_dispatch` only. V5-04H and V5 remain open.

For example, Qdrant may finish a point PUT just as the caller cancels. The manager must keep the original intent and old active generation, and the durable journal must represent the uncertain acknowledgment. A retry cannot assume the physical write was undone.

## Native observation

Both public-manager consumers published a base generation, staged a distinct successor, and cancelled immediately after Qdrant completed the successor's real point PUT, before the completion acknowledgment reached the manager. Each observed native cancellation, one `unknown` dispatch without a completion digest, an unchanged active pointer, preserved immutable stage data, and exact physical readback of the completed successor points. A new manager refused to resend or replace that intent. The two public snapshot hashes matched without normalized fields. The fixture used synthetic points and no model or paid provider.

The first Python run exposed a fixture control captured before successor staging. A named check established that publication admission legitimately transfers the document owner; the control now compares the immutable base graph and pointer while leaving owner transfer visible in the successor graph. Node then exposed a real runtime difference: its conservative `mark_unknown` call inherited the cancelled signal and left the journal `dispatched`. The Node manager now uses a separate two-second cleanup deadline for that journal update. If cleanup fails, the durable `dispatched` record still blocks a successor. No write or authorization boundary is relaxed.

## Verification

Root inspected both consumer diffs and ran these serial checks:

```sh
npm --prefix packages/typescript run build
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_publication_manager_native.py -q
node --test --test-concurrency=1 packages/typescript/tests/qdrant-publication.test.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --scenario cancel-after-dispatch --runtime all --artifacts-dir artifacts/V5/V5-04H/cancel-after-dispatch-both-07
python3 tools/check_seal.py
```

The focused tests passed: 11 Python protocol tests and 25 Node publication regressions. The native parent passed one exact case in each runtime, matched the SHA-256 public snapshots, and reported `cleanup_verified: true`. Its ignored result is `artifacts/V5/V5-04H/cancel-after-dispatch-both-07/results.json`. The earlier failed runs remain separate diagnostic artifacts and do not count as acceptance. No task-owned service remained. This is local native evidence, not hosted CI, live-model quality or production readiness.

Sol peers implemented separate Python and Node consumers and coordinated the scenario spelling, pending-state checks and snapshot format directly. Python assembled their files. Root owned the parent protocol guard, the narrow Node cleanup correction, native verification, report and tracker. The original QW-r1 fixture, schema/migrations, sealed inputs, optional package locks and user-owned edits were not changed. Learning practice is unassessed: explain why a completed point can coexist with an `unknown` dispatch until reconciliation.
