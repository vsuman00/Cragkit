# V5-04H: Global physical UUID claim collision

State: COMPLETE for exact fault ID `global_uuid_collision` only. V5-04H and V5 remain open.

For example, two documents can each have a valid coordinator but still contend for one physical point UUID. The global SQL claim must allow only one immutable owner. A losing document must not overwrite the winner's Qdrant point.

The native test publishes a baseline generation for each document with separate coordinator and writer resources. Two successor stages then race for the same physical UUID. Because Cragkit derives point IDs from the complete document identity, a test-only hook maps one successor's exact identity to the other's valid UUID. All other identities keep their ordinary derivation. Manifest validation, the PostgreSQL claim transaction and guard, manager operations and Qdrant HTTP remain native. The Python hook is restored after the case; the TypeScript hook is source-hash checked and confined to an isolated child process.

The first stage pauses after its real claim INSERT. The independent observer sees the second PostgreSQL transaction waiting on the first transaction's claim. After the first commits, the second returns `IntegrityViolation`. Its successor intent, source/revision/generation/member, replay, claim and journal rows roll back; both baseline owners, active pointers and points remain unchanged. The winner then publishes through the managed transport. A retry of the losing stage still makes zero Qdrant mutations and leaves the winner's exact payload and named-vector readback, plus unrelated baseline points, unchanged. This is a controlled collision fault, not evidence of finding a natural hash collision.

Root inspected both consumers and ran Python-only, TypeScript-only and combined native cases serially against disposable local PostgreSQL and Qdrant. The combined result passed 14 checks, seven per runtime, with matching semantic witness SHA-256 `8744159fa9127919ea6f0da05212329ae527b64932d34c12c99b6fbaf7e88c0e` and verified cleanup. The ignored result is `artifacts/V5/V5-04H/global-uuid-both-01/results.json`. Fifteen focused parent tests, Python compilation, Node syntax and all 16 input seals passed. Full package regressions last passed at H-S30 and were not rerun for this isolated harness addition.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_security_verification.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --global-uuid --runtime all --artifacts-dir artifacts/V5/V5-04H/global-uuid-both-01
```

No product module, SQL/schema, migration, shared fixture, lockfile or user-owned file changed. The result is local single-node behavior, not hosted CI or production readiness. The two Sol peers owned separate consumers and assembled the agreed witness; root ran acceptance. Learning practice remains unassessed: explain why a single shared one-slot database pool would not demonstrate this race.
