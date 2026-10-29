# V5 current-security SQL guard (SG-r2)

Status: SQL IMPLEMENTED AND VERIFIED under SG-r2; [G2b2d1 evidence](../evaluation/reports/V5/V5-04G2b2d1.md) records 23 native SQL checks. Runtime profile-4 admission, genuine guarded graph validation and receipt settlement remain TARGET dependencies. The [D0 counterexample](../evaluation/reports/V5/V5-04G2b2d0.md) establishes the need for same-transaction lock custody. It does not implement or validate this guard. Previous migrations remain unchanged, and library imports never apply this migration.

For example, the supervisor locks current authorization and settles retired writes in one transaction. A later authorization change waits for that transaction's commit or abort. An independently lost source-reader connection cannot release its lock.

G2b2d1 first supplies the additive SQL migration and actual restricted-role/operator acceptance. Exact profile-4 native runtime admission, genuine guarded graph validation and same-session receipt settlement follow as dependent tasks. Do not mark G2 or V5 complete from SQL-only acceptance. Existing stage receipts, source release, public APIs and logical security-update independence remain protected.

## Selected boundary

Add `0004_security_settlement_guard.sql` and one private `cragkit_qdrant.lock_current_security` function. Keep migrations 0001-0003 byte-for-byte unchanged. The function performs static metadata checks and backend -> owner -> document row locking. It returns `void`; it does not settle journals, return document fields, release sources, inspect vectors or assert physical Qdrant proof.

Use a dedicated role named `cragkit_qdrant_security_guard`, with NOLOGIN, NOSUPERUSER, NOBYPASSRLS, NOCREATEDB, NOCREATEROLE, NOREPLICATION and NOINHERIT. It owns exactly this function, no schema/table/type/database, and has no outbound role memberships. It must not be a member of writer or supervisor. Existing `lock_publication_owner` cannot be called as this role: its recovery branch tests `current_user` for supervisor membership (`0002_publication.sql:380-418`). Duplicating its small static metadata/lock sequence is preferable to giving the definer that broader role.

The function is PL/pgSQL, SECURITY DEFINER, VOLATILE, PARALLEL UNSAFE, not LEAKPROOF, and CALLED ON NULL INPUT. Do not mark it STRICT: nullable tuple fields are meaningful, while null required arguments must raise instead of silently skipping the guard. Set `search_path=pg_catalog` and `row_security=on`; qualify every application relation and every catalog reference. Use no dynamic SQL, untrusted routine call, exception-swallowing block or transaction control. PUBLIC receives no EXECUTE. The supervisor capability receives EXECUTE on this exact signature without grant option; writer and reader receive none.

## Frozen SQL argument contract (SG-r2)

Use built-in types and this fixed order, rather than adding a composite type or JSON decoder:

```text
lock_current_security(
  p_instance_id text,
  p_backend_namespace text,
  p_storage_identity text,
  p_supervisor_id text,
  p_recovery_id text,
  p_backend_epoch bigint,
  p_tenant_id text,
  p_collection text,
  p_document_id text,
  p_owner_intent_id text,
  p_owner_token uuid,
  p_security_intent_id text,
  p_security_payload_sha256 text,
  p_active_generation_id text,
  p_authorization_revision text,
  p_mutation_epoch bigint,
  p_principal_ids text[],
  p_grant_ids text[],
  p_language text,
  p_kind text,
  p_tag text,
  p_tombstoned boolean
) RETURNS void
```

Only active generation and language/kind/tag are nullable. Validate the existing SQL identity/collection/sha/count/metadata bounds, nonzero backend epoch and mutation epoch, and bounded canonical ACL arrays before locking. Accept ordinary one-dimensional arrays with lower bound one, plus the ordinary empty array; reject null members, duplicates and noncanonical unsigned UTF-8 order. Existing native writers store `_acl(...)` in that order (`_qdrant_writer.py:185-186,1972-1973`). Compare stored arrays exactly, including order. A noncanonical stored representation fails closed; do not silently repair it in this helper. This stricter representation check needs an explicit fixture case because existing graph projection also canonicalizes its exposed ACLs.

