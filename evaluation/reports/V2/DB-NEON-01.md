# DB-NEON-01: Neon migration evidence

22 October 2026. COMPLETE for direct-endpoint development and native lexical acceptance. Follow [the tracker](../../../tasks/todo.md#db-neon-01-neon-migration) and [the plan](../../../docs/neon-migration-plan.md) for dependencies. This report separates local tooling, administrative SQL, native runtime checks and development cutover. Vector storage remains V2-04; pooling and production acceptance remain separate.

## Scope and target

The user authorized execution using the Neon skill/plugin, security tests and a new dedicated Cragkit development project in VAIBHAV's Free organization, Singapore, PostgreSQL 17. The existing untracked V1 security evaluation is unrelated and excluded.

The Neon plugin provisioned project `muddy-boat-55325449`, default branch `br-square-surf-b3nra8du` named `development`, database `cragkit`, administrative role `cragkit_admin` and direct endpoint `ep-plain-queen-b37i9a2b`. Native SQL reports PostgreSQL 17.11 and UTF8. Endpoint configuration limits compute to 0.25 CU. Preflight found no Cragkit schema or application tables and advertised pgvector 0.8.0. Only synthetic fixtures are permitted; no Supabase data was copied or deleted.

The first provisioning request failed with HTTP 412 because Free does not permit changing the suspend interval. A re-list found no newly created project. A second request omitted that setting and succeeded. The API reports zero for its suspend field; current official Free documentation requires five-minute scale-to-zero, so this field is not proof of always-on operation. No plan upgrade or extra service was enabled. Current plan limits and platform controls were checked through the plugin's official plans documentation; paid private networking, IP allowlisting and an uptime SLA are not Free acceptance claims.

## Coordination and document alignment

Two `gpt-6.1-sol` peers contributed disjoint artifacts under the project coordinate/manager protocol. One produced the Neon runbook and assembled the pair; the other updated development/storage guidance and reviewed native/security tooling. Root owned target operations, shared documentation, tracker, combined tests and Git. Both peers reviewed each other's concrete interfaces and stopped writing before integration.

DB-NEON-01-A passed 269 local Markdown target checks across 12 changed documents, whitespace checks and self-contained prose inspection/cleaning. Historical Supabase results retain their original target and scope. The documentation change was committed and pushed as `866bbf9` before provisioning.

## Transport and credential handling

The plugin's backend SQL session reports SSL off. Neon terminates external TLS at its proxy; a backend flag is not evidence of the native client's transport. The Neon-specific tools require actual native client TLS, a direct validated host and certificate/hostname verification. Existing non-Neon checks retain their previous behavior.

The plugin returned a pooled credential URI. The private importer rejected that target without writing credential files. Root selected the independently listed direct hostname and Cragkit's fixed native verify-full policy. The provider URL's optional channel-binding suggestion is not configured or claimed; the importer rejects unsupported query options rather than claiming to enforce them.

Credentials entered a hidden terminal prompt, never shell arguments or printed output. The importer wrote an escaped password file and password-free configuration JSON with mode 0600 in an owned mode-0700 directory outside the checkout. It pins host, database, login and port, rejects control bytes and unsafe URI options, and refuses existing or symlink outputs. Synthetic tests cover those rejection and preservation paths. Hidden input acceptance is capped at 16 KiB after the prompt reads it; this is not a hard interactive input-allocation bound.

Actual native transport checks passed: direct libpq verify-full with the system trust bundle; exact database/admin identity; rejection of an unrelated valid CA before SQL; and plaintext startup rejection without sending a password. The local native driver was initially unavailable. Frozen uv sync restored the three already-pinned optional psycopg packages; no manifest or lock changed.

## Administrative acceptance

The explicit Neon wrapper reuses the existing migration builder, checksums and ledger. It validates private scalar configuration and client TLS before SQL, bounds connection/statements/locks/overall work, drains result sets and requires exact success markers. Errors contain safe stage/type/SQLSTATE fields, not rendered statements or provider text. Deployment hardening revokes PUBLIC access/defaults within the private schema and enables RLS on all nine current tables without creating an application role or permissive policy.

Actual commands from the project root:

```sh
uv sync --project packages/python --frozen --extra postgres
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_neon_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --confirm-dedicated-target --apply --harden --integration --security --allow-test-writes
```

The administrative command passed twice. Independent plugin reads before/after the rerun found identical migration checksums and application timestamps. Existing integrity and default-deny security probes passed and rolled back their synthetic rows and nonowner probe role. No pgvector installation or vector table was included; V2-04 retains that dependency.

## Native runtime acceptance

The test fixture has an explicit Neon mode for its host's SQL password requirements. It sends an in-memory generated password only after native TLS proof; normal runtime credentials are distinct from administrator credentials, expire and are removed after tests. A native Node check proved actual authorized TLS at the existing driver factory before guarded leases hide the socket. The library interface does not expose raw sockets or credentials.

The first Node probe rejected a TLS assertion made on the intentionally guarded connection view. A regression now instruments the existing owned driver factory and destroys clients with missing/unverified TLS. The corrected native Node session suite passed seven groups: real runtime login/RLS, scope rollback/reuse, borrowed pool ownership, queued cancellation, observed-query deadline/abort, schema rejection/restoration and unsafe administrator rejection.

The first Python session run timed out during cancellation work. Independent cleanup found zero probe roles, policies, collections/documents or renamed columns. A minimal native diagnostic observed the server statement timeout and prompt task cancellation; it did not establish a slow-driver root cause. Source review found fixture waits shorter than the original request deadline plus declared cleanup budgets, and an assumption that cancellation must preserve the physical connection. The fixture now waits within those explicit budgets and permits a replacement connection after cancellation while still requiring cleared scope and fresh authorization. Safe subphase markers and regression tests cover these changes. The final revised Python session suite passed eight groups with cleanup. No core deadline or authorization behavior changed.

The combined Python/Node ingestion, lexical retrieval and lifecycle run passed 32 groups with verified cleanup. These include cross-tenant and same-tenant write denial, exact UTF-8 spans, stale compare-and-swap, interrupted publication, cancellation rollback, hidden ready transitions, cross-runtime writes/reads, scope/filter/limit checks, revocation before source release, source-corruption refusal, late updates, deletion and hidden-child purge. Together the three runs passed 47 native groups; their coverage overlaps.

Native commands actually run, serially, after the administrative preparation above:

```sh
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --typescript --neon
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --neon
uv run --project packages/python --frozen --no-sync --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/admin-config.json" --allow-test-writes --lifecycle --neon
```

The final Python session run followed the fixture timing correction. The combined lifecycle run preceded that correction and bypasses the modified session-only path. Runtime pools were limited to one, with at most two native connections including the fixture owner.

## Final regression and security evidence

| Check actually run | Result |
| --- | --- |
| `uv run --project packages/python --frozen --no-sync --extra postgres pytest packages/python/tests tools/tests -q` | 598 passed |
| `npm test` in `packages/typescript` | 499 passed, including build |
| `npm run typecheck` in `packages/typescript` | Passed |
| `uv run --project packages/python --frozen --no-sync mypy --config-file packages/python/pyproject.toml packages/python/src` | Passed, 16 source files |
| `python3 tools/check_seal.py` | All 16 sealed inputs unchanged |
| Final administrative `--check --integration --security --allow-test-writes` with the same target/configuration flags | Passed |

Three real negative probes independently introduced a PUBLIC schema grant, disabled collection RLS, and a SECURITY DEFINER function. The existing security probe rejected each specific mutation. Each transaction rolled back; the clean security baseline then passed.

Independent plugin catalog checks after the native runs found zero application rows, temporary probe roles, policies or SECURITY DEFINER functions; all nine tables had RLS enabled and the migration advisory lock was available. No pgvector extension was installed. Both migration ledger entries retained identical checksums and original application timestamps across repeated application. No migration bytes, core runtime source, manifests, locks or sealed inputs changed.

Final documentation checks passed for nine documents: 230 local file targets, 69 anchors, zero suspicious Unicode characters and unchanged deterministic-cleaner output. Prose density was low (scores 0.0325–0.1225). Owned changed files passed the live Neon credential/private-key pattern review and whitespace checks. These are scoped checks, not proof that every possible secret format is detectable.

## Development cutover and handoff

The verified private development fixture configuration now points to the dedicated direct Neon endpoint. This is administrative test-owner configuration outside Git; applications must supply their own restricted roles and scoped policies. No permanent application login or permissive policy was installed. The target began empty, so no data transfer was required. Supabase resources and historical evidence were preserved; retirement was not performed.

Two Sol peers reviewed the transport, credential importer and administrative tooling, with no blocking finding remaining after integration. Default privileges depend on the executing object owner and must be rechecked after ownership or migration changes. Hard termination can interrupt fixture cleanup and requires manual inspection. Final resource observations were 28 GiB available disk and 63% system memory free. No task-owned service, model download or background process remains.

Next smallest product task: V2-04, explicit pgvector installation, generation storage and reindex acceptance. Learning remains pending; exercise: explain why a successful owner connection cannot establish tenant isolation, and why a cancelled request may safely replace its connection only after scope is reset and reauthorized.

No live model call, model-quality evaluation, hosted CI, package publication, pooling acceptance or production readiness is part of this migration. Scoped passing tests cannot establish universal absence of security issues or leakage.
