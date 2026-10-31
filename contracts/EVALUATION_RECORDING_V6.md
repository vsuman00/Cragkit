# Evaluation recording contract EREC-r1

State: FROZEN for V6-02C2. This is evaluation tooling, not a retrieval cache or permission to call a provider. LEIO-r1 limits, models and data boundaries remain unchanged.

For example, a process can stop after the provider accepts a request but before the local response is saved. A durable pending record must remain uncertain. Reusing that directory must never resend the request automatically.

## Ownership and outcome

Deliver crash-safe provider recording and an integrated gated sender, with offline fault/replay tests. Sol journal owns `tools/provider_journal.py` and its focused tests. Sol sender owns `tools/recorded_provider.py` and its tests, and assembles the pair. Root owns shared `tools/provider_recordings.py` validation/helpers and tests, this contract, tracker, integration and Git. Existing provider adapters, budget, HTTP, payload gate, core, storage, locks and release settings are read-only dependencies. Peers resolve routine interfaces directly; outcome or ownership changes go to root, unresolved issues to Astra. One test process, no credentials/live HTTP/services/installs/held-out access in development.

## Shared validation

Root supplies `request_metadata(request) -> dict` with exactly `provider`, `model`, `replay_key`, `request_sha256`, `response_items`. It validates the existing exact ProviderRequest and mapped native request body, including the fixed model/parameters, without authorizing public text. Root also supplies `validate_recording(provider, model, response, *, expected_items, max_response_bytes=2097152) -> int | None`. It uses the existing strict OpenAI/Cohere response mappers to reject malformed vectors, indices/scores and usage. It returns reported input tokens (OpenAI total tokens; Cohere billed input tokens), or None. Integral finite Cohere numeric counts normalize to integers; fractional search units never become tokens. Fixed sanitized errors must not retain a private parser/provider exception context.

## Durable journal

`EvaluationJournal(directory, *, evidence_kind)` is a synchronous context manager. Evidence kind is exactly `live` or `mock`. Opening creates one fresh owner-private directory, never reuses an existing path, and retains a directory descriptor. Files are owner-private regular files opened exclusively without following symlinks. Use bounded bytes and fsync files/directory before reporting durability. Close only owned descriptors; never remove the retained journal.

`begin(request, input_token_ceiling)` validates metadata and a strict positive bounded token ceiling, permits one pending attempt and at most 60 attempts, durably writes its pending metadata before returning an opaque owner-bound ticket. Metadata contains no keys, raw source/query text or connection configuration.

`complete(ticket, response)` independently validates response shape with the shared helper, writes its bounded raw response and completion metadata durably, and returns reported input tokens or None. No success state exists before both writes finish. A crash/partial write stays unreplayable. `uncertain(ticket, code)` records a fixed safe code, retains the pending attempt's identity and marks the run failed. Allowed codes: `transport_failed`, `response_invalid`, `cancelled`, `deadline_exceeded`, `journal_failed`, `usage_overrun`. `fail(code)` marks a run failed after a completed response, for example when usage settlement overruns. Unknown/foreign/forged/duplicate tickets never mutate another pending attempt. Failed/sealed runs refuse new attempts.

`finish()` writes a final complete seal only when all attempts completed and the run is not failed. It is idempotent after success and prevents further appends. Normal context exit does not silently seal a run; the sender owns that explicit step. `snapshot()` exports only bounded safe metadata/counts, never responses or input text.

`load_recordings(directory, *, require_live=True)` returns an ordered tuple of existing ProviderRecording objects only from a complete sealed run. Validate private owner/mode, no symlink/special files, closed metadata shapes, consecutive ordinals, file sizes/digests and matching pending/completion/seal identity. Revalidate response shape using stored item counts. Reject pending, uncertain, failed, altered, extra or missing files. Reject mock provenance by default. Explicit `require_live=False` is for mechanics tests and must never establish live quality. Repeated identical replay keys remain separate ordered entries. No replay reader contacts the network.

## Integrated sender

