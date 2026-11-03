# V6-02H offline transport correction

Status: COMPLETE for H1/H2/H3 offline implementation and verification.
V6-02 held-out acceptance and full V6 remain open.

For example, eleven synthetic Cohere dispatches now span at least 61 seconds
on the fake clock. The same sender refuses a second call when its pacing wait
cannot fit inside the original deadline; no HTTP request is sent for that call.

The [ETP-r1 contract](../../../contracts/EVALUATION_TRANSPORT_V6.md) freezes the
scope. Sol diagnostics implemented fixed HTTP status categories and privacy
fault cases in `provider_http.py` and its test. Sol pacing implemented the
internal pacer and fake-clock tests, coordinated directly with its peer and
assembled both reviews. Root read the actual code and assembly, integrated the
HTTP/recorder/journal boundaries and ran every verification process serially.
Both peers stopped writing and returned ownership before root integration.

Live evaluation HTTP 401/403, 429 and 500–599 responses now yield fixed auth,
rate-limit and server categories. Other failures remain generic. Classification
precedes body/header interpretation; response bodies are not consumed for error
statuses. The recorder and private journal preserve only these allowlisted
categories, including fixed pacing failures. Unknown error values collapse to
safe errors, and hostile exception stringifiers are never invoked. Exception
contexts, response headers and key values do not enter persisted diagnostics.
Failed or cancelled journals remain unsealed, with conservative unknown usage
and no automatic retries.

One pacer belongs to each live sender. Its monotonic spacing of at least 6.1
seconds between Cohere admissions is a conservative local policy informed by
[Cohere's documented trial limit](https://docs.cohere.com/docs/rate-limits),
verified on 3 November 2026. It is not an account-wide quota guarantee: other
processes and monthly provider limits remain outside this pacer. OpenAI has no
additional interval in this correction. Mock transports bypass production pacing;
production-branch tests substitute only the HTTP client and clock, proving the
wiring without account access or real waits. The original timeout includes the
pacing wait, with deadline/cancellation rechecks immediately before sending.
Concurrent use fails without creating a queue. Early/late wakeup, clock faults
and cancellation do not consume a new pacing slot.

Actual checks, run from the project root:

```sh
uv run --project packages/python --frozen --no-sync python -B -m pytest tools/tests/test_evaluation_pacing.py tools/tests/test_provider_http.py tools/tests/test_recorded_provider.py tools/tests/test_provider_journal.py -q
uv run --project packages/python --frozen --no-sync python -B -m pytest packages/python/tests tools/tests -q
node --test --test-concurrency=1 tools/tests/provider_replay.test.mjs
python3 tools/check_release_readiness.py
```

Results: **143 focused tests passed**, **3,697 Python/tool tests passed** with
four existing intentional Pydantic warnings, and **41 Node tests passed**.
Tests cover status boundaries, no error-body reads, one-send behavior, response/
client closure, private exception faults, journal propagation, unknown billing,
unsealed-tape refusal, eleven-call pacing, cross-provider independence,
insufficient/elapsed deadlines, early/late wakeup, malformed/backwards clocks,
concurrency and propagated/suppressed cancellation. E106/E107 record these faults.
The actual preregistration checker also verified ten requirements, 107 edge-case
owners/evidence paths and six original input digests. Its no-held-out-read flag
describes that checker invocation, not the already documented original run
exposure. This check does not prove release readiness. New E106/E107 entries
are synchronized in the release coverage index.

No core package, public API, manifest, lockfile, migration, scoring function,
original label, quality threshold, old admission or recording was changed.

This does not diagnose the old transport failure retroactively or authorize
another paid run. Original failed evidence and post-run label exposure remain
recorded in [the live report](V6-02E3-live-attempt.md). The old runtime receipt
is historical; changed tooling requires a later source/runtime refreeze.
Next: prepare a separate human-review packet under the existing contamination
policy, retaining pending review until actual user approval. Do not substitute
fake success for the required live run or skip V6-02 dependencies.

Resource observation: 25.3 GiB free disk, 40 percent system memory free. One test
process at a time; no credentials, account calls, installations, model downloads
or owned background services. Learning practice remains unassessed. Optional
exercise: explain why a paced request can still encounter a provider rate limit.
