# PostgreSQL lexical storage

V1-01-r1 turns [architecture section 7](../../docs/architecture/ARCHITECTURE.md#7-storage-model-and-database-connection) into an explicit administrative migration. The native packages do not import this tooling or apply migrations. The schema stores canonical sources and lexical generations; it does not implement ingestion, retrieval, publication orchestration or a vector backend.

For example, a generation belonging to tenant B cannot become tenant A's active generation merely because its ID is known: the foreign key also includes tenant, collection and document identity.

## Migration contract

[0001_initial.sql](migrations/0001_initial.sql) is portable PostgreSQL DDL with no extension installation, transaction wrapper or migration-history writes. A UTF-8 database is required. The [explicit runner](../../tools/check_postgres.py) owns the transaction, bounded timeouts, advisory lock and `cragkit.migration_history(version, checksum, applied_at)` ledger. Migration versions are contiguous filename stems such as `0001_initial`; checksums cover the exact file bytes.

`--apply` checks the known history under the same transaction and lock used to apply missing migrations. An unchanged migration is skipped on a rerun. Changed checksums, unknown versions and history gaps are rejected. `--check` verifies that all known migrations are recorded without applying DDL. An unmanaged schema containing existing relations or functions is rejected before initial application. The runner never drops an existing schema. Once applied, preserve a migration's bytes and add a new numbered migration for changes.

## Storage relationships

The SQL file is the authoritative column and constraint definition. Every document-related reference carries tenant and collection identity as well as the relevant document, revision or generation key.

| Table | Key and purpose |
| --- | --- |
| `collections` | Tenant and collection; schema/profile declarations and object-valued policy metadata. |
| `documents` | Tenant, collection and document; active generation pointer, tombstone, object metadata and authorization revision. |
| `document_revisions` | Document key and revision; source locator/digest, immutable canonical text/digest and parser identity. |
| `index_generations` | Document key and generation; scoped revision, chunker/lexical profiles, optional embedding-profile declaration, staging/ready/failed state and expected count. |
| `chunks` | Full generation/revision key and chunk; scoped parent, ordinal, canonical byte span, exact text/digest and object metadata. |
| `chunk_lexical` | Full chunk key; explicit `regconfig`, maintained `tsvector` and separate exact identifier tokens. |
| `document_grants` | Document key and grant; optional principal and authorization revision. Membership resolution belongs to the application. |
| `ingestion_jobs` | Tenant, collection and stable intent; scoped document/generation, payload digest, state, nonnegative safe attempt count and allowlisted error code. |

Identity values are nonblank strings of at most 256 UTF-8 bytes; collection IDs use the request contract's 128-byte bound. Blank checks trim ASCII space, tab, CR, LF, form feed and vertical tab. Accepted text is preserved rather than normalized. Identity domains use the deterministic `C` collation. IDs remain strings, including large numeric-looking IDs. Digests are lowercase SHA-256 hex strings; metadata must be a JSON object. Byte offsets and counters use nonnegative integers no larger than the shared maximum safe integer.

Canonical revision digests are checked against `convert_to(canonical_text, 'UTF8')`. Chunk offsets are zero-based, start-inclusive and end-exclusive. A trigger verifies that the referenced revision exists and the chunk equals its exact UTF-8 byte slice; length and digest constraints provide additional checks. The original source digest is recorded, but verifying that digest against an external immutable source remains later source-release work.

All revision updates are rejected, including locator or timestamp updates. Deletion remains available for explicit purge: clear active-generation and retained-job references before deleting a revision, or delete the owning document and its derived rows together. Scoped cascading foreign keys remove derived data. These are administrative capabilities, not an automatic retention policy. Deferred active-generation and parent/job references are checked at transaction completion or an explicit constraint check.

The lexical trigger computes `to_tsvector(language_config, chunk.text)` from the referenced chunk on lexical insert/update, and refreshes it after a chunk text update. The search vector and exact identifier array have independent GIN indexes. This is native PostgreSQL FTS, not BM25. Declaring a generation `ready` or setting an active pointer does not itself validate expected counts or implement the later compare-and-swap publication protocol.

## Explicit connection and checks

Use an identified, dedicated nonproduction database with administrative migration credentials. The runner requires `--confirm-dedicated-target`; the flag records an operator acknowledgment, not independent proof that the target is safe. Hosted configuration uses scalar `PGHOST`, `PGDATABASE` and `PGUSER`, plus `PGSSLMODE=verify-full` and an existing `PGSSLROOTCERT` file. Keep passwords in protected libpq configuration or environment, never command arguments, reports or committed files. Service/host-address redirection and connection-string values are rejected.

Proposed commands from the project root, after configuring and verifying the target:

```sh
python3 tools/check_postgres.py --apply --confirm-dedicated-target
python3 tools/check_postgres.py --check --confirm-dedicated-target
python3 tools/check_postgres.py --check --confirm-dedicated-target --integration
```

The integration fixture takes the migration lock and exclusive application-table locks, requires empty application tables, inserts only synthetic data and rolls everything back. It exercises scoped foreign keys, immutable revisions, Unicode byte spans, identity bounds and transaction rollback. It does not delete preexisting data or establish runtime-role isolation. The runner suppresses raw database output and returns bounded, redacted status messages.

An explicitly selected task-owned Unix socket can support disposable local verification with `--local-socket /absolute/socket/directory`, matching `PGHOST`. Only this mode disables TLS; it cannot silently fall back to TCP. Existing PostgreSQL binaries may be used without installing tools. Local SQL results and hosted Supabase results must be recorded separately in [development evidence](../../docs/development.md) and [the tracker](../../tasks/todo.md). A dedicated Supabase target is still pending; local verification does not satisfy that hosted acceptance requirement.

## Access boundary and pending work

The migration creates objects in the private `cragkit` schema, revokes PUBLIC schema/table/domain privileges and function execution, and installs no public API grants. Row-level security is enabled with no policies, so ordinary nonowner roles have no allowed row access. Owners and bypass roles are different: successful administrative checks do not demonstrate least-privilege runtime behavior. Explicit role grants, scoped policies, pooled connection context and real runtime-role verification remain V1-02 through V1-10 work. No application role or authentication mechanism is created here.

A failure case is using another tenant's revision ID while keeping the current tenant/document key: the composite constraint must reject it. Exercise: compare that full key with the active-generation pointer and explain why an ID alone cannot authorize a reference.

SQL API references: [PostgreSQL constraints](https://www.postgresql.org/docs/17/ddl-constraints.html), [privilege revocation](https://www.postgresql.org/docs/17/sql-revoke.html), [byte functions and SHA-256](https://www.postgresql.org/docs/current/functions-binarystring.html), and [text search types](https://www.postgresql.org/docs/17/datatype-textsearch.html). These references explain the APIs; actual compatibility and acceptance depend on recorded database runs.
