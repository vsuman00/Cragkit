# Migration and recovery

For example, reverting an application package does not remove a new database
column. Restoring yesterday's database can also bring back yesterday's access
grants. Treat package rollback, schema compatibility and security recovery as
separate decisions.

This guide covers the declared PostgreSQL schema/profile and the disposable
[MRR-r2 rehearsal](../contracts/RECOVERY_REHEARSAL_V6.md). The consuming
application owns backups, identity, deployment credentials and the release of a
recovered database. The library performs no migration or restore during import.

## Before an upgrade

Record the installed package hashes, database/schema versions, profile descriptor
and active generation. Keep the preceding artifact only if its schema support
and security status are known. Preserve immutable migration bytes and their
checksums; add a new migration rather than editing an applied file.

Use a dedicated operator credential and a verified backup/restore path. Keep
runtime roles restricted and provider keys in the consuming project's private
configuration. A password, connection URI or global roles/password dump does not
belong in Git, reports or command arguments. [PostgreSQL's pg_dump documentation](https://www.postgresql.org/docs/17/app-pgdump.html)
explains that a database dump excludes cluster-global roles. Record required
roles and reviewed policies separately without publishing credentials.

Use the existing explicit administrative checks with the selected private
scalar `PG*` environment and `PGSSLMODE=verify-full`:

```sh
python3 tools/check_postgres.py --check --confirm-dedicated-target
python3 tools/check_postgres_profiles.py --check --confirm-dedicated-target
```

The second command refuses when the optional third profile setup is pending;
that is not permission to suppress the error. Review the
[profile upgrade procedure](postgres-embedding-profiles.md) before choosing its
explicit apply command. Source fidelity and tenant restrictions still apply
when an upgrade or an older package fails admission.

## Interrupted upgrade

Keep request traffic stopped for an operator-directed incompatible change.
The existing runners bind checksummed DDL and ledger writes in one transaction.
An uncommitted failure must preserve the prior usable state. After an interrupted
operation, inspect the actual ledger and catalog, run the read-only check, and
resume only through the reviewed apply path. A lost acknowledgment after commit
is different: inspect durable state before deciding whether any retry is needed.
Never delete a new history row to make an older binary accept the database.

The rehearsal observes a native transaction before commit, terminates only its
owned backend, then checks data, generation pointers and history before explicit
recovery. Its result cannot establish crash recovery for every operating system,
storage device or hosted service.

## Legacy lexical configuration

The populated 0001-to-0002 rehearsal observed `simple` after the unchanged cast
to text. PostgreSQL resolves that name to `pg_catalog.simple`, but the native
reader contract requires the qualified spelling. Source bytes, active generation
and prior history timestamps were preserved; that alone does not prove the
upgraded rows are readable. [PostgreSQL documents](https://www.postgresql.org/docs/17/datatype-oid.html)
that OID alias types can display an unqualified name depending on the search path.

MRR-r2 requires a separately versioned operator repair of this derived field,
with explicit check/apply modes, writer exclusion, exact catalog checks and
before/after verification. It must record direct reader refusal before any
repair, preserve source/vector/security state, and prove successful reads
subsequently. The repair is still under local validation. Do not edit migration
0002, delete its history row or normalize fixture setup to hide this result.
The original paid CI evidence covers its frozen inputs; it does not validate
this new maintenance procedure.

## Restore into quarantine

1. Restore only a trusted, identified archive into a fresh isolated target. Verify
   its hash, tool versions, provenance and intended schema/profile. An archive can
   contain executable database definitions; do not restore unknown SQL as an
   administrator.
2. Close runtime connections and prevent application login before restoring.
   In the disposable same-cluster rehearsal, both fixture roles are `NOLOGIN`
   and PUBLIC database `CONNECT` is revoked. Existing sessions must also be gone;
   changing `LOGIN` alone does not end them.
3. Restore with bounded commands and explicit failure handling. The rehearsal
   uses a custom-format archive and `pg_restore --single-transaction
   --exit-on-error --no-owner` while preserving reviewed ACLs/policies. This is a
   same-cluster test with known roles. Cross-cluster ownership and role mapping
   need their own review. See the [PostgreSQL 17 restore reference](https://www.postgresql.org/docs/17/app-pgrestore.html).
4. Obtain current authoritative grants, authorization revisions and tombstones
   independently of the old content backup. Verify every restored identity and
   apply current security state transactionally before restoring application
   access. Cragkit authorization revisions are opaque; the rehearsal's integer
   ordering is a fixture convention, not a production identity rule.
5. If current authority is unavailable, incomplete or cannot be shown current,
   leave the target quarantined. Reapply current restricted role policies,
   validate the native runtime guards and test allowed and denied requests with
   the actual application roles before resuming traffic.

`--no-acl` is not a replacement for this security step: it changes restored
privileges and does not supply current document authorization. A restored backup
can contain a revoked grant or an old untombstoned row even when the data hashes
match perfectly. Old vectors never authorize source release.

## Package rollback

Use the compatibility result for the exact package and catalog. An older binary
may continue lexical reads but refuse the newer vector setup. Keep that refusal;
do not relabel real/fake vectors or lower the schema guard. Historical 0.0.0
products are tested only on disposable data. They lack the later reranker error
redaction correction and are not approved production rollback targets. No patched
predecessor has yet been declared eligible for rollback.

After a published bad artifact, prepare a corrective version and release notes.
Rebuilding different local bytes under the same published version does not
repair consumer installations. The [release guide](releasing.md) keeps registry
publication and deployment approval separate.

## Rehearsal evidence

The backup lane passed its scoped native rehearsal. Overall V6-07 acceptance
remains pending the upgrade lane and explicit legacy repair negative cases. The tracker records actual commands, source/artifact hashes, restoration
checks, resource observations and cleanup. No hosted target or model call is
required for this rehearsal. A small exercise: explain why a valid old backup
must still be denied release when its current authority snapshot is missing.
