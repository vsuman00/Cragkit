# Tooling entry points and naming

For example, renaming a Python file does not update a lazy import, a subprocess path or an artifact-copy source. Collection can pass while a later execution branch still fails. Validate both imports and actual entry points after a move.

Use role-based filenames for implementation and tests. Milestone names remain appropriate in versioned contracts, plans and evidence directories. Keep existing protocol identifiers, fixture revisions and historical observations stable during a filename refactor.

## Current commands

| Entry point | Actual responsibility |
| --- | --- |
| `tools/check_core_pipeline.py` | Serial core typing/tests, shared conformance, corpus/seals and clean core artifacts |
| `tools/check_sdk_packages.py` | Core pipeline plus optional LangChain typing/tests and installed SDK artifacts |
| `tools/check_postgres_prerequisites.py` | Explicit opt-in check of a prepared private PostgreSQL/pgvector environment and cleanup |
| `tools/check_postgres_profiles.py` | Explicit atomic upgrade/read-only verification of the two-profile PostgreSQL catalog; no automatic grants or inference |
| `tools/check_postgres_profile_storage.py` | Disposable native legacy/upgraded profile, rollback, permission and Python/Node mechanics checks |
| `tools/check_backend_conformance.py` | Explicit disposable PostgreSQL/Qdrant direct, LangChain and MCP native conformance |
| `tools/check_qdrant_artifacts.py` | MCP archives and six isolated core/backend/tokenizer/MCP installation profiles; this does not start a Qdrant server |
| `tools/check_release_readiness.py` | Frozen release preregistration and evidence-path integrity; configuration verification alone does not establish release readiness |
| `tools/run_rerank_calibration.py` | Opt-in live calibration driver; routine validation uses recorded/injected responses without live calls |
| `examples/pilot_rag/session.py` | Installed-package pilot on an explicitly owned disposable database |

The former `check_v4.py` is now `check_sdk_packages.py`. It was not a PostgreSQL prerequisite checker. The database prerequisite command came from the separate development fixture check. File roles above follow the actual implementations.

The backend workspace is `tools/backend-conformance/`. Its internal project is named `cragkit-backend-conformance`, with frozen dependency hashes. Run tools serially and use fresh artifact directories where required.

```sh
python3 tools/check_sdk_packages.py --artifacts-dir artifacts/refactor-validation/full-sdk
python3 tools/check_qdrant_artifacts.py --core-artifacts artifacts/refactor-validation/full-sdk/core --output-dir artifacts/refactor-validation/optional-artifacts
python3 tools/check_release_readiness.py
```

[Development commands](development.md) list explicit native setup and admission flags. [The validation report](../evaluation/reports/REFACTOR-VALIDATION.md) records commands actually executed and their limits. These commands do not publish packages.

## Evaluation helpers

Evaluation-only helpers live in `tools/`: `provider_recordings.py` validates
provider wire data, `provider_journal.py` retains durable private tapes,
`recorded_provider.py` composes text/admission/HTTP boundaries, and
`provider_replay.mjs` replays the same tape through native Node adapters.
They do not discover credentials or form a live evaluation CLI. The
[recording checks](development.md#evaluation-recording-and-provider-replay)
run without paid inference.

## Historical-name lookup

Historical reports retain the command names actually executed at the time. They are evidence records, not current command references. Use this map when reproducing an old report; use the current filenames for new code and documentation.

| Historical name | Current path |
| --- | --- |
| `tools/check_v0.py` | `tools/check_core_pipeline.py` |
| `tools/check_v4.py` | `tools/check_sdk_packages.py` |
| `tools/check_v5_conformance.py` | `tools/check_backend_conformance.py` |
| `tools/check_typescript_v5_conformance.mjs` | `tools/check_typescript_backend_conformance.mjs` |
| `tools/v5_conformance_fixture.py` | `tools/backend_conformance_fixture.py` |
| `tools/v5_conformance_python.py` | `tools/backend_conformance_runner.py` |
| `tools/v5-conformance/` | `tools/backend-conformance/` |
| `tools/check_v5_artifacts.py` | `tools/check_qdrant_artifacts.py` |
| `tools/check_v6_release.py` | `tools/check_release_readiness.py` |
| `tools/probe_v5_installed.py` / `.mjs` | `tools/probe_qdrant_installed.py` / `.mjs` |
| `tools/run_v3_calibration.py` | `tools/run_rerank_calibration.py` |
| `tools/check_typescript_v3_calibration.mjs` | `tools/check_typescript_rerank_calibration.mjs` |
| `evaluation/runners/v2_metrics.py` | `evaluation/runners/dense_metrics.py` |
| `evaluation/runners/v3_calibration.py` | `evaluation/runners/rerank_calibration.py` |
| `evaluation/runners/v6_metrics.py` | `evaluation/runners/benchmark_metrics.py` |
| `evaluation/runners/synthetic-vectors.mjs` | `evaluation/runners/synthetic_vectors.mjs` |
| `examples/v5_rag/` | `examples/pilot_rag/` |
| `packages/python/tests/test_retrieval_v3.py` | `packages/python/tests/test_retrieval_evidence.py` |
| `packages/typescript/tests/retrieval-v3.test.mjs` | `packages/typescript/tests/retrieval-evidence.test.mjs` |
| `packages/python/tests/test_existing_index_example.py` | `packages/python/tests/test_existing_index_adapter.py` |
| `packages/typescript/tests/existing-index-example.test.mjs` | `packages/typescript/tests/existing-index-adapter.test.mjs` |
| `tools/test_qdrant_dense_example.mjs` | `packages/typescript/tests/qdrant-dense-retrieval.test.mjs` |
| `tools/tests/test_qdrant_dense_example.py` | `packages/python/tests/test_qdrant_dense_retrieval.py` |
| `tools/qdrant_publication_verification_node.mjs` | `tools/qdrant_publication_verification_cases.mjs` |

Renamed tool tests use the same role-based stems. Keep metric algorithms and reviewed inputs unchanged when updating path/digest references. A documentation link repair may legitimately change the documentation digest; record that separately from code or policy changes.

Exercise: move one small test-only module in a temporary branch, predict the imports and copied paths affected, then use a failing entry-point test to verify the repair.
