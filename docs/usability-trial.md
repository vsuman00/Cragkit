# Developer usability trial

For example, a participant should distinguish an empty authorized search from a
closed database resource. An empty search returns insufficient evidence; a closed
resource is an operational failure. Neither case permits an invented answer.

This is the V6-05 protocol for a future independent human trial. The
[current report](../evaluation/reports/V6/V6-05-usability.md) records the unavailable
participant and agent rehearsal separately. No integration-effort saving or
adoption result has been measured.

## Fixed comparison

Use the preregistered comparison in
[V6-candidate.json](../evaluation/release/V6-candidate.json): manual native
PostgreSQL retrieval versus the installed Cragkit package, with the same synthetic
corpus, scope, required filters and exact-source requirements. The frozen target
is library task time no greater than the measured baseline, without weaker
invariants. Preserve failures and assistance; do not change the target after the
participant starts.

Recruit a developer unfamiliar with this code. Record prior Python/Node,
PostgreSQL and retrieval experience. Explain data handling and obtain agreement
to record task observations. Use public synthetic sources only. The
[pilot corpus](../examples/pilot_rag/corpus.json) supplies ten documents, including
same-tenant and cross-tenant denial cases. Record its digest and reset the same
corpus/database state before each arm. Keep the held-out quality questions out of
this trial; do not tune retrieval from participant results.

Fix the machine, runtime versions, schema, restricted roles, source/corpus bytes,
tokenizer, budgets and network conditions for both arms. Provision infrastructure
through a separate operator step. Record common setup time separately; apply the
same starting-state policy to both arms. The manual baseline must implement the
declared required behavior, not merely return a plausible SQL row. It must check
scope before selection, preserve required filters, verify immutable source
digests/spans and distinguish operational errors from missing evidence.

Use a fresh application environment per arm. Alternate the arm order across
participants when possible, recording order and any learning carryover. Do not
infer a population result from a single participant.

## Participant tasks

| Task | Completion check |
| --- | --- |
| Install and ingest | Inspect installed origin/version; ingest the fixed corpus under the restricted writer. No administrator login or hidden provider setup in application code. |
| First authorized retrieval | Retrieve an expected passage, verify its exact source span and enforce the required document filter. Same-tenant and foreign-tenant denial still hold. |
| Interpret outcomes | Explain a partial/unknown-coverage result, a no-match insufficient result and an operational failure. Preserve execution state and uncertainty. |
| Bounded maintenance | Change one document through a new immutable revision or change one required filter; verify the new behavior, original citation identity and unchanged permissions. |

The [pilot guide](../examples/pilot_rag/README.md) and
[manual checklist](../examples/pilot_rag/CHECKLIST.md) support the library arm.
Automated smoke output does not fill the human result cells. A model provider is
unnecessary. Manual prompt disclosure, if separately chosen, is outside this
comparison and must not mix private content into the recorded trial.

For each task and arm, record start/end time, completion or failure, errors,
attempts, documentation visited, assistance and unresolved confusion. Record
external interruptions separately. Stop a task if the participant declines or
local resource pressure develops. An incomplete arm is not zero time and must
not be counted as a successful comparison.

After the tasks, record the participant's own reasons to continue or abandon the
integration. Preserve their meaning; do not invent quotes, satisfaction scores or
adoption intent. Repeat failed steps from a fresh environment after a fix and
retain both observations. Report paired task outcomes before any aggregate time.

## Recording and claim limits

Use this minimal record for each participant. Leave unavailable values null.

```json
{
  "participant_id": null,
  "eligibility_verified": false,
  "arm_order": [],
  "environment_and_corpus": null,
  "tasks": [],
  "baseline_total_seconds": null,
  "library_total_seconds": null,
  "assistance": null,
  "continue_or_abandon_feedback": null,
  "comparison_valid": false
}
```

Keep private identity, credentials and raw private prompts outside Git. Use a
nonidentifying participant ID in any shared report. No participant or comparable
baseline means usability and comparative-effort claims remain unvalidated, even
when package installation and mechanics pass. The active V6 plan explicitly
allows recording that limitation; it does not authorize invented human evidence.
