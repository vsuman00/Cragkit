# Architecture-derived edge-case validation

This inventory accompanies [the master plan](plan.md). It defines expected tests, not passed tests. Completion evidence belongs to the owning task in [todo.md](todo.md). Every applicable case must have an executable regression or documented manual validation before its version exits. Add newly discovered cases rather than claiming this inventory covers every possible failure.

Layers: U = deterministic unit/contract fixtures; I = real adapter/database integration; L = explicit live-model evaluation; M = manual artifact, usability or operations review. Shared semantic fixtures run in Python and TypeScript. An isolated language pass is insufficient evidence of parity.

## Input and package boundaries

| ID | Trigger | Expected behavior | Owner | Layer |
| --- | --- | --- | --- | --- |
| E01 | Empty, whitespace-only, oversized or malformed query | Reject with the declared invalid-request code before external work. | V0-04 | U |
| E02 | Unknown filter operator, injected SQL, invalid value type | Reject unsupported AST fields; parameterize values and allowlist identifiers. | V0-04, V1-07 | U/I |
| E03 | Tool input attempts to supply tenant/grants or alter limits | Trusted scope remains separately bound; agent fields cannot override server policy. | V0-04, V4-06, V4-07, V5-06 | U/I |
| E04 | Unicode, large IDs, nonfinite numbers, different JSON key order | Canonical fixtures agree; IDs remain strings, nonfinite numbers fail, hashes follow the canonical rule. | V0-05 | U |
| E05 | Core import with no database/model/framework installation or network | Import succeeds with only declared core dependencies and no network or asset downloads. | V0-02, V1-12, V6-06 | U/M |
| E06 | Unsupported schema, storage capability or embedding profile | Fail early with a typed compatibility/capability error. | V1-02, V1-03, V2-04, V5-05 | U/I |

## Ingestion and revisions

| ID | Trigger | Expected behavior | Owner | Layer |
| --- | --- | --- | --- | --- |
| E07 | Emoji, combining characters, CRLF or invalid UTF-8 boundary | Exact canonical byte spans agree across languages; invalid boundaries are rejected. | V1-04 | U |
| E08 | Unsupported binary/scanned PDF, empty document or excessive input size | Explicitly reject or report unsupported input; do not create a successful empty searchable revision. | V1-04 | U |
| E09 | Heading, negation, code block or table crosses a chunk boundary | Preserve structural context where supported; flag unavoidable splits and test resulting excerpts. | V1-04, V3-04 | U |
| E10 | Same ingestion key and payload replayed | Return/reuse the same intent result without duplicate active content. | V1-05, V1-06 | I |
| E11 | Same ingestion key with changed payload or concurrent duplicates | Enforce atomic uniqueness; reject changed payload and define in-flight retry behavior. | V1-05, V1-06 | I |
| E12 | Crash before publication, incomplete chunks or failed indexing | Keep prior active generation visible; incomplete generation remains unsearchable. | V1-05, V2-04 | I |
| E13 | Two competing revisions finish out of order | Compare-and-swap detects conflict; old intent cannot silently replace a newer publication. | V1-09 | I |
| E14 | Document deleted while indexes/caches remain | Tombstone blocks retrieval; purge follows retention; unavailable historical citations are explicit. | V1-09, V5-04 | I |
| E15 | Model/parser/chunker change or vector dimension mismatch | Build a new compatible generation; preserve profile identity and reject mixed embedding spaces. | V2-04 | U/I |
| E16 | Source digest mismatch, absent source revision or invalid span | Quarantine/reject invalid evidence; surface integrity or source-availability failure according to contract. | V1-08, V3-04 | U/I |

## Authorization and database lifecycle

