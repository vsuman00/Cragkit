# Qdrant consistency contract

Revision `QD-r1`. Design for V5-01; no Qdrant adapter, SourceStore implementation or public API is introduced here. The [decision](../docs/decisions/0003-qdrant-consistency.md) records authority and failure boundaries. The [synthetic cases](fixtures/qdrant_consistency.json) are normative inputs and stored expectations for future runtime assertions, not executed observations.

For example, a revoked document may still have a Qdrant point with an old grant. That point can nominate an identity; only a fresh authoritative authorization check can permit its text to leave the source boundary.

## Authority and identity

An injected authoritative SourceStore owns immutable canonical source revisions, current document metadata and ACLs, tombstones, durable ingestion intents and completion manifests, and the atomic active-generation compare-and-swap (CAS). It may be caller-owned storage; QD-r1 does not require another PostgreSQL deployment. A Qdrant payload containing text is a replica, even when convenient for small sources. A store without these authority and atomicity capabilities cannot claim QD-r1 compatibility.

All identities are scoped by tenant and collection. A durable intent binds its stable key to one payload digest and immutable document/revision/generation identity. Replay of the same intent and digest resumes or returns its recorded outcome after current write authorization; reuse with different content fails. A failed or ambiguous request does not establish that its write failed. Read the durable intent and reconcile the same identities before retrying; never allocate a new generation merely because an acknowledgment was lost.

A generation manifest binds parser, chunker, dense profile and declared sparse profile to the immutable source digest and the exact expected chunk/point set. Each member binds document, revision, generation, chunk ID, canonical UTF-8 start/end offsets and excerpt digest. Point IDs use deterministic UUIDs derived from the scoped identity, with full identity/digest collision checks in the payload and manifest; raw hexadecimal digests are not Qdrant point IDs. Counts alone cannot prove completeness: an equal-sized set with an unexpected member is invalid. Verify stored identities, source/excerpt digests and profiles against every expected member, and reject missing, duplicate, extra or mismatched members in the generation namespace. Validate canonical spans against authoritative bytes. Separately verify every required named vector is present with finite values and declared dimensions. Arbitrary float JSON checksums are not canonical vector identity: any later vector checksum needs an explicit float32 byte encoding and normalization rule shared by both runtimes.

Immutable manifest identity covers source/chunk membership, canonical digests and vector/profile identity. Mutable ACL and metadata-filter replicas, including their authorization epochs, are excluded from that immutable identity. Their changes do not change immutable source bytes or generation membership.

Before the first point write, atomically reserve its physical ID in an authoritative ownership registry shared by every writer to that physical Qdrant collection. The unique reservation key includes the backend/collection incarnation and point ID; its value binds the complete immutable scoped identity and profile. An existing identical claim is an idempotent replay. A different owner fails with `IntegrityViolation` before any point mutation. Resolve an ambiguous reservation acknowledgment by reading the same claim. A per-document lock and a separate read-before-upsert cannot provide this cross-document exclusion. The SourceStore must supply this atomic registry capability, or initialization rejects the profile. An independent source authority cannot share the physical collection without the same registry. Keep reservations while stored points, retained generations or unresolved writes/intents can reference them. Reclamation requires verified cleanup and durable fencing of all old writers; cancellation, lease expiry or an empty point read alone is insufficient. The registry retains ownership metadata under the owner's deletion policy, not source text. Collection recreation uses a new incarnation and fences old credentials/writers before namespace reuse.

## Publication and repair

Durable job creation precedes staging. Store the immutable source and chunk manifest before vector completion. Staged generations remain unsearchable. The initial implementation profile is explicitly single-node; reject unverified distributed consistency profiles. It requires an enforceable external per-document mutation coordinator shared by ingestion, repair, ACL/filter replication and purge. The coordinator serializes Qdrant mutations and drains or reconciles every uncertain in-flight mutation before admitting another conflicting mutation. After a coordinator crash, a successor remains blocked until prior mutations are resolved/drained. Lease expiry or a SourceStore epoch alone cannot fence a Qdrant write already dispatched. Reject the profile when the store cannot provide this exclusion/drain capability; QD-r1 does not assert a Qdrant compare-and-swap. Complete all bounded vector writes with the declared durable completion semantics, then verify the exact expected scoped content set. Qdrant wait=false acknowledgment alone is insufficient; require wait=true completed writes and readback reconciliation after ambiguous acknowledgment. Replaying a point must include its complete dense and sparse named-vector content because same-ID upsert replaces the point, including omitted vectors. Under the mutation coordinator, construct mutable ACL/filter payload fields from current authoritative state rather than replaying a stale payload captured by the intent. This prevents an old full-point repair from overwriting a newer replica update once conflicting operations have drained. Acceptance of a request, an operation ID or a matching point count is not a publication barrier.

