# V6-07B: quarantined backup and recovery

Status: COMPLETE for this scoped backup/recovery rehearsal. Root ran 32 focused tests in 0.15 seconds after the diagnosed quarantine correction, then passed the actual restore and both native consumers. The first native attempt and its diagnostic probe remain recorded below. This lane inspected the results and digests; root owned tests, PostgreSQL and cleanup. Full V6-07 acceptance also requires the upgrade lane and final integration under [MRR-r1](../../../contracts/RECOVERY_REHEARSAL_V6.md).

For example, an old backup can contain a grant that was later revoked. Restoring its content must keep application logins disabled until the later grant state and deletion markers have been reconciled.

## Bounded procedure

`tools/check_backup_recovery.py` uses one prepared, task-owned PostgreSQL 17.11/pgvector 0.8.0 cluster. It seeds three small synthetic documents through the installed current vector writer with fake embeddings, then closes those resources. It creates an owner-only custom-format `pg_dump` archive before committing a later authorization revision, principal revocation and tombstone.

The helper captures that later authority separately from the backup and hashes its complete document/grant state. This is a rehearsal of an operator's trusted current authority source. It does not make an old backup authoritative or discover a production authority service.

Before restore, both fixture runtime roles become `NOLOGIN`, a fresh empty database is created, and `PUBLIC` database CONNECT is revoked. The helper checks zero runtime sessions and requires real runtime connection refusal. Password files remain mode 0600 within the fixture's private temporary directory. Child commands use scalar libpq environment fields; no password or connection URI appears in argv, reports or captured output.

Only the helper's own custom archive is accepted: regular owner-only file, bounded size, custom-format header and exact SHA-256. `pg_restore` uses `--no-owner --single-transaction --exit-on-error`. Existing object ACLs and policies are preserved; the helper does not pass `--no-acl`. The runtime roles already exist globally in this same cluster and remain unable to log in during restore.

The restored data initially has the old authority. A wrong archive hash, missing current snapshot and incomplete current snapshot must refuse progression while quarantine remains enforced. The authority gate checks exact document identity coverage, unique grants, the fixture's canonical integer revision format, nondecreasing revisions and preservation of existing tombstones. A transaction replaces grants and reconciles current authorization revisions/tombstones; it cannot release logins.

Only after current authority, immutable content/profile/generation metadata, original checksummed history, object ACLs and policies pass does the helper grant bounded database CONNECT and restore the two runtime logins. The installed Python consumer and current Node dist then independently check:

- Allowed retrieval returns the exact immutable source bytes, span, revision and digests.
- The revoked principal cannot retrieve the restored old source.
- A foreign tenant cannot retrieve it.
- A tombstoned document remains unavailable.
- A held old authorization revision cannot recover source access.

Both consumers use lexical retrieval with strict context counting and require zero provider calls. The seed uses only a deterministic fake embedding adapter. Final checks require unchanged current authority and immutable metadata, zero runtime sessions and a closed disposable listener. Temporary credentials disappear with fixture cleanup; the owner-only synthetic backup remains in the ignored output directory as evidence.

## Verification and diagnosed first attempt

Root ran the focused command below: 26 passed in 0.08 seconds initially, then 32 passed in 0.15 seconds after the quarantine regression cases were added:

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_check_backup_recovery.py -q
```

The cases cover missing/incomplete/changed authority, foreign/duplicate document identities, stale or malformed revisions, grant revision mismatch, duplicate grants, tombstone reversal and an authority failure before mutation. They also cover missing/changed/mispermissioned/linked backup files, a bad archive header, disabled-role/session/connection checks, and fixture-local database-specific password files. These are small synthetic tests; they do not substitute for the actual restore.

The first native command stopped at phase `quarantine`; it did not restore or release runtime access. Root retained `artifacts/V6/backup-recovery-run.log` and the owner-only `source.dump`. Memory was 34 percent free, with unchanged swapout count 7,050,832 across that attempt.

Root then ran the isolated empty-database probe at `artifacts/V6/backup-quarantine-probe/quarantine-observation.json`. Both copied role configurations executed `SELECT 1` before disabling. After `NOLOGIN`, both failed with the observed Psycopg `OperationalError` form: SQLSTATE unavailable, connection present and status BAD (1). The target administrator remained healthy; both roles were disabled, runtime sessions were zero and cleanup passed. This confirms that the startup refusal does not carry SQLSTATE in this driver path.

The gate now retains the independent NOLOGIN and zero-session checks and verifies a healthy administrator in the exact target database. It accepts a known authorization/permission SQLSTATE, or the observed `OperationalError` plus BAD-connection form when SQLSTATE is absent. Generic errors, unrelated timeouts, absent connection metadata and a non-BAD connection remain refused. Target role/admin host, port, database and certificate fields must agree when a separate target administrator is opened. The corrected focused suite and complete native restore both passed under root execution.

The successful native invocation used the fresh verified output path:

```sh
env -u PYTHONPATH -u PYTHONHOME -u NODE_PATH -u NODE_OPTIONS \
  artifacts/V6/release-candidate-rc1/packages/python/.venv/bin/python -I -B tools/check_backup_recovery.py \
  --sdk-root artifacts/V6/release-candidate-rc1/packages/typescript \
  --prepared-postgres-bin artifacts/V6/V6-02A/private-pg/prefix/Cellar/postgresql@17/17.11/bin \
  --output artifacts/V6/backup-recovery-verified \
  --allow-local-processes
