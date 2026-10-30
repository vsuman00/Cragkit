# V5-04H existing native fault mapping

The serial PostgreSQL 17/Qdrant 1.20 parent run in
`artifacts/V5/V5-04H/partial-member-both-final-01/results.json` passed 19
checks per runtime with matching public snapshots and verified cleanup. Four
checks already exercised exact frozen fault IDs but had only implementation
labels in the result. This report registers their H coverage without changing
the tests or treating nearby cases as equivalent.

| Frozen matrix ID | Executed native check | Observed boundary |
| --- | --- | --- |
| `intent_payload_changed` | `changed_stage_payload_fails_without_new_writes` | Reusing a published stage intent with a changed initial metadata tag raises `IntegrityViolation`; actual Qdrant mutation count does not increase. |
| `write_ack_lost` | `actual_lost_write_ack_stays_unknown_and_retry_does_not_resend` | A real point request completes while its client acknowledgment is withheld. The durable dispatch remains unknown; a fresh manager retry does not resend it or publish. |
| `verified_prepared_commit_lost` | `actual_preparation_commit_ack_loss_reconciles_without_http_resend` | The real preparation transaction commits with its reply withheld. The same publication resumes without another point request. |
| `pointer_cas_race` | `competing_original_pointer_preserves_winner_and_persists_conflict` | Two staged intents share the original expected pointer. The winner publishes; the older loser persists conflict and leaves the winner active. |

For example, a lost point acknowledgment and a lost preparation COMMIT reply
are different uncertainty boundaries. The native suite checks both, and their
separate result labels remain visible. The pointer case uses deterministic
interleaving, not a claim about simultaneous scheduler timing.

These four registrations bring the exact H IDs with native evidence to 12.
The remaining matrix rows and recovery process-death experiment still need
their own accepted observations. V5-04 and full V5 remain open. No code,
fixture, service, schema or dependency changed for this mapping. Learning
practice remains unassessed: explain why a completed HTTP request with a lost
reply cannot be retried as if it never ran.
