# V6-02H4 terminal-time pacing correction

Status: COMPLETE for offline correctness and verification. V6-02 live evaluation
and full V6 remain OPEN; recovery labels still await actual human review.

For example, a ten-second connection delay must not use up the gap before the
next request. The controlled before-fix probe observed two dispatches at the same
simulated time, with eleven within 54.9 seconds. It used a fake client/clock and
made no network request. The initial pacing tests had exercised immediate client
dispatch, so they did not cover this boundary. Root reproduced the failure before
assigning any implementation changes.

## Fix and ownership

The [ETP-r2 amendment](../../../contracts/EVALUATION_TRANSPORT_V6.md#etp-r2-amendment-terminal-time-pacing-v6-02h4)
keeps the same 6.1-second local policy while anchoring it conservatively after the
previous started operation fully unwinds, including stream and response cleanup.
`EvaluationPacer.finish(provider)` records that terminal time without sleeping.
The next Cohere wait uses the later of admission and terminal times. OpenAI has
no added interval. Invalid/backwards/throwing terminal clocks invalidate future
admission rather than silently reusing an old timestamp.

The HTTP sender keeps single-inflight ownership through cleanup and finish.
It finalizes started successes, failures, timeouts and cancellations; refused or
cancelled waits do not finalize an unstarted operation. Results return only after
cleanup/finalization, and a late cleanup cannot become success. Cancellation
remains cancellation even if finalization fails. Errors remain fixed, with no
private callback/transport exception context. No retry, end-of-request sleep,
deadline extension, provider destination or credential-loading change was added.

Sol pacing owned helper/tests, and Sol HTTP owned sender/tests and assembled.
They agreed on the interface directly and returned all four paths before root
verification. Root inspected actual source, tests and both reports; no unresolved
protected decision required escalation. Recorder/journal and core packages were
not changed. This corrects local scheduling; it is not a guarantee of account-wide
or remote-server quota behavior.

## Actual verification

```sh
uv run --project packages/python --frozen --no-sync python -B -m pytest tools/tests/test_evaluation_pacing.py tools/tests/test_provider_http.py tools/tests/test_recorded_provider.py tools/tests/test_provider_journal.py -q
uv run --project packages/python --frozen --no-sync python -B -m pytest packages/python/tests tools/tests -q
```

**173 focused tests passed**; **3,727 Python/tool tests passed**, with four existing
intentional Pydantic warnings. New cases cover delayed initial dispatch, blocked
stream cleanup and ownership, started status/network/stream failures, timeout,
cancellation, finalization faults, invalid terminal clocks, failed waits and late
cleanup. Existing privacy, fixed errors, ledger/journal, deadline and no-retry
regressions also passed.

Root reran the same fake-client/clock probe after the fix: eleven observed
dispatches had minimum gap 6.1000000000000085 simulated seconds and span
61.0000000000002 simulated seconds. These floating-point observations satisfy
the minimum 6.1-second condition; they are not measured production latency.
The [verification record](V6-02H4-terminal-verification.json) preserves before/
after counts and scoped resource/preservation evidence. E107 and the release
coverage index now include the delayed-transport/cleanup condition.

All 121 original failed-run files and the one durable admission marker have
identical hashes before/after this task. The recovery review bundle and its
pending human-review state also match the previously recorded revision. The old
failed tape was not sealed, resumed, replaced or replayed. Original approval
seals, labels, metrics and targets remain unchanged. No paid request occurred.
A later approved input and changed source still need their own frozen identity.

Resource observation: 25.2 GiB free disk and 44 percent system memory free.
There was one regression suite at a time; a short fake-clock probe ran while
that suite was active. Peers ran no tests. No service, database, installation,
model download or persistent background task was started. Learning practice
remains unassessed. Optional exercise: explain why starting a clock before
connection setup differs from starting it after response cleanup.
