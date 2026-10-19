Cragkit: product and architecture review

Reviewed on 19 October 2026. Inputs: the pasted Gemini discussion and `project_context_and_architecture.md`. The directory contained only that architecture document when inspected: no application code, dependency manifests, tests, benchmarks, or Git repository. This review assesses the proposal. It does not establish implemented behavior, measured performance, customer demand, or an approved implementation plan.

My recommendation is to pursue a smaller version of this idea. Packaging retrieval behind one tool call gives developers a useful boundary. The strongest product promise would be: retrieve evidence with traceable sources, report incomplete coverage, and respect explicit execution budgets. The current document promises more certainty than its proposed mechanisms can deliver and introduces too many deployment and integration paths before proving retrieval quality.

A possible positioning statement is: "Cragkit gives AI agents source-linked evidence within a defined context budget, with bounded recovery when retrieval falls short." This is a proposed description, not an established capability.

The useful part of Gemini's proposal

The caller should not need to orchestrate embedding, lexical retrieval, fusion, reranking, recovery, and context selection on every agent step. A focused library can own those decisions and make them observable. Keeping framework integrations outside the engine is also sensible. An agent developer should be able to change frameworks without replacing the retrieval policy.

Returning evidence instead of generating the final answer is another good boundary. It allows the parent application to own the answer, tone, conversation, and downstream actions. Cragkit should still provide enough information for that application to distinguish a supported response from a partial result or an operational failure.

