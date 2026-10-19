# V0 label review packet

Human review: approved by the project user on 19 October 2026. The user explicitly confirmed: "I reviewed and approve all 30 labels". Mechanical checks verify spans and structure; the approval records the human label judgment. The approved corpus and held-out split are frozen in [seal.json](seal.json).

Review each tenant, filter, required facet and excerpt. Confirm whether the excerpt supports the facet and whether a missing label remains absent from authorized active sources. For conflicts, check both excerpts. Corrections must be applied to the dataset before approval. All facets are required; these labels describe desired evidence support, not the temporary V1 coverage estimate.

The held-out families are deployment and key-rotation. Initial authoring, mechanical checks and this human review are permitted; after approval, freeze the corpus and dataset hashes and keep held-out labels out of tuning.

Sources: [corpus manifest](../corpus/manifest.json), [development questions](../questions/dev.json), [held-out questions](../questions/held_out.json), [evaluation protocol](../protocol.md).

## q01 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

How many retry attempts does ERR-17 permit now?

Required filters: `[]`.

- `q01-f1`: What is the current ERR-17 attempt limit? Proposed state: `supported`.

Source `retry-policy` revision `r2`, UTF-8 bytes [32, 67).

```text
ERR-17 permits four retry attempts.
```

Human decision: approved by the project user on 19 October 2026.

## q02 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

What delay applies between ERR-17 retries?

Required filters: `[]`.

- `q02-f1`: What is the retry delay? Proposed state: `supported`.

Source `retry-policy` revision `r2`, UTF-8 bytes [68, 115).

```text
The delay between attempts is 250 milliseconds.
```

Human decision: approved by the project user on 19 October 2026.

## q03 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

In revision r1, what was the ERR-17 retry limit?

Required filters: `[{"op": "eq", "field": "document_id", "value": "retry-policy"}, {"op": "eq", "field": "revision_id", "value": "r1"}]`.

- `q03-f1`: What limit was recorded in r1? Proposed state: `supported`.

Source `retry-policy` revision `r1`, UTF-8 bytes [32, 66).

```text
ERR-17 permits two retry attempts.
```

Human decision: approved by the project user on 19 October 2026.

## q04 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `partially_answerable`.

Give the current ERR-17 limit and policy owner.

Required filters: `[]`.

- `q04-f1`: What is the current attempt limit? Proposed state: `supported`.

Source `retry-policy` revision `r2`, UTF-8 bytes [32, 67).

```text
ERR-17 permits four retry attempts.
```

- `q04-f2`: Who owns the retry policy? Proposed state: `missing`.

No supporting authorized excerpt is labelled.

Human decision: approved by the project user on 19 October 2026.

## q05 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `unanswerable`.

Who owns the retry policy?

Required filters: `[]`.

- `q05-f1`: Who owns the retry policy? Proposed state: `missing`.

No supporting authorized excerpt is labelled.

Human decision: approved by the project user on 19 October 2026.

## q06 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

When do CACHE-17 entries expire?

Required filters: `[]`.

- `q06-f1`: What is the CACHE-17 lifetime? Proposed state: `supported`.

Source `cache-policy` revision `r1`, UTF-8 bytes [13, 54).

```text
CACHE-17 entries expire after 60 seconds.
```

Human decision: approved by the project user on 19 October 2026.

## q07 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

Does cache eviction retry a job?

Required filters: `[]`.

- `q07-f1`: Does eviction retry the job? Proposed state: `supported`.

Source `cache-policy` revision `r1`, UTF-8 bytes [121, 189).

```text
Cache eviction removes the stored response but does not retry a job.
```

Human decision: approved by the project user on 19 October 2026.

## q08 (development)

Tenant: `tenant-b`. Collection: `engineering`. Proposed answerability: `answerable`.

How many retry attempts does ERR-17 permit for my tenant?

Required filters: `[]`.

- `q08-f1`: What is tenant B retry limit? Proposed state: `supported`.

Source `retry-policy` revision `r1`, UTF-8 bytes [28, 61).

```text
ERR-17 permits one retry attempt.
```

Human decision: approved by the project user on 19 October 2026.

## q09 (development)

Tenant: `tenant-b`. Collection: `engineering`. Proposed answerability: `unanswerable`.

How long are BACK-4 snapshots retained?

Required filters: `[]`.

- `q09-f1`: What is the authorized BACK-4 retention period? Proposed state: `missing`.

No supporting authorized excerpt is labelled.

