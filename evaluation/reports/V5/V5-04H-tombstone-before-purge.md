# V5-04H: Tombstone before managed purge

State: COMPLETE for frozen fault ID `tombstone_before_purge` only. V5-04H and V5 remain open.

For example, a source must stop releasing text as soon as its tombstone commits, even while its older Qdrant points still exist. Physical cleanup can follow without making that source readable in the meantime.

The existing G3 native purge trace now checks that boundary directly. After the base document's tombstone commits, retained and fresh source requests both return unavailable. Before any purge call, a bounded, scope-filtered Qdrant scroll returns the exact four base and successor point IDs and reaches its final page. The authority snapshot shows authorization revision `auth-2`, a committed tombstone, an unchanged active pointer, and purge still incomplete. A successor publication admission records denial without publishing or sending a new point write. The trace then completes the existing managed purge and its fault checks.

Root inspected the separate Python and Node consumer edits and ran these serial checks:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_purge_native.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_purge.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/tombstone-before-purge-both-01
uv run --project packages/python --frozen --no-sync pytest packages/python/tests tools/tests -q
npm --prefix packages/typescript test
python3 tools/check_seal.py
```

Seven focused protocol tests passed. The native parent passed 42 checks: nine purge scenario checks, five fault checks and seven independent SQL storage checks per runtime. Both runtimes returned the same semantic witness SHA-256, `11795e401a358d604d3e8f8c1450d188d6ef41398f85346b3ee5aab0ec08934d`, with verified task-owned cleanup. The ignored result is `artifacts/V5/V5-04H/tombstone-before-purge-both-01/results.json`. Full local regressions passed: 3,104 Python/package-tool tests with four existing Pydantic serializer warnings, and 1,557 Node tests. Strict Python and TypeScript typechecks passed earlier in this slice. All 16 sealed inputs matched. No owned service remained; disk headroom was 28 GiB.

The first full Python regression ran while the peer files were still being assembled and failed only the not-yet-updated nine-check protocol assertion. The final assembled suite passed. This is local native evidence for the selected single-node profile, not hosted CI, live-model quality, forensic erasure or production readiness. Sol peers owned the nonoverlapping consumers and coordinated the physical readback, denial and witness order directly; Python assembled. Root owned final integration and the tracker. No product module, schema/migration, shared fixture, lockfile or user-owned edit changed. Learning practice is unassessed: explain why an old physical point cannot authorize source release after a tombstone.
