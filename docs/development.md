# Cragkit development

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

Hosted Supabase PostgreSQL is the selected development database. Provisioning, credentials and connectivity remain pending. No dedicated target or schema has been verified, and no database connection was attempted for this baseline. Before any hosted test, verify a dedicated nonproduction target, connection mode, privileges, isolated schema/test data and required extension versions. Keep credentials and credential-bearing URLs out of reports and fixtures. Local PostgreSQL or Docker installation is optional and was not needed for V0-01. See the resource report for the full isolation checklist.

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

For hosted Supabase, first identify a dedicated development project and confirm a direct or session connection suitable for administrative work. Configure scalar `PGHOST`, `PGDATABASE`, `PGUSER`, a protected password source, `PGSSLMODE=verify-full` and the downloaded certificate path in `PGSSLROOTCERT`. Service files, connection-string database values and host redirection are rejected by this initial developer runner. The dedicated-target flag is an operator acknowledgment; it does not detect a production database. The hosted invocation omits `--local-socket`:

```sh
python3 tools/check_postgres.py --apply --confirm-dedicated-target --integration
python3 tools/check_postgres.py --check --confirm-dedicated-target --integration
```

Hosted commands are prepared, not verified. No Cragkit project or connection configuration was available during this session. Project provisioning/cost selection, certificate verification, actual role privileges and Supabase advisors remain pending. Existing unrelated projects were not modified. Administrative local tests use a privileged role; they do not prove least-privilege runtime access, pool behavior or RLS policy isolation. See [Supabase connections](https://supabase.com/docs/guides/database/connecting-to-postgres) and [PostgreSQL TLS verification](https://www.postgresql.org/docs/current/libpq-ssl.html).


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