No credential generation argument is needed: the backend table has no such fact. No inventory hash substitutes for full graph validation. Those remain receipt/runtime checks.

## Caller and role authentication

PostgreSQL's function ACL checks the effective caller before the SECURITY DEFINER switch. Inside the function, `current_user` is the dedicated guard owner; it is not the caller. Authenticate the session principal using `session_user`, and require `current_setting('role', true) = 'none'`. Accept only an actual LOGIN principal with inherited USAGE of `cragkit_qdrant_supervisor`, no writer or guard membership, no administrative/bypass/built-in broad-data memberships, and no ownership or CREATE privilege in the protected schema. Mirror the existing supervisor admission restrictions using that explicit principal, including database-owner exclusion. Check both the principal's own attributes and unsafe reachable memberships. Do not use `row_security_active` under the definer as a substitute for evaluating the caller's privileges.

Require the safe NOLOGIN supervisor capability itself and the dedicated guard role's accepted ownership/membership/ACL shape. Reject effective caller SET ROLE, direct writer/reader, an administrative login using SET ROLE to a supervisor, and a nonsupervisor login entering through another definer. A nested definer called by an already authorized supervisor login does not prove a different principal; the session checks plus the exact helper ACL and complete argument/durable checks remain the boundary. No text argument claiming a caller name or boolean `authorized` is accepted. Database administrators remain trusted; a superuser that deliberately changes session authorization is outside a runtime-role security claim.

Require supplied instance ID to equal the existing transaction-local `cragkit_qdrant.backend_instance_id`. The GUC is an instance selector, not role authentication. The helper must never broaden the existing supervisor instance profile or set a new arbitrary instance for the caller.

## Minimum grants and explicit FORCE RLS policies

Grant the guard owner schema USAGE, selected columns below, and only the listed UPDATE column needed for row-lock permission. PostgreSQL 17 requires UPDATE on at least one column for SELECT FOR UPDATE/SHARE. No table-level SELECT/UPDATE grant is necessary.

| Table | SELECT columns | UPDATE column used only to permit locks |
| --- | --- | --- |
| `backend_instances` | instance_id, backend_namespace, storage_identity, supervisor_id, epoch, state, recovery_id | epoch |
| `document_owners` | tenant_id, collection, document_id, instance_id, intent_id, owner_token, backend_epoch | backend_epoch |
| `documents` | tenant_id, collection, document_id, active_generation_id, authorization_revision, mutation_epoch, principal_ids, grant_ids, language, kind, tag, tombstoned | mutation_epoch |
| `publication_intents` | tenant_id, collection, document_id, intent_id, instance_id, action, payload_sha256, expected_mutation_epoch, authority_committed | none |

Do not grant payload_bytes, manifest_bytes, request_bytes, canonical_utf8, excerpt_utf8 or replay/vector columns. Grant no INSERT, DELETE, TRUNCATE, REFERENCES or TRIGGER. Grant no journal access. The guard role also receives EXECUTE on exactly three existing read-only invoker routines: `scope_visible(text,text,text[],text[],text,boolean)`, `scope_grants()` and `valid_identity_array(text[])`. The existing PUBLIC document SELECT policy evaluates these dependencies even when the guard's own policy admits the row. Actual PostgreSQL probes refused locking without these grants; granting only the first two still failed when scope GUCs exercised the third. These functions read caller settings or validate supplied data; they expose no source rows or mutation capability. No existing function body/policy or supervisor direct-read grant changes. The guard role executes no other application routine except its own owned guard.

Add seven named policies, each exclusively `TO cragkit_qdrant_security_guard`: SELECT and UPDATE on backend, owner and document; SELECT on intents. Backend/owner/intent predicates require row instance ID equal to the existing backend-instance GUC. Document predicates use a nonrecursive EXISTS against `document_owners` matching the document's complete tenant/collection/document key and that selected instance. Owner policies read no document table, so this introduces no policy recursion. The function's own WHERE clauses always include its exact arguments; RLS does not replace those predicates.

