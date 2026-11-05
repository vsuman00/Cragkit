# Qdrant candidate contract

Revision `QC-r1`; V5-02A design boundary, subordinate to [QD-r1](QDRANT_V5.md), [wire validation](README.md), [E-r1](EMBEDDINGS_V2.md) and [EL-r1](EXECUTION_V4.md). The [fixtures](fixtures/qdrant_candidates.json) are normative synthetic expectations. No native adapter or public API is implemented by this document.

For example, a point carrying yesterday's grant can nominate a document identity. It cannot supply authorized text: V5-03 must check the active published generation and today's authoritative grants before any provider sees bytes.

## Reference profile and ownership

The selected baseline is Qdrant server `1.20.0`, optional Python `httpx==0.28.1` on Python `3.14.6`, and Node `26.5.0` built-in `fetch`. These access the same REST API natively. The first isolated target is one loopback-only single-node server on macOS arm64. V5-02A evidence (record retained in the private maintainer archive) separates version selection, transport prototypes and server readiness from later adapter acceptance. Reject an unverified server/client or distributed profile with `UnsupportedCapability`; do not auto-upgrade or create services.

Official `qdrant-client==1.20.0` and `@qdrant/js-client-rest@1.20.0` archives were inspected as alternatives. They are not the selected runtime dependency profile: their default request paths do not establish this contract's streaming byte bound and request cancellation together. A later SDK binding must demonstrate those guarantees before acceptance. This choice also avoids adding the Python SDK's NumPy and gRPC dependencies for a REST-only adapter. No SDK package is installed by QC-r1.

Trusted application configuration binds endpoint, physical collection, backend namespace, collection incarnation, named vector configuration, profile descriptors and limits. Caller-owned clients remain caller-owned. Construction/import does not connect, create collections, apply migrations, discover credentials, download models or call providers. Query input cannot change this configuration or trusted scope.

The candidate boundary receives already encoded dense and/or sparse vectors, the validated request, trusted scope, shared deadline and ledger. It never encodes text. Snapshot native JSON input, scope, vectors, filters and trusted descriptors before any await; reject unknown fields, invalid native values, cycles and unchecked model instances. Follow wire identity/NUL and complexity limits without coercing booleans to numbers.

