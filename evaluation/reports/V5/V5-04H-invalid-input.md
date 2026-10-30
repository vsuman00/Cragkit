# V5-04H: Invalid member, UTF-8 span and sparse encoder

State: COMPLETE for frozen fault IDs `mixed_revision_member`, `malformed_utf8_span` and `unsupported_sparse_encoder` only. V5-04H and V5 remain open.

For example, a chunk ending at byte 6 of `A café 雪.\n` splits the UTF-8 bytes for `é`. The manager must reject that stage before it creates target rows or sends points to Qdrant.

## Native trace

An exclusive `invalid-input` mode uses the real Python and TypeScript public managers, disposable PostgreSQL 17 and pinned Qdrant 1.20. It first publishes a valid two-point base. Three separate successor copies then each fail at public `manager.stage`:

1. A member's point ID is replaced by the corresponding base member ID, which encodes a different revision. The observed error is `IntegrityViolation`.
2. Chunk-1 `end_byte` changes from 7 to 6 inside `é`. The observed error is `IntegrityViolation`.
3. The copied sparse profile changes its encoder from the supported manual fixture to undeclared `bm25` while retaining complete sparse vectors. The observed error is `UnsupportedCapability`. This does not add a BM25 encoder.

Each refusal leaves the base pointer and immutable base graph unchanged. The two consumers check that no target intent, revision, generation, member, claim, replay, preparation or dispatch row appeared; the journal, HTTP request/mutation counts and issuer attempt count did not advance. Fresh diagnostic attempts read the valid target IDs and filtered target scope from Qdrant and find no target points. The diagnostic calls are separate from product mutations. No model provider exists in this fixture. Only the base's two public result snapshots enter the cross-runtime hash.

## Verification

Root ran ten focused parent guards, Python compile, Node syntax, all 16 seals and the following native parents serially. The Qdrant binary SHA-256 was `830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3`:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_publication_manager_native.py -q
node --check tools/check_typescript_qdrant_publication_manager.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --scenario invalid-input --artifacts-dir artifacts/V5/V5-04H/invalid-input-both-02
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/manager-default-regression-07
python3 tools/check_seal.py
```

The invalid-input parent passed three checks per runtime (six total) and matched public snapshot hash `3909082988a2b3dd9d83fd9174b7660898f4981dc1d5c96eaac11c9be42dee57`. The default manager passed 40 checks and retained hash `89319b18e0a39af96dc72d9d0db5ae4a56913e44e4f28d8922fefd134e40c61e`. Both parents verified cleanup, and their Python/TypeScript comparisons required zero normalized fields. Ignored local result files remain under those artifact directories.

The first invalid-input run passed. Root then limited Node's attempt-count observer to this mode so other modes retain their existing behavior, and reran the accepted scenario and default regression on that final source. No product module, schema, migration, shared fixture, dependency, lockfile, provider or hosted service changed. Sol peers owned separate consumers and coordinated typed errors and absence checks directly; Python assembled and root integrated. Disk headroom was 32 GiB and system memory free 54 percent after cleanup; no task-owned service remains.

Twenty-seven exact H IDs now have accepted native evidence. The whole H matrix still needs the other IDs and final combined gates. This trace proves the byte-6 split; separate NUL-preserving and invalid-whole-UTF-8 source regressions remain part of the later combined checkpoint. Learning practice is unassessed: explain why checking only that no point PUT occurred would miss a target SQL row created by a faulty admission path.
