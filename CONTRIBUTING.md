# Contributing to Cragkit

A useful first contribution is a small reproduction: two synthetic passages and a fake reranker that raises an error. It lets a reviewer check failure handling without a provider account or private documents.

Cragkit welcomes focused bug fixes, documentation improvements and proposals that fit its native Python and TypeScript retrieval library. Read the [current roadmap](docs/roadmap.md), the relevant [public contract](contracts/README.md) and [architecture](docs/architecture/ARCHITECTURE.md) before changing behavior. Repository agents also follow [AGENTS.md](AGENTS.md).

The repository currently requires access. Forking, issues and pull requests are available only where your repository permissions allow them; this guide does not change repository visibility. There is no response-time commitment. Contributions use the project's [MIT license](LICENSE); this guide adds no separate contributor agreement.

## Choose and discuss the change

Search existing issues and pull requests first. Use the [bug report](.github/ISSUE_TEMPLATE/bug_report.yml) for a reproducible failure or the [feature request](.github/ISSUE_TEMPLATE/feature_request.yml) to explain a missing capability. A small documentation correction can go directly to a pull request. Discuss new subsystems, public API changes, dependencies, database migrations and changes to data disclosure before investing in an implementation.

| Stage | Contributor | Maintainer or reviewer |
| --- | --- | --- |
| Report or proposal | Describe the problem, affected version, synthetic example and expected outcome. | Triage scope, affected contract, reproducibility and whether the proposal fits the roadmap. |
| Implementation | Make one focused change and provide reproducible verification. Open a draft PR if a decision remains unresolved. | Resolve contract and compatibility questions before dependent work. |
| Review | Answer questions, update the change and report checks after revisions. | Review correctness, failure paths, cross-runtime parity, security and documentation; run applicable maintainer checks. |
| Merge | Keep the PR current and leave unrelated work out. | Decide whether the evidence and scope are acceptable, honor repository protections and merge when ready. |
| Release | State whether published users need a fix or migration. | Make a separate version and release decision; merging a PR does not publish a package. |

For a suspected authorization bypass, credential exposure or other security issue, do not post exploit details or real payloads in an issue or PR. Follow [support scope](docs/support.md): request a private exchange through an existing trusted maintainer contact. No configured confidential inbox or GitHub private-reporting feature is assumed.

## Get a working checkout

Install Git, Python `>=3.14,<3.15`, Node.js `>=26.5.0 <27`, uv and npm. The recorded RC1 tool tuple is Python 3.14.6, Node 26.5.0, npm 11.17.0 and uv 0.11.8. Manifest ranges are installation constraints; tested platform and profile limits are in the [release notes](docs/releases/V6.md).

If forking is available, fork `vsuman00/Cragkit` in GitHub, replace `YOUR-USERNAME` below, then run:

```sh
git clone https://github.com/YOUR-USERNAME/Cragkit.git
cd Cragkit
git remote add upstream https://github.com/vsuman00/Cragkit.git
git switch -c fix/describe-the-change
git status --short
```

Collaborators using a branch in the upstream repository can instead clone `https://github.com/vsuman00/Cragkit.git` and create the same feature branch, without adding a second remote. When reusing a checkout, inspect its changes before switching branches. Preserve unrelated work.

All commands below say which working directory they use. Run one check process at a time. Frozen installs may download locked dependencies; they do not start a database, call a model, apply migrations or authorize publishing.

### Python core

From the repository root:

```sh
uv sync --project packages/python --frozen
uv run --project packages/python --frozen --no-sync mypy --config-file packages/python/pyproject.toml packages/python/src
uv build packages/python --out-dir artifacts/contribution-python
```

The first command creates the package's development environment from `uv.lock`. The last builds the wheel and source distribution in an ignored output directory.

### TypeScript core

From `packages/typescript`, run each command in order:

```sh
npm ci --ignore-scripts
npm run typecheck
npm run build
```

The build emits `dist` for Node.js and for local adapter development. The npm package runs natively in Node.js; no Python server is needed.

### Optional packages and profiles

Install only what your change needs. The core development environments include their declared development dependencies; this does not require starting those dependencies' services.

For Python core extras, run the needed command from the repository root:

```sh
uv sync --project packages/python --frozen --extra postgres
uv sync --project packages/python --frozen --extra qdrant
uv sync --project packages/python --frozen --extra tokenizers
```

These are separate choices, not a requirement to install every extra. Inspect `packages/python/pyproject.toml` for the current declarations. Backend setup and any integration acceptance remain separate from dependency installation.

For a Python LangChain or MCP change, use its own frozen environment. From the repository root, choose the affected package:

```sh
uv sync --project packages/langchain-python --frozen
uv run --project packages/langchain-python --frozen --no-sync mypy --config-file packages/langchain-python/pyproject.toml packages/langchain-python/src
```

```sh
uv sync --project packages/mcp-python --frozen
uv run --project packages/mcp-python --frozen --no-sync mypy --config-file packages/mcp-python/pyproject.toml packages/mcp-python/src
```

Their uv configuration uses the local Python core. Build an affected adapter with `uv build packages/langchain-python --out-dir artifacts/contribution-langchain-python` or `uv build packages/mcp-python --out-dir artifacts/contribution-mcp-python` from the repository root.

For a TypeScript adapter change, first install and build `packages/typescript` as above. Then run `npm ci --ignore-scripts`, `npm run typecheck` and `npm run build` from the affected `packages/langchain-typescript` or `packages/mcp-typescript` directory. Each has its own manifest and lock. TypeScript PostgreSQL and tokenizer dependencies are optional peers for consumers, declared alongside the core's development dependencies; Qdrant uses the native HTTP boundary. Consult the [API reference](docs/api-reference.md) and affected contract before configuring a backend or model.

