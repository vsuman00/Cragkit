# Verified PostgreSQL connections on Neon

For example, a TLS connection that encrypts traffic but accepts the wrong hostname does not establish the intended database identity. Reject certificate or hostname failures without downgrading verification.

Neon is a PostgreSQL hosting option for applications using the native optional drivers. Historical direct development acceptance is retained privately; it does not approve another target, connection pooling or production deployment. This guide contains no personal project/endpoint configuration. Follow [storage](../storage/postgres/README.md), [operations](v5-operations.md) and [production security](production-security.md).

## Configure a target explicitly

The application/operator owns provisioning, credentials, data disclosure and costs. Inspect current service limits and account usage before provisioning; do not upgrade or enable unrelated services to bypass a limit. No Neon Auth, Data API, Functions, AI Gateway or alternate driver is required by Cragkit.

Use the direct endpoint for migrations and initial native acceptance. Transaction pooling needs separate acceptance. An administrative/control-plane SQL result cannot establish native Python/Node driver reachability or transport verification.

Keep private scalar connection configuration, password files and certificate paths outside the repository. Use owner-only private files and avoid connection strings or passwords in arguments, logs or chat. PostgreSQL uses `PGSSLMODE=verify-full` and a trusted CA; Node must enforce equivalent certificate and hostname verification. Do not recover from an error by using plaintext or disabling TLS checks.

## Apply least privilege and migrations

Separate schema/history ownership, ingestion and retrieval roles. Retrieval must not use an owner, superuser, BYPASSRLS or transitive administrative membership. Apply required tenant/collection/principal/grant predicates and deny access by default. Keep immutable checksummed migrations and optional profile setup under explicit operator control; imports never migrate.

The public migration tools use current SQL operational checks under `storage/postgres/deployment/checks/` for invariants, security and vectors. These are operator checks, separate from the private regression suites. The tools require explicit dedicated-target admission. Follow their current help and [storage instructions](../storage/postgres/README.md), not a personal historical configuration. The `--confirm-dedicated-target` flag is an acknowledgment, not production detection.

Neon's accepted managed-vector-primitive exception permits its platform-owned scalar functions/types while keeping private schema and ledger access restricted. Select that profile explicitly only for the reviewed target; the strict default rejects unexpected PUBLIC function/type privileges. The exception grants no access to application rows and does not replace runtime RLS or creator-default-ACL review.

## Verify before use

Run native integration only against an explicitly owned disposable target with recorded cleanup. Serialize Python and Node suites; bound pools, connections, statements, waits and deadlines. Use synthetic data and real restricted login roles. Test cross-tenant denial, same-tenant write refusal, grant revocation, tombstones, immutable source/digest checks, interrupted publication, repeated scoped connections, cancellation and rollback.

Keep integration harness, fixtures and actual receipts in the private maintainer workbench described in [development](development.md#private-maintainer-verification). A missing harness is a missing check, not permission to infer a pass. TLS, allowance, endpoint and pool errors remain operational failures rather than missing evidence. Record native/direct transport, configuration without secrets, source identity, results and cleanup separately from pooling, live models or production claims.
