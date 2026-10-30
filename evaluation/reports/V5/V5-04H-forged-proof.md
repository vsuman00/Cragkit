# V5-04H: Fabricated physical proof under durable uncertainty

State: COMPLETE for frozen fault ID `forged_quiescence_proof` only. V5-04H and full V5 remain open.

For example, a caller can claim `drained: true` and supply the current process ID. Those fields cannot prove that the caller owns the recovery capability. Unknown dispatches must stay unknown until the actual issuer-bound proof and scoped settlement complete.

## Native assertion

The E2b scenario first writes points for two scoped documents through real Qdrant HTTP, withholds the replies and confirms both dispatches are `unknown` in PostgreSQL. It then commits the instance recovery block and performs the actual owned-process/key fence. Before any settlement, each runtime sends two fabricated proof objects to the real `advance_owner` recovery boundary: a JSON copy of the physical binding and a separate object carrying the binding plus asserted quiescence and the observed new process ID. Both must raise `UnsupportedCapability`.

The consumers compare all 16 supervisor-readable journal metadata columns before and after each refusal, including state and request digest. They also confirm the SQL instance remains blocked and the supervisor still refuses ordinary admission. The genuine proof then advances the owner and the existing scoped settlement sequence continues. The restricted supervisor never reads journal request bytes for this check.

This proves refusal of copied and invented physical metadata while two actual unresolved journals exist. It does not prove lease expiry, supervisor adoption or coordinator process-death recovery.

## Verification

Root reviewed the two Sol-owned consumer diffs, checked the selected journal columns against the restricted role predicate, and ran:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_recovery_native.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_recovery.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/forged-proof-both-01
python3 tools/check_seal.py
```

Four focused protocol guards passed. The native parent returned `ok: true`, eight restricted SQL checks and 22 recovery checks per runtime, with `cleanup_verified: true`. Both ordered result lists include `fabricated_physical_proofs_cannot_authorize_recovery_or_clear_unknowns`; the ignored record is `artifacts/V5/V5-04H/forged-proof-both-01/results.json`. All 16 sealed evaluation inputs matched. No provider, hosted service, model download, product module, schema, migration, shared fixture or lockfile changed.

The two Sol peers edited separate Python and TypeScript consumers and resolved the permitted-column and check-order dependencies directly. Python assembled; root ran native checks serially. Disk headroom was 28 GiB and system memory free 54 percent after cleanup. Nineteen exact H IDs now have accepted native evidence; the remaining fault rows and V5 gates are open. Learning practice remains unassessed: explain why a process ID and a `drained` flag cannot replace an issuer-bound recovery proof.
