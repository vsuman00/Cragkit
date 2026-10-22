# Cragkit: complete library architecture

Design baseline v0.1 | 19 October 2026 | Status: governing target architecture; implementation and verification evidence are tracked in [todo.md](../../tasks/todo.md). This document is not a claim that the full design is implemented or benchmarked.

The [BRD](../product/BRD.md) records intended users, business requirements and outcome measures. The [master plan](../../tasks/plan.md) assigns delivery milestones; neither product intent nor a design diagram establishes runtime acceptance.

## 1. The problem and the product

Developers building document-backed applications repeatedly assemble ingestion contracts, database access, semantic and lexical retrieval, ranking, retries, citations, context limits, and diagnostics. A short search call hides substantial integration work. When evidence is missing or irrelevant, applications often have no structured way to distinguish that condition from a successful search.

Cragkit will be an installable Python and TypeScript retrieval library that owns this recurring work behind a small, typed API. It will return source-linked excerpts, an estimate of which parts of the request have evidence, explicit limitations, and execution diagnostics. Applications retain control of their data, providers, authorization, and final answers.

The intended result is less retrieval integration and maintenance work, with observable behavior and measurable quality. This remains a product hypothesis until developers complete real integration tasks. There is no established numerical reduction from 200 lines to 5, and no claim that the library has already solved hallucination.

The first evaluation corpus should be engineering documentation: Markdown, plain text, runbooks, ADRs, and postmortems. The interfaces should support other domains without claiming tested quality there. A question about an actual incident requires incident-specific evidence; general documentation cannot establish its cause.

### Product boundaries

| Included in the library design | Ownership outside the core |
| --- | --- |
| Native Python and native TypeScript retrieval engines | Application authentication and trusted identity resolution |
| Small ingestion API and an existing-index adapter contract | Crawling, enterprise connectors, and application data ownership |
| Hybrid retrieval, fusion, reranking, bounded correction | Final-answer generation and permission to take actions |
| Extractive packing, source references, coverage estimates | Truth and completeness of source documents |
| Typed results, budgets, cancellation, local diagnostics | Hosting, credentials, backups, and provider accounts |
| Optional agent-tool and MCP adapters | A hosted dashboard or commercial service |

The npm package executes in a Node.js application without a Python server. The Python package executes in its Python application. Optional MCP is a separate process wrapper around a library instance. Browser-side database access is outside the supported deployment model.

## 2. Decisions consolidated from the discussion

This baseline follows the user's later library-first clarification where it differs from the original Gemini proposal. The original proposal and HTML remain historical inputs. The earlier review's Python-service-backed TypeScript recommendation is not the selected design.

| Decision | Rationale and consequence |
| --- | --- |
| Two native runtimes, one behavioral specification | Meets pip and npm expectations; requires explicit cross-language conformance work. |
| PostgreSQL reference adapter first | Keeps canonical evidence, lexical search, vectors, and publication transactions in one database. |
| Qdrant adapter after the reference pipeline | Preserves the planned backend choice without introducing distributed publication into the first implementation. |
| Native PostgreSQL FTS as the reference lexical method | It is not BM25. True BM25 remains an adapter capability with its own dependencies. |
| Deterministic orchestration around optional model calls | Attempt limits and contracts can be enforced; live model output is not deterministic. |
| Exact excerpts as the default output | Avoids generating replacement source text during compression. |
| Coverage assessed per question facet | A high score on one passage cannot establish that all parts of a question are answered. |
| Immutable access scope and required filters | Query rewriting cannot broaden permissions or remove caller constraints. |
| Research-informed, evaluation-gated defaults | No universal reranker threshold, unmeasured latency promise, or zero-hallucination promise. |
| No automatic database migrations at import or retrieval | Applications control schema changes and database privileges. |

## 3. System context and deployment

See [system overview](diagrams/01-system.svg) and the [editable diagram catalog](DIAGRAMS.md). Boxes within the library are modules, not network services.

An application constructs one reusable retriever per compatible configuration, injects adapters and provider clients, and submits requests with an access scope resolved by trusted application code. Each request gets independent state, deadlines, counters, and cancellation. A retriever must not retain a previous user's question, candidates, or permissions.

Three paths share the same engine:

1. Direct application calls to `retrieve`.
2. An optional framework tool adapter that exposes a narrow request schema.
3. An optional MCP host that resolves identity and then invokes the library.

