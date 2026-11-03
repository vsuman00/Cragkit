# Cragkit development

## Recovery evaluation acceptance

[V6-02 recovery evidence](../evaluation/reports/V6/V6-02-recovery.md) records
39 completed live calls, a healthy sealed tape and matched Python/Node recorded
replays. Six synthetic questions passed the frozen relative targets; all results
withheld sufficiency, historical search remained active-generation-only and
conflict detection missed its one case. This is scoped evaluation/reproduction
acceptance, not general relevance or production-readiness evidence.

The [runtime preparation record](../evaluation/reports/V6/V6-02I-runtime.md)
records explicit Python 3.14.6 selection, verified frozen Node dependency reuse
and the owner-only output parent needed before receipt preparation. The frozen
candidate's pending gate/access wording is its pre-run snapshot; current task
acceptance belongs in the tracker. Preserve receipt-bound candidate bytes when
recording post-run completion.

## Reviewed evaluation packet profiles

The [EPR-r1 binding contract](../contracts/EVALUATION_PACKET_REVISIONS_V6.md)
selects only known independently pinned original/recovery profiles. Development
remains original. Recovery labels were approved separately by the project user;
[the approval and binding report](../evaluation/reports/V6/V6-02I-approved-binding.md)
records scope and limits. The checker reads manifest/seal metadata, never held-out
questions; the parent scorer loads only an issued root/path/digest after execution.

```sh
uv run --project packages/python --frozen --no-sync python -B -m pytest tools/tests/test_evaluation_packet.py tools/tests/test_check_release_readiness.py tools/tests/test_run_release_evaluation.py tools/tests/test_evaluation_runtime.py -q
```

Verified: 179 focused tests and 3,780 Python/tool regressions. These are offline
checks; a later candidate/profile selection requires a new frozen runtime receipt.

## Evaluation transport pacing and safe failures

The [ETP-r1 correction](../contracts/EVALUATION_TRANSPORT_V6.md) adds serial
Cohere pacing to the live evaluation sender and preserves fixed auth/rate/server
failure categories in its private journal. Pacing waits share the original
request deadline; they do not retry requests or raise spend/call limits.
Mock transports skip production pacing. These offline tests also exercise the
production path with a fake client and clock:

```sh
uv run --project packages/python --frozen --no-sync python -B -m pytest tools/tests/test_evaluation_pacing.py tools/tests/test_provider_http.py tools/tests/test_recorded_provider.py tools/tests/test_provider_journal.py -q
```

Current terminal-time correction: 173 focused tests and 3,727 Python/tool
regression tests passed. The next interval starts after a started HTTP operation
fully unwinds, including stream cleanup; delayed connection setup cannot consume
that interval. See [the terminal-time report](../evaluation/reports/V6/V6-02H4-terminal.md).
The prior [H1-H3 check](../evaluation/reports/V6/V6-02H-transport.md) also passed
41 Node provider-replay tests; H4 changes Python evaluation transport only.
The failed original live run remains unsealed and cannot be resumed by this
change. Any later evaluation requires its own reviewed input and frozen identity.

## Candidate execution identity and comparison

The [ECR-r1 contract](../contracts/EVALUATION_CANDIDATE_V6.md) and
[offline checkpoint](../evaluation/reports/V6/V6-02E-candidate-execution.md)
separate runtime preparation from genuine model-quality acceptance. Use a fresh
isolated checkout for candidate preparation: Python `-B` still reads existing
bytecode, so checkout caches are refused. The runtime helper makes no install,
network or model request. Candidate source/versions must be aligned before its
real preparation commands can pass.

Verified focused commands, run serially from the repository root:

```sh
uv run --project packages/python --frozen --no-sync python -B -m pytest tools/tests/test_run_release_evaluation.py tools/tests/test_retrieval_evaluation.py tools/tests/test_evaluation_runtime.py tools/tests/test_evaluation_scoring.py tools/tests/test_evaluation_pricing.py -q
uv run --project packages/python --frozen --no-sync python -B tools/run_release_evaluation.py --mode mechanics --prepared-postgres-bin artifacts/V6/V6-02A/private-pg/prefix/Cellar/postgresql@17/17.11/bin --output artifacts/V6/V6-02E/mechanics-03 --allow-local-processes
```

Use a fresh output directory for another run. Mechanics uses approved development
input and fake providers; it does not validate live quality. The parent rejects
incomplete mode matrices before independent scoring, preserving every failed
question/mode denominator. Live and replay modes additionally require matching
prepared runtime identity and held-out packet binding. Live mode needs explicit
private key paths, dated official-price review and a durable single-use admission;
it never discovers keys or retries dispatch automatically.

## Evaluation recording and provider replay

The [recording contract](../contracts/EVALUATION_RECORDING_V6.md) separates
pending dispatch, captured responses, usage estimates and healthy cleanup.
These helpers are internal evaluation tooling; their tests make no live call.
Use the existing development environment and a current TypeScript build, then
run these checks serially from the root:

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_recorded_provider.py tools/tests/test_provider_journal.py tools/tests/test_provider_recordings.py tools/tests/test_provider_http.py tools/tests/test_live_evaluation_budget.py tools/tests/test_evaluation_payloads.py tools/tests/test_provider_adapters.py -q
node --test --test-concurrency=1 tools/tests/provider_replay.test.mjs
```

[Recorded acceptance](../evaluation/reports/V6/V6-02C-recording.md) distinguishes
mock HTTP/native adapter replay from genuine provider and held-out quality
evidence. A journal seal alone does not prove a healthy evaluation exit.

## Explicit PostgreSQL embedding-profile upgrade

[The profile guide](postgres-embedding-profiles.md) explains the optional OpenAI
storage upgrade and runtime selection. This administrative setup remains
separate from library imports and key/provider configuration. The native check
uses an already prepared, genuinely pinned PostgreSQL17.11/pgvector0.8.0 prefix;
it never downloads or replaces the machine's extension installation.

```sh
python3 tools/check_postgres_profiles.py --check --confirm-dedicated-target
uv run --project packages/python --frozen --no-sync python tools/check_postgres_profile_storage.py --prepared-postgres-bin artifacts/V6/V6-02A/private-pg/prefix/Cellar/postgresql@17/17.11/bin --artifacts-dir artifacts/V6/profile-storage-check --allow-local-processes
```

Use a fresh artifact directory and build TypeScript first. Run one native suite
at a time. The checker uses at most two runtime connections, releases setup
connections before model callbacks and verifies owned process cleanup. Fake
vectors remain fake; injected OpenAI dispatch failures return no vector data.
See [V6-02B evidence](../evaluation/reports/V6/V6-02B.md) for actual results and
the remaining live-quality boundary.

## Current development database: Neon

On 22 October 2026 the user selected a new dedicated Neon development project in VAIBHAV's Free organization, Singapore, PostgreSQL 17, and authorized the [migration plan](neon-migration-plan.md). Follow the [Neon setup and security runbook](neon.md) for current target preparation. Direct Neon native Python/TypeScript security and integration acceptance passed on the dedicated synthetic target. [DB-NEON-01 evidence](../evaluation/reports/V2/DB-NEON-01.md) records 47 native groups, final local regressions and cleanup. Private development fixture configuration uses that endpoint; applications still supply restricted roles and scoped policies.

The verified commands below remain portable PostgreSQL commands. Use the direct Neon endpoint first with verified TLS and separate administrative, ingestion and retrieval roles; validate pooled behavior separately. Preserve the existing migrations and optional native drivers. Neon hosting does not enable Auth, a Data API or other Neon services.

The dated sections below retain their original local and Supabase observations. Their successful checks establish behavior only for their recorded target and configuration; they are not Neon results. Supabase resources were preserved after development cutover; retirement is a separate action.

## V0-01 baseline

Observed locally on 19 October 2026 before package setup. This is a workspace and tool inventory; supported runtime ranges and dependency compatibility remain pending V0-03. The [V0-01 resource report](../evaluation/reports/V0/V0-01.md) records hardware, disk, memory, existing services and database preconditions. Completion state lives in [the tracker](../tasks/todo.md).

The workspace contains architecture, plans, papers, analysis artifacts and project skills. File discovery found no Python or npm package manifests, lockfiles, TypeScript configuration or implementation test configuration. `git status --short` exited 128 because this directory is not a Git checkout. No Git initialization was performed; existing files were preserved.

### Verified tools

Commands below ran from the project root. Version probes establish availability only; they do not establish package compatibility.

| Command | Actual result | Exit |
| --- | --- | --- |
| `python3 --version` | Python 3.14.6 | 0 |
| `node --version` | v26.5.0 | 0 |
| `npm --version` | 11.17.0 | 0 |
| `uv --version` | uv 0.11.8 (0e961dd9a 2026-04-27 aarch64-apple-darwin) | 0 |
| `pnpm --version` | 9.15.9 | 0 |
| `git --version` | git version 2.50.1 (Apple Git-155) | 0 |
| `tsc --version` | Command not found | 127 |
| `pyright --version` | Command not found | 127 |
| `mypy --version` | Command not found | 127 |
| `pytest --version` | Command not found | 127 |

`command -v python3 node npm uv tsc pyright mypy pytest pnpm yarn git` found Python, Node, npm, uv, pnpm and Git; it exited 1 because some requested commands were absent. Python, Node, npm and pnpm resolve under `/opt/homebrew/bin`; Git resolves to `/usr/bin/git`; uv resolves to the user's `.local/bin/uv`. TypeScript/Python checking tools, pytest and yarn were absent from this shell's PATH. This does not prove they are absent from every environment on the machine.

Workspace discovery commands actually run:

```sh
git status --short
rg --files -g '!node_modules' -g '!.git'
rg --files -g 'AGENTS.md' -g 'package.json' -g 'pyproject.toml' -g '*lock*' -g 'tsconfig*' -g 'development.md' -g '.git' -g '!node_modules'
rg --files --hidden -g '!.git' -g '!node_modules' -g '!papers/**' -g '!docs/architecture/diagrams/**'
```

The scoped manifest discovery returned only `AGENTS.md` before this document existed. Hidden-file discovery also found both project skill entrypoints. These inventories are a snapshot; reinspect before establishing package commands.

### Resource and database policy

The resource report observed an Apple M4 with 16 GiB RAM and 10 logical CPUs, macOS 27.0.1 on arm64, and 22 GiB available disk space. Its snapshot recorded 2855.75 MB allocated swap; this does not establish active swap growth. No listeners appeared on the selected database/model/service ports. These observations support small setup steps with fresh headroom checks, rather than a capacity or service-readiness guarantee; the report preserves the commands and visibility limits.

Use one local test process and one language integration suite at a time. Routine checks use fake providers, small fixtures and no database. Independent agent writers must own separate files under [the coordination protocol](agents/WORKFLOW.md); shared contracts, manifests, lockfiles and tracker updates keep one owner. Stop and reduce concurrency or batch size if memory pressure or responsiveness deteriorates. Recheck headroom before installs or larger evaluations.

At the V0-01 baseline, hosted Supabase PostgreSQL was the selected development database. Provisioning, credentials and connectivity were pending. No dedicated target or schema has been verified, and no database connection was attempted for this baseline. Before any hosted test, verify a dedicated nonproduction target, connection mode, privileges, isolated schema/test data and required extension versions. Keep credentials and credential-bearing URLs out of reports and fixtures. Local PostgreSQL or Docker installation is optional and was not needed for V0-01. See the resource report for the full isolation checklist.

For example, a 500 MB model file uses disk even when no model process is running; process memory changes while that process runs. A hosted database's storage belongs to the remote database, so it is measured separately from laptop memory and disk. This baseline avoids starting services to make an inventory look complete. A failure case is treating an installed `node` executable as proof that the future TypeScript package passes its typecheck: no such package or typecheck exists yet.

### Commands still pending

| Purpose | State and owning task |
| --- | --- |
| Package installation and core import | Pending V0-02 package manifests and smoke checks |
| Focused Python and TypeScript tests | Pending V0-02 test setup |
| Dependency versions and typecheck commands | Pending V0-03 compatibility/dependency policy |
| Shared contract conformance | Pending V0-04 and V0-05 contracts |
| Database integration | Pending the owning retrieval task and verified isolated target |
| Package builds and resource measurements | Pending package setup and V0-07 baseline checkpoint |
| Hosted CI | Pending an available repository and V0-07 configuration |

No dependency installation, package test, typecheck, build, provider call or CI run was performed for V0-01. Add commands here only after their manifests/configuration exist and the commands have actually run. Runtime support ranges remain undecided until compatibility probes pass.

Learning exercise: identify which measurement would change when a model file is downloaded, when it is loaded, and when evidence is inserted into the hosted database. Learning remains pending until the learner practices or explains it.

## V0-02 package smoke checks

Both internal packages export version `0.0.0` and perform no retrieval yet. Package names remain provisional; the npm package is private. No license or publication decision has been made. Python uses a `src/cragkit` layout; TypeScript compiles strict ESM and declarations to `dist`.

Actual commands from the root, run sequentially:

```sh
uv venv .venv --python python3.14
uv pip install --python .venv/bin/python --editable packages/python
.venv/bin/python -m unittest discover -s packages/python/tests -v
```

The selected `python3.14` interpreter was CPython 3.14.4, while the baseline shell's `python3` reports 3.14.6. Python installed successfully with no runtime dependencies and passed one isolated import test. The test blocks socket activity, subprocesses, filesystem mutation, non-module reads and external dependency imports during core import.

Actual commands in `packages/typescript`, also sequential:

```sh
npm install --ignore-scripts
npm run typecheck
npm test
```

Installation added four development packages. Typecheck and build passed using TypeScript 7.0.2 and Node 26.5.0. One import smoke test passed with dependency and I/O guards. The npm lockfile records exact resolutions. No database driver, model runtime, service or provider was used. The import tests establish these small package entrypoints' behavior, not future optional integrations.

## Reproducible environment and compatibility

The current Python environment is `packages/python/.venv`, using CPython 3.14.6. The root `.venv` was an initial V0-02 smoke environment and is no longer used by project commands. Python direct and transitive versions/hashes are locked in `packages/python/uv.lock`; npm versions/integrities are locked in `packages/typescript/package-lock.json`. Update manifests and locks together, then run the affected compatibility and conformance checks. The internal release uses exact direct versions; widening public dependency ranges is future release work.

Verified root commands:

```sh
uv sync --project packages/python --frozen
uv run --project packages/python --frozen pytest packages/python/tests
uv run --project packages/python --frozen mypy --config-file packages/python/pyproject.toml packages/python/src
uv tree --project packages/python
```

Verified TypeScript commands, from `packages/typescript`:

```sh
npm run typecheck
npm test
npm ls --all
```

Reproducible npm setup uses `npm ci --ignore-scripts`; its lockfile was generated by `npm install --ignore-scripts`. The final checkpoint will exercise clean installation and package artifacts. Run Python and TypeScript checks sequentially, without database/model services. Python's `postgres` extra is optional; the core depends only on Pydantic, and TypeScript's core depends only on Zod. No frameworks, transports or model runtimes are installed.

The [compatibility report](../evaluation/reports/V0/V0-03.md) records tested pins, dependency sizes and driver-import probes. Only the installed macOS arm64/Python 3.14 and Node 26.5 combination has local evidence. Hosted database integration is not yet available; no database-test command is claimed. Upstream APIs checked before use: [Pydantic strict mode](https://docs.pydantic.dev/latest/concepts/strict_mode/) and [Zod strict schemas](https://zod.dev/api).

## Request contract verification

The [wire specification](../contracts/README.md) separates application requests, tool input and trusted scope. Python imports its models from `cragkit.contracts`; TypeScript imports from `cragkit/contracts`. The package root remains a minimal version export, with validation exposed through an explicit module/subpath. Neither path starts a retrieval engine or connects a service.

Verified root commands:

```sh
uv run --project packages/python --frozen python tools/check_contracts.py
uv run --project packages/python --frozen python tools/export_schemas.py
uv run --project packages/python --frozen python tools/export_schemas.py --check
```

The first command compares both runtimes on shared fixtures after building TypeScript. The second exports structural schemas from the Python models; the third fails on schema drift. Native implementations enforce additional semantic rules beyond JSON Schema. Fixture hashes identify exact checked-in UTF-8 file bytes, including formatting; normalized wire comparisons ignore object key order and compare JSON numbers by value. No universal canonicalization of arbitrary floating-point JSON is claimed.

For example, Python `parse_request({"query": "Find ERR-17", "collection": "engineering"})` and the TypeScript helper validate the same shape and fill explicit defaults. `parse_tool_request` rejects an extra `scope` or `limits` field. See [V0-04 evidence](../evaluation/reports/V0/V0-04.md) for the full checks and failure cases.

## Result contract verification

The [result specification](../contracts/RESULTS.md) defines immutable source spans, facet estimates, execution state and nullable accounting. `parse_result` is exported alongside request validation in both runtimes. It checks UTF-8 excerpt lengths/digests and internal references; a full canonical-source check requires the future source store.

Verified root command, after the TypeScript build:

```sh
uv run --project packages/python --frozen python tools/check_contracts.py --fixtures results
```

This passed all 32 result cases in addition to the 34 request cases. The full Python suite passed 110 tests and TypeScript passed 78 at V0-05, with both strict typechecks green. See [V0-05 evidence](../evaluation/reports/V0/V0-05.md). Unknown provider usage and costs remain null; a declared tokenizer identity is a schema requirement, not proof that any token counting ran.

## Corpus checks and human review

Verified root commands:

```sh
uv run --project packages/python --frozen pytest tools/tests/test_check_corpus.py -q
uv run --project packages/python --frozen python tools/check_corpus.py
uv run --project packages/python --frozen python tools/check_corpus.py --include-held-out
```

The corpus validator's 16 focused tests passed. The default command checks all 12 source digests but loads only 24 development questions; explicit initial held-out review checks all 30 questions and 26 labelled support spans. Output contains counts and stable error codes, without query/source text. These checks make no retrieval-quality claim.

The user explicitly approved all 30 labels on 19 October 2026. After recording that decision, `--include-held-out --require-human-review` passed with zero pending reviews. All 16 approved input hashes match [the seal](../evaluation/review/seal.json). Routine checks use development labels only and verify the held-out bytes through hashes; no held-out scoring occurred. [V0-06 evidence](../evaluation/reports/V0/V0-06.md) preserves both the historical pending gate and the final human acceptance.

## Complete local V0 check

Verified from the project root:

```sh
python3 tools/check_core_pipeline.py
```

All 12 stages passed: frozen setup, both typechecks, 155 Python/tool tests, 78 TypeScript tests/build, four schema checks, 66 native conformance cases, approved development-corpus validation, sealed input integrity and clean package verification. See [the CI profile](ci.md) for the stage policy and future hosted-job definition. Git was initialized afterward and the private [GitHub repository](https://github.com/vsuman00/Cragkit) was created under GIT-01. Hosted CI remains unrun; see [version control](version-control.md) for the current workflow.

Verified individual integrity and artifact commands:

```sh
python3 tools/check_seal.py
python3 tools/check_artifacts.py --output-dir artifacts/V0
```

The artifact command runs these build operations with absolute task-owned output paths and then checks clean installations:

```sh
uv build packages/python --out-dir artifacts/V0/python --no-python-downloads
uv build artifacts/V0/python/cragkit-0.0.0.tar.gz --wheel --out-dir artifacts/V0/rebuilt --no-python-downloads
```

In `packages/typescript`, it runs `npm run build` followed by `npm pack --json --ignore-scripts --pack-destination <absolute-artifact-directory>`. The standalone and runner commands share the same verifier; the recorded successful execution used the runner. Temporary default installations passed guarded imports outside the checkout, and the source distribution rebuilt identical wheel contents. Generated archives and detailed results remain under ignored `artifacts/V0/`; [V0-07 evidence](../evaluation/reports/V0/V0-07.md) records hashes, counts, resource methods and limitations.

There is no database-test command yet because no database integration exists. V0 produces internal contract packages and fixtures; it does not implement retrieval or demonstrate live model quality. Local package acceptance is separate from public distribution, license/name decisions, hosted CI and later platform support.


## V1-01: PostgreSQL schema and migration checks

The schema and explicit administrative runner passed local PostgreSQL 17.11 checks and the dedicated Supabase acceptance below, including authenticated native SQL. V1-01 is COMPLETE. [Evidence and limitations](../evaluation/reports/V1/V1-01.md); [storage contract](../storage/postgres/README.md). Native package adapters and retrieval are not implemented by this task.

Verified from the project root on 19 October 2026:

```sh
uv run --project packages/python --frozen pytest tools/tests/test_check_postgres.py -q
uv run --project packages/python --frozen pytest packages/python/tests tools/tests -q
python3 tools/check_postgres.py --help
```

Results: 17 focused tooling tests and 172 combined Python/tool tests passed. `npm test` from `packages/typescript` built TypeScript and passed all 78 tests. Both core import guards still passed; no native source or dependency changes were made.

### Database commands

The runner uses existing `psql`; it does not add a database-driver dependency to either package. These exact runner actions passed with `PGHOST` set to an absolute task-owned Unix-socket directory, `PGDATABASE=postgres` and `PGUSER=cragkit_admin`:

```sh
python3 tools/check_postgres.py --apply --confirm-dedicated-target --local-socket "$PGHOST" --integration
python3 tools/check_postgres.py --check --confirm-dedicated-target --local-socket "$PGHOST" --integration
python3 tools/check_postgres.py --check --confirm-dedicated-target --local-socket "$PGHOST"
```

The disposable cluster was created with the installed PostgreSQL 17 binaries, UTF-8 encoding and a private socket, with TCP listening disabled, 16 MB shared buffers and 10 maximum connections. The local harness also verified unchanged reruns, checksum/unknown-history rejection, failed-migration DDL and ledger rollback, and rejection of nonempty integration targets. Its generated script/result are in ignored `artifacts/V1/`; the committed SQL probes are `storage/postgres/tests/invariants.sql`. The harness stopped the server and removed the temporary cluster after each run, including failed runs. Do not point integration probes at a shared application database. They require all eight application tables to be empty, take exclusive locks, and roll back their synthetic rows.

For the original hosted Supabase preparation, the procedure was to identify a dedicated development project and confirm a direct or session connection suitable for administrative work. Current Neon setup follows the [Neon runbook](neon.md). Configure scalar `PGHOST`, `PGDATABASE`, `PGUSER`, a protected password source, `PGSSLMODE=verify-full` and the downloaded certificate path in `PGSSLROOTCERT`. Service files, connection-string database values and host redirection are rejected by this initial developer runner. The dedicated-target flag is an operator acknowledgment; it does not detect a production database. The hosted invocation omits `--local-socket`:

```sh
python3 tools/check_postgres.py --apply --confirm-dedicated-target --integration
python3 tools/check_postgres.py --check --confirm-dedicated-target --integration
```

At this historical preparation checkpoint, hosted commands were prepared, not verified. No Cragkit project or connection configuration was available during that session. Project provisioning/cost selection, certificate verification, actual role privileges and Supabase advisors remain pending. Existing unrelated projects were not modified. Administrative local tests use a privileged role; they do not prove least-privilege runtime access, pool behavior or RLS policy isolation. See [Supabase connections](https://supabase.com/docs/guides/database/connecting-to-postgres) and [PostgreSQL TLS verification](https://www.postgresql.org/docs/current/libpq-ssl.html).


### V1-01-H: Supabase security preparation

The [Supabase runbook](supabase.md), scoped deployment hardening and SQL security probe are implemented and locally verified. Hosted provisioning is waiting for the plugin-required organization choice. No Cragkit Supabase project, cost quote, hosted SQL or advisor run was created during this preparation. [Security evidence](../evaluation/reports/V1/V1-01-H.md).

Root ran `python3 artifacts/V1/run_supabase_security_local.py` using the existing temporary-cluster harness. It reapplied all migration/integrity checks, seeded three representative API roles and unsafe privileges, verified removal and safe hardening reruns, verified nine-table RLS and populated-row denial under a temporary nonowner role, detected owner-assumption/admin-attribute/RLS/privilege regressions, and preserved unrelated-schema grants. The cluster stopped and its files were removed. The generated harness/result remain ignored local artifacts; the deployment and probe SQL are committed.

`uv run --project packages/python --frozen pytest tools/tests/test_check_postgres.py -q` passed all 17 tests; `python3 tools/check_seal.py` verified all 16 sealed files. The native package sources and initial migration bytes are unchanged. These results are local preparation, not hosted security or native TLS evidence.


## Hosted Supabase checkpoint: 20 October 2026

Current target: the user-created Cragkit project, Singapore, PostgreSQL 17.11 and UTF-8. Root used the Supabase plugin to apply the exact checksummed initial migration, private-schema hardening and `0002_portable_lexical_config.sql`. Hosted schema/integrity and nonowner security probes passed; guarded reruns retained both original checksums and application timestamps. The plugin endpoint's transactional rollback was tested before application. [Hosted evidence](../evaluation/reports/V1/V1-01-H-hosted.md), [connection and security guide](supabase.md).

The new migration resolves the stored-`regconfig` upgrade warning and four unindexed-foreign-key advisor findings using text configuration names and three covering indexes. Fixed-path casts validate configuration names when maintaining vectors. Root ran `python3 artifacts/V1/run_supabase_0002_local.py`: fresh two-migration installation, populated 0001-to-0002 vector preservation, safe reruns, rollback/drift checks, lexical configuration changes and security probes passed. The task-owned cluster stopped and its files were removed. E65/E66 record the discovered upgrade and TLS failure cases.

Final hosted advisors reported no WARN/ERROR: nine INFO notices reflect intentional default-deny RLS without policies; two performance INFO notices concern unused GIN indexes in the empty development database. These notices are retained and explained, not suppressed with broad policies or removed indexes. All eight application tables are empty after the probes; the temporary role and failure-probe schema are absent. This is scoped development evidence, not production readiness or measured retrieval performance.

Dashboard controls: mandatory database TLS enabled after its restart; unused Data API disabled and independently observed on its settings page. Private-schema access is revoked from PUBLIC and Supabase API roles, and all nine tables have RLS. Network restrictions still allow all IPs; no allowlist was invented without development-network requirements. Administrative credentials remain separate from future runtime credentials.

A PostgreSQL SSLRequest handshake from native Python to the actual direct endpoint verified the downloaded CA and hostname with TLS 1.3. A plaintext startup without a password was rejected with SQLSTATE 28000. The session-pooler handshake failed certificate verification with that CA; it was rejected and not selected. The direct endpoint is selected in an owner-readable configuration outside Git. No password has been requested in chat.

Native authenticated SQL has now passed after the approved network-ban removal; the earlier failures and final evidence are recorded below. The workspace-only helper `python3 artifacts/V1/configure_private_password.py` uses a hidden terminal prompt and writes an owner-only libpq password file outside the repository. It preserves an existing file unless the user explicitly passes `--replace`, and prints no password. The CA and nonsecret connection environment are under `~/.config/cragkit/supabase/`. After saving, load the prepared settings and run:

```sh
source ~/.config/cragkit/supabase/ksvzlzklspfghrhirogt.env
python3 tools/check_postgres.py --check --confirm-dedicated-target --integration
```

The first native execution after the user saved the credential failed with `database_check_failed`; a bounded `psql` diagnostic classified password authentication failure, without a certificate or network error. The password file has the current owner and mode `0600`. Migration-history and integration assertions did not run through that failed connection. These historical failures are superseded by the final authenticated acceptance below; another password reset is not required. This command does not apply migrations; initial hosted DDL was explicit through the plugin. Full regression rerun after the corrective migration: 172 Python/tool tests passed; `npm test` built TypeScript and passed 78 tests; all 16 sealed hashes matched. No package release, hosted CI, runtime pool adapter or live-model evaluation occurred.

The next private-save attempt changed the local password file, but direct access failed with connection refused before login. The actual session pooler passed native libpq certificate/hostname verification with the downloaded Supabase CA and then rejected password authentication. No TLS downgrade or permanent endpoint change was made; temporary credential material was removed. Those pooler failures did not establish that the new password was incorrect: Supabase documents credential caching after rotation, and the final direct connection succeeded with the saved password. The [hosted report](../evaluation/reports/V1/V1-01-H-hosted.md#acceptance-and-next-action) records these distinct failure stages.

### Final authenticated native acceptance

On 20 October, the user explicitly approved removing the listed ban for their recognized network address and making one direct check. Root completed the separate confirmation, observed the successful removal and empty ban list, then used the existing private password file in one direct libpq session with the dashboard CA and `verify-full`. TLS 1.3 and SSL true were reported under administrative `postgres`; history validation found both expected schema versions. The canonical history script, `storage/postgres/tests/invariants.sql` and `storage/postgres/tests/security.sql` all passed, with `cragkit_migration_ok` and `cragkit_security_probe_ok`. No migration was applied, and fixture data/temporary roles rolled back.

The successful command was an inline Python harness calling `tools.check_postgres.connection_environment`, `migrations`, `migration_script(..., apply=False)` and `execute` with the three SQL scripts concatenated for one connection. Its ignored result is `artifacts/V1/native-direct-after-unban.json`. The CLI command above remains the repeatable history/integration entrypoint, but it uses separate connections and was not rerun after this single-connection acceptance. V1-01 is COMPLETE; V1-02 Python connection lifecycle is READY and unstarted. Native package sources, contracts, dependency locks, migration bytes and sealed evaluation inputs were unchanged; product regression suites were not rerun for this documentation/configuration acceptance.

Supabase's [rotation guidance](https://supabase.com/docs/guides/troubleshooting/supavisor-error-password-authentication-failed-after-password-rotation) explains why a pooler can reject a correct newly rotated password. That possibility was initially missed; the exact cache contribution here was not established. The successful direct login proves the saved password works now. No further reset is required. No local service, installation, live model or runtime pool adapter was introduced.

## V1-02A: Optional Python pool resources

The internal `cragkit._postgres_pool` module now provides `PoolConfig`, `parse_pool_config` and `PoolResource`. The top-level package and public request/result contracts are unchanged. The optional driver loads only when opening an owned resource; construction/configuration performs no network or private-file access. Owned startup validates the configured CA file and owner-only regular password file. It rejects populated `PG*` environment values so hidden libpq settings cannot override the scalar configuration. Borrowed pools stay caller-owned and are never opened, reconfigured or closed by the wrapper.

All operations for a resource belong to one event loop. A lease's absolute `loop.time()` deadline bounds acquisition. It does not yet enforce the yielded body's deadline, begin a scoped transaction or set a statement timeout; V1-02B supplies those policies. Raw leases require caller-managed transactions. Closing the wrapper rejects new work, cancels its own active/queued requests and uses a shared bounded close budget; unrelated caller leases survive. Driver failures return fixed errors without raw driver text. A configured acquisition timeout maps to `ProviderUnavailable`; expiration of the request's acquisition deadline maps to `DeadlineExceeded`.

For example, an internal caller acquires and returns a connection as follows after explicit resource startup:

```python
loop = asyncio.get_running_loop()
async with resource.lease(deadline=loop.time() + 1.0) as connection:
    # The future store adapter will bind scope and perform a bounded transaction.
    pass
