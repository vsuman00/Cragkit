<div align="center">

# Cragkit

**Native Python & TypeScript retrieval library**

Source-linked evidence · Coverage estimates · Limitations · Execution diagnostics

[![Python](https://img.shields.io/badge/Python-3.14-3776AB?logo=python&logoColor=white)](packages/python)
[![TypeScript](https://img.shields.io/badge/TypeScript-Node_26-3178C6?logo=typescript&logoColor=white)](packages/typescript)
[![Status](https://img.shields.io/badge/Status-V6_In_Progress-yellow)](#current-status)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

</div>

---

Cragkit is a retrieval library with native Python and TypeScript packages. It returns source-linked evidence, coverage estimates, explicit limitations and execution diagnostics. The consuming application owns identity, data, providers and final answers — Cragkit never generates answers on its own.

Coverage remains unknown unless the application configures a suitable assessment policy.

Provider credentials belong to each consuming application. For example, Project
A loads its own OpenAI key from its private `.env`, while Project B uses its own
configuration. The application configures its provider client and injects a
transport into Cragkit's adapter. Cragkit does not load `.env` files or supply a built-in key.
Keep credentials in trusted backend configuration, outside retrieval/tool input.
The separate V6 live benchmark needs a test credential; using the library does
not require our development key or the Codex key-setup plugin.

> [!IMPORTANT]
> Python `1.0.0rc1` and npm `1.0.0-rc.1` identify the published MIT-licensed RC1. All six registry packages and nine files passed exact download and installed-consumer acceptance. Maintenance and C3 passed; formal public-evidence exit remains pending.

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
| **V1** | Native lexical library, source authorization, cancellation, installed-artifact acceptance | ✅ Complete for the declared milestone | [Release scope and limits](docs/releases/V6.md) |
| **V2** | Dense/identifier retrieval, rank fusion, hybrid orchestration, synthetic comparison | ✅ Complete for the declared milestone | [HY-r1 configuration](contracts/HYBRID_V2.md) · [Release limits](docs/releases/V6.md) |
| **V3** | Bounded reranking, exact context accounting, extractive packing, reviewed-span coverage | ✅ Complete for the curated milestone | [Release limits](docs/releases/V6.md) |
| **V4** | Bounded corrective retrieval, privacy-controlled events and optional LangChain Core adapters | ✅ Complete for the internal native/synthetic milestone | [Adapter guide](docs/integrations/langchain.md) |
| **V5** | Qdrant publication and repair, existing indexes and optional MCP | ✅ Complete for the declared local native milestone | [Installation and operations](docs/v5-operations.md) |
| **V6** | Evaluation and release | 🚧 RC1 published and verified; maintenance/C3 passed; formal public-evidence exit pending | [RC1 notes and limitations](docs/releases/V6.md) · [Current roadmap](docs/roadmap.md) |

> [!NOTE]
> V3 calibration is curated in-sample evidence, not general semantic quality. V4 and V5 are complete for their declared internal milestones. V5 acceptance covers single-node native publication/recovery, existing-index contracts, backend/transport conformance and clean local optional artifacts. V6 records limited live-model results and declared-platform CI. Local migration acceptance passed. Reviewed security leads are closed, while qualified CSO coverage remains partial. RC1 registry acceptance passed; public-evidence exit and production acceptance remain separate gates.

Track current work → [roadmap and maintenance state](docs/roadmap.md)

## Quick Start

### Prerequisites

| Tool | Version |
|------|---------|
| Python | 3.14 |
| Node.js | `>=26.5.0, <27` |
| npm | 11.17.0 |
| uv | 0.11.8 |

The corrected hosted candidate used Python 3.14.6, Node 26.5.0, npm 11.17.0
and uv 0.11.8 on macOS 15.8.2 ARM64. This measured tuple does not establish
acceptance for every version in the declared ranges or for other platforms.

Install the reviewed RC1 in your application's environment. Python uses an
active virtual environment; Node uses its own project directory:

```sh
uv pip install 'cragkit==1.0.0rc1'
npm install 'cragkit@1.0.0-rc.1'
```

The optional `cragkit-langchain` and `cragkit-mcp` packages use the matching
version in each registry. Provider credentials belong to the consuming
application; installation needs no built-in Cragkit key.

### Run Local Checks

Use the source-only type and package checks in [development.md](docs/development.md). They build the library without a private corpus, evaluation packet or example application. Full regression and native backend verification remain separate maintainer checks against the private workbench.

📖 [Development commands](docs/development.md) · [Local CI profile](docs/ci.md)

## Evidence Examples

For a question asking for both a retry rule and its delay, a supported retry facet and a missing delay facet produce `partial` coverage. If a strict token budget cannot fit any evidence, the result is `insufficient`; a provider timeout remains an operational failure.

The consuming application binds trusted scope, supplies its backend and tokenizer, and decides how to use those outcomes. See the [result contract](contracts/RESULTS.md) and [operations guide](docs/v5-operations.md). Maintainer demonstration applications and their regression fixtures are retained outside this source checkout.

> [!NOTE]
> Strict counting applies to the declared cl100k renderer and wrapper allowance. Reviewed-span support is a curated estimate; exact source bytes do not establish truth. See [TK-r1](contracts/TOKEN_CONTEXT_V3.md), [PK-r1](contracts/PACKING_V3.md), [AS-r1](contracts/ASSESSMENT_V3.md) and [EP-r1](contracts/EVIDENCE_PIPELINE_V3.md) for the public contract boundaries.

## Project Guide

<details>
<summary><strong>📐 Architecture & Design</strong></summary>

- [Architecture](docs/architecture/ARCHITECTURE.md) — Governing boundaries and planned retrieval behavior
- [Release scope and limits](docs/releases/V6.md) — Supported behavior and limits on quality, platform and usability claims

</details>

<details>
<summary><strong>📋 Planning & Tracking</strong></summary>

- [Roadmap and maintenance state](docs/roadmap.md) — Current scope, pending decisions and handoff
- [Maintenance checklist](docs/maintenance.md) — Reproduction, regressions and policy review
- [Release limitations](docs/releases/V6.md) — Evaluation scope and disclosure boundaries

</details>

<details>
<summary><strong>📦 Contracts</strong></summary>

- [Wire contracts](contracts/README.md) — Current validation behavior
- [Evidence/result contracts](contracts/RESULTS.md) — Result structure and guarantees

</details>

<details>
<summary><strong>🗄️ Infrastructure</strong></summary>

- [PostgreSQL storage](storage/postgres/README.md) — Explicit migrations, role boundaries and schema profiles
- [Secure setup runbook](docs/neon.md) — Security requirements and acceptance gates
- [PostgreSQL embedding profiles](docs/postgres-embedding-profiles.md) — Explicit fake/OpenAI profile selection
- [V5 installation and operations](docs/v5-operations.md) — Optional profiles, connection ownership, explicit migrations, recovery and local shutdown
- [Publishing and deployment guide](docs/releasing.md) — MIT notices, exact artifacts, CI, release permission and application hosting
- [Migration and recovery guide](docs/migrations-and-recovery.md) — Explicit upgrades, quarantined restore and current access state

> Development backend acceptance does not establish production or connection-pooling acceptance.

</details>

<details>
<summary><strong>🤖 Agent & Development Workflow</strong></summary>

- [Agent instructions](AGENTS.md) — Bounded ownership and resource policy
- [Coordination protocol](docs/agents/WORKFLOW.md) — Multi-agent coordination
- [Version control](docs/version-control.md) — Scoped commits, immediate pushes and synchronization checks
- [Contributing](CONTRIBUTING.md) — Focused changes and synthetic bug reports
- [Support scope](docs/support.md) — Supported evidence, safe reporting and triage
- [Maintenance checklist](docs/maintenance.md) — Regressions, dependencies and release follow-through
- [Tooling entry points](docs/tooling.md) — Current command roles and historical-name lookup
- [Development guide](docs/development.md) — Source checks, package builds and private maintainer verification

</details>

> [!NOTE]
> Personal plans, reviews, evaluation records, examples and saved papers are retained in a separate private maintainer archive. This source checkout contains the library and current operational documentation. The architecture and current user decisions govern.

## Repository

GitHub: [vsuman00/Cragkit](https://github.com/vsuman00/Cragkit) (private) · Remote: `origin` (HTTPS)

RC1 registry acceptance passed for all six packages and nine exact files. The [release notes](docs/releases/V6.md) distinguish those recorded results from current source validation. Personal workbench materials have been separated from the library checkout; original history remains private. Repository visibility and formal public evidence disclosure still require separate decisions.
