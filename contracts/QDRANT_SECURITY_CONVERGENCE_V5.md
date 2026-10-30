# Public current-security convergence

Revision: QSC-r1. G2c implementation contract; acceptance belongs to the tracker.

For example, an authority-only update changes authorization immediately. A
later `converge_security` call repairs every claimed replica to that current
authorization, then records replica completion after authenticated readback.

## API and prerequisites

Add `QdrantPublicationManager.converge_security(reference, scope, ledger,
deadline/options)`. The reference has exactly collection, document_id and
intent_id, using the existing native reference contract. The result retains
the existing manager fields and uses operation `converge_security`.
`QdrantSecurityManager` continues to admit authority independently.

Require the exact profile-5 writer, a matching native recovery coordinator and
managed supervisor. Reject worker-only, missing-recovery and older profiles
before the authorizer or storage checkout. Python uses its existing deadline;
Node propagates its original AbortSignal. Charge one shared logical attempt,
zero provider calls, and one shared bounded SecurityReadbackBudget throughout.

Accept a committed update_authorization intent. Tombstone convergence belongs
to G3 and is unsupported here. After fresh application authorization, exact
completed historical retries return their durable flags without new physical
work. An incomplete intent must match the current security projection; never
restore historical authorization or an old active-generation pointer.

## Ordered execution

1. Snapshot current backend, document, intent and actual owner under the bound
   trusted scope. Reauthorize through the manager's existing callback.
2. If ownerless, require an open backend and no pending target journal, then
   admit the genuine current security owner with a fresh token. A blocked
   ownerless document remains operationally unavailable.
3. Preserve the actual owner's intent and token. Use current trusted scope
   with those immutable owner facts. Recover the instance using its existing
   recovery ID when blocked; otherwise derive a stable g2 ID from the exact
   instance and current backend epoch. Every recover invocation genuinely
   refences credentials, including retries within an existing blocked epoch.
4. Advance that owner through the actual proof. Dispatch current complete
   point payloads using the accepted private security path and the fresh
   application authorizer. Reconcile only that owner's eligible retired
   journals under a genuine guarded current-security receipt. Preserve foreign
   target and unrelated-document pending work; no scope invention is allowed.
5. Reopen only through durable global settlement. Hand off to the current
   security intent, preserving an existing matching token on exact retries.
   Issue a genuine ordinary attempt and obtain exact full current readback.
6. Under the original controller finalization, reauthorize and complete only
   the security intent through its accepted writer transaction. Hold manager
   admission until actual callbacks and cleanup drain. Close the manager-owned
   security verifier; borrowed dependencies retain their caller-owned lifetime.

All waits share the caller deadline. A failure after authority admission leaves
that admission committed. Unknown physical effects stay durable and require
actual refencing on an explicit retry. There are no background jobs, permission
expansion, new source revisions, model calls or automatic retry loops.

## Acceptance

Focused tests cover malformed references, scope and action mismatch, exact
historical retry, ownerless and previous/current owner cases, callback denial,
deadline/cancellation, late callback drainage, budgets and borrowed lifetime.
Native tests use actual PostgreSQL and Qdrant in each runtime: repeat authority
updates, ownerless stage denial, lost completed HTTP acknowledgment followed
by actual refencing and successful retry, changed authority/tombstone during
convergence, and source release under current allowed and revoked scopes.
Keep direct authority admission independent while replica work is blocked.
Compare semantic outcomes across runtimes and verify all task-owned cleanup.
