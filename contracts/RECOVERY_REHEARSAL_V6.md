# Migration and recovery rehearsal (MRR-r2)

V6-07 exercises explicit operations on synthetic disposable PostgreSQL 17.11 /
pgvector 0.8.0 data. Library imports remain free of network, migration, backup and hosting effects.
Operators run these steps explicitly. Native Python and Node remain independent consumers. Existing migration
and setup bytes, profile identity and runtime authorization contracts are fixed.

## Upgrade lane

Apply the lexical migration sequence and fake-vector setup with the existing
checksummed administrative runners. Preserve canonical data, active generation,
prior ledger entries and timestamps. Exercise an interrupted transaction before
commit, observe its native rollback, then apply and read-only check the upgrade.
Profile setup 0003 remains additive; unknown history/checksum drift is refused,
never repaired by deleting a history row. A genuine backend termination before
commit must leave the earlier usable state and permit explicit recovery.

Record package downgrade compatibility separately. Use the retained V5 0.0.0
products only in isolated synthetic test environments, verify their recorded
hashes, and compare fake/lexical admission before and after the third setup step.
An older binary that cannot validate the new catalog must refuse it; do not
remove newer history or relabel vectors. A tested storage compatibility result
is not approval to deploy an older binary with a known security correction
missing. No rollback-eligible patched predecessor has been declared.

## Required legacy lexical repair

Native observation of a populated 0001-to-0002 upgrade retained `simple` in the
text column. It resolves to the same PostgreSQL configuration but does not match
the readers' required `pg_catalog.simple` spelling. Keep that direct outcome and
both native runtime refusals visible before repair. The earlier `to_regconfig`
observation failure was a harness defect, not proof of this compatibility issue.

V6-07F1 adds a separate explicit operator repair, never edits applied migration
0002, changes either history or weakens the library guard. Version and checksum
the maintenance artifact. Check mode reports `repair_required` without mutation;
apply mode changes only literal `simple` rows belonging to supported
`native_fts.v1` generations. Unknown configuration/profile, wrong target,
checksum/history/catalog/trigger drift or inconsistent stored vectors must refuse.

Hold the migration advisory lock and deterministic table locks excluding ordinary
writers in one bounded transaction. Validate exact expected history, target,
ownership, schema/RLS, column/default and complete affected trigger/function
identity before mutation. Under `search_path=pg_catalog`, verify alias equality
and that each affected vector already equals the canonical configuration applied
to the joined chunk bytes. Reject ambiguous/missing joins. Preserve source and
revision bytes, spans, identifiers, vectors, generations/active pointers, grants,
authorization revisions, tombstones, policies/ACLs and both histories/timestamps.
Compare keyed before/after state; only the declared config text may differ.
Bound snapshot rows/bytes explicitly and refuse larger unsupported work.

After repair, the same frozen package products must retrieve exact evidence in
both runtimes; current denial tests remain required. Exercise mixed/canonical
rows, idempotence, malformed target/catalog/history/trigger/profile/vector,
unavailable writer lock and native interruption before commit with explicit
recovery. A refusal must not mutate data. Record this as upgrade plus a required
operator repair, not an unmodified migration pass. The new operator tool has
separate local acceptance; the earlier paid CI result does not validate it.

## Backup and restore lane

Use pg_dump/pg_restore from the prepared PostgreSQL prefix, owner-only output and
scalar private libpq configuration. No passwords/connection URIs in argv,
reports or committed files. Back up synthetic source data before a committed
revocation and tombstone. Capture the later authoritative security state
separately from that old backup; it must cover all restored document identities.

Create a fresh database in the task-owned cluster. Close runtime connections,
make all fixture runtime roles NOLOGIN, and revoke PUBLIC database CONNECT before
restore. Verify quarantine with a real runtime connection refusal. Restore only
the known task-created archive, with checksummed identity, bounded commands,
--single-transaction and --exit-on-error. Preserve reviewed object ACL/policy
semantics in this same-cluster rehearsal; roles are global, not restored from the
single-database dump. No untrusted archive is accepted and no occupied database
is overwritten. Missing/mismatched backup or current security state must refuse
release, leaving the target quarantined.

Before restoring runtime access, reconcile current grants, authorization revisions
and tombstones from the later authority snapshot in a transaction. Never copy
old grants back as current authority. Check completeness, stable document identity
and nondecreasing authorization revision under this fixture's declared revision
format. Only then restore the explicit restricted role access and verify the
native guards. Both Python and Node must preserve allowed exact source retrieval,
deny revoked/foreign access and deny tombstoned source after the old data returns.
Immutable revision bytes, vector profile, active generation and migration/setup
checksums must agree with the declared recovery policy. Content recovery cannot
reverse deletion/security state; old vectors do not authorize source release.

This is an application recovery procedure rehearsal, not a new generic backup
service or production point-in-time recovery guarantee. A live operator needs a
current trusted authority/identity source; if unavailable, keep recovery offline.
Full cross-cluster/global-role/hosted restores require separate acceptance.

## Evidence and resource budget

Each lane owns separate tools/tests, uses one fixture/cluster at a time and fake
providers only, and emits fixed check identifiers/counts/hashes without secrets
or private source text. Root runs tests and languages serially, checks headroom,
and closes owned clients, servers, temporary credentials and listeners. Report
measured outcomes and unsupported modes. No new paid CI or provider run is
implied. Root integrates the two reports, edge case E58 and the operations guide
before marking V6-07 complete.
