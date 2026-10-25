# Optional Qdrant source authority storage

V5-03A supplies the separate PostgreSQL 17 namespace `cragkit_qdrant`. It stores authoritative source bytes and current authorization for the [source contract](../../../contracts/QDRANT_SOURCES_V5.md). This foundation does not implement the [QD-r1](../../../contracts/QDRANT_V5.md) intent registry, physical ownership reservation, mutation coordinator, publication CAS or repair protocol. It cannot by itself claim QD-r1 compatibility.

For example, an old Qdrant payload can still contain a revoked grant. The source reader must use current document authorization in this schema before returning any excerpt; a matching vector payload does not authorize it.

## Explicit migration and ownership

The administrator applies [0001_authority.sql](migrations/0001_authority.sql) explicitly, inside a transaction, with an external wrapper that computes the SHA-256 of the exact migration bytes. That same transaction records the actual version and checksum in `cragkit_qdrant.schema_migrations`. The SQL contains no self-checksum constant or automatic migration entry. The wrapper must verify the expected independent history before reuse and reject an unknown namespace or checksum; an existing namespace is never silently adopted. No import or source read runs this file.

The migration requires a UTF-8 PostgreSQL 17 database. It creates no extension, role, credential, pgvector object or FTS object. It does not read or alter the existing `cragkit` schema, its migration history or optional vector profiles. Root acceptance applies the new DDL and synthetic seed data in one transaction that is rolled back, refusing a preexisting authority namespace.

The namespace, tables and functions deny `PUBLIC` privileges. The administrator must separately grant a dedicated reader schema usage, SELECT on the four content tables plus the metadata-only `schema_migrations` history and EXECUTE on the three scope helpers: `scope_visible(text,text,text[],text[],text,boolean)`, `scope_grants()` and `valid_identity_array(text[])`. Runtime readers must be nonowners without superuser or `BYPASSRLS` privileges, membership or an administrative connection fallback. All four content tables enable and force RLS. See the [PostgreSQL 17 row-security rules](https://www.postgresql.org/docs/17/ddl-rowsecurity.html) for owner and BYPASSRLS semantics. This slice adds only SELECT policies; it provides no runtime writer privileges or writer policies. Privileged staging in acceptance is administrative fixture setup.

## Rows and invariants

| Table | Authority and constraints |
| --- | --- |
| `documents` | Scoped document identity, current principal/grant arrays, authorization revision, mutation epoch, scalar metadata, tombstone and active generation pointer. Arrays contain at most 64 valid identities. Security or metadata changes require a different authorization revision and a strictly newer mutation epoch; the epoch cannot decrease. A tombstone cannot be cleared. |
| `document_revisions` | Immutable scoped revision, canonical bytes, exact source SHA-256, parser identity and opaque source locator. Locators follow the existing evidence identity limit of 256 UTF-8 bytes; readers never interpret or open them. |
| `generations` | Immutable revision/generation identity, physical backend/collection/incarnation, chunker identity, expected member count and full exact QC-r1 dense/sparse descriptors. Publication flags are separate; `ever_published` cannot be cleared. Real OpenAI identity requires a dense-only profile. |
| `members` | Immutable exact generation/chunk identity, UUIDv5-shaped point ID, half-open canonical byte span, source and excerpt SHA-256, and exact excerpt bytes. A trigger compares the source digest and the exact byte slice against the authoritative revision. New members cannot be inserted after the generation has been published. |

All composite relationships retain tenant, logical collection and document identity; revision membership also preserves revision and generation together. The active pointer has a deferred scoped foreign key. Revisions and members reject UPDATE, including attempts to rewrite digests alongside altered bytes. Generation updates cannot change physical identity, descriptors, revision, expected count or other immutable fields. SQL checks enforce the declared descriptor objects, including the distinction between an absent sparse descriptor and a nonempty sparse profile ID.

Canonical and excerpt storage uses `bytea`, bounded to 16 MiB per source and 32 KiB per excerpt, with no normalization or conversion through PostgreSQL `text`. NUL bytes therefore survive exactly. SQL verifies byte lengths, digests and byte-slice equality. It does not certify UTF-8 validity or code-point boundaries. The native source adapter must strictly decode the complete canonical bytes and selected excerpt and verify their spans before any release. The V5-04 writer must validate canonical UTF-8 before staging. Malformed UTF-8 inserted directly by an administrator is integrity corruption, even if its stored digest and byte span match; it is never releasable evidence.

The UUID constraint checks UUIDv5 shape, not derivation or collision freedom. Native source verification recomputes QC-r1's complete tuple-derived ID. The V5-04 atomic physical ownership registry remains necessary before any point write. Likewise, the stored expected member count and publication flags do not prove a complete Qdrant generation. Only the later verified manifest and publication protocol can establish that boundary. Administrative generation flags in SQL fixtures are synthetic setup, not publication acceptance.

## Read scope and publication modes

A trusted application binds all five transaction-local settings before each read:

```text
cragkit_qdrant.tenant_id
cragkit_qdrant.collection
cragkit_qdrant.principal_id
cragkit_qdrant.grant_ids
cragkit_qdrant.authorization_revision
```

`grant_ids` is JSON text containing at most 64 identity strings, including `[]` when there are no grants. Its encoded setting is bounded to 131,072 bytes, allowing required JSON escaping within the wire identity limits. Missing or malformed scope cannot grant access. The document policy requires exact tenant, logical collection and authorization revision, a valid principal, no tombstone, and either principal membership or an intersecting grant. These settings are not authentication: an application that permits a caller to forge them defeats its own authority boundary. Use parameterized `set_config(..., true)` in a short explicit transaction; connection reuse must not inherit another request's scope.

Generation policies require an authorized document and `ever_published`. Revision and member policies require matching authorized previously published generations. This hides staged source rows while retaining the possibility of a separately authorized historical read. Policies do not require the active generation, because that would prevent legitimate resolution of a binding issued before a later publication.

Native read SQL must repeat the full trusted scope, current ACL, authorization revision, tombstone and required metadata predicates. For a new candidate, it additionally requires the document's active generation and `published = true`. Retained release requires the same request handle's previously issued opaque binding and `ever_published = true`; a caller-supplied historical tuple is insufficient. Verify every immutable row field, complete descriptor, point ID, source digest, byte span and excerpt digest again. Apply fresh authorization before provider disclosure and final release. Release database leases between operations; never hold one across a provider call.

The native query computes source/excerpt lengths first and gates returned byte columns against the remaining cumulative request allowance. It must not load unbounded bytes and only then announce budget exhaustion. An unavailable source authority is an operational failure, and a corrupt row is an integrity failure; neither becomes an empty successful search. The source contract owns exact row aliases, byte accounting and handle limits.

## Verification state

This document describes the schema and required reader behavior. Worker review alone does not establish PostgreSQL execution, RLS behavior, source-adapter acceptance or concurrency safety. Root records actual transactional constraint/RLS checks and rollback cleanup separately. V5-03B/C implement native readers; V5-03D verifies stale grants, provider disclosure and final release against the real backends. V5-04 adds the independently required writer/publication capabilities.

A useful failure case is a byte span beginning inside a multibyte character: SQL can prove that the excerpt matches those exact bytes, but the native strict decoder must reject it. As a small exercise, explain why a superseded generation can satisfy the historical policy while remaining ineligible for a new search.