Ingestion is a separate write path. It may run in a script, worker, or application process. Retrieval uses a read-only database role where practical. Administrative migration and deletion credentials are separate. Database integration requires access to PostgreSQL, which may be remote. On 22 October 2026, the user selected Neon to replace Supabase as the development host, retaining PostgreSQL with pgvector and native FTS. The standard PostgreSQL adapter remains the boundary; local PostgreSQL/Docker is optional and routine unit tests use fixtures. Follow the [Neon migration plan](../neon-migration-plan.md) and [runbook](../neon.md); the tracker distinguishes provisioning, security, native acceptance and cutover. Earlier Supabase results remain evidence for their tested target and do not prove Neon compatibility. Kubernetes, Redis, a task queue, and a GPU are not core requirements.

The architecture supports API-backed models and optional local models. On the previously inspected M4/16 GB machine, begin with a small corpus and one local model at a time, or provider-backed models. This is a development approach, not a benchmark or a promise that every model fits. Record measured peak memory before enabling concurrent model workloads.

## 4. Packages and internal boundaries

All package names below are proposed; registry availability has not been checked.

| Module | Responsibility | Main interface |
| --- | --- | --- |
| Core contracts | Versioned requests, results, errors, limits, events | `RetrievalRequest`, `RetrievalResult` |
| Orchestrator | Request-local state machine and shared resource ledger | `Retriever.retrieve` |
| Planner | Original query preservation, facets, optional decomposition | `Planner.plan` |
| Store adapter | Capabilities, scoped candidates, authorized source fetch | `SearchStore` |
| Embedding adapter | Batch and query embeddings with a fixed profile | `Embedder` |
| Fusion | Stable rank fusion and identity merging | Pure function |
| Reranker | Query-candidate relevance ordering, score metadata | `Reranker.rank` |
| Coverage assessor | Supported, missing, unknown, conflicting facet estimates | `CoverageAssessor.assess` |
| Recovery policy | Decide whether and how to spend another attempt | `RecoveryPolicy.next` |
| Evidence packer | Extractive spans, deduplication, budget accounting | `EvidencePacker.pack` |
| Tokenizer | Count the exact selected serialized representation | `TokenCounter` |
| Ingestion | Canonical revisions, chunking, staging, publication | `Indexer.ingest` |
| Observability | Redacted events and optional trace export | `EventSink.emit` |
| Integrations | Framework schemas, tool rendering, MCP transport | Optional packages |

Core imports must not load a database driver, download model weights, contact a network, or import agent frameworks. Python can use extras for database/model integrations. TypeScript should use separate adapter packages or explicit subpath exports with optional dependencies. Model assets require explicit acquisition, checksums, version records, and license review.

Proposed stack: Python with Pydantic v2 and asyncio; strict TypeScript with Zod; JSON Schema for shared wire fixtures; PostgreSQL with pgvector and native FTS; psycopg async pooling and a Node PostgreSQL pool behind adapters; pytest and Vitest for tests. Exact supported runtime and dependency versions are pinned after the compatibility spike, before publishing. Optional ONNX reranking needs equivalent tokenizer, model revision, preprocessing, and truncation rules in both runtimes.

## 5. Contract-first API

The following is proposed API pseudocode, not a claim that these imports run today. Provider and store construction is deliberately explicit.

```python
async with Retriever(store=store, embedder=embedder,
                     reranker=reranker, policy=policy,
                     token_counter=token_counter) as retriever:
    result = await retriever.retrieve(
        RetrievalRequest(query=question, collection="engineering",
                         limits=limits),
        scope=trusted_scope,
    )
```

```typescript
const retriever = new Retriever({store, embedder, reranker, policy, tokenCounter});
try {
  const result = await retriever.retrieve(
    {query: question, collection: "engineering", limits},
    {scope: trustedScope, signal: abortController.signal},
  );
} finally {
  await retriever.close();
}
```

The instance closes only resources it created or was explicitly given ownership of. Injected pools and clients remain caller-owned by default. `close` is idempotent; it rejects new work, permits a bounded drain, then cancels remaining work. Python cancellation propagates through child tasks; Node uses a propagated abort signal. CPU inference requires a bounded worker/executor so it does not block the event loop.

### Request

