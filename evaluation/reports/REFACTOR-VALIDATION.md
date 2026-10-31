# Role-based filename refactor validation

State: COMPLETE for the renamed original checkout. Date: 31 October 2026. The broader V6 implementation remains paused.

For example, Python test collection succeeded while a renamed TypeScript native runner could not resolve `cragkit/*` from the tools directory. Executing that entry point exposed the missing dependency path before any query ran. This is why collection, installed artifacts and actual native entry points need separate checks.

## Repairs and ownership

The user-provided renames are retained. Sol peers repaired executable references and test harnesses in separate lanes, coordinated directly and named the test peer as assembler. Primary inspected their changes, fixed native ESM linking, reconciled current documentation/manifest/lock paths and ran integration serially.

Fixed stale calibration imports and subprocess paths, both installed-probe copy paths, the PostgreSQL fixture import and the publication verifier's renamed Node child. Native execution found bare package imports introduced in the backend runner and publication helper; both now resolve the checkout's built modules by explicit relative paths. Installed-package probes retain bare imports because those deliberately execute inside clean package environments. Added real subprocess entry-point regression cases from an unrelated directory and a lazy-import regression. A malformed native child result now leaves bounded diagnostic metadata instead of masking it as an unexplained JSON parse failure.

The actual former `check_v4.py` is `check_sdk_packages.py`; the separate `check_postgres_prerequisites.py` checks the prepared native database fixture. The user-selected `check_qdrant_artifacts.py` checks MCP archives and six optional installation profiles, not Qdrant publication itself. [Tooling entry points](../../docs/tooling.md) records actual command roles and the historical-name map. Current README/development/CI/pilot commands and links use the new names. Historical reports retain literal commands actually run; their moved local hyperlink targets were repaired.

A frozen-lock check exposed stale local-project metadata. The conformance workspace now uses the role-based internal project name and synchronized metadata for the existing development dependencies. All third-party package versions, URLs and hashes remain unchanged. Core runtime dependencies and migrations were not changed.

## Actual verification

| Check | Result |
| --- | --- |
| Renamed focused Python surfaces | 161 passed |
| Full core/SDK pipeline | All 34 stages passed, including core types/builds, shared conformance, corpus/seals, clean core and LangChain artifacts |
| Final complete Python/tool suite | 3,199 passed; four deliberate malformed-model serializer warnings |
| Complete Node core suite | 1,590 passed |
| LangChain suites and installed artifacts | 72 Python / 69 Node passed |
| Isolated optional profiles / installed MCP | Twelve fresh environments passed; 41 Python / 36 Node MCP tests passed |
| Actual PostgreSQL/Qdrant direct, LangChain and MCP | 84 retrieval calls and 16 forged-input refusals passed with parsed cross-runtime parity and verified cleanup |
| Renamed publication verification child | 38 native checks passed; cleanup verified |
| Renamed PostgreSQL prerequisite command | Genuine private PostgreSQL17.11/pgvector0.8.0 binding and restricted-role guards passed; cleanup verified |
| Moved installed-package pilot | All 21 smoke checks passed, including scope, exact excerpts, updates, tombstone and shutdown |
| Release/corpus integrity | Six preregistration digests, 10 BR/105 edge paths and all 16 sealed inputs verified; no held-out scoring |

The 34-stage run's Python count was 3,197. Two additional native entry-point regression cases then passed, and the complete final Python suite passed all 3,199. No successful count is inferred from collection alone.

Executed entry points:

```sh
python3 tools/check_sdk_packages.py --artifacts-dir artifacts/refactor-validation/full-sdk
python3 tools/check_qdrant_artifacts.py --core-artifacts artifacts/refactor-validation/full-sdk/core --output-dir artifacts/refactor-validation/optional-artifacts
uv run --project packages/python --frozen --no-sync pytest packages/python/tests tools/tests -q
uv sync --project tools/backend-conformance --python /opt/homebrew/bin/python3 --frozen
uv run --project tools/backend-conformance --frozen --no-sync python tools/check_backend_conformance.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/refactor-validation/backend-conformance-final-02
uv run --project packages/python --frozen --no-sync python tools/check_qdrant_publication_verification.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/refactor-validation/publication-verification
uv run --project packages/python --frozen --no-sync python tools/check_postgres_prerequisites.py --prepared-postgres-bin artifacts/V6/V6-02A/private-pg/prefix/Cellar/postgresql@17/17.11/bin --allow-local-processes --artifacts-dir artifacts/refactor-validation/postgres-prerequisites
uv run --project packages/python --frozen --no-sync python examples/pilot_rag/session.py --smoke
python3 tools/check_release_readiness.py
python3 tools/check_seal.py
uv lock --project tools/backend-conformance --check --offline
```

Native commands require their explicit preinstalled/prepared prerequisites. Use fresh output directories when repeating them. [Structured results](REFACTOR-VALIDATION-results.json) bind the retained native/artifact result digests. Logs and full raw observations are under ignored `artifacts/refactor-validation/`. The first native conformance failure was retained; after reproducing its module-resolution error, corrected entry points and the full native matrix passed.

## Integrity and limits

The renamed `benchmark_metrics.py` is byte-identical to the previously frozen `v6_metrics.py`: SHA-256 `c7478fd304d0b4c2b72e506e0080119a05ab34068566208b314c9b6a6fee99e8`. Release settings, quality/resource targets, limits, mode list and corpus/split digests are unchanged. The metric documentation digest was rebound only because its link now targets the renamed file; no metric definition or algorithm changed. All old input seals passed.

Verification used the inspected working tree, including preserved pre-existing reader-facing edits. Those unrelated source/storage edits and user audit files remain outside the scoped commit. Paused OpenAI-profile drafts in the detached worktree were neither integrated nor tested as part of this refactor. README banner, section order, status table, callouts and collapsible guide were preserved. AGENTS.md now directs future implementation/test filenames to describe their roles.

Suites ran serially on local macOS arm64, Python3.14.6 and Node26.5.0. Final headroom was 31 GiB disk and 39 percent system memory free. Native PostgreSQL, Qdrant and SDK boundaries were real; model responses were fake or recorded. No live inference, private document disclosure, hosted write, registry publication or hosted CI run occurred. Native fixtures and temporary installation environments closed. These results establish the stated local refactor behavior, not production or V6 release readiness.

Learning exercise: explain why an installed probe should import a package by name while a repository-owned development runner needs a resolvable checkout path. Learning practice remains unassessed. V6 stays paused until the user resumes it.
