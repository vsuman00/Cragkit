# V5-04H changed bootstrap ACL checkpoint

This checkpoint covers frozen fault ID `bootstrap_acl_changed` in the actual
public publication manager. V5-04H and the complete 43-case matrix remain
open.

For example, the original stage binds initial grant `grant-a`. After the
document receives authorization revision `auth-manager-2`, a caller retries
that same published intent with a different initial grant and metadata tag.
The manager rejects the changed immutable payload as `IntegrityViolation`.
It does not restore the old ACL or change the active generation.

Both native consumers compare the exact persisted stage graph and document
ACL before and after the rejected call. They also count SQL mutation statements
and actual Qdrant HTTP requests. The current ACL, pointer and terminal intent
remain unchanged, with no new SQL/HTTP mutation. This extends the earlier
changed-payload test, which ran before the later security update.

The first local parent run reached result validation but failed because the new
check label was emitted out of the frozen order. The root integrator corrected
only the emitted check order in both consumers. The subsequent serial
PostgreSQL 17/Qdrant 1.20 run passed all 36 checks, 18 per runtime, and
verified task-owned cleanup. Both public snapshot hashes remained
`89319b18e0a39af96dc72d9d0db5ae4a56913e44e4f28d8922fefd134e40c61e`.
The accepted private result is
`artifacts/V5/V5-04H/bootstrap-both-final-01/results.json`.
The focused parent validation tests passed (4), and all 16 sealed inputs
matched. No product code, schema, grants, fixture, dependency, hosted service
or package release changed in this checkpoint.

Seven exact H fault IDs now have native evidence. The remaining matrix rows,
recovery process-death experiment, V5-04 parent acceptance and later V5 gates
remain open. Learning practice is unassessed: explain why an immutable
bootstrap grant cannot be replayed to undo a later authorization change.