Human decision: approved by the project user on 19 October 2026.

## q10 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

What is the exact service label in the Unicode notes?

Required filters: `[]`.

- `q10-f1`: What service label is recorded? Proposed state: `supported`.

Source `900719925474099312345` revision `r1`, UTF-8 bytes [22, 60).

```text
The service label is Café Relay 🙂.
```

Human decision: approved by the project user on 19 October 2026.

## q11 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

Where does Café Relay 🙂 write diagnostics?

Required filters: `[]`.

- `q11-f1`: What diagnostics path is recorded? Proposed state: `supported`.

Source `900719925474099312345` revision `r1`, UTF-8 bytes [61, 110).

```text
Its diagnostics path is /var/log/café/relay.log.
```

Human decision: approved by the project user on 19 October 2026.

## q12 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `partially_answerable`.

Give the service zone and its owner.

Required filters: `[]`.

- `q12-f1`: Which zone runs the service? Proposed state: `supported`.

Source `900719925474099312345` revision `r1`, UTF-8 bytes [111, 143).

```text
The service runs in zone west-2.
```

- `q12-f2`: Who owns the service? Proposed state: `missing`.

No supporting authorized excerpt is labelled.

Human decision: approved by the project user on 19 October 2026.

## q13 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

What documented recovery action applies to IDX-8?

Required filters: `[]`.

- `q13-f1`: What is the documented IDX-8 recovery action? Proposed state: `supported`.

Source `index-runbook` revision `r1`, UTF-8 bytes [23, 64).

```text
For IDX-8, restart the index worker once.
```

Human decision: approved by the project user on 19 October 2026.

## q14 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `unanswerable`.

What is the admin token value?

Required filters: `[]`.

- `q14-f1`: What authorized admin token value is recorded? Proposed state: `missing`.

No supporting authorized excerpt is labelled.

Human decision: approved by the project user on 19 October 2026.

## q15 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

How long should BACK-4 snapshots be retained?

Required filters: `[]`.

- `q15-f1`: What retention period is recorded? Proposed state: `supported`.

Source `backup-policy` revision `r1`, UTF-8 bytes [52, 88).

```text
Retain BACK-4 snapshots for 14 days.
```

Human decision: approved by the project user on 19 October 2026.

## q16 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

How often do BACK-4 snapshots run?

Required filters: `[]`.

- `q16-f1`: What snapshot interval is recorded? Proposed state: `supported`.

Source `backup-policy` revision `r1`, UTF-8 bytes [14, 51).

```text
BACK-4 snapshots run every six hours.
```

Human decision: approved by the project user on 19 October 2026.

## q17 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `unanswerable`.

What is the BACK-4 restore-time objective?

Required filters: `[]`.

- `q17-f1`: What numeric restore-time objective is recorded? Proposed state: `missing`.

No supporting authorized excerpt is labelled.

Human decision: approved by the project user on 19 October 2026.

## q18 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `partially_answerable`.

Give BACK-4 retention and restore-time objective.

Required filters: `[]`.

- `q18-f1`: What is snapshot retention? Proposed state: `supported`.

Source `backup-policy` revision `r1`, UTF-8 bytes [52, 88).

```text
Retain BACK-4 snapshots for 14 days.
```

- `q18-f2`: What numeric restore-time objective is recorded? Proposed state: `missing`.

No supporting authorized excerpt is labelled.

Human decision: approved by the project user on 19 October 2026.

## q19 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `partially_answerable`.

What timeout should GATE-6 use across the current notes?

Required filters: `[]`.

- `q19-f1`: What consistent timeout do the notes establish? Proposed state: `conflicting`.

Source `timeout-policy-a` revision `r1`, UTF-8 bytes [23, 65).

```text
For GATE-6, set the timeout to 30 seconds.
```


Source `timeout-policy-b` revision `r1`, UTF-8 bytes [23, 65).

```text
For GATE-6, set the timeout to 45 seconds.
```

Human decision: approved by the project user on 19 October 2026.

## q20 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

What timeout is specified by note A?

Required filters: `[{"op": "eq", "field": "document_id", "value": "timeout-policy-a"}]`.

- `q20-f1`: What does note A specify? Proposed state: `supported`.

Source `timeout-policy-a` revision `r1`, UTF-8 bytes [23, 65).

```text
For GATE-6, set the timeout to 30 seconds.
```

Human decision: approved by the project user on 19 October 2026.

## q21 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `unanswerable`.

