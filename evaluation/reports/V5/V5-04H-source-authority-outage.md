# V5-04H: Authority unavailable during repair authorization

State: COMPLETE for fault ID `source_authority_outage` in the declared client authority-access profile only. V5-04H and V5 remain open.

For example, a repair must not treat an unavailable authority read as permission to continue. It must return an operational failure before it contacts Qdrant or publishes.

At the G1a repair authorization boundary, both native consumers first make a bounded, scoped PostgreSQL read of the active generation and staged intent. The read succeeds. The caller-owned writer pool is then closed, and the same read fails with `ProviderUnavailable`. The manager returns that typed failure. Instrumented preflight, recovery, publication and all Qdrant requests remain at their prior counts. A sequential fresh writer connection reads the same active generation and still-unpublished intent after the refusal. The fixture never exceeds two concurrent PostgreSQL clients. This injects a client loss of authority access; it does not stop the PostgreSQL server process.

Root inspected the Python and TypeScript consumer edits and ran:

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_qdrant_repair_native.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_repair.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/source-authority-outage-both-04
node --check tools/check_typescript_qdrant_repair.mjs
uv run --project packages/python --frozen --no-sync python -m py_compile tools/qdrant_repair_cases.py tools/check_qdrant_repair.py
python3 tools/check_seal.py
```

Three focused protocol tests passed. The native parent passed ten checks per runtime with verified cleanup; its ignored result is `artifacts/V5/V5-04H/source-authority-outage-both-04/results.json`. Syntax, compilation and all 16 seals passed. Full 3,104-test Python and 1,557-test Node regressions passed at H-S22; they were not rerun for this fixture and harness change.

The first two Python native attempts failed before the new case. Source inspection found that the G1a acknowledgment fixture omitted an inactive `publication` observation required by its shared transaction wrapper. Adding those five inactive fields restored the baseline; the final Python and combined native runs passed. The Python pool logs a discarded closed connection during the intentional fault. No product module, SQL/schema, migration, lockfile, shared sealed fixture, or user-owned file changed. This is local single-node evidence for caller authority-access loss, not a database-server outage, hosted CI or production readiness. Sol peers coordinated the exact read and client ceiling directly; Python assembled, and root ran acceptance. Learning practice remains unassessed: explain why an unavailable authority read must not become an empty-success repair result.
