# Evidence and result contract, revision 0.1

This extends [the request contract](README.md) and uses its strict objects, scalar Unicode, safe finite numbers, integer normalization and native-input bounds. Result validation checks declarations and internal consistency. V1-08 now performs scoped source authorization and canonical source/digest verification in the native PostgreSQL runtimes. Coverage assessment and strict tokenizer-based counting remain later executable stages.

## Envelope and evidence

`RetrievalResult` has required `request_id` and `status` (`sufficient`, `partial`, `insufficient`). Defaults: `schema_version: "0.1"`, `execution: "complete"` (`complete` or `degraded`), `evidence: []`, `facets: []`, `context: ""`, `usage: {}`, `limitations: []`, `trace_id: null`, `versions: {}`. Request/trace IDs use the request identity rules. Context is scalar Unicode up to 262,144 UTF-8 bytes and is preserved exactly; V0 does not render or pack it.

At most 64 `Evidence` values are allowed. Each requires identity strings `evidence_id`, `collection`, `document_id`, `revision_id`, `chunk_id` and `source_locator`; the latter is an opaque application label, never fetched or interpreted as executable markup. Required `start_byte` and `end_byte` are safe nonnegative integers, start inclusive and end exclusive. Required `text` is nonempty scalar Unicode, at most 32,768 UTF-8 bytes. Require `end_byte > start_byte` and `end_byte - start_byte == len(text.encode("utf-8"))`.

Required `source_sha256` and `text_sha256` are lowercase 64-digit hex strings. Verify `text_sha256` against the excerpt's UTF-8 bytes. For each `(collection, document_id, revision_id)` in a result, all source digests must agree. At source release, the full source digest is verified against the immutable canonical source; checking its syntax does not establish source fidelity or truth. IDs remain strings, including IDs beyond JavaScript's safe integer range. Evidence IDs are unique within a result. Parsed revisions and collections are immutable snapshots.

## Facets and evidence estimates

At most 32 `Facet` values are allowed. Required fields: identity `facet_id`, nonblank `question` up to 2,048 UTF-8 bytes and `state` (`supported`, `missing`, `unknown`, `conflicting`). Defaults: `required: true`, `evidence_ids: []` (at most 64 unique identity strings), `assessment_method: "none"`, `assessment_version: "0"`; method and version use identity rules.

Facet IDs are unique. Every evidence reference must identify evidence actually returned. Supported facets require at least one evidence ID; conflicting facets require at least two distinct evidence IDs; missing facets have none. Any state except unknown requires a method other than `none`. Unknown facets may reference potentially useful evidence without asserting support.

Sufficient requires at least one required facet, all required facets supported, no unresolved required conflict, and a declared policy other than `unassessed.v0`. Partial requires at least one evidence item and may conservatively include supported, missing, unknown or conflicting facets. Insufficient makes no support promise. Execution is independent of the evidence estimate.

`Limitations` are strict objects with required `code`: `coverage_unknown`, `incomplete_facets`, `stale_evidence`, `truncated_evidence`, `budget_exhausted` or `degraded_search`. Defaults: `facet_ids: []` (max 32 unique IDs) and `evidence_ids: []` (max 64 unique IDs). References must resolve to returned facets/evidence. At most 32 limitations are allowed. Degraded execution requires at least one `degraded_search` limitation, so an operational fallback remains visible. These objects contain codes and IDs rather than arbitrary provider error text.

## Usage and versions

| Usage field | Default | Rule |
| --- | --- | --- |
| `attempt_count` | 0 | integer 0-10 |
| `provider_calls` | 0 | integer 0-1000 |
| `provider_input_tokens` | null | null or integer 0 through maximum safe integer |
| `provider_output_tokens` | null | null or integer 0 through maximum safe integer |
| `cost_usd` | null | null or finite number 0-1000000 |
| `cost_kind` | unknown | unknown, estimated or known |
| `context_tokens` | null | null or integer 0-1000000 |
| `context_counting` | unknown | unknown, estimated or strict |
| `stage_durations` | [] | up to 32 strict `{stage, duration_ms}` objects |

Stage names are unique identity strings and durations are finite numbers 0-300000. Unknown cost requires null cost; known/estimated cost requires a number. Unknown context counting requires null tokens; estimated/strict counting requires a token number. Strict context counting also requires a declared tokenizer in versions. Missing provider usage remains null, not zero. Zero is accepted only when explicitly supplied as known usage.

`Versions` defaults: `engine: "1.0.0-rc.1"`, `policy: "unassessed.v0"`, `model: null`, `tokenizer: null`, `index: null`. All non-null values use identity rules. Top-level schema version identifies the wire schema. These fields declare identities; V0 does not validate model/tokenizer capabilities or claim a hard token ceiling.

The RC preparation updates the declared engine identity; schema version remains
`0.1`. Explicit historical engine identities such as `0.0.0` remain valid. Both
native runtimes emit `1.0.0-rc.1`; Python package metadata separately uses the
PEP 440 spelling `1.0.0rc1`. See [the identity decision](../docs/decisions/0005-release-candidate-identity.md).

## Public validation and temporary V1 behavior

Python `cragkit.contracts` exports the Pydantic models `RetrievalResult`, `Evidence`, `Facet`, `Usage`, `Versions`, `Limitation`, `StageDuration` and `parse_result`. TypeScript `cragkit/contracts` exports inferred types, `ResultSchema`, corresponding component schemas and `parse_result`. Helper rejection uses the same safe `InvalidRequest` envelope as malformed wire input; source release failures in later runtime stages use `IntegrityViolation`.

Until the V3 coverage assessor exists, V1 may return exact lexical excerpts as partial with unknown facets, policy `unassessed.v0` and `coverage_unknown`. No useful authorized evidence returns insufficient. Search/store failures must raise typed operational errors or, only for an explicitly configured fallback, return degraded execution with a limitation. V0 does not implement retrieval, source release or scoring.

For example, one exact excerpt plus an unknown facet is a valid partial result. Changing only its status to sufficient is invalid. Exercise: remove the only evidence item referenced by a supported facet and observe validation fail. This illustrates internal consistency; it does not prove the excerpt supports the question.