Each UPDATE policy has the same bounded USING predicate and explicit `WITH CHECK (false)`. SELECT FOR UPDATE/SHARE applies visibility/locking policy checks, while an actual UPDATE must satisfy the new-row check and is refused. Prove this exact policy shape natively. Existing writer/reader/supervisor policies and privileges are unchanged. The dedicated role has no memberships that could activate an alternative permissive UPDATE policy. FORCE RLS stays enabled on all existing tables.

This adds restricted metadata visibility to the dedicated definer, not the supervisor. Its fixed function is the only runtime entry point; its trusted maintenance membership is described below. No new mutable guard-scope GUCs or additional SECURITY DEFINER routines are required.

## Exact locking and comparison

1. Require READ COMMITTED, valid caller/role/profile, bounded arguments and the matching selected instance. Reject unsupported isolation before locks.
2. Lock the exact backend row FOR SHARE, then reread and compare namespace, storage identity, supervisor identity, epoch, `recovery_blocked` and recovery ID. An absent row or mismatch fails closed.
3. Lock the exact document-owner row FOR UPDATE. Reread it and require the supplied instance, historical intent/token and current backend epoch. This child requires the already advanced owner; it does not advance or replace ownership.
4. Lock the exact document row FOR UPDATE. After any wait, reread backend, owner and document in separate statements, and repeat every binding check. Compare the complete nine-field current document tuple using null-safe equality.
5. Read the supplied historical owner intent and require its exact document/instance binding and `action='stage'`. Read the distinct security intent and require the same document/instance, action in `update_authorization`/`tombstone`, authority_committed true, exact payload SHA-256 and `expected_mutation_epoch = p_mutation_epoch - 1`. For tombstone action require the expected tombstone true. Its immutable payload hash binds the already writer-validated canonical intent; the helper has no payload-byte access and does not claim to parse that payload.
6. Return void. All row locks remain owned by the invoking supervisor transaction through its actual commit/abort. Do not catch a guard error inside the product transaction and continue settlement.

Use generic bounded errors without revealing which tuple member differed. Distinguish invalid input/profile (22023), unauthorized caller (42501) and failed durable guard (23514) with SQL-only acceptance asserting these exact states; native runtime mapping follows in D2. Do not log parameters or return current values.

The later native coordinator must reconstruct the complete graph through a genuine guarded nonlocking writer path while the supervisor transaction remains active. Ordinary writer projection keeps its existing document lock. The private guard must be invalidated on transaction exit, client release/destruction or rollback, including rollback to a savepoint predating the guard. Do not expose raw clients, arbitrary callbacks, a public `lock=False` option or a transferable SQL-result token. This writer/coordinator work is a separate child; D1 SQL acceptance alone grants no settlement authority.

## Non-superuser migration ownership and maintenance

Select a documented operator profile: a trusted migration role that owns the protected schema and existing tables, has CREATEROLE, is neither SUPERUSER nor BYPASSRLS, and is never a runtime role or reachable from runtime roles. Exact operator naming is deployment configuration; derive and verify its OID against the schema/table owners, not a caller GUC. Hosted accounts without these powers require explicit administrator provisioning; portability does not mean every hosted login can apply this migration.

PostgreSQL 17 creates a bootstrap-superuser-granted membership from the new role to its non-superuser creator with ADMIN TRUE, SET FALSE, INHERIT FALSE. The creator cannot remove that grant. Therefore a final state with no inbound membership is incompatible with this installation route. Accept only inbound membership rows whose member is the exact trusted migration/schema owner: the automatic bootstrap grant, plus its explicit self-granted SET TRUE/INHERIT FALSE membership. Retain both for future maintenance. The explicit self-grant does not need ADMIN TRUE because the automatic edge already supplies it. Check grantor and option values, not only the set of member names. Permit no other inbound member and no indirect runtime path to the migration owner. The guard role itself has no outbound membership.

Within the administrator wrapper's single transaction:

