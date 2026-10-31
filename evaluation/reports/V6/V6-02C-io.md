# V6-02C1: Bounded evaluation I/O primitives

State: COMPLETE for the offline primitives. Parent V6-02C and V6-02 remain open. Date: 31 October 2026.

For example, a request admitted with a 32,768-token bound that times out after dispatch retains that full estimate and consumes one attempt. A validated reported input count may settle the estimate downward; an account charge remains unknown. The ledger never refunds the call count.

[LEIO-r1](../../../contracts/LIVE_EVALUATION_IO_V6.md) fixes the interfaces, provider destinations, limits and remaining gates. Sol HTTP owned `tools/provider_http.py` and its tests. Sol budget owned `tools/live_evaluation_budget.py` and its tests, assembled the pair and directly requested two HTTP corrections. Root integrated the pair, added the approved-payload primitive, fixed close-error sanitization and performed final verification. Files had one writer at a time; one test process ran at a time.

Implemented:

- Fixed OpenAI embedding/Cohere rerank HTTPS POST routes, one owned asynchronous client, verified TLS configuration, no environment proxy/CA overrides, redirects, retries or caller-selected URLs. Whole-stream deadlines, body/type/encoding limits, cancellation and response closure are enforced. Explicit keys stay out of representations and fixed error messages.
- Exact Decimal admission: USD 0.02 total, USD 0.01 per provider, 60 attempts and one pending reservation. Missing/failed usage retains its full estimate; invalid usage freezes admission; an integer overrun records the larger estimate before freezing. Snapshots distinguish retained estimates, historical ceilings, reported input counts and unknown billing.
- An immutable approved-text gate rejects unknown query/source text and extra wire fields. OpenAI counts use the issued pinned tokenizer; Cohere reserves a full 32,768-token context per document/query pair. The gate does not read labels or attest corpus provenance. The runner must verify the sealed packet before supplying these strings.

The HTTP review found that suppressing an exception's display with `from None` still retained the original HTTPX request through `__context__`. Peer/root fixes raise sanitized errors after leaving the handler, including malformed JSON, network and client-close failures. Regression cases inspect both exception cause and context. The payload gate applies the same protection to parser/encoding failures.

Actual final command:

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_evaluation_payloads.py tools/tests/test_live_evaluation_budget.py tools/tests/test_provider_http.py tools/tests/test_provider_adapters.py -q
```

All 112 tests passed in 0.29 seconds: 29 payload, 25 budget, 32 HTTP and 26 existing provider-mapping cases. Tests cover exact caps, foreign/forged/duplicate reservations, usage uncertainty/overrun, caller Decimal context, snapshot isolation, fixed routes/auth snapshots, malformed requests before dispatch, wrong-provider keys, redirects, streaming limits, deadline/cancellation, concurrent refusal, closure, unissued tokenizers and unapproved text. Owned whitespace, documentation links and self-contained prose checks passed. HTTPX0.28.1's installed TLS source was inspected: `verify=True` with `trust_env=False` selects certifi instead of environment CA overrides.

Pricing sources were checked before freezing this implementation detail: [OpenAI text-embedding-3-small](https://developers.openai.com/api/docs/models/text-embedding-3-small) and [Cohere's Rerank5 announcement](https://cohere.com/blog/rerank-5) list USD 0.02 per million input tokens for the selected models. [OpenAI's endpoint](https://developers.openai.com/api/reference/resources/embeddings/methods/create) and [Cohere's endpoint](https://docs.cohere.com/reference/rerank) support the fixed routes. Prices must be rechecked before a live run; these estimates do not independently establish billing.

No key was read, created or disclosed, and no live provider request, held-out access, database service, dependency installation or publication occurred. Mock HTTP does not establish live TLS, account access or model quality. Core runtime packages, storage and locks were unchanged by this slice. The earlier full SDK/native acceptance belongs to V6-02B; it was not rerun for these evaluation-only utilities. Final headroom was 31 GiB disk and 47 percent system memory free; no task-owned process remains.

Remaining: bind the actual sealed public packet, durably journal attempts before dispatch, validate/record responses for replay, run genuine-profile publication and all five comparison modes, refreeze candidate source identity before held-out access, and complete subsequent V6 gates. Secure key target selection is pending. Optional exercise: explain why cumulative historical ceilings can differ from the current retained estimate after reported usage settles. Learning practice remains unassessed.