## Make a focused, verifiable change

Keep each PR centered on one problem. Use existing APIs and naming patterns. Avoid unrelated formatting, generated output, dependency updates or changes to release versions.

For a behavior change, provide a small runnable synthetic reproduction with exact commands and expected output. Show that it fails before the change and succeeds after it, and include a failure or denied-access case. If only one runtime needs a code change, explain why the other runtime already meets the contract. Do not copy the private maintainer corpus or historical test suites into the public checkout.

Preserve these boundaries during implementation:

- Bind trusted access scope outside agent-editable input. Keep required filters in every search branch and reauthorize source release.
- Keep immutable revisions, source digests, exact excerpts and UTF-8 byte spans consistent across runtimes.
- Keep coverage estimates (`sufficient`, `partial`, `insufficient`) separate from execution (`complete`, `degraded`). Unknown coverage cannot become sufficient, and operational failures cannot become missing-evidence success.
- Preserve deadlines, cancellation, budgets and usage accounting. Core imports must not contact a network, download models, connect to a database or migrate schemas.

Start with fake providers and small inputs. A provider error is a useful failure case: the result must expose the operational failure according to its contract, even if some evidence is available. An empty result alone does not prove that error handling works.

### Run checks and report their limits

Run the affected package's typecheck and build above, plus your synthetic reproduction. For documentation-only work, check links, commands and consistency instead of inventing code tests.

The public package checker verifies all six packages in a disposable source copy without private files, databases or provider credentials. From the repository root, choose a fresh output directory:

```sh
python3 tools/check_public_packages.py --output-dir artifacts/contribution-public-check
```

Its default uses populated offline dependency caches. Missing cache inputs fail clearly. To permit dependency downloads explicitly, use a different fresh directory:

```sh
python3 tools/check_public_packages.py --allow-downloads --output-dir artifacts/contribution-public-check-online
```

Read the generated report. The checker covers serial frozen installs, typing, builds, archives, source-distribution rebuilds and installed imports. A pass establishes those boundaries; it does not establish model quality, native backend security or production readiness. See [development](docs/development.md) for the full scope and resource policy.

The public checkout does not ship a general `pytest` or `npm test` regression suite. Contributors do not need access to the private workbench. Maintainers run retained regression and parity checks against the proposed source and record their results separately. Native backend tests, live-provider runs and hosted CI also need their own prerequisites and authorization; do not start services or paid calls just to submit a PR. The current GitHub workflow is manually dispatched, so opening a PR does not imply that hosted checks have run.

For each check, report its exact command, working directory, runtime versions, result and relevant configuration. Name checks you did not run and why. Record whether evidence is local, fake-provider, installed-artifact, native-backend, live-provider or hosted CI. Stop resource-heavy work if responsiveness deteriorates and close task-owned processes.

## Submit a pull request

Use a descriptive branch and a Conventional Commit style PR title, such as `fix(retrieval): preserve required filters during recovery` or `docs(usage): explain optional tokenizer setup`. Use the [PR template](.github/pull_request_template.md) to describe the problem, resulting behavior, reproduction, checks and compatibility impact. Link the issue when one exists; use a closing keyword only when the PR actually resolves it.

Before opening the PR:

1. Review `git status --short`, `git diff` and `git diff --check` from the repository root. Exclude secrets, private data, generated artifacts and unrelated edits.
2. Stage only the files belonging to the change. Review `git diff --cached` and `git diff --cached --check`, then make a focused commit using the same title convention.
3. Push the feature branch to your fork or authorized repository remote. Open a PR against the intended base branch, normally `main`, and complete the template. Use a draft while required decisions or evidence remain pending.

Respond to review with the reason for each substantive change and rerun affected checks after revisions. Maintainers may request smaller scope, additional failure evidence or a contract decision. Follow repository branch protections; this guide does not assume a fixed reviewer count, automatic checks or a merge deadline.

| Change | Include for review |
| --- | --- |
| Shared schema or public API | Contract update, Python/TypeScript compatibility analysis, synthetic cases and migration guidance for breaking behavior. |
| Dependency or toolchain | Reason, manifest and matching lock changes, API/license review and affected build/import evidence. Keep optional integrations optional. |
| SQL, backend capability or source profile | Explicit migration/operator impact, scoped-access and failure cases, reindexing or rollback limits and separately run backend evidence. Never apply migrations on import. |
| Provider, model, tokenizer or policy | Validation, identity, budget and disclosure impact. Fake tests do not establish live quality; new quality claims need separate evidence. |
| Documentation | Working commands and links, accurate status and clear limitations without changing the README's established structure incidentally. |

Merging a fix does not change published RC1 bytes. A corrective version, registry upload, stable release or repository visibility change follows a separate maintainer decision under the [release guide](docs/releasing.md), [publication procedure](docs/publication.md) and [maintenance workflow](docs/maintenance.md).

## Report issues safely

Use synthetic data and invented identities. Include affected packages and versions, install method or source commit, runtime/platform, enabled profiles, provider mode, exact reproduction commands, expected behavior and actual evidence/execution state. A short redacted log or stable error code is more useful than a raw dump. Mark unavailable fields as unknown and unrun checks explicitly.

Never attach credentials, connection strings, `.env` files, private queries, source documents, raw provider errors, database dumps or unreviewed logs. A private repository is still a disclosure surface. If you cannot remove sensitive details, stop and arrange a safe path as described in [support](docs/support.md). Issue forms help structure reports; maintainers still review completeness and redaction, especially while the repository is private.

For a small practice exercise, trace one synthetic failure from the bug form to a focused patch and PR, then identify which checks require a maintainer or a backend. No provider call is needed.