1. Verify exact three-entry history, old catalog and role/ownership baseline. Fail if the dedicated role already exists; do not adopt a cluster-global name silently. Require `current_user=session_user` for the chosen direct migration-operator profile.
2. Create the dedicated role with all explicit safe attributes. Set a transaction-local `createrole_self_grant` policy or verify it is empty so host defaults cannot add unexpected INHERIT/SET edges; then grant the explicit self SET membership with INHERIT FALSE. Verify the resulting membership rows.
3. Grant the dedicated role schema USAGE and temporary schema CREATE. Add exact column grants and seven policies as the table owner. Create the function, revoke PUBLIC execution immediately within the transaction, and grant exact supervisor EXECUTE.
4. ALTER FUNCTION OWNER to the dedicated role. The operator needs SET ability to the new owner, and the new owner needs schema CREATE for this transfer. Revoke its CREATE before commit; leave only USAGE. Do not grant schema/table ownership to the definer.
5. Inspect final role, owner, effective ACLs, policies, function attributes/body and absence of unexpected memberships/objects. Record 0004's actual checksum in the same transaction and commit. On any failure roll back role creation, membership, grants, policies, function and ledger together.

Retaining only the trusted operator's admin/self-SET edges preserves future upgrades without an assumed superuser rescue. A later operator may temporarily restore schema CREATE when ownership transfer/recreation requires it, perform reviewed maintenance, then revoke it in the same transaction. No permanent CREATE or inherited runtime authority is needed. This is a trust boundary: the operator already controls the protected schema and can change its policies/functions.

## Catalog profiles and minimum acceptance sequence

Current source/recovery/writer admission cannot accept 0004 unchanged. `_qdrant_authority.py:96-119` and `qdrant-authority.ts:45-61` forbid every SECURITY DEFINER routine and fingerprint all policies/functions. Recovery has an exact executable-function allowlist (`_qdrant_recovery.py:45-101`). The history query currently reads at most four rows; profile 4 must read a fifth overflow row to reject an unknown suffix.

Add a separate exact four-entry history/fingerprint profile, retaining previous profiles for their existing supported operations. It allows exactly this one definer signature/body/configuration and no other definer. Because the existing fingerprint excludes owners and named grants, add separate exact dedicated-owner/membership/effective-column-ACL checks. Do not merely remove the old `NOT prosecdef` test. Only the new recovery profile admits the additional supervisor EXECUTE. Writer/source roles gain no new privilege, but their catalog/history selectors must understand the accepted profile before native product integration. Keep older databases explicit; guard-dependent operations require profile 4.

Smallest next slice is SQL migration plus rollback-only schema/permission acceptance. Use a fixture administrator only to bootstrap the exact non-superuser migration operator and preexisting fixture. Execute 0004 itself as that operator with `current_user=session_user`, NOSUPERUSER/NOBYPASSRLS confirmed, and record final automatic/self-granted membership rows. Capture the new fingerprint only after positive lock and negative privilege checks pass. In a separate transaction force rollback and compare complete role/membership/schema/default-ACL/history baselines, including no leaked dedicated role. Test preexisting-name refusal and failure after ownership transfer.

Then verify actual restricted supervisor login can call the exact guard and direct document/source/request/vector SELECT still fails; writer/reader/PUBLIC and SET ROLE callers cannot call it; wrong instance/owner/intent/hash/tuple/isolation and null/oversized/noncanonical inputs fail; UPDATE-as-guard is denied while lock-as-guard succeeds; post-wait rereads reject changed authority; same-transaction COMMIT/abort/connection-loss owns the lock correctly. Reuse D0's COMMIT barrier to show authority changes wait through supervisor COMMIT and cannot reproduce its stale-settlement ordering. Inject extra grants, owner changes, unsafe membership and additional definer functions and require profile rejection.

Later runtime/receipt integration remains separate. Preserve current-credential uncertainty and foreign global blocks, no recovery upserts, no public convergence and no HTTP inside the SQL lease. Acceptance of this artifact is not acceptance of SQL, migration portability, physical proof or G2 completion.


## D2a: Native authority profile-4 foundation

Implement the accepted four-entry history and observed catalog from `fixtures/qdrant_security_guard_catalog.json`, without changing any migration. Both history queries read five rows so an unknown suffix cannot be hidden. Legacy profiles 1-3 keep their exact histories, fingerprints and prohibition of all definers. Profile 4 permits exactly the frozen `lock_current_security` signature/body/configuration with its dedicated owner, plus all existing constraints, trigger and FORCE RLS checks. An extra or altered definer remains unsupported.

