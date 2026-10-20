# Dedicated Supabase development target

For example, a successful administrative SQL query through the plugin does not show that a Python/libpq client verified the database hostname. Record those as separate checks.

Cragkit uses Supabase as hosted PostgreSQL. Native Python and TypeScript libraries retain their standard PostgreSQL adapter boundary; Supabase Auth, Data API, Storage and a required Python server are outside this setup. See [the architecture](architecture/ARCHITECTURE.md), [the migration contract](../storage/postgres/README.md) and [the tracker](../tasks/todo.md).

## Current evidence and pending setup

On 20 October 2026, root verified the user-created dedicated `Cragkit` project, reference `ksvzlzklspfghrhirogt` in Singapore (`ap-southeast-1`), in the existing organization, with `ACTIVE_HEALTHY` status and PostgreSQL 17.11 using UTF-8. This supersedes the earlier proposed Mumbai project; no new provisioning or cost action is needed for this target. Use this identified project rather than an unrelated existing project.

Root's read-only hosted preflight found no `cragkit` schema, no public or Cragkit application tables and no recorded Supabase migrations. The plugin session ran as administrative `postgres`, which was not a superuser but had role-creation and RLS-bypass attributes. Server SSL was enabled and the plugin SQL session used SSL. Root subsequently enabled the distinct dashboard SSL-enforcement setting and observed it enabled after the project restart. These observations do not prove a native client's certificate-chain or hostname verification or Data API configuration. Native connection environment and credential files were not configured at preflight.

Initial migration, rerun, history, relational, byte/digest, FTS and purge checks previously passed on a task-owned local PostgreSQL 17.11 Unix-socket cluster, including local deployment-hardening and transactional nonowner security probes. That cluster was stopped and removed. Root has now applied the initial migration and hardening to the dedicated hosted target. Hosted relational and security probes passed; at that initial checkpoint, the guarded initial-migration rerun retained one Cragkit ledger row and its original checksum and application timestamp. These administrative checks do not prove a hosted runtime role's positive authorization policy. See [the hosted evidence report](../evaluation/reports/V1/V1-01-H-hosted.md) for the actual records.

Hosted advisors initially identified a `regconfig` storage-type upgrade warning and four missing foreign-key indexes. The [second migration](../storage/postgres/migrations/0002_portable_lexical_config.sql) is now verified locally and applied on the hosted target: it stores configuration names as text, validates them through explicit casts when maintaining vectors, and adds three indexes covering all four foreign keys. Fresh application, a populated initial-schema upgrade, FTS preservation, reruns, configuration-change/rejection probes and security checks passed locally. Root removed the temporary cluster afterward. Hosted integrity/security reruns passed, the text column and three indexes were confirmed, and the initial migration checksum/timestamp were preserved.

Final hosted advisors report nine informational RLS-without-policy findings, matching deliberate default denial, and two unused GIN-index notices in the new empty database. The upgrade warning and missing-FK-index notices are resolved. Root confirmed all nine tables have RLS and all eight application tables remain empty. Data API is disabled. Authenticated native database access remains pending; transport and platform-setting results are recorded below.

The plugin's administrative SQL and advisor tools can inspect database configuration. Its currently available capabilities do not include SSL-enforcement or Data API settings controls. An authorized dashboard session may be needed to inspect and configure those settings. Do not record an unperformed dashboard action as complete, or treat an unavailable setting tool as proof of a secure default.

## Choose and identify the target

Use a dedicated development project and the private `cragkit` schema, with synthetic test data only. Confirm organization, project identity, selected region and cost before provisioning. Record PostgreSQL version, administrative role, connection mode, schema isolation and the exact migration revision; store no password or credential-bearing connection string in that evidence. The baseline lexical schema requires no vector extension, model runtime or provider account.

