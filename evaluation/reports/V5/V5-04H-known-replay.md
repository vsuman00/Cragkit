# V5-04H known completed replay checkpoint

This checkpoint registers frozen fault ID `known_completed_replay` against
the actual native publication-worker process in both runtimes. The first
child publishes a complete generation and exits. A second child receives
the same stage reference and returns the identical durable published result.
It emits no reserved, before-write or HTTP observation event. The parent
ledger records one admitted logical attempt with no model-provider charge.

For example, a client restart after a completed write must not create a new
point request. Node already compared the settled journal across its second
child. Python now makes the same scoped SQL READ ONLY comparison, including
the dispatch ID, settled state, sequence and completion digest. Both retain
the first generation's identity and result. The ordinary native scenario
also exercises the remaining process and recovery checks; this report counts
only the exact completed-replay row.

The final serial PostgreSQL 17/Qdrant 1.20 run passed 18 checks, nine per
runtime, with matching public-result hash
`7ba570d37e0a78880cf9d914816ae12748590d656142dfbf4e6d8c6e030d267e`
and verified task-owned cleanup. Private result:
`artifacts/V5/V5-04H/known-replay-both-01/results.json`. The focused parent
validation tests passed (3). Product code, schema, fixture, grants,
dependency, lockfile, provider and hosted service did not change.

Fourteen exact H IDs now have complete native evidence. The distinct
reserved-owner lease assertion, other matrix rows, recovery coordinator
process death, V5-04 parent acceptance and full V5 remain open. Learning
practice is unassessed: explain why a settled journal and historical result
allow this retry without recharging old provider work.