| ID | Trigger | Expected behavior | Owner | Layer |
| --- | --- | --- | --- | --- |
| E17 | Identical high-ranking documents across tenants | Scope is applied before candidate limits in every branch; no cross-tenant candidate text is released. | V1-07, V2-05, V2-07 | I |
| E18 | A foreign key references another tenant's revision/grant/chunk | Composite relational constraints reject the reference. | V1-01 | I |
| E19 | Pool connection is reused by another principal | Transaction-local context and cleanup prevent permission carryover. | V1-02, V1-03 | I |
| E20 | Grant revoked or document tombstoned after search | Final authorized source fetch excludes it; already delivered bytes cannot be retroactively revoked. | V1-10 | I |
| E21 | No matches under current authorization | Return insufficient without revealing whether inaccessible matches exist. | V1-08 | I |
| E22 | Runtime role is owner, bypasses RLS, or lacks intended privileges | Detect/document configuration; tests run under the real least-privilege runtime role. | V1-10 | I/M |
| E23 | Pool saturated, connection lost, statement hangs | Bound queue/wait/timeouts, return typed failure and release acquired resources. | V1-02, V1-03, V1-11 | I |
| E24 | close called twice or with in-flight work and borrowed pools | Idempotent close, bounded drain/cancel; caller-owned pools are not closed. | V1-02, V1-03, V1-11 | U/I |
| E25 | Active generation changes between candidates and source fetch | Return an allowed immutable revision under documented policy, or retry within limits; never mix revision text. | V1-09, V1-10 | I |

## Retrieval, fusion and model boundaries

| ID | Trigger | Expected behavior | Owner | Layer |
| --- | --- | --- | --- | --- |
| E26 | Exact error code/symbol is split by ordinary FTS | Declared identifier branch handles its fixtures without treating all language text as exact identifiers. | V2-06 | U/I |
| E27 | Duplicate candidates, tied ranks or a missing rank-list entry | Stable IDs/tie-breaks, per-list deduplication and correct RRF contributions. | V2-06 | U |
| E28 | Many subqueries or rewrites repeatedly retrieve one chunk | Global union cap and per-facet/list-family vote rules prevent unbounded score inflation. | V2-06, V4-03 | U |
| E29 | Dense or lexical branch fails | Typed error by default; only configured fallback returns degraded execution. | V2-07 | U/I |
| E30 | Embedding response has NaN, wrong dimensions, missing vectors or wrong profile | Reject response before indexing/search; no silent coercion into valid evidence. | V2-02, V2-03 | U |
| E31 | Reranker returns raw logits, missing/duplicate IDs or malformed scores | Preserve legitimate score semantics; reject malformed candidate mappings. | V3-01, V3-02 | U |
| E32 | Provider truncates input or local inference blocks event loop | Truncation is recorded; CPU work is bounded/offloaded and cancellation/resource effects are tested. | V3-02 | U/I |
| E33 | Structured planner/judge emits malformed output or invented evidence IDs | Apply declared bounded fallback/failure; never trust invented references. | V3-05, V4-02 | U |
| E34 | Source contains instructions to change scope, call tools or expose secrets | Treat source as data; fixed scope/configuration survives; core has no arbitrary executor. | V4-02, V6-04 | U/I |

## Evidence and context

| ID | Trigger | Expected behavior | Owner | Layer |
| --- | --- | --- | --- | --- |
| E35 | High-scoring evidence answers only one required facet | Partial result identifies missing/unknown facets; maximum score alone cannot yield sufficient. | V3-05 | U/L |
| E36 | No coverage assessor configured | Coverage remains unknown; useful excerpts can be partial, never silently sufficient. | V0-05, V1-08, V3-05 | U |
| E37 | Two applicable sources conflict, or a question requires current behavior | Record unresolved conflict/applicability; do not silently pick the highest score as truth. | V3-05 | U/L |
| E38 | Packing removes the only support for a facet | Reassessment sees only emitted evidence and downgrades the result; rebalance is bounded. | V3-06 | U |
| E39 | Overlapping chunks or disjoint excerpts share a revision | Merge overlaps without duplicated text; preserve separate spans and explicit omission separators. | V3-04 | U |
| E40 | Budget cannot fit the mandatory envelope | Raise ContextBudgetTooSmall; do not return a payload falsely labelled within limit. | V3-03 | U |
| E41 | Envelope fits but useful evidence does not | Return insufficient with budget limitation and correctly counted serialized output. | V3-04, V3-06 | U |
| E42 | Unknown tokenizer, escaped JSON, citation labels or tool wrapper overhead | Strict mode uses the declared tokenizer and final representation; unsupported counting is explicit. | V3-03, V4-06, V4-07 | U |
| E43 | Quote is genuine but source is incorrect/outdated | Preserve provenance and limitations; do not claim that byte verification proves world truth. | V3-07, V6-02 | L/M |

