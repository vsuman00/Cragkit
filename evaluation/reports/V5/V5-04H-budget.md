# V5-04H budget-before-dispatch checkpoint

This checkpoint covers frozen fault ID `budget_before_dispatch` against the
actual Python and TypeScript public publication managers. The base intent is
staged, and its admitted one-attempt ledger is exhausted before publication.
The next publish call returns `BudgetExhausted`.

For example, an exhausted request must not reserve a physical write and then
hide that reservation behind a budget error. Both native consumers compare
the complete staged snapshot, active pointer, empty durable dispatch journal
and actual Qdrant HTTP counters before and after the refusal. All remain
unchanged. The test also retains the original scope, intent and declared
limits; it does not remove filters or allocate a new generation.

The final serial PostgreSQL 17/Qdrant 1.20 parent run passed 40 checks,
20 per runtime, with matching public snapshot hash
`89319b18e0a39af96dc72d9d0db5ae4a56913e44e4f28d8922fefd134e40c61e`
and verified task-owned cleanup. Private result:
`artifacts/V5/V5-04H/budget-both-01/results.json`. Four focused parent
validation tests passed; all 16 sealed inputs matched. No product code,
schema, grants, fixture, dependency, lockfile, provider or hosted service
changed.

Fifteen exact H IDs now have complete native evidence. The other matrix
rows, recovery coordinator process death, V5-04 parent acceptance and full
V5 remain open. Learning practice is unassessed: explain why a local budget
check must run before a durable dispatch is created.
