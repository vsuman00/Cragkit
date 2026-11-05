# V1-08 runtime contract E-r1

Engine identifiers in this frozen contract describe its reference fixture. Current
native release identities are defined in [Results](RESULTS.md#release-identities);
schema `0.1` and historical fixture values remain unchanged.

This freezes the internal Python/Node source-release and minimal result behavior for V1-08. Public revision 0.1 wire schemas, immutable migrations and the approved corpus remain unchanged. V1-09/V1-10 retain their lifecycle/race acceptance tasks.

## Ownership and interface

Python peer owns its session module, optional `_postgres_source.py`, `retrieval.py` and new retrieval tests; Node peer owns corresponding native files. Python is peer assembler. Root owns shared fixtures, native hosted helpers/bridge, tracker/docs/Git and final verification. Peers coordinate directly; shared/outcome/protected-boundary changes go through root. One test process, at most two native clients; root alone runs integration.

`PostgresRetriever(resource).retrieve(request, scope=scope, deadline=absolute_loop_time)` in Python and `.retrieve(request, {scope, deadline, signal?})` in Node return the existing typed RetrievalResult. The resource remains caller-owned; there is no new driver or migration at import. Parse/snapshot request and trusted scope, enforce the minimum of supplied deadline and request deadline from call entry, including request snapshotting, both transactions and assembly.

A scoped handle adds `fetch_evidence(candidate, max_source_bytes)` (Python keyword argument; Node options object). It returns an immutable SourceFetch: state `verified`, `unavailable` or `budget_exhausted`; evidence or null; source_bytes (bytes actually loaded, otherwise zero); stale (verified retained generation differs from current active generation). Malformed candidates/budgets use InvalidRequest; valid candidate scope/collection mismatches use UnauthorizedScope before SQL. Methods retain existing task/context/busy/expiration guards.

## Authorized source fetch

Use a fresh scoped transaction after candidate retrieval. Each fetch parameterizes candidate tenant/collection/document/revision/generation/chunk, current scope/grants/authorization revision, required filters and remaining source byte budget. Every join uses full composite keys. Require non-tombstoned document and ready retained generation. A still-retained immutable generation may resolve after active publication changes; mark stale_evidence. Missing/deauthorized rows are unavailable, not an operational exception. SQL/driver failures remain typed exceptions; duplicates or corrupt source data fail closed.

Source row order is tenant, collection, document, revision, generation, chunk, canonical_sha256, source_bytes, canonical_text, start, end, chunk_bytes, chunk_text, chunk_sha256, locator, lexical_profile, is_active. Parameter order is remaining budget, six candidate keys, tenant/collection/two authorization-revision values/principal/grants, then filters (Node filter placeholders start at 14).

Fetch one bounded canonical revision at a time. Return identity columns for comparison, canonical_sha256, canonical UTF-8 byte count, canonical_text only if it fits the remaining budget, chunk start/end, chunk byte count/text only if at most 32,768 bytes, chunk digest, opaque source_locator, lexical profile and active-generation equality. PostgreSQL byte counts are integers; Node bigint offsets may be canonical decimal strings and must remain safe exact integers. Maximum canonical source is 16,777,216 bytes. A larger source or malformed fields are integrity failures. A valid source exceeding the remaining request budget yields budget_exhausted without loading canonical text.

Verify full canonical UTF-8 bytes against canonical_sha256; strict UTF-8 slice boundaries; 0<=start<end<=source_bytes; exact chunk bytes/text; text byte length<=32768; chunk digest; all candidate identity/span/digest fields; profile native_fts.v1. Validation failures use redacted IntegrityViolation (unsupported profile uses UnsupportedCapability). Raw canonical source never enters the result or logs.

Evidence.source_sha256 is the verified canonical digest, not document_revisions.source_sha256 (which hashes the original pre-normalized source). Evidence ID is SHA256 of compact UTF-8 JSON:

`['cragkit.evidence.v1', tenant, collection, document, revision, chunk, String(start), String(end), text_sha256]`

Evidence field order is the existing schema order: evidence_id, collection, document_id, revision_id, chunk_id, source_locator, start_byte, end_byte, text, source_sha256, text_sha256. Locators are opaque labels, never opened or treated as instructions.

## Minimal assembly and bounds

Only renderer cragkit.context.v1 with estimated counting and no declared tokenizer is supported; other renderers, strict counting or named tokenizers fail before leasing. If envelope_reserve_tokens>=max_context_tokens, raise ContextBudgetTooSmall before leasing. This is an estimated V1 policy, not a hard model token ceiling.

Retrieve at most min(65, request.limits.max_candidates) candidates in existing FTS order. The 65th is a sentinel for the result's 64-item ceiling. Process only the first 64; maximum 64 source fetches and 16,777,216 canonical source bytes actually loaded per request. No retries, provider calls or alternate queries. Never broaden scope/filters. If the source byte budget is exhausted, stop and mark budget_exhausted; unavailable candidates mark stale_evidence and are omitted.

Context is compact JSON of the emitted Evidence array, without ASCII escaping or whitespace, or empty string when no evidence is emitted. Pack only whole chunks in candidate order. For each proposed addition, serialize the actual context. Require UTF-8 length<=min(262144, 4*(max_context_tokens-envelope_reserve_tokens)). Skip a chunk that does not fit and continue within the same bounds. A skipped chunk/65th sentinel marks truncated_evidence; a context capacity rejection also marks budget_exhausted. No token-counter/provider is installed; count is ceil(actual context UTF-8 bytes/4), explicitly estimated and potentially inaccurate for a model. Returned evidence exactly matches rendered evidence, with no source text splicing or synthetic ellipsis.

Nonempty evidence gives partial, empty gives insufficient; never sufficient. Execution is complete when all operations succeed. No fallback converts an operational/integrity failure into missing evidence. Facets are empty because V1 has no facet assessor (request queries may exceed the facet question ceiling). Limitations use fixed order: coverage_unknown always, then stale_evidence, truncated_evidence, budget_exhausted when applicable; ID references may be empty. No semantic support is inferred from an FTS hit.

Usage: attempt_count 1, provider_calls 0, provider_input_tokens 0, provider_output_tokens 0, cost_usd 0/cost_kind known, context_counting estimated with the count above, stage_durations empty. These zeros describe model/provider usage and spend, which are known because no such work occurs; they do not measure database hosting or infrastructure cost. trace_id null; versions engine 1.0.0-rc.1, policy unassessed.v0, model/tokenizer null, index native_fts.v1. Recheck deadline/cancellation after assembly before returning.

## Acceptance

Both runtimes consume root-owned exact shared source/result fixtures. Test original/canonical hash distinction, Unicode/CRLF/BOM, forged identities/spans/digests, UTF-8 mid-scalar offsets, invalid profiles, missing/deauthorized records, budget boundaries, whole-chunk omission, defaults/unsupported profiles, immutable outputs, deadlines/abort and driver-free import. Root verifies native round trips, no-match/denied scope, scoped byte spans, corruption refusal and no fixture leakage. Post-candidate authorization race coverage beyond the fresh fetch snapshot remains V1-10.