await resource.close()
```

Commands actually run on the final source:

```sh
uv sync --project packages/python --frozen --extra postgres
uv run --project packages/python --frozen pytest packages/python/tests/test_postgres_pool.py -q
uv run --project packages/python --frozen --extra postgres python artifacts/V1/check_pool_resources.py
uv sync --project packages/python --frozen
uv run --project packages/python --frozen pytest packages/python/tests tools/tests -q
uv run --project packages/python --frozen mypy --config-file packages/python/pyproject.toml packages/python/src
python3 tools/check_seal.py
```

Results: 27 focused cases; 199 combined Python/tool cases in the default environment without optional drivers; strict typing passed for seven source files; 16 sealed hashes matched. The workspace-only hosted harness passed on the established direct connection with `verify-full` and TLS 1.3. It demonstrated owned reuse, acquisition deadline/saturation/cancellation, owned shutdown, borrowed-pool preservation and an unrelated caller lease remaining usable. It used fixed SELECTs and explicit caller transactions, changed no application/schema/role/policy data, closed every task-owned pool and used at most two connections. The ignored harness and sanitized result are local evidence, not integration artifacts shipped in a fresh checkout. [Detailed evidence and limits](../evaluation/reports/V1/V1-02A.md).

No manifests/locks, public schemas, migrations, TypeScript or approved corpus changed. No TypeScript/artifact/hosted-CI/live-model run occurred for this child. V1-02A is complete; parent V1-02 remains incomplete until V1-02B schema/capability, transaction scope, statement budgets and runtime-role checks pass. Failure case: a connection returned just after its acquisition deadline must be returned without entering the caller body, even if the event-loop timeout callback has not run yet.

## V1-02B: Scoped Python sessions

`cragkit._postgres_session.PostgresSession` builds on the internal pool resource. Construct it once around an explicitly opened `PoolResource`. `validate(deadline=...)` checks the leased runtime connection's role, UTF-8/native FTS support, table/column types, RLS flags, absence of security-definer routines and exact migration history. These are compatibility checks, not proof against an administrator changing the database. Migrations remain explicit and separate.

For example, trusted application code can run the bounded identifier probe:

```python
adapter = PostgresSession(resource)
loop = asyncio.get_running_loop()
await adapter.validate(deadline=loop.time() + 5.0)
async with adapter.transaction(request, scope=trusted_scope,
                               deadline=loop.time() + 5.0) as session:
    identifiers = await session.visible_documents(limit=20)