## Recovery, resource accounting and telemetry

| ID | Trigger | Expected behavior | Owner | Layer |
| --- | --- | --- | --- | --- |
| E44 | Rewrite removes required filters or changes original identifiers/intent | Reject the forbidden transformation or use the safe declared fallback; log the reason without raw content by default. | V4-02, V4-03 | U |
| E45 | Repeated query/candidate set, no progress or attempts exhausted | Stop with honest evidence outcome; useful prior evidence is retained within the final budget. | V4-03, V4-04 | U |
| E46 | Concurrent calls try to spend the final budget slot | Atomic reservations enforce global request limits; all internal/provider retries count. | V4-01 | U |
| E47 | Timeout/cancel during pool wait, model call, retry or packing | Stop new work, release resources, and propagate cancellation/typed error; never relabel as absent evidence. | V1-11, V4-04 | U/I |
| E48 | Rate limit, retryable transport fault or permanent validation error | Retry only declared transient cases within deadline/backoff limits; permanent errors do not loop. | V4-04 | U |
| E49 | Usage/cost absent, price unknown, or cancellation after dispatch | Mark unknown usage; strict unsupported accounting fails; do not promise an already-sent request is free. | V4-01 | U/M |
| E50 | Telemetry exporter hangs/fails or buffer fills | Retrieval remains bounded; events may drop with counters; audit durability is not implied. | V4-05 | U |
| E51 | Secrets, DSN, query/source text appear in error/trace fixtures | Redact credentials and honor raw-content-off default; inspect exported records. | V4-05, V6-04 | U/M |

## Extensions, releases and conditional cases

| ID | Trigger | Expected behavior | Owner | Layer |
| --- | --- | --- | --- | --- |
| E52 | Source/vector/manifest write succeeds only partially | Only fully published generations are visible; replay/repair is idempotent. | V5-01, V5-04 | I |
| E53 | Qdrant ACL payload is stale or SourceStore is unavailable | Authoritative checks precede provider disclosure; fail closed on unavailable authorization/source. | V5-03 | I |
| E54 | Existing index lacks required filters, revisions or source spans | Reject unsupported guarantees with capability errors; do not fabricate provenance. | V5-05 | I |
| E55 | MCP disconnect, malformed input or untrusted scope | Propagate cancellation, validate requests and bind host-resolved scope. | V5-06 | I |
| E56 | Different runtime/backend/library-tool-MCP results | Stable contract semantics agree; documented backend ranking differences stay explicit. | V5-07 | U/I |
| E57 | Clean install, unsupported runtime or missing optional dependency | Supported core installs work; incompatible optional use gives an actionable error. | V6-06 | I/M |
| E58 | Migration interrupted or package rollback attempted | Follow tested compatibility/restore procedure; never restore revoked permissions through rollback. | V6-07 | I |
| E59 | Held-out leakage, synthetic labels or selective benchmark reporting | Separate splits, human review, complete configuration/results and honest uncertainty. | V0-06, V6-01, V6-02 | M/L |
| E60 | Sustained load, large inputs or too many queued requests | Backpressure and batch/input limits keep work bounded; measure pressure and stop local runs when necessary. | V6-03 | I/M |
| E61 | Published artifact differs from local candidate | Verify artifact identity/version and installed behavior; create a corrective release if necessary. | V6-08 | I/M |
| E62 | A result/embedding cache is proposed later | Before enabling it, test scope, authorization revision, generation, profiles and invalidation; reauthorize hits. No cache is required for initial delivery. | V6-04, conditional feature gate | U/I |
| E63 | Approximate vector index is proposed for measured scale needs | Test filtered recall/underfill and bounded expansion/exact fallback with unchanged scope. Exact search remains the baseline until justified. | V2-08, V6-03, conditional optimization gate | I/L |
| E64 | Final-answer generation is added to a demo | Evaluate unsupported claims and citation support separately; retrieval tests alone do not establish answer faithfulness. | V6-02, conditional demo gate | L/M |

