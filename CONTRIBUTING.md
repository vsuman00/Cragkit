# Contributing to Cragkit

For example, a reranker failure report can use two synthetic passages and a fake transport that raises an exception. That is enough to test error redaction without an API key or private document.

Cragkit is a native Python and TypeScript retrieval library. Contributions should preserve source-linked evidence, trusted access scope, bounded execution and honest coverage estimates. Start with the [architecture](docs/architecture/ARCHITECTURE.md), [active plan](tasks/plan.md) and [tracker](tasks/todo.md). Repository agents also follow [AGENTS.md](AGENTS.md).

The repository currently remains private. These instructions and the [bug report form](.github/ISSUE_TEMPLATE/bug_report.yml) help collaborators who have access; they do not establish public issue access or a confidential security channel. See [support scope](docs/support.md) before sharing a report. No response-time commitment is offered.

Complete all requested reproduction fields and the redaction check before submitting. GitHub documents required-field enforcement for public repositories only, so maintainers must review completeness and redaction here. See [GitHub's form schema](https://docs.github.com/en/communities/using-templates-to-encourage-useful-issues-and-pull-requests/syntax-for-githubs-form-schema).

## Reproduce a bug safely

Reduce the problem to one synthetic document, request and scope. Record the package version or source commit, install method, OS and architecture, Python or Node version, package manager, backend and enabled extras or adapters. State whether the provider is fake, recorded, local or live. Separate expected behavior from actual evidence, coverage and execution status; include a safe error code when available.

Share exact reproduction commands and short redacted logs. Never include API keys, tokens, database connection strings, passwords, raw private queries or documents. Replace sensitive input with synthetic text before attaching anything. A report that requires live access should first describe the missing reproduction step; routine contribution work does not need paid calls or built-in project API keys.

The measured local toolchain is macOS 15.8.2 ARM64, Python 3.14.6, Node 26.5.0, npm 11.17.0 and uv 0.11.8. Manifest engine ranges describe installation constraints; they do not prove every OS, patch version or optional profile has passed. Report other environments explicitly and consult the [release compatibility evidence](docs/releases/V6.md).

## Set up and check a small change

Use a checkout you can modify without overwriting someone else's work. Inspect existing changes first. From the repository root, install locked development dependencies:

```sh
uv sync --project packages/python --frozen
```

Then, from `packages/typescript`:

```sh
npm ci --ignore-scripts
```

Installation may download dependencies. It does not authorize model downloads, database setup, hosted CI or publishing. Core imports must remain free of network access, database connections and migration side effects. PostgreSQL, Qdrant, tokenizers, LangChain and MCP have separate optional profiles; install and test only the profiles needed for your change using [development.md](docs/development.md).

Begin with the affected deterministic test. This existing regression exercises a fake transport and safe error handling, from the repository root:

```sh
uv run --project packages/python --frozen --no-sync pytest packages/python/tests/test_reranking.py::test_unknown_transport_error_is_redacted_and_fatal -q
```

For a core change, run the relevant Python checks from the root:

```sh
uv run --project packages/python --frozen --no-sync pytest packages/python/tests -q
uv run --project packages/python --frozen --no-sync mypy --config-file packages/python/pyproject.toml packages/python/src
```

Run the TypeScript checks separately, from `packages/typescript`:

```sh
npm run typecheck
npm test
```

`npm test` builds before its serial test run. Start with one test process and small fake-provider fixtures. Native database integration, optional adapters and installed-artifact checks need their documented prerequisites and separate evidence; a unit pass cannot replace them. Stop resource-heavy work if memory pressure or responsiveness deteriorates.

## Submit a focused change

Agree on scope against the active plan before adding a subsystem or changing public behavior. Add a regression that fails for the original bug, implement the smallest correction and check the corresponding behavior in both runtimes. Keep shared fixtures, source spans, required filters, cancellation, usage accounting and failure semantics consistent. `partial` coverage and `degraded` execution remain separate concepts; failures must not become missing-evidence success.

Describe the trigger, resulting behavior, test commands actually run and their results. Mark unrun integration, live-provider or platform checks explicitly. Include limitations and any compatibility or migration effect. Preserve unrelated changes and keep dependency changes with their manifests, locks and license review. The project uses the [MIT license](LICENSE); this guide adds no separate contributor agreement.

## Maintain and release the fix

Follow the [maintenance workflow](docs/maintenance.md) for triage, dependency changes and model-policy re-evaluation. Changes to a provider/model, tokenizer, pricing, corpus, coverage policy or disclosure behavior need the affected evidence reviewed; fake tests alone establish no model-quality improvement.

Published RC1 bytes are immutable. A fix to published behavior requires a separately reviewed and authorized corrective version, exact artifact verification and release communication. Do not replace RC1 archives, broaden permissions, or infer permission to publish a stable release. The [release guide](docs/releasing.md) and [publication procedure](docs/publication.md) define those gates. Report the affected version, workaround, correction and remaining limitations through the agreed repository channel; do not claim a fix shipped before registry acceptance.

To practice, trace the fake reranker report through its regression, patch review, corrective release decision and user-facing explanation. The [maintenance walkthrough](docs/maintenance.md) gives the sequence.
