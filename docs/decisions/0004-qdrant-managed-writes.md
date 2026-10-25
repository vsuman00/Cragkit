# ADR 0004: Restricted managed Qdrant writes

Status: V5-04A design. No runtime publication acceptance is implied.

## Context

A durable SQL owner token cannot stop a request that passed its last fence check and paused before HTTP. Qdrant does not compare the document's SQL mutation epoch when applying an upsert. A replacement admitted after lease expiry could therefore be overwritten by the old request. Readback alone cannot prove that request will never arrive.

The existing [QD-r1 decision](0003-qdrant-consistency.md) requires physical ownership claims, complete verification, fresh source authorization and genuine old-writer exclusion. V5-04 must define an executable reference profile before implementing publication and repair. [QW-r1](../../contracts/QDRANT_PUBLICATION_V5.md) supplies the normative protocol.

## Decision

Use durable per-document CAS ownership and a dispatch journal committed before every Qdrant side effect. Reserved entries are uncertain after a crash even when a later dispatched marker is absent. No successor clears them on lease expiry.

The initial reference is a managed single-node Qdrant 1.20.0 instance with optional PostgreSQL 17 authority. An application-owned exclusive supervisor outlives writer/coordinator processes and alone controls the server, durable directory and write-key rotation. Native Python and Node use the same capability boundary without a required Python service for Node.

Normal writes require `wait=true` completed acknowledgment followed by exact full membership, payload and named-vector readback. Publication is one authority CAS binding the verified preparation, expected prior active pointer, current security fences and intent outcome. There is no open SQL transaction across an HTTP call.

An uncertain write triggers an instance-wide recovery gate. Quarantine all old-epoch work, retire old writer capabilities, stop the owned server, rotate its write key and restart the same durable storage. Old transports keep their old credential and must receive actual mutation-endpoint denial. Verify supported `optimizer_config.prevent_unoptimized=false`: pinned Qdrant's false path completes full WAL replay/flush during loading, while true can replay a tail asynchronously. Reconcile every quarantined operation before reopening admission. A health response or caller-supplied drained flag is insufficient. [Pinned load and replay source](https://github.com/qdrant/qdrant/blob/v1.20.0/lib/collection/src/shards/local_shard/mod.rs).

The supervisor issues opaque attempt capabilities bound to physical instance and epoch. This does not make supervisor loss automatically recoverable. If its exclusive ownership is lost or a paused old controller could resume lifecycle operations, writes remain blocked until explicit out-of-band recovery establishes safe ownership. Trusted administrators are outside this protocol. A hosted endpoint without an equivalent verified drain/fencing capability is unsupported.

Authority revocation and tombstone commit immediately even during blocked recovery. Delayed old replica grants never authorize source release: QS-r1 rereads current authority before provider and final release. Replica repair uses current ACL/metadata and does not restore an old intent snapshot.

Generation manifests bind immutable source bytes, exact spans, full profile descriptors, QC-r1 physical UUID tuples and domain-separated length-framed float32 input identity. Arbitrary decimal JSON hashes are insufficient. Validate original inputs, round to binary32 nearest/ties-even, reject nonzero underflow and overflow, and canonicalize signed zero. Qdrant Cosine may normalize input differently across scalar/SIMD paths, so dense readback uses the fixed component, norm and L2 bounds in QW-r1 around an explicitly ordered binary64 normalization. Sparse indices and binary32 values match exactly. The dense rule deliberately accepts a bounded equivalence class, not exact stored-byte identity. Native nontrivial normalization and tolerance probes remain required; same-dimensional wrong vectors outside the declared bounds fail.

Additive authority migration `0002` will preserve applied `0001` bytes and declare a new exact history/catalog profile. Old source readers reject that new catalog; a bounded compatibility child supports the old source-only and new publication profiles explicitly. Writer privileges remain separate from read-only source roles and do not weaken reader RLS.

## Consequences

Writer-manager crashes can be repaired while the exclusive supervisor survives. Recovery affects the whole physical instance, so mutations for other documents pause too. Read authorization and immediate authoritative denial remain available; availability is deliberately bounded by the ability to prove old effects are settled.

The library borrows pools, transports and the supervisor. It introduces no automatic migration, provider call, hidden reconnect loop, permanent elevated role or automatic controller takeover. Native acceptance must exercise a live paused old writer, key rejection, durable replay, exact readback and manager restart in both runtimes. Synthetic scenarios and mocks do not establish these facts.

This excludes arbitrary distributed or externally managed Qdrant write profiles until they provide equivalent tested guarantees. It does not claim universal crash durability, source truth, relevance, production readiness or recovery from loss of the supervisor's trusted control boundary.

## Alternatives considered

SQL leases and epochs alone cannot fence already-admitted HTTP requests. An expiring lock therefore cannot justify takeover. Re-reading an expected point also cannot exclude a future delayed write.

Holding a PostgreSQL row lock or connection across network calls consumes scarce resources and still cannot undo an external side effect after the connection dies. The protocol uses short transactions and durable uncertainty instead.

A shared mutable credential would let stale workers regain access after rotation. Immutable transport credentials and fresh opaque supervisor capabilities keep old workers fenced. A plain boolean recovery result cannot establish process or credential exclusion.

Automatic supervisor takeover would require an independently proven lifecycle exclusion mechanism across both runtimes. It is outside the first reference profile, rather than inferred from a PID, timeout or expired database lease.
