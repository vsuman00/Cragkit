# V4 readiness recheck

Historical snapshot of f91eb37. V4-AUD-01 and V4-AUD-02 were subsequently completed; see [current verification and timing-profile limits](V4-SECURITY-VERIFICATION.md). The original assessment below is preserved.

## Decision

V5-01 can begin as a design task. V4's recorded internal native/synthetic feature milestone remains accepted, with two newer operational follow-ups open. Resolve them before V5 backend implementation and its next native database acceptance run. This sequencing recommendation does not turn an unproven cleanup cause into a confirmed product vulnerability.

The review input was the local, untracked `evaluation/reports/AUDIT-V2-V4.md`, an independent audit of f91eb37. It and the two original security reports were preserved without edits or staging. Its reported database failures were not reproduced during this recheck.

## Remaining work

| Task | Finding | Acceptance needed |
| --- | --- | --- |
| V4-AUD-02 | Cleanup loses useful diagnostics. In `tools/check_python_postgres.py`, operation errors collapse to `cleanup_failed` around lines 556-566. | Preserve a bounded, redacted operation label, error category and SQLSTATE when available, including cleanup timeout/connection failures. Test that credentials, raw SQL and private text cannot enter the report. Preserve the original failure separately from cleanup failure. |
| V4-AUD-01 | Interrupted hybrid acceptance can leave task-owned fixture resources, as reported by the audit. The cleanup path around lines 511-566 reuses the administrator connection and does not provide bounded retry/recovery after failure. Its exact observed failure cause is unproven. | Add deterministic interruption/failure tests and bounded, repeatable recovery of exact task-owned resources. Verify no fixture rows, policies, roles or lock remain after recovery; preserve histories and unrelated data. A killed process or unavailable database needs an explicit resumable recovery path rather than a promise that cleanup always runs. |

Both tasks are OPEN, not implemented or revalidated by this review. Start with V4-AUD-02 to make the reliability failure diagnosable. Existing fixture wait-budget and sibling dense cleanup tests do not prove parent hybrid cleanup recovery.

For example, if a cleanup connection fails, a later retry must identify the exact unfinished fixture and converge safely when connectivity returns. A broad deletion by name prefix would not establish ownership and is not an acceptable recovery policy.

## Evidence checked

Root and a managed Sol pair inspected the governing plans, tracker, exit report, source, relevant tests and saved acceptance artifacts. The harness peer verified source behavior and assembled; the exit peer checked plan prerequisites and recorded evidence. Peers coordinated their conclusions directly. No material disagreement required Astra.

All 14 recorded implementation/lock hashes still match current files. The saved final acceptance log ends with 34 passed stages; core and optional artifact reports record passed states. The saved native run records 18 checks and cleanup verified. These establish the recorded successful runs; they do not disprove the newer failure reports or establish the live database's current state. No product tests, provider calls, database connections, installs or services ran during this review.

V5-01's prerequisite, V4-08, is satisfied. Its first output is the alternative-store consistency specification: source authority, generation manifest, publication barrier, sparse encoder identity and ACL synchronization, including a failure table for each write boundary. Qdrant implementation depends on acceptance of that specification. See [the V5 plan](../../../tasks/versions/V5-integrations.md).

Live model quality, hosted CI, production, pooled endpoints, cross-platform acceptance and public release remain outside the accepted internal V4 milestone; they are not newly discovered missing V4 feature tasks. Learning practice remains optional and unassessed. See [V4 exit evidence](V4-08-exit.md) and [the tracker](../../../tasks/todo.md).
