# Cragkit wire contracts

Contract revision `0.1`, internal V0 foundation. Python and TypeScript implement this specification natively. This page defines wire validation and serialization; versioned adapter contracts below specify implemented runtime behavior. Shared fixtures are normative for their cases; runtime-specific malformed objects also need focused tests.

## Request and trusted scope

All objects reject unknown keys and all values retain their JSON type. Numbers are finite, with absolute value at most 9,007,199,254,740,991. Integer fields reject booleans and fractional numbers; integer-valued numbers such as `1.0` normalize to `1`. Text must contain valid Unicode scalar values; limits count UTF-8 bytes. A nonblank string must contain something beyond ASCII space, tab, CR, LF, form feed and vertical tab. Preserve accepted text exactly, including leading whitespace. Before recursive schema validation, reject cyclic/non-JSON native values, inputs exceeding 4,096 value nodes, or inputs deeper than 32 levels (root level zero); repeated references are counted at each occurrence.

`RetrievalRequest`: `query` and `collection` are required. Defaults: `schema_version: "0.1"`, `request_id` generated as UUID text if absent, `required_filters: []`, `search_hints: []`, `limits: {}` and `output_profile: {}`. Explicit null does not mean absent. Query is nonblank, at most 16,384 bytes. Collection is nonblank, at most 128 bytes. Request IDs and other identity strings are nonblank, at most 256 bytes. Caller-provided IDs are tracing labels and confer no authority. Identity strings, queries, collections, search hints and string filter values reject NUL (`U+0000`) in both runtimes (NUL-r1). Exact source/evidence text retains its bytes; it is never stripped or normalized by this input rule. PostgreSQL adapters also revalidate before leasing a connection.

`ToolRequest` exposes only `schema_version`, optional/generated `request_id`, `query`, `collection` and `search_hints`, using the same rules. It cannot set scope, grants, required filters, limits or output profile. Applications bind those separately. `TrustedScope` is a separate object with required `tenant_id`, `principal_id`, `authorization_revision` identity strings and `grant_ids`, default `[]`, with at most 64 identity strings. Constructing it does not authenticate a caller. No query object contains trusted scope.

### Filters

`required_filters` has at most 16 roots, combined with AND. Leaves use allowlisted fields `document_id`, `revision_id`, `language`, `kind` and `tag`. Later adapters may reject unsupported fields. There is no raw SQL or provider expression input.

- Equality: `{ "op": "eq" | "ne", "field": <field>, "value": <scalar> }`.
- Order: `{ "op": "gt" | "gte" | "lt" | "lte", "field": <field>, "value": <number> }`.
- Membership: `{ "op": "in", "field": <field>, "values": [<scalar>, ...] }`, 1-32 values.
- Group: `{ "op": "and" | "or", "filters": [<filter>, ...] }`, 1-16 children.
- Negation: `{ "op": "not", "filter": <filter> }`.

A scalar is a finite number, boolean or string of at most 1,024 UTF-8 bytes; null is not supported in this revision. Across all roots, allow at most 64 nodes and eight levels, with a root at level one. Reject malformed or cyclic native inputs before recursive validation. Search hints are at most eight nonblank strings of at most 256 bytes.

### Limits and output profile

| Limit | Default | Accepted range |
| --- | --- | --- |
| `deadline_ms` | 10000 | integer 1-300000 |
| `max_attempts` | 3 | integer 1-10 |
| `max_subqueries` | 4 | integer 1-16 |
| `max_candidates` | 200 | integer 1-10000 |
| `max_context_tokens` | 2000 | integer 1-1000000 |
| `max_provider_calls` | 16 | integer 0-1000 |
| `max_spend_usd` | null | null or finite number 0-1000000 |

`OutputProfile` defaults to `renderer: "cragkit.context.v1"`, `tokenizer: null`, `envelope_reserve_tokens: 256` (integer 0-1000000) and `counting_mode: "estimated"`. Renderer/tokenizer identifiers use the identity-string rules. Strict mode requires a non-null tokenizer identity; actual tokenizer capability checks and hard counting are V3 work. V0 makes no hard-token-ceiling claim.

## Typed errors

