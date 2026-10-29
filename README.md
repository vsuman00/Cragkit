<div align="center">

# Cragkit

**Native Python & TypeScript retrieval library**

Source-linked evidence · Coverage estimates · Limitations · Execution diagnostics

[![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](packages/python)
[![TypeScript](https://img.shields.io/badge/TypeScript-Node_26-3178C6?logo=typescript&logoColor=white)](packages/typescript)
[![Status](https://img.shields.io/badge/Status-V5_In_Progress-yellow)](#current-status)
[![License](https://img.shields.io/badge/License-TBD-lightgrey)](#)

</div>

---

Cragkit is a retrieval library with native Python and TypeScript packages. It returns source-linked evidence, coverage estimates, explicit limitations and execution diagnostics. The consuming application owns identity, data, providers and final answers — Cragkit never generates answers on its own.

Coverage remains unknown unless the application configures a suitable assessment policy.

> [!IMPORTANT]
> Package version `0.0.0` and the `cragkit` package names are provisional. Registry publication, license selection and hosted CI evidence remain separate.

## What Cragkit Does

| Your application owns | Cragkit handles |
|---|---|
| Authentication & trusted identity | Source-linked evidence retrieval |
| Data, crawling & enterprise connectors | Hybrid search (lexical + dense + fusion) |
| Final-answer generation & actions | Bounded reranking & corrective retrieval |
| Hosting, credentials & provider accounts | Extractive packing within token budgets |
| Truth & completeness of source documents | Coverage estimates & explicit limitations |
| | Typed results, cancellation & diagnostics |

The **npm** package runs natively in Node.js — no Python server required. The **Python** package runs in its own Python application. Optional MCP is a separate process wrapper around a library instance.

## Current Status

| Version | Scope | Status | Evidence |
|---------|-------|--------|----------|
| **V0** | Baseline | ✅ Complete | — |
| **V1** | Native lexical library, source authorization, cancellation, installed-artifact acceptance | ✅ Complete | [V1 evidence & limitations](evaluation/reports/V1/V1-10-12.md) |
| **V2** | Dense/identifier retrieval, rank fusion, hybrid orchestration, synthetic comparison | ✅ Complete | [V2 exit evidence](evaluation/reports/V2/V2-07-08-exit.md) · [HY-r1 config](contracts/HYBRID_V2.md) |
| **V3** | Bounded reranking, exact context accounting, extractive packing, reviewed-span coverage | ✅ Complete | [V3 calibration](evaluation/reports/V3/V3-07.md) · [V3 exit](evaluation/reports/V3/V3-08-exit.md) |
| **V4** | Bounded corrective retrieval, privacy-controlled events and optional LangChain Core adapters | ✅ Complete for the internal native/synthetic milestone | [V4 exit evidence](evaluation/reports/V4/V4-08-exit.md) |
| **V5** | Qdrant publication and repair, existing indexes and optional MCP | 🚧 In progress | [V5 plan](tasks/versions/V5-integrations.md) · [Latest accepted settlement checkpoint](evaluation/reports/V5/V5-04G2b2d4.md) |
| **V6** | Evaluation and release | 🔲 Planned | [V6 plan](tasks/versions/V6-release.md) |

> [!NOTE]
> V3 calibration is curated in-sample evidence, not general semantic quality. The V3 exit checkpoint passed local, installed and native acceptance. V4 is complete for its internal native/synthetic milestone. V5 source authorization, profile-4 source/writer/recovery admission, private guarded graph validation and retired security settlement are verified for their recorded native profiles; current-payload recovery and the remaining V5 gates are still in progress. Production acceptance is unvalidated.

Track progress → [task tracker](tasks/todo.md) · [master plan](tasks/plan.md)

## Quick Start

### Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.14 |
| Node.js | `>=26.5.0, <27` |
| npm | latest |
| uv | latest |

### Run Local Checks

```sh
python3 tools/check_v0.py
```

This runner:
1. Installs frozen dependencies
2. Checks both native packages and shared contracts
3. Verifies approved development labels and sealed inputs
4. Builds and checks clean Python/npm artifacts

No database, model download or live provider is required. Temporary install environments are cleaned up; generated artifacts go to `artifacts/V0/` (git-ignored). This is the baseline check; use the development guide for current-version focused tests and optional native acceptance runs.

📖 [Development commands](docs/development.md) · [Local CI profile](docs/ci.md)

## Evidence Examples

The [Python example](examples/evidence.py) and [Node example](examples/evidence.mjs) demonstrate:

1. A supported **retry** facet with a missing **delay** facet → `partial` status
2. A strict **one-token budget** → emits only `[]` with `insufficient` status

Both use public synthetic source text and a caller-supplied local tokenizer asset — no model is installed or contacted. The [installed-package verifier](docs/development.md#v3-installed-evidence-release-checkpoint) copies these examples into fresh package environments and compares their complete outputs.

> [!NOTE]
> Strict counting applies to the declared cl100k renderer and wrapper allowance. Reviewed-span support is a curated estimate; exact source bytes do not establish truth. See [TK-r1](contracts/TOKEN_CONTEXT_V3.md), [PK-r1](contracts/PACKING_V3.md), [AS-r1](contracts/ASSESSMENT_V3.md) and [EP-r1](contracts/EVIDENCE_PIPELINE_V3.md) for the public contract boundaries.

## Project Guide

<details>
<summary><strong>📐 Architecture & Design</strong></summary>

- [Architecture](docs/architecture/ARCHITECTURE.md) — Governing boundaries and planned retrieval behavior
- [Business requirements](docs/product/BRD.md) — Developer problem, intended users, product requirements, success measures and unvalidated assumptions

</details>

<details>
<summary><strong>📋 Planning & Tracking</strong></summary>

- [Master plan](tasks/plan.md) — Dependency order, acceptance evidence and current state
- [Task tracker](tasks/todo.md) — Current progress and status
- [Evaluation protocol](evaluation/protocol.md) — Human review, source spans and held-out handling

</details>

<details>
<summary><strong>📦 Contracts</strong></summary>

- [Wire contracts](contracts/README.md) — Current validation behavior
- [Evidence/result contracts](contracts/RESULTS.md) — Result structure and guarantees

</details>

<details>
<summary><strong>🗄️ Infrastructure</strong></summary>

- [Neon migration plan](docs/neon-migration-plan.md) — Selected development PostgreSQL host
- [Secure setup runbook](docs/neon.md) — Security requirements and acceptance gates
- [Direct Neon acceptance](evaluation/reports/V2/DB-NEON-01.md) — Verified development transport and native checks, with production and pooling limits

> Historical Supabase results do not establish Neon acceptance; see the tracker before hosted use.

</details>

<details>
<summary><strong>🤖 Agent & Development Workflow</strong></summary>

- [Agent instructions](AGENTS.md) — Bounded ownership and resource policy
- [Coordination protocol](docs/agents/WORKFLOW.md) — Multi-agent coordination
- [Version control](docs/version-control.md) — Scoped commits, immediate pushes and synchronization checks

</details>

> [!NOTE]
> Earlier proposals, reviews, analysis artifacts and saved papers remain as project history. The consolidated architecture and later user decisions govern where those historical materials disagree.

## Repository

GitHub: [vsuman00/Cragkit](https://github.com/vsuman00/Cragkit) (private) · Remote: `origin` (HTTPS)

The initial V0 baseline was committed and pushed to `main` as [`feb2bdd`](https://github.com/vsuman00/Cragkit/commit/feb2bdd). Current milestone evidence and Git handoffs are recorded in the [task tracker](tasks/todo.md). No hosted CI run is claimed here; local pipeline results do not establish a hosted run.
