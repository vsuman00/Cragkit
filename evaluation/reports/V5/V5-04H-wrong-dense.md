# V5-04H: Public refusal of a wrong dense vector

State: COMPLETE for frozen fault ID `wrong_dense_vector` only. The other public corruption rows, V5-04H and full V5 remain open.

For example, a two-point successor can be written to Qdrant while the previous generation remains active. If one stored dense vector changes from basis e0 to e1 before verification, the public manager must refuse publication and keep the previous pointer.

## Native boundary

A separate `wrong-dense` mode reuses the actual public manager, PostgreSQL authority, pinned Qdrant controller and disposable fixture. The default manager mode and its 20 ordered checks per runtime remain unchanged. The mode publishes a two-member base, stages a two-member successor, then arms a one-shot observer for that successor's ordinary full-point PUT. The observer forwards the real request, requires Qdrant's completed acknowledgment, and uses the underlying native handle to change the e0 point to e1 with a second completed same-ID PUT. It returns the original acknowledgment to the manager. The manager's genuine readback raises `IntegrityViolation`.

The test checks the physical two-ID readback through a fresh diagnostic attempt because the manager closes its write handle. It also checks the previous active pointer, no target preparation, target generation `published=false` and `ever_published=false`, writing intent with incomplete replica, one settled product dispatch, unchanged immutable member/claim/source graph and one observer firing. Fixture fault writes are counted separately from product writes. The synthetic generation IDs stand for the frozen example's old and successor generations.

This tests one same-dimension vector corruption and public refusal. It does not establish equal-count wrong membership, sparse corruption, missing sparse repair or wrong full profile. No product verifier or SQL authority state was replaced by a fake.

## Verification

Root ran five parent protocol guards, static syntax checks, both native modes serially and all 16 seals. The accepted commands were:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_publication_manager_native.py -q
node --check tools/check_typescript_qdrant_publication_manager.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --scenario wrong-dense --artifacts-dir artifacts/V5/V5-04H/wrong-dense-both-final-06
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/manager-default-final-07
python3 tools/check_seal.py
```

The isolated mode passed one check per runtime with identical three-result snapshot hash `aada03a4d97b1a0abeaaa2f665fd68d26c97eab47c509f9a53cf97c8e25cb23b` and verified cleanup. The default mode passed 40 checks, preserved its earlier hash `89319b18e0a39af96dc72d9d0db5ae4a56913e44e4f28d8922fefd134e40c61e`, and verified cleanup. Both comparison records have zero normalized fields. These ignored result files sit under the two artifact directories above. All sealed evaluation inputs matched.

Three preliminary runs failed before acceptance. The first exposed the UUID-order assumption: the e1 point came first, so the injector now selects e0 by value. The next two showed that the manager had correctly refused publication but had closed its write handle before the fixture's physical read. A fresh diagnostic attempt fixed that observation. The final runs used the corrected source. Failed private fixture storage is retained as ignored diagnostic evidence; the task-owned listeners were closed.

Sol peers implemented separate Python and TypeScript consumers and coordinated the fault and snapshot contract directly; Python assembled. Root owned the mode protocol, parent, focused tests, serial native runs and integration. No product module, schema, migration, dependency, lockfile, hosted service or model provider changed. Disk headroom was 28 GiB and system memory free 53 percent after final cleanup. Twenty exact H IDs now have accepted native evidence. Learning practice remains unassessed: explain why a Qdrant completed write is insufficient to publish when its readback vector differs from the immutable manifest.
