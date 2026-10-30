# V5-04H: Interrupted point deletion during purge

State: COMPLETE for fault ID `purge_interruption` only. V5-04H and V5 remain open.

For example, a Qdrant delete can complete while its client is cancelled before recording the response. The purge must stay pending until managed recovery resolves that uncertainty and verifies the scoped point set.

Both native consumers publish and tombstone a separate bounded document. They intercept a real strongly ordered point-delete response after the server reports completion, then cancel the client before the managed transport settles it. The first purge does not report completion. Its dispatch remains unsettled (`dispatched` or `unknown`, with no completion digest), the backend is recovery blocked, the tombstone denies source release, and the original point claims remain. A replacement owner cannot enter before recovery. The explicit retry fences the uncertain transport, completes managed purge and verifies a final empty Qdrant scroll under the document's exact scope. Source remains unavailable afterward. This tests client interruption after server completion; it does not claim the server stopped mid-delete. The earlier lost-delete-acknowledgment case remains distinct and still passes.

Root inspected the Python and TypeScript consumer edits and ran:

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_qdrant_purge_native.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_purge.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/purge-interruption-both-01
node --check tools/check_typescript_qdrant_purge.mjs
uv run --project packages/python --frozen --no-sync python -m py_compile tools/qdrant_purge_cases.py
python3 tools/check_seal.py
```

Seven focused protocol tests passed. The native parent passed 46 checks: ten purge scenarios, five fault checks and eight independent storage checks per runtime. Both produced semantic witness SHA-256 `3e4f3644d6f3acfdfa9d6c83756e907c25ad7ebf113785880e44b30b87e62f7a`, with verified task-owned cleanup. The ignored result is `artifacts/V5/V5-04H/purge-interruption-both-01/results.json`. Syntax, compilation and all 16 sealed inputs passed. The full Python and Node regressions last passed at H-S22 and were not rerun for this fixture-only slice.

The key failure case is a completed physical delete with no settled client receipt. Treating that as completed purge could reclaim claims before recovery has fenced old writers. The native test keeps the purge pending until exact absence is observed. No product module, SQL/schema, migration, lockfile, shared sealed fixture or user-owned file changed. This is local single-node evidence, not hosted CI, live-model quality, cluster behavior or production readiness. Sol peers coordinated cancellation and matching witness directly; Python assembled and root ran final acceptance. Learning practice remains unassessed: explain why a cancelled client cannot infer that its completed server operation was safely recorded.
