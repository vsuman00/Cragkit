# Shared contracts

These contracts define the native Python and TypeScript boundaries. Runtime schemas, shared deterministic cases and SQL capability definitions remain available to contributors. Historical evaluation, release-workflow and execution records are maintained in the private validation workspace; see the [current development guide](../docs/development.md).

## Runtime contracts

- [Artifact licensing checks](ARTIFACT_LICENSING_V6.md)
- [AS-r1: Conservative reviewed-span assessment](ASSESSMENT_V3.md)
- [Scoped exact dense candidates DN-r1](DENSE_V2.md)
- [Embedding adapter contract E-r1](EMBEDDINGS_V2.md)
- [EP-r1: Post-packing assessment and optional PostgreSQL integration](EVIDENCE_PIPELINE_V3.md)
- [V4 execution contract](EXECUTION_V4.md)
- [V2-07 hybrid orchestration contract (HY-r1)](HYBRID_V2.md)
- [V2-06 identifier and fusion contract (IF-r1)](IDENTIFIER_FUSION_V2.md)
- [V1-09 lifecycle contract L-r1](LIFECYCLE_V1.md)
- [Optional retrieval-only MCP host](MCP_V5.md)
- [PK-r1: Extractive evidence packing](PACKING_V3.md)
- [PGO-r1: Explicit PostgreSQL OpenAI profile](POSTGRES_OPENAI_V6.md)
- [Qdrant candidate contract](QDRANT_CANDIDATES_V5.md)
- [Qdrant corrective integration: QCC-r1](QDRANT_CORRECTIVE_V5.md)
- [Qdrant publication and managed repair](QDRANT_PUBLICATION_V5.md)
- [Qdrant security-owner and managed erasure profile](QDRANT_PURGE_V5.md)
- [Public current-security convergence](QDRANT_SECURITY_CONVERGENCE_V5.md)
- [V5 current-security SQL guard (SG-r2)](QDRANT_SECURITY_GUARD_V5.md)
- [Qdrant authoritative source reads](QDRANT_SOURCES_V5.md)
- [Qdrant consistency contract](QDRANT_V5.md)
- [Migration and recovery rehearsal (MRR-r2)](RECOVERY_REHEARSAL_V6.md)
- [V3-01 reranker boundary (RK-r1)](RERANKER_V3.md)
- [Evidence and result contract, revision 0.1](RESULTS.md)
- [V1-08 runtime contract E-r1](RETRIEVAL_V1.md)
- [TK-r1: Exact context rendering and token counting](TOKEN_CONTEXT_V3.md)
- [Vector generation contract VG-r1](VECTOR_GENERATIONS_V2.md)

## Schemas and shared cases

- [Request schema](schemas/0.1/request.schema.json)
- [Trusted scope schema](schemas/0.1/scope.schema.json)
- [Tool request schema](schemas/0.1/tool-request.schema.json)
- [Result schema](schemas/0.1/result.schema.json)
- [Deterministic fixtures](fixtures/)
- [Qdrant authority catalog](QDRANT_AUTHORITY_CATALOG_V5.sql)
- [Qdrant purge capabilities](sql/qdrant_purge_capabilities.sql)

Update native behavior and the applicable shared contract together. An exact source excerpt does not prove source truth or relevance. Fake-provider parity does not establish live-model quality.
