# Cragkit business requirements

Version 1 | 22 October 2026 | Status: documented product intent; market and outcome assumptions remain unvalidated.

## 1. Purpose and authority

This BRD connects the developer problem to the value Cragkit intends to deliver, its requirements and the evidence needed to judge success. It consolidates existing decisions; it does not add implementation scope or certify release readiness.

The [architecture](../architecture/ARCHITECTURE.md) governs technical boundaries. The [master plan](../../tasks/plan.md) and version plans govern sequencing, and the [tracker](../../tasks/todo.md) owns implementation and verification status. Requirements below are targets across those milestones, not a claim that all capabilities are available today. Later user decisions control scope; conflicts must be resolved before dependent implementation.

## 2. Problem and intended value

Developers building document-backed applications repeatedly assemble ingestion, storage access, retrieval, ranking, context limits, source references, retries and diagnostics. Even after that work, a successful search can return evidence that is irrelevant, incomplete or unsuitable for the original question. Applications need to distinguish missing evidence from operational failure before deciding what to do next.

For example, an incident question may ask for both the cause and the recovery procedure. Finding a recovery runbook does not establish the cause of that incident. Cragkit should preserve the useful excerpt while exposing missing or unknown support instead of presenting the search as fully sufficient.

Cragkit is an installable native Python and TypeScript retrieval library. Its intended value is less repeated integration and maintenance work through a small typed API, source-linked evidence, coverage estimates, explicit limitations and bounded execution. The application retains identity, data, provider choices, final answers and actions.

Reduced effort and improved retrieval quality are product hypotheses to measure. Neither a fixed reduction from 200 lines to 5 nor elimination of hallucinations is a business promise. Exact source text can still be irrelevant, outdated or wrong, and a consuming LLM can misuse it.

## 3. Users and stakeholders

| Group | Need and responsibility | Validation status |
| --- | --- | --- |
| Python and TypeScript developers building document-backed applications or agents | Integrate retrieval, inspect evidence and handle incomplete results without rebuilding every supporting component. | Intended primary users; demand and adoption are unvalidated. |
| Application maintainers and operators | Diagnose failures, control disclosure and resource use, and keep retrieval working through updates. | Intended stakeholders; maintenance savings are unvalidated. |
| Application and data owners | Resolve trusted identity, define access policy, choose providers and operate their data infrastructure. | Ownership boundary established by the architecture. |
| Project builder and maintainer | Learn the underlying engineering, keep changes understandable and sustain the two native implementations. | Established project objective; learning must be demonstrated separately from passing tests. |

The first evaluation domain is engineering documentation: Markdown, plain text, runbooks, ADRs and postmortems. This is an evaluation focus, not evidence of demand in a particular industry. Broader domain quality requires separate evidence. End users receive answers through consuming applications; a Cragkit end-user interface is not part of this baseline.

## 4. Scope and constraints

The existing delivery sequence remains unchanged:

- V0 establishes contracts, fixtures and development foundations.
- V1 provides the native source-linked lexical library.
- V2 adds embedding profiles and hybrid retrieval.
- V3 adds reranking, coverage estimates and exact context packing.
- V4 adds bounded correction, diagnostics and first framework adapters.
- V5 adds Qdrant, existing-index integration and optional MCP.
- V6 establishes evaluated release, distribution and maintenance evidence.

