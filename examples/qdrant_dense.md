# Dense embedding and Qdrant composition

For example, a query embedding computed with `openai_te3small_1536_r1` cannot query a collection configured with `fake_embedding_1536_v1`, even though both contain 1536 numbers. The complete model, tokenizer, normalization and dimension descriptor must match.

The [Python](qdrant_dense.py) and [Node](qdrant_dense.mjs) examples compose the existing E-r1 adapter with the native candidate store. They export `retrieve_candidates`; importing either example starts no operation. The Node file uses repository-relative built modules. Installed applications use the matching `cragkit/contracts`, `cragkit/embeddings`, `cragkit/execution`, `cragkit/errors` and `cragkit/qdrant` imports.

## Caller responsibilities

Initialize a `QdrantSearchStore` against a compatible existing collection before invoking the example. Bind trusted scope outside agent-editable input. Pass a caller-owned, bounded embedding transport and a token counter matching the configured profile. The example snapshots request and scope before its first await. The caller closes its store and transport; the example borrows both.

Use `sparse_profile: null` for the accepted OpenAI deployment. This profile supports dense candidate search; it supplies no sparse text encoder or hybrid search. The fake profile may also use a dense-only collection for routine mechanics tests. No model runtime is installed on the laptop.

The default embedding policy forbids live execution. A real transport also requires explicit disclosure permission, a correctly configured tokenizer, an allowed live policy and a price/spend allowance. The example discovers no credentials or endpoint. Its tests inject in-memory spies; they do not verify live OpenAI service availability, TLS or billing. Never label fake vectors with the real model identity for storage.

## Work and usage

A transport wrapper reserves and dispatches one provider slot when the E-r1 adapter actually calls it. A token-limit or live-policy denial occurs before that point and counts as zero calls. A dispatched failure or cancellation retains one call with unknown usage. Successful fake execution records known zero cost; an estimated live cost stays in `embedding_usage`, while the shared ledger retains unknown billing. These are different claims.

After embedding, `bind_embedding_batch` revalidates the complete immutable batch. The query requires one vector. The pure binder also accepts up to eight vectors for later ingestion composition; binding an existing batch performs no inference or accounting. Qdrant candidate work is reserved separately. Both operations receive the same effective deadline; Node forwards the same caller cancellation signal.

The returned nominations remain text-free and `UNVERIFIED`. They are not an answer or authorized evidence. V5-03 must resolve canonical source bytes and current permissions before provider disclosure or final release.

## Check the examples

From the repository root, with the development dependencies and optional Python Qdrant extra installed, run these checks serially:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant pytest packages/python/tests/test_qdrant_dense_retrieval.py -q
```

Build Node with `npm run build` in `packages/typescript`, then run from the root:

```sh
node --test --test-concurrency=1 packages/typescript/tests/qdrant-dense-retrieval.test.mjs
```

The isolated real-backend command and pinned binary requirements are in [development.md](../docs/development.md#v5-native-qdrant-candidates). Select `--dense-only` to exercise fake E-r1 inference, complete batch binding and actual dense-only backend queries. The integration harness provisions and removes only its temporary collection/process/configuration.

Failure to inspect: a same-dimensional batch naming another model raises `EmbeddingProfileMismatch` before query dispatch. Optional exercise: explain why a successfully returned estimated cost cannot be reported as a verified charge.
