# Qdrant security-owner and managed erasure profile

Revision: QP-r1. This is the additive schema prerequisite for V5-04G2 repeated
security convergence and V5-04G3 purge. It specifies implementation, not completed
acceptance. G3 and V5 remain open until their native gates pass.

For example, an acknowledged vector deletion leaves canonical source and replay
bodies in PostgreSQL. Purge completion requires both authenticated physical
absence and the managed erasure below.

## Installation and compatibility

Install `0005_security_owners_and_erasure.sql` explicitly, in an operator-owned
transaction, only after the exact four accepted migration checksums. Never edit
0001 through 0004 or migrate on core import. The supported operator remains a
native PostgreSQL 17 login, schema owner and CREATEROLE, without superuser or
BYPASSRLS. Runtime roles cannot become the operator or either definer role.

Profile 5 has exact history, catalog, roles, ACLs, RLS and function fingerprints.
Readers, writers and recovery must explicitly admit it; a changed or partial
catalog fails closed. Older supported profiles retain their existing checks.
Installing this foundation does not accept public convergence or purge.

## Repeated security ownership

Replace the existing 22-argument `lock_current_security` implementation without
changing its signature, metadata-only guard privileges, lock order or current
authority checks. An actual owner intent may be `stage`, or an
`authority_committed` `update_authorization` or `tombstone`. The latter may equal
the current security intent. An uncommitted security intent or any `purge` owner
is rejected. Keep exact backend identity, blocked recovery ID, epoch, owner token,
current document tuple and security digest checks, including rereads after waits.

The old owner payload is immutable history, not the current authorization tuple.
Runtime plans carry the actual owner action and payload digest. Stage-only
manifest/revision/generation fields are absent for security owners. An open,
ownerless document may admit the genuine current security owner when no target
journal is pending. A blocked instance cannot bypass global settlement to do so.
Ownerless admission transitions an `authority_committed` current security intent
to `writing`. A historical `complete` intent requires its existing matching owner;
it does not authorize inventing ownership after administrative history changes.
No fabricated stage, new source revision or old authorization restoration is
allowed. Profile 4's stage-only behavior remains unchanged.

## Irreversible content representation

Add `documents.content_unavailable` and per-body `content_erased` flags, all
initially false. Make only these content columns nullable:

| Table | Managed content |
| --- | --- |
| `document_revisions` | `canonical_utf8` |
| `members` | `excerpt_utf8` |
| `vector_replays` | `dense_blob`, `sparse_blob` |
| `dispatch_journal` | `request_bytes` |

Preserve original identities, byte spans, digests, manifests, claims, journal
headers and memberships, preparation/attestation metadata and operation flags.
Store immutable original byte counts before nulling. Insert triggers derive
counts from original bytes so existing inserts remain compatible. Preserve the
distinction between an originally absent sparse body and an erased one.

Checks require original valid bytes when present and NULL managed bodies when
erased. Existing immutable triggers admit only the exact one-way transition by
the dedicated purge function; all other fields remain immutable. No restoration,
marker reversal, direct runtime body update/delete, or new managed content insert
is allowed after the document becomes unavailable. Retain point claims permanently
in this profile. Historical source reads return known unavailable before decoding
NULL, never an invented empty excerpt or an integrity outage.

## Dedicated SQL capability

Create `cragkit_qdrant_purger` as NOLOGIN, NOSUPERUSER, NOBYPASSRLS, NOINHERIT,
NOCREATEDB, NOCREATEROLE and NOREPLICATION. Follow the existing operator membership
pattern. It cannot read canonical, excerpt, replay or request bodies. Grant only
enumerated metadata reads, required row locks and one-way content-column updates.
FORCE RLS covers every new table. Account for the existing document policy's
read-only helper dependencies. Revoke PUBLIC execution on new functions.

Only the original restricted writer login may execute this fixed SECURITY DEFINER
function, with `search_path=pg_catalog`, `row_security=on`:

```text
erase_purged_document(
  instance_id text, backend_namespace text, storage_identity text,
  supervisor_id text, backend_epoch bigint,
  physical_collection text, collection_incarnation text,
  tenant_id text, collection text, document_id text,
  purge_intent_id text, purge_payload_sha256 text, owner_token uuid,
  tombstone_payload_sha256 text, authorization_revision text, mutation_epoch bigint,
  inventory_bytes bytea, inventory_sha256 text, policy_id text, absence_sha256 text
) RETURNS boolean
```

SQL parameter names use the `p_` prefix. Accept only
`erase_managed_source_and_replay_v1`. Validate bounded identities, digest formats,
safe integer epochs and inventory bytes at most 262144. Reject privileged,
SET ROLE, supervisor or unexpected inherited callers. Lock backend, owner and
document in that order and reread after waits. Require open exact backend, actual
current purge owner, committed exact purge/tombstone binding and no pending target
journals. Validate the exact canonical purge payload and independently reconstruct
the sorted full claimed inventory from immutable metadata. Check both the supplied
inventory byte digest and decoded JSON value; SQL JSON formatting is not the SDK's
compact canonical codec.