| Field | Contract |
| --- | --- |
| `schema_version`, `request_id` | Versioned envelope; caller ID optional, generated otherwise. IDs are tracing identifiers, not authorization. |
| `query` | Required nonempty text, bounded UTF-8 bytes; original preserved for every recovery and trace. |
| `collection` | Application-selected logical corpus; resolved against store capabilities. |
| `required_filters` | Typed allowlisted predicates; ANDed with access scope on every branch. No raw SQL or arbitrary provider expressions. |
| `search_hints` | Optional relevance preferences; changes allowed only by policy and recorded. |
| `limits` | Deadline, max attempts, subqueries, candidates, context tokens, provider calls, and optional spend ceiling. |
| `output_profile` | Renderer version, tokenizer identity, envelope reserve, and strict or estimated counting mode. |

`scope` is a separate trusted argument with tenant, principal/grants, and authorization revision. It is never exposed as an LLM-editable tool argument. Libraries cannot authenticate an arbitrary caller by themselves; an application that accepts forged scope defeats this boundary.

### Result

| Field | Meaning |
| --- | --- |
| `status` | `sufficient`, `partial`, or `insufficient`, always an evidence estimate. |
| `execution` | `complete` or `degraded`; operational fallback is visible independently of evidence quality. |
| `evidence` | Ordered exact source spans with collection, document, revision, chunk, offsets, digest, and safe locator. |
| `facets` | Original question facets, evidence IDs, assessment method/version, and state: `supported`, `missing`, `unknown`, `conflicting`. |
| `context` | Exact packed representation intended for the consuming model. |
| `usage` | Stage durations, attempt count, provider usage, known/estimated cost, and context token count. |
| `limitations` | Structured codes such as incomplete facets, stale evidence, truncated evidence, or degraded search. |
| `trace_id`, `versions` | Trace reference; engine, policy, schema, model, tokenizer, and index identities. |

`sufficient` means all required facets pass the selected assessment policy after packing, with no unresolved required conflict. It does not mean proven true. Without a suitable coverage assessor, coverage is `unknown` and cannot produce `sufficient`. Useful excerpts may still return `partial`.

Operational failures use typed exceptions in both runtimes: `InvalidRequest`, `UnauthorizedScope`, `UnsupportedCapability`, `IndexNotReady`, `EmbeddingProfileMismatch`, `ProviderUnavailable`, `DeadlineExceeded`, `ContextBudgetTooSmall`, and `IntegrityViolation`. Expected lack of evidence is a result, not an exception. Errors carry stable codes, retryability, and redacted details. Cancellation uses the runtime's cancellation semantics. Error paths never masquerade as missing documentation.

## 6. Ingestion and document lifecycle

See [ingestion diagram](diagrams/03-ingestion.svg). The first ingestion path accepts caller-supplied text and metadata, plus basic Markdown/plain-text loading. Existing indexes are usable through a capability-checked adapter. Scanned PDFs, OCR, complex tables, web crawling, and enterprise connectors are later extensions with their own fidelity tests.

1. Validate document identity, tenant, collection, size, metadata, and caller write authorization. Reject unsupported encodings and formats explicitly.
2. Preserve source bytes or an application-owned immutable locator and digest. Extract canonical UTF-8 text. Record parser version and normalization rules. Canonical text is evidence extracted from the file, not proof that extraction was correct.
3. Identify headings, paragraphs, code blocks, and available page/line mappings. Chunk at structural boundaries; use a configurable token target and maximum. Preserve tables/code blocks when possible; flag oversized splits instead of silently breaking meaning.
4. Store byte offsets into immutable canonical UTF-8 text. Use zero-based, start-inclusive/end-exclusive byte spans in both runtimes. Never mix Python code-point offsets with JavaScript UTF-16 offsets. Line/page locators are supplementary and may be unavailable.
5. Create an index generation containing chunker, parser, embedding, and lexical profiles. Embed chunks in bounded batches; validate dimensions, finite numbers, normalization, and model identity. Query embedding must use the same profile.
6. Build lexical entries and an explicit identifier field for symbols/error codes. Ordinary language tokenization may split identifiers; identifier retrieval gets its own fixtures and rank list.
7. Write staging records using a stable document revision and generation key. Enforce uniqueness atomically. A repeated ingestion intent with the same payload returns the existing result; a different payload under the same idempotency key fails.
8. Validate chunk spans/digests, expected counts, and index readiness. Publish the document's active generation in a short transaction. Model calls never run inside the publication transaction.
9. A failed build leaves the old generation active. Staging records can be retried or garbage-collected under a documented retention policy. Concurrent updates compare the expected active revision; a slower job cannot overwrite a newer publication silently.

