# Cragkit development

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
python3 tools/check_v0.py
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
python3 tools/check_v0.py --artifacts-dir artifacts/V2/V2-C1-final
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
python3 tools/check_v0.py --artifacts-dir artifacts/V2/V2-04-final
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
python3 tools/check_v0.py --artifacts-dir artifacts/V2/V2-05-final
```

The explicit dense native fixture provisions only temporary restricted roles/policies and synthetic records on the accepted empty dedicated target. It reuses the optional profile/setup grants, holds at most two native clients including the owner, closes Python before Node and accepts only fixed local owner actions. No administrator credential reaches the child. Do native checks before the final frozen default checkpoint removes optional Python drivers; restore only the locked postgres extra if needed.

The 15-stage serial checkpoint adds canonical SQL and seven shared mathematical reference cases. Those reference cases validate geometry and SQL parity; the native fixture executes the real ranking in both runtimes. Exact search scans the authorized filtered set and has no HNSW/IVFFlat index or measured large-corpus performance guarantee. Fake-vector ordering is not model-quality evidence. [V2-05 report](../evaluation/reports/V2/V2-05.md) records actual results and limitations. Exercise: with limit one, explain why a required document filter must run before choosing the closest vector.

## V2-06 exact identifiers and rank fusion

For example, `ERR_CONN-42` is one exact, case-sensitive identifier even when FTS splits punctuation. The internal scoped handle adds `identifier_candidates`; both native ingestion paths populate the existing identifier array. [IF-r1](../contracts/IDENTIFIER_FUSION_V2.md) specifies the ASCII heuristic, strict query shape, scoped SQL and weighted reciprocal rank fusion. Old immutable generations are not backfilled: use a new ingestion intent to populate their tokens.

Pure fusion uses distinct ranks, keeps raw scores as provenance, normalizes family weights per facet and retains each family's best rank across attempts. With equal dense/lexical weights, rank 1 in both lists scores `1/61`; rank 1 in only one scores `0.5/61`. Duplicate entries cannot add votes. A union above the declared global ceiling fails explicitly; V2-07 will budget branch fan-out before fusion. Positive votes that underflow to zero also fail. These are ranking values, not relevance probabilities.

Run from the root, serially:

```sh
uv run --project packages/python --frozen --no-sync pytest packages/python/tests/test_fusion.py packages/python/tests/test_postgres_identifiers.py tools/tests/test_check_identifier_fusion.py tools/tests/test_check_v0.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/fusion.test.mjs packages/typescript/tests/postgres-identifiers.test.mjs
uv run --project packages/python --frozen --no-sync python tools/check_identifier_fusion.py
uv sync --project packages/python --frozen --extra postgres
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --dense --typescript
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --vectors --typescript
python3 tools/check_v0.py --artifacts-dir artifacts/V2/V2-06-final
```

The dense native fixture now includes actual identifier storage/search, scope and filters before limits, grant-only access, source revocation/tombstones, common snapshots and actual three-branch fusion arithmetic in both runtimes. The vector fixture separately asserts that Node lexical and vector writers populate exact arrays. They use only synthetic data, restricted temporary roles, fixed owner actions and at most two database clients; their Node children receive restricted configuration only. The base legacy fixture has a separate administrator-negative check design under security follow-up; do not generalize these children's credential boundary to every harness.

The serial checkpoint has 16 stages, including actual extraction/fusion/provenance parity. Native checks run before its default frozen install removes optional Python drivers. [The V2-06 report](../evaluation/reports/V2/V2-06.md) records results and limitations. Public `PostgresRetriever` stays lexical until V2-07. Optional exercise: add a repeated family list to the three-document shared fixture and predict which ranks change without gaining an extra vote.

## V2-07 hybrid orchestration and V2-08 evaluation

For example, a dense SQL failure raises by default. With trusted `allow_degraded=True` in Python or `allow_degraded: true` in Node, hybrid mode can roll back the failed branch to a savepoint, search the remaining branches in the same snapshot and return `execution: degraded`. An authorization error, deadline, corrupt source or broken savepoint remains fatal.

The optional PostgreSQL `PostgresRetriever` now accepts trusted constructor configuration for `mode` (`lexical`, `dense`, `hybrid`), `embedder`, `allow_degraded` and `identifiers`. The default remains lexical. Dense/hybrid require a configured `EmbeddingAdapter` under the provisioned synthetic profile; no adapter is created implicitly. [HY-r1](../contracts/HYBRID_V2.md) defines validation, invocation accounting, branch budgets, diagnostics and source reauthorization. Node exports the `RetrieverOptions` type from `cragkit/postgres`. Call the existing retrieve method with a separately bound trusted scope and absolute deadline.

Dense/hybrid reserve one embedding boundary invocation before a candidate lease. They run one original query/attempt, at most three serial branch families, at most 40 candidates per branch and a global ceiling of min(request limit,200). Tiny hybrid ceilings below the planned family count fail before provider/DB work. Budgets are divided before execution; failures cannot gain retries or expand the surviving branches. Only an explicitly enabled hybrid policy recovers `ProviderUnavailable`/`UnsupportedCapability` from individual branches or embedding. Source release always uses a fresh scoped transaction.

Run the following from the repository root, one command at a time:

```sh
uv run --project packages/python --frozen --no-sync pytest packages/python/tests/test_hybrid.py packages/python/tests/test_hybrid_savepoint.py packages/python/tests/test_role_guards.py tools/tests/test_v2_metrics.py tools/tests/test_check_hybrid_contract.py tools/tests/test_check_python_postgres.py tools/tests/test_check_v0.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/hybrid.test.mjs packages/typescript/tests/hybrid-savepoint.test.mjs packages/typescript/tests/role-guards.test.mjs
uv run --project packages/python --frozen --no-sync python tools/check_hybrid_contract.py
uv sync --project packages/python --frozen --extra postgres
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --hybrid --typescript
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --typescript
python3 tools/check_v0.py --artifacts-dir artifacts/V2/V2-exit
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
python3 tools/check_v0.py --artifacts-dir artifacts/V3/V3-02/final
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
uv run --project packages/python --frozen pytest packages/python/tests/test_evidence.py packages/python/tests/test_retrieval_v3.py -q
npm --prefix packages/typescript run build
node --test --test-concurrency=1 packages/typescript/tests/evidence.test.mjs packages/typescript/tests/retrieval-v3.test.mjs
uv run --project packages/python --frozen python tools/check_evidence_pipeline.py
uv sync --project packages/python --frozen --extra postgres
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon --hybrid --evidence --typescript
```

Constructor options are policy, counter, rebalance, surrounding_bytes, reranker, rerank_fallback and rerank_limit (1-40, default 40). Only the application binds these values. Strict requests need an issued cl100k counter and matching tokenizer identity. Optional reranking closes the first authorized source lease before dispatch and fetches fresh authorization afterward. Source reads share 16 MiB across both rounds. Token usage/live cost cannot be invented; strict live spend ceilings are unsupported at this boundary.

## V3 frozen calibration and replay

The [frozen protocol](../evaluation/policies/V3-reviewed-span-v1.json) compares the same two authorized development candidates before and after reranking. [Observed results](../evaluation/reports/V3/V3-07.md) include raw-score recordings, independent label-based false-sufficient checks and separate pre-packing/packed metrics. The five hosted calls already completed; routine work must replay them rather than redispatch.

```sh
uv run --project packages/python --frozen pytest tools/tests/test_v3_calibration.py tools/tests/test_run_v3_calibration.py -q
node --test --test-concurrency=1 packages/typescript/tests/calibration-replay.test.mjs
```

`tools/run_v3_calibration.py` refuses dispatch without `--allow-live`. Its explicit baseline/output arguments select a verified native baseline and task-owned report. A new live run requires its own recorded budget/rationale; it is not part of routine acceptance. Parent-bounded serial children read the private Cohere key, retain redacted call/failure accounting and never retry automatically. Node replay takes an explicit `--replay` local public JSON payload and never accesses credentials or the network.

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
uv run --project packages/python --frozen --no-sync --extra qdrant pytest packages/python/tests/test_qdrant.py packages/python/tests/test_qdrant_transport.py packages/python/tests/test_qdrant_embeddings.py tools/tests/test_check_qdrant.py tools/tests/test_qdrant_dense_example.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant mypy --config-file packages/python/pyproject.toml packages/python/src
```

