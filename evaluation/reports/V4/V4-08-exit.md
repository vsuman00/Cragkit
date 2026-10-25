# V4 exit: bounded corrective retrieval

V4-01 through V4-08 and checkpoints C1-C3 are complete for the internal native/synthetic development milestone on 25 October 2026. Both libraries implement bounded correction, privacy-controlled events and one optional LangChain Core adapter. [Machine-readable results](V4-08-results.json) record source/archive hashes, checks, limits and measurements. This is not registry publication or production acceptance.

## Final acceptance

The final-source serial command passed all 34 stages:

```sh
python3 tools/check_v4.py --artifacts-dir artifacts/V4/final-acceptance
```

| Evidence | Final result |
| --- | --- |
| Core tests | 1,216 Python/tool and 878 Node tests; four expected warnings from deliberately invalid bypassed models |
| Optional real SDK tests | 72 Python and 69 Node tests; repeated successfully against installed archives |
| Types/builds | Strict core Python checking over 30 files, optional Python source checking, core/SDK TypeScript typechecks and builds |
| Conformance | All prior suites plus complete EL 10, QP 13, CR 17 and EV four shared cases |
| Inputs | Reviewed development corpus and 16 sealed input files unchanged |
| Core artifacts | Four archives, three guarded default imports, 216 installed evidence and 44 installed V4 cases |
| Optional artifacts | Python wheel/source/rebuilt wheel and npm archive; rebuilt Python contents identical; installed product origins and 12 production Node SDK lock versions/integrities verified |

The final dedicated direct Neon run passed 18 native acceptance groups, including 20 corrective cases in each runtime, full normalized result parity, unchanged filters, fresh authorization after reranking, no database lease during model work, tenant isolation and cleanup. Maximum connections: two. Final stderr was empty. The actual command used the private administrative configuration outside Git:

```sh
uv sync --project packages/python --frozen --extra postgres
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --hybrid --corrective --typescript
```

Earlier passes preceded final corrections and were retained as intermediate evidence. One final-source attempt hit the existing hybrid deadline; it failed honestly, discarded the affected connection and completed cleanup. No warning was suppressed or deadline increased. The next retry was interrupted by the user. Inventory found exactly one task-owned role, 12 policies and two fixture collections; root removed that exact fixture transactionally, preserved both histories and verified the empty baseline. The subsequent final run passed with cleanup verified. Afterward, frozen default sync removed the three optional PostgreSQL packages from the core development environment.

## Does correction earn its extra work?

Six reviewed development questions were compared in hybrid, reranked and corrective modes. Five have positive retrieval labels; one is unanswerable. Every mode used the same per-request candidate-work ceiling of 12, batch size four, at most three attempts and eight synthetic provider calls. The first question used strict cl100k accounting; the others used the declared estimate.

| Mode | Document / facet recall@5 | Reciprocal rank / nDCG@5 | Synthetic calls across six questions, each runtime | Python median ms | Node median ms |
| --- | --- | --- | --- | --- | --- |
| Hybrid | 0.8 / 0.8 | 0.8 / 0.8 | 6 | 2473 | 2508 |
| Reranked | 0.8 / 0.8 | 0.8 / 0.8 | 11 | 3448 | 2971 |
| Corrective | 0.8 / 0.8 | 0.8 / 0.8 | 17 | 3739 | 3477 |

No labelled question improved facet recall. Correction remains opt-in: this sample does not justify its extra calls as a default. A separate deliberately weak-query probe changed insufficient to sufficient after an approved correction, demonstrating mechanics; it was excluded from labelled scores.

All embeddings, reranking and planning were synthetic. Approved variants were derived from development labels, making this an oracle-assisted, in-sample mechanics comparison. No held-out labels were evaluated. These timings include native database/network execution with fake model transports; they are not live-model latency estimates. Zero simulated model cost is not a hosting-cost measurement.

Evidence was returned on the one unanswerable question in every mode, so evidence-on-unanswerable rate was 1.0. That is retrieval noise, not an answer-quality score. Unanswerable/conflicting cases were explicitly checked never to become sufficient. Source fidelity and a matching schema still do not establish source truth or model quality.

## Resource observations and boundaries

On M4 / 16 GiB, the final pre-run snapshot showed 38 GiB disk available and 54 percent memory free. Only one test process/language suite ran at a time; native pools were capped at two connections. No model runtime, watcher or persistent service was started. Python's largest recorded process high-water RSS was 106,070,016 bytes; Node's largest sampled current RSS was 176,930,816 bytes. These measure different things and are not request-level peaks or comparable runtime benchmarks.

The clean Python SDK test environment contained 34,351,727 logical bytes, including core, SDK, pytest and tokenizer dependencies. The Node consumer contained 69,745,389 logical bytes including core, SDK and tokenizer dependencies. These are file totals, not disk allocation or incremental SDK costs. Isolated installed imports exclude product-source fallback; the original checkout remains physically present and fixtures/tokenizer paths are explicit.

Packages retain internal version 0.0.0. The plan's 0.4.0-alpha.1 label remains tentative for a separately authorized public release. Hosted CI, paid/live-provider quality, pooled endpoints, production and cross-platform checks were not run. Native corrective PostgreSQL dense/hybrid paths use the existing synthetic embedding profile. Application-approved variants, coverage policy, trusted scope and final model serializer remain application responsibilities. Framework tools support their documented async paths only; external prompt/history tokens and outer agent tracing are outside the tool boundary. Qdrant, existing indexes and MCP remain V5 scope.

## Owned failure cases and handoff

| Cases | Acceptance evidence |
| --- | --- |
| E05 / E34 | Guarded default imports; fixed scope/filter/limits survive malicious plans and source content |
| E42 / E44 | Exact final SDK wrapper counting, narrow tool schemas and approved identifier-preserving variants |
| E45 / E46 | Repetition/no-progress stops; atomic final-slot ledger reservations |
| E47 / E48 | Native cancellation/deadline stays operational; transient-only charged retries; permanent errors never loop |
| E49 | Unknown dispatched usage stays unknown; unsupported strict cost fails before dispatch |
| E50 / E51 | Bounded queues/export; dropped-event counters; privacy canaries and tracing/network denial |

Sol peers delivered substantive modules and complementary adversarial tests in disjoint lanes, resolved dependencies directly and named an assembler. Root inspected integration, owned contracts/fixtures/locks, ran checks serially and committed/pushed verified scopes. Astra resolved the one material capture-budget policy disagreement without expanding permissions. Final review fixes covered post-planner revocation, branch admission before embedding, forged cancellation errors and closed counters.

For example, a planner can finish after access is revoked. The next capture must remove that evidence even when planning returns no new query. Learning practice remains optional and unassessed; it does not block implementation acceptance. The next smallest planned task is V5-01, the alternative-store consistency specification, before any Qdrant implementation. Original user security reports remain untouched and excluded from commits. See [release notes](../../../docs/releases/V4.md), [the adapter guide](../../../docs/integrations/langchain.md) and [the tracker](../../../tasks/todo.md).
