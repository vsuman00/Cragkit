# PK-r1: Extractive evidence packing

For example, expanding `delete logs` to its surrounding paragraph can preserve the preceding `Do not`. Expansion still returns exact bytes from the same immutable revision.

## Inputs and trust

The optional native `pack_evidence` function accepts at most 64 Evidence seeds and 64 caller-authorized source records. Each source has exactly `collection`, `document_id`, `revision_id`, `source_sha256` and `text`; cumulative source UTF-8 bytes cannot exceed 16,777,216. It verifies every source digest and every seed's exact byte slice before selection, including seeds that will not fit. Missing sources, conflicting source records/locators or mismatched slices raise `IntegrityViolation`. Invalid shape/options raise `InvalidRequest`.

This standalone function does not establish access rights. The PostgreSQL source helper can explicitly capture a verified full-source snapshot after its existing authorization and integrity checks; capture is private, opt-in and absent from the serialized fetch shape. Retrieval integration must fetch fresh authorization before release. Sources are already canonical caller data; packing does not normalize BOM, line endings or Unicode. Mutable caller inputs are copied before yielding.

## Span selection

`surrounding_bytes` defaults to 256 and accepts integers from 0 to 4096. Expansion prefers paragraph boundaries or source edges within that distance on each side and never cuts a seed. A fenced Markdown code block can expand through internal blank lines when its full enclosing block fits this allowance. An immediately preceding Markdown heading is included when it fits. These bounded heuristics are not a general document parser; context beyond the allowance may remain absent.

Overlapping or adjacent spans merge only within the same collection/document/revision. Disjoint spans remain separate JSON array items, so omissions are visible rather than joined as continuous prose. A merged/expanded span exceeding the existing 32,768-byte Evidence cap is omitted whole. Changed spans receive `span-` plus SHA-256 of compact UTF-8 JSON `[collection, document_id, revision_id, source_sha256, start_byte, end_byte]` as both evidence and chunk ID. If that ID is already an original or emitted ID, append the first unused positive integer suffix. Unchanged single seeds retain their IDs. Aliases map each emitted ID to its original seed IDs in input order.

Up to 32 optional facet groups contain unique original seed references. For each facet, select its highest-ranked group unless a previously prioritized group already covers it. Then consider remaining groups in input rank order. These references express selection preferences; they do not establish semantic support.

## Budgets and cancellation

Each proposal is recounted with [TK-r1](TOKEN_CONTEXT_V3.md), including all citation fields and the declared wrapper reserve. Omit whole proposals that exceed the token or 262,144-byte rendered limit. If only the mandatory envelope fits, return `[]` with omissions; if that envelope does not fit, raise `ContextBudgetTooSmall`. Strict and estimated modes retain their separate claims.

The deadline uses the runtime monotonic clock in seconds. Python propagates native task cancellation; Node accepts an optional AbortSignal. Work yields between source/proposal iterations and checks deadlines. Bounded synchronous hashing/tokenization is not preempted mid-instruction. No provider call, download or database connection occurs in the packer.

The result includes emitted `evidence`, the TK-r1 counted fields, `aliases`, and `omitted_count`, `merged_count`, `expanded_count`. Omissions count original seeds absent from emitted aliases; merges count additional seeds in emitted merged groups; expansions count emitted groups extending beyond their original seed envelope. No coverage status is inferred here. V3-05/V3-06 must assess only the actual emitted excerpts.

## Verification and limitations

Shared [fixtures](fixtures/packing.json) compare complete deterministic outputs, exact source slices, text/source digests and serialized budgets across runtimes. Native tests cover mutable inputs, Unicode identity distinctions, malicious property names, ID collisions, deadline/cancellation, strict exact-fit boundaries and malformed inputs. Source fidelity cannot establish relevance or truth. A failure case is assuming an authentic short quote contains its distant exception; bounded expansion cannot guarantee that.
