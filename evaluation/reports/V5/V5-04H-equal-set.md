# V5-04H: Equal-count wrong set and third-point sentinel

State: COMPLETE for frozen fault ID `equal_count_wrong_set` only. V5-04H and V5 remain open.

For example, replacing one expected point with an unexpected point can leave the scoped count at two. A count check would pass. The public manager must read the expected IDs and enumerate the scoped set before it changes the active generation.

## Native traces

An exclusive `equal-set` mode uses the actual Python and TypeScript public managers, PostgreSQL 17 authority, pinned Qdrant 1.20 controller and disposable two-point fixture. It publishes a base generation, then stages two separate successors against the same base pointer.

In the first trace, the successor's genuine full-point PUT receives a completed acknowledgment. The fixture then completes a native delete of one expected UUID and a native PUT of its copied point under fixed unexpected UUID `00000000-0000-4000-8000-000000000099`. Exact-ID and filtered scoped reads show the surviving expected point plus the unexpected point, with the scoped count still two. The manager's actual readback raises `IntegrityViolation`. The old active pointer, target unpublished flags and immutable source/member/claim/replay graph remain intact; the unexpected UUID is not adopted into claims.

In the second trace, both expected points remain and the fixture inserts a third scoped point under `00000000-0000-4000-8000-000000000098` after the genuine completed PUT. The observer records the verifier's exact-ID read followed by one filtered scroll with `limit=8`, at most 1 MiB response allowance, three full points and no continuation. The manager again raises `IntegrityViolation` and preserves the same publication fence. Fresh diagnostic attempts confirm each physical set. The fixture deletes both unexpected UUIDs by exact ID after recording their evidence; fixture mutations and product PUTs are counted separately. Four ordered public result snapshots match across runtimes.

## Verification

Root ran nine focused parent guards, Python compile, Node syntax, all 16 seals, and native parents serially. The accepted native commands used the pinned Qdrant binary SHA-256 `830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3`:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_publication_manager_native.py -q
node --check tools/check_typescript_qdrant_publication_manager.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --scenario equal-set --artifacts-dir artifacts/V5/V5-04H/equal-set-both-04
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/manager-default-regression-06
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --scenario missing-sparse --artifacts-dir artifacts/V5/V5-04H/missing-sparse-regression-06
python3 tools/check_seal.py
```

The equal-set mode passed two checks per runtime (four total) with identical public snapshot hash `1ac7cd0cb40d14834f2d4da23bdc409337a286e43a48c51a06e52abbf86ee074`. Default manager regression passed 40 checks and retained hash `89319b18e0a39af96dc72d9d0db5ae4a56913e44e4f28d8922fefd134e40c61e`. Missing-sparse repair regression passed four checks and retained hash `e0c14d24d4ef765be5f4c93353bfad0372d23349f87d54a003d7b25a40068a74`. Each native parent verified cleanup; comparisons required zero normalized fields. Ignored local results are under those artifact directories.

The initial combined run failed in Node's fixture at step zero. A Python-only diagnostic passed; Node's failure location identified an overly broad equality check that included legitimate owner/dispatch changes in the base graph. Root narrowed it to immutable base records, pointer, intent and preparation state. The accepted combined and regression runs used that correction. The failed and diagnostic directories remain ignored, and no task-owned service remains running.

Sol peers wrote separate Python and TypeScript consumers and coordinated the fault and readback contract directly; Python assembled. Root integrated the parent and protocol, inspected both diffs and ran native verification. No product module, schema, migration, shared fixture, dependency, lockfile, provider or hosted service changed. Disk headroom was 31 GiB and system memory free 62 percent after cleanup.

Twenty-four exact H IDs now have accepted native evidence. The rest of H and V5 remain open. Learning practice is unassessed: explain why a scoped count of two cannot prove the two stored UUIDs are the expected members.
