# V5-04H: Revocation between stage and publication

State: COMPLETE for fault ID `revocation_between_stages` only. V5-04H and V5 remain open.

For example, a writer may stage a successor while a reader is authorized. If that reader is revoked before publication, the staged intent cannot use its old authorization to become active.

The G2c native public-security trace stages a fresh intent under auth-2 after the existing current-security convergence. Auth-3 then revokes the original reader in a separate authority transaction. The commit makes no Qdrant request. Publishing the staged intent with auth-2 raises `UnauthorizedScope`; trying it with the current auth-3 reader records a durable denied intent. Neither attempt sends another HTTP request or point PUT. The authoritative document and base active generation remain unchanged. A retained source handle releases zero bytes for both provider and final purposes after revocation. Fresh revoked-reader fetches remain unavailable, while the current reader can still fetch the prior published source. The later lost-acknowledgment and tombstone cases remain in the trace.

Root inspected the disjoint Python and TypeScript consumer changes and ran:

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_qdrant_security_verification_native.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_security_verification.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --with-security-guard --with-purge-profile --public-security --runtime all --artifacts-dir artifacts/V5/V5-04H/revocation-between-stages-both-05
node --check tools/check_typescript_qdrant_public_security.mjs
uv run --project packages/python --frozen --no-sync python -m py_compile tools/qdrant_public_security_cases.py
python3 tools/check_seal.py
```

Ten focused protocol tests passed. The native parent passed ten checks in each runtime; both returned semantic witness SHA-256 `44428a6e3d9f975fab3563110cb86c0efb634478938ad94c075b71a53361f99a`, with verified task-owned cleanup. The ignored result is `artifacts/V5/V5-04H/revocation-between-stages-both-05/results.json`. Syntax, compilation and all 16 sealed inputs passed. Full 3,104-test Python and 1,557-test Node regressions passed in H-S22 and were not rerun for this fixture-only slice.

The first combined run failed in the TypeScript consumer because its source store allows one open request. The fixture kept a retained handle open while starting fresh requests. A phase-specific native diagnostic identified that operation; both consumers now finish the two denied retained releases and close the handle before fresh reads. Temporary diagnostics were removed. No product module, SQL/schema, migration, lockfile, shared sealed fixture, or user-owned file changed. This is local native single-node evidence, not hosted CI, live-model quality or production readiness. Sol peers coordinated the matching source lifecycle and witness directly; Python assembled and root ran final acceptance. Learning practice is unassessed: explain why staging does not grant permission to publish after a later revocation.
