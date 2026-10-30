# V5-04H partial member checkpoint

This checkpoint covers frozen fault ID `partial_member_stage` against the
actual Python and TypeScript publication managers. V5-04H and the full
43-case matrix remain open.

For example, a generation manifest declares two members, but a persisted
graph contains only one. The public stage transaction normally commits the
intent, source, members and claims together. The test therefore uses the
disposable fixture administrator to delete one member after a complete,
unpublished stage has committed. It leaves both physical claims and vector
replays intact to expose the mismatch to the real manager.

An independent read-only connection observes the generation's declared count
of two, one stored member, the staged intent and the previous active pointer.
The manager's publication call raises `IntegrityViolation` before any Qdrant
HTTP request. A second independent read confirms the corrupted graph and
pointer did not change. This proves refusal of a committed bad graph; it does
not suggest that a public stage can half-commit.

The final serial PostgreSQL 17/Qdrant 1.20 parent run passed 38 checks, 19 per
runtime. Both public snapshot hashes matched
`89319b18e0a39af96dc72d9d0db5ae4a56913e44e4f28d8922fefd134e40c61e`,
and task-owned cleanup was verified. The accepted private result is
`artifacts/V5/V5-04H/partial-member-both-final-01/results.json`.
Four focused parent validation tests passed; all 16 sealed inputs matched.
Only the two native consumers changed. No product code, schema, grants,
fixture, dependency, hosted service or package release changed.

Eight exact H fault IDs now have native evidence. The remaining matrix rows,
recovery process-death experiment, V5-04 parent acceptance and later V5 gates
remain open. Learning practice is unassessed: explain why checking the member
count before any vector write protects the previously published generation.
