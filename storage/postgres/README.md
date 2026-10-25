# PostgreSQL storage

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
| `chunk_lexical` | Full chunk key; text configuration name resolved as `regconfig` during vector maintenance, maintained `tsvector` and separate exact identifier tokens. |
| `document_grants` | Document key and grant; optional principal and authorization revision. Membership resolution belongs to the application. |
| `ingestion_jobs` | Tenant, collection and stable intent; scoped document/generation, payload digest, state, nonnegative safe attempt count and allowlisted error code. |

Identity values are nonblank strings of at most 256 UTF-8 bytes; collection IDs use the request contract's 128-byte bound. Blank checks trim ASCII space, tab, CR, LF, form feed and vertical tab. Accepted text is preserved rather than normalized. Identity domains use the deterministic `C` collation. IDs remain strings, including large numeric-looking IDs. Digests are lowercase SHA-256 hex strings; metadata must be a JSON object. Byte offsets and counters use nonnegative integers no larger than the shared maximum safe integer.

Canonical revision digests are checked against `convert_to(canonical_text, 'UTF8')`. Chunk offsets are zero-based, start-inclusive and end-exclusive. A trigger verifies that the referenced revision exists and the chunk equals its exact UTF-8 byte slice; length and digest constraints provide additional checks. The original source digest is recorded, but verifying that digest against an external immutable source remains later source-release work.

All revision updates are rejected, including locator or timestamp updates. Deletion remains available for explicit purge: clear active-generation and retained-job references before deleting a revision, or delete the owning document and its derived rows together. Scoped cascading foreign keys remove derived data. These are administrative capabilities, not an automatic retention policy. Deferred active-generation and parent/job references are checked at transaction completion or an explicit constraint check.

After `0002_portable_lexical_config.sql`, the lexical trigger computes `to_tsvector(language_config::regconfig, chunk.text)` from the referenced chunk on lexical insert/update, and refreshes it after a chunk text update. The search vector and exact identifier array have independent GIN indexes. Configuration names are stored as text to avoid the hosted upgrade limitation of stored `regconfig` OIDs. Names are validated by the explicit cast during lexical insert/update; changing a configuration rebuilds its vector. Three additional composite indexes cover parent-chunk, active-generation and ingestion-job foreign keys. This is native PostgreSQL FTS, not BM25. Declaring a generation `ready` or setting an active pointer does not itself validate expected counts or implement the later compare-and-swap publication protocol.

## Explicit connection and checks

Neon is the selected development host as of 22 October 2026. The user authorized a new dedicated Cragkit development project in VAIBHAV's Free organization, Singapore, PostgreSQL 17. Follow the [Neon runbook](../../docs/neon.md) and [migration plan](../../docs/neon-migration-plan.md); direct Neon native connection, security and integration acceptance passed; see [DB-NEON-01 evidence](../../evaluation/reports/V2/DB-NEON-01.md). Use the direct endpoint first and validate pooled operation separately. This hosting choice preserves portable PostgreSQL migrations and optional native drivers; optional vector storage, generation APIs, dense candidates and identifiers/fusion are described below; public hybrid orchestration remains V2-07.

Use an identified, dedicated nonproduction database with administrative migration credentials. The runner requires `--confirm-dedicated-target`; the flag records an operator acknowledgment, not independent proof that the target is safe. Hosted configuration uses scalar `PGHOST`, `PGDATABASE` and `PGUSER`, plus `PGSSLMODE=verify-full` and an existing `PGSSLROOTCERT` file. Keep passwords in protected libpq configuration or environment, never command arguments, reports or committed files. Service/host-address redirection and connection-string values are rejected.

Proposed commands from the project root, after configuring and verifying the target:

```sh
python3 tools/check_postgres.py --apply --confirm-dedicated-target
python3 tools/check_postgres.py --check --confirm-dedicated-target
python3 tools/check_postgres.py --check --confirm-dedicated-target --integration
```

The integration fixture takes the migration lock and exclusive application-table locks, requires empty application tables, inserts only synthetic data and rolls everything back. It exercises scoped foreign keys, immutable revisions, Unicode byte spans, identity bounds and transaction rollback. It does not delete preexisting data or establish runtime-role isolation. The runner suppresses raw database output and returns bounded, redacted status messages.

