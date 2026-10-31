# V6-01: release coverage inventory

This is a static acceptance inventory, not release validation. [The machine-readable inventory](../../release/V6-coverage.json) assigns all ten BRD requirements and all 105 edge cases to existing behavior tests, historical evidence and plan owners. No coverage percentage is inferred. V6 remains blocked while its required gates are pending.

For example, `test_qdrant_source.py` owns source-verification failures, while a native report records a particular database and transport run. Neither establishes current hosted CI success or live embedding quality.

## Audited support boundary

| Area | Declared or previously exercised scope | Evidence and remaining gate |
| --- | --- | --- |
| Python core and optional packages | Python `>=3.14,<3.15`; Pydantic `2.14.1`; core, LangChain and MCP packages version `0.0.0` | Actual package manifests; [prior local installation report](../V5/V5-08.md). Broader Python/platform compatibility is unvalidated. |
| Node core and optional packages | Node `>=26.5.0 <27`; Zod `4.6.7`; all npm packages private, version `0.0.0` | Actual package manifests; [prior local installation report](../V5/V5-08.md). No publication is implied. |
| PostgreSQL | Native lexical FTS, exact dense and hybrid profiles; optional psycopg/pg drivers; local PostgreSQL 17 and dedicated hosted development acceptance are distinct | [V2 hybrid report](../V2/V2-07-08-exit.md), [Neon report](../V2/DB-NEON-01.md). Synthetic vector profiles do not establish live-model quality or arbitrary production deployment. |
| Qdrant | Pinned single-node `1.20.0`, controlled writer/supervisor, authoritative PostgreSQL SourceStore; dense/sparse profile restrictions | [Native publication ledger](../V5/V5-04H-matrix.json), [native report](../V5/V5-04H.md), [backend/transport matrix](../V5/V5-07.md). No clustered deployment, arbitrary writers or automatic supervisor takeover acceptance. |
| Embeddings | Distinct synthetic profile; opt-in OpenAI `text-embedding-3-small`, 1536 dimensions, application-owned transport | [Embedding decision](../../../docs/decisions/0001-embedding-profile.md), [native synthetic integration](../V2/V2-07-08-exit.md). No live OpenAI inference result establishes storage compatibility or quality. |
| Reranking | Fake/recorded contract responses and bounded Cohere `rerank-v5.0-fast` development observations | [Live development report](../V3/V3-02D.md), [calibration report](../V3/V3-07.md). Node replay is not independent inference. Local model shortlist is not a supported installed runtime. |
| Entry points | Direct library, optional LangChain and MCP; existing-index capability-gated example | [Conformance matrix](../V5/V5-07.md), [local artifact profiles](../V5/V5-08.md). Only declared combinations have native evidence; schema agreement does not prove every combination. |
| CI and publication | No `.github` workflow directory in the audited checkout; local artifact probes exist | Hosted supported-platform CI, candidate identity and published-package smoke remain V6-06/V6-08 gates. |

Python optional runtime dependencies are psycopg `3.3.6`, psycopg-pool `3.3.3`, httpx `0.28.1` and tiktoken `0.14.0`. Node optional peers are pg `8.23.1` and tiktoken `1.0.22`. Optional frameworks have separate manifests: Python langchain-core `1.7.0` and MCP `2.3.0`; Node @langchain/core `1.3.0` and @modelcontextprotocol/server `2.4.0`. Installed profile evidence belongs to its exact archive and lock configuration.

## Reading the inventory

`evidence_indexed_not_revalidated` means code/tests and historical reports are located. It is not a pass. Unit files identify behavior owners; explicit edge-ID mentions provide additional targeted report, SQL or harness references. Some tests cover only part of an edge-case sentence, so final acceptance must inspect the actual assertions and command results.

`release_gate_pending` keeps E57 installation, E58 migration, E59 evaluation integrity, E60 sustained load, E61 publication and E65 upgrade compatibility open for their V6 owner. Historical installation and migration checks remain useful evidence without closing new candidate gates. BR-01 through BR-10 retain `release_validation_pending` because the release gates apply to the promised outcome, beyond the existing implementation.

E62 caching, E63 approximate indexing and E64 final-answer evaluation are conditional and currently outside the declared initial scope. They must be reassessed before enabling those features. Final answers remain owned by consuming applications. Zero observed invariant violations in a defined suite is the architecture's acceptance rule; it is not a universal security claim.

## Required remaining evidence

Freeze candidate identity, numeric quality/resource targets and comparison configurations before V6-02. Preserve all compared baselines and complete result denominators; unknown costs and missing evidence cannot become zero. V6-03 must measure resource pressure and bounded overload. V6-04 must inspect current boundaries and exact package contents. V6-05 needs an unfamiliar developer, a declared comparison and actual task observations. V6-06 through V6-09 own supported artifacts, CI, license/notices, rollback, authorized publication and maintenance evidence. A missing participant, license decision or external release capability remains explicit.

The [sealed metadata](../../review/seal.json) records human approval of the initial synthetic labels and discloses that initial authors and reviewers saw held-out content before sealing. This audit read metadata only, without opening `evaluation/questions/held_out.json`. That historic exposure limits an independent unseen-data claim. Development-only inspection and the small corpus cannot establish broad quality. If held-out results inform changes, record contamination and require fresh held-out data for a later unbiased comparison.

## Audit and handoff

The audit inspected manifests, the BRD crosswalk, architecture sections 13-14, active V6 plan, edge inventory, existing unit paths, SQL/harness references and historical report boundaries. Static validation checks every indexed evidence path exists and IDs are complete and unique. No product test, service, install, live-provider call or hosted write ran in this lane. Existing dirty source/audit files were preserved. The final integrator owns candidate tests and tracker updates.

Failure case: a source digest test can pass while a packing change drops the only supporting facet. BR-02 fidelity evidence therefore cannot close BR-04 coverage or BR-07 reassessment gates. Exercise: choose an inventory row requiring native integration and identify the exact target and result report needed beyond its unit test. Learning remains unassessed.
