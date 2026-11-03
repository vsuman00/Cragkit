# Evaluation transport correction ETP-r1

V6-02H is an offline corrective prerequisite after the failed original live run.
It does not reopen that run, authorize another paid request, alter retrieval or
quality targets, or make the original held-out packet unseen again.

For example, HTTP 429 becomes a fixed rate-limit diagnostic. A queued dispatch
whose pacing delay cannot fit its original deadline fails before sending.

## Children and ownership

H1: Sol diagnostics owns `tools/provider_http.py` and
`tools/tests/test_provider_http.py`. H2: Sol pacing owns
`tools/evaluation_pacing.py` and `tools/tests/test_evaluation_pacing.py`, and
assembles both lanes. Root owns this contract, tracker, documentation, recorder/
journal integration and H3 combined verification. Root may integrate H1 files
only after the peer stops and returns ownership. Both peers resolve concrete
API dependencies directly. Unresolved protected/outcome changes escalate to root
and then Astra; no peer may change labels, thresholds, admission markers or tapes.

## Fixed diagnostics

HTTP 401/403 map to `provider_http_auth_failed`, HTTP 429 to
`provider_http_rate_limited`, HTTP 500–599 to `provider_http_server_failed`.
Other status/header/stream/network failures retain `provider_http_failed`.
No response body, header, URL, key, raw exception or arbitrary provider string
enters diagnostic values or exception chains. Existing TLS, endpoint, closure,
deadline and cancellation controls remain. There are no retries or redirects.
Root extends the recorder's exact safe-code and journal-reason allowlists so
these fixed categories survive to failure metadata. The fixed `provider_pacing_invalid` and `provider_pacing_failed` categories also
survive recording. Unknown categories continue to collapse to safe generic diagnostics. Incomplete journals remain unsealed.

## Serial live pacing

`EvaluationPacer()` exposes `async wait(provider, *, deadline)`. It admits only
`openai` and `cohere`, using the caller's original finite monotonic deadline.
Cohere dispatches on one pacer are spaced at least 6.1 seconds apart; OpenAI has
no additional interval in this correction. Unknown providers, malformed clocks/
deadlines, elapsed or insufficient deadlines fail with fixed errors. Time is
rechecked after waiting. Concurrent use is rejected rather than queued.
Cancelled, late or failed waits never dispatch or consume a new pacing slot.
No hidden retry loop, persistent task or unbounded waiter queue is introduced.

The HTTP sender owns one pacer for its lifetime, awaits it inside the existing
single-inflight/deadline boundary, and sends once only after admission succeeds.
Mock transports skip production pacing; focused tests exercise the production
branch with a fake client/clock and never access accounts. The helper is internal
evaluation tooling, not a core-library or distributed account quota guarantee.
Other processes using the same account remain outside its control.

Verification uses fake clocks/transports: pacing success, early/late wakeup,
insufficient deadline, cancellation, cross-provider behavior and concurrency;
fixed HTTP categories without response reads, one send/no retry, private error
context exclusion, journal propagation and healthy/unhealthy seal behavior.
One root-owned test process at a time; no service, install, secret file, original
held-out label or provider access. Preserve failed-run evidence and frozen inputs.