The profile-5 supervisor additionally receives only document identity and
`content_unavailable` SELECT columns, plus lock-only UPDATE privilege on that
marker with a scoped RLS update policy whose `WITH CHECK` is false. This permits
the generic body-insert trigger to acquire `FOR SHARE` and check availability
without reading source or authorization bodies. It cannot change the marker.
Insert checks serialize with erasure, so a concurrent insert cannot restore a
body after erasure commits. Profile-4 grants remain unchanged.
The supervisor receives the exact read-only `scope_visible` function dependency
needed by the existing public document policy. The purger receives
`generations.ever_published` metadata SELECT for existing revision/member RLS.
Neither addition permits source-body reads or a broader write operation.

The decoded inventory is exactly the existing security inventory array:
`["cragkit.qdrant.security-inventory.v1", backend_namespace, physical_collection,
collection_incarnation, tenant_id, collection, document_id, instance_id, groups]`.
Each group is `[revision_id, generation_id, manifest_sha256, sorted_point_ids]`;
groups sort by UTF-8 revision then generation and point IDs sort by UTF-8 bytes.

The function runs in the writer's existing transaction under the authentic native
ordinary absence receipt and controller finalization. SQL cannot establish Qdrant
absence from a caller digest. Direct SQL probes use synthetic absence digests and
must never be reported as physical purge acceptance.

Create metadata-only `purge_erasures` records binding exact target, purge intent
and payload hash, tombstone hash, inventory hash, policy, absence hash and terminal
erasure digest. Only the fixed function writes them; restricted writers may read
scoped metadata for historical confirmation. Explicitly name any SQL JSON digest
codec; do not label it the cross-runtime compact codec.

In the same transaction, null every target managed body, set irreversible markers,
verify no body remains, record erasure and complete the exact purge intent with
`authority_committed`, `replica_complete` and `purge_complete` true. Any failure
rolls back every body, marker, record and flag. Historical exact retries use retained
metadata, never erased content reconstruction or HTTP/DML replay.

## Bounds and physical prerequisite

Preflight before the first physical deletion, and recheck before erasure: at most
64 generations, 2048 claims, 64 MiB source plus manifest data, 4096 total target
journal headers, 64 MiB retained request bodies and 32 MiB replay bodies. Query
4097 journal headers to detect overflow. Reserve enough remaining journal slots
for the planned exact-ID delete batches. Overflow leaves cleanup pending; no
truncation, vectors-only completion or unbounded resume loop is allowed.

Keep stage/security ownership through actual fencing, exact-ID deletes, retired
journal settlement and reopening. Transfer to the ordinary purge owner only after
all possible physical writers have been settled. A current-credential uncertain
request requires genuine refencing, even if a point read is empty. Delete batches
contain one through eight claimed UUIDs, never a broad filter. Authenticate full
document absence, including scoped enumeration EOF and rejection of unknown IDs.

This policy erases managed source and derived bodies logically. It retains
locators, ACL and other identity metadata. It does not sanitize PostgreSQL heap,
WAL, replicas, backups, external logs, caches or caller-owned stores.

## Acceptance before dependent runtime use

Use an isolated actual PostgreSQL 17 fixture with the non-superuser operator.
Prove installation rollback, exact history/catalog and minimum effective
permissions; runtime and forged helper calls must fail. Prove stage, prior
committed security and same-current-owner guard branches, rejecting uncommitted
and purge owners. Prove successful authorized erasure, foreign target and changed
binding rejection, all pending-journal refusals, rollback after intermediate
nulling, immutable retained metadata and prohibited restore/reinsertion. These
SQL checks precede runtime integration; real Qdrant absence, crash and provider
non-disclosure acceptance remains a later separate gate.

## Profile-5 runtime admission

The actual PostgreSQL 17.11 fixture pins history/catalog in
`contracts/fixtures/qdrant_purge_catalog.json`. Embed the exact SQL bytes from
`contracts/sql/qdrant_purge_capabilities.sql` into each native optional authority
module. The query normalizes installation-specific operator/bootstrap names
with tagged JSON arrays and preserves capability-role attributes, membership
edges, effective privileges, ownership and definer ACLs. Its actual accepted
fingerprint is
`80210922ed1130d45762383222affbf0147c679f5a23e9b2ed20ac079f33c817`.
Do not substitute schema-body fingerprinting for role/privilege checks.

Internal names are `EXPECTED_PURGE_HISTORY`,
`EXPECTED_PURGE_CATALOG_FINGERPRINT`, `_PURGE_CATALOG_SQL`,
`_PURGE_CAPABILITY_FINGERPRINT_SQL` and `_PURGE_OWNER_SQL`, with corresponding
native TypeScript names. Increase migration history lookahead to six, admit
exactly five known rows, and reject a sixth or changed checksum. Structural
checks admit exactly the two fixed definer signatures with their pinned
attributes and fifteen tables, fourteen under FORCE RLS. Preserve the existing
guard-owner/operator checks, changing only its exact other-definer exclusion to
admit the fixed purge signature; require the capability fingerprint as well.
Writer and supervisor caller checks must match only the profile-5 additions in
this contract. No profile fallback or live catalog upgrade is allowed.

For source reads under profile 5, preserve the existing source-row contract and
known unavailable outcome. Use original immutable source/excerpt byte counts
after erasure so NULL-body lengths do not become invalid metadata. Ensure erased
content is unavailable before attempting body decoding and never release text
from a marked document. Older profile query shapes and behavior remain intact.
This admission slice does not widen stage-only recovery plans to security owners,
issue purge receipts, erase through the public SDK or complete G2/G3.
