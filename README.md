# Cragkit

Cragkit is a native Python and TypeScript retrieval library in development. The consuming application owns identity, data, providers and final answers. The planned library returns source-linked evidence, coverage estimates, limitations and execution diagnostics.

V0 is complete locally: both internal packages validate request, trusted-scope, evidence and result contracts against shared fixtures. The project includes a human-reviewed synthetic corpus, sealed inputs, native conformance checks and a sequential local acceptance pipeline. V1-01 is complete: lexical schema, explicit migrations and security checks passed locally and on hosted Supabase, including authenticated native SQL with certificate and hostname verification. TLS enforcement and private-schema restrictions are configured. V1-02 completes the internal Python connection lifecycle with optional pools, schema/role checks, parameterized identifier filters, scoped read-only transactions and tested deadlines/cancellation. Actual runtime-login hosted tests and cleanup passed. V1-03 adds the equivalent native Node lifecycle with verified aborts and runtime-role scope checks. V1-04 through V1-07 add shared canonical UTF-8 spans, atomic ingestion in both runtimes and scoped native FTS candidates, with hosted parity, rollback and authorization checks. V1-08 adds verified canonical source excerpts and conservative typed results in both runtimes. V1-09 adds explicit tombstone/purge lifecycle operations with controlled update-ordering and rollback checks. Final source-release races, broader cancellation acceptance and V1 artifacts are still pending. Package version `0.0.0` and the `cragkit` package names are provisional; no registry publication or license decision has been made.

## Run local checks

The verified development setup uses Python 3.14, Node.js 26.5 or later within Node 26, npm and uv. From the project root:

```sh
python3 tools/check_v0.py
```

The runner installs frozen dependencies, checks both native packages and shared contracts, verifies approved development labels and sealed inputs, then builds and checks clean Python/npm artifacts. Dependency setup may access package registries. No database, model download or live provider is required. Temporary installation environments are removed; generated artifacts are written under `artifacts/V0/` and ignored by Git. See [development commands](docs/development.md) and the [local CI profile](docs/ci.md) for verified scope and limitations.

## Project guide

- [Architecture](docs/architecture/ARCHITECTURE.md): governing boundaries and planned retrieval behavior.
- [Master plan](tasks/plan.md) and [task tracker](tasks/todo.md): dependency order, acceptance evidence and current state.
- [Wire contracts](contracts/README.md) and [evidence/result contracts](contracts/RESULTS.md): current validation behavior.
- [Evaluation protocol](evaluation/protocol.md): human review, source spans and held-out handling.
- [Agent instructions](AGENTS.md) and [coordination protocol](docs/agents/WORKFLOW.md): bounded ownership and resource policy.
- [Version control](docs/version-control.md): scoped commits, immediate pushes and synchronization checks.

Earlier proposals, reviews, analysis artifacts and saved papers remain as project history. The consolidated architecture and later user decisions govern where those historical materials disagree.

GitHub repository: [vsuman00/Cragkit](https://github.com/vsuman00/Cragkit), private, with the HTTPS remote configured as `origin`. The initial V0 baseline was committed and pushed to `main` as `feb2bdd`; matching local and remote commits were verified. Hosted CI remains unconfigured; the local pipeline passing does not establish a hosted run.