In `packages/typescript`, run `npm run build`, then `node --test --test-concurrency=1 tests/qdrant.test.mjs tests/qdrant-transport.test.mjs tests/qdrant-embeddings.test.mjs`. The optional Python extra pins HTTPX 0.28.1. Node uses its built-in fetch; no Qdrant SDK or model runtime is installed. Neither module import starts a service or connects to a database.

An administrator explicitly acquires and verifies a supported Qdrant server binary. The current macOS arm64 reference is 1.20.0; acquisition evidence is in [V5-02A](../evaluation/reports/V5/V5-02A.md). No library import or native checker downloads it. After building Node and installing the Python extra, the verified isolated integration command is:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant python tools/check_qdrant.py --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --artifacts-dir artifacts/V5/native-candidates
```

The checker creates one owned loopback process, private administrative/read-only keys and eight synthetic points. It runs the native runtimes serially and compares all returned nominations and ledger snapshots. It verifies write denial for the read-only key, deletes its collection, confirms an empty inventory, terminates the process and removes private config/data. Generated artifacts contain synthetic records only. Explicit clients must close the store and then their owned transport; borrowed resources are not closed by the store. Remote endpoints require verified HTTPS. Plain HTTP is allowed only for explicitly configured `127.0.0.1` or `::1` development endpoints; proxy/TLS bypass settings are unsupported.

The [dense composition examples](../examples/qdrant_dense.md) connect E-r1 batch output to candidate search and preserve separate provider/candidate work. After Node build, the root command `node --test --test-concurrency=1 tools/test_qdrant_dense_example.mjs` checks their accounting and cancellation. The Python example checks are included in the focused command above. Real-profile tests inject routing spies; they make no paid calls or real-profile writes.

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
python3 tools/check_v0.py --artifacts-dir artifacts/V4/checkpoint-core
```

It runs 27 stages, including complete execution, planning, corrective and event parity. Clean installed archives also run the 44 V4 shared state-machine cases outside the checkout. The optional framework packages have separate environments; they are not installed by this core command. Internal core archives retain version 0.0.0; V4 is an implementation milestone, and public alpha publication remains separate.

Event exporters are cooperative async application callbacks. Retrieval only queues events; call `flush` explicitly outside its critical path with an absolute monotonic deadline. No implementation can make a synchronously blocking application callback cooperative. Shared sinks expose cumulative counters; generated trace IDs separate concurrent requests without storing request text. The final result's events snapshot is a point-in-time view of that shared queue, not a per-request delivery receipt.

### Optional V4 framework verification

The separate `packages/langchain-python` project pins LangChain Core 1.7.0; `packages/langchain-typescript` pins `@langchain/core` 1.3.0 and LangSmith 0.11.1. Their locks include SDK dependencies; core manifests remain framework-free. See [the adapter guide](integrations/langchain.md).

```sh
python3 tools/check_v4.py --artifacts-dir artifacts/V4/acceptance
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
