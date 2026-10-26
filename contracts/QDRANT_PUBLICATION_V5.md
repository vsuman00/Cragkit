# Qdrant publication and managed repair

Revision `QW-r1`, the V5-04 execution boundary. This extends [QD-r1](QDRANT_V5.md), [QC-r1](QDRANT_CANDIDATES_V5.md) and [QS-r1](QDRANT_SOURCES_V5.md). The [publication scenarios](fixtures/qdrant_publication.json) and [native fault matrix](../docs/qdrant-publication-acceptance.md) specify acceptance. [ADR 0004](../docs/decisions/0004-qdrant-managed-writes.md) records the restricted recovery profile.

For example, a writer can commit its dispatch record and pause before sending an upsert. A replacement cannot clear that record after a lease expires: the old writer might resume. Recovery must make its old credential unusable and finish replay of the stopped server's durable operations before a replacement writes.

## Status and supported boundary

V5-04A defines behavior; it does not implement or demonstrate publication. Dependent runtime, migration and native fault children must pass before a store advertises QD-r1 compatibility. The existing candidate and source stores retain their narrower capabilities.

The first write profile is one managed Qdrant 1.20.0 process, one durable storage directory, replication and write consistency one, server Cosine named `dense`, and optional explicit fake-profile named `sparse`. PostgreSQL 17 provides authority in the separate optional `cragkit_qdrant` schema. No pgvector, FTS, model invocation, remote model runtime or required Python service is introduced. Full QC-r1 configuration and E-r1 descriptor checks apply; real OpenAI vectors are supplied as already-computed bound E-r1 batches, dense-only.

All writers to this physical Qdrant instance participate in this protocol and use supervisor-issued immutable credential generations. Trusted out-of-band administrators are outside the concurrency model. An independently hosted endpoint, uncontrolled writer, unsupported server configuration or missing recovery controller fails `UnsupportedCapability`; configuration alone cannot assert safe write exclusion.