Add a standalone read-only system-catalog predicate for the dedicated owner/operator memberships, safe attributes, exact function ownership/ACL, schema rights, absence of extra owned objects, complete effective table/column/function grants and supervisor capability shape. Match the frozen SG-r2 role and three read-only policy dependencies; the schema fingerprint alone cannot validate named grants/owners. Query only public metadata and return one boolean; a reader must not execute the guard to inspect it. Run this predicate during profile-4 authority initialization and each subsequent source-read lease. Recheck the exact four-entry history/fingerprint when validating that profile on a read, so added migrations, altered bodies and later grant drift fail closed before source SQL. Existing trusted scope/filter/excerpt behavior and borrowed resource lifetime stay unchanged.

Python shared internal constants are `EXPECTED_SECURITY_GUARD_HISTORY`, `EXPECTED_SECURITY_GUARD_CATALOG_FINGERPRINT`, `_SECURITY_GUARD_CATALOG_SQL` and `_SECURITY_GUARD_OWNER_SQL`. Node counterparts are `AUTHORITY_SECURITY_GUARD_HISTORY`, `EXPECTED_SECURITY_GUARD_AUTHORITY_FINGERPRINT`, `AUTHORITY_SECURITY_GUARD_CATALOG_SQL` and `SECURITY_GUARD_OWNER_SQL`. They contain pinned metadata, not runtime file reads or SQL side effects on import. Preserve a clear unsupported boundary for writer/recovery until D2b handles this profile explicitly; shared profile enums may name it, but no fallback to an older admission profile is allowed.

Acceptance requires old-profile regressions, exact profile-4 positive admission, fifth-row/malformed history rejection, wrong hash/extra-definer/body/config/owner/ACL/membership refusals, and permission drift after initialization. Native readers in both runtimes must initialize the actual four-migration fixture, return honest absence for its unpublished sources and reject a committed unsafe guard grant before source SQL; restoration permits the safe read again. Fake-driver tests are wiring evidence only. No migration application, new source permission, public guard API, HTTP/model call or settlement is introduced in this foundation.

### D2b1 writer admission

Native writer admission may accept the exact D2a four-entry history with the same catalog fingerprint, structural predicate and complete owner predicate. This adds no writer grant and never calls the SQL guard. The existing attestation writer role map applies unchanged; profile 4 retains every profile-3 preparation/attestation requirement. Legacy profile-2/3 behavior remains supported.

On every profile-4 writer lease, before scope binding or business SQL, revalidate exact history, catalog/fingerprint and owner permissions as well as the restricted writer role. A fifth row, downgrade or malformed metadata fails closed. Once profile 4 is admitted, reinitialization cannot downgrade it. A profile change requires explicit reinitialization rather than silently changing a live writer. Native writer selection stays private to the writer; source publication selectors used by recovery continue rejecting profile 4 until D2b2. No migration, recovery/settlement, public graph-lock bypass or resource-lifetime change belongs to D2b1.

Acceptance includes exact admission, grant/LOGIN/catalog/history drift before business SQL, strict scalar results, restored access, preserved profile-3 attestation behavior, and actual restricted PostgreSQL writer initialization/current-security projection after explicit 0004 installation in both runtimes.

### D2b2 recovery admission

Native recovery may accept the exact four-migration profile with the same pinned catalog, structural predicate and complete guard-owner predicate. Its profile-4 supervisor role map differs from the existing map only by permitting EXECUTE on the exact lock_current_security signature. It receives no direct source/document/vector privilege. Admission never invokes that function; guarded settlement is a later task.

Check exact bounded history on every recovery transaction before backend binding or business SQL. Require the initialized profile except during explicit initialization. Revalidate all profile-4 catalog/fingerprint/owner metadata on every transaction, before the role check so an extra function remains an unsupported catalog even if it changes executable privileges. Strict native scalar results are required. Successful profile-4 admission prevents later downgrade, including failed reinitialization; live profile changes require explicit reinitialization. Profile 4 retains all attestation-profile recovery behavior. Legacy 2/3 remain supported. Preserve exact lost-COMMIT read-only confirmation, cancellation, proof/session identity and resource ownership.

