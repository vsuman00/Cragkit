# Qdrant authoritative source reads

Revision `QS-r1`, the V5-03 source boundary. [QD-r1](QDRANT_V5.md) owns consistency and publication; [QC-r1](QDRANT_CANDIDATES_V5.md) owns vector nominations and full embedding profiles. The [source scenarios](fixtures/qdrant_sources.json) define shared reader assertions. [current maintenance roadmap](../docs/roadmap.md) distinguishes schema, native reader, cross-store integration and publication acceptance.

For example, a vector can still name `gen-1` after `gen-2` becomes active. A new source fetch rejects that nomination. A live request that verified and bound `gen-1` while it was active may resolve its retained bytes after fresh authorization, with `stale=true`.

## Optional authority and initialization

The reference authority is PostgreSQL 17 in the separate `cragkit_qdrant` schema, with its own migration history. It requires neither pgvector nor native FTS and does not alter the existing `cragkit` schema or its applied migrations. V5-03A provisions source content, manifest membership and SELECT policies only. No permanent application role, ingestion writer policy or implicit migration is created by a library import or constructor.

Native entry points expose `PostgresQdrantSourceStore(resource, config)` through Python `cragkit.qdrant_source` and Node `cragkit/qdrant-source`. `resource` is a borrowed native PostgreSQL pool; configuration is the exact five-field QC-r1 namespace/profile configuration. Initialization explicitly checks PostgreSQL/schema/history compatibility, required tables/constraints/read policies and a least-privilege runtime role. Reject owner, superuser, BYPASSRLS or incompatible privilege profiles before reading sources. Harmless reader-group membership is allowed; dangerous or owner membership and effective write privileges are rejected. Every leased source-read connection rechecks the reader role. The application separately grants the documented reader permissions; initialization does not repair privileges. Missing optional drivers or unsupported capabilities fail explicitly. Connections require the existing verified TLS or explicit local development profile.

Initialization compares the exact [catalog query](QDRANT_AUTHORITY_CATALOG_V5.sql) result with the [reference manifest](fixtures/qdrant_authority_catalog.json). Its server-side SHA-256 covers table and column definitions, domains, constraints, indexes, user triggers, policies, helper definitions and PUBLIC privileges. It excludes physical OIDs, owners, timestamps and named runtime grants, which are deployment-specific; role and effective privilege checks run separately. Both runtimes embed the same query and expected hash, without reading repository files at runtime. Policy, helper, constraint or PUBLIC privilege drift fails `UnsupportedCapability` even if the migration ledger still matches.

Reader grants comprise schema usage, SELECT on the four content tables and metadata-only `schema_migrations`, and EXECUTE on `scope_visible`, `scope_grants` and `valid_identity_array` with the signatures in the storage guide. The independent history stores `version`, `checksum_sha256` and `applied_at`; an explicit administrator wrapper records the checksum of the actual migration bytes. Source initialization never silently adopts an unknown namespace/history or writes this ledger.

### C2-r1: Explicit publication-schema compatibility

The source-only catalog above remains an accepted independent profile. The additive publication profile has its own [captured catalog](fixtures/qdrant_publication_catalog.json), using the unchanged complete catalog query. Runtime code embeds both profiles; it does not load repository files. Both exact history and fingerprint must match the same profile:

| Profile | Exact history | Catalog SHA-256 |
| --- | --- | --- |
| Source-only | `0001_authority` with its existing exact checksum | `8104abeef00594e7bfa4b533a139767599b56b87d09062c0d6f52f6e2f5d0b48` |
| Publication | The same `0001_authority`, followed by `0002_publication` with checksum `386fe01d0d03e35ac35c21bce598b21bff2c5ad510e9cdf0a6fbe56f359b6661` | `e395925257def30b9d143b7210c68583d4cbbb0950d8a8e1bb4f5aba5b8be69b` |

Read at most three ordered history rows so an unexpected third entry cannot be mistaken for the accepted two-row profile. Choose a known profile before its structural and fingerprint checks. Preserve the original source-only structural check; the new structural check must require PostgreSQL 17/UTF-8, thirteen ordinary tables, all twelve content/operational tables forcing RLS, validated constraints and no security-definer functions. The complete fingerprint binds every remaining catalog detail. Unknown or mixed pairs, drift and extra history fail `UnsupportedCapability`; no wildcard or migration-prefix acceptance is allowed.

