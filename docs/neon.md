# Neon development database runbook

Task: DB-NEON-01. Follow the [migration plan](neon-migration-plan.md) and [tracker](../tasks/todo.md#db-neon-01-neon-migration) for authorization, target facts and acceptance state. This runbook describes the procedure; its commands are proposed Neon invocations until an evidence record reports their actual results. Previous [Supabase evidence](supabase.md) applies to its original target.

For example, an owner can read a document even when a normal retrieval login cannot. An owner query establishes connectivity, not tenant isolation.

## Target and data boundary

The user selected a new dedicated Cragkit development target in the VAIBHAV Free organization, Singapore, PostgreSQL 17. Record the exact organization/project/branch/database/endpoint identifiers and observed server version in the tracker after verification. Do not infer provisioning or native acceptance from this selection. Use synthetic fixtures only. Do not copy Supabase data or branch private data without a separate disclosure decision.

Before provisioning or testing, check current [Free-plan limits](https://neon.com/pricing) and the chosen organization's actual usage: compute, storage, branches, connections, suspend/resume and recovery window. Do not upgrade or enable additional services to bypass a limit. Record unavailable required controls as blockers. Neon Auth, Data API, Functions and AI Gateway are outside this migration. Keep the native optional `psycopg` and Node `pg` drivers; no driver replacement or Python server is needed.

## Direct verified connections and private configuration

Use the direct endpoint, without `-pooler`, for migrations and initial native acceptance. [Neon pooling](https://neon.com/docs/connect/connection-pooling) needs separate transaction-pooling acceptance before adoption. A connected control-plane SQL tool does not establish native driver reachability or certificate validation.

Use a protected private directory outside the checkout, such as `$HOME/.config/cragkit/neon`. Keep password files and the administrative runtime-check JSON owner-readable only, with mode `0600`; keep their parent directory private. Never put credentials or credential-bearing URLs in command arguments, tracked files, fixtures, reports or shell tracing. Use a private libpq password file rather than an inline password.

The [administrative runner](../tools/check_postgres.py) consumes these scalar environment values:

| Variable | Required value |
| --- | --- |
| `PGHOST` | Confirmed direct endpoint DNS name. |
| `PGPORT` | Confirmed port, normally `5432`. |
| `PGDATABASE`, `PGUSER` | Scalar database and migration/administrative login names. |
| `PGSSLMODE` | Exactly `verify-full`. |
| `PGSSLROOTCERT` | Existing local CA bundle file trusted for the endpoint. The runner requires a file; the literal `system` is not accepted. |
| `PGPASSFILE` | Absolute path to the private administrative password file. |

Obtain the trust bundle through a trusted source and validate the actual endpoint certificate and hostname. Encryption alone is insufficient. Do not switch to `require`, `prefer`, disabled validation or plaintext after a certificate error. The runner rejects service-file and host-address redirection, sets a ten-second connect timeout, and bounds statements, locks and the subprocess. The dedicated-target flag is an operator acknowledgment, not automatic production detection.

For the native harness, use a separate clean process environment with no nonempty `PG*` variables. Its owned-pool guard rejects them to prevent configuration overrides. The private JSON contains scalar `host`, `port`, `dbname`, `user`, and absolute string paths `sslrootcert` and `passfile`; no password or URI. These are administrative fixture-owner credentials, not application runtime configuration. The harness creates separate temporary runtime credentials and never passes administrator credentials to Node. Inspect [configuration validation](../packages/python/src/cragkit/_postgres_pool.py) before preparing the file. Do not print the private configuration or password file.

## Roles and default denial

[Neon's role documentation](https://neon.com/docs/manage/roles) states that Console, CLI and API-created roles receive `neon_superuser` membership. Treat those roles as administrative. Create restricted ingestion and retrieval roles with SQL, and inspect their effective memberships before granting application access. `NOINHERIT` alone does not rule out role assumption.

Keep migration/administrative credentials separate from ingestion and retrieval credentials. Runtime logins must have no superuser, RLS bypass, database/role creation, replication, broad predefined read/write membership, owner membership or route to assume an administrative role. Check direct and transitive memberships, including `neon_superuser`, `pg_read_all_data` and `pg_write_all_data`, and ownership of schemas, tables, functions and domains. Never use the project owner login in an application.

Start SQL-created runtime roles with no application object grants. Grant only the operations each role needs. Retrieval is read-only; ingestion privileges do not belong on the retrieval role. Schema/domain usage, migration-ledger reads, table grants and row policies need explicit review. Do not grant schema creation, DDL, TRUNCATE, role administration or unrestricted function execution to normal runtime roles. The existing runtime guards reject unsafe role attributes, ownership and retrieval writes; operator membership review remains necessary.

Keep `cragkit` private and RLS enabled on all nine current tables, including `migration_history`. With no runtime policies, rows remain denied by default. Explicit deployment hardening must revoke PUBLIC object privileges, review creator-specific default privileges and preserve unrelated schemas. The historical [Supabase hardening script](../storage/postgres/deployment/supabase.sql) is reference material, not proof of Neon deployment. Inspect the actual target's roles; absent Supabase API roles or advisors do not establish Neon security. Per-schema default revocations do not cancel global default grants. Recheck defaults and effective privileges after every object-creating migration.

Application code authenticates the caller and binds trusted scope outside agent-editable input. Transaction-local tenant/principal/grant/revision context complements fixed query predicates. Reauthorize source release after grant revocation or tombstoning. Do not introduce permissive permanent tenant policies merely to make a test pass.

## Explicit migration and security sequence

Inspect all scripts before execution on the confirmed unused development target. Core import, initialization and retrieval must not migrate or install extensions. Preserve existing migration bytes and the SHA-256 history ledger. The runner holds an advisory transaction lock, rejects unmanaged schemas, unknown checksums and history gaps, and rolls back failed application.

Proposed root commands after private administrative configuration is loaded:

```sh
python3 tools/check_postgres.py --apply --confirm-dedicated-target
python3 tools/check_postgres.py --apply --confirm-dedicated-target
python3 tools/check_postgres.py --check --confirm-dedicated-target --integration
```

The second application must leave checksums and original application timestamps unchanged. `--integration` executes [invariants.sql](../storage/postgres/tests/invariants.sql); it does not apply deployment hardening or run [security.sql](../storage/postgres/tests/security.sql). Execute reviewed hardening and security probes separately through a bounded administrative path with redacted failures and verified native TLS. Check the complete relation/function/domain ACLs, nine-table RLS inventory and migration ledger. Review probe role-creation privileges and fixture collision checks first. The security probe inserts synthetic rows, switches to a temporary nonowner role and rolls back its changes; it is not a persistent runtime login or positive tenant-policy test.

Inspect available `pgvector` versions without installing the extension as a side effect. Extension installation, vector tables and profile-specific storage remain subject to [V2-04](../tasks/versions/V2-hybrid-search.md#v2-04-vector-generations-and-reindex). Native PostgreSQL FTS remains the lexical method; it is not BM25.

## Native acceptance and cleanup

Inspect [development commands](development.md) and the [native fixture owner](../tools/check_python_postgres.py) before running. The fixture requires empty application tables and no existing Cragkit row policies. It temporarily changes schema shape, inserts synthetic content, creates narrow role-specific policies and uses a SQL-created expiring nonowner LOGIN role. Do not run it against an occupied database or an application using the target.

Potential compatibility blocker: the current harness supplies a client-generated SCRAM password verifier when creating its temporary role. Neon's [SQL role guidance](https://neon.com/docs/manage/roles#manage-roles-with-sql) says hashed passwords are unsupported. Resolve this against the actual target through the owning implementation lane before claiming acceptance; do not weaken authentication or substitute an owner login.

With optional drivers already prepared and TypeScript built using the verified development commands, proposed native invocations from a clean environment are:

```sh
uv run --project packages/python --frozen --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/python-runtime-check.json" --allow-test-writes
uv run --project packages/python --frozen --extra postgres python tools/check_python_postgres.py --config "$HOME/.config/cragkit/neon/python-runtime-check.json" --allow-test-writes --lifecycle
```

The first isolates Python session acceptance. The lifecycle invocation includes both native runtimes, ingestion, lexical retrieval and typed source-result checks, switching runtime pools serially. Do not run either concurrently with migrations, security probes or another integration suite. The harness limits the runtime pool to one and permits at most two native client connections including the fixture owner. Its lifecycle work budget is 600 seconds, Node lifecycle child budget 90 seconds and separate cleanup budget 25 seconds. Runtime checks use actual restricted logins; control-plane SQL alone is insufficient.

Record cross-tenant denial, same-tenant write rejection, principal/grant/revision predicates, grant revocation, immutable source/digest validation, update ordering, interrupted publication, deletion, same-connection scope reuse, bounded pool waits, deadlines, cancellation, rollback, schema restoration and connection cleanup. Use [E17-E25, E47, E51, E58, E66, E69 and E73-E75](../tasks/EDGE_CASES.md). Inspect coverage against actual harness output; do not infer an unexecuted probe from this checklist. Inspect plaintext rejection without sending a password, and treat endpoint suspension, allowance exhaustion and TLS failures as operational errors rather than missing evidence.

After each run, independently verify that synthetic rows, temporary role memberships, policies, grants and logins are gone; schema shape is restored; migration history is unchanged; and default-deny security probes still pass. Hard termination or cleanup failure requires manual inspection before retrying. Do not delete unrelated data or reset the database to repair a fixture. Close all task-owned clients and record resource observations.

## Evidence and cutover

Record commands actually run, native/direct endpoint and role configuration without secrets, fixture/tool revisions, results, remaining limitations and cleanup evidence. Separate local tests, administrative SQL, native Python, native Node, pooling and hosted CI. These checks do not establish live model quality, production readiness or universal absence of leakage.

Switch development configuration only after DB-NEON-01-B through E pass and any data-transfer decision is resolved. Preserve Supabase until cutover is verified; retirement needs separate authorization. Never recover by restoring stale permissions or automatically falling back to the old host. Record outstanding work in the tracker rather than advancing V2 product acceptance.

Failure case: a Console-created retrieval role may have administrative membership even if a connection succeeds. Reject that runtime configuration and test a SQL-created restricted role. Exercise: explain why certificate validation, authenticated LOGIN and tenant-policy denial require separate evidence.