`RecordedProviderSend(keys, gate, directory, *, counter=None, enabled=False, transport=None)` is an async context manager implementing the existing Send signature. Require explicit `enabled=True`; snapshot/validate local configuration before opening resources. It owns a new LiveEvaluationBudget, HttpProviderSend and EvaluationJournal. The gate is the exact existing EvaluationPayloadGate. Evidence kind is `mock` whenever a trusted test transport is supplied, otherwise `live`. No key/file discovery occurs. The live factory supplies no injected transport.

For each request: validate deadline/limit, configured provider key and approved payload; compute its exact/conservative ceiling; admit the budget; persist pending metadata; then attempt HTTP. Missing local provider configuration charges no attempt and creates no pending call. Validate and durably complete the response before settling reported usage. Mark the budget settlement as attempted before calling settle, since it can record an overrun and raise. A subsequent journal/settlement failure must not erase reported tokens or mask the original fixed error. Dispatched failures/cancellation retain the full estimate. A predispatch journal failure reaches no HTTP. Any operational failure freezes this sender against further dispatch; there is no retry or implicit fallback. Durably record uncertainty/failure when possible; a failed write still leaves the original pending record unreplayable.

On normal context exit, close HTTP successfully before explicitly finishing/sealing the journal. Give owned asynchronous cleanup a separate fixed two-second allowance; a hung close must not hold journal descriptors or cancellation indefinitely. Cancel/observe a late task and report cleanup unverified, without claiming that an uncooperative callback stopped. Operational, write, settlement or HTTP-close failures leave the run unsealed. Attempt all owned closes and sanitize close failures. A final journal-descriptor close can fail after the seal is already durable; retain that committed data, raise cleanup failure and mark the sender failed. A seal attests recording integrity, not successful execution or cleanup. Full evaluation acceptance requires a healthy sender exit as well as a valid seal. Never delete a seal or resend a call to hide a cleanup failure. Preserve caller cancellation. `snapshot()` returns budget and safe journal metadata and the evidence kind. It must not expose key material, source/query text, raw responses or credential-bearing exception contexts. A live CLI still requires verified sealed-packet provenance, current price review, configured keys and explicit run limits before using this sender.

## Verification

Test disk/write/partial-completion failures before/after HTTP, process interruption after a durable pending record, directory/file symlinks and permissions, corrupted/missing/extra files, foreign/duplicate tickets, response validation, mock/live separation, duplicate ordered keys, exact replay, budget/usage preservation, cancellation and safe cleanup errors. Use a subprocess only for the actual crash case, and close it. Root runs combined tests after inspecting both lanes. These mechanical tests do not establish live TLS, account access, genuine vectors, model quality or V6 completion.

## Native Node provider replay

Sol Node owns only `tools/provider_replay.mjs` and its focused test under
`tools/tests/`. Root owns the synthetic cross-runtime fixture
`contracts/fixtures/provider_replay.json`. This lane is independent of live I/O
and journal writes. Root serializes its tests after the recording pair.

`create_provider_replay(recordings)` snapshots up to 60 closed JSON rows with
exact fields `provider`, `model`, `replay_key`, `response_base64`. Bound total
decoded tape bytes to 64 MiB and each response to 2 MiB; reject noncanonical
base64, malformed/unsafe JSON records and unknown provider/models. It returns
async `embedding_transport(body, options)` and `rerank_transport(body, options)`,
plus `assert_complete()` and safe `snapshot()`. Both transports share one ordered
cursor. Recompute exactly the Python mapper's request identity and payload hash
from the actual native UTF-8 body, match the next provider/model/replay key, and
map the captured response to the native adapter format with the same strict
model/vector/score/usage invariants. Preserve duplicate keys as distinct calls;
there is no lookup cache, fallback, HTTP, Python server or model execution.
Check native monotonic deadlines, abort signals and byte caps. Fail with fixed
codes without including payloads. Unconsumed, missing or reordered calls fail.
The production parent may supply only a validated sealed live tape; the shared
synthetic fixture proves mapping/parity mechanics only.
