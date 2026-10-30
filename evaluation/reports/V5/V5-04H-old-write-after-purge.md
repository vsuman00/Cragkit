# V5-04H: Delayed old write after the first absence read

State: COMPLETE for fault ID `old_write_after_initial_purge` only. V5-04H and V5 remain open.

For example, an empty Qdrant result does not prove deletion is stable while an older admitted write can still arrive. The purge must wait for fencing and check absence again.

Both native consumers publish a target document and a separate outside document with a newer active generation. They pause a genuine managed target upsert before its HTTP send, commit the target tombstone on the authority connection, and bind a durable incomplete purge intent. Managed owner admission and the busy manager refuse purge while the old request is held; point claims remain and retained/fresh target source release is denied. The fault harness then makes a real strongly ordered exact-ID deletion and a scoped empty scroll. **That first deletion/read is test injection, not a completed managed purge.** Releasing the same held request makes its two points physically reappear after the first empty read. Native recovery fences the old transport, and the managed purge performs its own fresh exact scoped absence verification before completion. The outside document's four physical points, active newer generation and source remain available.

Root inspected the nonoverlapping Python and TypeScript consumers, the parent storage audit, and ran:

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_qdrant_purge_native.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_purge.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/old-write-after-purge-both-03
node --check tools/check_typescript_qdrant_purge.mjs
uv run --project packages/python --frozen --no-sync python -m py_compile tools/qdrant_purge_cases.py tools/check_qdrant_purge.py
python3 tools/check_seal.py
```

Seven focused protocol tests passed. The combined native parent passed 52 checks: eleven purge scenarios, five fault checks and ten independent storage checks per runtime. Both returned semantic witness SHA-256 `7e2b06be9835776bfe9569e2b17f84f7584a598509e6dc8bd9e33485260aa37e`, with verified task-owned cleanup. The ignored result is `artifacts/V5/V5-04H/old-write-after-purge-both-03/results.json`. Syntax, compilation and all 16 sealed inputs passed. Full Python and Node regressions last passed at H-S22 and were not rerun for this fixture/harness slice.

The first combined run passed Python but exposed a Node test-harness type error: its direct HTTP request passed a number array to `end()`. The peer converted the bounded request body to a `Buffer`; a native Node-only run and the combined rerun then passed. Astra reviewed the frozen matrix and confirmed that a clearly labeled harness first deletion can establish this race; it did not supply execution evidence. No product module, SQL/schema, migration, lockfile, shared sealed fixture or user-owned file changed. This is local single-node evidence, not hosted CI, live-model quality, cluster behavior or production readiness. Sol peers coordinated the interleaving and witness directly; Python assembled and root ran acceptance. Learning practice remains unassessed: explain why an early empty read cannot reclaim point claims while an old write is unresolved.
