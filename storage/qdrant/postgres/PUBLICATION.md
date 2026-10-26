# Managed publication authority

This is the additive V5-04C1 SQL foundation for [QW-r1](../../../contracts/QDRANT_PUBLICATION_V5.md). It defines database constraints and restricted runtime capabilities. [C2 evidence](../../../evaluation/reports/V5/V5-04C2.md) records native reader/catalog compatibility. [D evidence](../../../evaluation/reports/V5/V5-04D.md) records native authoritative writer transactions. Qdrant completion, supervisor process exclusion, application write authorization and actual replica publication remain E through H acceptance.

For example, a committed `reserved` dispatch prevents a new document owner even when its caller disappears. A supervisor can later settle that historical record during instance recovery without changing the original request or epoch. The database records that decision; the native supervisor must establish that old requests can no longer arrive.

## Explicit installation

Apply `migrations/0002_publication.sql` only through an authorized administrative transaction. First verify exact history `0001_authority` with SHA-256 `3d75cd46eb32a10864f1097a7494b01f9759150911a7cd9a1e6aab60105c1f1a`. The wrapper computes this new artifact's actual checksum and records `0002_publication` in the independent `cragkit_qdrant.schema_migrations` history in the same transaction. This file has no self-checksum constant and no implicit installer.

The administrator explicitly provisions two dedicated capability roles before applying the migration:

```sql
CREATE ROLE cragkit_qdrant_writer NOLOGIN NOSUPERUSER NOCREATEDB
    NOCREATEROLE NOREPLICATION NOBYPASSRLS;
CREATE ROLE cragkit_qdrant_supervisor NOLOGIN NOSUPERUSER NOCREATEDB
    NOCREATEROLE NOREPLICATION NOBYPASSRLS;
```

The migration requires those exact safe flags, no outbound role memberships and no existing ownership of database/schema/table/function/type objects. It does not create, repair or silently adopt an unsafe role. Provision dedicated LOGIN roles separately and grant only the relevant capability membership. Never give a source reader writer or supervisor membership. Role checks cannot replace application authentication; transaction-local settings are trusted application bindings.

The migration adds validated generation bounds of 1 through 64 expected members, refuses existing actual member sets above 64, and refuses contradictory existing active/published flags. It preserves the bytes and existing reader policies of `0001`. Existing consistent source-only published generations remain legacy authority facts; the new commit guards apply to subsequent publication changes. There is no automatic conversion of old content to verified vector manifests or claims.