A metadata or ACL update changes authorization immediately and invalidates scoped caches. A content update creates a new immutable revision. Deletion first tombstones the document, blocking retrieval, then removes derived indexes and source content according to the owner's retention policy. Historical citations can return `unavailable`; retention does not override deletion requirements. Logs and caches participate in deletion policy.

Embedding changes require a new profile and index generation. Different dimensions or model spaces cannot share a searchable vector index. Build a shadow generation, evaluate it, then switch the active pointer atomically. Keep rollback eligibility explicit; do not roll back security revocations.

## 7. Storage model and database connection

### Logical PostgreSQL schema

All foreign keys and uniqueness constraints include tenant/collection identity where necessary. IDs should not allow a cross-tenant reference to another tenant's revision or chunk.

| Entity | Essential columns and relationships |
| --- | --- |
| `collections` | Tenant, collection ID, schema version, active profile, policy metadata. |
| `documents` | Tenant, collection, document ID, active generation ID, tombstone, metadata, authorization revision. |
| `document_revisions` | Document key, revision ID, source digest/locator, canonical text/digest, parser identity, creation time. Immutable. |
| `index_generations` | Revision key, generation ID, chunker profile, embedding profile, lexical profile, status, expected chunk count. |
| `chunks` | Generation key, chunk ID, parent/section reference, UTF-8 start/end, source text digest, safe metadata. |
| `chunk_vectors_<profile>` | Chunk key plus `vector(d)` for one explicit embedding profile; vector index built for that profile. |
| `chunk_lexical` | Chunk key, `tsvector`, language configuration, exact identifier tokens; GIN and suitable identifier indexes. |
| `document_grants` | Document key, grant/principal identifiers, authorization revision; application-defined membership resolution. |
| `ingestion_jobs` | Stable intent key, payload digest, state, attempt count, generation, last redacted error. |

This is a logical schema, not executable migration SQL. Phase 1 must turn it into migrations with indexes, checks, composite foreign keys, and adapter tests. Avoid hardcoding one embedding dimension globally. For a first profile, one physical vector table is enough; adding profiles is an explicit migration/provisioning action.

### Connection and query lifecycle

At explicit initialization, validate schema compatibility, extension availability, embedding profile, and adapter capabilities. Accept a caller pool or a validated connection configuration. Never log a credential-bearing DSN. Remote connections use certificate validation; local-development socket configuration is explicit. Migration and extension installation are separate administrative commands.

Acquire connections with a deadline; set transaction-local authorization context when RLS is configured. Scope parameters must never leak between pooled requests. Return connections in `finally` blocks. Apply statement timeouts using the remaining request budget. Bound pool waiters and concurrent search calls; the library must not create one pool per request.

Reference PostgreSQL retrieval uses a read transaction to obtain dense, lexical, and identifier candidates from the same active-generation snapshot, preferably through one query with scoped CTEs. These are independent logical retrieval branches; the database may execute them without physical parallelism. Release the transaction before external reranking. Immediately before packing, perform an authorized source fetch and recheck tombstones and authorization revision. If publication changed, either use the still-valid immutable revision or retry within budget; policy and returned revision make this explicit.