Acceptance requires native restricted supervisor profile-4 initialization and genuine recovery/source/readback receipt flow in both runtimes, plus committed guard source-grant, LOGIN, fifth-history and extra-definer faults rejected before backend binding on owner advance, with exact restoration. Existing three-profile native receipt acceptance remains supported. No guard invocation, guarded graph capability, new journal settlement behavior or public API is added here.

### D3-r1: transaction-owned guarded graph validation

D3 adds a fixed internal `validate_security_guarded(recovery, security_verifier, proof, owner_context, security_context, deadline/options, security_readback_budget?) -> void` driver. It is not a package/public manager export. A real Recovery constructor registers the private driver closure; the helper resolves that original instance and accepts no callback, client, transaction, caller projection, receipt factory or locking flag. Require admitted profile 4, the original writer/supervisor/verifier registrations, matching trusted scope/document and distinct historical owner/security intent contexts.

The driver owns one Recovery operation and genuine control facade. It calls the nominal SecurityVerifier under that facade, completing HTTP readback, handle close and ordinary locked source validation before opening supervisor SQL. Open the genuine receipt with the exact verifier invocation options; its projection supplies the current tuple and security intent digest. Inside the admitted READ COMMITTED transaction, execute the exact 22-argument `SELECT true FROM cragkit_qdrant.lock_current_security(...)`, using original physical proof and historical owner binding, and require one native boolean true. No HTTP, controller RPC or application callback runs inside this SQL lease.

After successful guard acknowledgment, Recovery alone issues a nominal opaque guard token. Its module-private weak registry binds the original Recovery/writer/supervisor/verifier/resources, real transaction invocation identity and client wrapper, original control facade/proof/receipt/projection, full contexts/current tuple, deadline and cancellation state. No general mint/register API is exported. A writer-facing internal read-only `security_guard_binding` validates the token and returns only frozen target/projection metadata, never a client, transaction, facade, mutable lifetime or callback. Copies, proxies, wrong issuer/writer/projection/document/intent/scope and expired tokens fail before writer SQL. Python additionally binds the owning inner task and rejects another task or pending cancellation.

The fixed writer consumer accepts that actual token and original nominal projection, checks their identity before admission and around all database continuations, then reads the document without a row lock on its original restricted writer resource. Compare the exact nine-field tuple to the guard-bound tuple and run the complete existing security graph loader. Extract loader code after document acquisition; normal project/validate paths retain their existing locks. The guarded path must not indirectly take backend/owner/document row locks or call a lock-taking publication helper. It retains scope/profile/role checks, raw claim/replay inventories, overflow, all size/member/generation bounds, original stage reconstruction, canonical spans/excerpts, complete profiles/vector replay/seals, manifest bytes/hashes and current payloads. Counts or inventory hashes cannot replace reconstruction. Compare all declared projection facts; preserve the existing treatment of freshly issued Python vector identities. This consumer returns void and issues no new projection/receipt.

The guard record separates verifier/operation options from the derived supervisor pool lease signal and any derived writer signal. Use the exact verifier options to open the receipt, while checking both operation and actual supervisor lease cancellation for custody. Never substitute a derived signal into the original receipt accessor. No deadline extension is accepted. Require the original transaction invocation and active status at statement boundaries (Python INTRANS/2, Node T); released/null/idle/error/unknown status rejects. No savepoint, rollback/re-BEGIN, reconnect or transaction-control callback is permitted inside the fixed guarded body.

Set private `guard_required` before submitting guard SQL. Failure poisons this guarded transaction even if accidentally caught. Only successful guard SQL admits guarded reading; only full writer validation followed by fresh receipt/proof/activity and transaction checks marks it validated. Revoke token use immediately on cancellation/client release and when graph work ends, before rollback or COMMIT. Immediately before constructing the same-client COMMIT query, synchronously check original and lease deadline/signals, client status/transaction identity, validated/unpoisoned state and unchanged receipt/proof/activity. There is no intervening application await. A required-but-unvalidated or poisoned operation cannot COMMIT. Do not depend on `bounded(client.query(...))` to check before query construction.