However, the individual retrieval techniques do not establish a product advantage. LlamaIndex exposes `QueryFusionRetriever`; Haystack provides RRF through `DocumentJoiner`, alongside rankers and routers; Qdrant supports hybrid and multistage queries. My inference is that Cragkit must compete on reliable defaults, explicit contracts, evaluation evidence, and ease of operation, rather than the presence of fusion or reranking. This is a limited comparison of documented capabilities, not an exhaustive market study. [LlamaIndex retrievers](https://developers.llamaindex.ai/python/framework-api-reference/retrievers/vector/), [Haystack DocumentJoiner](https://docs.haystack.deepset.ai/docs/documentjoiner), [Haystack rankers](https://docs.haystack.deepset.ai/docs/rankers), [Haystack routers](https://docs.haystack.deepset.ai/docs/routers), [Qdrant hybrid queries](https://qdrant.tech/documentation/search/hybrid-queries/).

The initial audience should be narrower than everyone building an agent. My suggested starting user is a Python backend engineer building an internal assistant over engineering documentation already stored in PostgreSQL. Markdown documentation, ADRs, runbooks, and postmortems make a coherent first corpus. This is a recommendation to validate, not evidence that this audience will adopt or pay for Cragkit.

Corrections needed in the current specification

| Location in the architecture document | Issue | Recommended change |
| --- | --- | --- |
| Lines 10 and 23-25 | High-signal or verified context is presented as a guarantee. | Promise enforceable execution and provenance properties. Treat relevance and sufficiency as estimates; evaluate answer quality separately. |
| Lines 13 and 17 | An LLM-based planner is described as deterministic. | Specify bounded control flow. Use recorded model outputs and stable inputs for replay; do not promise identical live model results. |
| Lines 19 and 99 | Native PostgreSQL full-text ranking is conflated with BM25. | Name the selected lexical backend accurately and make true BM25 an explicit capability. |
| Lines 22 and 51 | A universal relevance threshold is implied. | Retain model-specific raw scores and version the decision policy with its evaluation data. |
| Line 24 | Metadata filters can be relaxed without distinguishing their purpose. | Keep authorization and caller-required constraints immutable. Permit only explicitly designated search hints to change. |
| Line 24 | Internal recovery appears to avoid billing. | Explain that it avoids extra parent-agent orchestration but still consumes compute, model calls, and time. |
| Lines 25 and 89 | Failed retrieval is treated as proof of absent or outdated documentation. | Record an unresolved retrieval event first; retain a documentation-gap hypothesis for later review. |
| Lines 27 and 53 | The token ceiling has no tokenizer or serialization definition. | Define which rendered bytes, tokenizer, metadata, and wrapper overhead are covered. |
| Lines 33-38 | One engine is proposed alongside TypeScript direct database execution. | Make TypeScript a client of the same engine initially. Shared storage does not preserve execution-policy parity. |

PostgreSQL's native full-text system uses lexemes and functions such as `ts_rank` and `ts_rank_cd`; it should not be advertised as BM25. Its parser and dictionaries also affect punctuation and identifiers, so exact error-code and symbol retrieval needs separate tests. `pg_search` is an optional extension with different installation requirements; its repository currently lists AGPL-3.0. Record extension and model dependencies separately from the intended MIT license for Cragkit's own code. [PostgreSQL text search](https://www.postgresql.org/docs/current/textsearch-controls.html), [ParadeDB repository](https://github.com/paradedb/paradedb).

Reranker scores require particular care. Sentence Transformers documents cross-encoders that emit logits, with an optional sigmoid mapping into a zero-to-one range. Cohere documents query-dependent scores and recommends domain examples when choosing a threshold. A bounded number is not automatically a calibrated probability, and neither relevance nor a high rank establishes that a passage proves a claim. [Sentence Transformers cross-encoder usage](https://www.sbert.net/docs/cross_encoder/usage/usage.html), [Cohere interpretation guidance](https://docs.cohere.com/docs/reranking-best-practices).

The CRAG paper is useful inspiration, but the proposed loop differs from that paper. The paper includes an evaluator, corrective retrieval using web search, and document refinement. A reranker plus query rewriting over the same private corpus should be described as CRAG-inspired recovery. Adding web search is unnecessary for the first release and would change the data and trust boundary. [Corrective Retrieval Augmented Generation](https://arxiv.org/abs/2401.15884).

The central design problem is evidence sufficiency

Consider the example about JWT expiration compared with session-cookie expiration. Five highly ranked JWT passages can produce a strong maximum score while providing no evidence about cookies. The current happy-path rule can therefore accept a result that answers only half the question.

Keep a representation of the question's required facets and map selected evidence to those facets. Preserve the original question throughout planning. Recovery should target the missing facet and retain useful evidence already found. If the final context covers only JWT behavior, return that limitation explicitly.

Coverage estimation is itself fallible. An LLM judge can be wrong, and a keyword match can be misleading. Store the method and version used to estimate coverage, allow an unknown outcome, and test the estimate against human labels. A structural check that cited source text exists is a stronger guarantee than a judgement that the text answers a question; the API should keep those concepts separate.

Also distinguish decomposition from dependent retrieval. Searching for JWT and cookie expiration independently is parallel decomposition. Finding which deployment caused an incident and then retrieving the postmortem for that deployment requires a dependent step. The initial release can support simple decomposition without claiming general multi-hop investigation.

For a question such as "Why did the payment webhook fail above 500 RPS?", Cragkit must retrieve an actual supporting postmortem or other authorized evidence. General scaling documentation cannot establish that particular incident's cause. A documentation-only corpus also cannot substitute for live logs or metrics.

An architecture I would implement

Use one Python async engine with small typed interfaces for storage, embeddings, reranking, planning, token counting, and event emission. Pydantic v2 fits the existing document's preference. Avoid a Rust core, gRPC service, and workflow framework until profiling or an integration requirement justifies them.

The logical flow should be:

1. Validate the request, resolve trusted access scope, and establish execution limits.
2. Preserve the original query; plan facets only when the chosen policy needs them.
3. Retrieve dense and lexical candidates within the same authorized scope.
4. Fuse candidates with stable identity and tie-breaking rules.
5. Rerank and estimate evidence coverage.
6. Attempt a bounded recovery only for a recoverable deficiency.
7. Pack source excerpts, then recheck what coverage survives the packing step.
8. Return a structured outcome and emit a privacy-controlled trace.

These are logical responsibilities, not eight services. Keep retrieval state request-scoped. Avoid hidden conversational memory in the first release; it complicates reproducibility and isolation.

Represent scoring information explicitly: retriever name, raw score, score direction, rank, model identity, and policy version. Fuse ordered lists rather than adding incompatible raw scores. Deduplicate candidates by source identity and revision, and do not let many near-identical query rewrites create uncontrolled extra votes for one document. Preserve per-facet candidates so one popular subject does not consume the entire context.

Start with PostgreSQL plus `pgvector` and native full-text search, accurately named. Keep the lexical interface open to BM25 later. PostgreSQL is already central to the proposal, so this choice reduces the first deployment's moving parts. If an existing design partner instead runs Qdrant, that would be a sound reason to change the first connector.

Test filtered vector retrieval before assuming low recall is a query-language problem. The pgvector documentation explains that approximate index filtering can leave too few results and describes iterative scans that search further. Increasing search effort within the authorized scope can be a better recovery than rewriting the question. [pgvector filtering and iterative scans](https://github.com/pgvector/pgvector#filtering).

Expose the Python callable first and local MCP through stdio next. For a later remote deployment, use Streamable HTTP and test a declared client/version matrix. The current MCP transport specification names stdio and Streamable HTTP; a standalone legacy SSE endpoint should not be the default new design. [MCP transports](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports).

For TypeScript, document the tradeoff honestly: the first SDK would call a Python-backed service. It would not be an entirely in-process Node retrieval engine. A small HTTP client plus one framework adapter is enough initially. Derive wire types from a versioned schema and test Python/TypeScript payload compatibility. A direct database client should wait until there is an explicit decision about duplicated policy, reranking, security, and token-counting behavior.

The missing ingestion contract

The examples imply that a database URL and collection name are enough to connect any existing knowledge base. They are not enough to identify text columns, embedding spaces, chunking rules, authorization fields, or source revisions.

Provide one reference storage schema and one small Markdown/text ingestion path. It should establish stable document IDs, revision hashes, chunk IDs, heading paths, original text, reliable source offsets, timestamps, and collection-level embedding configuration. Track embedding model identity, dimensions, normalization, and distance metric. Reject an incompatible query embedding configuration rather than silently searching a different vector space.

Define idempotent updates and deletions. A deleted or superseded document must not survive indefinitely as retrievable evidence. Detect incompatible schema versions early. Keep ingestion writes separate from retrieval permissions. Support arbitrary existing schemas later through an adapter contract, rather than presenting universal compatibility in the first quickstart.

This ingestion path is deliberately small. A general PDF/OCR pipeline, web crawler, connector marketplace, and file synchronization service would become a second product.

What the return contract needs

Use one structured result schema and render Markdown from it when needed. A useful proposed contract separates the execution outcome from the evidence judgement:

| Field | Purpose |
| --- | --- |
| `execution_status` | Completed, failed, cancelled, or stopped by a budget. |
| `evidence_status` | Estimated sufficient, partial, insufficient, or unknown. |
| `reason_codes` | Stable explanations such as no authorized matches, reranker unavailable, or context too small. |
| `evidence` | Source excerpts with document, revision, chunk, URI, and reliable location information. |
| `coverage` | Supported and unresolved facets, including how coverage was estimated. |
| `budget` | Tokenizer identity, defined output token count, attempts, elapsed time, and known usage. |
| `trace_id` | A reference for authorized operational investigation. |
| `schema_version` | Compatibility boundary for SDKs and transports. |

Do not fabricate line ranges for sources that lack them. A citation should resolve to the revision actually retrieved. If an excerpt is shortened, retain a mapping to the original span. Keep large debug traces out of the parent model's context.

Default to extractive selection and deduplication. Generative summaries introduce another opportunity for unsupported claims and should be an opt-in later feature. For technical material, preserve relevant code blocks, negation, conditions, warnings, and exceptions. Boilerplate removal must not silently remove the qualification that makes a statement correct.

Define the token promise precisely. Count the final rendered evidence and citations with a named tokenizer; separately state whether the complete tool-result envelope is included. If the application needs a strict total ceiling, account for every model-visible field and transport rendering. Reject an impossibly small budget or return a minimal structured outcome. An arbitrary character limit is not an exact token limit across providers.

Packing must consider coverage as well as rank. If the budget forces removal of all cookie evidence, the result must become partial even if retrieval had originally found it. This interaction between sufficiency and compression deserves explicit tests.

Recovery, cost, and operational boundaries

`max_retries` alone does not bound the amount of work. With three subqueries, two retrieval channels, and an initial attempt plus two retries, a naive policy can perform eighteen logical retrieval searches before counting embeddings, planning, grading, or rewriting. Parallel execution reduces some elapsed time; it does not remove the work.

Define limits for subqueries, candidate counts, reranker pairs, provider calls, concurrency, total duration, and output size. Track cost where it is knowable and report unknown cost as unknown. A hard monetary ceiling requires conservative estimates or reservations before calls; after-the-fact usage is not enough.

Start with direct retrieval for simple queries and one optional recovery attempt. Compare that policy with the document's two-retry default before choosing a release setting. Distinguish provider retries from semantic retrieval recovery so the two cannot multiply unnoticed.

Suggested recovery actions depend on the failure:

| Observation | Possible action within policy |
| --- | --- |
| Exact identifier is absent from results | Try a dedicated identifier lookup while preserving the original literal. |
| Some question facets lack evidence | Search the unresolved facets. |
| Filtered approximate search returns too few candidates | Increase search effort within the same authorized scope. |
| An inferred topic hint was too narrow | Relax only that explicitly relaxable hint. |
| A provider times out or rate-limits | Apply bounded operational retry or a documented degraded mode. |
| New attempts repeat the same query and candidates | Stop for lack of progress. |

Retain the best authorized evidence across attempts. Stop at the deadline and propagate cancellation to outstanding work. Avoid blocking the async event loop with CPU-heavy local inference; benchmark a bounded execution pool and model reuse. Local reranking avoids a hosted rerank API charge, but still has memory, compute, download, and deployment costs.

Security requirements follow directly from the proposed recovery feature

Separate trusted access constraints, explicit caller-required constraints, and inferred hints in the data model. A model-generated plan must never establish identity or expand access. Tenant, ACL, collection access, and required product/version scope must not disappear during recovery.

Apply scope consistently to dense retrieval, lexical retrieval, reranking inputs, evidence lookup, caches, and debug output. If PostgreSQL row-level security is used, verify behavior with the actual application role. A privileged development connection is not evidence of tenant isolation. Shared caches must incorporate authorization scope and corpus revision; otherwise a correct database query can still be followed by an unsafe cache hit.

Treat retrieved documents as untrusted data. Preserve the boundary between evidence text and engine instructions. Do not execute embedded commands or follow document instructions that request more access. Parameterize database values and validate dynamic identifiers against configured schema definitions. Hosted embedding, planning, or reranking also needs an explicit policy about which queries and document text may leave the environment.

These controls reduce risks; source wrapping does not prove prompt-injection immunity. Keep telemetry redacted by default, avoid storing raw confidential queries without opt-in, and ensure outward error messages do not reveal whether inaccessible documents exist.

Knowledge-gap reporting needs a diagnostic stage

An empty or low-quality result can arise from missing ingestion, stale indexing, a model mismatch, poor chunking, lexical parsing, strict filters, low approximate-search recall, provider failure, or genuinely absent documentation. The engine usually cannot identify which explanation is true from its maximum reranker score.

Emit a neutral unresolved-retrieval event first. Record available diagnostic facts and a provisional reason. Let repeated events be grouped and reviewed before calling them confirmed documentation gaps. Distinguish missing information from stale or conflicting evidence; they require different remediation.

A useful commercial workflow might connect unresolved agent questions to triage, a documentation change, and a rerun showing improvement. A dashboard of raw failures is a weaker proposition. Payment willingness remains untested. General traces should be exportable so adoption does not require a hosted Cragkit dashboard.

Do not display automatic recall as ground truth without references. Ragas explicitly defines context recall against reference information. Label-based measurements and LLM-judge estimates should appear separately, with judge/version metadata where applicable. [Ragas context recall](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/context_recall/).

How I would prove the project is useful

Before adding broad integrations, build a small evaluation corpus with human-reviewed relevance labels and expected supporting spans. A proposed initial set is 120-200 questions across exact identifiers, paraphrases, comparisons, missing answers, version conflicts, strict scope, misleading near-matches, and malicious document instructions. This is a practical starting range, not a statistical adequacy claim.

Keep tuning and held-out evaluation separate, including related document or question families where feasible. Freeze document revisions, chunking, embedding and reranker models, tokenizer, and policy versions for comparisons. Include a small real-provider integration run separately from deterministic fixture tests.

Compare dense-only, lexical-only, hybrid, hybrid plus reranking, and the full bounded-recovery policy. Use the same corpus and relevant resource limits. The important comparison is against hybrid plus reranking, since that is a stronger alternative than a deliberately weak single search.

Measure retrieval recall and ranking quality before packing, evidence coverage after packing, unsupported-evidence acceptance, false abstention, citation/span integrity, returned tokens, latency percentiles, and resource usage. Separately evaluate final-answer quality with a fixed parent model and prompt. Improved retrieval does not by itself demonstrate improved answers.

Hard invariants should include authorized scope, valid source references, declared output budgets, attempt limits, and cancellation behavior. Use meaningful integration tests for filtered SQL and idempotent ingestion, plus failure injection for missing models and unavailable providers. Fixture tests establish control-flow behavior; they cannot establish real retrieval quality.

The release decision should be based on held-out results: does the recovery policy improve coverage or reduce unsupported evidence enough to justify its extra latency and cost? Publish unfavorable query categories and uncertainty as well as improvements. Do not adopt a generic accuracy percentage before a baseline exists.

A smaller proposed delivery sequence

| Slice | Deliverable | Evidence needed to advance |
| --- | --- | --- |
| 0 | Define the initial user, corpus boundary, result contract, threat assumptions, and benchmark format. | Realistic example questions and an explicit first-release scope. |
| 1 | Markdown ingestion, reference PostgreSQL schema, dense/lexical retrieval, fusion, and source-linked budgeted output. | Reproducible baseline evaluation and source/scope/budget checks. |
| 2 | One reranker and a documented evidence-decision policy. | Measured ranking and coverage results, including false acceptance and abstention. |
| 3 | Optional planning and one bounded recovery action. | Held-out benefit over hybrid plus reranking within declared limits. |
| 4 | Python tool adapter and local MCP server. | One real agent integration plus timeout, cancellation, and error-path checks. |
| 5 | Remote service, thin TypeScript client, and one TypeScript framework adapter. | Cross-language contract parity and deployment/security verification. |
| Later | Qdrant, more adapters, generative compression, and a triage dashboard. | User demand or measured limitations in the initial design. |

This sequence differs from the suggested roadmap because it establishes ingestion, source integrity, and evaluation before making autonomous recovery central. It preserves the intended architecture's direction while making each additional mechanism justify itself.

The decisions still open are whether this is primarily a portfolio project or a business, whether Python is the first real adoption path, which corpus will supply representative questions, whether a Python service is acceptable for TypeScript users, and which quality/latency tradeoff that audience needs. None prevents a design discussion, but they materially affect implementation priorities.

For a portfolio, a reproducible retrieval benchmark, an honest failure analysis, and a working MCP demonstration would provide strong engineering evidence. For a business, the same technical work needs design partners who show that current retrieval failures consume enough time to justify adoption. GitHub interest alone would not answer that question.

I would continue with Cragkit, but center the first release on source integrity, estimated question coverage, and bounded execution. Those properties can make the retrieval loop worth trusting. The claim that it autonomously prevents hallucination cannot be supported by this design.

The subsequently supplied HTML architecture explorer has now received a separate execution and source review in [analysis/EXPLORER_REVIEW.md](analysis/EXPLORER_REVIEW.md). Its scripts were exercised in a local DOM model: 14 checks passed and 5 flagged findings. Browser rendering remains unverified because the browser tool rejected the local-file URL. The explorer contains scripted examples rather than a retrieval engine, so it does not establish the quality or performance capabilities discussed above.