| E65 | Stored PostgreSQL catalog-OID types prevent a hosted database upgrade | Store lexical configuration names as text, resolve them with the fixed search path at use, reject missing names and preserve existing vectors through the migration. | V1-01-C, V6-07 | I |
| E66 | A hosted endpoint certificate cannot be verified or plaintext startup is attempted | Reject the connection without downgrading TLS; verify the selected endpoint's certificate and hostname, and test enforced plaintext rejection without sending a password. | V1-01-H, V1-02, V1-03 | I |
| E67 | A rotated database password is followed by pooler rejection and a direct network ban | Distinguish cached pooler authentication from direct reachability, stop repeated attempts/resets, verify authorized ban removal and use a bounded direct check before judging the saved password. Cache involvement requires evidence. | V1-01-D, V1-02, V1-03 | I/M |
| E68 | A driver returns a connection after its acquisition deadline before the timer callback runs | Recheck the absolute deadline before yielding, return the late connection and release admission; distinguish configured acquisition timeout from request deadline expiry. | V1-02A, V1-03 | U |

| E69 | Hosted CREATEROLE administrator cannot use DROP OWNED for a temporary runtime role | Revoke the fixture's exact table/domain/schema grants, remove its role-specific policies/data, drop only its role and verify cleanup without granting broader administrator or runtime privileges. | V1-02B, V1-03 | I |
| E70 | A scoped session handle escapes its transaction, or a deadline is too large for a float | Reject cross-task/expired handles and malformed deadlines before SQL; recheck elapsed deadlines after driver returns and caller body completion. | V1-02B, V1-03 | U |

| E71 | A driver suppresses a rollback error or reports failed transaction exit without raising | Verify the connection is IDLE after rollback; discard a nonidle connection and return a typed failure within the cleanup budget. | V1-02B, V1-03 | U/I |

| E72 | Native text parsers disagree on CR/BOM, Unicode line boundaries, split packing or tokenizer work | Shared exact byte/digest/profile fixtures and bounded counter regressions agree; asynchronous/malformed counters fail without leaked work. | V1-04, V1-06 | U |

| E73 | A same-tenant caller has read scope but no document write permission | Require a separately bound application write authorizer before parsing/leasing, reauthorize intent replay, preserve existing ACLs and reject an overprivileged ingestion role. | V1-05, V1-06 | U/I |
| E74 | COMMIT acknowledgement is lost or times out | Discard the uncertain connection; report the operational failure and resolve with the same intent. Never claim a failed acknowledgement proves no publication. | V1-05, V1-06, V1-11 | U/I |

| E75 | RLS allows reading/inserting a staging generation but silently hides its ready UPDATE | Require exactly one ready-transition row before changing the active pointer; rollback the entire generation on a missing publication barrier. | V1-05, V1-06 | U/I |

| E76 | Node returns PostgreSQL bigint/domain byte offsets as decimal strings | Decode only canonical nonnegative integer strings and enforce the safe-integer range; reject fractional, Boolean, null or unsafe offsets before returning candidates. | V1-07, V1-08 | U/I |

## Evidence record

When a case is exercised, record its ID, fixture/test path, language/backend/configuration, expected result, actual result, and command/report in the owning task's evidence. A case can be covered by several tests; one test can cover several cases. Conditional cases must be recorded as not applicable with a reason until that feature exists, rather than marked passed.

At each version exit, inspect all cases owned by that version. At V6, audit the entire inventory and verify that no required case is merely planned, skipped without explanation, or supported only by a mock when real integration is required.
