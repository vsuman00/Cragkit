# V5-04H: Missing sparse vector and ordinary repair

State: COMPLETE for frozen fault ID `missing_sparse_vector` only. V5-04H and V5 remain open.

For example, Qdrant can acknowledge a two-point successor write, then store one point without its named sparse vector. The public manager must refuse publication. A later repair of the same durable intent must send both named vectors and verify the full stored points before changing the active pointer.

## Native trace

The exclusive `missing-sparse` mode uses a disposable PostgreSQL 17 authority with the existing attestation migration and a pinned Qdrant 1.20 controller. The base generation is published. A two-member successor is staged against that pointer. After the successor's genuine full-point PUT returns a completed acknowledgment, the fixture makes one completed same-ID PUT that removes `sparse` from the e0 point while retaining its dense vector and payload. It returns the original acknowledgment to the manager. The manager's real readback raises `IntegrityViolation`.

Both consumers read back the exact two physical IDs through a fresh diagnostic attempt. They check that the previous pointer remains active, the target remains unpublished and unprepared, its writing intent has an incomplete replica, the product dispatch is settled, and the immutable source/member/claim/replay graph is unchanged. The fixture write is counted separately.

With the fault disabled, public `manager.repair` uses a fresh ledger on the same intent, revision and generation. The consumers capture the actual forwarded repair PUT before sending it and require both named `dense` and `sparse` vectors, the two expected IDs, original submitted values and manifest profile descriptors. They require Qdrant's completed acknowledgment, exact physical full-point readback, two settled target dispatches and no unknown journal state. The target then becomes published with true publication flags and the active pointer; immutable graph records remain unchanged. Four ordered public result snapshots match across runtimes.

## Verification and limits

Root ran eight focused parent protocol guards, Python compile and Node syntax checks. These native commands ran serially with the pinned binary SHA-256 `830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3`:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_publication_manager_native.py -q
node --check tools/check_typescript_qdrant_publication_manager.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --scenario missing-sparse --artifacts-dir artifacts/V5/V5-04H/missing-sparse-both-03
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/manager-default-regression-04
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --scenario wrong-sparse --artifacts-dir artifacts/V5/V5-04H/wrong-sparse-regression-04
python3 tools/check_seal.py
```

The missing-sparse mode passed two checks per runtime (four total) and matched public snapshot hash `e0c14d24d4ef765be5f4c93353bfad0372d23349f87d54a003d7b25a40068a74`. Default manager regression passed 40 checks and retained hash `89319b18e0a39af96dc72d9d0db5ae4a56913e44e4f28d8922fefd134e40c61e`. Wrong-sparse regression passed two checks and retained hash `3525244b198393223e17ce6efddf53cbab6a0d88c1967181c861528c1bf84ea4`. All three native parents verified cleanup, and their Python/TypeScript comparisons needed zero normalized fields. All 16 seals matched. Ignored local result files remain under the directories above.

The first native attempt failed during repair with `UnsupportedCapability`. A bounded diagnostic run traced it to `preflight_repair` rejecting the publication-only fixture schema profile. Root enabled the already existing attestation migration only for `missing-sparse` and reran the accepted path. This changed fixture setup, not a product migration. The diagnostic and failed artifact directories remain ignored; no service remains running.

Sol peers owned separate Python and TypeScript consumers, resolved the journal and profile assertion difference directly, and the Python peer assembled. Root reviewed the pair, owned the parent/protocol, ran native checks and integrated the result. No product module, schema file, shared fixture, dependency, lockfile, provider or hosted service changed. Disk headroom was 28 GiB and system memory free 52 percent after cleanup.

Twenty-three exact H IDs now have accepted native evidence. Equal-count wrong membership with third-point sentinel remains a separate fault. Learning practice is unassessed: explain why a successful repair must send the full named-vector point instead of relying on the earlier write's sparse field.