These are build milestones, not promised delivery dates or public release versions. Follow their dependency and acceptance gates in the [master plan](../../tasks/plan.md#3-versions-and-phase-mapping).

Python and TypeScript execute natively; the npm library does not require a Python server. Python/Pydantic/asyncio and TypeScript/Zod remain the baseline. PostgreSQL with pgvector and native FTS is the first backend; FTS is not BM25. Neon is the current development database choice, following the user decision on 22 October 2026; it is not a mandatory service for library consumers. The [Neon runbook](../neon.md) and [DB-NEON-01 evidence](../../evaluation/reports/V2/DB-NEON-01.md) record direct-endpoint development and native lexical acceptance. Vector storage and pgvector installation remain part of [V2-04](../../tasks/versions/V2-hybrid-search.md#v2-04-vector-generations-and-reindex). Pooling and production acceptance, and any Supabase retirement, are separate work and do not block the next development slice.

Keep database drivers, model runtimes, frameworks and transports optional. Core import must not initiate network calls, connect to a database, apply migrations or download models. Request-local budgets do not establish a global quota across application instances; that infrastructure remains application-owned. Development follows the existing M4/16 GB resource policy: small fixtures, fake providers for routine tests and one integration suite at a time. This is not a universal hardware guarantee.

Outside this baseline are a hosted product/dashboard, application authentication, final-answer generation or verification, arbitrary agent actions, enterprise crawling, OCR/multimodal ingestion and dependent multi-hop research. Rust replacement and commercial hosting require separate decisions. Optional integrations already assigned to later versions remain in their planned phases.

## 5. Business requirements and traceability

"Required" below describes the agreed product target within the named milestone. Completion evidence remains in the tracker. Edge-case IDs refer to the existing [validation inventory](../../tasks/EDGE_CASES.md); these references highlight relevant cases rather than replace the full inventory.

| ID | Required outcome and reason | Existing delivery and acceptance path |
| --- | --- | --- |
| BR-01 | Developers can use small typed native Python and TypeScript APIs with consistent documented semantics and useful errors. This is intended to reduce repeated integration decisions. | V0-V1 contracts and native artifacts; shared fixtures and installation checks; V6 developer trial. |
| BR-02 | Returned excerpts identify immutable source revisions and exact canonical spans, with integrity checks. Developers can inspect where evidence came from. | V1 source assembly and lifecycle; V3 packing; E07-E16. |
| BR-03 | Evidence release respects caller-bound trusted scope and required filters throughout retrieval, recovery and final authorization. A useful result cannot justify broader access. | V1 authorization, V2 branches, V4 recovery, V5 adapters; E17-E25, E44, E53-E55. |
| BR-04 | Results distinguish sufficient, partial and insufficient evidence estimates from complete or degraded execution. Unknown support cannot be declared sufficient; operational errors cannot become "no evidence." | V0/V1 contracts, V3 assessment and post-packing checks, V4 orchestration; E29, E35-E38, E47. |
| BR-05 | Hybrid retrieval, reranking and bounded correction are evaluated against simpler baselines. Added work must justify its quality and cost. | V2-V4 evaluations and V6 held-out comparison; E26-E33, E44-E45. |
| BR-06 | Requests obey shared deadlines, cancellation and declared candidate, call and attempt limits; usage accounting reports unknowns honestly. Applications can bound work and handle failures. | V1 lifecycle, V4 shared budgets and recovery; E23-E24, E46-E50. |
| BR-07 | Evidence packing respects the declared representation and tokenizer for hard token ceilings, then reassesses support using only emitted evidence. | V3 packing and V4 wrappers; E38-E42. |
| BR-08 | Ingestion, updates and deletion preserve consistent published revisions. Unsupported input and incompatible profiles fail explicitly rather than creating misleading searchable content. | V1 lifecycle, V2 profiles, V5 publication/repair; E08-E16, E25, E30, E52-E54. |
| BR-09 | Diagnostics explain retrieval limitations and failures while keeping credentials and raw query/source text out of default telemetry. Applications explicitly choose allowed providers and disclosure policies before query or source text is sent externally. Retrieved content remains data, not authority to change policy. | V2/V3 provider selection, V4 events/planner boundaries, V5 source authorization and V6 security evaluation; E34, E50-E51, E53. |
| BR-10 | Consumers can adopt optional integrations without mandatory heavy services or dependencies, with documented compatibility and migration limitations. | V0 import isolation, V5 integrations, V6 packaging and release checks. |

### Requirement crosswalk

This maps existing requirements to design sections and task owners, not completion state. Task definitions are linked from the [master plan](../../tasks/plan.md#3-versions-and-phase-mapping); acceptance evidence stays in the tracker.

| Requirement | Architecture sections | Existing task owners |
| --- | --- | --- |
| BR-01 | 4-5, 12-13 | V0-02 through V0-05; V1-12; V6-05, V6-06 |
| BR-02 | 6, 9-10 | V1-04, V1-08, V1-09; V3-04 |
| BR-03 | 5, 7-8, 11 | V1-07, V1-10; V2-05, V2-07; V4-02, V4-03; V5-03, V5-06 |
| BR-04 | 5, 8-9, 11 | V0-05; V1-08; V2-07; V3-05 through V3-07; V4-04 |
| BR-05 | 8, 13 | V2-08; V3-07; V4-08; V6-02 |
| BR-06 | 5, 7-8, 11 | V1-02, V1-03, V1-11; V4-01, V4-04; V6-03 |
| BR-07 | 10 | V3-03, V3-04, V3-06; V4-06, V4-07 |
| BR-08 | 6-7 | V1-04 through V1-06, V1-09; V2-02 through V2-04; V5-01, V5-04, V5-05 |
| BR-09 | 7, 11 | V2-01; V3-01, V3-05; V4-02, V4-05; V5-03; V6-04 |
| BR-10 | 3-4, 12-14 | V0-02, V0-03; V5-05 through V5-08; V6-06 through V6-09 |

## 6. Success measures and evidence

Business success means developers can integrate and maintain useful retrieval with less effort, while preserving the required access, evidence and resource behavior. Engineering checks support that judgment but do not establish adoption or market fit.

| Measure | How to evaluate | Decision rule and limitation |
| --- | --- | --- |
| Integration effort | Independent developer tasks on the same corpus and acceptance criteria: compare an explicit retrieval baseline with Cragkit. Record time to first correct authorized retrieval, setup errors and assistance required. | Seek lower effort without dropping required behavior. Define the comparison and target before the trial; no percentage saving is established. |
| Debugging and maintenance | Ask developers to diagnose missing evidence versus a provider failure, interpret a partial result and perform a bounded update/configuration task. Record correct outcomes, time and help needed. | Agree task success criteria in advance. Report failed attempts as well as completed ones; targets await baseline observations. |
| Retrieval quality | Use reviewed relevant-passage and facet labels; compare lexical, dense, hybrid, reranked and corrective configurations with fixed inputs and budgets. | Freeze metric definitions and thresholds before held-out evaluation under V6-01. Report sample size and uncertainty; more stages are not inherently better. |
| Coverage reliability | Measure false-sufficient rate, abstention precision/recall, conflict detection and supported facets after packing. | Calibrate on development data only; disclose denominators and false-sufficient cases. Coverage remains an estimate. |
| Access and source fidelity | Exercise negative authorization, revision, digest and exact-span cases under the defined runtime roles and backend profiles. | Zero observed invariant violations in the specified acceptance suite; this does not prove universal security or source truth. |
| Resource and operational behavior | Record p50/p95 latency, peak process memory, package/dependency size, database work, provider calls/tokens/cost and cancellation behavior. | Set release budgets from measured baselines. Disclose corpus, hardware, concurrency, warm/cold state and hosted network effects; missing usage is unknown. |
| Adoption and ongoing usefulness | In the planned developer trial, record whether participants complete a real integration and their reasons for continuing or abandoning it. | Exploratory evidence, not an adoption target or market-size estimate. Do not infer demand from package downloads alone. |

V6-01 owns the predeclared measures and criteria; V6-02 owns retrieval/coverage evaluation, V6-03 resource measurements, V6-04 the security audit, and V6-05 the developer comparison and exploratory adoption feedback. If an independent participant or comparable baseline is unavailable, record the missing evidence rather than claim reduced effort. These measurements refine existing tasks and do not create a separate market-research program.

Use the existing [evaluation protocol](../../evaluation/protocol.md) and [architecture validation requirements](../architecture/ARCHITECTURE.md#13-validation-and-release-evidence). Preserve held-out separation and human review. Deterministic fake-provider tests establish contract behavior; live model quality needs separate evaluation. Any downstream answer demonstration must measure unsupported claims and citation support separately.

## 7. Assumptions, risks and unresolved decisions

| ID | Assumption or open question | Validation or response within existing scope |
| --- | --- | --- |
| A-01 | Developers experience enough recurring retrieval work to adopt another library. Unvalidated. | V6 developer trials; record current workflows and reasons to adopt or reject. |
| A-02 | A small API reduces total integration and maintenance effort rather than moving complexity into configuration. Unvalidated. | Measure setup, debugging and update tasks, including failures and required help. |
| A-03 | Hybrid retrieval and correction improve evidence enough to justify latency and provider cost. Corpus/model dependent and unvalidated as a broad claim. | V2-V4 baselines and ablations; V6 held-out evaluation. |
| A-04 | Maintaining two native runtimes is sustainable for this project. A risk, not a reason to change architecture implicitly. | Track parity failures and maintenance effort at existing checkpoints; escalate a material scope change to the user. |
| A-05 | The chosen small-machine workflow remains practical as the corpus and models grow. Workload dependent. | Follow measured resource policy, bound batches/concurrency and keep local models optional. |
| A-06 | Developers can interpret coverage and limitations correctly, and applications will handle them appropriately. Unvalidated. | Developer interpretation tasks and explicit documentation; parent-model compliance is outside the library guarantee. |
| A-07 | Package names, license, supported release matrix and numeric quality/resource targets are suitable for distribution. Unresolved where not recorded by their owning decisions. | Resolve through existing compatibility and V6 release tasks before publication; this BRD chooses none of them. |

Pricing, revenue forecasts, market size and a commercial operating model are not established requirements. No business case here depends on invented customers, willingness to pay or competitor superiority. If evaluation does not support a value hypothesis, record that result and revise priorities through the existing plans rather than claim success from passing unit tests.

## 8. Learning and acceptance

Learning is a separate project objective: explain contracts, source spans, database isolation, asynchronous cancellation, ranking and evaluation through small verified changes. Follow the [learning guide](../../tasks/LEARNING.md); record demonstrated or practiced understanding separately from implementation completion. A useful exercise is to explain why a genuine runbook excerpt can still leave an incident question only partially supported.

This BRD is accepted as documentation when it traces to the existing architecture/plans, marks unvalidated assumptions, defines how outcomes will be measured and passes link and consistency checks. Product acceptance still requires the version criteria and release evidence. Writing the BRD does not complete those tasks or authorize publication.

Maintain this document when a user-approved product decision changes users, scope or value measures. Keep detailed schema, algorithms and test cases in their existing documents, and keep progress in the tracker.
