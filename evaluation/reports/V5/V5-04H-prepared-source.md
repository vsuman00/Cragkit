# V5-04H: Prepared replica source boundary

State: COMPLETE for frozen fault ID `prepared_not_published` only. V5-04H and full V5 remain open.

For example, Qdrant can nominate a successor point while its SQL publication is still prepared. A fresh source request must continue to authorize only the previous active generation.

## Native observation

The current F3 source scenario pauses the actual public manager after durable preparation and before the publication CAS. The source consumer checks that the intent is `prepared` and the document pointer still names the previous generation. It searches the physical collection, receives both old and successor nominations, then fetches sources through the authoritative gate. During the prepared successor pause, only the two previous-generation sources verify; successor source release is refused. The scenario resumes publication, then verifies that fresh requests admit the successor and refuse the previous generation. Python and TypeScript use the same synthetic fixture and independent native clients.

This is a bounded pause with a surviving manager. It does not establish process-death recovery or the other H fault rows. Physical candidates being present is expected; source release and publication are the protected boundaries.

## Verification

Root reran the existing parent against disposable PostgreSQL 17 and pinned Qdrant 1.20.0:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_source.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/prepared-source-both-01
```

The parent returned `ok: true`, 16 checks (eight per runtime), `cleanup_verified: true`. Both runtimes reported `source_observations_sha256: a29e4a9af6479ce69a97e38763e5f164c8758109d073e113317328e613c24510`. The ordered checks include `prepared_replica_has_candidates_but_no_source_release` and `prepared_successor_preserves_previous_active_sources`. The ignored result is `artifacts/V5/V5-04H/prepared-source-both-01/results.json`. The parent verified task-owned process cleanup. No paid provider, model download or hosted database was used.

The frozen fixture illustrates `gen-1` as the active generation and `gen-2` as prepared. The actual fixture uses its own synthetic generation IDs and asserts the same relationship. No code, fixture, schema, migration, dependency or lockfile changed for this registration. The independent H-S9 audit proposed this mapping; root inspected the consumers and reran the current source before accepting it.

Sixteen exact H IDs now have accepted native evidence. The remaining matrix rows, recovery process-death profile and final V5 gates are open. Learning practice remains unassessed: explain why a physical search hit from a prepared generation cannot authorize source release.