Source readers still require SELECT on exactly the original five tables. They must have no table/column SELECT on new operational tables, no DML on any authority table, and no ownership/admin/bypass or writer/supervisor capability membership, even when inheritance is disabled. Only the three existing scope helpers are executable reader helpers. Recheck effective role permissions on every source-read lease. Granting writer capability later must fail `UnauthorizedScope` before source release. These checks never install privileges or migrate data.

This adds reader compatibility only. A valid publication schema does not prove that a native manager, supervisor or Qdrant publication protocol has run. Read-only repeatable-read source transactions remain separate from managed writes' READ COMMITTED requirement.

The authority owns current document grants, authorization revision, metadata, tombstone and active generation; immutable canonical revision bytes and locator; parser/chunker identity; and complete scoped generation/member identities and profiles. Qdrant payloads cannot replace these values. An administrative setup can populate this foundation for acceptance, but cannot establish QD-r1 writer compatibility.

`capabilities()` must report `source_authority=true`, `candidate_replica_only=false` for this source component, and `qd_r1_compatible=false`, `publication=false`, `repair=false`. The complete combined Qdrant profile remains incompatible with full QD-r1 until V5-04 implements and validates the ownership registry, durable intent/dispatch journal, enforceable mutation coordination, uncertain-operation recovery and atomic publication CAS. A lease, advisory lock or caller-supplied `drained=true` does not fence an already dispatched Qdrant request.

## Request handle and release gates

The native APIs are as follows. Python `initialize`, `open_request`, `fetch_candidate` and `release` take the named options as keyword-only arguments; Node takes one options object after the request, nomination or binding argument. Initialization, fetch, release and close are asynchronous. Opening a request handle is synchronous.

```text
await store.initialize(deadline, signal?)
handle = store.open_request(request, scope, deadline, signal?)
await handle.fetch_candidate(nomination, max_source_bytes, include_source=false)
await handle.release(binding, purpose, max_source_bytes, include_source=false)
await handle.close()
await store.close()
```

`open_request` performs no I/O. It snapshots and validates the request, trusted scope, supported required filters and finite safe monotonic deadline before any await. Scope comes from trusted application code, outside query input. The effective deadline is the minimum of the supplied original request deadline and request duration measured from entry. A consuming coordinator passes its already bounded execution-ledger deadline; source reads never reserve the same candidate slots again or infer model calls, tokens or cost.

One store admits at most one live request handle, with one source operation in flight and no waiting queue. A second handle or concurrent operation fails `ProviderUnavailable`. Closed or expired handles fail the existing typed guard appropriate to the condition. Each operation borrows a connection for a fresh short read transaction, installs transaction-local scope and releases the connection after verified cleanup. It holds no transaction across reranking, provider calls or application work. It neither closes borrowed pools nor creates a persistent service.

`fetch_candidate` accepts a revalidated QC-r1 nomination, including all immutable physical/scoped identities and profile descriptors. Revalidate structure and immutable binding; do not reuse replicated ACL/filter selection as source authority. Foreign tenant or logical collection fails `UnauthorizedScope` before SQL; malformed nominations, text/locator injection, unknown fields or invalid options fail `InvalidRequest`. Structurally valid namespace/profile contradictions with trusted configuration fail `IntegrityViolation` before SQL. Only an authoritative active, published generation can issue a binding for a new search. Missing, denied, tombstoned, staging or superseded rows return the same unavailable state without revealing which condition occurred.

A verified fetch issues an opaque binding object stored in a private registry belonging to that handle. A public constructor, serialized identity, copied object, payload flag or caller assertion cannot issue a binding. The registry stores the original validated identity, profiles, spans/digests, parser/chunker IDs, locator and evidence identity; mutable ACL/filter replicas do not authorize reuse. At most 64 bindings may be issued per handle. The handle and all bindings expire at the original request deadline or explicit close. No raw historical tuple resolution API is introduced.

`release` accepts only a binding issued by the same live handle. It rereads authority in a new transaction and verifies current grants, authorization revision, required metadata, tombstone, retained revision/member identity and bytes. A previously bound generation may be retained after another generation becomes active only when its authority still records `ever_published=true`; return its exact original revision and set `stale=true`. Never relabel it as the new active generation. Unpublished or mixed-revision content cannot become eligible through a forged binding.

