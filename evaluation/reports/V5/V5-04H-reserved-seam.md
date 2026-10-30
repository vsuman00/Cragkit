# V5-04H reserved worker boundary, implementation checkpoint

The native ordinary worker now emits one private `reserved` event after the
real dispatch reservation is committed or exactly reconciled, and before it
marks the dispatch as sent. The parent validates the original attempt,
dispatch ID, sequence and request digest. It rejects replay, changed fields
and a later `before_write` event that does not match the reservation. The
existing owned-worker observer receives the closed event before the child
continues. The later `before_write` event still marks the dispatched barrier.

For example, a process killed at `reserved` has a durable journal row but has
not reached the manager's HTTP send. The event lets the native harness stop
that exact child at this point; the next checkpoint must independently read
the journal and physical point set. A callback event alone is not evidence of
process death or of a safe retry.

This is an implementation checkpoint. Python focused publication/worker tests
passed (82), Node focused publication/worker tests passed (62), strict
TypeScript build passed, and Python mypy found no issues in 49 source files.
The tests include normal and reconciled reservation order, parent observer
ordering, forged or replayed protocol fields, and the existing later barrier.
No native PostgreSQL/Qdrant process-death run has yet validated the new
barrier, so matrix IDs `journal_commit_before_api` and
`reserved_owner_crash` remain open. No migration, grants, dependency,
lockfile, model provider or hosted service changed.

Learning practice remains unassessed: explain why a committed `reserved` row
cannot be assumed unsent after its owner dies.