An explicitly selected task-owned Unix socket can support disposable local verification with `--local-socket /absolute/socket/directory`, matching `PGHOST`. Only this mode disables TLS; it cannot silently fall back to TCP. Existing PostgreSQL binaries may be used without installing tools. Local SQL, hosted Supabase and Neon results must be recorded separately in [development evidence](../../docs/development.md) and [the tracker](../../tasks/todo.md). The historical Supabase Cragkit target in Singapore passed hosted administrative migration and security probes; see [the Supabase hosted evidence](../../evaluation/reports/V1/V1-01-H-hosted.md). Authenticated native SQL passed over the direct endpoint with libpq `verify-full` and TLS 1.3, including migration history, integrity invariants and nonowner security probes.

## Access boundary and pending work

The migration creates objects in the private `cragkit` schema, revokes PUBLIC schema/table/domain privileges and function execution, and installs no public API grants. Row-level security is enabled with no policies, so ordinary nonowner roles have no allowed row access. Owners and bypass roles are different: successful administrative checks do not demonstrate least-privilege runtime behavior. Explicit role grants, scoped policies, pooled connection context and real runtime-role verification were exercised for Supabase in V1-02 through V1-10; those results do not establish Neon acceptance. For Neon, inspect effective memberships as well as direct role attributes and ownership, create runtime roles through SQL rather than inheriting Console/API role privileges, and verify allowed and denied access with the actual runtime roles. No application role or authentication mechanism is created here.

A failure case is using another tenant's revision ID while keeping the current tenant/document key: the composite constraint must reject it. Exercise: compare that full key with the active-generation pointer and explain why an ID alone cannot authorize a reference.

