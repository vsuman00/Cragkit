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

## ETP-r2 amendment: terminal-time pacing (V6-02H4)

A controlled fake-client probe on 3 November exposed a gap in ETP-r1's admission
anchor: delaying the first transport dispatch by ten seconds yielded two dispatch
observations at the same time, with eleven within 54.9 seconds. No network or
account was used. This amendment supersedes the admission-only spacing anchor.

`EvaluationPacer.finish(provider)` is synchronous and records a monotonic
terminal timestamp after a started HTTP operation has fully unwound, including
stream/response cleanup. The next Cohere admission must be at least 6.1 seconds
after both its previous admission and that operation's terminal timestamp.
OpenAI has no added interval. Invalid/backwards terminal clocks fail with a
fixed pacing code and invalidate future pacing admission; do not silently reuse
an older unsafe timestamp. Concurrent helper use is refused. Failed/cancelled
waits and pre-dispatch refusal do not call finish or consume a new slot.

The sender keeps its single-inflight ownership through finish. Mark an HTTP
operation started immediately before entering the client stream. Finish it on
success, status/body/stream failure, timeout and cancellation, without adding a
sleep at the end of the operation or extending its deadline. Return bytes only
after response close and pacing finalization. A finalization fault must not
retain private exception context or convert cancellation into a normal error.
Capture fixed outcomes then raise outside exception handlers; release inflight
ownership in an outer finally. Unknown callbacks remain sanitized.

H4a Sol pacing owns helper/tests; H4b Sol HTTP owns sender/tests and assembles.
Root owns this amendment, tracker, combined verification, reports and Git. Peers
coordinate directly on finish semantics; protected/outcome issues go to root,
unresolved decisions to Astra. Four implementation/test files, no recorder or
public-core API change. Tests must include delayed dispatch, delayed stream
cleanup, failed/cancelled operations, finalization faults and no-request waits.
No keys, services, live calls, original labels/admissions/tapes or release targets
are involved. Human review of the new recovery labels remains a separate gate.
