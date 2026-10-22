# Vector generation contract VG-r1

V2-04 uses optional, explicit numbered setup artifacts and one synthetic profile table. Lexical migration history remains unchanged. A-r2's managed primitive exposure remains explicit: runtime schema USAGE permits ordinary lookup of platform-owned scalar functions. Application data permissions and scoped RLS remain mandatory. No permanent runtime grant or permissive tenant policy is supplied.

## Storage and capability

B-r1 registry fields match E-r1 exactly: profile_id/provider/model/dimensions/tokenizer/normalization, plus an allowlisted storage_table. The first provisioned profile is fake_embedding_1536_v1/fake/fake_embedding_model_v1/1536/fake-byte-v1/l2. The hosted OpenAI profile is not provisioned. Equal dimensions do not establish compatible spaces. Native vector work must check extension/schema/catalog, both setup checksums and exact registry identity before any model call. Lexical-only operations do not require vector storage.

The table cragkit.chunk_vectors_fake_1536 stores full tenant/collection/document/revision/generation/chunk identity, embedding_profile and embedding. Composite foreign keys bind the chunk and generation's embedding profile. Values must be finite, dimension 1536 and l2 norm within 0.001, matching E-r1; the dimension is a provisioned-profile property. Registry identities are immutable. Additional profiles require explicit future provisioning.

The canonical read-only capability query is [vector_capability.sql](../storage/postgres/queries/vector_capability.sql). Native copies must be semantically identical. Missing tables/functions, mismatched history or unsupported stored profile fail typed UnsupportedCapability; mismatched returned embedding profile fails EmbeddingProfileMismatch. Model and runtime failures cannot become missing evidence.

## Native staging and publication

PostgresVectorIndexer binds resource, trusted write authorizer and E-r1 embedding adapter. VectorIngestionReceipt extends the lexical receipt with embedding_profile, provider_calls and per-invocation usage. Replays report zero new calls and no historical usage; failed operations return typed errors, not successful zero-cost receipts.

Stage and publish accept the same full source/options as lexical ingest so both independently recompute content identity, source/metadata snapshots and expected pointer. Neither accepts an editable receipt as publication authority. Ingest is convenience stage followed by publish. Native naming remains snake_case.

Identity revision reuses lexical immutable revision identity. Let base_payload be the existing lexical ingestion payload hash. Vector payload is SHA-256 of compact UTF-8 JSON `["cragkit.vector-ingest.v1", base_payload, [profile_id,provider,model,dimensions,tokenizer,normalization]]`; generation is SHA-256 of compact UTF-8 JSON `["cragkit.vector-generation.v1", payload]`. Both runtimes use the existing canonical metadata/hash rules; source/options/profile changes under one intent are rejected.

C stages canonical/chunk/lexical records without publishing, then calls the provider outside any lease/transaction and commits bounded vector batches. One operation per indexer, zero waiting queue; defaults at most 128 batches and 8 resume attempts, configurable downward only. Adapter item, byte and token limits apply to every batch. A running identical intent resumes missing vectors; succeeded replay verifies readiness without another provider call. Changed payload is InvalidRequest; exhausted/in-flight/conflicting state is IndexNotReady. Partial staging remains invisible and retryable. No automatic model retry is added.

D publishes in a short transaction after reauthorization, exact job/revision/generation/profile checks, and matching chunk/lexical/vector counts. It marks ready and switches the expected active pointer atomically; source/metadata belong to the same recomputed payload. It validates current document authorization revision, principal/grants and tombstone before writes. The existing source-release policy permits an authorized retained immutable revision; no mixed text is allowed. A callback before publication supports deterministic failure/race probes. No model call runs inside publication.

A failure after partial vectors preserves the exact prior active pointer. A slower build cannot overwrite a newer published generation. A revoked grant or tombstone stays denied even if an older generation remains stored. Native cancellation/deadline helpers own rollback, bounded release and close behavior; borrowed pools remain caller-owned.

## Verification boundary

Root serializes fake-provider unit/conformance tests and dedicated native LOGIN suites, with at most two native clients including the fixture owner. Shared cases and native evidence cover mismatch, interruption, incomplete/mixed generations, CAS conflict, exact prior lexical usability and authorization changes. Synthetic vectors establish mechanics and parity, not hosted model quality. Dense ranking remains V2-05.
