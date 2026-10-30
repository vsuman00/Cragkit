# V5-04H atomic stage boundary checkpoint

This checkpoint exercises five IDs from the frozen 43-case Qdrant publication
matrix: `intent_commit_failed`, `intent_ack_lost`, `source_commit_failed`,
`source_ack_lost` and `claim_ack_lost`. They share two actual PostgreSQL
boundaries because intent, source, members, replay and claims stage in one
transaction. The full H matrix and V5-04 parent remain open.

For example, after the stage COMMIT succeeds but its reply is lost, a fresh
read-only transaction compares the original intent and complete graph. It can
return the stored `staged` result without issuing another INSERT or point
request. If the transaction rolls back instead, an independent observer sees
none of the target rows and the old active generation stays in place.

The native harness forwards the real intent INSERT before raising the rollback
fault. Its second fault forwards the real COMMIT, withholds only the reply and
retires that connection. A new writer and manager then reconstruct the
canonical source, manifest, members, global point claims and dense/sparse
replay under the same trusted scope. An independent disposable read-only
observer checks the target tables and active pointer; runtime RLS cannot make
missing rows appear proven. Neither trace sends a Qdrant point request.

The first native run exposed a public parity gap: Node confirmed a lost stage
COMMIT, while Python returned unavailable. Both now make one exact SQL READ
ONLY confirmation. Missing same-intent history remains unavailable; changed
payload, fences or graph are integrity failures. Body failure, known rollback,
deadline and cancellation do not enter successful confirmation. The Node
confirmation no longer uses a read-write SQL transaction. No migration,
permission or public signature changed.

| Check | Result |
| --- | --- |
| Focused Python writer and native-tool tests | 260 passed |
| Focused Node writer tests | 232 passed; strict build passed |
| Full Python/package-tool regression | 3,088 passed; four existing serializer warnings |
| Full Node regression | 1,530 passed; strict build passed |
| Python strict typecheck | No issues in 49 source files |
| Native PostgreSQL 17/Qdrant 1.20 public-manager run | 16 checks per runtime, 32 total; matching public snapshot hash and task-owned cleanup |

The final native output is
`artifacts/V5/V5-04H/stage-both-final-01/results.json`. Both runtimes report
`89319b18e0a39af96dc72d9d0db5ae4a56913e44e4f28d8922fefd134e40c61e`
for the public snapshot hash. The fixture's `source_commit_failed` expectation
was corrected to reflect atomic rollback; the case IDs and physical profile
were unchanged. Failed local probes are separate private diagnostics, not
successful evidence.

These checks establish two native stage boundaries and their five mapped IDs.
They do not establish publication-CAS acknowledgment loss, worker crashes,
the remaining H rows, clean package installation, live-provider behavior or
production readiness. No hosted database, model provider, package publication
or persistent service was used. The learning practice remains unassessed:
identify why an absent intent after rollback and an unacknowledged committed
intent require different retry behavior.