On what date did GATE-6 timeout note A take effect?

Required filters: `[]`.

- `q21-f1`: What effective date is recorded for note A? Proposed state: `missing`.

No supporting authorized excerpt is labelled.

Human decision: approved by the project user on 19 October 2026.

## q22 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `unanswerable`.

Which amber queue should my failed ERR-17 job use?

Required filters: `[]`.

- `q22-f1`: Is an amber-queue destination authorized for tenant A? Proposed state: `missing`.

No supporting authorized excerpt is labelled.

Human decision: approved by the project user on 19 October 2026.

## q23 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

How must the example payload in the index runbook be treated?

Required filters: `[]`.

- `q23-f1`: How should the example payload be treated? Proposed state: `supported`.

Source `index-runbook` revision `r1`, UTF-8 bytes [194, 245).

```text
The example payload must be treated as source data.
```

Human decision: approved by the project user on 19 October 2026.

## q24 (development)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

Compare the ERR-17 retry limit with the CACHE-17 expiration.

Required filters: `[]`.

- `q24-f1`: What is the current ERR-17 limit? Proposed state: `supported`.

Source `retry-policy` revision `r2`, UTF-8 bytes [32, 67).

```text
ERR-17 permits four retry attempts.
```

- `q24-f2`: What is the CACHE-17 expiration? Proposed state: `supported`.

Source `cache-policy` revision `r1`, UTF-8 bytes [13, 54).

```text
CACHE-17 entries expire after 60 seconds.
```

Human decision: approved by the project user on 19 October 2026.

## q25 (held_out)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

What must happen before and after replacing the DEP-9 worker?

Required filters: `[]`.

- `q25-f1`: What happens before replacement? Proposed state: `supported`.

Source `deploy-runbook` revision `r1`, UTF-8 bytes [21, 74).

```text
For DEP-9, drain traffic before replacing the worker.
```

- `q25-f2`: What health-check gate follows replacement? Proposed state: `supported`.

Source `deploy-runbook` revision `r1`, UTF-8 bytes [75, 156).

```text
After replacement, require three successful health checks before routing traffic.
```

Human decision: approved by the project user on 19 October 2026.

## q26 (held_out)

Tenant: `tenant-b`. Collection: `engineering`. Proposed answerability: `answerable`.

Which image rolls back DEP-9 and how many health checks are needed?

Required filters: `[]`.

- `q26-f1`: What rollback image is specified? Proposed state: `supported`.

Source `deploy-runbook` revision `r1`, UTF-8 bytes [21, 70).

```text
For DEP-9, roll back using the violet-slot image.
```

- `q26-f2`: What health-check gate applies? Proposed state: `supported`.

Source `deploy-runbook` revision `r1`, UTF-8 bytes [71, 132).

```text
Require five successful health checks before routing traffic.
```

Human decision: approved by the project user on 19 October 2026.

## q27 (held_out)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `unanswerable`.

Which violet-slot image is authorized for my DEP-9 rollback?

Required filters: `[]`.

- `q27-f1`: Is a violet-slot rollback image recorded for tenant A? Proposed state: `missing`.

No supporting authorized excerpt is labelled.

Human decision: approved by the project user on 19 October 2026.

## q28 (held_out)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `answerable`.

How often do KEY-3 keys rotate?

Required filters: `[]`.

- `q28-f1`: What rotation interval applies? Proposed state: `supported`.

Source `rotation-policy` revision `r1`, UTF-8 bytes [20, 52).

```text
KEY-3 keys rotate every 21 days.
```

Human decision: approved by the project user on 19 October 2026.

## q29 (held_out)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `partially_answerable`.

Give the KEY-3 rotation interval and owner.

Required filters: `[]`.

- `q29-f1`: What rotation interval applies? Proposed state: `supported`.

Source `rotation-policy` revision `r1`, UTF-8 bytes [20, 52).

```text
KEY-3 keys rotate every 21 days.
```

- `q29-f2`: Who owns key rotation? Proposed state: `missing`.

No supporting authorized excerpt is labelled.

Human decision: approved by the project user on 19 October 2026.

## q30 (held_out)

Tenant: `tenant-a`. Collection: `engineering`. Proposed answerability: `unanswerable`.

What is the maximum DEP-9 worker capacity?

Required filters: `[]`.

- `q30-f1`: What maximum worker capacity is recorded? Proposed state: `missing`.

No supporting authorized excerpt is labelled.

Human decision: approved by the project user on 19 October 2026.