```

This probe returns published ready document/revision identifiers. It does not rank evidence, load source text or implement `SearchStore`. Its filter capability is string `document_id`/`revision_id` with `eq`, `ne`, `in`, `and`, `or` and `not`. Valid but unsupported fields, numeric comparisons or scalar types fail with `UnsupportedCapability` before SQL. Values remain parameters; column names and operators come from fixed code. All predicates are combined with tenant, collection, tombstone, authorization revision and principal/grant checks before the result limit.

Every transaction checks the actual leased database role. Administrative, owner, bypass, write-capable and owner-member roles are rejected. The runtime needs narrowly granted reads and application-managed RLS policies, including read access to the migration ledger; the dedicated development deployment's default deny state is preserved outside the explicit temporary acceptance fixture. Borrowed pools retain caller ownership and transport configuration. The caller must provide idle compatible psycopg connections and configure their TLS verification; the session layer validates the actual database role for borrowed and owned connections alike.

Transactions are read-only at repeatable-read isolation, with a fixed search path and transaction-local tenant/principal/authorization/grant settings. The effective deadline is the earlier of the supplied absolute loop deadline and request limit. Each statement uses the remaining budget, and the Python timeout also bounds caller body awaits. Cleanup rolls back even on success, with a separate bounded release budget; an uncertain begin or failed rollback discards the connection. Cooperative cancellation is required of caller code and drivers. Scoped handles cannot be used after exit or from a different task.

Final verification passed; see [the task report](../evaluation/reports/V1/V1-02B.md). A failure case is a pooled connection retaining tenant A's session settings when tenant B reuses it. Transaction-local context plus rollback prevents that carryover; fixed query predicates provide a separate scope boundary. Exercise: trace acquire, begin, validate, bind, query, rollback and release, and explain why a valid `TrustedScope` object does not authenticate its caller.


Verified final commands from the root:

```sh
uv sync --project packages/python --frozen --extra postgres
uv run --project packages/python --frozen --extra postgres pytest packages/python/tests/test_postgres_pool.py packages/python/tests/test_postgres_session.py -q
uv run --project packages/python --frozen --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/supabase/python-runtime-check.json" --allow-test-writes
uv sync --project packages/python --frozen
uv run --project packages/python --frozen pytest packages/python/tests tools/tests -q
uv run --project packages/python --frozen mypy --config-file packages/python/pyproject.toml packages/python/src
python3 tools/check_seal.py
```

Results: 66 focused and 238 combined cases passed; strict typing passed for nine source files without optional drivers; 16 sealed hashes matched. Final hosted runtime-role, same-connection tenant reuse, principal/grant/revision and literal-filter checks, observed blocked-query timeout/cancellation, unsafe-administrator rejection and schema rejection/restoration passed. The harness verified complete fixture/role/policy cleanup. Final administrative history, invariants and security probes also passed in one native session. A fresh V1-02A hosted lifecycle smoke run passed separately; its ignored harness remains workspace-only evidence.

The committed harness requires an owner-only regular JSON configuration file containing scalar `PoolConfig` fields. Use absolute strings for `sslrootcert` and `passfile`; the latter points to the existing private libpq password file. Never put a password or connection URI in that JSON or the repository. The tested configuration used maximum pool size one, one waiter, startup five seconds, acquisition one second, close three seconds and release one second. The harness forces runtime pool size one, uses a temporary SCRAM-authenticated LOGIN role with a ten-minute expiry and one-connection limit, and permits at most two native client connections. It refuses without the test-write flag, nonempty application tables or preexisting Cragkit policies. Run it only against an unused dedicated development target: it temporarily renames a schema column to verify incompatibility rejection. It takes the migration advisory lock and restores the schema, revokes its exact grants, removes synthetic rows/policies and drops the role in bounded cleanup. Its total request-work timeout is 90 seconds and final cleanup has a separate 25-second budget. Hard process termination can interrupt cleanup; a reported cleanup failure requires inspection before another run.

An initial cleanup failure exposed the distinction between `CREATEROLE` and permission to `DROP OWNED BY`; exact revokes fixed it without broader privileges. One intermediate run returned a safe `ProviderUnavailable`; traced and canonical follow-ups passed, and the cause was not established. Driver-source inspection independently led to an IDLE check after rollback because transaction exit can suppress errors. These findings and their scope are preserved in the report. No permanent application runtime role or positive RLS policies remain configured; the acceptance role was temporary. V1-02 is complete; V1-03 is next.


## V1-03: Native Node connection lifecycle

The internal `postgres-pool` and `postgres-session` modules provide the equivalent optional Node lifecycle. `PoolResource.withLease({deadline, signal}, callback)` and `PostgresSession.transaction(request, {scope, deadline, signal}, callback)` use absolute seconds from exported `now()`. Always await closure; borrowed pools remain caller-owned. The supported filter subset and runtime-role/schema requirements match Python. `pg` 8.23.1 is an optional peer and exact development dependency; root import remains side-effect free.

The committed Python fixture owner now accepts `--typescript` and launches the Node child against the same temporary role/rows. It coordinates observed lock waits and schema rejection through a fixed message protocol, then restores/revokes/removes its own fixture. Never run this test against an occupied database. [Full verified commands and results](../evaluation/reports/V1/V1-03.md): 58 focused/136 full Node tests, 238 Python/tool regressions, both typechecks, 66 shared cases, four schemas and 16 sealed hashes passed. Native runtime-role, borrowed pool, scope reuse, deadline/abort and cleanup checks passed. No permanent application policy/login was added.


## V1-04: Canonical text and chunks

Native `canonicalize` functions preserve original-source and canonical hashes and return immutable chunks with UTF-8 byte spans. Newline/BOM rules, structural scope, byte and optional declared-token limits are recorded in [V1-04 evidence](../evaluation/reports/V1/V1-04.md). The shared 23-case oracle is separate from the approved retrieval corpus. Verified focused commands: `uv run --project packages/python --frozen pytest packages/python/tests/test_canonical.py -q` (52 cases), Python strict mypy (ten files), and TypeScript typecheck/build plus `node --test --test-concurrency=1 tests/canonical.test.mjs` (72 cases). No database or model is needed. Byte mode makes no hard model-token claim; token mode requires an explicit synchronous caller counter and identity.

## V1-05 Python staged ingestion

`cragkit.ingestion.PostgresIndexer(resource, authorize_write=application_write_authorizer)` binds an asynchronous application write policy outside editable ingestion input. Every ingest/replay requires exact `True`; trusted read grants alone do not authorize a write. Use an absolute event-loop deadline and a stable intent ID; existing-document updates require the expected active generation. Replaying the identical payload returns the original receipt without republishing it.

Verified commands/results and the exact hash contract are in [V1-05 evidence](../evaluation/reports/V1/V1-05.md): 37 focused/327 combined Python-tool cases, strict typing for 11 files and 16 sealed hashes passed. The explicit native fixture command accepts `--ingestion` with `--allow-test-writes`; use only the verified dedicated empty target and private configuration. Its final eight hosted groups and complete cleanup passed with at most two native clients. A failed COMMIT acknowledgement has an uncertain server outcome; retry the same intent rather than assuming nothing published. TypeScript parity, retrieval/source release and deletion remain subsequent V1 tasks.

## V1-06 native ingestion parity and V1-C2

Native Node ingestion uses `PostgresIndexer(resource, authorize_write)` with the same payload/revision/generation identity as Python. It snapshots mutable caller bytes/options/metadata, accepts a monotonic deadline plus AbortSignal, and discards an aborted or uncertain-commit lease. Every call, including replay, requires separately bound application write permission. Both runtimes require a successful ready-transition row before publishing the active pointer.

Run the existing native fixture command with `--ingestion --typescript --allow-test-writes` and the private configuration to check both write/read directions. The parent closes each runtime pool before opening the other; no Python service or administrator credential is required by the Node package. [V1-06/C2 evidence](../evaluation/reports/V1/V1-06.md) records 58 Node/39 Python focused cases, 266 Node/329 Python-tool regressions, both typechecks/build, 66 shared wire cases, four schemas, 16 sealed hashes and 14 hosted groups. The temporary restrictive-policy cleanup failure was repaired and the full run then passed. Scoped lexical retrieval/source assembly remains V1-07/V1-08.

## V1-H1 PostgreSQL adapter hardening

Read/write adapters map SQLSTATE class 23 constraint failures to IntegrityViolation. Read adapters reject NUL in the query, collection, trusted scope and supported identifier-filter values before leasing; ingestion already rejects those inputs. H1 retained the backend-neutral request/scope schemas; NUL-r1 now rejects NUL in public input identities, queries, collections, hints and string filters, while preserving exact evidence text. [H1 evidence](../evaluation/reports/V1/V1-H1.md) records 97 Python/135 Node focused cases, 348 Python-tool/285 full Node regressions, both typechecks/build, 66 wire cases and 16 sealed hashes. These checks used fake drivers and no hosted database.

## V1-07 scoped lexical candidates

`ScopedSession.lexical_candidates` in each native session returns immutable candidate IDs, byte offsets, text digests and native FTS ranks from active ready generations. Scope/grants/revision/tombstone predicates and supported required filters run before candidate LIMIT; ties use explicit C collation and chunk ordinal. Native FTS is not BM25, and candidate ranks do not estimate semantic coverage. Source excerpts and typed results remain V1-08.

Use the existing private-config fixture command with `--lexical --allow-test-writes` for combined ingestion and both native read-only lexical checks. [V1-07 evidence](../evaluation/reports/V1/V1-07.md) records 62 Python/87 Node focused checks, 357 Python-tool/300 Node regressions, both typechecks/build, 66 wire cases, four schemas, 16 sealed hashes and 19 hosted groups. PostgreSQL bigint offsets arrive as strings in Node and are converted only when exact safe integers. The final fixture and independent plugin cleanup checks passed.

## V1-08 verified source spans and typed results

Internal Python/Node `PostgresRetriever(resource)` performs scoped candidate selection followed by a fresh authorized source snapshot and exact canonical UTF-8 digest/span verification. It returns the existing typed result: partial for emitted lexical evidence, insufficient otherwise, always coverage_unknown with no facet assessor. Context is compact JSON of emitted evidence; counting is explicitly estimated. Strict counting and unsupported renderer/tokenizer declarations fail before leasing. [E-r1](../contracts/RETRIEVAL_V1.md) records behavior and bounds.

Verified commands and limitations are in [V1-08 evidence](../evaluation/reports/V1/V1-08.md): 50 Python/63 Node focused cases, 407 Python/tool/363 Node regressions, both typechecks/build, 66 wire cases, four schemas, 16 sealed hashes and 24 hosted groups passed. Use the existing private-config native command with `--results --allow-test-writes` for combined acceptance. Both actual runtime logins refused a stored span corruption; source denial and exact typed-result parity passed. The span trigger and fixture state were restored and independently checked. Provider usage zeros describe model calls/spend; infrastructure cost is unmeasured.

## V1-09 lifecycle and retention

Internal Python/Node `PostgresLifecycle` binds an application lifecycle authorizer for tombstone and purge operations. The expected active generation is required, including an explicit null for a purged marker. Tombstone blocks fresh retrieval snapshots while retaining source content until the owner explicitly purges it. Purge uses a separate restricted role with DELETE/INSERT and column-level UPDATE(created_at) on documents, no direct child DELETE, and compatible RLS. The collection, document identity, authorization revision and original creation time remain as a minimal tombstone; external backup/cache/log erasure remains the caller's responsibility. [L-r1](../contracts/LIFECYCLE_V1.md) defines retention, receipt semantics, compatibility checks and uncertain-commit limitations.

The opt-in native fixture adds `--lifecycle --allow-test-writes` to the existing private-config command. It includes the previous source/result checks, then serial Python/Node controlled update ordering, interrupted publication, tombstone visibility, failed marker reinsertion and hidden-child cascade probes. The fixture owns an otherwise empty dedicated development target, temporary role/policies and synthetic rows. Runtime pools close before switching language or permissions. The outer lifecycle budget is 600 seconds, each Node lifecycle child is limited to 90 seconds, and the existing separate cleanup bound is 25 seconds. It permits at most two native client connections including the administrator. No administrator credential reaches Node. See [V1-09 evidence](../evaluation/reports/V1/V1-09.md) for actual results and limitations.

## V1 public PostgreSQL entry points and installed demos

Python applications can import `PoolResource`, `PostgresIndexer`, `PostgresLifecycle` and `PostgresRetriever` from `cragkit.postgres`; Node applications use `cragkit/postgres`. Importing these modules does not open a connection. Install the Python `postgres` extra or the optional Node `pg` driver before opening a resource. Existing ingestion, lifecycle and retrieval contracts still apply.

The [Python example](../examples/postgres.py) and [Node example](../examples/postgres.mjs) accept an owner-only regular JSON runtime configuration file and a JSON input containing `request` and `scope`. The application must derive scope from its own authorization before invoking the example; an agent or untrusted client must not choose it. Use an absolute private configuration path outside the repo, with mode 0600 and the verified CA/password-file configuration described above. Run from an environment where the candidate package and its optional driver are installed:

```sh
python examples/postgres.py "$PRIVATE_CONFIG" "$AUTHORIZED_INPUT"
node examples/postgres.mjs "$PRIVATE_CONFIG" "$AUTHORIZED_INPUT"
```

Run the commands sequentially against already provisioned application data and policies. Each example emits a typed result, enforces a 20-second deadline and closes its pool. A denied scope yields no evidence. Lexical evidence retains unknown coverage and estimated context accounting. These examples perform queries; the installed acceptance runner supplies synthetic ingestion and lifecycle fixtures.

To rebuild and check the local wheel, source distribution, rebuilt wheel and npm tarball, including installed examples against an isolated empty development database:

```sh
python3 tools/check_artifacts.py --output-dir artifacts/V1/V1-12-installed --postgres-config "$PRIVATE_CONFIG" --allow-test-writes
```

Omit both hosted flags for driver-free artifact/import acceptance alone. The hosted option creates temporary runtime roles, scoped policies and synthetic rows, then checks cleanup. Never target application data. It limits native clients to two including the administrator and closes one runtime pool before starting the other. Installed examples are copied outside the source checkout and compared with expected authorized and denied results. Raw observations remain under ignored artifacts. [Final V1 evidence](../evaluation/reports/V1/V1-10-12.md) records commands, measurements, complete checkpoint results and their limits.


## V2-02 Python embedding boundary

`cragkit.embeddings` supplies `EmbeddingAdapter`, immutable `EmbeddingProfile`, `EmbeddingLimits`, `EmbeddingPolicy` and result/usage models. [E-r1](../contracts/EMBEDDINGS_V2.md) specifies the two supported profiles, callback signatures, bounds and errors. [ADR 0001](decisions/0001-embedding-profile.md) selects hosted OpenAI as opt-in; routine development uses the distinct fake identity. Core imports are unchanged.

The application injects a caller-owned async `EmbeddingTransport` and matching `TokenCounter`. No HTTP client, SDK, token assets, credentials or network connection is created automatically. For a configured live transport, the application owns TLS, endpoint/redirect policy, bounded streaming reads, timeouts, disabled internal retries and cooperative cancellation. Blocking/noncooperative callbacks cannot be sandboxed by the adapter. The standalone adapter does not authorize source release or perform retrieval; the application must authorize text before disclosure.

For example, after constructing those callbacks, a fake-profile call is:

```python
import asyncio
from cragkit.embeddings import EmbeddingAdapter, FAKE_PROFILE

