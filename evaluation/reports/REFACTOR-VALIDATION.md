# Role-based filename refactor validation

State: COMPLETE for the filename refactor. Latest verification: REF-01-R3 below, 31 October 2026. V6 release acceptance remains open. Earlier sections retain their original run snapshots.

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

## Follow-up reference audit

REF-01-R2, 31 October 2026: COMPLETE. Two Sol peers independently inspected executable references and retained evidence; the evidence peer assembled their findings, and root performed the final checks. No remaining stale executable imports, subprocess targets or installed-probe copy paths were found in the inspected tooling, runners, examples and package tests. Four active documentation locations still used moved paths: two commands in `examples/qdrant_dense.md`, the test references in `examples/existing_index.md`, and the SDK command in `docs/releases/V4.md`. Root corrected them. Historical executed-command records and protocol identifiers remain unchanged.

Fresh checks, run serially:

- The eleven renamed tooling suites listed below passed 131 tests.
- The Python retrieval-evidence, existing-index-adapter and Qdrant example suites passed 32 tests.
- TypeScript typecheck/build passed; the four affected Node suites passed 35 tests without skips.
- Release preregistration verified six input digests and all 105 edge-case paths; all 16 input seals and the offline conformance lock check passed.
- Root independently verified all six retained native/artifact evidence digests, the benchmark identity against both the report and candidate manifest, and twelve local documentation targets. The evidence peer also verified twelve nested archive digests. Scoped whitespace and prose checks passed.

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_check_core_pipeline.py tools/tests/test_check_sdk_packages.py tools/tests/test_backend_conformance.py tools/tests/test_check_qdrant_artifacts.py tools/tests/test_check_release_readiness.py tools/tests/test_dense_metrics.py tools/tests/test_benchmark_metrics.py tools/tests/test_rerank_calibration.py tools/tests/test_run_rerank_calibration.py tools/tests/test_postgres_vector_fixture.py tools/tests/test_provider_adapters.py -q
uv run --project packages/python --frozen --no-sync pytest packages/python/tests/test_retrieval_evidence.py packages/python/tests/test_existing_index_adapter.py packages/python/tests/test_qdrant_dense_retrieval.py -q
npm run typecheck --prefix packages/typescript
npm run build --prefix packages/typescript
node --test --test-concurrency=1 packages/typescript/tests/calibration-replay.test.mjs packages/typescript/tests/retrieval-evidence.test.mjs packages/typescript/tests/existing-index-adapter.test.mjs packages/typescript/tests/qdrant-dense-retrieval.test.mjs
python3 tools/check_release_readiness.py
python3 tools/check_seal.py
uv lock --project tools/backend-conformance --check --offline
```

The full-suite, installed-package and native database results above remain retained evidence from the original validation; they were not rerun in this follow-up. No live API call, service startup, installation or held-out scoring occurred. Existing unrelated edits and detached V6 feature drafts were preserved. Final headroom: 31 GiB disk and 46 percent system memory free; no task-owned background process. Role-based implementation and test names are required by AGENTS.md for subsequent versions, including V6. Learning practice remains unassessed; the exercise above is optional. This follow-up completes rename validation, not V6 release acceptance.

## Current-checkout verification

REF-01-R3, 31 October 2026: COMPLETE for the filename refactor on the current checkout, based on `cc9a3ee` plus the preserved workspace edits. This supersedes the earlier follow-up's runtime snapshot. It does not complete V6 or establish that the current package tree matches the frozen release candidate.

Two Sol peers inspected executable references and manifest/Node resolution independently, communicated directly and assembled their findings. Root inspected the combined evidence and ran acceptance serially. All 39 destinations recorded in the rename commit exist. No stale active import, subprocess target, installed-probe copy source or moved example path required another repair. Historical command records and stable protocol identifiers remain unchanged. The existing role-based naming rule in `AGENTS.md` applies to future implementation and tests, including V6.

Fresh execution did expose a test-harness defect in `tools/tests/test_provider_adapters.py`. During collection it replaced the canonical `provider_adapters` module through `sys.modules`. Previously collected consumers retained the original `ProviderRequest` class; later requests used a different class and failed exact-type admission. Five tests failed after 3,155 passed, and a cancellation test waited for a mock transport that could never be reached. Root interrupted that owned run after 89 seconds to obtain the tracebacks. All 21 sender tests passed in isolation, confirming that isolated success was insufficient.

The repair uses the normal canonical import. A new regression checks shared request identity and exercises approved synthetic text through payload admission, recording metadata, fake HTTP and strict response validation. Production admission, authorization and type checks were not relaxed. The six related suites then passed together in the collection order that exposed the defect: 159 tests.

Fresh acceptance after the repair:

| Check | Result |
| --- | --- |
| SDK/core pipeline | All 34 stages passed |
| Python core and tooling | 3,394 passed; four intentional malformed-model serializer warnings |
| Node core | 1,615 passed; no skips |
| LangChain | 72 Python / 69 Node passed; clean installed artifacts passed |
| Optional installed profiles | Six Python / six Node passed; installed MCP tests 41 Python / 36 Node passed |
| Native PostgreSQL/Qdrant direct, LangChain and MCP | 84 calls, 16 forged-input refusals, parsed cross-runtime parity and verified cleanup |
| Native publication verifier | 38 checks passed across Python/Node; cleanup verified |
| Prepared PostgreSQL prerequisite entry point | Three genuine pgvector/restricted-role checks passed; cleanup verified |
| Moved pilot using its existing installed wheel | All 21 smoke checks passed; disposable database and private credentials cleaned |
| Release metadata and sealed inputs | Six preregistration digests, 10 requirement / 105 edge paths, all 16 seals and the offline conformance lock check passed |

The renamed benchmark remains byte-identical to its pre-rename implementation, SHA-256 `c7478fd304d0b4c2b72e506e0080119a05ab34068566208b314c9b6a6fee99e8`. The peer audit also verified all 58 third-party conformance lock records against the pre-rename lock, 26 relative Node targets, 1,079 coverage-path occurrences, six retained result hashes and twelve nested archive hashes. Retained-file integrity is separate from the fresh execution above.

[Structured results](REFACTOR-CURRENT-results.json) record the actual commands and hashes of the fresh acceptance files and logs. Raw outputs remain under ignored `artifacts/refactor-validation/` and `/tmp/cragkit-rename-*.log`. Suites ran serially on local macOS arm64, Python 3.14.6 and Node 26.5.0. Final observed headroom was 31 GiB disk and 44 percent system memory free. Task-owned native processes closed.

No live inference, held-out scoring, hosted database write, hosted CI or package publication occurred. Models were fake or recorded. Current clean package installs were tested separately from the pilot's reused installed environment. Existing source/doc edits, audit reports and untracked V6 execution drafts were preserved and excluded from this change. V6 evaluation, candidate refreezing and release gates remain separately tracked.

Optional exercise: explain why importing the same file into two module objects can break an exact-type check even when the class names match. Learning practice remains unassessed.
