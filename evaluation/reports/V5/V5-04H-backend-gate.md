# V5-04H: Backend-wide gate with independent revocation

State: COMPLETE for frozen fault ID `backend_wide_recovery_gate` only. The rest of V5-04H and V5 remain open.

For example, two documents can have unresolved completed Qdrant writes when recovery closes mutation admission. A third document must not acquire a writer or Qdrant write capability during that window. Its grant revocation must still commit in the authoritative database.

## Native trace

The existing E2b recovery consumers now stage a third document under a distinct tenant and immutable identity before fencing. The first two documents each make a real completed point PUT whose acknowledgment is withheld from the writer, leaving two `unknown` dispatch journals. During the already observed durable `recovery_blocked` boundary, both runtimes try to acquire an owner for the third document and to issue a current-epoch Qdrant attempt. Both are refused with `ProviderUnavailable`. The third owner's snapshot and both original journals remain unchanged.

The third document then receives a separate, restricted `update_authorization` transaction while recovery remains blocked. It clears principal and grant IDs and advances authorization revision from `auth-1` to `auth-e2b-third-2` and mutation epoch from 1 to 2. A fresh authority snapshot sees the committed change; the old scope is rejected with `UnauthorizedScope`. Both unknown journals and the backend block remain in place. The original E2b sequence subsequently settles the two unknowns, reopens ordinary admission, and still observes the third document's new revision and epoch.

This trace tests authoritative revocation and the backend-wide write gate together on actual PostgreSQL/Qdrant. The E2b fixture has no source reader; its old-scope refusal is an authority check, not a final source-release assertion. Current-security/source-release coverage remains in G2c and final H integration.

## Verification

Root inspected both consumer diffs, ran four focused protocol tests, Python compile and Node syntax checks, then executed one serial native parent against disposable PostgreSQL 17 and pinned Qdrant 1.20 (SHA-256 `830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3`):

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_recovery_native.py -q
node --check tools/check_typescript_qdrant_recovery.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_recovery.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/backend-gate-both-01
python3 tools/check_seal.py
```

The parent passed 54 checks: eight restricted SQL checks and 23 recovery checks in each native runtime. Its result records `cleanup_verified: true`; all 16 sealed inputs matched. The ignored result file is `artifacts/V5/V5-04H/backend-gate-both-01/results.json`. No task-owned service remained. Disk headroom was 29 GiB and system memory free 34 percent after the run. These are local native observations, not hosted CI or production evidence.

Sol peers implemented Python and TypeScript recovery-consumer changes in separate files, resolved the third-document input and old-scope assertion directly, and Python assembled. Root owned the protocol guard, native run, report and tracker. No product module, schema, migration, shared sealed fixture, dependency, lockfile, provider or hosted service changed.

Twenty-eight exact H IDs now have accepted native evidence. A useful failure case to examine is a manager that blocks third-document writes but also blocks its grant revocation: that would leave stale access authoritative until recovery finishes. Learning practice is unassessed; explain why the revocation must have an independent short transaction.
