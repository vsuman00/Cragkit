# V5-04H: Managed recovery and retired credential

State: COMPLETE for frozen fault ID `managed_recovery_old_key_rejected` only. V5-04H and full V5 remain open.

For example, after a completed point write loses its acknowledgment, the old credential might still be held by a caller. Recovery must block ordinary admission in SQL, stop the owned Qdrant process, rotate its key and verify the old key fails before settling that uncertain write.

## Current native evidence

Root inspected the existing E1 and E2b consumers and reran both native parents. E2b first performs real point writes for two documents and withholds their acknowledgments, leaving two durable `unknown` journal rows. The recovery callback observes the committed instance block before physical fencing. It stops and restarts the owned Qdrant process on the same storage identity, then sends an actual mutation with the captured old credential and requires HTTP 401. A fresh current credential and readback permit settlement of only the authorized document; the other unknown row keeps SQL and native admission closed. After the second document is authorized and settled, a private committed handoff reopens ordinary reads at the current epoch. E1 independently checks old versus new process identity, unchanged storage/controller identity, exact full-point readback with the new recovery key and refusal to issue ordinary worker authority from recovery proof alone.

The frozen fixture uses illustrative epochs 7 and 8. These native cases start at 1 and fence to 2; they assert the same single-step epoch relationship and preserve the existing recovery identity through repeated physical fences. This is the supported surviving-controller profile. It does not prove supervisor adoption, coordinator process death or a general hosted recovery service.

## Verification

Root ran the commands serially against pinned Qdrant 1.20.0 and disposable PostgreSQL 17:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_supervisor.py --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/managed-recovery-e1-both-01
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_recovery.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/managed-recovery-e2b-both-01
```

E1 returned `ok: true`, nine checks per runtime and verified cleanup. E2b returned `ok: true`, eight restricted SQL checks, 21 recovery checks per runtime and verified cleanup. Ordered labels and proof scopes are recorded in the ignored `results.json` files under those directories. The E1-only proof scope is `process_credentials_profiles_only`; the E2b scope is `durable_recovery_settlement_only`. The combined scenario supports this single H mapping. No provider, hosted database, model download, schema or product code changed.

Seventeen exact H IDs now have accepted native evidence. The other frozen rows, killed-coordinator recovery and final V5 gates remain open. Learning practice remains unassessed: explain why a completed write with a lost reply cannot be cleared by a new-key health check alone.