SQL API references: [PostgreSQL constraints](https://www.postgresql.org/docs/17/ddl-constraints.html), [privilege revocation](https://www.postgresql.org/docs/17/sql-revoke.html), [byte functions and SHA-256](https://www.postgresql.org/docs/current/functions-binarystring.html), and [text search types](https://www.postgresql.org/docs/17/datatype-textsearch.html). These references explain the APIs; actual compatibility and acceptance depend on recorded database runs.


## Optional vector capability: V2-04A

For example, `--check --vector` rejects a missing extension while a lexical-only session continues to use the existing two-entry migration history. Installing pgvector is an explicit administrative action; imports and runtime initialization do not install it.

[0001_pgvector.sql](setup/0001_pgvector.sql) is a separate numbered, exact-byte checksummed setup artifact. The runner uses the same advisory transaction lock as lexical migrations, bounded statements/locks and `cragkit_vector.setup_history(version, checksum, applied_at)`. It validates extension version `0.8.0`, private namespace, actual extension-owned base type and `vector_dims(vector)` signature, ledger identity and security. Failed setup rolls back the extension, schema, ledger and default-privilege changes. Reruns validate existing objects and preserve both ledgers' timestamps. Unmanaged or incompatible installations fail without dropping, relocating, upgrading or reinstalling them.

`--vector` inspects target identity and checks installed capability; `--install-vector` additionally requires `--apply`. Missing, unsupported and unavailable capabilities map to the administrative `VectorCompatibilityError` with redacted codes. Existing lexical APIs remain unchanged. The optional native PostgresVectorIndexer now performs equivalent read-only capability and effective-role checks before vector work, returning native typed errors. The administrative runner must never be imported into either library.

### Explicit Neon managed primitive profile

Strict mode rejects PUBLIC function/type privileges. On the accepted Neon development target, the extension and namespace belong to `cragkit_admin`, but Neon creates scalar primitive functions/types owned by `cloud_admin`. The installer cannot revoke those platform-owned privileges. `--allow-managed-vector-primitives` is a separate explicit option, valid only with vector check/setup. It accepts only the pinned extension's expected platform-owned members, prohibits SECURITY DEFINER functions and unexpected namespace objects, and preserves owner-only schema/ledger privileges, ledger RLS without policies, and checksummed history. It does not make platform administrators untrusted runtime users.

The setup revokes primitive privileges where the installer has effective ownership. For future installer-created objects, it removes PUBLIC defaults for tables, sequences, functions and types across this dedicated database. PostgreSQL cannot subtract global PUBLIC defaults using per-schema revocation. This changes future defaults for the installer across schemas; it does not modify existing application grants. The checker validates those defaults.

Managed scalar primitives retain PUBLIC execution/type privileges. Schema USAGE controls ordinary name lookup, not every possible primitive invocation or previously resolved plan. V2-04B/C/E reviewed runtime schema USAGE exposure for the restricted synthetic fixture: it exposes those scalar functions and cannot promise a per-function allowlist. Application table permissions, trusted scope and RLS remain the data boundary. No vector data table or runtime grant is created by A.

[Acceptance report](../../evaluation/reports/V2/V2-04A.md). PostgreSQL references: [extension ownership](https://www.postgresql.org/docs/17/sql-createextension.html), [privilege semantics](https://www.postgresql.org/docs/17/ddl-priv.html), [global versus per-schema defaults](https://www.postgresql.org/docs/17/sql-alterdefaultprivileges.html).

## Optional vector storage: V2-04B

For example, two vectors with 1536 components remain incompatible when one uses the synthetic profile and the other declares OpenAI. [0002_vector_profiles.sql](setup/0002_vector_profiles.sql) provisions only `fake_embedding_1536_v1`; it never labels synthetic data as hosted output. Its explicit administrative application uses the existing `cragkit_vector.setup_history` ledger after setup artifact `0001_pgvector`. The two lexical migration files and their history stay unchanged. This artifact installs no extension, role, grant or approximate index.

`cragkit.embedding_profiles` stores the exact E-r1 identity fields `profile_id`, `provider`, `model`, `dimensions`, `tokenizer` and `normalization`, plus the allowlisted `storage_table`. The first row is `fake_embedding_1536_v1`, `fake`, `fake_embedding_model_v1`, `1536`, `fake-byte-v1`, `l2`, `chunk_vectors_fake_1536`. A constraint binds that complete tuple; updates and deletes are rejected. The profile ID records the application revision. Equal dimensions alone cannot establish identity, and the accepted OpenAI model alias does not identify immutable provider weights. Additional profiles and physical tables require explicit provisioning through a new administrative artifact; native consumers must reject an unprovisioned profile.

`cragkit.chunk_vectors_fake_1536` has the full tenant, collection, document, revision, generation and chunk key, an `embedding_profile` fixed to the fake identity, and `embedding` of type `cragkit_vector.vector(1536)`. One foreign key binds the complete chunk key; another binds tenant, collection, document, revision, generation and embedding profile to the generation. A registry foreign key prevents detached profile references. The vector type rejects nonfinite components and wrong dimensions; a constraint requires `abs(vector_norm(embedding) - 1) <= 0.001`, matching E-r1. No normalization or truncation repairs malformed input.

Both tables enable RLS without policies and revoke PUBLIC table privileges. The profile trigger is an invoker function with a fixed `pg_catalog` search path and no PUBLIC execution grant. Installation does not grant runtime access. A later, explicit restricted-writer grant of `cragkit_vector` schema USAGE exposes the managed extension's retained PUBLIC scalar computational primitives under A-r2; it cannot promise a narrow per-function allowlist. Application table grants, scoped policies and trusted native authorization remain the data boundary. Runtime setup must validate that accepted capability and effective role privileges before vector work.

Inserting a vector changes neither readiness nor the active pointer. Native publication must validate the complete scoped manifest: matching expected chunk, lexical and vector counts, exactly one provisioned profile, canonical revisions and authorized, untombstoned documents. It then marks ready and compares the expected active generation in one short transaction. A failed or incomplete build preserves the prior pointer; revocations and tombstones remain effective. These orchestration checks belong to V2-04C-F, rather than the storage artifact. The rollback-only [vector probes](tests/vectors.sql) cover the storage constraints; integrated native and migration evidence is recorded separately in the [V2-04 acceptance report](../../evaluation/reports/V2/V2-04G.md).

Failure case: reusing a known chunk ID under another tenant fails the full foreign key even when its vector has the right length. Exercise: explain why a complete vector count still cannot authorize publication when the declared profile differs.


## Native generation APIs: V2-04C-G

Both optional PostgreSQL entry points export PostgresVectorIndexer. [VG-r1](../../contracts/VECTOR_GENERATIONS_V2.md) specifies exact identity, bounded staging/resume, manifest readiness, atomic expected-pointer publication, current authorization and source-release behavior. [Development commands](../../docs/development.md#v2-04-vector-publication-and-integrated-acceptance) run the two native suites and serial package checkpoint. No application policy or runtime grant is installed permanently; applications own those permissions. Vector writers must lack vector namespace/extension/type/function ownership and setup-ledger administrative authority. Only the synthetic profile is provisioned. Dense ranking is a separate task.


## Exact dense candidates: V2-05

The existing scoped read handle can select exact cosine-distance candidates from the provisioned synthetic profile table. [DN-r1](../../contracts/DENSE_V2.md) and the [canonical dense query](queries/dense_candidates.sql) define profile validation, lower-is-better distance, full scoped joins and required filters before ranking/limit. Active ready generations only; lexical-only reads need no vector capability. Source fetching keeps current authorization and exact immutable byte-span verification. No migration, new physical table, approximate index or permanent runtime grant is added. This internal adapter supports later fusion/orchestration; [acceptance evidence](../../evaluation/reports/V2/V2-05.md) separates fake geometry from native execution.

## Exact identifiers and fusion: V2-06

[IF-r1](../../contracts/IDENTIFIER_FUSION_V2.md) defines case-sensitive ASCII identifier extraction and the [canonical identifier query](queries/identifier_candidates.sql). Both native lexical and vector indexers now populate the existing `chunk_lexical.identifier_tokens` array. Historical immutable generations remain unchanged; a new ingestion intent is required to index old content. Exact containment and all trusted scope/grant/required-filter predicates precede LIMIT. Identifier reads need no vector capability and share the lexical/dense scoped snapshot; source release reauthorizes in a fresh transaction.

Pure weighted RRF combines ranks, preserves branch provenance, deduplicates votes, normalizes per-facet family weights and enforces a bounded union. No DDL, migration, setup artifact, permanent grant or model call is added. [Development commands](../../docs/development.md#v2-06-exact-identifiers-and-rank-fusion) and [acceptance report](../../evaluation/reports/V2/V2-06.md). Public orchestration remains V2-07.

## Hybrid orchestration: V2-07

[HY-r1](../../contracts/HYBRID_V2.md) adds opt-in dense/hybrid modes to both public native retrievers. Embedding runs before a lease; logical branches execute serially in one scoped repeatable-read snapshot. Each branch has a savepoint so configured recovery from a SQL failure preserves that snapshot and its filters. A broken savepoint, invalid scope, deadline, integrity error or source-release failure remains fatal. Only explicit hybrid recovery emits degraded execution and the degraded_search limitation.

V2-EXIT strengthens reader/writer runtime-role guards with the exact denylist `pg_read_all_data`, `pg_write_all_data`, `pg_read_server_files`, `pg_write_server_files`, `pg_execute_server_program` through the existing transitive MEMBER check. The base Node fixture no longer receives or opens administrator configuration; its parent uses the existing administrator connection for the negative guard check. No migration, setup artifact, permanent grant or dangerous-role assignment is added. [Evidence](../../evaluation/reports/V2/V2-07-08-exit.md).


## Deployment security gate

Migration checks alone are not deployment-security acceptance. Apply the explicit host hardening, then require [the security checkpoint](../../docs/development.md#security-remediation-checkpoint), including effective creator defaults, vector ACLs and setup-ledger RLS. The generic runner supports `--security --allow-test-writes`; managed primitive exceptions require an explicit flag. The native lexical fixture separately checks required FTS behavior before mutation because UTF8 encoding does not fix locale-dependent tokenization. See [the remediation ledger](../../evaluation/reports/SECURITY-REMEDIATION.md) for scoped evidence and historical findings.