Expose named errors and a closed wire envelope `{ "code", "message", "retryable" }`. Exception messages and serialization use the fixed safe message below; rejected inputs and provider/connection details are omitted. Validation helpers raise `InvalidRequest` without a raw validation-error chain. Cancellation will use native runtime cancellation in the execution phases.

| Class | Code | Message | Retryable |
| --- | --- | --- | --- |
| InvalidRequest | invalid_request | Invalid retrieval request. | false |
| UnauthorizedScope | unauthorized_scope | Access scope is not authorized. | false |
| UnsupportedCapability | unsupported_capability | Required capability is unavailable. | false |
| IndexNotReady | index_not_ready | Index is not ready. | true |
| EmbeddingProfileMismatch | embedding_profile_mismatch | Embedding profile does not match. | false |
| ProviderUnavailable | provider_unavailable | Provider is unavailable. | true |
| DeadlineExceeded | deadline_exceeded | Request deadline exceeded. | true |
| ContextBudgetTooSmall | context_budget_too_small | Context budget cannot fit the required envelope. | false |
| IntegrityViolation | integrity_violation | Source integrity validation failed. | false |

Public validation entrypoints: Python `cragkit.contracts` exports `parse_request`, `parse_tool_request`, `parse_scope` and their Pydantic models; TypeScript `cragkit/contracts` exports the same snake_case helpers, Zod schemas and inferred types. Error classes live in `cragkit.errors` / `cragkit/errors`. Collections in parsed models are immutable snapshots; modifying caller-owned input after validation cannot change the parsed request.

## Sources and evidence boundaries

Use the installed Pydantic strict APIs and Zod strict objects, checked against their current official documentation: [Pydantic strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/), [Pydantic model configuration](https://docs.pydantic.dev/latest/api/config/), [Zod schemas](https://zod.dev/api). Runtime support and dependency pins are in [development.md](../docs/development.md).

Schema files describe structural constraints. Byte limits, finite/safe numbers, recursive bounds and cross-field invariants remain normative even where JSON Schema cannot express them fully. Schema conformance alone does not prove relevance, authorization or retrieval quality.

## V2 optional PostgreSQL behavior

The unchanged 0.1 wire schemas also carry explicitly degraded execution from the trusted [HY-r1 retrieval configuration](HYBRID_V2.md). [IF-r1](IDENTIFIER_FUSION_V2.md) governs exact identifiers and fusion; [DN-r1](DENSE_V2.md) governs dense candidates. Constructor configuration and these adapter contracts do not add agent-editable scope, permission or fallback fields to ToolRequest.


## V3 reranker design boundary

[RK-r1](RERANKER_V3.md) defines the next optional reranker boundary and its [recorded examples](fixtures/reranking.json). The [shortlist decision](../docs/decisions/0002-reranker-policy.md) separates synthetic mechanics from real-model evaluation. V3-01 documents this design; executable adapters and their failure tests belong to V3-02. No public wire-schema change follows from the design record.


## V3 context representation

[TK-r1](TOKEN_CONTEXT_V3.md) defines the optional exact Evidence renderer and pinned local cl100k tokenizer pair. Strict context counting includes citations and the declared wrapper reserve; estimated mode remains labelled. This standalone boundary does not change the legacy PostgreSQL retrieval default.

[PK-r1](PACKING_V3.md) defines bounded exact-source expansion/merging, whole-span selection, aliases and final context recounting. It requires caller-authorized immutable sources and does not infer coverage.

[AS-r1](ASSESSMENT_V3.md) defines conservative query-bound reviewed-anchor coverage and emitted-reference validation. Curated matching is not a general semantic judge or proof of source truth.

[EP-r1](EVIDENCE_PIPELINE_V3.md) combines packing with emitted-only assessment and one bounded rebalance. Its explicit PostgreSQL constructor option preserves trusted scope and reauthorizes after optional reranking.

## V5 alternative-store design

[QD-r1](QDRANT_V5.md) and [ADR 0003](../docs/decisions/0003-qdrant-consistency.md) specify authoritative source resolution, atomic publication, sparse identity and bounded repair for the optional Qdrant profile. The [scenario fixture](fixtures/qdrant_consistency.json) records design expectations. Executable adapter and recovery acceptance belong to V5-02 through V5-04; these documents introduce no runtime API.
