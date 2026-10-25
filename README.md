# Cragkit

Cragkit is a native Python and TypeScript retrieval library in development. The consuming application owns identity, data, providers and final answers. The library returns source-linked evidence, limitations and execution diagnostics; coverage remains unknown unless the application configures a suitable assessment policy.

V0 is complete locally and V1 is complete for the scoped native lexical library milestone, including final source authorization, cancellation and installed-artifact acceptance. See the [V1 evidence and limitations](evaluation/reports/V1/V1-10-12.md) and [current tracker](tasks/todo.md). V2 is complete for native dense/identifier retrieval, rank fusion, public hybrid orchestration and the declared synthetic development comparison. See [V2 exit evidence](evaluation/reports/V2/V2-07-08-exit.md) and [HY-r1 configuration](contracts/HYBRID_V2.md). V3 adds optional bounded reranking, exact context accounting, extractive packing and conservative reviewed-span coverage with one configured rebalance. Its frozen small development comparison is recorded in [V3 calibration](evaluation/reports/V3/V3-07.md); this is curated in-sample evidence, not general semantic quality. The [V3 exit checkpoint](evaluation/reports/V3/V3-08-exit.md) passed local, installed and native acceptance. Corrective retrieval remains V4 work; production acceptance is unvalidated. Package version `0.0.0` and the `cragkit` package names are provisional; registry publication, license selection and hosted CI evidence remain separate.

## Run local checks

The verified development setup uses Python 3.14, Node.js 26.5 or later within Node 26, npm and uv. From the project root:

```sh
python3 tools/check_v0.py
```

The runner installs frozen dependencies, checks both native packages and shared contracts, verifies approved development labels and sealed inputs, then builds and checks clean Python/npm artifacts. Dependency setup may access package registries. No database, model download or live provider is required. Temporary installation environments are removed; generated artifacts are written under `artifacts/V0/` and ignored by Git. See [development commands](docs/development.md) and the [local CI profile](docs/ci.md) for verified scope and limitations.

## Project guide

- [Neon migration plan](docs/neon-migration-plan.md) and [secure setup runbook](docs/neon.md): selected development PostgreSQL host, security requirements and acceptance gates. Historical Supabase results do not establish Neon acceptance; see the tracker before hosted use.
- [Business requirements](docs/product/BRD.md): developer problem, intended users, product requirements, success measures and unvalidated assumptions.
- [Architecture](docs/architecture/ARCHITECTURE.md): governing boundaries and planned retrieval behavior.
- [Master plan](tasks/plan.md) and [task tracker](tasks/todo.md): dependency order, acceptance evidence and current state.
- [Wire contracts](contracts/README.md) and [evidence/result contracts](contracts/RESULTS.md): current validation behavior.
- [Evaluation protocol](evaluation/protocol.md): human review, source spans and held-out handling.
- [Agent instructions](AGENTS.md) and [coordination protocol](docs/agents/WORKFLOW.md): bounded ownership and resource policy.
- [Version control](docs/version-control.md): scoped commits, immediate pushes and synchronization checks.

Earlier proposals, reviews, analysis artifacts and saved papers remain as project history. The consolidated architecture and later user decisions govern where those historical materials disagree.

GitHub repository: [vsuman00/Cragkit](https://github.com/vsuman00/Cragkit), private, with the HTTPS remote configured as `origin`. The initial V0 baseline was committed and pushed to `main` as `feb2bdd`; matching local and remote commits were verified. Hosted CI remains unconfigured; the local pipeline passing does not establish a hosted run.

## Evidence examples

The [Python example](examples/evidence.py) and [Node example](examples/evidence.mjs) demonstrate a supported retry facet with a missing delay facet, then a strict one-token budget that emits only `[]`. They use public synthetic source text and a caller-supplied local tokenizer asset; no model is installed or contacted. The [installed-package verifier](docs/development.md#v3-installed-evidence-release-checkpoint) copies these examples into fresh package environments and compares their complete outputs.

Strict counting applies to the declared cl100k renderer and wrapper allowance. Reviewed-span support is a curated estimate; exact source bytes do not establish truth. [TK-r1](contracts/TOKEN_CONTEXT_V3.md), [PK-r1](contracts/PACKING_V3.md), [AS-r1](contracts/ASSESSMENT_V3.md) and [EP-r1](contracts/EVIDENCE_PIPELINE_V3.md) define the public boundaries.