Record verified preparation in the SourceStore. In one atomic publication mutation, require the verified manifest, expected prior active generation, current write authorization, unchanged authorization/delete fences and no tombstone; set ready/published, switch the active pointer and record intent success together. A prepared record is not ready or published. This boundary contains no model or Qdrant call. Qdrant and an independent SourceStore do not share a transaction.

After any prepublication failure, the previous active generation remains eligible, subject to current authorization and deletion. Concurrent publishers must compare the expected active generation; a slower intent cannot overwrite a newer publication. Ambiguous CAS acknowledgment is resolved from the authoritative active pointer and intent outcome. It cannot justify rolling back a successful publication or retrying against a different expected generation.

Repair resumes the same intent with bounded attempts and exact identities. It rechecks current write authority and fences before each new side effect and publication. Tombstones are monotonic for this intent: repair cannot restore a revoked grant, resurrect a deleted document, change immutable bytes or adopt unexpected points as the expected set. An already dispatched write may land after the tombstone or initial purge; fences cannot retract that write. Keep deletion durably pending until unsettled writers resolve and a repeated exact scoped absence check confirms purge. The tombstone blocks disclosure throughout. A destructive purge targets the recorded scoped generation/point set; it cannot remove a concurrent replacement generation. Staging retention and source retention are explicit owner policy, not permission to bypass tombstones.

## Search, source release and ACL synchronization

Every dense, sparse, identifier and fallback branch must enforce trusted tenant/collection scope and all required filters before candidate selection. Unsupported operators or consistency capabilities fail explicitly. Replicated ACL/filter fields may reduce candidates but never authorize disclosure. Do not relax scope, filters or budgets when stale replicas underfill a result. Recheck current authoritative metadata for required filters before disclosure.

New searches admit only the document's authoritative active, published generation. A candidate from a superseded, unpublished, mixed-revision or foreign-scope generation cannot enter a provider shortlist. A request already bound to a previously published revision and existing historical reference resolution retain the documented [immutable revision policy](RETRIEVAL_V1.md): a previously published revision may resolve with a stale indication after fresh authorization, when retention permits. That does not make a superseded generation eligible for a new search.

Before any external provider receives candidate text, resolve its exact identity against the authority, verify bytes/spans/digests and profile, and check current grants, required filters and tombstone. Repeat authorization immediately before final release; a revocation between reranking and packing discards that source. The provider must also be explicitly permitted by application disclosure policy. Query disclosure follows the same configured provider policy. Bytes already lawfully delivered cannot be recalled by a later revocation.

The mutation coordinator does not delay authoritative revocation or tombstoning while waiting for Qdrant: commit those security changes immediately, then serialize their replica updates and cleanup. Authoritative checks continue to block stale replicas throughout.

ACL and metadata changes become effective when the authority commits them and advances its authorization fence; replica updates follow idempotently. A stale grant cannot bypass the authority. A newly granted document may be temporarily absent because old payload filters suppress it; treat this synchronization limitation honestly. Lost replica-update acknowledgments do not undo authoritative changes. An ACL-only change must not rewrite immutable source identity or silently restore a previous grant during repair.

Deletion first commits the authoritative tombstone and invalidates authorization/cache eligibility, then purges derived points and source material under owner retention policy. Partial purge leaves inaccessible debris, never readable evidence. Concurrent repair must observe the delete fence before publication. ACL revocation and deletion cannot be rolled back by switching to an older generation.

An unavailable source/authorization service fails closed before provider disclosure or final release. Represent the outage as `ProviderUnavailable` or `DeadlineExceeded` as applicable through the existing operational error policy, fatal by default for source release failures in [HY-r1](HYBRID_V2.md). A confirmed missing, deleted or deauthorized source is unavailable evidence under the existing source contract. A service outage must not become an ordinary empty success. Malformed replica identities are quarantined without resolving arbitrary payload locators or exposing raw text in diagnostics. Integrity failures use the existing integrity policy. Rejection of individual stale candidates must not itself imply known sufficient coverage.