The upgraded schema requires a new exact history/catalog profile. Readers from before C2 reject it. Current native readers support the old source-only profile and the new publication profile explicitly through [C2-r1](../../../contracts/QDRANT_SOURCES_V5.md#c2-r1-explicit-publication-schema-compatibility), with frozen complete fingerprints and dynamic role checks. They reject added objects and preserve the original fingerprint.

## Roles and scope

Writer transactions use `READ COMMITTED`. Bind all five existing QS-r1 settings and four operation settings with parameterized `set_config(..., true)`:

| Setting suffix under `cragkit_qdrant.` | Meaning |
| --- | --- |
| `tenant_id`, `collection`, `principal_id`, `grant_ids`, `authorization_revision` | Existing freshly trusted scope. Grants JSON remains at most 131,072 bytes. |
| `writer_document_id` | Exact document target, including for predecessor journal inspection. |
| `writer_intent_id` | Current stable operation identity; staged source access binds its recorded revision/generation. |
| `writer_owner_token` | Canonical lowercase UUID text for the current private owner capability; validated without casting malformed settings. |
| `backend_instance_id` | Exact managed physical instance. |

Missing or malformed writer settings deny row access. Higher-isolation managed mutation is rejected; explicit BEFORE guards use SQLSTATE `23514`, while a policy-only denial uses `42501`. C1's fresh-after-lock logic assumes `READ COMMITTED`. Source readers keep their existing read-only transaction behavior, including their separate repeatable-read path.

Writer SELECT on intents, journals, claims, replay sidecars and other operational rows includes all records for the bound document, including predecessor intents. Hiding a predecessor would hide uncertainty. Source revision bytes and member excerpts instead require the bound stage intent's exact source identity. That stage precedes owner acquisition, so source admission does not require a coordinator row.

Restrictive writer SELECT policies prevent the existing PUBLIC reader-policy OR from widening writer source access. Never-published generations require their bound stage intent; already-published generation metadata remains visible for scoped prior-generation flag updates. The unchanged reader policies continue hiding unpublished content. Writer RLS permits authoritative revocation and tombstone even when new ACLs no longer grant read access; the native application must call `authorize_write(scope, collection, document_id)` and compare current security fences explicitly.

An authorization or purge operation may need retained vectors and member metadata. Claims and sidecars are available under the bound document. Reading source/member byte rows for another retained stage requires a separate short transaction bound to that original stage intent, followed by restoring the current mutation binding. This never broadens the document target or reader policies.

The supervisor has instance-wide operational metadata access and instance control, with column privileges withholding intent payloads/manifests, request bodies, vector sidecars and all source tables. A mutable GUC does not confer that role. It cannot use a source reader's role to obtain lifecycle authority. No SECURITY DEFINER function, PUBLIC table privilege or PUBLIC helper execution is added.

## Durable records

| Table | Retained facts |
| --- | --- |
| `backend_instances` | Instance, namespace, durable storage/supervisor identity, admission epoch and recovery state. |
| `publication_intents` | Fully scoped stable action, immutable payload/manifest bytes and hashes, expected active/security fences, monotonic state and outcome flags. |
| `document_owners` | One current private owner token, intent and backend epoch per fully scoped document. |
| `point_claims` | Global physical UUID ownership, full scoped member/profile/vector identity and source digests/spans. |
| `vector_replays` | Immutable B2 original binary64 sidecars and their byte digests, anchored to retained claims. |
| `dispatch_journal` | Exact immutable request identity, credential generation, owner/epoch, sequence, recovery kind, creation transaction and uncertainty/settlement. |
| `dispatch_points` | One to eight exact globally claimed physical points in a dispatch. |
| `preparations` | Immutable verified manifest/readback identity bound to owner, instance epoch and current security fences. |

Global claims are unique on `(backend_namespace, physical_collection, collection_incarnation, point_id)`, without tenant in the unique key. Insertion locks and compares the complete existing member/generation identity. A hidden foreign collision still conflicts through the unique index; `ON CONFLICT DO NOTHING` cannot overwrite it. Claims retain a security-document FK instead of a permanent source-member FK, so later explicit source retention cleanup need not erase ownership proof.

No runtime role receives DELETE on these records. Source deletion cannot cascade through a claim into journal/replay history. G must define bounded physical source/replay retention cleanup while preserving unresolved claims, dispatches and security facts; C1 does not silently reclaim ownership. SQL checks sidecar byte size/digests, not the B1/B2 numerical meaning: native D must restore originals and match canonical seals.

## Transaction protocol and locks

1. Bind the stable intent in `staged`. A new security-document shell and the intent may be created in one transaction using the deferred document FK. New documents start with a null active pointer. Stage revision, generation, members, claims and sidecars before network work.
2. Acquire or conditionally transfer `document_owners`, then change the bound intent to `writing`. A successor cannot transfer ownership while any same-document journal record is reserved, dispatched or unknown. No lease expiry bypass exists.
3. Reserve a dispatch and all its point rows in the same transaction. `created_xid` binds membership to that creation transaction; a later transaction cannot append points even if the journal remains reserved. The sequence is unique and bounded to 256 per intent. Native D must validate the exact request/claimed-set relationship before committing admission.
4. Release the connection before HTTP. Native code dispatches only after the reservation transaction commits. Known completion plus exact readback may settle a normal request. Unknown settlement requires the supervisor. SQL metadata cannot prove that an acknowledgment or readback actually happened.
5. With all document dispatches settled, insert immutable preparation while the stage intent is `writing`, then move it to `prepared`. The expected source member, claim and replay counts must agree with the fully scoped generation. These SQL joins supplement, rather than replace, native exact full-set/vector verification.
6. In one transaction, update the active pointer, old/new published flags and intent outcome. The stage intent becomes `published` with `authority_committed=true` and `replica_complete=true`. Deferred constraint triggers require preparation, the original expected prior active pointer, current owner/epoch/security fences, no tombstone, no unsettled journal, exact member counts and consistent published flags. Use `SET CONSTRAINTS ALL IMMEDIATE` in a test subtransaction to inspect the final facts without an external commit.

Admission locks the backend row `FOR SHARE`, then the document owner row `FOR UPDATE`. Owner transfer, reservation, preparation and deferred publication use the same records. A supervisor gate/epoch UPDATE conflicts with backend SHARE; no new reservation can slip past that short transaction. After waiting for locks, guards read facts in separate statements. The final owner record is refreshed too. The native D adapter must use the same lock order before its DML to avoid avoidable deadlock/retry paths.

Member-limit enforcement locks the generation row before recounting, and rechecks that it has never been published. Final publication rechecks membership after preparation. Thus a late member cannot silently enlarge a prepared generation; source/member/claim facts are immutable. No connection or SQL lock is held over HTTP, a provider, an authorization callback or a supervisor lifecycle operation.

The limited `UPDATE(point_id)` member privilege exists solely because PostgreSQL row-locking SELECT requires an UPDATE privilege. The unchanged unconditional immutable-member trigger rejects actual member UPDATE, including a no-op. It does not permit changing point ownership.

## Recovery and immediate denial

Only the supervisor may move an open instance to `recovery_blocked`; it advances the epoch and binds a recovery ID. Repeated work on that recovery keeps its epoch/identity. Reopening requires no unresolved instance journal, including other documents. SQL does not establish server exit, key rotation, WAL replay, current credential privacy or supervisor exclusivity. E and H must prove those observations with the native controller.

During blocked recovery, the supervisor may advance the existing document owner's epoch without changing its token or intent, and reserve a distinct immutable `recovery=true` dispatch at the current backend epoch. It may settle a historical old-epoch journal under the current blocked recovery without rewriting the historical request/epoch. This is reconciliation by the same owner identity, not successor takeover. Ordinary writers cannot forge recovery with a GUC or dispatch while blocked.

Authorization/metadata updates and tombstones that leave the active pointer unchanged do not acquire the vector owner or recovery gate. Existing monotonic authorization/epoch and irreversible tombstone guards remain active. Authority denial can therefore commit while a vector request is uncertain. Native D/G must bind the corresponding stable security intent and perform a fresh conditional authority mutation; SQL role membership is not evidence that the application authorized it.

## Acceptance limits

C1's root harness installs and probes the schema inside an isolated rollback-only PostgreSQL transaction. It exercises restricted roles, row/column isolation, immutable facts, legal and illegal state transitions, global collisions, deferred publication consistency and cleanup. The same-outer-transaction `created_xid` checks do not establish real cross-commit membership freezing; D/H must exercise a reservation commit followed by a separate attempted extension.

Actual two-connection reservation/owner-transfer, instance-gate and member-limit interleavings remain D/H native evidence. Successful sequential constraints or source review do not prove those races passed. [C1 SQL acceptance](../../../evaluation/reports/V5/V5-04C1.md) and C2 reader acceptance are separate from those gates. No model call, publication durability or production-readiness claim follows from this migration alone.
