# V6-02C2/C3: Durable recording and native provider replay

State: COMPLETE for recording/sender and replay mechanics. Parent V6-02 remains open. Date: 31 October 2026.

For example, a process can stop after a paid request leaves the machine but before its response is saved. The pending record remains uncertain, cannot become a successful replay and never causes an automatic resend. Missing usage retains the conservative admission estimate.

[EREC-r1](../../../contracts/EVALUATION_RECORDING_V6.md) defines ownership, interfaces and failure behavior. Sol journal owned `tools/provider_journal.py` and its tests. Sol sender owned `tools/recorded_provider.py` and its tests, assembled the pair, and coordinated fixes directly. Sol Node owned `tools/provider_replay.mjs` and its tests. Root owned shared validation, the synthetic cross-runtime fixture, integration, documentation, tracker and Git. All writes transferred before root corrections; tests ran serially.

## Implemented behavior

The journal creates a fresh owner-private directory, writes pending metadata durably before HTTP, and keeps bounded responses in exclusive owner-private files. Completed tapes require matching pending/completion/seal metadata, consecutive ordinals, exact response digests and validated provider output. Loader checks reject incomplete, uncertain, altered, extra, missing, symlinked, hard-linked or incorrectly permissioned files. Metadata is hashed and parsed from the same bounded read. Mock provenance is rejected by default; repeated identical calls retain separate ordered entries.

The integrated sender requires explicit enablement, configured provider keys, an approved-text gate and the existing budget. It records a pending attempt before transport and saves validated responses before settling usage. A disk failure after HTTP preserves validated reported tokens. Any operational failure freezes further dispatch; timeouts/cancellation retain uncertain admission and there is no retry. HTTP closes before sealing, with a separate two-second cleanup bound. Late task exceptions are observed. A final descriptor-close failure after a durable seal still fails the sender and leaves cleanup unverified; the seal proves recording integrity, not successful execution or quality.

Native Node replay independently recomputes Python's request/payload fingerprints and maps captured responses into native embedding/rerank formats. It uses one ordered cursor, bounded tape/response sizes, native deadlines and abort signals. Missing, changed, reordered or unconsumed calls fail. It uses no HTTP, Python server, model runtime or credential. The shared synthetic fixture covers Unicode including astral characters, quotes, backslashes, newlines and repeated requests; Python revalidates it against its actual mappers.

## Actual verification

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_recorded_provider.py tools/tests/test_provider_journal.py tools/tests/test_provider_recordings.py tools/tests/test_provider_http.py tools/tests/test_live_evaluation_budget.py tools/tests/test_evaluation_payloads.py tools/tests/test_provider_adapters.py -q
node --test --test-concurrency=1 tools/tests/provider_replay.test.mjs
```

The final combined Python scope passed 183 tests in 0.61 seconds, without skips. The Node replay scope passed all 41 tests without skips, including real native `EmbeddingAdapter` and `RerankingAdapter` construction against the synthetic three-call fixture. Node replay ran without a Python subprocess. The journal test did start one bounded Python subprocess, terminated it with `os._exit(23)` immediately after a durable pending record, and verified that the surviving incomplete tape could not replay.

Fault coverage includes short writes, fsync failure, partial completion, corruption/permissions, foreign/forged/duplicate tickets, the full 60-attempt tape, missing provider configuration before admission, validated usage after disk failure, usage overrun, cancellation, repeated cancellation during close, a hung/cancellation-resistant close, safe late-task observation, close-error redaction, and explicit mock/live separation. Root found and fixed a loader hash/parse double-read and preserved the HTTP primitive's specific sanitized close code. Node source was formatted for readable control flow. Owned link, whitespace and self-contained prose checks passed.

These are offline mechanics and fault results. No live key, provider request, held-out label, database service, dependency installation or package publication was used. Actual subprocess interruption establishes process-crash behavior on this local filesystem; it is not universal power-loss certification. The earlier full SDK/native database results remain V6-02B evidence and were not rerun for these evaluation-only utilities. Core runtime packages, storage, locks, targets and sealed corpus inputs were unchanged.

Remaining: the five-mode native executor, verified sealed public-packet binding, configured secure keys, current price review, genuine-vector publication, deliberate frozen held-out execution and subsequent V6 gates. A valid tape must also have a healthy sender exit before full-run acceptance. Final observed resources and next action are recorded in the tracker. Learning practice remains unassessed. Optional exercise: explain why a valid saved response and a failed cleanup can both be true while the overall evaluation still fails.