## Profiles and bounds

Dense profile identity includes model/revision, dimensions, normalization and preprocessing. Sparse identity declares encoder/model/revision, vocabulary or hashing scheme, preprocessing, weighting and any corpus-statistics revision. Generic sparse vectors are not BM25 or PostgreSQL FTS. QD-r1 selects no sparse provider, model download or public constructor. An adapter must reject an unknown/mismatched required profile rather than guess compatibility. Any claimed BM25 behavior needs its own declared scoring/statistics contract and verification.

Retries, repair, verification reads, pool waits and fallback consume the shared deadline and bounded attempt/candidate/call budgets. Check cancellation before further side effects, propagate it and release task-owned resources. Durable writes may survive cancellation; reconciliation uses the same intent. Do not claim cancellation undid them. Operational errors and degraded execution remain separate from sufficient/partial/insufficient coverage, and unknown coverage stays unknown.

Qdrant operation details are grounded in its [points documentation](https://qdrant.tech/documentation/manage-data/points/). Backend acknowledgment alone does not establish the cross-store barrier.

## Failure boundary inventory

Each row has a corresponding fixture case. Rows describe required behavior; V5-02/03/04 must supply executable evidence before implementation acceptance.

| Row | Boundary or input | Required stored outcome and reader behavior | Planned assertions |
| --- | --- | --- | --- |
| QD-W01 | Intent/job create fails or acknowledgment is lost | No publication; reconcile durable intent and payload binding before resume. | V5-04 |
| QD-W02 | Immutable source stage fails or acknowledgment is lost | Prior active remains; compare source identity/digest before retry. | V5-04 |
| QD-W03 | Chunk manifest write stops partway | Incomplete staging cannot become ready; reconcile exact members. | V5-04 |
| QD-W04 | Vector write stops partway or acknowledgment is lost | No publication; inspect same scoped points and retry missing writes. | V5-04 |
| QD-W05 | Full vector write completes before verification | Complete counts are insufficient; generation stays unpublished. | V5-04 |
| QD-W06 | Verification succeeds before prepared commit fails | Reverify as necessary; no active-pointer change without verified preparation and the atomic publication mutation. | V5-04 |
| QD-W07 | Prepared record commits before publication | Prepared alone is invisible; prior active remains. | V5-04 |
| QD-W08 | CAS commits but acknowledgment is lost | Authority resolves successful outcome; retry creates no second publication. | V5-04 |
| QD-W09 | Competing publisher changes expected active | Stale CAS fails; newer active remains. | V5-04 |
| QD-W10 | Physical point reservation conflicts or acknowledgment is lost | Atomic shared ownership prevents cross-document overwrite; reconcile the same claim before any vector write. | V5-02, V5-04 |
| QD-A01 | ACL revoke commits before payload replication | Old payload grant cannot reach provider or final release. | V5-03, V5-04 |
| QD-A02 | ACL replication acknowledgment is lost | Authority remains revoked; replay same replica update. | V5-03, V5-04 |
| QD-D01 | Tombstone commits before purge starts | All generations immediately ineligible. | V5-03, V5-04 |
| QD-D02 | Purge partly completes or acknowledgment is lost | Debris stays inaccessible; replay scoped purge. | V5-04 |
| QD-D03 | Delete or revoke races with repair | Fence prevents resurrection/publication or restored grants. | V5-03, V5-04 |
| QD-R01 | Source/authorization authority unavailable | No candidate text disclosed; operational failure stays explicit. | V5-03 |
| QD-R02 | Stale, unpublished or mixed revision candidate | Exclude from new search; resolve only exact authorized bytes. | V5-02, V5-03 |
| QD-R03 | Malformed scope, span, digest or profile replica | Quarantine; no payload text or arbitrary locator disclosure. | V5-02, V5-03 |
| QD-P01 | Sparse profile absent or mismatched | Unsupported/mismatch failure; no invented BM25 capability. | V5-02 |
| QD-P02 | Fallback, retry or verification exhausts budget | Preserve all scope/required filters; stop explicitly. | V5-02, V5-03, V5-04 |
| QD-P03 | Required mutation coordinator is absent | Reject the consistency profile; lease epochs alone do not enforce Qdrant write exclusion. | V5-02, V5-04 |

V5-01 documentation acceptance does not validate distributed durability, Qdrant configuration, model quality or cross-runtime adapter behavior. Those require the later scoped implementation and integration runs.