Dense name `dense` uses Qdrant `Cosine`, 1536 dimensions and an exact supported E-r1 descriptor. The initial profile uses `fake_embedding_1536_v1`; the [E extension](#e-extension-embedding-batch-binding) adds `openai_te3small_1536_r1` for dense-only deployments. Values are finite and nonzero with L2 norm within `0.001` of one.

Sparse name `sparse` uses explicit caller-supplied vectors and this exact synthetic descriptor:

```json
{"profile_id":"fake_manual_sparse_v1","encoder":"caller_supplied_fixture","model":"none","revision":"1","vocabulary":"fixture_uint32_v1","preprocessing":"none","weighting":"caller_supplied","corpus_statistics_revision":"none"}
```

These tiny bounds define the synthetic reference profile, not general Qdrant limits. Sparse vectors have parallel `indices`/`values` arrays with 1-16 entries, strictly increasing unique unsigned 32-bit indices, and finite strictly positive numeric values that remain finite and positive when represented as float32. Reject overflow or underflow to zero; do not silently replace values. No automatic inference, IDF modifier, BM25 claim, model runtime or corpus-statistics discovery is permitted. Dense-only configuration represents absent `sparse_profile` as null and `sparse_profile_id` as the empty string. A requested branch absent from the configured collection fails before query dispatch.

## Physical identity and payload

Derive a lowercase UUIDv5 using RFC URL namespace `6ba7b811-9dad-11d1-80b4-00c04fd430c8`. Its name is compact UTF-8 JSON of this ordered, all-string array; preserve Unicode exactly, with no whitespace, normalization or ASCII-only escaping:

```text
["cragkit.qdrant.point.v1",backend_namespace,physical_collection,collection_incarnation,tenant_id,collection,document_id,revision_id,generation_id,chunk_id,dense_profile_id,sparse_profile_id]
```

Use standard JSON escaping for quotes, backslashes and controls; reject unpaired surrogates. This contains no floats. A raw digest or an integer point ID is not a compatible identity. UUID derivation does not guarantee collision freedom. QD-r1's shared atomic physical ownership registry must reserve the ID before any point write, compare the complete identity/profile claim and preserve fencing across ambiguous writes and collection recreation. This document does not implement that registry or publication.

Each point payload contains these fields:

| Fields | Meaning and validation |
| --- | --- |
| `backend_namespace`, `physical_collection`, `collection_incarnation` | Exact trusted physical namespace; never accepted from query input. |
| `tenant_id`, `collection`, `document_id`, `revision_id`, `generation_id`, `chunk_id` | Full scoped immutable identity; wire identity limits. |
| `dense_profile_id`, `sparse_profile_id`, `dense_profile`, `sparse_profile` | IDs and full exact descriptors must agree with trusted configuration. An ID match alone is insufficient. |
| `start_byte`, `end_byte` | Safe integers, `0 <= start_byte < end_byte`, canonical UTF-8 half-open span. |
| `source_sha256`, `text_sha256` | Lowercase 64-hex digests of canonical UTF-8 source and exact excerpt respectively; these remain unverified until authoritative source resolution. |
| `principal_ids`, `grant_ids`, `authorization_revision` | Bounded wire identity replicas; arrays have at most 64 entries each. The revision is carried, never used to grant authority. |
| `language`, `kind`, `tag` | Optional scalar strings following wire string-value limits; absent means no match. Arrays, numbers, booleans and null are incompatible. |

No source text, query text, excerpt or provider output is part of a candidate payload/projection. Request only the declared payload fields and no vectors in search responses. Reject unexpected response payload fields rather than releasing them. Recompute the UUID from every returned full tuple and compare the Qdrant point ID. Validate replicas and profiles even when the backend reports success. Mutable ACL/filter fields do not alter the immutable UUID or manifest identity.

## Scope and required filters

Every branch applies `tenant_id == scope.tenant_id AND collection == request.collection AND (principal_ids contains scope.principal_id OR grant_ids intersects scope.grant_ids) AND required_filters`. Empty grants leave only the principal arm. Never let a required-filter OR group escape the outer scope conjunction. Do not compare payload `authorization_revision` as proof of current permission. A stale replica may suppress new grants; report this limitation without broadening the search.

QC-r1 supports string `eq` and `in` on `document_id`, `revision_id`, `language`, `kind`, `tag`; nonempty nested `and`/`or` groups retain wire node/depth/value limits. Multiple roots form AND. Missing scalar fields match neither equality nor membership. No string case folding, coercion or array semantics are added.

| Cragkit condition | Qdrant filter mapping |
| --- | --- |
| String equality | Field condition `match: {value: string}`. |
| String membership | Field condition `match: {any: [strings]}`. |
| AND group / required roots | Nested filter `must: [conditions]`. |
| OR group | Nested filter `should: [conditions]`, at least one match; remains inside outer `must`. |
| Principal / grant replica | `match.value` for principal membership, `match.any` for nonempty grants, inside the scope OR. |

Well-formed wire `ne`, order operators, `not`, numeric/boolean leaves and unsupported vector/profile capabilities raise `UnsupportedCapability` before any network request. Malformed ASTs, unknown fields, invalid types or excess complexity raise `InvalidRequest`. No raw backend expressions, filter dropping, lexical fallback, unfiltered retry or client-side postfilter as a substitute for backend filtering is allowed. Defensive response checks supplement backend filtering.

## Query and result boundary

Use the universal point query endpoint with the explicit named vector (`using`), caller vector (`query`), complete `filter`, positive bounded `limit`, declared payload projection and `with_vector: false`. Dense and sparse are separate branch queries; QC-r1 specifies no native fusion, prefetch, reranking, identifier branch or score comparability. Keep deterministic branch order dense then sparse when both are requested. The orchestrator may later fuse validated nominations under a separately declared contract.

Before dispatch, allocate a positive integer limit to each requested branch. Their sum is at most the minimum of 64, request `max_candidates` and the admitted remaining candidate-work allowance. The 64-item ceiling belongs to QC-r1; the wire permits `max_candidates` up to 10000. Insufficient allowance for all requested branches fails admission before the first dispatch; never silently omit a branch. Reserve cumulative candidate work for allocated limits, not returned hits; avoid double reservation when the outer coordinator already owns that allocation. Serial queries are sufficient. At most one backend query per branch, zero transport retries, bounded in-flight work and no unbounded queue. Backend queries are not model/provider calls; account any separately configured transport attempt honestly.

Bound the compact query body to 262144 UTF-8 bytes and each raw response to 1048576 bytes before full materialization. Input follows wire limits of 4096 value nodes and depth 32; response parsing rejects duplicate object keys, invalid UTF-8, nonfinite numbers, numeric literals longer than 128 characters, depth above 32 and more than 32768 value nodes. Check result count against the allocated branch limit. Reject a transport/client integration that cannot enforce response-byte bounds before unbounded buffering. There is no pagination or candidate expansion in QC-r1.

The reference transport uses Python `AsyncClient.stream` with bounded raw chunk accumulation and response closure, or a Node `Response.body` reader with bounded accumulation and reader cancellation. An outer monotonic deadline covers headers, body and parsing. Set `Accept-Encoding: identity` and reject other content encodings; disable redirects, ambient proxy/credential discovery and automatic retries. A borrowed transport must declare and meet the same behavior. HTTPS requires certificate and hostname verification; plaintext HTTP is confined to an explicitly configured loopback development target. Never install a process-global fetch hook, disable certificate checks or change unrelated client settings. Transport prototypes and their adversarial checks do not implement the candidate adapter. [HTTPX async streaming](https://www.python-httpx.org/async/), [Node 26.5 fetch](https://nodejs.org/download/release/v26.5.0/docs/api/globals.html#fetch).

Both branches use the same effective monotonic deadline and cancellation scope. Derive each backend timeout from the remaining deadline and also bound the outer await; a rounded server timeout cannot extend the request. Recheck deadline/cancellation after parsing. Propagate native cancellation, observe late failures, and do not dispatch another branch after termination. Do not close caller-owned resources. Any retry requires a later explicit contract and fresh ledger admission; hidden SDK retries are forbidden.

The future result is a text-free list of `UNVERIFIED` nominations, with full validated payload, point ID, branch and raw score semantics. Dense raw score is finite cosine similarity, higher is better. Accept `[-1.000001,1.000001]` to allow float32 roundoff around the mathematical `[-1,1]` range; preserve the raw score without clamping. Sparse raw score is finite dot-product similarity, higher is better. Do not put these scores into the existing `DenseCandidate` cosine-distance field. The same identity may occur once per branch; reject duplicate IDs or scoped chunk identities within a branch and contradictory cross-branch payloads. Preserve both branch scores without inventing extra votes or fusion.

Response validation rejects excess rows, missing identities, mismatched scope/required-filter fields, full-profile mismatch, invalid digest/span/UUID, malformed score, nonfinite values or incompatible response shape with `IntegrityViolation`. A structurally valid empty response means zero nominations, not insufficient coverage or a completed source search. Qdrant omissions or approximate ranking establish neither source completeness nor relevance.

## Failures and later gates

### Native binding for V5-02B/C

The planned Python module `cragkit.qdrant` and Node subpath `cragkit/qdrant` expose `QdrantSearchStore`, `point_id` and a native REST transport (`HttpxQdrantTransport` / `FetchQdrantTransport`). Python uses `QdrantSearchStore(config, transport)`; Node uses the same two constructor arguments. `config` contains exactly `backend_namespace`, `physical_collection`, `collection_incarnation`, `dense_profile` and `sparse_profile`. The physical collection is a safe ASCII segment matching `[A-Za-z][A-Za-z0-9_-]{0,63}`. Profile descriptors follow the rules above. The transport owns endpoint and explicit credentials separately; no query can supply them.

`initialize` explicitly checks server version, disabled cluster mode and the collection's dense/sparse configuration, replication factor and write consistency before searches. It neither provisions storage nor asserts complete QD-r1 source/publication compatibility. `capabilities()` declares this candidate-only boundary and its unsupported capabilities. `search_candidates` receives request plus trusted scope, encoded vectors, exact branch-limit mapping, shared `ExecutionLedger`, external monotonic deadline and Node's optional abort signal. Python passes the latter fields as keyword arguments; Node passes an options object. The store owns one reservation for the total allocated candidate slots, dispatches it before the first branch, and settles/abandons it once; an outer coordinator must not reserve those same slots again. The effective deadline is the minimum of the external deadline, ledger deadline and request duration from call entry. No model usage or provider call is inferred from a database request.

Both bindings return immutable nominations shaped as `{point_id, branch, score, score_kind, score_direction, verification, payload}`; `branch` is `dense` or `sparse`, `score_kind` is `cosine_similarity` or `dot_product`, `score_direction` is `higher_is_better` and `verification` is `UNVERIFIED`. Full payload fields retain their native immutable representation and JSON serialization. `point_id` accepts the ordered tuple defined above. A transport request takes method, same-origin path, optional compact body bytes, remaining deadline, maximum response bytes and Node cancellation; it returns bounded bytes. Transport constructors accept endpoint and explicit API key; imports remain driver-free. `close` is idempotent, rejects new work and cancels/drains owned work within a documented bound. Stores borrow injected transports by default; transport closure belongs to their owner. These are implementation requirements, not an implementation claim.

QC-r1 integer fields, including descriptor dimensions and server metadata, follow wire numeric semantics: an integral JSON number such as `1536.0` is equivalent to `1536`. Booleans, fractions, nonfinite values and unsafe integers are rejected. This boundary does not change the existing E-r1 implementation. Default Node fetch rejects environment proxy startup flags, including forms supplied through `NODE_OPTIONS`, and disabled certificate verification before dispatch. Borrowed transports must uphold the declared security profile; their mutable error messages are replaced with safe typed errors.

| Condition | Outcome |
| --- | --- |
| Malformed native input/configuration or request | Redacted `InvalidRequest`, no dispatch. |
| Valid but unsupported operator/profile/version/consistency or missing transport bound | Redacted `UnsupportedCapability`, no query dispatch. |
| Shared admission exhausted | Existing private `BudgetExhausted` transition; coordinator reports budget limitation, no omitted mandatory branch. |
| Deadline / caller cancellation | `DeadlineExceeded` / native cancellation; never evidence insufficiency. |
| Backend unavailable, connection failure, non-success transport response | Redacted `ProviderUnavailable`; no implicit retry or empty-success conversion. |
| Invalid successful backend response or identity/profile contradiction | Redacted `IntegrityViolation`; discard the batch. |

Never expose backend exception text, endpoint credentials, raw query/body/response or scope in logs/errors. No candidate establishes authoritative source availability or authorization. V5-03 must resolve active published generation, tombstone, current grants, current required metadata, exact canonical bytes/spans/digests and profiles before any provider disclosure, then freshly authorize final release. Source authority unavailability is operational failure. V5-04 owns registry-backed ingestion, publication and repair. V5-02B/C own native adapters; V5-02D must demonstrate this contract against the isolated server serially before candidate-adapter acceptance.

## E extension: embedding batch binding

V5-02E extends QC-r1 without changing QD-r1, E-r1 or EL-r1. The [shared batch cases](fixtures/qdrant_embedding_batches.json) are normative for this extension. Accept the exact E-r1 `OPENAI_PROFILE` descriptor as well as `FAKE_PROFILE`. The OpenAI profile supports a genuine dense-only collection: `sparse_profile` is null, the sparse profile ID is empty, and collection metadata contains no sparse vector configuration. OpenAI plus any sparse profile fails `UnsupportedCapability` before I/O. Synthetic manual sparse vectors remain a separate fake-profile mechanics configuration; no sparse text encoder is provided.

Export `bind_embedding_batch(batch, profile, expected_items=None)` in Python, with `expected_items` keyword-only, and `bind_embedding_batch(batch, profile, {expected_items?})` in Node. Accept an E-r1 batch or its native JSON representation. Revalidate and snapshot every field, including unchecked model copies; return an immutable E-r1 batch. Bound admission to eight vectors, 16,384 value nodes and depth 8 before copying the full batch. String values have at most 1024 UTF-8 bytes and object keys at most 256; reject excessive character counts before encoding or scanning strings. The expected item count, when supplied, is an integer in 1..8. Every vector has 1536 finite components and unit L2 norm within 0.001, with no implicit normalization. Full descriptors must match the supported expected profile. Wrong descriptors or dimensions, or a synthetic flag inconsistent with the provider, fail `EmbeddingProfileMismatch`; malformed structure, usage or vector values fail `InvalidRequest`.

Require exactly one declared provider call. Usage token counts are both null or both integers in 0..2147483647, with total at least prompt. Cost is finite and nonnegative. Fake usage has known zero cost. Real usage is either estimated with a finite cost in 0..1000000 or unknown with null cost; never relabel an estimate as verified billing. Unknown usage stays unknown. Binding an already computed batch makes no provider call and must not charge its work again.

`search_candidates` accepts a bound batch through its existing `dense` argument and requires exactly one vector for a query. Raw dense arrays remain supported only for the fake profile. A real-profile raw array fails `EmbeddingProfileMismatch`, since it carries no profile binding. Batch validation occurs before Qdrant dispatch. Immutable point identity and candidate payloads continue carrying the selected full profile and IDs; a same-dimensional wrong model fails closed. SourceStore manifests and publication must retain the same binding in V5-03/04.

The bounded example composes the existing E-r1 adapter with this boundary. Its injected transport reserves and dispatches one provider slot only when E-r1 actually invokes transport, and settles that slot after response validation. Failed or cancelled dispatched work keeps unknown usage; preflight denials make zero provider calls. Qdrant candidate work has a separate reservation. Share one effective deadline and cancellation across both operations. Keep the returned E-r1 estimated cost separately; record unknown ledger cost for estimated or unavailable live billing, rather than reporting a known charge. The existing E-r1 live policy, accurate tokenizer and trusted transport remain mandatory. Examples default to fake execution and discover no credentials or live endpoints.

Real-profile routing uses explicit test spies only, with no vectors persisted under real model identity. Actual dense-only backend mechanics use the fake profile. Neither kind of test establishes embedding quality, live availability or billing. V5-02 exits only after both native runtimes pass this extension and dense-only backend checks, alongside the initial hybrid mechanics checks.