```

The separate `--quarantine-probe` mode used a fresh empty fixture database. It first confirms that both database-specific role configurations can execute `SELECT 1`, then disables both roles, revokes PUBLIC CONNECT, checks zero sessions and a healthy target administrator, and records actual runtime refusals. Its observation contains only fixed error categories, SQLSTATE/connection-status fields and counts; no raw exception message or credentials. It performs no source ingestion, backup or provider work. This probe is not a passing recovery result.

The output path was fresh. A failure emits only a fixed diagnostic and phase name; it writes no passing result. The successful result and stdout were retained as `artifacts/V6/backup-recovery-verified/results.json` and `artifacts/V6/backup-recovery-verified-run.log`.

## Actual restore evidence

The verified custom archive is 110,248 bytes. All ten recovery checks passed: runtime quarantine, bad backup hash refusal, missing/incomplete authority refusal, current authority reconciliation, ACL/policy preservation, immutable content/profile/history preservation, native role guards, revocation preservation and cleanup. Three restored document identities were reconciled to the later authority before logins were released.

Both installed native consumers passed all five source cases: exact allowed source, revoked principal denial, foreign tenant denial, tombstone denial and held-old-scope denial. The tombstoned document retained its current grant, so its denial exercised the tombstone independently of grant revocation. Both consumers recorded zero provider HTTP calls. The fixture listener closed and runtime sessions were zero before shutdown.

The retained authority SHA-256 is `c783ff05a399f83cfca745f9bec4dbf61f6103ca6090e2d1801dbf88c949fa9d`. Thirteen immutable/catalog fingerprints in the result cover source revisions, generations, chunks, lexical/vector rows, profiles, collections, histories, policies and object ACLs. Current security metadata remained equal to the later snapshot after both consumers ran.

| Retained file | SHA-256 |
| --- | --- |
| `tools/check_backup_recovery.py` | `50f076e2b80ed3329dde8bf8bd9cf7d317b3c84eada48544e6b7653f2d6b3447` |
| `tools/recovery_source_checks.mjs` | `7bf042c368708e875cfc99aa1bac53319a89f07640d23011e16fb2fa463b6982` |
| `artifacts/V6/backup-recovery-verified/results.json` | `d4e42e509d3d84add93b94652dda8899c739656bbca62f1a98e313e70332db40` |
| `artifacts/V6/backup-recovery-verified/source.dump` | `1a5290ef8edd4952956e40430ece44fc8d25075b131a54aeeb9018d0c8c62af5` |
| `artifacts/V6/backup-recovery-verified-run.log` | `66ca183b6a2cac0bddec26754bf585b59e77f6e141bf7fc94ea0ebca2dd31956` |
| `artifacts/V6/backup-recovery-run.log` | `b028d3d07be79311b4059a7d4662ab4ce6be3dc784b8f9c65fd0474ba626c8ee` |

Successful-run pressure samples were 44 and 43 percent free memory; cumulative swapouts stayed at 7,050,832. Root also observed no swapout increase through the separate probe. These are current-machine observations for this small synthetic run, not a workload capacity guarantee.

## Limits and handoff

This slice does not modify migrations, package APIs, locks or application storage contracts. It does not restore into an occupied database, accept another archive, recreate cross-cluster global roles, provide hosted/PITR recovery or approve deployment of an older package. Full V6-07 acceptance also requires the independent [upgrade and package compatibility lane](V6-07-upgrade.md).

Changed files: the Python helper, Node consumer, focused Python test and this report. No lane-owned process was started. Root owns the tracker and final Git actions. Learning practice remains unassessed: explain why a byte-perfect backup with stale grants must remain offline, then change one fixture authority revision and predict whether release should be refused.

The retained quarantine observation file has SHA-256 `56b0287d87aa3f4b53328a854cff4c689a6400da545bcda8bd170af419bec624`. This is diagnosis of the initial safe refusal, not passing backup/restore acceptance.

The recorded backup result retains its MRR-r1 revision. The current MRR-r2
contract adds the separate legacy lexical repair; the backup requirements used
for this accepted run are unchanged.