`optimizer_config.prevent_unoptimized` must be explicitly false and verified against the running supported configuration. A restart health response is insufficient. In pinned Qdrant 1.20.0, local shard loading calls WAL replay; the false configuration requires the full replay and synchronous flush path before load finishes. The true setting permits an asynchronous replay tail and is unsupported. Initialization and recovery verify the selected configuration and collection profile, then perform bounded exact readback before reopening writes. [Pinned shard loading and replay](https://github.com/qdrant/qdrant/blob/v1.20.0/lib/collection/src/shards/local_shard/mod.rs).

## Public manager boundary

Native Python and Node expose equivalent optional manager modules. Construction is `QdrantPublicationManager(authority, transport, config, supervisor, authorize_write)`. All dependencies are explicit and borrowed; the manager closes its own work and capabilities, never the caller's pool, transport or supervisor. Constructors and imports perform no I/O. The trusted QC-r1 five-field config is unchanged.

`initialize(deadline, cancellation)` explicitly checks authority history/catalog/role, Qdrant version/configuration, controller capability and durable instance identity. Operations before initialization fail `IndexNotReady`. There is one active operation per manager, no queue, one deadline inherited through every callback, SQL transaction, HTTP request, verification page and cleanup. A caller retry does not reset an existing request's budget or make an uncertain mutation disappear.

The public operations are:

| Operation | Immutable input and behavior |
| --- | --- |
| `stage(change, scope, ledger, deadline, cancellation)` | Validate and snapshot one complete source/generation/member/vector change; bind a stable intent and immutable manifest; stage authority and reserve all physical identities. No Qdrant mutation. |
| `publish(intent_id, scope, ledger, deadline, cancellation)` | Resolve the existing intent; acquire document ownership; dispatch complete point writes; verify exact completeness; atomically prepare/publish under the original expected fences. |
| `repair(intent_id, scope, ledger, deadline, cancellation)` | Resolve and reconcile the same durable operation. Never invent a replacement generation, broaden scope, refresh a stale worker's credential or silently rebase expected active. Unknown dispatch requires managed recovery. |
| `update_authorization(change, scope, ledger, deadline, cancellation)` | Commit the expected current ACL/metadata replacement and changed authorization revision/epoch first; queue exact current replica convergence as durable work. It may return authority committed with replica pending. |
| `tombstone(change, scope, ledger, deadline, cancellation)` | Atomically deny all source release and advance security fences first. Vector cleanup may remain pending. This operation never waits for Qdrant before authoritative denial. |
| `purge(intent_id, scope, ledger, deadline, cancellation)` | Resolve a tombstone-bound cleanup intent; settle all old writers, delete only globally claimed exact physical IDs, and verify scoped absence. Preserve required retained claims and the security tombstone. |

Every change contains a stable caller-supplied `intent_id`, full tenant/collection/document target, action kind and expected `authorization_revision`/`mutation_epoch`. Stage additionally binds `expected_active_generation_id` (including explicit null for first publication), immutable revision/generation IDs, canonical bytes/locator/parser, chunker identity, full profiles and every member/span/vector. Its required `initial_authorization` field is null for an existing document, or a complete trusted initial authorization/metadata value for creation. That initial value is bound to the stage intent, never inferred from source text. Creation must atomically require document absence or reconcile a document created by the identical recorded intent. A changed initial ACL is a changed intent payload, even though later current replicas remain mutable. A null initial value requires an existing document; stage never replaces its authorization. Missing versus null is validated explicitly; unknown fields are rejected.

The application binds the existing `authorize_write(scope, collection, document_id)` async callback outside agent-editable input. Its result must be an actual boolean. Pass a freshly validated trusted scope and the immutable scoped target, preserving the existing indexer callback signature. Call it before initial authority admission and again before each new external mutation and publication CAS. Await it outside an SQL transaction; the following transaction must compare the authority fences observed for that attempt. A true callback does not override RLS, a tombstone or a changed fence. False is `UnauthorizedScope`; malformed results are `InvalidRequest`; unknown callback failures are redacted `ProviderUnavailable`.

Stable intent lookup is fully scoped. Reusing an intent ID with a different action or immutable payload digest is `IntegrityViolation`; do not allocate another revision or silently adopt the new input. A matching completed retry resolves its durable outcome after fresh write authorization. A lost SQL acknowledgment is reconciled by reading that same identity, not by assuming rollback or issuing an alternate operation.

Results contain the scoped intent ID, operation, durable state, revision/generation identity where relevant, and explicit `authority_committed`, `replica_complete`, `published` and `purge_complete` booleans. An authority change with replica pending is not reported as a failed revocation or a completed replica mutation. Do not expose source bytes, keys, owner capabilities, raw SQL/HTTP bodies or exception text. These are write diagnostics, not retrieval coverage estimates.

## Immutable source, vector and manifest admission

Snapshot native inputs before the first await. Reject custom/proxy/accessor containers at the runtime boundary; freeze nested models after validation. Preserve canonical UTF-8 bytes, including BOM, CRLF and NUL. Strict-decode the complete source, enforce its SHA-256, and verify every exact nonempty UTF-8 excerpt at its byte span before staging. QS-r1 source, locator, identity and profile limits remain in force.

An immutable generation has 1 to 64 members, with unique chunk IDs and QC-r1 UUIDs. Every member names the same fully scoped revision/generation, profiles and physical incarnation. Input vectors must be finite, correctly dimensioned and valid under their declared profile; matching dimensions alone never establish identity. Sparse indices are sorted unique uint32, at most 16, with positive finite float32-representable values. No automatic sparse encoder, BM25, provider call or normalization hidden behind a profile ID is permitted.

### B1: float32 codec and seal

Internal pure helpers are `encode_dense(vector, profile)`, `encode_sparse(indices, values, profile)`, `verify_dense_readback(expected, observed)` and `verify_sparse_readback(expected, observed_indices, observed_values)`. Encoders return immutable canonical components, sealed bytes and `input_sha256`; verifiers return no value on success and raise `IntegrityViolation` on failure. They perform no I/O, provider work, ledger mutation or public package export. The manager's manifest admission decides whether an original real-profile input is a correctly bound E-r1 batch; the codec does not turn raw real arrays into a public ingestion route.

Expected codec objects have private process-local provenance. Deserializing their fields does not recreate that provenance. Durable intents must preserve the original admitted numeric inputs together with their canonical seals; B2 freezes their portable replay serialization. After restart, revalidate and encode the original input, then compare the recorded canonical seal before using the newly issued expected object. Do not re-admit only the rounded values: an accepted original component such as `1.00099999` can round beyond the original E-r1 norm boundary. This rule does not add a public restore bypass.

First validate the ORIGINAL dense input using existing full E-r1 profile, dimension, finite-number and norm rules (including 0.001 tolerance). Validate original sparse input using the exact QC-r1 fake sparse profile. Reject booleans, numeric strings and malformed containers. Round each component once to IEEE-754 binary32, nearest with ties to even. Reject conversion overflow/nonfinite output and a nonzero original value that rounds to zero. Preserve representable subnormals; canonicalize either signed zero to positive zero. Do not perform another 0.001 norm check after rounding or silently change E-r1 adapters.

At this native codec boundary, dimensions and sparse indices use semantic integer values: finite integral Python floats and integers have the same meaning as an integral Node number within the declared range. Booleans are rejected. Canonical indices are unsigned integers, including positive zero. This does not change the protected QC-r1 search-input parser.

`U32(n)` is exactly four unsigned little-endian bytes. `F32(x)` is exactly four binary32 little-endian bytes after the conversion above. `FRAME(b)` is `U32(len(b)) || b`; lengths count bytes. `UTF8(s)` is strict UTF-8 without BOM or normalization. `||` means byte concatenation. Names are exactly ASCII `dense` and `sparse`.

The exact dense profile field order is `profile_id`, `provider`, `model`, `dimensions`, `tokenizer`, `normalization`. The exact sparse order is `profile_id`, `encoder`, `model`, `revision`, `vocabulary`, `preprocessing`, `weighting`, `corpus_statistics_revision`. No extra fields are admitted. Encode each profile value as its existing string, except dimensions as canonical unsigned decimal ASCII. `PROFILE(p)` is `U32(field_count)` followed in that order by `FRAME(UTF8(key)) || FRAME(UTF8(value))` for every field.

The dense seal bytes are exactly:

```text
ASCII("cragkit.qdrant.vector.v1") || 00
|| FRAME(ASCII("dense")) || FRAME(ASCII("dense"))
|| PROFILE(dense_profile) || U32(dimensions)
|| F32(x[0]) || ... || F32(x[dimensions-1])
```

The sparse seal bytes are exactly:

```text
ASCII("cragkit.qdrant.vector.v1") || 00
|| FRAME(ASCII("sparse")) || FRAME(ASCII("sparse"))
|| PROFILE(sparse_profile) || U32(nonzero_count)
|| U32(index[0]) || ... || U32(index[nonzero_count-1])
|| F32(value[0]) || ... || F32(value[nonzero_count-1])
```

The two framed strings distinguish vector kind and physical vector name, even though they match in this reference profile. `input_sha256` is lowercase SHA-256 of these complete bytes. It binds the canonical submitted content, including full profile and named branch. It is not a hash of arbitrary JSON or a promise that Cosine stores those same bytes. Absent sparse has no seal, represented as null in manifests; do not hash an invented empty sparse vector. Bound each profile string before copying/encoding to at most 1,024 characters and 1,024 UTF-8 bytes, and keys to 256 characters/bytes. The supported full descriptors are much smaller. Dense dimensions are exactly 1,536; sparse has 1 to 16 entries with sorted unique uint32 indices and positive float32 values.

For dense readback let `x` be canonical submitted binary32 components converted exactly to binary64. Compute `s` with an explicit loop initialized to positive binary64 zero, performing `s += x[i]*x[i]` in ascending component order, then `u[i] = x[i]/sqrt(s)`. Do not use Python built-in `sum`, `math.fsum`, SIMD, dot-product helpers or reassociation. Canonicalize observed components to binary32 with the same finite/underflow/zero rules, producing `y`. Require the exact dimension and name; then require all three bounds with fixed `T = 0.0002 - 0.000000000002`:

```text
for every i: abs(y[i] - u[i]) <= T*abs(u[i]) + 2**(-126)
abs(sqrt(ascending_binary64_sum(y[i]*y[i])) - 1) <= T
sqrt(ascending_binary64_sum((y[i]-u[i])*(y[i]-u[i]))) <= T
```

Every sum above uses the same explicit index-ordered binary64 loop. The fixed guard is part of the rule; implementations must not loosen it. This intentionally admits only a bounded equivalence class around normalized expected content, rather than exact dense stored-bit identity. Differences inside that class are accepted; wrong vectors outside it fail, even at matching dimensions/profile. The component bound prevents a norm-only substitute. Signed zero is semantically canonical. Sparse readback requires identical sorted indices and exact canonical float32 value bits. Malformed input is `InvalidRequest`, an input full-profile contradiction is `EmbeddingProfileMismatch`, and any malformed/mismatching readback is `IntegrityViolation`.

### B2: manifest and intent seals

`J(value)` is compact UTF-8 JSON with no insignificant whitespace, literal valid Unicode (no ASCII-only escaping), ordinary JSON escaping for controls/quotes/backslashes, and no Unicode normalization. Only arrays, strings and explicit null occur, so object key ordering and floating JSON never participate. All decimal strings are `0` or `[1-9][0-9]*`, within the existing safe integer range. Full profiles become ordered arrays of `[key,string_value]` pairs in the B1 order. IDs follow QC/QS bounds. Byte ordering means unsigned UTF-8 byte lexicographic order, never locale sorting.

`member_tuple` has this exact positional order:

```text
[qc_identity_tuple, point_id, start_byte_decimal, end_byte_decimal,
 text_sha256, dense_input_sha256, sparse_input_sha256_or_null]
```

The manifest digest is SHA-256 of `J` applied to this exact ordered array:

```text
["cragkit.qdrant.manifest.v1",
 backend_namespace, physical_collection, collection_incarnation,
 tenant_id, collection, document_id, revision_id, generation_id,
 source_sha256, source_bytes_decimal, source_locator, parser_id, chunker_profile,
 dense_profile_pairs, sparse_profile_pairs_or_null,
 member_count_decimal, [member_tuple, ...]]
```

Sort members by chunk-ID UTF-8 bytes, reject duplicate chunk IDs or physical IDs, and recompute every QC-r1 UUID rather than trusting an input UUID. Every nested QC identity tuple carries the same full generation/source identity and exact dense/sparse profile IDs. Sparse absence is the QC empty profile ID plus null descriptor/seal. Hash source bytes and excerpt bytes directly; they are not embedded in the manifest JSON. Maximum manifest encoding is 1,048,576 bytes; reject before retaining an oversized snapshot.

The stage intent payload digest is SHA-256 of `J` applied to:

```text
["cragkit.qdrant.intent.v1", "stage", intent_id,
 tenant_id, collection, document_id, manifest_sha256,
 expected_active_generation_id_or_null,
 expected_authorization_revision, expected_mutation_epoch_decimal,
 initial_authorization_or_null]
```

For creation, `initial_authorization` is the ordered array `[authorization_revision, sorted_unique_principal_ids, sorted_unique_grant_ids, language_or_null, kind_or_null, tag_or_null, "false"]`. Sort ACL IDs by UTF-8 bytes. Its authorization revision must equal the expected initial revision, with the initial mutation epoch fixed to one. Existing-document staging uses null. The creation binding is retained with the intent and cannot overwrite later authoritative security changes during replay. It is excluded from the immutable generation manifest, which also remains unchanged by later ACL updates.

`publish` and `repair` reference that exact stage intent and its original fences; they do not hash a new stage action or silently rebase it. The exact security-change intent array is:

```text
["cragkit.qdrant.intent.v1", action, intent_id,
 tenant_id, collection, document_id,
 expected_authorization_revision, expected_mutation_epoch_decimal,
 [new_authorization_revision, sorted_unique_principal_ids, sorted_unique_grant_ids,
  language_or_null, kind_or_null, tag_or_null, tombstoned_string]]
```

`action` is `"update_authorization"` or `"tombstone"`. Sort/deduplicate each ACL array by UTF-8 bytes. The last string is exactly `"true"` or `"false"`; tombstone requires `"true"`, and authorization update cannot clear an existing tombstone. The exact purge intent array is:

```text
["cragkit.qdrant.intent.v1", "purge", intent_id,
 tenant_id, collection, document_id, tombstone_intent_payload_sha256,
 expected_authorization_revision, expected_mutation_epoch_decimal]
```

These operation digests are SHA-256 of `J(array)`. B2 must consume the shared ordered fixture rather than a generic object serializer.

### B2 native helpers and durable original vectors

The following internal pure helpers perform no I/O, model work, ledger mutation or public package export. Their immutable JSON result has `value` (the ordered nested array), `encoded_bytes` and lowercase `sha256`. Python uses nested tuples and bytes; Node uses frozen arrays, including byte arrays. These records identify content; they are not authorization, verified-vector or publication capabilities.

`encode_manifest(record, canonical_text)` accepts exactly these record keys: `backend_namespace`, `physical_collection`, `collection_incarnation`, `tenant_id`, `collection`, `document_id`, `revision_id`, `generation_id`, `source_sha256`, `source_bytes`, `source_locator`, `parser_id`, `chunker_profile`, `dense_profile`, `sparse_profile`, `members`. Each member has exactly `chunk_id`, `point_id`, `start_byte`, `end_byte`, `text_sha256`, `dense_input_sha256`, `sparse_input_sha256`. Derive each complete QC tuple from its shared record and chunk; validate the supplied UUID against the derivation. The full profiles follow supported QC configuration rules. Sparse absence requires a null descriptor and null member sparse seal.

`canonical_text` is a native string, not a byte buffer or locator. Strict UTF-8 encoding preserves BOM, CRLF, NUL and every code point without normalization. Reject surrogates. Preflight both character and byte ceilings before a complete encoded copy, using bounded chunks where necessary. Require 1 to 16,777,216 source bytes, exact source digest/count, 1 to 64 members, unique chunk IDs/UUIDs, safe integral nonboolean offsets, nonempty spans inside the source and at most 32,768 excerpt bytes. Strictly decode each exact slice and verify its digest. This helper validates source/member metadata and serializes the declared vector seals; the later manager must independently restore and match every actual vector before preparing publication.

`encode_stage_intent(record)` accepts exactly `intent_id`, `tenant_id`, `collection`, `document_id`, `manifest_sha256`, `expected_active_generation_id`, `expected_authorization_revision`, `expected_mutation_epoch`, `initial_authorization`. It emits the stage array above. Non-null initial authorization requires expected active null, initial epoch one and the same expected authorization revision.

`encode_security_intent(record)` accepts exactly `action`, `intent_id`, `tenant_id`, `collection`, `document_id`, `expected_authorization_revision`, `expected_mutation_epoch`, `authorization`. `action` is `update_authorization` or `tombstone`. The `authorization` object and non-null stage `initial_authorization` have exactly `authorization_revision`, `principal_ids`, `grant_ids`, `language`, `kind`, `tag`, `tombstoned`. The revision supplies the security tuple's new revision. Initial authorization requires tombstoned false; a tombstone action requires true. Each ACL array has at most 64 valid identities before deduplication and unsigned UTF-8 sorting. Nullable metadata strings are NUL-free and at most 1,024 UTF-8 bytes. The helper cannot establish the current tombstone state; the authoritative manager must enforce monotonic deletion.

`encode_purge_intent(record)` accepts exactly `intent_id`, `tenant_id`, `collection`, `document_id`, `tombstone_intent_payload_sha256`, `expected_authorization_revision`, `expected_mutation_epoch`, and emits the purge array above. Epochs are nonnegative safe semantic integers; other identity, collection and locator bounds remain QC/QS rules. Missing nullable keys and extra fields are invalid. Bound metadata traversal to 4,096 native nodes, reject cycles/proxies/accessors/custom containers without evaluating hooks, and enforce the 1,048,576-byte final manifest ceiling.

`encode_dense_replay(original, profile)` and `encode_sparse_replay(indices, original, profile)` snapshot the original native numbers once, validate/encode them through B1 and return immutable `blob`, `blob_sha256`, `input_sha256`, `encoded`. `encoded` is the freshly issued B1 result. Original numbers are their finite binary64 numerical values, preserving signed zero. Input identity remains B1's canonical float32 seal. No generic serializer or new real-model batch admission is introduced.

The exact replay blob is:

```text
ASCII("cragkit.qdrant.replay.v1") || 00 || FRAME(ASCII(kind)) || U32(count)
|| [all U32 indices, only for sparse]
|| F64(original[0]) || ... || F64(original[count-1])
```

`kind` is `dense` or `sparse`. `F64` is IEEE-754 binary64 little-endian. Dense count is exactly 1,536; sparse count is 1 to 16 with sorted unique uint32 indices. Exact blob length follows count, with no trailing data. The original blob and its digest are durable sidecar data, separate from the generation's canonical float32 identity. Python blob admission accepts exact native bytes; Node accepts a bounded native array of unsigned byte numbers and returns a frozen array. A later authority adapter converts validated driver bytea to this native form.

`restore_dense_replay(blob, expected_blob_sha256, expected_input_sha256, profile)` and `restore_sparse_replay(...)` return a newly issued B1 result. Both expected hashes come from the trusted immutable authority record. Check native shape, hard length cap, hashes, domain/kind/count and exact layout before decoding bounded data; decode original values, re-encode through B1 and compare its complete canonical input seal. An attacker-supplied blob and matching self-reported hashes do not authorize anything. A copied result's fields cannot mint provenance. Replaying a valid original near the norm boundary must work even when its rounded components would fail original admission.

New malformed shapes, sizes, numeric input or options give `InvalidRequest`; structurally valid contradictory source/member data, duplicate membership or wrong UUID/digest give `IntegrityViolation`. Unsupported manifest profiles retain QC's `UnsupportedCapability`; a replay encoder's full-profile contradiction uses B1's `EmbeddingProfileMismatch`. Restore converts malformed or contradictory replay/hash/profile data to `IntegrityViolation`, while preserving unknown operational failures. This does not weaken manager scope, authorization or publication checks.

Current ACL, authorization revision and metadata replicas are excluded from immutable generation/vector identity. They are rebuilt from current authority for every point replay. An authorization-change intent separately binds the complete desired replacement ACL/metadata and expected fences; this does not authorize a staged publication to ignore a later security change.

## Additive authority and privileges

Do not modify applied `0001_authority.sql` or its checksum `3d75cd46eb32a10864f1097a7494b01f9759150911a7cd9a1e6aab60105c1f1a`. A future explicit administrative `0002` adds publication objects and policies, records its actual checksum atomically, and is never run on import, construction or initialize. Preparation/coordination lives in new tables; do not accidentally change immutable source/generation identity through a generic row-update trigger.

The new profile specifies complete history and a new exact catalog fingerprint. The existing QS-r1 `0001`/`8104abeef00594e7bfa4b533a139767599b56b87d09062c0d6f52f6e2f5d0b48` profile remains a separately supported source-only installation. Old readers correctly reject the upgraded unknown catalog. A subsequent reader-compatibility child explicitly accepts each frozen supported history/catalog pair; it must not wildcard-ignore new objects or weaken the old expected fingerprint.

Use dedicated nonowner, nonsuperuser, non-BYPASSRLS writer roles, separate from read-only source roles. Reader initialization continues rejecting effective writes and unsafe/admin/owner memberships. All write tables default-deny PUBLIC; only explicit least-privilege grants and policies admit scoped application writers. No security-definer function or permanent elevated runtime role is introduced. Any staged-row SELECT policy is restricted to the dedicated writer role and full trusted scope/owned intent; permissive-policy OR must not expose staged rows to readers. Reader fresh authorization still hides unpublished content.

Each fresh transaction installs the same five validated parameterized scope GUCs as QS-r1, including grants JSON at most 131,072 encoded bytes. Explicit SQL predicates repeat full scoped identities, required filters and expected fences. Writer role/catalog/history checks are explicit; dynamic unsafe privilege checks run for each fresh lease. Borrow pools with at most two connections and one active manager operation. Bound pool acquisition, statements, rollback and cleanup; discard a dirty connection instead of returning it. Never hold a transaction, row lock or checked-out connection over a Qdrant request, application callback or controller operation.

The additive schema must represent these durable facts:

| Record | Required uniqueness and binding |
| --- | --- |
| Backend control | Physical server instance/storage identity, epoch, admission state, supervisor identity and recovery attempt. Recovery scope covers every collection/document served by that instance. |
| Document coordinator | Full tenant/collection/document key, unguessable owner token, instance epoch and operation identity; conditional ownership changes. Time/lease is diagnostic, not side-effect fencing. |
| Intent | Fully scoped stable ID/action, immutable payload/manifest digests, expected prior active and security fences, source/generation identity, state and durable outcome. |
| Point claim | Unique `(backend_namespace, physical_collection, collection_incarnation, point_id)` globally, with full immutable scoped owner, source/member/profile/vector manifest. Tenant is deliberately absent from the unique key. |
| Dispatch journal | Unique intent/attempt/sequence, owner token, backend epoch, immutable credential generation, operation/request digest, exact claimed IDs and durable completion/uncertainty. |
| Preparation | Verified complete manifest, exact vector/payload readback, document/security fences, owner token and epoch; cannot stand in for publication. |

Reserve every physical point atomically before its first mutation. Use insert-if-absent plus full owner comparison, never an upsert that overwrites the claim owner. A conflicting hidden/foreign owner fails `IntegrityViolation` without touching Qdrant. Claims survive while any point, retained generation or unresolved dispatch can reference them; lease expiry, tombstone or an initial empty read does not permit reclamation. Collection incarnation never silently changes to reuse a name.

## Ownership, dispatch and publication

Intent states are `staged`, `writing`, `prepared`, `published`, `conflict`, `denied`. Security/cleanup actions also retain their explicit durable pending/complete outcome. `conflict` and `denied` cannot be rebased in place into a publication of different data. Dispatch states are `reserved`, `dispatched`, `settled`, `unknown`.

1. Validate/snapshot the full request; authorize; bind or reconcile intent, immutable source/members and every global claim. Incomplete staging remains unpublished. A same-ID revision/member mismatch is corruption, not a repair opportunity.
2. Acquire the per-document owner token with a short CAS. Verify backend admission open, current epoch, expected active, current authorization fences and no tombstone. A successor cannot acquire while any predecessor dispatch is unresolved, regardless of lease expiry or process timeout.
3. Reauthorize outside SQL; open a short transaction that checks owner/epoch/fences and commits a `reserved` dispatch before every Qdrant side effect. Bind the complete request digest and exact claimed IDs to an immutable credential generation. Only after commit acknowledgment is reconciled may the HTTP request begin. A later `dispatched` marker is informative; the crash gap means reserved is uncertain too.
4. Send a bounded complete point upsert, never a partial named-vector replay. Include exact immutable QC-r1 payload plus current authority ACL/metadata. Require `wait=true`, a strictly validated completed acknowledgment and exact readback. Accepted/queued responses, readback without known completion, canceled requests and unknown acknowledgments cannot settle a dispatch. No implicit SDK retry or redirect is admitted.
5. Verify the full generation with bounded scoped readback, all named vectors and full payload. Match exact member IDs, profiles, digests, spans and current replicas, reject duplicates/unexpected members and reach end of enumeration. Counts alone are insufficient. A mismatch never adopts the backend's values into the intent. If a current fence changes during verification, stop without publication.
6. Commit preparation only under the same owner, backend epoch and document/security fences, with no unresolved journal entry. Preparation remains invisible to new source fetches.
7. In one short final transaction, compare the original expected active pointer, owner token, epoch, authorization revision/mutation epoch, tombstone=false and verified preparation; atomically set new active/published facts and the intent's publication outcome. Clear the prior generation's current published flag while retaining its ever-published fact. Make no Qdrant call in this transaction. A stale CAS becomes `conflict` or `denied`, never overwrites a newer active generation.

On a failed/lost CAS acknowledgment, read the same durable intent and pointer. A committed outcome resolves success without a second publication. A read-only verification cannot prove a paused old request will not arrive later; uncertain dispatch remains blocked until the managed recovery protocol settles it.

## Managed recovery and controller ownership

The application supplies a borrowed exclusive supervisor that outlives all writer/coordinator processes. It alone owns server lifecycle, durable directory identity and write-key rotation. Its implementation is native or application-injected in each runtime; npm does not depend on a Python HTTP server. It issues opaque per-attempt capabilities bound to instance, recovery ID and epoch, with private identity validation. A dictionary, boolean, PID supplied by an untrusted caller, serialized token or `drained=true` is not a capability.

The supervisor is a trusted safety boundary. A paused predecessor controller must not retain authority to stop/restart the successor's process. There is no automatic supervisor takeover based on SQL lease expiry. If the supervisor dies or its exclusive ownership cannot be established, admission remains blocked until explicit out-of-band recovery establishes that old controller execution cannot resume. This reference profile recovers writer/coordinator crashes while the supervisor survives; it makes no automatic supervisor-crash recovery claim.

Recovery is instance-wide:

1. Atomically enter `recovery_blocked`, advance the admission epoch and quarantine all old-epoch document owners and unresolved dispatches. No new vector mutation may dispatch anywhere on that instance. Revocation and tombstone authority transactions remain available.
2. The supervisor retires old writer capabilities and stops/drains managed writer executions. Old transports retain their old key forever; they cannot fetch the new key through a retry, shared mutable transport or credential-refresh callback. A paused old caller after its last epoch check is explicitly included.
3. Stop the exact owned Qdrant process and observe its exit. Close old connections. Rotate the write credential in private configuration, restart the same durable directory under a new process identity and supported `prevent_unoptimized=false`, and establish completed load/WAL replay, not just a successful health probe.
4. Probe an actual mutation endpoint with the old key and require denial; the probe cannot mutate a foreign point. The fresh key is available only through current supervisor-issued capabilities. In the pinned single-key profile, the retired key is invalid and must receive HTTP 401; it must not silently retry with the fresh key. Qdrant 1.20 maps an invalid API key to `Unauthorized`, while a recognized credential lacking permission can receive 403. The E1 native run observed the retired key's 401. [Pinned credential validation](https://github.com/qdrant/qdrant/blob/v1.20.0/src/common/auth/mod.rs), [HTTP status mapping](https://github.com/qdrant/qdrant/blob/v1.20.0/src/actix/auth.rs).
5. With the gate still closed, reconcile every quarantined intent/claim/dispatch against exact current stored points. Unknown old effects may have completed and replayed; never rewrite history as a proven unsent request. Reconstruct desired complete points from immutable manifests and current authority, or delete only exact owned tombstoned debris. Journal any recovery mutation before dispatch under the new attempt capability.
6. Verify exact repaired sets, current payloads and purge absence as applicable. Conditional authority settlement records the supervisor attempt, old/new epochs, reconciled manifests and outcome. Reopen admission only after all instance-wide uncertainty is resolved. A failed deadline, controller step or reconciliation leaves the instance blocked and resumable under the same durable recovery identity.

The supervisor's private completion capability is an in-process authority object, not a reusable public proof. Native acceptance must verify actual process/key/storage behavior and manager-crash resumption. No fixed sleep, heartbeat expiry or operator assertion replaces those observations.

## Security changes, tombstones and deletion

ACL/metadata updates compare expected fences, atomically commit the new complete state and increment `mutation_epoch` with a new authorization revision. Tombstone performs the same security transition and immediately denies all generations, including private retained source bindings. These SQL commits are not delayed by an outstanding vector request or instance recovery gate.

The same document coordinator serializes subsequent vector convergence. An old full-point upsert can still carry old ACL while it is uncertain; QS-r1 must independently enforce current authority before provider/final release. After settlement, replay builds current replicas, never restores an intent's stale grants or unsets a tombstone. A denied or conflicting publication does not resurrect its source.

Purge is a stable tombstone-bound intent. Settle/fence every older possible writer first, delete only complete exact globally claimed point IDs in bounded batches with completed acknowledgments, then enumerate the full scoped identity to prove absence. Repeat after managed recovery if any earlier deletion/read was uncertain. Never delete a replacement generation by broad document filter, reclaim a claim while a late upsert is possible, or report complete because the first absence read was empty. Retain non-text tombstone, ownership and operation facts needed to prevent replay; physical source retention/deletion policy is explicit and cannot weaken immutable retained evidence semantics.

## Resource and error contract

Profile ceilings are 64 members per generation, eight points per write/readback page, 256 dispatch attempts per intent, 1,048,576 response bytes per HTTP request and 8,388,608 aggregate verification response bytes per operation. Shared ledger admission may make these smaller. Enumeration must reserve enough to detect an unexpected 65th member and require EOF; an exhausted page/byte budget cannot become complete. Offsets, repeated offsets, duplicate points, malformed JSON and depth/node bounds are validated before release. Source/excerpt ceilings remain 16,777,216/32,768 bytes. There are no background repair loops, unbounded retries or new provider charges.

The existing execution ledger has provider calls, candidates, attempts, tokens and spend; it has no storage-HTTP call or byte allowance. Storage HTTP never consumes `provider_calls` or search `candidates`. Charge at most one shared logical attempt for an admitted public manager operation, and only when the outer caller has not already reserved that same logical attempt. Individual HTTP dispatches and verification pages consume separate local bounded counters and durable journal slots, not extra logical attempts. Reconcile actual model usage only if a genuine model operation exists; this manager makes none. An already-computed E-r1 batch adds no provider usage. Local storage counters charge dispatched requests/observed bytes honestly even on partial or canceled I/O; only undispatched local admissions can be abandoned. Admission failure before dispatch creates no HTTP side effect; after dispatch it preserves durable uncertainty. The original shared deadline governs both kinds of accounting.

| Failure | Required result |
| --- | --- |
| Malformed native shape, IDs, span input or unsupported operation option | `InvalidRequest`, before I/O where locally decidable. |
| Unsupported server, control capability, profile or authority history/catalog/role | `UnsupportedCapability`; never downgrade the write profile. |
| E-r1 batch/profile contradiction at admission | `EmbeddingProfileMismatch`; response/authority immutable contradiction is `IntegrityViolation`. |
| Claim collision, same-intent changed payload, full-set/vector/payload mismatch | `IntegrityViolation`; no adoption or publication. |
| Fresh authorization false or revoked scope | `UnauthorizedScope`/durable `denied` as appropriate; authoritative denial remains committed. |
| Changed expected active or nonsecurity fence | Durable `conflict`; no automatic rebase. |
| Shared deadline/caller cancellation | `DeadlineExceeded`/native cancellation; preserve unknown dispatch and bounded cleanup. |
| Authority, transport, controller or cleanup operational failure | Redacted `ProviderUnavailable` or established cleanup failure; no ordinary empty success. |

Known errors are recreated with fixed safe messages; unknown subclasses and raw chains cannot leak source, credentials or SQL. Close rejects new work, bounds cancel/drain, preserves unresolved durable work and never reports a canceled external write as undone. One failure to test is cancellation after dispatch followed by tombstone: source access stays denied while cleanup remains pending until the old credential and server effects are settled.

## Acceptance and implementation order

The scenario fixture is synthetic unexecuted design data until a native report records actual results. Each QD-r1 row must map to a fault scenario, and native acceptance must cover actual journal/HTTP/CAS boundaries, global claim collision, same-dimensional wrong vectors, exact full membership, concurrent revocation/tombstone, retained source authorization, old live credential rejection and supervisor survival across writer-manager crash. Run Python and Node separately against the same bounded inputs; no runtime may delegate its manager to the other language.

Implement B1 pure vector codec, B2 immutable manifest binding, C additive authority/writer privileges and upgraded reader compatibility, D native authority writer, E caller-owned supervisor, F stage/publish, G repair/security changes/purge, then H the complete native fault matrix. Each child has explicit owned paths, frozen contracts and a final serial integrator. No child may claim publication from thin mocks alone. [The version plan](../tasks/versions/V5-integrations.md) and tracker own the final child split and evidence state.