Parameterize values; allowlist identifiers and filter operations. Apply scope before candidate selection, not only to the final top-k. Defense-in-depth RLS is recommended for multi-tenant PostgreSQL deployments. Table owners and roles with bypass privileges require particular care; test with the real runtime role. [PostgreSQL row security](https://www.postgresql.org/docs/current/ddl-rowsecurity.html).

Native FTS uses PostgreSQL ranking functions such as `ts_rank_cd`, with a declared text-search configuration. It must not be labelled BM25. [PostgreSQL text search](https://www.postgresql.org/docs/current/textsearch-controls.html).

Start with exact vector search for small test corpora. Add HNSW only after measuring recall and latency. Approximate search combined with filtering can underfill results; investigate bounded search expansion or exact fallback with the same filters, never permission relaxation. [pgvector documentation](https://github.com/pgvector/pgvector).

### Qdrant and existing stores

`SearchStore.capabilities()` declares dense/lexical methods, filter operators, source resolution, revision support, and consistency semantics. Hybrid mode requires both search branches; unsupported capabilities fail early unless the caller explicitly selects a degraded mode.

The Qdrant adapter is an alternative deployment profile, not a required second database. Store immutable source revisions through a `SourceStore`; it may use payloads for small text or caller-owned storage. Every point carries tenant, collection, document revision, generation, ACL/filter fields, and profile identity. Sparse vectors require a declared encoder; they are not automatically BM25. Qdrant's native fusion can be an optimization after equivalent behavior is tested. [Qdrant hybrid search](https://qdrant.tech/documentation/search/hybrid-queries/).

Separate source and vector stores require idempotent staging, completion manifests, publication barriers, and repair of partial writes. Readers must resolve only published generations and recheck authorization against the authoritative source. The adapter must preserve backend filtering while handling stale ACL replicas; it must never send unverified candidate text to an external provider. This consistency work is a Phase 6 requirement, not hidden inside the first PostgreSQL release.

## 8. Retrieval state machine

See [retrieval flow](diagrams/02-retrieval.svg) and the detailed state and sequence diagrams in [DIAGRAMS.md](DIAGRAMS.md).

1. **Validate and bind.** Validate request, trusted scope, capabilities, tokenizer, profile, and limits. Create a monotonic deadline, cancellation handle, and atomic shared budget ledger. No model can edit these values.
2. **Plan.** Default to the original query as one facet. An optional structured planner may decompose a complex question. Preserve exact identifiers and caller constraints; record assumptions. Reject malformed or oversized plans and fall back to the original query when policy permits. Decomposition does not implement dependent multi-hop investigation.
3. **Search.** Embed each allowed search query; obtain dense, lexical, and optional identifier lists under identical immutable filters and published-generation rules. Bound fan-out. Keep list identity, rank, raw score, score direction, and profile.
4. **Fuse.** Deduplicate within each list by tenant/collection/document/revision/chunk. Use weighted reciprocal rank fusion: `score(d) = sum(weight_i / (k + rank_i(d)))`, ranks starting at 1. Missing items contribute zero. `k=60` is a starting experiment, not a confidence calibration. Break ties by canonical ID. Normalize total branch weights per facet so extra rewrites do not gain unlimited votes; across attempts retain each list family's best rank per candidate rather than repeatedly accumulating votes.
5. **Rerank.** Rank the bounded candidate set against the original question and relevant facets. Preserve raw scores and model identity. Scores need not fall in 0-1 and never become truth probabilities by renaming them. Record input truncation. Select cutoffs from calibration data for the chosen model/corpus.
6. **Assess.** Map evidence to required facets. Distinguish missing, unknown, and conflicting evidence. Require temporal/version context when the question asks about current behavior. The assessor may be heuristic or model-based; its method and uncertainty are visible.
7. **Correct if useful.** A recoverable deficit may trigger targeted query rewriting, identifier expansion, or bounded candidate expansion. Retain useful prior evidence. Detect repeated normalized queries, repeated candidate sets, and no-progress loops. Stop at the first resource limit or when policy finds no justified next action.
8. **Fetch and pack.** Reauthorize exact source spans, validate digests and offsets, expand necessary parent context, merge overlapping spans within the same revision, and select across facets. Never silently replace quotations with model summaries.
9. **Reassess packed evidence.** Packing can remove the only passage for a facet. Estimate coverage again using only returned spans. If necessary, rebalance once within budget; report partial or insufficient evidence if coverage cannot fit.
10. **Return.** Freeze the result with versions, limitations, accounting, and redacted trace. A gap event means unresolved retrieval, not proof that a document is missing from the organization.

### Limits and recovery policy

Proposed development preset: 3 total search attempts, at most 4 planned subqueries, at most 40 dense and 40 lexical candidates per subquery, a global 200-candidate union ceiling, at most 40 reranked candidates, and 2,000 context tokens. These are bounded starting values to evaluate, not optimized defaults. Additional identifier candidates must fit the global ceiling. The initial request deadline is an explicit application setting; examples can start at 10 seconds and adjust from measurements.

All limits apply across retries, including provider SDK retries. Reserve calls/tokens before concurrent dispatch and reconcile after completion. Set provider timeouts from the remaining deadline; retry only recognized transient failures with bounded backoff. Rewrites count as attempts; transport retries have a separate, still bounded counter. A malformed model response cannot trigger an unlimited repair loop.

Cost ceilings are strict only where an upper bound can be computed from versioned prices and token limits. Unknown provider usage is marked unknown, not zero. A strict budget rejects unsupported accounting; estimated budgets are labelled estimates. Cancellation stops new work but cannot guarantee that an already-dispatched provider request incurs no charge.

## 9. Evidence integrity and hallucination risk

There are four different checks: source extraction fidelity, retrieval relevance, evidence sufficiency, and final-answer support. They require different tests.

| Failure | Design response | Remaining limitation |
| --- | --- | --- |
| Chunk removes a heading, negation, or table context | Structural chunking, source maps, parent expansion, boundary fixtures | Parser and segmentation errors remain possible. |
| Search finds plausible but unrelated text | Hybrid retrieval, reranking, facet-level assessment | Learned relevance is an estimate. |
| Rewrite invents the intended incident or removes constraints | Preserve original query, fixed constraints, logged assumptions | A planner may still choose poor subqueries. |
| Compression invents text | Return verified source slices; generated summaries excluded from evidence | An authentic quote may still be misleading without context. |
| Citation points to a stale or changed document | Immutable revision/digest and availability status | Sources may themselves be outdated or false. |
| Parent LLM ignores evidence or fills missing facts | Explicit partial/insufficient signals; answer-support adapter is later research outside V0-V6 | The consuming application must enforce its response policy. |

RAGTruth documents unsupported and contradictory output even with retrieved context. Citation quality is also distinct from answer quality, as studied by ALCE. These support separate evaluation of retrieval and generation; they do not establish that Cragkit prevents hallucination. [RAGTruth](https://aclanthology.org/2024.acl-long.585/), [ALCE](https://arxiv.org/abs/2305.14627).

An optional later answer-support adapter can split a draft answer into claims, attach source spans, mark unsupported/conflicting claims, and advise abstention. Its judgments remain fallible. It cannot retroactively make a final answer safe unless the host application uses the outcome.

## 10. Context serialization and token accounting

Each evidence item includes the exact text and compact source reference. The model-facing context has a versioned renderer; the diagnostic result envelope is separate. Count the exact rendered context, including citation labels and separators, with the selected tokenizer. Reserve a declared wrapper allowance for tool output. A tool adapter must recount its final serialized model-visible payload if it claims a ceiling for that payload.

Avoid duplicating full text in both diagnostic JSON and model-facing output. Untrusted source text is escaped/delimited as data. The renderer never treats document content as instructions or trusted markup. No raw HTML execution is needed.

The packer selects spans with facet coverage, relevance, and diversity in mind. It cuts only at valid UTF-8 boundaries and prefers sentence/section boundaries. It cannot drop negation or join disjoint passages as if continuous. Omitted regions receive an explicit separator. Citations retain individual span offsets even when displayed together.

If the mandatory output envelope does not fit, raise `ContextBudgetTooSmall`. If the envelope fits but evidence does not, return an insufficient result with a budget limitation. Strict token ceilings require the actual tokenizer and renderer; approximate counting produces an explicitly estimated result and cannot claim a hard bound for a different downstream model.

## 11. Failures, privacy, and operational controls

| Situation | Required behavior |
| --- | --- |
| No authorized matches | Return insufficient; do not reveal whether other tenants have matches. |
| One facet has evidence | Return partial with missing/unknown facets. |
| Dense branch unavailable | Fail by default; explicit lexical fallback returns degraded execution. |
| Reranker unavailable | Fail or use explicitly configured unreranked fallback, visibly degraded. |
| Invalid source span/digest | Quarantine the candidate; fail with integrity error if a trustworthy result cannot be formed. |
| Timeout or caller cancellation | Cancel children, release resources, emit terminal telemetry; no silent success result. |
| Revoked ACL during retrieval | Recheck before source release; discard inaccessible evidence. Request-time authorization cannot revoke bytes already delivered. |
| Conflicting applicable sources | Return conflicting facet state and both allowed references, subject to budget. |
| Telemetry exporter fails | Do not block retrieval; bounded buffer/drop counters. Durable audit belongs to the application. |

Documents and provider outputs are untrusted. Validate structured outputs and reject invented chunk IDs. Prompt-injection instructions inside documents cannot change tools, access scope, queries beyond policy, or system configuration. The core has no general code executor or arbitrary URL fetcher. Provider calls can expose query and candidate text: applications must select allowed providers and data policies explicitly. Local mode must be tested for unintended network access.

Trace events contain request/stage/attempt IDs, latency, counts, stop reasons, profile versions, and redacted evidence IDs. Raw queries and source text are off by default. Full replay data is opt-in, access-controlled, and retained under an application policy. Even hashes and IDs may reveal relationships; do not advertise them as anonymous.

No result cache in the first vertical slice. Later keys must include scope/authorization revision, collection generation, query, immutable filters, model/policy/tokenizer versions, and limits. Reauthorize cache hits. Embedding caches need profile plus input digest and appropriate tenant isolation. In-process limits do not enforce a global quota across many application instances; global rate limits are caller infrastructure.

## 12. Cross-language parity and extension contracts

Maintain one versioned schema and normative behavior specification. Python and TypeScript implementations share JSON fixtures and expected outcomes, not a hidden Python execution service. Both ship native orchestration, fusion, packing, and database adapters.

Conformance fixtures cover stable ordering, byte offsets, filter serialization, deadline/attempt semantics, result enums, source identifiers, token serialization, and error codes. Reject nonfinite numbers; represent large identifiers as strings. Use canonical fixture serialization for hashes. Model scores use documented numerical tolerances; tiny floating-point differences must not silently change semantic contract claims.

Use deterministic fake providers to compare engines exactly. Live models require separate quality tests; sharing JSON schemas cannot make their outputs identical. Local models should share artifact checksums and preprocessing fixtures. Capabilities expose differences honestly rather than emulating unsupported features silently.

Version public API, storage schema, events, and index profiles separately. Reject incompatible versions with a migration message. Additive optional fields are preferred, but changes in default policy, ordering, or statuses can also affect users and require release notes and regression evaluation.

## 13. Validation and release evidence

Automated invariants and empirical quality claims have separate gates.

| Layer | Evidence required |
| --- | --- |
| Contracts | Shared valid/invalid fixtures accepted or rejected consistently by both runtimes. |
| Source fidelity | Every returned quote matches its immutable revision bytes and span; Unicode, code, tables, and boundary fixtures. |
| Authorization | Cross-tenant negative tests in every search/fetch/cache path; real runtime-role RLS tests. |
| Lifecycle | Concurrent updates, interrupted ingestion, tombstones, reindex and rollback tests. |
| Resource control | Deadline, cancellation, pool saturation, provider rate limit, fan-out and retry exhaustion tests. |
| Retrieval quality | Held-out labelled questions with relevant passages and facet labels. Compare lexical, dense, hybrid, hybrid plus rerank, and full correction. |
| Coverage quality | False-sufficient rate, abstention precision/recall, conflict detection, and supported facets after packing. |
| Downstream answers | If demonstrated, unsupported-claim rate and citation support assessed separately from retrieval. |
| Performance | p50/p95 latency, peak RSS, database work, calls/tokens/cost; disclosed corpus size, hardware, warm/cold conditions and concurrency. |
| Developer experience | Independent integration tasks: time to first retrieval, configuration errors, understanding partial results, maintenance effort. |

Split train/development/held-out questions by document families where possible to reduce leakage. Start with a small manually reviewed suite, then grow to at least a few hundred diverse questions before broad quality claims. Include unanswerable questions, exact IDs, ambiguous intents, multi-facet queries, outdated revisions, unauthorized matches, Unicode, prompt injection, and adversarially similar documents. Synthetic questions need human review.

Publish all compared configurations and confidence intervals where sample sizes permit. Tune on development data only. Release quality targets must be frozen before the held-out run; this document does not invent performance numbers. Gate invariant failures at zero observed violations in the defined suite, while stating the suite's scope. A test pass is evidence within that scope, not a universal guarantee.

Use ablations to decide whether planning, reranking, correction, and parent expansion justify their cost. More stages do not automatically improve results. The CRAG paper motivates quality-conditioned correction, but its web-search strategy differs from this private-corpus design. [CRAG](https://arxiv.org/abs/2401.15884). The six local papers are indexed in [papers/README.md](../../papers/README.md).

## 14. Build phases and dependencies

These are proposed acceptance gates, not an assertion of implementation or user sign-off. Build both runtime contracts from the beginning; a Python spike may lead internally, but TypeScript is not deferred into a service client.

| Phase | Build scope | Exit evidence |
| --- | --- | --- |
| 0: specification and corpus | Finalize schemas, status semantics, scope model, small labelled corpus, provider/model shortlist, compatibility/license checks | Written fixtures and evaluation protocol; record unresolved model choices. |
| 1: first end-to-end slice | Both runtimes; text ingestion; immutable revisions; PostgreSQL migrations; lexical retrieval; exact citations; lifecycle ownership | Ingest a Markdown document and retrieve authorized source spans from Python and TypeScript against the same DB; deletion, invalid input, cancellation tests. |
| 2: hybrid retrieval | Embeddings, profile validation, vector search, identifier search, RRF, shared rank fixtures | Cross-runtime parity and measured comparison against lexical/dense baselines. |
| 3: evidence selection | Reranking, extractive packing, token accounting, facet assessment, partial outcomes | Calibrated development policy; source, budget, multi-facet and truncation tests. |
| 4: bounded correction | Optional planning, targeted rewrites, no-progress detection, shared ledger and limits | Full-loop ablations; all retries constrained; no required-filter changes. |
| 5: usable alpha libraries | Packaging, examples, provider errors, observability, docs, one Python and one TypeScript tool adapter | Clean-environment installation and smoke tests; direct-library and adapter results agree. |
| 6: backend and transport extensions | Qdrant consistency profile, existing-index examples, optional MCP, additional adapters | Capability, publication, authorization and conformance suites for each extension. |
| 7: release candidate | Scale/concurrency tests, migration/rollback docs, compatibility matrix, held-out benchmark, developer trial | Published limitations and evidence; dependency/model licensing, package integrity and release checklist complete. |
| Later research | PDF/OCR, dependent multi-hop, answer verification, optional telemetry UI | Separate design and evaluation; do not silently include in core release claims. |

The first useful milestone is Phase 1, not the entire agentic loop. It establishes the data and contract foundation on which more sophisticated retrieval depends. The first complete corrective-library alpha is Phase 5. Qdrant and MCP remain in the planned architecture with explicit later gates.

## 15. Proposed repository structure

```text
docs/architecture/         architecture, diagrams, decisions
contracts/                JSON schemas, canonical fixtures, event specification
packages/python/          core, ingestion, adapters, tests, pyproject.toml
packages/typescript/      core, ingestion, adapters, tests, package.json
integrations/             optional framework and MCP packages
storage/postgres/         migrations, permissions, integration fixtures
evaluation/               labelled corpus, baselines, ablations, reports
examples/python/          direct library and framework examples
examples/typescript/      direct library and framework examples
tools/                    conformance and release utilities
papers/                   unchanged research PDFs and provenance manifest
```

Only this documentation directory and its diagrams are created by this architecture task. The tree above describes future implementation files. CI should run contract and invariant tests on every change; integration jobs use disposable databases; live-provider benchmarks are separate, explicit jobs. Releases build and test wheel/sdist and npm tarballs in clean environments before publishing. No credentials or model assets are bundled by accident.

## 16. Remaining choices and how to resolve them

| Choice | Proposed way to decide |
| --- | --- |
| Embedding and reranker models/providers | Compare a small local option and a provider option on the target corpus, latency, memory, cost, license, and parity. |
| Coverage assessor | Compare conservative heuristics with a structured model judge using human-labelled facets; retain unknown states. |
| Runtime/version matrix | Verify Python and Node versions against database drivers, tokenizer and optional ONNX packages; publish tested combinations. |
| Package names and license | Check registry availability and dependency/model licenses before publication; original MIT intent remains proposed. |
| Performance and false-sufficient targets | Set targets from the first baseline and target application needs, then freeze before held-out evaluation. |
| Hosted telemetry or monetization | Validate developer demand separately; no cloud dependency in the library design. |

Use the tracker to select the next dependency-ready task rather than restarting the contract and corpus phase. Model-specific thresholds, public performance claims, and release readiness must come from implementation and evaluation rather than this design document.