Permission to continue and ownership of started callbacks are separate. Node's outer `withLease` promise can reject before its callback unwinds. The guarded writer and supervisor paths must track the actual callbacks through transaction cleanup. Invalidation is immediate; active ownership lasts until actual drainage. Use an owned inner scope/task that retains Recovery/control-session and writer admission. Bound the external caller by original deadline/cancellation and established cleanup allowance. If bounded drainage fails, report failure, latch the owner closed/poisoned and retain the observed inner scope until actual callbacks finish. Never return from the inner control callback or clear active ownership merely because an outer race rejected. Late work cannot validate, submit business SQL/COMMIT or change failure into success. Close may fail within its bound while that poisoned owner remains reserved. No PoolResource-wide redesign belongs to D3. Python guarded writer work remains inline in its recorded inner owner task.

Map native SQLSTATE only at the exact guard invocation: 42501 to UnauthorizedScope, 22023 to UnsupportedCapability and 23514 stale/mismatched guard to UnauthorizedScope. Preserve deadline/cancellation and redact other operational failures as ProviderUnavailable. Do not inspect error messages or change unrelated constraint mappings. Local malformed inputs remain InvalidRequest; corrupted graph/source/vector/manifest/inventory remains IntegrityViolation.

D3 returns no reusable validation fact, changes no journal/owner/document state and adds no mutation retry. D4 must place its fixed settlement body after this validation in the same supervisor transaction and same facade; it must not settle in a later transaction using D3 success. A lost read-only D3 COMMIT acknowledgment cannot be called durable settlement. Future exact lost-settlement-COMMIT confirmation must read the original intended journal identities/bindings/digest without discovering a new set or retrying DML under expired validation.

D3 acceptance includes actual guard plus nonlocking full graph without self-deadlock; observed concurrent document lock wait and release; post-wait authority mismatch; late canonical/vector/manifest/raw inventory corruption; copied/wrong/expired token and signal/task failures; actual supervisor connection loss; and Node early lease rejection with noncooperative callback drainage retaining real control ownership, including failed bounded drainage. Exercise cancellation around guard acknowledgment, graph completion and COMMIT construction. Preserve ordinary locking, old-profile regressions and restricted grants. Native clients/services must be explicitly bounded; structural doubles do not replace connection-loss/SQL-lock evidence. D3 establishes no security settlement, convergence, purge or production readiness.

D3b native mode extends the existing security-verification checker with explicit `--guarded-graph` requiring `--with-security-guard`. Its private envelope adds only `guard_graph_config: {admin_config}`; generated fixture credentials remain private. Keep existing modes unchanged. Reuse the same receipt fixture: validate live graphs outside its first control session, before tombstoning; run authority-wait/loss cases after its original eight checks. Add a closed `guarded_graph` result containing ordered checks and `denied_commits: 0`. Checks, in order: `actual_guard_nonlocking_full_graph`, `document_lock_wait_observed_until_guard_commit`, `late_canonical_drift_refused`, `late_vector_drift_refused`, `late_manifest_drift_refused`, `extra_raw_claim_refused`, `post_wait_authority_mismatch_refused`, `supervisor_connection_loss_releases_document_without_commit`, `late_callback_retains_control_and_writer_until_drained`.

Budget four actual SQL clients (original writer, supervisor, contender writer and fixture admin observer) and seven server slots; close the earlier operator before opening the admin observer. A fixture-only admin may inject and restore committed corruption using transaction-local replica mode, preserving catalog/migration bytes. Inject after verifier readback and before guarded graph validation. Observe actual `pg_locks` waits; use genuine native authority mutation for the post-wait stale tuple. Actual supervisor resource closure during a delayed native graph callback must terminate its backend and release the document; preserve delayed callback ownership until release and prove no supervisor COMMIT is submitted. Never count a fake connection as this native loss case. No new dependency, generic harness framework or public API is needed.
