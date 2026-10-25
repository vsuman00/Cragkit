# TK-r1: Exact context rendering and token counting

For example, a citation, its byte offsets and escaped quotation marks consume tokens as well as the excerpt. Counting only `Evidence.text` understates the rendered context.

## Representation

The optional `cragkit.context` / `cragkit/context` entry points implement renderer `cragkit.context.v2`. They render a compact JSON array with no outside whitespace. Each item uses this field order: `evidence_id`, `collection`, `document_id`, `revision_id`, `chunk_id`, `source_locator`, `start_byte`, `end_byte`, `text`, `source_sha256`, `text_sha256`. Non-ASCII scalar values remain literal UTF-8; JSON quotes, backslashes and control characters are escaped. No Unicode normalization occurs. Disjoint excerpts remain separate array items.

Inputs obey the existing Evidence schema, with at most 64 items and 262,144 rendered UTF-8 bytes. Duplicate evidence IDs and conflicting source digests for the same collection/document/revision are invalid. Rendering validates structure; it does not fetch a source, establish authorization or prove relevance.

`count_context` returns `context`, `context_tokens`, `total_tokens`, `renderer`, `tokenizer` and `counting_mode`. Total tokens equal context tokens plus the caller's declared wrapper reserve, default 256. The maximum is an integer from 1 to 1,000,000; reserve is an integer from 0 to 1,000,000. The diagnostic result envelope is outside this representation. A later tool adapter must recount its actual wrapper before claiming a limit for that wrapper.

## Counting modes

Estimated mode uses the ceiling of rendered UTF-8 bytes divided by four, identifies no tokenizer, and rejects a supplied non-null counter. It makes no hard token claim.

Strict mode accepts only a counter created by the supported factory. Python uses `Cl100kCounter.from_file(path)` with optional `tiktoken==0.14.0`; Node uses `await Cl100kCounter.create(path)` with optional `tiktoken==1.0.22`. Both require the caller's local `cl100k_base.tiktoken` asset, at most 2,000,000 bytes, SHA-256 `223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7`. Both construct the encoding with the same pattern and merge ranks. All special-token spellings are ordinary source text. Node callers close the counter to free its WASM allocation. A closed or fabricated counter is unsupported.

The library never downloads token assets. `python3 tools/fetch_tokenizer.py` is a separate explicit development setup command that acquires and verifies the pinned asset under `artifacts/tokenizers/`. Missing optional dependencies raise `UnsupportedCapability`; invalid assets raise `InvalidRequest`. Core installation and import do not require tokenizer dependencies or asset files.

The empty array `[]` is the mandatory context envelope. If its count plus reserve exceeds the maximum, raise `ContextBudgetTooSmall`. The same error is raised when the complete supplied context exceeds the budget; selection belongs to the packer. Invalid modes or bounds raise `InvalidRequest`. Counter text input is bounded to 262,144 UTF-8 bytes.

## Compatibility and limits

The supported pair counts this declared representation, not every model's proprietary message framing. The shared [fixtures](fixtures/context.json) compare serialized bytes, token counts, wrapper arithmetic, escaped text, Unicode whitespace, literal special tokens and failure codes in both runtimes. Unicode whitespace differences discovered in a pure JavaScript tokenizer led to its replacement with the optional WASM tokenizer and a shared rank asset. This does not change Cragkit's native Python/Node execution boundary.

A failure case is using a genuine counter with the wrong downstream model and calling the result a hard bound for that model. Strictness applies only to the declared tokenizer and representation. Token parity does not establish evidence quality or source truth.
