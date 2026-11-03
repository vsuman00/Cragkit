# V6-07 upgrade and required operator repair

Status: COMPLETE for the scoped MRR-r2 upgrade, explicit lexical repair and
package-compatibility rehearsal on disposable PostgreSQL 17.11 / pgvector 0.8.0.
The unmodified populated 0001-to-0002 upgrade is not accepted: it preserves the
`simple` alias that both native readers refuse. The successful path requires
the separate LCR-r1 operator repair. Full V6 and publication remain separate.

For example, the native interruption returned a pending repair receipt, then
terminated its backend before commit. The alias rows remained unchanged;
explicit retry committed their repair. A pending receipt never became proof of
a successful commit.

This report follows [MRR-r2](../../../contracts/RECOVERY_REHEARSAL_V6.md) and
[V6-07](../../../tasks/versions/V6-release.md#v6-07-migration-and-rollback-rehearsal),
covering E58/E65. Current-authority backup/restore acceptance is recorded
separately in [the backup report](V6-07-backup.md).

## Verified native behavior

Root ran the bounded functional pipeline successfully. The inspected local
result is `artifacts/V6/migration-recovery-r2-functional/results.json`, SHA-256
`3000cc2dd8d895785bee7d52f16b0223636be27e6d10dd22f46bdd00bda54308`.
Its retained stdout, `artifacts/V6/migration-recovery-r2-functional-run.log`,
reports MRR-r2 passed with six main check groups. Fourteen operator check groups
also passed. The result records verified cleanup and zero live provider calls.

The populated lexical upgrade preserved canonical revisions, source bytes and
spans, grants, active generations and the prior migration checksum/timestamp.
The column became text while retaining `simple`, which resolves to the same
`regconfig` as `pg_catalog.simple` but fails the exact reader guard. The saved
observation records `fixture_normalized=false`. A separate identifier document
stores `ERR_RECOVERY_42` through the native `identifier_ascii_v1` extractor;
original source/documents and earlier observation directories were preserved.

Both historical `0.0.0` products and the current exact CI products were exercised
in native Python and Node. Every worker verified installed file bytes and its
trusted package version before reading. The identifier case directly called
`PostgresSession.transaction` / `identifier_candidates`, then fetched the
currently authorized candidate source. It did not infer branch coverage from
query syntax. Successful evidence had exact text, byte span, revision and
source/text digests.

| Storage state | Current Python/Node | Historical Python/Node |
| --- | --- | --- |
| Unmodified 0002 alias rows | FTS and direct identifier: `unsupported_capability`; fake dense: complete | Same |
| Explicit repair, before setup 0003 | FTS, direct identifier and fake dense: complete | Same |
| After setup 0003 | FTS, direct identifier and fake dense: complete | FTS and direct identifier: complete; fake dense: `unsupported_capability` |

The pre-repair observations remain explicitly labeled
`failed_unmodified_upgrade`. The successful result sets
`unmodified_upgrade_accepted=false`; no history was removed or vector relabeled
to accommodate the old binary. The retained products lack a later security
correction and remain ineligible for production rollback. No patched eligible
predecessor has been declared.

Setup 0003 also passed a genuine precommit backend-termination check: the owned
PID was observed active in `PgSleep` after writes, then terminated. Earlier
committed source/history/vector state remained intact and the new table was
absent. Explicit upgrade, read-only checking and idempotent reapplication then
passed. The upgraded optional catalog passed an additional LCR-r1 check-only
no-op. Finally, a committed unknown history row was refused without deleting or
repairing it; disposal ended that deliberately invalid fixture state.

## LCR-r1 operator acceptance

The separate artifact is
`storage/postgres/maintenance/0001_lexical_config.sql`, SHA-256
`78d3b4c322e1e79c6e8ac012876308abba1724466b61548bad36904478da536c`.
It changes only literal `simple` to `pg_catalog.simple` for supported
`native_fts.v1` generations. The operator changes neither schema nor history;
applied migration, library, manifest and lockfile bytes remain unchanged.

The explicit tool binds the database, owner and TLS connection; its receipt
hashes only validated host/port/database/owner scalars. It checks pinned history,
ownership/RLS, affected columns/defaults/constraints, complete affected triggers
and frozen function bodies/flags, supported profiles/configurations, joins,
canonical spans and existing FTS vectors. It holds the migration advisory lock
and sorted writer-excluding table locks with bounded timeouts. Keyed snapshots
preserve source/security/history, policies/ACLs and binary vector wires, allowing
only the declared configuration text delta. Combined snapshots refuse work
above 1,000 rows or 8 MiB.

A separate hardened lexical-only fixture passed check/apply/idempotence without
creating optional vector storage. Actual CLI check/apply/check returned **2/0/0**:
repair required, repaired, then already canonical. Its owner-only scalar config
was removed in `finally`; no credential appeared in argv or output. Check mode
made no update. Imported transaction receipts remained pending until their owned
commit completed. Exact two-step and three-step vector catalogs were also
validated; setup-only 0001 is explicitly unsupported and unmanaged state refuses.

The fourteen native operator groups covered check-only/no mutation, wrong
target, core-history drift, unknown optional history, column-default drift,
generation profile, configuration, stored FTS vector, disabled trigger,
replaced function, extra trigger, writer-lock refusal, native interrupted repair
and successful retry/idempotence. Probe mutations rolled back. The actual writer
conflict returned `55P03`. Interrupted repair was observed after its validated
update but before commit; its receipt stayed pending and prior alias state
survived. Retry repaired two alias rows while preserving the already canonical
vector document. Idempotent reapplication changed zero rows.

## Commands and resource observations

Root's latest focused suite passed **109 tests in 0.32 seconds**:

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_check_migration_recovery.py tools/tests/test_repair_legacy_lexical_config.py -q
```

The functional command used the prepared local prefix and fresh output:

```sh
env -u PYTHONPATH -u PYTHONHOME -u NODE_PATH -u NODE_OPTIONS \
  artifacts/V6/release-candidate-rc1/packages/python/.venv/bin/python -I -B tools/check_migration_recovery.py \
  --old-python artifacts/V6/rollback-installed/python-env/bin/python \
  --old-node-root artifacts/V6/rollback-installed/node-sdk \
  --sdk-root artifacts/V6/release-candidate-rc1/packages/typescript \
  --prepared-postgres-bin artifacts/V6/V6-02A/private-pg/prefix/Cellar/postgresql@17/17.11/bin \
  --output artifacts/V6/migration-recovery-r2-functional \
  --allow-local-processes
```

One cluster was active at a time, with the existing six-connection fixture cap,
small synthetic documents and sequential package consumers. Ten pressure samples
reported **35-38% free memory** and unchanged cumulative swapout pages
**7,204,592**, so no new swapouts occurred between those samples. The existing
pressure guard ran before/after each fixture and at major phases. This was a
functional rehearsal, not a load benchmark. Clients, private configuration and
fixture listeners closed. Broader checkpoint regression is a separate final
integration record; this report does not infer its result from the focused run.

## Identity and retained diagnostics

Current products were rebound to the pinned hosted ZIP through CIB-r1 and its
exact core members; historical archives were rebound to their retained V5
acceptance record. These identifiers do not establish new model quality or CI
acceptance for the newly added operator tool.
The current products retain CI source
`0c7c568d5cb71638eebab2dea97c5973b0f8cc08`; the operator's acceptance is local.

| Product | SHA-256 |
| --- | --- |
| Current core wheel | `ad8e7c928363bdf23cf69d479657219a0e662e498706f7254e211554e11ca599` |
| Current core npm | `339e1004df372a5fe111296b96b964a0e90533dfc0db414ce996a0c7805932b3` |
| Historical core wheel | `42b6958b6239db2184f9fa814b88c16c9832d0e05886c198795a60febb3b224f` |
| Historical core npm | `f169baf931ba36492dd3c2be104f2f3aab105b811fb6e305f257b70b34a2bfe0` |

Frozen code hashes inspected after the successful run:

| File | SHA-256 |
| --- | --- |
| `tools/check_migration_recovery.py` | `aa9083d5e71d51cb5390f78a62e7ad1ef958f8208ced118c0194329566ffc8d8` |
| `tools/migration_package_probe.py` | `b2bfc7553b51b8081a6350817881e7bb44976596d86e2412e85da2958381107c` |
| `tools/migration_package_probe.mjs` | `644482c1729cb8cd81aac52274196f766985274d011424047f69467bb099a157` |
| `tools/repair_legacy_lexical_config.py` | `5c69afed172eda0112d9065ae8ece559865c665bf52a44fd7e34213a08ac8079` |

All earlier local attempts remain retained, separately from the real alias
compatibility issue. Paths below are under `artifacts/V6/`:

| Attempt | Observed outcome and disposition |
| --- | --- |
| `migration-recovery-run.log` | Initial unlocalized lexical-stage failure; no acceptance claim. |
| `migration-recovery-diagnostic-run.log` | Harness used nonexistent `to_regconfig(text)`; replaced with the supported `regconfig` cast. |
| `migration-recovery-cast-verified-run.log` | Real preserved-alias observation; the child harness had not yet collected both runtimes' typed refusals. The final functional run supplies them. |
| `migration-recovery-r2-run.log` | Strict CHECK expectation omitted PostgreSQL's intermediate `NULL::text` cast. A genuine PG17 backup schema verified the exact expression; only that expected spelling changed. |
| `migration-recovery-r2-catalog-verified-run.log` | Binary snapshot called nonexistent `tsvector_send`; prepared PG17 BKI verified `pg_catalog.tsvectorsend(tsvector)`. Binary comparison was retained. |

The prepared `prefix/share/postgresql@17/postgres.bki` line 2650 registers
`tsvectorsend`, and line 2203 verifies `sha256(bytea)`; the extension SQL line 20
verifies `vector_send(vector)`. Safe failure diagnostics expose fixed stages,
allowlisted types/SQLSTATE/function signatures and owning code locations without
raw SQL, messages, arguments or configuration. Earlier harness failures were not
relabeled as successful runs or used as proof of the alias defect.

The native operator receipt in `operator-repair.json` has SHA-256
`8ffd4573ff0831f64a6a11e253a36e89a2b749f8db0c76aa7e659061f7da0c7e`;
`lexical-only-repair.json` has SHA-256
`bdd03cdeda8c3eae883e470c65de184b5167ccad39fdd6c783d1714adf7a0a52`.
Both are retained in the successful functional directory above.

Acceptance is limited to this disposable same-platform fixture, declared
catalogs and bounded maintenance operation. Cross-cluster/hosted recovery,
production availability, larger datasets and deployment of the old package
remain unvalidated. Learning practice remains unassessed: explain why a pending
receipt after backend termination differs from an explicit committed retry.