adapter = EmbeddingAdapter(application_transport, token_counter, profile=FAKE_PROFILE)
batch = await adapter.embed_query(
    "restart the service", deadline=asyncio.get_running_loop().time() + 5,
)
vector = batch.vectors[0]
```

This is an application integration sketch: `application_transport` and `token_counter` are injected values. The fake counter must identify itself as `fake-byte-v1`; a real-profile counter must declare `cl100k_base` and count accurately. Query and batch calls share one path. Batches over an item, UTF-8 byte or token bound fail before dispatch; the adapter does not split or truncate them. One operation may be in flight per instance, with no waiting queue and no retries. Injected resources stay caller-owned.

Default live policy is disabled with zero allowance. Selecting `OPENAI_PROFILE` alone cannot enable dispatch: explicit live policy, known positive configured price and sufficient per-operation allowance are also required. Per-operation cost gating is estimated from trusted counts/configured price, not a provider-wide billing guarantee. Missing live usage/cost remains unknown. A failed or cancelled dispatched call can still be charged. Mocked OpenAI response checks do not establish real compatibility or actual billing.

Verified root commands:

```sh
uv run --project packages/python --frozen pytest packages/python/tests/test_embeddings.py -q
uv run --project packages/python --frozen mypy --config-file packages/python/pyproject.toml packages/python/src
uv run --project packages/python --frozen pytest packages/python/tests tools/tests -q
```

The final [V2-02 report](../evaluation/reports/V2/V2-02.md) records actual results, privacy/accounting regressions and limits. No live API/model check ran. TypeScript parity is the next task.


## V2-03 native embedding parity and V2-C1

Node applications can import `EmbeddingAdapter`, `FAKE_PROFILE`, `OPENAI_PROFILE`, strict Zod schemas and corresponding types from `cragkit/embeddings`. Python uses `cragkit.embeddings`. [E-r1](../contracts/EMBEDDINGS_V2.md) includes the Node callback and abort/deadline mapping. Both adapters inject caller-owned asynchronous transport and token counting; neither bundles a concrete HTTP client or model runtime. The caller binds provider, endpoint, input permissions and cost policy outside agent-editable input.

After supplying the callbacks, a Node fake query is:

```typescript
import { EmbeddingAdapter, FAKE_PROFILE } from 'cragkit/embeddings';
const adapter = new EmbeddingAdapter(applicationTransport, tokenCounter, {profile: FAKE_PROFILE});
const batch = await adapter.embed_query('restart the service', {
  deadline: performance.now() / 1000 + 5,
  signal: abortController.signal,
});
```

This sketch uses application-owned callbacks and an optional caller abort controller. Transport receives a task-owned signal; it must settle promptly on cancellation. Inputs and result vectors are copied, results/configuration are frozen, and overlapping calls fail without an unbounded queue. Core imports remain independent of provider/model packages.

Run the focused Node checks after building, then the shared checker from the root:

```sh
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/embeddings.test.mjs
uv run --project packages/python --frozen python tools/check_embeddings.py
python3 tools/check_core_pipeline.py --artifacts-dir artifacts/V2/V2-C1-final
```

The full profile now includes embedding parity and clean artifacts with both optional embedding entry points. It runs serially and may access registries for frozen dependency setup. [V2-03/V2-C1 evidence](../evaluation/reports/V2/V2-03-C1.md) records 41 shared synthetic cases and final local results. These checks do not call OpenAI or establish semantic quality/billing. Both runtimes explicitly reject excessive response depth/numeric-token length, duplicate keys, floating-point index/usage tokens and malformed vectors. Vector storage and reindex are next under V2-04.


## V2-04A: Explicit vector setup

The administrative setup is independent of lexical migration history. On the accepted dedicated Neon development target, use the explicit managed primitive profile described in the [storage contract](../storage/postgres/README.md#explicit-neon-managed-primitive-profile). Credentials remain in the private configuration outside Git.

```sh
uv run --project packages/python --frozen --no-sync --extra postgres pytest tools/tests/test_check_postgres.py tools/tests/test_check_neon_postgres.py -q
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_neon_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --confirm-dedicated-target --apply --install-vector --allow-managed-vector-primitives --harden --integration --security --allow-test-writes
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_neon_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --confirm-dedicated-target --check --vector --allow-managed-vector-primitives --security --allow-test-writes
```

The install command and its unchanged rerun passed. The check command is read-only for vector setup; the separately requested security probe performs rolled-back synthetic writes. Optional drivers were already installed, so these invocations used `--no-sync`. The native wrapper has a 120-second overall bound; generic psql tooling retains its 120-second bound per subprocess, with SQL statement/lock bounds. No installation happens without `--install-vector`; `--apply` alone stays lexical-only. [Results and limitations](../evaluation/reports/V2/V2-04A.md).


## V2-04B: Optional vector profile storage

After explicit A setup, --vector-storage applies/checks the next numbered setup artifact without changing lexical migration history. Verified install/rerun with existing optional drivers:

```sh
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_neon_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --confirm-dedicated-target --apply --vector-storage --allow-managed-vector-primitives --harden --integration --security --allow-test-writes
```

The vector SQL probes roll back all synthetic rows. [B/B1 results](../evaluation/reports/V2/V2-04B.md). The new profile table is synthetic-only; hosted profile provisioning and dense ranking are not implied.


## V2-04 native generation checks

The --vectors fixture uses a temporary restricted LOGIN, explicit managed-primitive schema USAGE and scoped table policies, and cleans up after the run. Use only the accepted empty dedicated development target.

```sh
uv run --project packages/python --frozen --no-sync --extra postgres pytest packages/python/tests/test_vector_ingestion.py -q
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --vectors
```

[Staging evidence](../evaluation/reports/V2/V2-04C.md); publication and Node acceptance are recorded separately as their slices complete.


Node staging checkpoint (V2-04E) uses the same fixture with explicit --typescript --vector-stage-only. This excludes F publication probes until F is implemented; the final --vectors --typescript command requires full publication. The owner/child pipe is local and restricted to fixture permission/readiness operations; it sends no administrative credentials to Node. [E evidence](../evaluation/reports/V2/V2-04E.md).


## V2-04 vector publication and integrated acceptance

Both optional PostgreSQL entry points now export `PostgresVectorIndexer`: Python uses `cragkit.postgres`, Node uses `cragkit/postgres`. Applications inject the restricted pool, trusted write authorizer and E-r1 adapter. [VG-r1](../contracts/VECTOR_GENERATIONS_V2.md) defines stage/publish/ingest, profile identity, bounded resume and receipts. Only the distinct synthetic fake profile is provisioned; OpenAI storage requires a later explicit provisioning decision. No API call is needed for routine verification.

For example, stage G2 while G1 stays active, then publish with G1 as the expected pointer. Publication checks the full immutable manifest, exact profile, counts and current authorization before an atomic pointer update. A missing vector or stale expected pointer leaves the active generation unchanged. Replaying an older succeeded job cannot restore its pointer or revoked access.

Run from the root, one command at a time:

```sh
npm --prefix packages/typescript run build
uv run --project packages/python --frozen --no-sync --extra postgres pytest packages/python/tests/test_vector_ingestion.py packages/python/tests/test_vector_publication.py -q
node --test --test-concurrency=1 packages/typescript/tests/vector-ingestion.test.mjs packages/typescript/tests/vector-publication.test.mjs
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_vector_contract.py
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --vectors --typescript
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --lifecycle
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_neon_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --confirm-dedicated-target --check --vector-storage --allow-managed-vector-primitives --integration --security --allow-test-writes
python3 tools/check_core_pipeline.py --artifacts-dir artifacts/V2/V2-04-final
```

Run native checks before the final checkpoint: its frozen default Python installation removes optional drivers. Restore only the locked postgres extra when needed. Native fixtures require the accepted empty dedicated development target, verified TLS and private owner-only configuration outside Git. They use synthetic documents, temporary restricted roles/policies and at most two clients including the owner. Owner RPC actions are fixed fixture operations; no administrative credentials reach Node.

The serial checkpoint adds vector SQL/setup/identity parity and guarded installed vector imports to the existing checks. Its fixture-definition count is a manifest check; executable unit and native tests establish the listed failure behavior. [Final V2-04 evidence](../evaluation/reports/V2/V2-04G.md) separates those results. Fake vectors validate mechanics, not semantic model quality. Dense search remains V2-05. Exercise: explain which pointer survives an incomplete G2 build and a delayed G2 publication after G3 wins.


## V2-05 scoped exact dense adapter

For example, a query vector along the first axis ranks the same direction before an orthogonal or opposite vector. The native scoped handle now adds dense_candidates with an E-r1 single-vector batch, returning cosine distance (smaller is better), exact profile identity and source keys. [DN-r1](../contracts/DENSE_V2.md) describes the input, scope and score contract. This is the internal candidate adapter for later fusion/orchestration; the public V1 PostgresRetriever remains lexical.

Obtain and authorize the query embedding before opening the read transaction. The dense method calls no provider. It validates batch/profile/catalog, searches only the authorized active ready generations and applies required filters before distance ranking and LIMIT. Lexical and dense reads share the current repeatable-read snapshot. Fetch source in a fresh scoped transaction to enforce current grants/tombstones; authorized retained immutable source may be stale after publication. An invalid profile fails explicitly, and a missing vector capability cannot disable lexical-only reads.

From the root, run one command at a time:

```sh
uv sync --project packages/python --frozen --extra postgres
uv run --project packages/python --frozen --no-sync --extra postgres pytest packages/python/tests/test_dense.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/dense.test.mjs
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_dense_contract.py
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --dense --typescript
python3 tools/check_core_pipeline.py --artifacts-dir artifacts/V2/V2-05-final
```

The explicit dense native fixture provisions only temporary restricted roles/policies and synthetic records on the accepted empty dedicated target. It reuses the optional profile/setup grants, holds at most two native clients including the owner, closes Python before Node and accepts only fixed local owner actions. No administrator credential reaches the child. Do native checks before the final frozen default checkpoint removes optional Python drivers; restore only the locked postgres extra if needed.

The 15-stage serial checkpoint adds canonical SQL and seven shared mathematical reference cases. Those reference cases validate geometry and SQL parity; the native fixture executes the real ranking in both runtimes. Exact search scans the authorized filtered set and has no HNSW/IVFFlat index or measured large-corpus performance guarantee. Fake-vector ordering is not model-quality evidence. [V2-05 report](../evaluation/reports/V2/V2-05.md) records actual results and limitations. Exercise: with limit one, explain why a required document filter must run before choosing the closest vector.

## V2-06 exact identifiers and rank fusion

For example, `ERR_CONN-42` is one exact, case-sensitive identifier even when FTS splits punctuation. The internal scoped handle adds `identifier_candidates`; both native ingestion paths populate the existing identifier array. [IF-r1](../contracts/IDENTIFIER_FUSION_V2.md) specifies the ASCII heuristic, strict query shape, scoped SQL and weighted reciprocal rank fusion. Old immutable generations are not backfilled: use a new ingestion intent to populate their tokens.

Pure fusion uses distinct ranks, keeps raw scores as provenance, normalizes family weights per facet and retains each family's best rank across attempts. With equal dense/lexical weights, rank 1 in both lists scores `1/61`; rank 1 in only one scores `0.5/61`. Duplicate entries cannot add votes. A union above the declared global ceiling fails explicitly; V2-07 will budget branch fan-out before fusion. Positive votes that underflow to zero also fail. These are ranking values, not relevance probabilities.

Run from the root, serially:

```sh
uv run --project packages/python --frozen --no-sync pytest packages/python/tests/test_fusion.py packages/python/tests/test_postgres_identifiers.py tools/tests/test_check_identifier_fusion.py tools/tests/test_check_core_pipeline.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/fusion.test.mjs packages/typescript/tests/postgres-identifiers.test.mjs
uv run --project packages/python --frozen --no-sync python tools/check_identifier_fusion.py
uv sync --project packages/python --frozen --extra postgres
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --dense --typescript
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --vectors --typescript
python3 tools/check_core_pipeline.py --artifacts-dir artifacts/V2/V2-06-final
```

The dense native fixture now includes actual identifier storage/search, scope and filters before limits, grant-only access, source revocation/tombstones, common snapshots and actual three-branch fusion arithmetic in both runtimes. The vector fixture separately asserts that Node lexical and vector writers populate exact arrays. They use only synthetic data, restricted temporary roles, fixed owner actions and at most two database clients; their Node children receive restricted configuration only. The base legacy fixture has a separate administrator-negative check design under security follow-up; do not generalize these children's credential boundary to every harness.

The serial checkpoint has 16 stages, including actual extraction/fusion/provenance parity. Native checks run before its default frozen install removes optional Python drivers. [The V2-06 report](../evaluation/reports/V2/V2-06.md) records results and limitations. Public `PostgresRetriever` stays lexical until V2-07. Optional exercise: add a repeated family list to the three-document shared fixture and predict which ranks change without gaining an extra vote.

## V2-07 hybrid orchestration and V2-08 evaluation

For example, a dense SQL failure raises by default. With trusted `allow_degraded=True` in Python or `allow_degraded: true` in Node, hybrid mode can roll back the failed branch to a savepoint, search the remaining branches in the same snapshot and return `execution: degraded`. An authorization error, deadline, corrupt source or broken savepoint remains fatal.

The optional PostgreSQL `PostgresRetriever` now accepts trusted constructor configuration for `mode` (`lexical`, `dense`, `hybrid`), `embedder`, `allow_degraded` and `identifiers`. The default remains lexical. Dense/hybrid require a configured `EmbeddingAdapter` under the provisioned synthetic profile; no adapter is created implicitly. [HY-r1](../contracts/HYBRID_V2.md) defines validation, invocation accounting, branch budgets, diagnostics and source reauthorization. Node exports the `RetrieverOptions` type from `cragkit/postgres`. Call the existing retrieve method with a separately bound trusted scope and absolute deadline.

Dense/hybrid reserve one embedding boundary invocation before a candidate lease. They run one original query/attempt, at most three serial branch families, at most 40 candidates per branch and a global ceiling of min(request limit,200). Tiny hybrid ceilings below the planned family count fail before provider/DB work. Budgets are divided before execution; failures cannot gain retries or expand the surviving branches. Only an explicitly enabled hybrid policy recovers `ProviderUnavailable`/`UnsupportedCapability` from individual branches or embedding. Source release always uses a fresh scoped transaction.

Run the following from the repository root, one command at a time:

```sh
uv run --project packages/python --frozen --no-sync pytest packages/python/tests/test_hybrid.py packages/python/tests/test_hybrid_savepoint.py packages/python/tests/test_role_guards.py tools/tests/test_dense_metrics.py tools/tests/test_check_hybrid_contract.py tools/tests/test_check_python_postgres.py tools/tests/test_check_core_pipeline.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/hybrid.test.mjs packages/typescript/tests/hybrid-savepoint.test.mjs packages/typescript/tests/role-guards.test.mjs
uv run --project packages/python --frozen --no-sync python tools/check_hybrid_contract.py
uv sync --project packages/python --frozen --extra postgres
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --hybrid --typescript
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --typescript
python3 tools/check_core_pipeline.py --artifacts-dir artifacts/V2/V2-exit
```

The explicit hybrid native command includes the V2-08 development ablation: nine approved document revisions, six question IDs frozen in the shared fixture before measurement, three modes and 18 requests per runtime. It reads no held-out labels. Python and Node compare full results after timing normalization; the label-blind hash encoder is a synthetic mechanics baseline. Historical logical revision filters map to generated physical IDs without changing labels. Active-generation candidate search intentionally misses a historical-only target; the report retains that regression. [Evaluation protocol](../evaluation/protocol.md#v2-development-ablation) and [V2 exit report](../evaluation/reports/V2/V2-07-08-exit.md).

V2 exit also removes administrator configuration from the legacy Node child. The Python parent tests its existing administrator connection against the runtime guard; the child receives restricted configuration only. Reader/writer guards in both runtimes now reject direct/transitive membership in the five declared broad-data/server roles, regardless of INHERIT. No dangerous role is granted for testing. This is an explicit credential-handling fix, not an OS sandbox between processes running as the same user.

The local checkpoint now has 17 serial stages, including public hybrid boundary and synthetic encoder parity. Native checks use a temporary restricted role, fixed local owner actions and at most two clients; run them before the default frozen checkpoint removes optional drivers. No live model or registry publication is part of this command. Optional exercise: explain why a failed SQL statement needs a savepoint rollback, then predict whether identifier fusion will rank the retry policy above a cache policy that also mentions `ERR-17`.


## V3 bounded reranker checks

The optional Python `cragkit.reranking` and Node `cragkit/reranking` modules expose the [RK-r2 boundary](../contracts/RERANKER_V3.md). They accept caller-owned asynchronous transports; no model, destination or credential is discovered at import. This adapter is not yet wired into PostgresRetriever. Real-model selection/comparison remains a V3-02 acceptance gate.

Verified from the repository root:

```sh
uv run --project packages/python --frozen --no-sync pytest packages/python/tests/test_reranking.py -q
uv run --project packages/python --frozen --no-sync mypy packages/python/src/cragkit
npm --prefix packages/typescript run typecheck
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/reranking.test.mjs
uv run --project packages/python --frozen --no-sync python tools/check_reranking.py
python3 tools/check_core_pipeline.py --artifacts-dir artifacts/V3/V3-02/final
```

Focused results: 26 Python tests and eight Node tests. The final checkpoint passed 18 stages, 870 Python/tool tests, 701 Node tests, 11 shared recorded adapter cases and four clean artifacts with three guarded installed import samples. Default installations imported the reranker modules without database/model extras or external I/O. These are native/synthetic checks; no real-model inference or relevance quality was evaluated. [Evidence and remaining gate](../evaluation/reports/V3/V3-02.md).


## Cohere live probe and private credential entry

For the selected hosted reranker, save a **Cohere** API key through the hidden prompt:

```sh
python3 tools/save_cohere_key.py
```

The helper atomically creates/replaces `$HOME/.config/cragkit/cohere/api-key` outside Git, with owner-only file permissions 0600 and directory 0700. Do not paste keys into chat, shell arguments, reports or fixtures. A key from OpenAI or another provider does not authenticate to Cohere. An invalid entry preserves the existing file; replacing the local file does not revoke a key at its provider.

The explicitly opted-in Python and Node probe tools each permit one fixed-host verified-TLS request on the existing synthetic room sample, no retries and no private corpus. They reject unsafe key-file permissions. Root runs Python first, Node only after Python succeeds; do not run both automatically after an authentication failure. Each request caps input to three short ASCII passages and response to 65,536 bytes. The pair's dated price/context admission estimate is USD 0.00393216, below its USD 0.01 budget; that estimate is not observed billing. Live output preserves unknown processed-token/truncation behavior and mutable model identity. A parent 30-second subprocess limit was used for the actual Python attempt; socket timeouts alone are not a hard wall-clock guarantee.

Two separately configured Python attempts returned 401; Node was not dispatched. The owner confirmed another provider’s key, and an offline check after the replacement confirmation still found an OpenAI-style key format. The saver and probes now reject recognizable OpenAI project/service keys before dispatch. The hidden prompt refuses echoed-input fallback. The owner retained Cohere; a valid key and successful comparison remain pending. [Attempt evidence](../evaluation/reports/V3/V3-02D-attempt.md). Never treat an authentication failure as a successful model evaluation.


The later configured [Cohere comparison](../evaluation/reports/V3/V3-02D.md) passed in Python and Node, completing V3-02. Earlier failed attempts above remain historical evidence. No more model calls are needed for routine tests.


## V3 exact context counting

For example, counting only a quotation misses the citation fields and JSON escaping. The optional [TK-r1 renderer](../contracts/TOKEN_CONTEXT_V3.md) counts the full Evidence array and a declared wrapper reserve. It is separate from the legacy PostgreSQL retrieval default until V3-06 integration.

Provision the public pinned tokenizer table explicitly, then use the focused checks:

```sh
python3 tools/fetch_tokenizer.py
uv run --project packages/python --frozen pytest packages/python/tests/test_context.py tools/tests/test_fetch_tokenizer.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/context.test.mjs
uv run --project packages/python --frozen python tools/check_context.py
```

Python applications install the optional `tokenizers` extra and call `Cl100kCounter.from_file(path)`. Node applications supply optional `tiktoken@1.0.22`, call `await Cl100kCounter.create(path)` and close the counter after use. Both factories require the same verified local asset; imports never acquire it. The development lock includes these dependencies for regression checks, while default built installations omit them. No embedding model is installed.

Strict mode counts `cragkit.context.v2` with cl100k; estimated mode reports the ceiling of UTF-8 bytes divided by four. The wrapper reserve is an allowance, not a measurement of an arbitrary downstream tool response. A too-small mandatory `[]` envelope raises `ContextBudgetTooSmall`.


## V3 extractive packing

The optional `cragkit.packing` / `cragkit/packing` module implements [PK-r1](../contracts/PACKING_V3.md). Supply authorized immutable source snapshots; the packer verifies exact bytes/digests, expands bounded structural context, merges overlaps and counts every final proposal with TK-r1. Disjoint excerpts remain separate array items. Facet selection hints do not establish semantic coverage.

```sh
uv run --project packages/python --frozen pytest packages/python/tests/test_packing.py packages/python/tests/test_source_snapshot.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/packing.test.mjs packages/typescript/tests/source-snapshot.test.mjs
uv run --project packages/python --frozen python tools/check_packing.py
```

The existing native `--results --typescript` development fixture now also captures an explicitly opted-in verified source snapshot through each restricted runtime and packs it. Credentials remain in the private configuration; use the established Neon command with `--allow-test-writes` only on the dedicated development target. Default fetch serialization does not include full source text. A snapshot is not a durable permission grant: final retrieval release must reauthorize.


## V3 curated facet assessment

The optional `cragkit.assessment` / `cragkit/assessment` modules implement [AS-r1](../contracts/ASSESSMENT_V3.md). Supply a trusted query-bound reviewed-anchor policy. `assess_evidence` uses only emitted spans; `validate_assessment` rejects malformed facets and invented references. No policy stays unknown, and a known conflict cannot disappear into sufficient coverage when only one side survives.

```sh
uv run --project packages/python --frozen pytest packages/python/tests/test_assessment.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/assessment.test.mjs
uv run --project packages/python --frozen python tools/check_assessment.py
```

Shared reviewed examples are development lookup checks, not unseen semantic quality measurements. The consuming application owns policy applicability and must include necessary qualifications in the reviewed anchor.


## V3 post-packing orchestration

The optional `cragkit.evidence` / `cragkit/evidence` entry point combines [EP-r1](../contracts/EVIDENCE_PIPELINE_V3.md) packing and reassessment. `pack_and_assess` uses only emitted spans and allows one explicitly configured rebalance. A trusted PostgreSQL constructor `evidence_options` enables this pipeline; the request must declare renderer `cragkit.context.v2`. Legacy constructor defaults retain V1/V2 behavior.

```sh
uv run --project packages/python --frozen pytest packages/python/tests/test_evidence.py packages/python/tests/test_retrieval_evidence.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/evidence.test.mjs packages/typescript/tests/retrieval-evidence.test.mjs
uv run --project packages/python --frozen python tools/check_evidence_pipeline.py
uv sync --project packages/python --frozen --extra postgres
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --hybrid --evidence --typescript
```

Constructor options are policy, counter, rebalance, surrounding_bytes, reranker, rerank_fallback and rerank_limit (1-40, default 40). Only the application binds these values. Strict requests need an issued cl100k counter and matching tokenizer identity. Optional reranking closes the first authorized source lease before dispatch and fetches fresh authorization afterward. Source reads share 16 MiB across both rounds. Token usage/live cost cannot be invented; strict live spend ceilings are unsupported at this boundary.

## V3 frozen calibration and replay

The [frozen protocol](../evaluation/policies/V3-reviewed-span-v1.json) compares the same two authorized development candidates before and after reranking. [Observed results](../evaluation/reports/V3/V3-07.md) include raw-score recordings, independent label-based false-sufficient checks and separate pre-packing/packed metrics. The five hosted calls already completed; routine work must replay them rather than redispatch.

```sh
uv run --project packages/python --frozen pytest tools/tests/test_rerank_calibration.py tools/tests/test_run_rerank_calibration.py -q
node --test --test-concurrency=1 packages/typescript/tests/calibration-replay.test.mjs
```

`tools/run_rerank_calibration.py` refuses dispatch without `--allow-live`. Its explicit baseline/output arguments select a verified native baseline and task-owned report. A new live run requires its own recorded budget/rationale; it is not part of routine acceptance. Parent-bounded serial children read the private Cohere key, retain redacted call/failure accounting and never retry automatically. Node replay takes an explicit `--replay` local public JSON payload and never accesses credentials or the network.

## V3 installed evidence release checkpoint

The artifact verifier now runs source/authorization, context, packing, coverage and bounded-rebalance fixtures using clean installed wheel/npm product modules. It first checks three default installations with optional tokenizer/database/model packages absent and external I/O denied. Then it explicitly installs pinned tokenizer extras, copies probes/examples outside the checkout, validates module provenance and compares complete native outputs. Fake source fixtures are contract checks, separate from database RLS evidence.

```sh
python3 tools/check_artifacts.py --output-dir artifacts/V3/V3-installed
python3 tools/check_artifacts.py --output-dir artifacts/V3/V3-installed-native --postgres-config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --evidence-native
```

The second command is an explicit synthetic-write check on the dedicated development target. It copies the harness, links only fixture/storage/evaluation data, and loads Python product code from the installed wheel and Node product code from the installed npm package. No checkout Python product path is available. Provenance guards fail if those paths or the Python interpreter prefix disagree. The existing least-privilege runtime child and maximum two-client boundary remain in effect. An outer 720-second bound leaves time for cleanup after the native 600-second workload limit. Temporary environments and fixture state must both report cleaned.

The examples require the optional tokenizer and explicit local asset. Copy the relevant example into the application's package environment before running it with `--tokenizer`; the artifact verifier performs that setup automatically. Python uses the tokenizers extra; Node uses tiktoken 1.0.22. Generated archives retain the internal 0.0.0 package identity; V3 is an implementation milestone, not a registry release. Hosted CI, production and cross-platform checks remain separate.


## Security remediation checkpoint

Use [the remediation ledger](../evaluation/reports/SECURITY-REMEDIATION.md) for current status; historical audit checkboxes are snapshots. Migration success alone is not deployment acceptance. After explicit host hardening, run the migration, vector (if installed), invariant and security gates together. On the dedicated Neon managed profile:

```sh
uv run --project packages/python --frozen --extra postgres python tools/check_neon_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --confirm-dedicated-target --check --vector --vector-storage --allow-managed-vector-primitives --integration --security --allow-test-writes
uv run --project packages/python --frozen --extra postgres python tools/check_security_remnants.py --config "$HOME/.config/cragkit/neon/admin-config.json" --confirm-dedicated-target --allow-test-writes --allow-managed-vector-primitives
```

The second command temporarily changes catalog security settings in transactions, requires the empty dedicated development baseline and checks exact rejection diagnostics, rollback and both history ledgers. Use one administrative run at a time. It does not grant server-file/program roles. Keep raw errors and credentials out of reports. For generic PostgreSQL, `tools/check_postgres.py --check --confirm-dedicated-target --security --allow-test-writes` runs the separate strict security gate after host-specific hardening; configure the connection as documented above.

The security gate checks effective global creator defaults and additive schema defaults. An absent global function/type ACL row implies PostgreSQL's PUBLIC default, not a denial. If it fails, review the identified creator's defaults and remediate explicitly; scoped deployment hardening does not silently change defaults in unrelated schemas. Managed Neon permits only verified extension primitives: nongrantable PUBLIC EXECUTE on cloud_admin-owned extension functions and PUBLIC USAGE on its three extension base types. PUBLIC schema/table access, ledger writes, disabled RLS and SECURITY DEFINER routines remain rejected. Omit the managed flag for strict validation.

Native ingestion/lexical fixtures require the SQL FTS behavior that matches `Café` against `Café🙂` under `pg_catalog.simple`. The parent performs a read-only check before fixture writes and returns `lexical_fixture_locale_unsupported` when it fails. UTF8 encoding alone is insufficient. Disposable local databases should use a compatible UTF-8 ctype (for example the previously tested en_US.UTF-8 or C.UTF-8); plain C can tokenize the emoji as part of the word. Production search semantics still depend on the declared PostgreSQL configuration and locale. Canonical bytes and approved corpus inputs are unchanged.

## V5 native Qdrant candidates

The explicit Python module `cragkit.qdrant` and Node subpath `cragkit/qdrant` implement [QC-r1](../contracts/QDRANT_CANDIDATES_V5.md). They return text-free, unverified nominations; authoritative source release and distributed publication remain separate V5-03/04 gates. The [candidate report](../evaluation/reports/V5/V5-02.md) records tested configurations and limitations.

Verified focused commands from the repository root, one suite at a time:

```sh
uv sync --project packages/python --frozen --extra qdrant
uv run --project packages/python --frozen --no-sync --extra qdrant pytest packages/python/tests/test_qdrant.py packages/python/tests/test_qdrant_transport.py packages/python/tests/test_qdrant_embeddings.py tools/tests/test_check_qdrant.py packages/python/tests/test_qdrant_dense_retrieval.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant mypy --config-file packages/python/pyproject.toml packages/python/src
```

In `packages/typescript`, run `npm run build`, then `node --test --test-concurrency=1 tests/qdrant.test.mjs tests/qdrant-transport.test.mjs tests/qdrant-embeddings.test.mjs`. The optional Python extra pins HTTPX 0.28.1. Node uses its built-in fetch; no Qdrant SDK or model runtime is installed. Neither module import starts a service or connects to a database.

An administrator explicitly acquires and verifies a supported Qdrant server binary. The current macOS arm64 reference is 1.20.0; acquisition evidence is in [V5-02A](../evaluation/reports/V5/V5-02A.md). No library import or native checker downloads it. After building Node and installing the Python extra, the verified isolated integration command is:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant python tools/check_qdrant.py --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --artifacts-dir artifacts/V5/native-candidates
```