Use the project's Connect panel to obtain its actual host, port, database and user. Prefer the direct connection for migration and native PostgreSQL commands. When the development network cannot reach the direct endpoint, use the explicitly identified session pooler and verify it independently. Do not substitute transaction pooling for this administrative setup. Supabase documents direct endpoints as generally IPv6 and session pooling as an IPv4-compatible alternative; use the project's actual configuration rather than deriving an endpoint from an example. [Connection guidance](https://supabase.com/docs/guides/database/connecting-to-postgres).

## Keep the schema private

Do not expose `cragkit` through the Data API. Inspect the project's exposed-schema list; when the project uses no Data API, configure it disabled where available. Keep private-schema privileges absent for `PUBLIC`, `anon`, `authenticated` and `service_role`. The service role's RLS bypass makes privilege revocation necessary even when all tables have RLS enabled. Supabase distinguishes object grants from row policies; neither a private-sounding schema name nor RLS alone proves the API boundary. [API access controls](https://supabase.com/docs/guides/api/securing-your-api), [RLS behavior](https://supabase.com/docs/guides/database/postgres/row-level-security).

For this dedicated target, root changed the Enable Data API switch from enabled to disabled and saved it. A separate settings tab then explicitly reported "Data API is disabled". This is an observed platform configuration, in addition to the private-schema privilege checks.

After the initial migration, root explicitly applies [the deployment hardening SQL](../storage/postgres/deployment/supabase.sql). It revokes current API-role access in the `cragkit` schema, covers the current creator's per-schema defaults, and enables deny-by-default RLS on the application tables and migration ledger. It creates no broad runtime policy or permanent application login. It must not modify unrelated Supabase schemas or global default privileges.

Per-schema revocations do not erase global default privileges. In particular, future functions and types may inherit global defaults. Run hardening and the security probes again after any future object creation, and inspect effective privileges for that creator. Do not describe this deployment script as a universal guarantee for future objects or a substitute for reviewing each migration.

Keep administrative migration credentials separate from future application runtime credentials. The runtime role must not own the schema/tables, be a superuser, bypass RLS, inherit an administrative role or perform migrations. Its precise privileges, trusted transaction scope and policies belong to later adapter/access tasks. With no runtime policies now, ordinary runtime reads must remain denied or yield no rows; granting access to make a demonstration succeed would cross this phase's boundary.

## Configure a native administrative connection

Keep credentials in an approved secret store or a private libpq password file with owner-only permissions. Never place them in Git, shell command arguments, task reports, screenshots or logs. Do not print environment values. The migration runner uses libpq environment configuration and disables interactive password prompting; a private password file can supply credentials without embedding them in the command.

Configure these values privately for the approved target:

| Setting | Required meaning |
| --- | --- |
| `PGHOST` | One actual DNS host or IPv4 address; no socket path or multiple hosts in remote mode. |
| `PGPORT` | The project's actual direct or session-mode port. |
| `PGDATABASE`, `PGUSER` | Scalar database and administrative user names, with no URI or connection-parameter syntax. |
| `PGSSLMODE` | Exactly `verify-full`. |
| `PGSSLROOTCERT` | An existing CA certificate file obtained from the project's database SSL configuration. |
| `PGPASSFILE` | Optional path to the private owner-readable credential file; never commit its contents. |

The runner rejects `PGSERVICE`, `PGSERVICEFILE` and `PGHOSTADDR` redirection, URI/conninfo database values and multi-host/socket remote configuration. These restrictions prevent a service or encoded connection string from overriding the intended TLS/target settings. It sets a 10-second connection timeout, 30-second statement/idle-transaction bounds, 5-second lock timeout and 120-second subprocess bound. It verifies that its remote session actually uses TLS, while libpq `verify-full` checks the certificate chain and hostname.

Download the CA from the actual project's SSL configuration and keep the correct DNS hostname. `require` encrypts without hostname verification; `verify-ca` omits the hostname check. Do not silently reduce TLS verification when a connection fails. Diagnose endpoint, network, certificate and connection-mode configuration instead. Separately inspect and enable platform-side SSL enforcement where supported. A plugin-admin query is not evidence of this client's TLS path. [SSL modes and enforcement](https://supabase.com/docs/guides/platform/ssl-enforcement).

For this target, root obtained the dashboard CA and verified a PostgreSQL SSLRequest/TLS handshake to the actual direct DNS endpoint using Python SSL with `CERT_REQUIRED`, hostname checking and TLS 1.3. The session pooler rejected that same CA with `SSLCertVerificationError`; no verification downgrade or silent fallback was used. The direct endpoint is selected. Root also tested a plaintext startup without sending a password; the server rejected it with SQLSTATE `28000` and a no-encryption indication. This corroborates the observed SSL-enforcement setting on the tested direct path.

Owner-only CA and nonsecret target configuration were prepared outside the repository. The user saved a private password file; root verified its owner and mode `0600`. The native runner and bounded `psql` diagnostic reached password authentication failure with `verify-full` configured. No authenticated SQL session succeeded; the user must correct the saved project database password through the hidden prompt's explicit `--replace` option. The successful handshake proves this transport's certificate-chain/hostname verification; it does not prove database login or SQL privileges. Network restrictions currently allow all IPs; a restricted source allowlist has not been configured or verified.

The explicit `--local-socket` option is for isolated task-owned local tests only. It requires an absolute existing socket directory matching `PGHOST`, rejects redirection and cannot fall back to TCP. It is not a hosted connection workaround or evidence of remote TLS acceptance.

## Run and record acceptance

Root performs these commands only after target and credentials are configured and the administrative action is authorized:

```sh
python3 tools/check_postgres.py --apply --confirm-dedicated-target
python3 tools/check_postgres.py --apply --confirm-dedicated-target
python3 tools/check_postgres.py --check --confirm-dedicated-target
```

The first apply creates the checksummed migration history and schema. The second must leave already applied migration timestamps unchanged. The check must reject unknown, changed, missing or out-of-order history. Preserve the applied `0001_initial.sql` bytes; a later change needs its own reviewed migration.

An administrative plugin migration is a separate execution path. Before application DDL, root tested the actual endpoint with one multi-statement migration that created a task-only private probe schema/table and then divided by zero. The call failed with SQLSTATE `22012`; a separate catalog query confirmed both objects absent, and Supabase's migration history remained empty. No cleanup was required. This establishes rollback for the tested endpoint path, rather than inferring atomicity from the tool description or a multi-statement string.

For that verified path, root adapts the existing runner's generated SQL by removing only its outer `BEGIN`, trailing `COMMIT` and terminal success marker. Preserve every nested DO/function block, the advisory lock, timeouts, history checks, exact initial DDL and checksummed ledger insert together within the endpoint transaction. Keep Supabase's migration history separate from `cragkit.migration_history`; a second endpoint call can add a Supabase record even when the inner Cragkit migration is correctly skipped. Record actual application and rerun results separately from the endpoint rollback probe.

After both migrations, root reran the complete guarded script on the hosted target. Both Cragkit ledger rows retained their checksums and timestamps. Supabase recorded five migration audit entries across these deployment operations; those are separate from the two Cragkit schema versions.

Before adding application data, run the explicit empty-target integration check:

```sh
python3 tools/check_postgres.py --check --confirm-dedicated-target --integration
```

It locks and rejects nonempty application tables before writing synthetic fixtures, tests scoped keys and integrity invariants, rolls back, and checks that application tables remain empty. Never truncate or reset a nonempty target to satisfy this check.

Then apply the deployment hardening script and run [the security probes](../storage/postgres/tests/security.sql) through root's bounded, redacted administrative execution path. Inspect the scripts before execution; do not pass a DSN to `psql` or copy raw database error output into reports. The probe's temporary `cragkit_security_probe` role is a transaction-scoped test fixture: it has no login, superuser or RLS-bypass privilege, receives narrow temporary grants, and is rolled back. Its deny-by-default results do not provision a usable runtime login or prove future tenant policies.

Record migration hashes/rerun results, application-table rollback purity, effective API-role privileges, RLS flags/policies, role ownership/membership, security-definer status, security advisor findings, actual connection mode and native TLS evidence. Dashboard SSL enforcement and Data API exposure need their own observed results. Keep plugin-admin, local-cluster, native hosted-client and future runtime-role evidence separate. One test process runs at a time; start no local services for hosted checks.

V1-01 stays incomplete until required hosted acceptance is recorded. No V1-02 pool adapter, permissive RLS policy, new auth flow or production-readiness claim follows from this runbook.

Learning remains pending. One failure case is a native client that connects with encryption but skips hostname verification: the plugin's successful SQL response cannot close that gap. Exercise: explain which check proves object privileges, which proves row denial, and which proves the native client's TLS identity verification.
