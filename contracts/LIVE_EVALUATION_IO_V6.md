# Live evaluation I/O contract LEIO-r1

State: FROZEN implementation contract for V6-02C. It authorizes no live call by itself. The previously approved provider models, public-data boundary, USD 0.02 admission limit, concurrency one and zero retries remain unchanged.

For example, a timeout after dispatch does not prove the provider did no work. Keep that attempt's full admitted token ceiling until its outcome is known. Reported usage may reduce a conservative admission estimate; it never proves an account charge.

## Ownership and shared outcome

Deliver two tested evaluation-only primitives: fixed-endpoint asynchronous HTTP and an exact bounded admission ledger. Sol HTTP owns `tools/provider_http.py` and its focused tests. Sol budget owns `tools/live_evaluation_budget.py` and its focused tests, and assembles the pair. Root owns this contract, any shared wrapper/journal, release configuration, tracker, integration and Git. The existing `tools/provider_adapters.py` request/recording dataclasses and mapping behavior are read-only dependencies. Public core APIs, native storage, locks and package metadata are protected. Peers coordinate interface dependencies directly; outcome/boundary changes go to root, unresolved decisions to Astra. One test process; no credentials, services or live calls in these lanes.

## Fixed HTTP primitive

`HttpProviderSend(keys, *, transport=None)` is an explicit async context manager. It implements the existing async Send call: `await send(request, deadline=..., max_response_bytes=...) -> bytes`, where request is the exact existing `ProviderRequest`. Constructor configuration snapshots a provider-key mapping without logging or discovering credentials. A context creates one owned HTTPX0.28.1 asynchronous client; close is idempotent and closes only that client. `transport` is trusted dependency injection for routine fake-I/O tests; the live factory supplies none. No import or constructor starts network activity.

Only these POST destinations/models are supported:

| Provider | Model | URL |
| --- | --- | --- |
| openai | text-embedding-3-small | https://api.openai.com/v1/embeddings |
| cohere | rerank-v5.0-fast | https://api.cohere.com/v2/rerank |

Validate the request class, provider/model agreement, bytes/body cap, JSON object/model agreement and 64-hex replay key before dispatch. Request bodies are already mapped by the provider adapters; the later public-payload gate remains separately required. Reject malformed deadlines, response limits, keys and concurrent use before HTTP. Use verified TLS, no environment proxy/CA overrides, no redirects, no HTTP retries and at most one connection. Never accept a caller endpoint or base URL. Reject an OpenAI-style key for Cohere before sending it. Authorization headers and bodies must never appear in errors or object representations.

Bound the whole operation by its monotonic deadline, including streaming. Require HTTP200, JSON content type, uncompressed identity encoding and a bounded declared/actual body. Close streamed responses on success, failure or cancellation. Return bytes without interpreting model output; the existing strict adapters own that validation. Network/HTTP/timeout failures expose fixed sanitized codes. Caller cancellation propagates. Mock tests do not prove live TLS or account access.

## Admission ledger

`LiveEvaluationBudget()` is pure, synchronous and performs no I/O. Fixed limits: total USD0.02, each provider USD0.01, 60 attempts, one pending attempt. Dated admission prices are USD0.02 per million input tokens for each selected model. Use exact Decimal arithmetic. No constructor option raises those ceilings.

`begin(provider, input_token_ceiling)` validates a known provider and strict positive bounded integer, refuses exhausted/concurrent/closed state, atomically charges a call and its conservative ceiling, and returns an opaque reservation bound to that ledger. There is no refund of the call count. `settle(reservation, reported_input_tokens=None)` completes it: a strict nonnegative integer at or below its ceiling reduces the estimate to that reported input count; missing usage retains the full estimate. Invalid/over-ceiling reported usage freezes further dispatch and raises a sanitized `LiveBudgetError`. A bounded integer above the admitted ceiling records the larger estimate; invalid types or negative counts retain the original full estimate. Neither may understate observed overrun. `abort(reservation)` completes uncertain dispatched work while retaining the full admitted estimate. Unknown, forged, foreign or already completed reservations fail without changing another reservation. All methods are atomic between awaits because they do not await.

`snapshot()` returns safe counts, pending count, Decimal amounts as canonical strings, per-provider admission and reported/unknown usage state. Actual account billing remains explicitly unknown. Never expose private payloads or key material. Record conservative versus reported estimates separately. The future wrapper must durably journal a pending attempt before HTTP; a crash or failed write cannot authorize an automatic retry.

For OpenAI, the later wrapper computes the ceiling with the pinned declared tokenizer on the exact input strings. For Cohere, reserve 32,768 tokens for every query/document pair, as in the prior approved calibration. `max_tokens_per_doc` stays 4096. Reconcile only validated provider-reported input counts; missing or failed results retain the full bound. This is dated-price admission accounting, not an independently verified bill. The live runner must recheck dated official prices before dispatch and stop if the frozen budget cannot admit a call.

## Verification and remaining gates

HTTP tests cover fixed destination/auth routing, malformed input before send, wrong-provider keys, redirect refusal, oversized declared/chunked responses, content encoding/type, HTTP errors, timeout/cancellation, concurrent admission, response/client closure and redacted errors. Budget tests cover exact cap boundaries, provider/total/call limits, booleans/nonfinite/oversized integers, concurrent/foreign/duplicate reservations, uncertain failures, missing usage, overrun freeze and snapshot isolation.

Root integrates both primitives only after inspecting the implementation and running the focused suites serially. Public payload authorization, durable recordings, genuine-provider publication, five-mode execution and candidate refreeze remain separate V6-02C work. No fake transport result closes live quality or TLS acceptance.

Root's pure `EvaluationPayloadGate(sources, queries)` snapshots the approved
strings, rejects unapproved text or changed wire parameters, and computes an
OpenAI ceiling only with an issued pinned `Cl100kCounter`. Cohere admission uses
the complete context bound above. This gate does not attest packet provenance:
the runner must verify the sealed source/query identities before constructing
it. Neither this primitive nor the HTTP class is a live CLI. The future wrapper
must compose authorization, admission and durable recording before HTTP.

## Primary sources verified 31 October 2026

- [OpenAI embedding endpoint](https://developers.openai.com/api/reference/resources/embeddings/methods/create) and [model price](https://developers.openai.com/api/docs/models/text-embedding-3-small).
- [Cohere Rerank endpoint and request limits](https://docs.cohere.com/reference/rerank), [32k model context](https://docs.cohere.com/docs/rerank) and [dated Rerank5 API prices](https://cohere.com/blog/rerank-5).

Learning exercise: distinguish the request's admitted ceiling, the provider's reported input count and the actual account invoice. They are different evidence.