The checker creates one owned loopback process, private administrative/read-only keys and eight synthetic points. It runs the native runtimes serially and compares all returned nominations and ledger snapshots. It verifies write denial for the read-only key, deletes its collection, confirms an empty inventory, terminates the process and removes private config/data. Generated artifacts contain synthetic records only. Explicit clients must close the store and then their owned transport; borrowed resources are not closed by the store. Remote endpoints require verified HTTPS. Plain HTTP is allowed only for explicitly configured `127.0.0.1` or `::1` development endpoints; proxy/TLS bypass settings are unsupported.

The [dense composition examples](../examples/qdrant_dense.md) connect E-r1 batch output to candidate search and preserve separate provider/candidate work. After Node build, the root command `node --test --test-concurrency=1 packages/typescript/tests/qdrant-dense-retrieval.test.mjs` checks their accounting and cancellation. The Python example checks are included in the focused command above. Real-profile tests inject routing spies; they make no paid calls or real-profile writes.

Add `--dense-only` to the native checker and select a separate artifact directory, such as `--artifacts-dir artifacts/V5/native-dense-only`, to verify a genuine dense-only collection. This mode uses fake E-r1 inference and batch binding before each actual scoped backend query. The accepted OpenAI configuration exposes dense only; no sparse model is required. [V5-02E evidence](../evaluation/reports/V5/V5-02E.md) records both deployment modes and their limits.

## V5 authoritative source schema

[QS-r1](../contracts/QDRANT_SOURCES_V5.md) and [the optional schema guide](../storage/qdrant/postgres/README.md) freeze the source-only foundation. The [V5-03A report](../evaluation/reports/V5/V5-03A.md) separates actual SQL checks from later source-adapter, runtime LOGIN and publication acceptance. The authority uses PostgreSQL 17 without a pgvector/FTS dependency; existing core/vector histories remain separate.

Verified focused checks, from the root and one process at a time:

```sh
uv sync --project packages/python --frozen --extra qdrant --extra postgres
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_authority_schema.py -q
```

After verifying the dedicated nonproduction direct Neon target, client TLS, creator/runtime privileges and existing migration/security gates, the explicit rollback-only native command is:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_authority_schema.py --config "$HOME/.config/cragkit/neon/admin-config.json" --confirm-dedicated-target --allow-test-writes --artifacts-dir artifacts/V5/source-schema
```

It refuses an existing `cragkit_qdrant` namespace, takes the shared administrative locks, creates the exact schema/ledger and synthetic data, and tests forced RLS through an ephemeral NOLOGIN role with SELECT/helper permissions. It never permanently applies the migration. Deferred FK events are resolved before changing fixture RLS, avoiding SQLSTATE `55006`. Administrative seeding temporarily removes FORCE only on the four newly created fixture tables; actual reader assertions run with FORCE restored. All DDL/data/role/membership work rolls back, old histories and role fingerprints are compared, and rollback/connection closure are bounded with redacted combined failures. This is not an actual reader LOGIN test. No Qdrant service or model provider runs in this command.

## V4 bounded corrective execution

The optional `cragkit.corrective` / `cragkit/corrective` modules accept a trusted backend. `PostgresCorrectiveBackend` in `cragkit.postgres_corrective` / `cragkit/postgres-corrective` reuses caller-owned native sessions. Ledger, planner and event modules are explicit imports/subpaths. Importing them does not connect a service or load a model. Read [the execution contract](../contracts/EXECUTION_V4.md) and [V4-03 through V4-05 evidence](../evaluation/reports/V4/V4-03-05.md).

Verified serial checkpoint:

```sh
python3 tools/check_core_pipeline.py --artifacts-dir artifacts/V4/checkpoint-core
```

It runs 27 stages, including complete execution, planning, corrective and event parity. Clean installed archives also run the 44 V4 shared state-machine cases outside the checkout. The optional framework packages have separate environments; they are not installed by this core command. Internal core archives retain version 0.0.0; V4 is an implementation milestone, and public alpha publication remains separate.

Event exporters are cooperative async application callbacks. Retrieval only queues events; call `flush` explicitly outside its critical path with an absolute monotonic deadline. No implementation can make a synchronously blocking application callback cooperative. Shared sinks expose cumulative counters; generated trace IDs separate concurrent requests without storing request text. The final result's events snapshot is a point-in-time view of that shared queue, not a per-request delivery receipt.

### Optional V4 framework verification

The separate `packages/langchain-python` project pins LangChain Core 1.7.0; `packages/langchain-typescript` pins `@langchain/core` 1.3.0 and LangSmith 0.11.1. Their locks include SDK dependencies; core manifests remain framework-free. See [the adapter guide](integrations/langchain.md).

```sh
python3 tools/check_sdk_packages.py --artifacts-dir artifacts/V4/acceptance
```

This serial entrypoint runs the 27 core stages followed by frozen SDK installs, both adapter typechecks, real SDK tests and clean optional archives/install tests: 34 stages total. It requires registry access for missing pinned dependencies. It does not run a live model or touch a database. Hosted CI remains unconfigured/unrun. For a focused SDK pass, run each command separately:

```sh
uv run --project packages/langchain-python --frozen mypy --config-file packages/langchain-python/pyproject.toml packages/langchain-python/src
uv run --project packages/langchain-python --frozen pytest packages/langchain-python/tests -q
npm --prefix packages/langchain-typescript run typecheck
npm --prefix packages/langchain-typescript test
```

Clean framework verification builds Python wheel/source/rebuilt wheel and npm archive, installs those products in temporary environments, reruns the SDK tests there, verifies product import origins and checks SDK dependency versions/integrities. Original checkout files still exist; this proves isolated installed imports, not physical removal of the checkout. Environment payload sizes are logical file totals, not disk allocation or runtime memory. Core and optional reports live in separate subdirectories.


### Recovering interrupted native fixtures

For example, a killed V4 database check can leave its temporary role and synthetic rows even though ordinary tests pass. The parent writes a private, immutable ownership record before fixture mutation and uses a fresh verified connection for cleanup. It shares a 25-second budget across old-client closure and at most two serial recovery attempts. Failed cleanup emits bounded primary and cleanup diagnostics plus a random recovery ID; it retains the record outside Git. See [the harness contract](../contracts/HARNESS_RECOVERY_V4.md).

With the optional PostgreSQL dependencies installed, recover only the ID reported by that failed run:

```sh
uv run --project packages/python --frozen --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --recover RUN_ID
```

If a process was killed before printing its recovery ID, inspect the JSON filenames in the private `~/.config/cragkit/runtime-recovery` directory; each filename stem is one run ID. The recovery command still validates its target and ownership before database action. Do not mix recovery with a new fixture mode. The exact target, private record, ownership marker, restricted role, policies, schema and history hashes must match before deletion. Successful cleanup removes the record. Repeating the CLI after that fails closed; a missing file does not prove a prior cleanup succeeded. Old failures without a journal require exact operator inspection. The lifecycle unknown-purge test relation is outside the automatic recovery inventory and triggers a schema refusal, never an automatic table drop. Role comments are ownership evidence against accidental misuse, not secrets or protection from a compromised database administrator.

The native fault acceptance command creates and kills only its own child fixture, checks repeat cleanup, administrator loss, bounded retries and retained-journal recovery, and compares pre-existing roles/profiles/history:

```sh
uv run --project packages/python --frozen --extra postgres python tools/check_runtime_recovery.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --confirm-dedicated-target
```

Use the empty, dedicated development target and run this separately from other database checks. No model call is required. A hard termination cannot guarantee immediate cleanup; the durable record enables a later authorized recovery. Failure case: a forged ownership marker causes refusal before row deletion. Practice: explain why a role name alone is insufficient authority to delete it.


### Native evaluation timing profiles

The default hybrid/evidence/corrective administrative evaluation supplies an external 25-second deadline and retains the request policy default of 10,000 ms; the earlier deadline governs. An explicit higher-latency profile is available when the database round trips consume that budget:

```sh
uv run --project packages/python --frozen --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --hybrid --corrective --evidence --typescript --evaluation-deadline-seconds 60
```

The result records `acceptance_profile=high_latency_admin`, `evaluation_deadline_seconds=60` and `effective_evaluation_deadline_ms=60000`; default metadata records `default`, `25` and `10000`. The opt-in profile explicitly configures both the external deadline and request policy; all other limits are preserved. Both runtimes must report the same profile. The override is valid only for hybrid acceptance, has exact choices 25/60, and retains the fixed sample, candidate/call/attempt limits and authorization assertions. It changes no product default. Deliberate short fault probes and the shared 25-second recovery budget remain unchanged. The higher-latency run has separate bounded parent/child ceilings of 1,800/960 seconds and uses the same maximum two clients. Its temporary restricted LOGIN expires after 32 minutes to cover that bound; default expiry remains 10 minutes. Cleanup disables/removes the exact role immediately. Run it serially. Keep a failed default-profile result; a higher-budget pass does not establish the default budget or production latency. See [the current verification report](../evaluation/reports/V4/V4-SECURITY-VERIFICATION.md).

Focused administrative regression tests require the frozen Python and Node development environments; the profile test builds the Node library before importing its native helper:

```sh
uv run --project packages/python --frozen pytest tools/tests/test_runtime_diagnostics.py tools/tests/test_runtime_recovery.py tools/tests/test_runtime_recovery_postgres.py tools/tests/test_check_python_postgres.py tools/tests/test_native_evaluation_profile.py -q
```


## V5-03B/C authoritative source reader checks

The optional native readers borrow existing PostgreSQL pools. Import Python `cragkit.qdrant_source` or Node `cragkit/qdrant-source`; core imports remain unchanged. [V5-03B/C evidence](../evaluation/reports/V5/V5-03BC.md) records the verified focused/full-suite commands, type checks, exact catalog query/manifest and negative-case coverage. Use `--no-sync --extra qdrant --extra postgres` with the existing frozen Python environment to preserve both optional drivers. Run one language suite at a time.

Both facades execute all 40 source scenarios with fake authority/drivers. The rollback-only native catalog probe also checks deliberate policy/function/constraint/PUBLIC-privilege drift. These checks do not replace V5-03D actual restricted LOGIN, PostgreSQL/Qdrant and provider/final-release acceptance. No persistent source schema is installed by the probe or the reader.


## V5-03D local native source acceptance

[V5-03D/C1](../evaluation/reports/V5/V5-03D.md) records the exact opt-in command for preinstalled PostgreSQL 17.11 and the checksummed Qdrant 1.20.0 binary. It creates isolated local TLS/SCRAM PostgreSQL and loopback Qdrant fixtures, runs 14 source cases per runtime serially, checks wrong-hostname/untrusted-certificate rejection in Node, then shuts down and removes its private data. It uses no hosted configuration or live models. Do not run this tool as a watcher or point it at an unrelated server.

Focused lifecycle/protocol checks are `uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_source_native.py tools/tests/test_check_qdrant_source.py -q`. After the strict Node build, run `node --test --test-concurrency=1 packages/typescript/tests/postgres-pool.test.mjs packages/typescript/tests/qdrant-source.test.mjs packages/typescript/tests/qdrant-authority.test.mjs`. D-F1 keeps certificate verification enabled and omits IP SNI, as required by Node 26.5. V5-04 publication and repair acceptance remain separate.

## V5-04B1 pure vector codec

The internal native codecs implement [QW-r1 vector identity](../contracts/QDRANT_PUBLICATION_V5.md#b1-float32-codec-and-seal). They require no running service or provider. [V5-04B1 evidence](../evaluation/reports/V5/V5-04B1.md) records exact input seals, the fixed dense readback equivalence, exact sparse checks and remaining native storage gates. Package exports and existing candidate/source contracts are unchanged.

Run the runtimes serially from the repository root:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_vectors.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres mypy --config-file packages/python/pyproject.toml packages/python/src
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-vectors.test.mjs
```

