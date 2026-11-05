# Development and verification

For example, a strict typecheck can catch a mismatched adapter signature, while a package import check can catch a missing shipped module. Neither proves that a live backend enforces row access. Record those results separately.

The public checkout contains native library sources, contracts, migrations and current operational documentation. Personal tests, evaluation data, historical reports and demonstration applications are retained in the separate private maintainer workbench. Building or importing the library does not require that workbench.

## Toolchain and source checks

Inspect package manifests and frozen locks before running commands. Current declared runtime ranges are Python `>=3.14,<3.15` and Node `>=26.5.0 <27`. The recorded RC1 tuple used Python 3.14.6, Node 26.5.0, npm 11.17.0 and uv 0.11.8; see [release notes](releases/V6.md) for platform limits.

From the repository root:

```sh
uv sync --project packages/python --frozen
uv run --project packages/python --frozen --no-sync mypy --config-file packages/python/pyproject.toml packages/python/src
```

From `packages/typescript`, run these separately:

```sh
npm ci --ignore-scripts
npm run typecheck
npm run build
```

Optional packages under `packages/langchain-*` and `packages/mcp-*` have their own manifests and frozen locks. Install only the profiles needed for the task. Core imports must not open a database, contact a provider, download a model or apply a migration.

## Public package validation

From the repository root, choose a fresh ignored output directory:

```sh
python3 tools/check_public_packages.py --output-dir artifacts/public-check
```

The checker runs serial frozen installs, strict Python and TypeScript checks, builds for all six packages, Python wheel/source-distribution and npm archive checks, source-distribution wheel rebuild comparison and fresh installed-import smoke checks. It does not need private test suites, a database or provider credentials. The default requires already populated offline dependency caches; missing packages fail without downloading. `--allow-downloads` explicitly permits dependency downloads, as used by hosted CI. Read its report before claiming acceptance; the existence of the script is not a passing run.

A public package pass establishes the checked source/build/import boundaries only. It cannot replace regression, model-quality, native backend or deployment evidence.

## Private maintainer verification

Maintainers retain the original test suites, deterministic fixtures, examples, evaluation helpers and historical evidence outside the repository. The private runner takes an explicit current public source path and a fresh private output directory. For the archive created by `PUBLIC-SEPARATION`, invoke its `validation/run_private_regression.py` with `--public-root` and `--output-dir`.

The runner constructs a disposable overlay from the current public sources and retained private harness. It restores test-only configuration in that overlay, uses frozen offline dependency caches and serial checks, and leaves the public checkout and original archive trees untouched. Missing private material or cache inputs must fail clearly. An old archived pass does not validate changed public bytes.

Routine verification uses fake or recorded providers and small fixtures. Native PostgreSQL/Qdrant integration needs explicit disposable-target ownership, restricted roles, cleanup and separate admission; live providers additionally need approved data disclosure and bounded spending. Neither is started by a source or package check. The private workbench is a maintainer resource, not a runtime dependency distributed to consumers.

## Resource and reporting policy

Start one check process at a time. Serialize language integration suites, bound ingestion/pools/workers, reuse clients and stop if memory pressure or responsiveness deteriorates. Do not start persistent services or download models as a side effect of checking a small change. Close task-owned processes and retain only redacted diagnostics.

Record exact commands, source identity, configuration, results, unrun checks and cleanup. Keep local source, private regression, installed package, database integration, live-provider, hosted CI and registry evidence distinct. Use [the roadmap handoff](roadmap.md#session-handoff) for current task state.
