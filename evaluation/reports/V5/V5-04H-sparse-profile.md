# V5-04H: Public refusal of sparse and profile corruption

State: COMPLETE for frozen fault IDs `wrong_sparse_vector` and `wrong_full_profile` only. V5-04H and V5 remain open.

For example, a completed Qdrant write can leave the successor with a changed sparse weight. The public manager must compare the stored point with its immutable manifest before changing the active pointer.

## Native boundary

Two exclusive public-manager modes use the existing PostgreSQL authority, pinned Qdrant controller and disposable two-point fixture. After the successor's ordinary full-point PUT receives a completed acknowledgment, a one-shot observer changes the e0 point through the underlying native handle. `wrong-sparse` changes one sparse weight by 0.25. `wrong-profile` changes the stored dense profile model field to `wrong-profile` while keeping its profile ID. Each fault uses a second completed same-ID PUT, then returns the original acknowledgment to the manager.

Fresh diagnostic attempts read back both physical point IDs exactly. The manager's own readback raises `IntegrityViolation`. Each mode checks the previous active pointer, target `published=false` and `ever_published=false`, no target preparation, a writing intent with incomplete replica, one settled product dispatch, unchanged immutable member/claim/source graph and one observer firing. Fixture fault writes remain distinct from product dispatches. These modes do not replace the product verifier or SQL authority with fakes.

## Verification

The parent protocol passed seven focused guards. Python compiled, Node passed `--check`, and all 16 sealed inputs matched. Root ran each native parent serially with PostgreSQL 17 and the pinned Qdrant 1.20 binary (SHA-256 `830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3`):

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_publication_manager_native.py -q
node --check tools/check_typescript_qdrant_publication_manager.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --scenario wrong-sparse --artifacts-dir artifacts/V5/V5-04H/wrong-sparse-both-01
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --scenario wrong-profile --artifacts-dir artifacts/V5/V5-04H/wrong-profile-both-01
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --scenario wrong-dense --artifacts-dir artifacts/V5/V5-04H/wrong-dense-regression-02
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/manager-default-regression-03
python3 tools/check_seal.py
```

Each new mode passed one native check per runtime with verified cleanup and zero normalized snapshot fields. Python and TypeScript matched hashes `3525244b198393223e17ce6efddf53cbab6a0d88c1967181c861528c1bf84ea4` for sparse and `7a3c85fa0c5c15b6397e44658d2554b9071d4ade8c8057b9eaeca6d056e53493` for profile. Wrong-dense regression passed two checks and kept hash `aada03a4d97b1a0abeaaa2f665fd68d26c97eab47c509f9a53cf97c8e25cb23b`. The default parent passed 40 checks and kept hash `89319b18e0a39af96dc72d9d0db5ae4a56913e44e4f28d8922fefd134e40c61e`. All four runs verified cleanup. Result files are ignored local evidence under the directories above.

Sol peers owned separate Python and TypeScript consumers, coordinated the fault contract directly, and Python assembled. Root reviewed both diffs, integrated the parent and protocol guards, ran native verification and checked the report. No product module, schema, migration, shared fixture, dependency, lockfile, provider or hosted service changed. Disk headroom was 28 GiB and system memory free 54 percent. An orphaned Qdrant process from an earlier disposable run was stopped after verification.

Twenty-two exact H IDs now have accepted native evidence. Equal-count wrong membership and missing sparse vector with ordinary repair remain open. Learning practice is unassessed: explain why a profile field mismatch must block publication even when the profile ID and point count match.