The complete regression commands remain the existing Python/tool pytest suite and `npm --prefix packages/typescript test`. These checks prove pure codec behavior; they do not complete Qdrant publication or crash recovery. Durable replay must preserve admitted original numeric input as well as the canonical seal, because rounding can move a valid norm beyond the original E-r1 admission boundary.

## V5-04B2 metadata and replay codecs

The internal native helpers implement [QW-r1 manifests and portable replay](../contracts/QDRANT_PUBLICATION_V5.md#b2-native-helpers-and-durable-original-vectors). They require no service or provider. [B2 evidence](../evaluation/reports/V5/V5-04B2.md) records exact manifest/intent arrays, original Float64LE sidecars, corruption checks and cross-runtime results. These encoders do not authorize source release or establish publication.

Run from the repository root, one runtime at a time:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_manifest.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres mypy --config-file packages/python/pyproject.toml packages/python/src
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-manifest.test.mjs
```

Full regression commands remain the existing Python/tool pytest suite and `npm --prefix packages/typescript test`. Restore requires expected hashes from trusted immutable authority data and reissues B1 provenance. The later manager must link every restored vector to its manifest and recheck current authorization before publication.

## V5-04C1 publication authority SQL

The [additive migration guide](../storage/qdrant/postgres/PUBLICATION.md) defines the writer/supervisor roles, durable records and transaction boundaries. [C1 evidence](../evaluation/reports/V5/V5-04C1.md) records local PostgreSQL acceptance. It does not establish Qdrant completion or native manager compatibility.

Run focused construction/lifecycle tests without a database:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_publication_schema.py tools/tests/test_check_qdrant_publication_schema.py -q
```

The native command explicitly starts and removes one private loopback PostgreSQL 17.11 TLS/SCRAM cluster. It uses synthetic rows and rollback-only transactions, with one connection and no hosted configuration, Qdrant or model call. Choose a fresh artifact directory; an existing success file is refused.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_schema.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --allow-local-processes --artifacts-dir artifacts/V5/V5-04C1/run-new
```

The runner checks the exact original source catalog before each upgrade, tests scoped nonowner roles and rejects managed admission under repeatable-read/serializable isolation. It verifies namespace/role/membership/default-privilege rollback and closes the connection, server and private directory before writing success. SET ROLE is policy evidence; actual writer LOGIN, cross-commit and concurrent mutation acceptance remain later gates. C2 separately verifies source-reader LOGIN.

## V5-04C2 explicit reader profiles

The [source contract](../contracts/QDRANT_SOURCES_V5.md#c2-r1-explicit-publication-schema-compatibility) binds each exact history/catalog pair. [C2 evidence](../evaluation/reports/V5/V5-04C2.md) records both native profiles, role predicates, drift rejection and source/provider release gates. Neither profile advertises a publication manager.

Run focused tests and build serially:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_authority.py tools/tests/test_check_qdrant_source.py tools/tests/test_qdrant_source_privileges.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-authority.test.mjs
```

Native acceptance requires the already available pinned binaries. Run one profile at a time, with separate artifact directories:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_source.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --authority-profile publication --artifacts-dir artifacts/V5/V5-04C2/publication-verified
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_source.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --authority-profile source --artifacts-dir artifacts/V5/V5-04C2/source-verified
```

The parent evaluates both native SQL permission predicates on a real TLS reader connection, restoring each unsafe grant before source cases. The publication profile also tests catalog drift and disabled internal FK triggers. Each native runtime executes the same fourteen source/provider-gate cases. Private administrative source seeding temporarily disables only the two named new publication constraint triggers inside a transaction, resolves pending FK events and restores them before reading. This creates source fixtures; it is not manager publication. Final fingerprints, owned collection cleanup, process exit and private-directory removal are verified. No hosted database, model call or download is involved.

## V5-04D native authority writer acceptance

The internal native writers borrow a PostgreSQL pool. They perform committed authority transactions without Qdrant HTTP or application authorization callbacks. [D evidence](../evaluation/reports/V5/V5-04D.md) separates those checks from the E-H replica and controller gates. Build Node first, then run the opt-in local command with a fresh output directory:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_writer.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04D/a-new-run
```

This starts disposable PostgreSQL 17.11 TLS/SCRAM fixtures and runs SQL, Python and Node serially. No hosted configuration, Qdrant service or model is used. Administrative setup closes before two native writer clients run. The checker refuses an existing artifact directory and records success only after cleanup. Its synthetic completion digests exercise authority transitions; actual Qdrant acknowledgment/readback remains later acceptance.

## V5-04E1 controller acceptance

The optional internal controllers have a macOS arm64 reference profile with the existing pinned Qdrant 1.20.0 binary. [E1 evidence](../evaluation/reports/V5/V5-04E1.md) separates physical credential/process fencing from later SQL recovery settlement. Build Node, then explicitly run:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_supervisor.py --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04E1/a-new-run
```

Use a fresh artifact directory. The native runtimes run serially and explicitly provision synthetic collections; retired invalid keys must receive HTTP 401. The controller preserves storage, refuses directory adoption and leaves ordinary admission closed after recovery. The checker removes only its fixture directory after verified shutdown. No hosted configuration or SQL settlement is used in E1.

## V5-04E2a recovery readback acceptance

The internal native verifiers bind exact current authority and complete Qdrant readback to an actual controller recovery proof. [E2a evidence](../evaluation/reports/V5/V5-04E2a.md) records the SQL and process checks. Build Node, then run this explicit local profile with a fresh directory:

```sh
npm --prefix packages/typescript run build
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_reconciliation.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04E2a/a-new-run
```

This uses isolated PostgreSQL 17.11 with TLS and restricted writer/supervisor logins, at most two clients, and one pinned Qdrant process. Python and Node run serially. Deliberate point corruptions are fixture interventions; the checker never settles its unknown journal or reopens the SQL gate. Complete readback issues an internal receipt, not publication or purge completion. E2b supplies the separate settlement and admission handoff. Successful cleanup verifies listener absence before removing only owned fixture storage.

## V5-04E2b durable recovery acceptance

The internal recovery coordinators use the restricted supervisor role and actual E1/E2a capabilities. [E2b evidence](../evaluation/reports/V5/V5-04E2b.md) records durable blocking, retired-generation settlement, exclusive controller sessions and private SQL/native reopening.

```sh
npm --prefix packages/typescript run build
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_recovery.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04E2b/a-new-run
```

Use a fresh directory. The local profile runs the SQL privilege checks, then each native runtime serially, with two max-size-one pools and no remaining administrative client during runtime work. The two-client ceiling is a development configuration; applications own their other pool users. Fault wrappers perform real commits and withhold one acknowledgment, or pause one coordinator before actual fencing. They do not fabricate SQL/HTTP success. A test-only current-generation journal/upsert establishes a valid unresolved precondition; production recovery dispatch remains F/G work. Successful runs verify shutdown before deleting owned fixtures. Close recovery coordinators before their borrowed resources and controller. Supervisor restart/adoption and the H process-crash matrix remain separate from this primitive's acceptance.

## V5-04F1 ordinary publication readback

The private ordinary verifier checks the complete staged graph and live attempt, performs full native readback, then rechecks authority. It cannot publish, settle uncertainty or reopen admission. [F1 evidence](../evaluation/reports/V5/V5-04F1.md) records the tested boundary.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_writer.py packages/python/tests/test_qdrant_publication_verification.py packages/python/tests/test_qdrant_reconciliation.py tools/tests/test_qdrant_publication_verification_native.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-writer.test.mjs packages/typescript/tests/qdrant-reconciliation.test.mjs packages/typescript/tests/qdrant-publication-verification.test.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_verification.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04F1/a-new-run
```

Use a fresh directory. The native checker runs both languages serially with at most two database clients, synthetic original vectors and isolated PostgreSQL/Qdrant. Its completed-acknowledgment settlement and deliberate point corruptions are primitive fixture interventions. Final observations require unpublished source state, matching normalized witnesses and owned listener absence before fixture removal. Public manager and process-crash acceptance remain later V5-04 work.

## V5-04F2a1 manager authority admission

Private manager snapshots and admission use the existing restricted writer profile. [F2a1 evidence](../evaluation/reports/V5/V5-04F2a1.md) distinguishes SQL authority observations from public HTTP/publication acceptance.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_writer.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-writer.test.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_writer.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04F2a1/a-new-run
```

The checker now includes eight additional manager-authority groups in each runtime while retaining the original fourteen SQL and fourteen per-runtime D groups. It starts only isolated PostgreSQL, runs languages serially and requires a fresh output directory. Its one lost-commit observation forwards the actual commit before withholding the acknowledgment, then checks that the uncertain client was discarded. A discarded-connection log is expected for that injected failure. Fixture completion hashes remain synthetic; this command does not run Qdrant or establish public-manager publication.

## V5-04F2a2i native dependency bindings

Private dependency/profile accessors retain the original native writer, recovery verifier and controller identities without exposing resources. [Evidence](../evaluation/reports/V5/V5-04F2a2i.md) records their narrower metadata scope.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_writer.py packages/python/tests/test_qdrant_recovery.py packages/python/tests/test_qdrant_supervisor.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-writer.test.mjs packages/typescript/tests/qdrant-recovery.test.mjs packages/typescript/tests/qdrant-supervisor.test.mjs
```

The existing `check_qdrant_supervisor.py` and `check_qdrant_recovery.py` commands also verify these bindings on their real native graphs. Use their previously documented arguments with fresh output directories under `artifacts/V5/V5-04F2a2i/`. Accessor success does not open ordinary admission or authorize settlement; existing actual capabilities and current SQL checks still apply.

## V5-04F2a2ii public stage and publish

The optional modules expose the public managed stage/publish path and explicit native dependencies. Read [the API guide](qdrant-publication.md) and [acceptance evidence](../evaluation/reports/V5/V5-04F2a2ii.md) before configuring a managed writer. Pools and the supervisor open explicitly; imports and constructors apply no migrations or network side effects.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_publication.py packages/python/tests/test_qdrant_writer.py tools/tests/test_qdrant_publication_manager_native.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-publication.test.mjs packages/typescript/tests/qdrant-writer.test.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_manager.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04F2a2ii/a-new-run
```

## V5-04F3 publication and source visibility

The [F3 report](../evaluation/reports/V5/V5-04F3.md) records sixteen native checks and exact source-observation parity. Prepared physical vectors cannot release source text. Publication changes fresh source admission; retained authorized bindings preserve immutable evidence and report staleness. Worker crash recovery and the full V5 fault matrix remain separate gates.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_publication_source_native.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_source.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04F3/a-new-run
```

Use a fresh artifact directory. The command starts only disposable local servers with synthetic fixtures, runs runtimes serially, compares deterministic observation hashes and verifies listener shutdown. It performs no hosted/provider calls and requires no model installation.

## V5-04F2b native publication workers

The optional publication module now includes the fixed native worker host. [The guide](qdrant-publication.md#running-publication-in-an-owned-worker) describes resource ownership; [F2b evidence](../evaluation/reports/V5/V5-04F2b.md) distinguishes actual process tests from protocol doubles.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_publication_worker.py tools/tests/test_qdrant_publication_worker_native.py tools/tests/test_qdrant_source_native.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-publication-worker.test.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_worker.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04F2b/a-new-run
```

Use a fresh directory. This test owns disposable local processes and synthetic data. Ordinary windows use at most two database clients. The paused-child recovery experiment permits three max-one clients; its PostgreSQL fixture uses six total slots while preserving three reserved superuser slots. Other fixtures retain their five-slot default. No provider/model, hosted mutation or automatic supervisor takeover occurs. Full H acceptance, managed repair and installed artifacts remain separate gates.

The reserved-COMMIT child crash has its own native scenario. Run it with a fresh artifact directory:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_worker.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --scenario reserved --runtime all --artifacts-dir artifacts/V5/V5-04H/a-new-reserved-run
```

It kills the owned child at the acknowledged `reserved` barrier, crosses that operation's recorded five-second request deadline and verifies that a fresh retry cannot clear the durable reservation or write points. The [H-S30 report](../evaluation/reports/V5/V5-04H-reserved-owner-crash.md) records the local evidence and its limits.

Use a fresh directory. The checker opens two restricted resources, runs actual public manager code against isolated PostgreSQL/Qdrant, and compares nineteen exact public-result snapshots. It withholds one real preparation COMMIT acknowledgment and one real completed HTTP response; it does not fabricate successful writes. Prepared cancellation/object restart is narrower than the pending process-kill matrix. Keep native languages and other integration suites serial. Successful cleanup verifies listener absence before removing only owned fixture storage.

## V5-04G0 preparation attestations

[The publication guide](qdrant-publication.md#preparation-after-recovery) explains the explicit optional migration and private receipt boundary. [G0 evidence](../evaluation/reports/V5/V5-04G0.md) records acceptance scope.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_writer.py packages/python/tests/test_qdrant_publication_verification.py packages/python/tests/test_qdrant_publication_worker.py tools/tests/test_qdrant_attestation_migration.py tools/tests/test_qdrant_attestation_schema.py tools/tests/test_check_qdrant_attestation_schema.py tools/tests/test_qdrant_attestation_native.py tools/tests/test_qdrant_publication_native.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-writer.test.mjs packages/typescript/tests/qdrant-publication-verification.test.mjs packages/typescript/tests/qdrant-publication-worker.test.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_attestation.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --artifacts-dir artifacts/V5/V5-04G0/a-new-run
```

The parent runs each language serially against fresh disposable PostgreSQL/Qdrant servers, verifies the explicit three-migration catalog and tests native permission drift before releasing the setup administrator. At most two database clients are active. Its acknowledgment fault occurs after an actual successful SQL commit; same-key confirmation must succeed without another point write. Use a fresh artifact directory and retain the pinned Qdrant binary. This task does not call a model or configure a hosted service.

`tools/check_qdrant_publication_source.py` also accepts `--with-attestations` to run its unchanged source-facing scenarios on the explicit three-migration profile. Omit that option to retain the original two-migration fixture. Neither checker changes an application database or applies a migration on import.

## V5-04G1a native managed repair

[Managed repair](qdrant-publication.md#native-managed-repair) supports prepared and already-complete uncertain stages. [G1a evidence](../evaluation/reports/V5/V5-04G1a.md) retains the partial-write and remaining version gates.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_publication.py packages/python/tests/test_qdrant_writer.py tools/tests/test_qdrant_repair_native.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-publication.test.mjs packages/typescript/tests/qdrant-writer.test.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_repair.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --artifacts-dir artifacts/V5/V5-04G1/a-new-run
```

Use a fresh directory. The parent applies only the explicit disposable fixture schema, runs native languages serially with at most two database clients, checks least-privilege predicates and verifies listener shutdown. Real completed HTTP/SQL responses are withheld for acknowledgment faults. The Python and Node interruption points differ, as recorded in the report. Neither a passing schema nor a matching result shape proves complete repair or model quality.

## V5-04G1b-B1 recovery session transport

[B1 evidence](../evaluation/reports/V5/V5-04G1b-B1.md) covers the actual session transport prerequisite without SQL or publication claims.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_supervisor.py tools/tests/test_qdrant_recovery_session_native.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-supervisor.test.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_recovery_session.py --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --artifacts-dir artifacts/V5/V5-04G1/a-new-session-run
```

Use a fresh directory. The parent runs native languages serially with actual isolated Qdrant and synthetic vectors. It checks listener absence before removing owned storage. Cancellation/drain timing has unit coverage; the five native cases per runtime do not simulate a stalled wire response or establish SQL settlement. Existing native controller/recovery regressions remain separate runs.

## V5-04G1b-B2a readback inspection and shared bytes

[B2a evidence](../evaluation/reports/V5/V5-04G1b-B2a.md) distinguishes missing diagnostics from proof and records the multi-phase budget fix.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_reconciliation.py packages/python/tests/test_qdrant_publication_verification.py packages/python/tests/test_qdrant_publication.py tools/tests/test_qdrant_missing_readback_native.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-reconciliation.test.mjs packages/typescript/tests/qdrant-publication-verification.test.mjs packages/typescript/tests/qdrant-publication.test.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_missing_readback.py --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --artifacts-dir artifacts/V5/V5-04G1/a-new-inspection-run
```

Use a fresh directory. Native languages run serially against actual isolated Qdrant with synthetic vectors, without PostgreSQL or provider calls. The consumer injects faults through actual backend writes and compares actual returned bytes across passes. It closes owned sessions/controllers and checks listener absence before removing private fixture storage. It does not claim SQL settlement or complete partial repair.

## V5-04G1b partial-stage repair

For example, a nine-member generation can lose the reply to its first eight-point write. Repair inspects that set, fills the missing member under a new fenced credential, then requires complete verification before publication. [B2b/B3 evidence](../evaluation/reports/V5/V5-04G1b-B2b-B3.md) records the native fault scope.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_partial_repair_native.py packages/python/tests/test_qdrant_writer.py packages/python/tests/test_qdrant_recovery.py packages/python/tests/test_qdrant_publication.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-writer.test.mjs packages/typescript/tests/qdrant-recovery.test.mjs packages/typescript/tests/qdrant-publication.test.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_partial_repair.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --artifacts-dir artifacts/V5/V5-04G1/a-new-partial-run
```

Use a fresh directory. The parent runs runtimes serially with actual disposable PostgreSQL 17 and Qdrant 1.20, synthetic vectors and at most one writer plus one supervisor database client. Its explicit extended development profile allows 240 seconds for business work, 15 seconds for cleanup and 280 seconds for the Node child; it does not change library defaults or establish default-budget performance. Faults withhold genuine completed SQL/HTTP replies. The tools read only their generated owner-only fixture credential to inject scoped loopback corruption and test old-key rejection; credentials never enter reports or command arguments. Listener shutdown and fixture cleanup are checked. Full H crash-matrix, replica-security/purge and release acceptance remain separate.

## V5-04G2a1 authority-only security confirmation

[Security confirmation evidence](../evaluation/reports/V5/V5-04G2a1.md) covers exact historical outcomes after lost COMMIT replies, without vector convergence or purge claims. After the strict Node build, the existing `tools/check_qdrant_writer.py` command accepts `--postgres-bin /opt/homebrew/opt/postgresql@17/bin --allow-local-processes --artifacts-dir` with a fresh directory. It runs SQL, Python and Node serially on disposable PostgreSQL; the extended consumers withhold an actual tombstone commit reply and verify a superseded security retry preserves the current tombstone. Focused tests are the existing Python and Node writer test files. Native acceptance uses two runtime clients and no Qdrant service or provider call.

## V5-04G2a2 independent public security manager

[Public security evidence](../evaluation/reports/V5/V5-04G2a2.md) covers authority admission separately from physical convergence. Run `uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_security.py -q`, then `npm --prefix packages/typescript run build` and `node --test --test-concurrency=1 packages/typescript/tests/qdrant-security.test.mjs`, serially. The existing native writer parent command also checks public methods under an actual blocked SQL backend and an uncertain exact-ID purge reservation, preserving the prior owner/journal. It temporarily closes the second writer resource before opening a max-one supervisor resource; at most two runtime clients remain. Its 68 checks do not establish physical Qdrant recovery or convergence. Use a fresh artifact directory and retain the opt-in local-process flag.

## V5-04G2b1 current-security projection

[Projection evidence](../evaluation/reports/V5/V5-04G2b1.md) covers private read-only claim inventories and original graph validation, separately from physical recovery. Run the existing Python and Node writer test files and `tools/tests/test_qdrant_publication_native.py` serially after the strict Node build. The existing native `tools/check_qdrant_writer.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --allow-local-processes --artifacts-dir` command requires a fresh directory and now checks ordered cross-runtime projection observations and their independently recomputed inventory hash.

Its 78 checks include two actual database connections: one holds the projection's document row lock while the other stages a generation; the fixture observes the wait in `pg_catalog.pg_locks` before releasing it. Fresh validation then rejects the older inventory. The fixture uses 14 synthetic points across seven generations, not the maximum supported history or a physical Qdrant index. It closes both clients and its disposable server. A projection or matching inventory hash cannot settle an unknown write or certify current physical replicas.

## V5-04G2b2a denied-owner recovery SQL proof

[SQL permission evidence](../evaluation/reports/V5/V5-04G2b2a.md) distinguishes actual database mechanics from runtime/physical proof. Run these commands serially:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_recovery_dispatch_sql.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_recovery_dispatch_sql.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --allow-local-processes --security-owner --artifacts-dir artifacts/V5/V5-04G2b/a-new-security-sql-run
```

Use a fresh directory. The opt-in mode performs 15 checks on one disposable PostgreSQL connection with restricted SQL roles, explicit synthetic metadata and mandatory savepoint/outer rollback. It runs no Qdrant service or provider and creates no genuine recovery proof or completed HTTP acknowledgment. Omitting `--security-owner` retains the prior 12-check B0 profile. Pre-existing output directories are refused without overwriting their diagnostic files.


## V5-04G2b2b full-document security readback

[Readback evidence](../evaluation/reports/V5/V5-04G2b2b.md) separates diagnostics from genuine recovery receipts and settlement. Run languages serially:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_security_readback.py tools/tests/test_qdrant_security_readback_native.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-security-readback.test.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_security_readback.py --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --artifacts-dir artifacts/V5/V5-04G2b2/a-new-readback-run
```

Use a fresh artifact directory. The parent runs eight cases per runtime serially on actual isolated Qdrant, with four synthetic points across two generations and no PostgreSQL or provider. It checks real stale/missing/corrupt/extra/drifting data and actual shared response accounting, then closes sessions/controllers and verifies listener absence before cleanup. These observations do not authorize writes or certify SQL settlement. Deadline/cancellation and ceiling exhaustion have separate unit coverage.


## V5-04G2b2c1 authentic session snapshots

[Session evidence](../evaluation/reports/V5/V5-04G2b2c1.md) uses the existing Python `test_qdrant_supervisor.py` and Node `qdrant-supervisor.test.mjs` focused suites, strict typechecks/build and the G2b2b native parent above, serially. The parent now also compares actual session activity against three metered readback passes. Use a new artifact directory. No database or provider is required; these checks do not mint security receipts or settle journals.


## V5-04G2b2c2 same-session security receipts

[Receipt evidence](../evaluation/reports/V5/V5-04G2b2c2.md) distinguishes actual native observation from SQL settlement. Run checks serially:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_security_verification.py tools/tests/test_qdrant_security_verification_native.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-security-verification.test.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_security_verification.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --artifacts-dir artifacts/V5/V5-04G2b2c/a-new-security-receipt-run
```

Use a fresh artifact directory. The parent applies only the explicit disposable three-migration fixture profile and checks restricted-role admission before releasing its administrative connection. Each runtime uses at most one writer and one supervisor database client; languages run serially. It verifies eight actual source/proof/readback cases per runtime and stable witness-content parity. The 120-second business profile and separate twelve-second resource-cleanup allowance do not change library defaults or establish performance. Listener/process cleanup is checked before owned storage removal. These tests create no journal settlement or public convergence claim; routine vectors and source spans are synthetic.


## V5-04G2b2d0 separate-connection guard necessity

[Counterexample evidence](../evaluation/reports/V5/V5-04G2b2d0.md) rejects the candidate two-connection guard; passing this checker does not establish safe product settlement.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_security_lock_native.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_security_lock.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --allow-local-processes --artifacts-dir artifacts/V5/V5-04G2b2d0/a-new-lock-counterexample
```

Use a fresh directory. This PostgreSQL-only fixture uses two restricted runtime clients plus one administrative advisory-barrier observer, sequential writer replacement and six server slots. A separate fixture schema leaves the production catalog and capability grants unchanged. Actual submitted COMMIT and retained-lock waits are observed through database lock/activity views. Completion metadata is explicitly synthetic. The sixty-second business deadline and separate twelve-second cleanup allowance are development limits. Owned connections/schema/process/storage are closed and checked. No Qdrant, provider or hosted target is involved.


## V5-04G2b2d1 restricted same-transaction SQL guard

[SQL guard evidence](../evaluation/reports/V5/V5-04G2b2d1.md) covers the additive migration under an explicit non-superuser operator. Runtime profile-4 compatibility and receipt settlement remain separate tasks; use only disposable fixtures at this checkpoint.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_security_guard_schema.py tools/tests/test_qdrant_security_guard_races.py tools/tests/test_qdrant_security_guard_native.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_security_guard.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --allow-local-processes --artifacts-dir artifacts/V5/V5-04G2b2d1/a-new-guard-run
```

Use a fresh directory. The parent explicitly bootstraps a trusted non-superuser schema-owner operator on a new PostgreSQL fixture, seeds five small documents through accepted three-profile writer APIs, then applies 0004 as that operator. It checks rollback, preexisting-role refusal, twelve restricted SQL groups and six atomic-lock races. At most two restricted runtime clients plus one admin observer run at once; the server has six slots. Actual barriers stay in an owned separate schema. The test enables `client_connection_check_interval=100ms` and observes server-side termination; client close alone is not treated as that proof. Its outer 180-second deadline bounds the combined development profile, with separate twelve-second race cleanup. Final history, catalog and owned process/storage cleanup are checked. No Qdrant service, provider, hosted target or genuine recovery receipt is involved.


## V5-04G2b2d2a native profile-4 source admission

[Source admission evidence](../evaluation/reports/V5/V5-04G2b2d2a.md) covers the exact four-migration source-reader profile. Writer and recovery admission remain separate.

```bash
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_guard_authority.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04G2b2d2a/a-new-reader-run
```

Use a fresh directory. The parent runs Python and Node serially on disposable PostgreSQL 17 fixtures, seeds through the accepted older writer profile, then explicitly applies 0004 with the restricted operator. Each runtime uses one reader and one operator client plus the parent admin observer. The development profile has a 120-second business deadline, separate twelve-second cleanup allowance and 175-second outer runtime limit. It checks unsafe permission, role and catalog changes before source SQL, restores owned changes and closes owned processes before removing storage. It releases no source bytes and runs no Qdrant service, provider or hosted mutation. Node requires the current package build.


## V5-04G2b2d2b1 native profile-4 writer admission

[Writer admission evidence](../evaluation/reports/V5/V5-04G2b2d2b1.md) covers exact profile-4 admission and permission drift before business SQL. It adds no writer grants; recovery admission remains separate.

```bash
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_guard_writer.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04G2b2d2b1/a-new-writer-run
```

Use a fresh directory and the current TypeScript build. Python and Node run serially on separate disposable PostgreSQL 17 fixtures, with one writer and one operator client plus the parent admin. The explicit development profile uses a 120-second business deadline, twelve-second cleanup allowance and 175-second outer runtime limit. It reconstructs a synthetic complete security projection, rejects committed metadata faults before writer scope binding, restores owned changes and verifies resource cleanup. No Qdrant service, provider, hosted write or migration on import is involved.


## V5-04G2b2d2b2 native profile-4 recovery admission

[Recovery admission evidence](../evaluation/reports/V5/V5-04G2b2d2b2.md) completes the source/writer/recovery admission foundation. Guarded graph validation and security settlement remain separate.

Add `--with-security-guard` to the existing native receipt checker to explicitly install 0004 under the disposable fixture operator. Omit it to retain the original three-migration mode.

```bash
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_security_verification.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --with-security-guard --runtime all --artifacts-dir artifacts/V5/V5-04G2b2d2b2/a-new-recovery-run
```

Use a fresh directory and the current TypeScript build. Guard mode uses three runtime clients (writer/supervisor/operator), releases the parent admin and provides six PostgreSQL slots. It preserves the existing 120-second business and twelve-second cleanup profile and serial runtime execution. The optional result reports four metadata fault checks and zero denied-path backend bindings separately from the eight receipt checks. Restored faults allow idempotent owner advance; the guard function itself is not invoked. Actual listener/process cleanup and stable witness parity are checked. No provider or hosted target is used.


## V5-04G2b2d3 guarded graph validation

[Guarded graph evidence](../evaluation/reports/V5/V5-04G2b2d3.md) covers the private read-only guard/graph driver. It does not settle journals or establish replica convergence.

```bash
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_security_verification.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --with-security-guard --guarded-graph --runtime all --artifacts-dir artifacts/V5/V5-04G2b2d3/a-new-guarded-run
```

Use a fresh directory and the current TypeScript build. Guarded mode requires `--with-security-guard`; omit `--guarded-graph` to retain the earlier admission mode. It adds nine checks per runtime to the existing eight receipt and four admission checks. Four actual SQL clients use seven server slots; the old operator is closed before the fixture admin opens. Corruption maintenance is restricted to synthetic fixture data. Actual lock waits, backend termination, delayed callback ownership and closed-resource cleanup are checked. No model, provider, hosted target or new dependency is used.


## V5-04G2b2d4 exact retired security settlement

[Settlement evidence](../evaluation/reports/V5/V5-04G2b2d4.md) covers the internal guarded journal operation and exact historical lost-COMMIT confirmation. It does not establish current-payload recovery dispatch, replica convergence, purge or full V5 acceptance.

```bash
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_security_verification.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --with-security-guard --security-settlement --runtime all --artifacts-dir artifacts/V5/V5-04G2b2d4/a-new-settlement-run
```

Use a fresh directory and the current TypeScript build. Settlement mode requires `--with-security-guard` and excludes `--guarded-graph`; earlier modes remain available separately. The checker runs both runtimes serially, with three SQL clients and six PostgreSQL slots. It preserves eight receipt and four admission checks and adds four settlement checks per runtime. Real native COMMIT succeeds before its reply is withheld, and the native writer advances authority before read-only confirmation. Confirmation must issue no DML, guard, HTTP or writer query replay. A fresh repeat preserves historical completion, while current-credential uncertainty preserves rows and closed admission. The unknown-dispatch metadata is synthetic; actual SQL transactions, restricted roles, current readback and COMMIT observations are native evidence. Task-owned servers and listeners are closed and cleanup is checked. No model, provider or hosted target is used.


## V5-04G2b2d5a current-security recovery dispatch

[Dispatch evidence](../evaluation/reports/V5/V5-04G2b2d5a.md) covers internal stale/missing replay and genuine acknowledgment binding. Security ownership handoff and public convergence are later gates.

```bash
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_security_verification.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --with-security-guard --security-dispatch --runtime all --artifacts-dir artifacts/V5/V5-04G2b2d5/a-new-dispatch-run
```

Use a fresh directory and current TypeScript build. Dispatch mode requires the guard profile and excludes the graph and settlement modes. It runs its own four dispatch checks plus four admission checks per runtime, with three SQL clients and six PostgreSQL slots. Python and Node run serially. It checks actual cross-generation stale/missing replay, genuine receipt and retired settlement, no-op and corrupt-vector refusal, then controlled loss of a completed HTTP acknowledgment. The last case must preserve current-key uncertainty and closed admission without resend. The checker restores instrumentation and closes owned servers/listeners. No provider or hosted target is used.


## V5-04G2b2d5b ordinary security handoff and completion

[Handoff evidence](../evaluation/reports/V5/V5-04G2b2d5b.md) covers the initial stage-owner transition and genuine ordinary-security completion. Public and repeated-owner convergence remain separate.

```bash
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_security_verification.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --with-security-guard --security-completion --runtime all --artifacts-dir artifacts/V5/V5-04G2b2d5b/a-new-completion-run
```

Use a fresh directory and current TypeScript build. Completion mode requires the guard profile and excludes other optional modes. It runs four completion checks plus four admission checks per runtime. It closes the idle recovery SQL resource before opening a contender, retaining three clients and six PostgreSQL slots. The real writer completion COMMIT succeeds before its reply is withheld; a second writer advances authority before read-only confirmation. Immutable history, historical flags, witness parity and cleanup are checked. No provider or hosted target is used.

For [D5c repeated-owner acceptance](../evaluation/reports/V5/V5-04G2b2d5c.md),
add `--with-purge-profile --security-repetition` to the native security verifier
command instead of `--security-completion`. Keep `--with-security-guard`, a
fresh artifact directory and the pinned local binaries. The checker installs
profile 5 and runs four repeated-owner cases plus four guard-admission checks
per runtime. `--runtime python` and `--runtime typescript` allow serial runs;
compare their recorded semantic witnesses. Profile-5 lost-COMMIT checks use
`--with-purge-profile --security-completion --runtime all` separately.

For [G2c public convergence](../evaluation/reports/V5/V5-04G2c.md), use
`--with-security-guard --with-purge-profile --public-security` instead of the
private completion/repetition mode. The same native parent accepts `--runtime
python`, `--runtime typescript` or `--runtime all`; each run needs a fresh
artifact directory. It provisions only disposable PostgreSQL/Qdrant fixtures
and checks ten public/source/failure cases per runtime. Compare the final
recorded semantic witnesses when languages run separately. No provider is used.

For the held old-ACL write fault, run the same parent with
`--with-security-guard --with-purge-profile --old-acl-late --runtime all`
and a fresh artifact directory. [The H-S31 report](../evaluation/reports/V5/V5-04H-old-acl-late-upsert.md)
records the exact native command, physical readback and cleanup. This scenario
uses the existing restricted local roles and makes no provider call.

## V5 profile-5 schema and optional MCP implementation

For the additive Qdrant schema prerequisite, use a fresh artifact directory and
the isolated local PostgreSQL 17 fixture:

```bash
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_purge_schema.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_purge_schema.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --allow-local-processes --artifacts-dir artifacts/V5/V5-04-profile5/a-new-native-run
```

The [schema report](../evaluation/reports/V5/V5-04-profile5-schema.md) records
44 focused tests and 14 native SQL checks. The SQL fixture's absence digest is
synthetic; actual Qdrant deletion and absence require their separate gate.

After building the Node package, the same disposable checker also verifies
restricted Python and Node profile-5 writer/reader initialization. The
[runtime report](../evaluation/reports/V5/V5-04-profile5-runtime.md) records 18
checks with cleanup, 533 Python and 331 Node focused tests, and strict builds.
Use a fresh artifact directory for each native run. The runtime admission check
does not establish physical Qdrant purge.

The MCP hosts live in separate optional Python and Node packages. These
commands use their pinned locks and exercise official SDK clients with fake
native retrieval results:

```bash
uv run --project packages/mcp-python --frozen --no-sync pytest packages/mcp-python/tests -q
uv run --project packages/mcp-python --frozen --no-sync mypy --config-file packages/mcp-python/pyproject.toml packages/mcp-python/src/cragkit_mcp
npm --prefix packages/mcp-typescript test
```

The Python test command includes four bounded child-process stdio checks in
`test_stdio_process.py`. It verifies the installed editable package using the
official SDK client; it does not substitute for the V5-08 wheel installation.

Run one language suite at a time. The [MCP implementation report](../evaluation/reports/V5/V5-06-implementation.md)
records 40 Python tests, including four bounded child-process stdio checks,
and 36 Node tests. The core package installs without these optional SDKs.
No live model call is part
of these checks.

## V5-04G3 managed purge runtime

The optional public publication managers implement the profile-5 purge protocol
in [QP-r1](../contracts/QDRANT_PURGE_V5.md). Its native acceptance is still in
progress; passing the implemented scenarios does not complete G3 or V5.
Build Node first, then run the disposable fixtures serially with a fresh output
directory. This command requires the already verified local server binary and
makes no embedding or reranker call:

```bash
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_purge.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04G3/a-new-native-run
```

Each runtime exercises eight public scenario groups, followed by independent
read-only PostgreSQL checks for six documents. The SQL observer compares
original identities and digests and checks every managed body and erasure
marker. A completed retry must avoid HTTP, DML and body loading. Native results
and remaining acceptance gaps belong in the G3 report and tracker; this command
does not establish the complete H fault matrix or production readiness.

### Supervisor pause acceptance

The isolated pause scenario holds a real admitted publication worker while its
supervisor process is stopped. It checks independent controller and SQL owner
refusal, then resumes the same owner for cleanup. Run both runtimes serially:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_worker.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --scenario supervisor_pause --runtime all --artifacts-dir artifacts/V5/V5-04H/supervisor-pause-both-02
```

Choose a fresh artifact directory for each run. The command proves the pause
alternative only; it does not implement automatic supervisor takeover.

The same worker checker supports `--scenario deadline` for the operation-expiry
case. It uses one independently owned streamed request against the disposable
local server, preserves product deadlines, and verifies successor refusal until
managed recovery. Use a fresh artifact directory, for example
`artifacts/V5/V5-04H/deadline-both-02`, with the command above and replace
`--scenario supervisor_pause` with `--scenario deadline`. The original and
reserved scenarios remain `--scenario ordinary` and `--scenario reserved`.

## V5 corrective adapters and native transport matrix

The optional Python `cragkit.qdrant_corrective` and Node
`cragkit/qdrant-corrective` entries compose initialized candidate/source stores
with an explicit embedding transport, counter and policy. They borrow stores
and support dense retrieval; unsupported lexical/hybrid modes fail locally.
QCC-r1 preserves native score semantics and gives candidate admission one owner.

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_qdrant_corrective.py packages/python/tests/test_qdrant_corrective_candidates.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/qdrant-corrective.test.mjs packages/typescript/tests/qdrant-corrective-candidates.test.mjs
uv sync --project tools/backend-conformance --frozen
uv run --project tools/backend-conformance --frozen --no-sync python tools/check_backend_conformance.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-07/conformance-both-final-02
```

Choose a fresh artifact directory per native run. The locked tool environment
collects the optional SDKs/drivers only for development. Its representative
PostgreSQL lexical and Qdrant dense profiles each execute direct, LangChain and
official MCP calls, including a real interrupted publication. See
[the matrix report](../evaluation/reports/V5/V5-07.md) for exact combinations,
provider-budget differences, cleanup and limits. Installed artifacts remain a
separate gate.

## V5 local optional artifacts and operations

The [V5 operations guide](v5-operations.md) lists the six isolated installation
profiles, required services, explicit migrations, borrowed connections and native
shutdown/recovery example. Core still depends only on Pydantic or Zod. The Python
development group includes the already pinned HTTP/PostgreSQL clients so a frozen
default setup can typecheck and test optional modules; wheel runtime dependencies
and extras remain separate.

```sh
python3 tools/check_sdk_packages.py --artifacts-dir artifacts/V5/V5-08/full-core-frameworks
python3 tools/check_qdrant_artifacts.py --core-artifacts artifacts/V5/V5-08/full-core-frameworks/core --output-dir artifacts/V5/V5-08/artifacts-final-02
```

The first command checks core, shared fixtures and optional LangChain packages,
then builds and installs local artifacts. The second complements it with MCP
artifacts and separate core, PostgreSQL, candidate-only Qdrant, authoritative
Qdrant, tokenizer and MCP environments in each runtime. It checks installed
module locations, guarded imports, pinned dependencies and installed MCP suites.
Use a fresh optional-artifact output directory; existing evidence is preserved.
These are local installation checks, separate from native backend conformance,
provider quality, hosted CI and registry publication.

## V5 installed-package manual pilot

[V5-PILOT-01](../examples/pilot_rag/README.md) installs the existing V5 core wheel
with its PostgreSQL extra into a separate application environment. From the
repository root, the verified initial setup is:

```sh
uv venv --python 3.14 examples/pilot_rag/.venv
uv pip install --python examples/pilot_rag/.venv/bin/python 'artifacts/V5/V5-08/full-core-frameworks/core/python/cragkit-0.0.0-py3-none-any.whl[postgres]'
uv run --project packages/python --frozen --no-sync python examples/pilot_rag/session.py --smoke
```

Omit `--smoke` to start the interactive CLI. The launcher explicitly provisions
disposable local PostgreSQL 17.11 with TLS and separate restricted reader/writer
roles, then runs the installed application with Python isolated mode. It closes
the setup administrator before opening the two max-one application pools and
verifies database cleanup on normal exit. No hosted target or inference provider
is used. Use `--corpus /absolute/private/pilot-corpus.json` for caller documents;
the [guide](../examples/pilot_rag/README.md) defines bounds and session lifetime.
The [manual checklist](../examples/pilot_rag/CHECKLIST.md) remains for human review.
See [actual pilot evidence](../evaluation/reports/V5/V5-PILOT-01.md); this is
exploratory feedback, separate from V6 release and independent usability gates.

## V6 release preregistration

[Decision 0004](decisions/0004-v6-release-freeze.md) freezes the candidate
configuration, independent metrics, input digests and limits before held-out
evaluation. The following command verifies configuration only and never opens
held-out labels. It cannot establish release readiness.

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_check_release_readiness.py tools/tests/test_benchmark_metrics.py -q
python3 tools/check_release_readiness.py
```

The [beginner release guide](open-source-release-guide.md) explains local
packages, CI and registry publication as separate steps. MIT is selected.
[The identity amendment](decisions/0005-release-candidate-identity.md) moves RC
metadata and local preparation to V6-02F; exact release artifact, license,
supported-install and CI acceptance remain V6-06 work.

## Native five-mode evaluation mechanics

The [EVX-r1 execution contract](../contracts/EVALUATION_EXECUTION_V6.md) keeps
reviewed labels out of native retrieval. The following focused checks use
synthetic input and no live provider calls. Run them serially:

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_retrieval_evaluation.py tools/tests/test_check_native_evaluation.py -q
node --test --test-concurrency=1 tools/tests/retrieval-evaluation.test.mjs tools/tests/provider_replay.test.mjs
```

The native check needs the existing prepared PostgreSQL 17.11/pgvector 0.8.0
prefix and an unused output directory. It starts and closes one disposable
database per language; it does not install PostgreSQL or a model:

```sh
uv run --project packages/python --frozen --no-sync python tools/check_native_evaluation.py --prepared-postgres-bin artifacts/V6/V6-02A/private-pg/prefix/Cellar/postgresql@17/17.11/bin --artifacts-dir artifacts/V6/V6-02D/native-mechanics-03 --allow-local-processes
```

Use a fresh directory when repeating that command. The checker validates source
bytes, scope, filters, strict context accounting and cleanup before comparing
the 30 result rows per runtime. See [actual execution evidence](../evaluation/reports/V6/V6-02D-execution.md).
This mechanics pass does not establish genuine embedding or reranking quality.

## Sealed evaluation packet binding

`tools/evaluation_packet.py` projects the original reviewed inputs into the
label-free EVX packet. Run the binding and release-checker regressions together:

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_evaluation_packet.py tools/tests/test_check_release_readiness.py -q
```

`bind_packet()` defaults to development rehearsal. `require_candidate=True`
requires matching clean source; held-out binding additionally requires explicit
`allow_held_out=True`. Neither option authorizes a provider call. Returned
provenance distinguishes source verification from compiled/runtime artifact
verification, which the live parent must perform separately. See
[the contract](../contracts/EVALUATION_PACKET_BINDING_V6.md) and
[actual evidence](../evaluation/reports/V6/V6-02D-packet.md).


## V6-03 resource and concurrency checks

The [RST-r1 contract](../contracts/RESOURCE_TESTING_V6.md) fixes the measurement
procedure. [Local acceptance](../evaluation/reports/V6/V6-03-resources.md) and
[raw numeric observations](../evaluation/reports/V6/V6-03-verification.json)
record exact candidate/tool identities, failed attempts, native recovery behavior
and platform limits. These commands measure already prepared environments; they
never install drivers, download models or call a real embedding provider.

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_measure_default_resources.py tools/tests/test_measure_native_resources.py tools/tests/test_resource_workload.py -q
node --test --test-concurrency=1 tools/tests/resource-workload.test.mjs
python3 -B tools/measure_default_resources.py --python-env artifacts/V6/resource-default/python-env --node-env artifacts/V6/resource-default/node-env --output artifacts/V6/resource-default/new-measurements.json
uv run --project packages/python --frozen --no-sync python -B tools/measure_native_resources.py --candidate-root artifacts/V6/recovery-candidate-rc1 --runtime-receipt artifacts/V6/recovery-candidate-rc1/artifacts/V6/recovery-runtime/runtime.json --prepared-postgres-bin artifacts/V6/V6-02A/private-pg/prefix/Cellar/postgresql@17/17.11/bin --output artifacts/V6/resource-native-new --allow-local-processes
```

Output paths must be fresh. The native command verifies the existing ECR receipt
before/after execution and starts disposable local TLS databases sequentially.
Credentials travel through bounded stdin, never argv or reports. The restricted
reader/writer logins each retain one backend slot; pool queue size remains one.
Node active cancellation destroys its frontend socket. The report separately
counts temporary acquisition refusals until an actual healthy query succeeds
under one five-second harness recovery deadline; this is not a library retry.

Preparation used a clean frozen candidate, Python 3.14.6 with offline wheel/core
dependency installation, and offline npm pack followed by bounded extraction and
receipt-verified Zod reuse. Existing development environments with optional
packages do not satisfy the default-import probe. Full preparation provenance
and exact archive digests are retained in the linked observations; rebuilding
for V6-06 remains a separate artifact/release gate.

V6-C1 ran the following serially: 3,825 Python/tool tests (four existing intentional
warnings), `npm --prefix packages/typescript test` (1,617 tests), and the 19
`check_core_pipeline.py` stages from schema-drift through sealed-input-integrity.
That selected checkpoint reused prepared dependencies with `--no-sync`; it did
not run the full install/artifact pipeline or hosted CI. Both original sealed
inputs and active recovery configuration remained unchanged. The focused new
harness suites passed 45 Python and 19 Node tests. Local native measurements
cover PostgreSQL only, not Qdrant throughput or a long-duration soak.


## V6-04 security and failure checks

[Security acceptance](../evaluation/reports/V6/V6-04-security.md) links the full
edge-case audit and numeric evidence. Reranker transports now cross through fresh
fixed operational errors. Only transport-declared availability/capability errors
qualify for the existing explicit fallback; an unknown error remains fatal to
that call. No retry or new wire code was added.

```sh
uv run --project packages/python --frozen --no-sync pytest packages/python/tests/test_reranking.py packages/python/tests/test_retrieval_evidence.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/reranking.test.mjs packages/typescript/tests/retrieval-evidence.test.mjs
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python -B tools/check_qdrant_security_guard.py --postgres-bin artifacts/V6/V6-02A/private-pg/prefix/Cellar/postgresql@17/17.11/bin --allow-local-processes --artifacts-dir artifacts/V6/V6-04/new-security-guard
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python -B tools/check_qdrant_publication_worker.py --postgres-bin artifacts/V6/V6-02A/private-pg/prefix/Cellar/postgresql@17/17.11/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --scenario supervisor_pause --runtime all --artifacts-dir artifacts/V6/V6-04/new-supervisor-pause
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python -B tools/check_qdrant_purge.py --postgres-bin artifacts/V6/V6-02A/private-pg/prefix/Cellar/postgresql@17/17.11/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V6/V6-04/new-purge
```

Run native commands serially with fresh output directories and the existing
verified binaries; they start disposable services and close them. No credential
or provider setup is needed. Full regression results: 3,843 Python/tool cases,
1,635 core Node cases, strict Python typing over 51 source files, and optional
LangChain 73/70 and MCP 41/36 Python/Node tests. Node tests include strict builds.
The initial MCP metadata mismatch was corrected through a frozen offline sync,
not by weakening its installed-version test. Current source differs from the
frozen V6-02 live candidate only through separately recorded subsequent changes;
its original live evidence is retained rather than relabelled.


## V6-05 installed pilot rehearsal

The [human protocol](usability-trial.md) and
[actual record](../evaluation/reports/V6/V6-05-usability.md) separate an unavailable
independent participant from the passing installed-package agent smoke. No manual
baseline, human timing or adoption claim exists. The guide's RC1 wheel names and
PostgreSQL override now match current metadata/options. From the repository root,
the actual offline correction and smoke were:

```sh
uv pip install --offline --python artifacts/V6/V6-05/pilot-env/bin/python --constraints artifacts/V6/V6-05/constraints.txt 'cragkit[postgres] @ file:///absolute/percent-encoded/path/cragkit-1.0.0rc1-py3-none-any.whl'
uv run --project packages/python --frozen --no-sync python -B examples/pilot_rag/session.py --python artifacts/V6/V6-05/pilot-env/bin/python --postgres-bin artifacts/V6/V6-02A/private-pg/prefix/Cellar/postgresql@17/17.11/bin --smoke
```

Create a fresh Python environment first and export the current frozen core extras
as constraints; select your inspected wheel and verified PostgreSQL17.11 binaries.
The absolute constraints filename failed when it contained the workspace's space;
the relative filename above succeeded. Isolated dry runs verified that absolute
interpreter and wheel paths were not the cause. The smoke passed21 checks with
no model calls and cleaned up its private database. Native/load work stopped
after subsequent swap growth; recheck stable headroom before another local run.

## V6-06 licensing, artifacts and CI

[Licensing preparation](../evaluation/reports/V6/V6-06-licensing.md) records
the earlier child checks. [Final V6-C2 acceptance](../evaluation/reports/V6/V6-C2.md)
records the later exact-artifact and actual hosted evidence. The six manifests declare
MIT and carry exact root LICENSE/NOTICE files. Core, framework and MCP artifact
tools now check licensing as well as their existing dependency/asset identities.
The [publishing guide](releasing.md) explains license, artifacts, CI, deployment
and the separate publication decision.

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_artifact_licensing.py tools/tests/test_check_artifacts.py tools/tests/test_check_qdrant_artifacts.py tools/tests/test_check_framework_artifacts.py -q
```

This passed 135 focused cases. Nine small offline preview archives also passed
actual license/notice layout checks. Their emitted metadata format is 2.5; the
helper accepts known PEP 639 formats 2.4–2.6 and rejects old/invalid formats. These
working-tree previews are not the clean final artifacts. During those serial
builds free memory was 47–48% and swapouts remained unchanged.

The manual-only [candidate workflow](../.github/workflows/candidate-validation.yml)
has pinned official action commits, a read-only repository token and one ARM64
macOS job with a 30-minute timeout. Its YAML and configured action inputs were
checked. The single user-approved private run passed against `0c7c568`;
[CI evidence](../evaluation/reports/V6/V6-06-ci.md) records its exact products,
runner, counts and three initial build-order skips. Those cases passed locally
after builds; an added future post-build step has not run in hosted CI. No further
run is authorized by that approval. Actual charges/free allowance remain unverified.
The repository is private and no package was published.

The two new offline checkers passed 32 focused tests; the final Python/tool suite
passed 3,968 with no skips and four intentional boundary-fixture warnings:

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_check_ci_bundle.py tools/tests/test_check_recorded_compatibility.py -q
uv run --project packages/python --frozen --no-sync pytest packages/python/tests tools/tests -q
```

Use the exact archive-audit command in the CI verification record and the explicit
[recorded-output bridge command](../evaluation/reports/V6/V6-06-compatibility.md)
for the locally retained candidate. The bridge preserves the historical ECR
identity, checks the new installed CI products separately and uses only sealed
recordings/fake providers. It cannot authorize HTTP inference. Local prepared
PostgreSQL binaries and stable headroom are required for its native checks.
Do not overwrite the original frozen candidate or treat the replay as new quality
evidence. All six default resource targets and twelve native checks per runtime
passed for these exact products; full details and limits are in the checkpoint.


## V6-07 backup recovery child checkpoint

The [backup rehearsal](../evaluation/reports/V6/V6-07-backup.md) passed on a
single disposable PostgreSQL cluster, using the exact installed CI core wheel
and Node dist. This completes child B; the [legacy upgrade/repair](migrations-and-recovery.md)
and parent V6-07 remain open. The result retains the MRR-r1 backup label;
[MRR-r2](../contracts/RECOVERY_REHEARSAL_V6.md) adds the separate legacy repair
without changing the backup lane's requirements.

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_check_backup_recovery.py -q
env -u PYTHONPATH -u PYTHONHOME -u NODE_PATH -u NODE_OPTIONS artifacts/V6/release-candidate-rc1/packages/python/.venv/bin/python -I -B tools/check_backup_recovery.py --sdk-root artifacts/V6/release-candidate-rc1/packages/typescript --prepared-postgres-bin artifacts/V6/V6-02A/private-pg/prefix/Cellar/postgresql@17/17.11/bin --output artifacts/V6/backup-recovery-verified --allow-local-processes
```

The executed output directory is retained; select a fresh directory to reproduce.
The focused suite passed 32 cases. All ten native recovery checks and five
source-access cases per runtime passed with zero HTTP calls and verified cleanup.
An isolated `--quarantine-probe` first verified the driver's missing startup
SQLSTATE; the corrected gate retains independent NOLOGIN, zero-session, exact
healthy-target and failed runtime-connection checks. No raw driver diagnostic
is accepted as report text. Pressure was 44-43 percent free, without swapout
increase. No hosted database or second paid CI job was used.