`purpose` is `provider` or `final`. Each binding permits at most one release per purpose, with at most two release attempts total; a failed attempt still consumes its slot. A final release may occur without a provider release. A provider release after final release is invalid. Together with at most 64 fetch attempts, this bounds source operations to 192 per handle. Repeated fetches consume fetch slots even when no binding is issued. Bound exhaustion returns `budget_exhausted` without another SQL read; invalid/forged/cross-handle/replayed release inputs fail `InvalidRequest` before SQL.

Fetched evidence is a private verified view until the appropriate release gate. The caller invokes provider release immediately before external text disclosure, with no intervening await, and separately satisfies its provider disclosure policy. It invokes final release immediately before final packing/release. The source adapter does not select or call providers. A later revocation cannot retract bytes already lawfully delivered. A denied final release discards the source; it does not claim that an earlier authorized provider delivery never happened.

## Canonical row and byte verification

SQL returns at most one named row per exact member. Duplicate rows, excess results or contradictory values are `IntegrityViolation`. Row fields are exactly:

| Fields | Source and rules |
| --- | --- |
| `backend_namespace`, `physical_collection`, `collection_incarnation` | Generation authority; exact trusted physical identity. |
| `point_id` | Immutable member UUID selected as canonical lowercase text, recomputed from the full QC-r1 identity and compared with the nomination/binding; not a substitute for V5-04 atomic ownership reservations. |
| `tenant_id`, `collection`, `document_id`, `revision_id`, `generation_id`, `chunk_id` | Fully scoped revision/generation/member keys, with logical collection at most 128 UTF-8 bytes and other identities following existing wire limits. |
| `start_byte`, `end_byte`, `source_sha256`, `text_sha256` | Immutable member/source identity; safe integers and lowercase SHA-256 digests. |
| `dense_profile_id`, `sparse_profile_id`, `dense_profile`, `sparse_profile` | Full generation profile binding, matching trusted configuration and nomination. E-r1 OpenAI supports dense-only; absent sparse is null plus empty ID. |
| `authorization_revision`, `mutation_epoch`, `principal_ids`, `grant_ids`, `language`, `kind`, `tag`, `tombstoned`, `active_generation_id` | Current document authority. Mutation epoch is a nonnegative safe integer; security/metadata changes advance it and change authorization revision. It cannot fence an in-flight Qdrant request. Nullable SQL metadata means absent and never matches string equality/membership. ACL arrays have at most 64 identities each. |
| `parser_id`, `chunker_profile`, `source_locator` | Immutable revision/generation provenance. Parser/chunker IDs are authority-owned because QC-r1 nominations do not carry them. Locator is a nonblank, NUL-free existing identity of at most 256 UTF-8 bytes, opaque and never opened. |
| `generation_published`, `generation_ever_published` | Publication facts from authority; new fetch requires active and published, retained binding release requires ever published. |
| `source_bytes`, `canonical_utf8`, `excerpt_bytes`, `excerpt_utf8` | Safe byte counts and native byte buffers; SQL returns null byte columns when admission denies loading them. Fixture encoding objects are expanded before native assertions. |

Every SQL join uses complete composite identities. SELECT policies enforce current tenant/collection, principal-or-grant access, matching trusted authorization revision and no tombstone. Related-row policies additionally hide never-published generations, their members and revisions without any published generation. Required metadata and new-search active/published checks remain explicit query predicates; active-only RLS would incorrectly prevent the separate retained-binding path. Invalid/missing transaction-local scope defaults to denial. Replica scope/filter fields never broaden the authoritative query.

The five required transaction-local settings are `cragkit_qdrant.tenant_id`, `.collection`, `.principal_id`, `.grant_ids` and `.authorization_revision`. Grant IDs are a JSON array of at most 64 valid identities, with an encoded setting ceiling of 131,072 bytes to allow JSON escaping. Set them through parameterized `set_config(..., true)` in the fresh transaction, including explicit `[]` for no grants. The consuming application authenticates and binds this context; RLS cannot authenticate a setting that the application lets an attacker forge.

Native PostgreSQL integer columns may arrive as canonical unsigned decimal strings from a driver. Accept only `0` or `[1-9][0-9]*` within the safe integer range for these row columns, then normalize exactly. This exception does not permit numeric strings in nomination input, profile JSON or trusted request options. Boolean flags remain actual booleans.

Before source bytes leave the authority boundary:

1. Compare the complete row tuple, named profile descriptors/IDs, member span and digests with the validated nomination or private binding. Recompute and compare the QC-r1 point ID. Compare immutable parser/chunker identity and locator with an existing binding on release. Do not require mutable replicas to equal current ACL/metadata/authorization revision; enforce current authority against trusted scope instead.
2. Check byte counts before materializing source data: canonical source is nonempty and at most 16,777,216 bytes; excerpt is nonempty and at most 32,768 bytes. Require `0 <= start_byte < end_byte <= source_bytes` and `end_byte-start_byte == excerpt_bytes`. Numeric integers follow existing safe semantic JSON rules without boolean coercion.
3. Strictly decode the entire canonical byte buffer as UTF-8, including bytes outside the excerpt. Preserve exact bytes, embedded NUL, line endings and Unicode; do not normalize, trim or replace invalid sequences. A valid digest of invalid UTF-8 is still corruption. PostgreSQL `bytea` constraints enforce size/digest/immutability and exact member slicing; native validation supplies whole-source UTF-8 validation. V5-04 must validate before staging.
4. Hash canonical bytes and compare both authority and nomination/binding source digests. Slice the canonical bytes at the exact offsets, strictly decode that slice, compare its exact bytes to `excerpt_utf8`, and hash it against `text_sha256`. Mid-scalar boundaries, bad digests, wrong excerpts and same-dimensional wrong profiles are `IntegrityViolation`.
5. Construct the unchanged immutable wire Evidence. Its ID remains SHA-256 of compact UTF-8 JSON `['cragkit.evidence.v1',tenant,collection,document,revision,chunk,String(start),String(end),text_sha256]`, with no Unicode normalization. The evidence uses the authoritative revision locator, canonical source digest and exact excerpt text. Source fidelity establishes neither relevance nor source truth.

## Results, bounds and failures

Each operation returns an immutable source fetch with `state` (`verified`, `unavailable`, `budget_exhausted`), `evidence` or null, `binding` or null, canonical `source_bytes` actually loaded for that operation, `stale`, and `private_source` or null. A verified fetch/release returns the corresponding binding; unavailable/budget-exhausted operations return no evidence, binding or private source. No operation infers sufficient coverage or the execution state of a complete retrieval.

The cumulative canonical source-read ceiling is 16,777,216 bytes per handle across fetches and both release gates, including repeated reads of the same revision. Excerpt bytes derived from that canonical read do not add another canonical-byte charge. `max_source_bytes` is a nonnegative safe integer no greater than that ceiling and is intersected with the handle's remaining allowance. SQL returns metadata/counts first and conditionally loads bytes only when the source fits. A valid source above the remaining allowance returns `budget_exhausted`, zero loaded bytes and no binding. A source above the absolute size bound is corruption, not ordinary budget exhaustion.

`include_source` is a strictly validated explicit boolean, false by default. When true after successful verification, `private_source` contains the immutable object `{canonical_text, source_sha256}` for trusted packing verification. It is not wire Evidence, public context, telemetry or an error field and must be excluded from application serialization. Always drop temporary raw driver buffers after verification. Do not follow a locator from either authority or payload.

Driver/connection/source-authority outages raise redacted `ProviderUnavailable`; shared timeout raises `DeadlineExceeded`, and caller cancellation propagates natively. They never become an ordinary missing-evidence result. Driver rows remain untrusted even when SQL constraints exist. Close is idempotent, rejects new work, invalidates all bindings and bounds cancellation/draining and cleanup; do not return an unclean connection to a pool. No automatic reconnect, retry, filter removal or scope broadening is introduced.

Missing SQL tables, columns, functions or namespace fail `UnsupportedCapability`. A server cancellation (`57014`) becomes `DeadlineExceeded` only after the shared deadline has elapsed; an earlier operational cancellation is `ProviderUnavailable`. Native caller cancellation remains native. A request handle may move between application tasks; ownership means the same private handle and store, with concurrent operations rejected. A store that has not initialized fails `IndexNotReady`.

V5-03B/C implement these native boundaries; V5-03D/C1 acceptance (record retained in the private maintainer archive) records real local PostgreSQL/Qdrant stale-vector revocation, provider-spy and final-release checks. Existing CorrectiveRetriever private candidates and its outer candidate reservation remain a V5-07 integration dependency: do not duplicate QC-r1's reservation or reinterpret cosine similarity as cosine distance to force compatibility.

One failure to inspect: publishing a new generation between fetch and final release may legitimately produce stale retained evidence, but a copied old nomination cannot manufacture the private binding needed for that path. Practice unassessed: explain why fresh grants and an opaque request binding answer different questions.
