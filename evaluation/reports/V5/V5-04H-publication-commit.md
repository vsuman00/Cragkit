# V5-04H publication COMMIT checkpoint

This checkpoint exercises the frozen `publication_ack_lost` matrix case against
the actual final publication CAS. It adds one native fault boundary to the
[atomic stage checkpoint](V5-04H-stage.md). V5-04H and the 43-case matrix
remain open.

For example, Qdrant has acknowledged the complete generation and PostgreSQL
commits the new active pointer, but the caller loses the COMMIT reply. The
writer now reads the same scoped intent in one fresh SQL READ ONLY transaction.
It returns the recorded historical `published` outcome only when the original
payload, manifest, fences, revision, generation and terminal flags still
match. A later generation can become active without changing that historical
result.

The native wrapper observes the real `UPDATE documents SET
active_generation_id`, forwards the real COMMIT and withholds that reply.
It then retires the connection. An independent disposable read-only observer
checks the winner pointer, published generation and terminal intent. A fresh
manager retries the same intent and receives the same result with no new point
request, stage DML or CAS. The competing older stage still records conflict.
This fault is distinct from the existing preparation and attestation COMMIT
tests.

Python gained exact lost-COMMIT publication confirmation. Node's existing
confirmation is now an actual SQL READ ONLY transaction. Both preserve
deadline, cancellation and known rollback refusals, and classify missing
history as unavailable and contradictory history as an integrity failure.
The focused Python test exposed a captured-variable collision between the
eleven-field intent snapshot and a six-field preparation tuple; the captured
intent facts now use a distinct name.

| Check | Result |
| --- | --- |
| Focused Python writer and native-tool tests | 265 passed |
| Focused Node writer tests | 248 passed; strict build passed |
| Full Python/package-tool regression | 3,093 passed; four existing serializer warnings |
| Full Node regression | 1,546 passed; strict build passed |
| Python strict typecheck | No issues in 49 source files |
| Native PostgreSQL 17/Qdrant 1.20 public-manager run | 17 checks per runtime, 34 total; matching public snapshot hash and task-owned cleanup |
| Sealed input integrity | All 16 input hashes matched |

Final native evidence is
`artifacts/V5/V5-04H/publish-both-final-01/results.json`. Both runtimes report
`89319b18e0a39af96dc72d9d0db5ae4a56913e44e4f28d8922fefd134e40c61e`
for the public snapshot hash. Failed local probes are retained separately as
private diagnostics and do not count as acceptance.

The H checkpoint now has native evidence for six exact matrix IDs across
three transaction boundaries. The remaining matrix rows, recovery process
death, V5-04 parent acceptance and later V5 gates remain open. No migration,
grant, dependency, hosted database, live provider or package release changed.
Learning practice remains unassessed: explain why a lost COMMIT reply needs a
read-only history check before retrying the same operation.
