# V5-PILOT-01 manual observations

Run the [pilot](README.md) against its synthetic corpus. Leave the result cells blank until you observe each case. Record the command, document/revision IDs, status and any unexpected behavior. Automated smoke checks cover mechanics separately; these rows do not establish live-model quality or V6 usability acceptance.

| Check | Action | Expected observation | Manual result |
| --- | --- | --- | --- |
| Installed artifact | Start a session and inspect the import origin and version. | Child imports `cragkit` from `examples/pilot_rag/.venv`, version `0.0.0`, not checkout product code. | |
| Seed and baseline | As `alice`, run `docs`, then `ask atlas rollback`. | Nine authorized team documents are seeded; runbook evidence has source references. Useful hits can be `partial` with unknown coverage. | |
| No match | `ask quasarlattice` | No matching evidence; an honest `insufficient` result, not an invented answer. | |
| Synonym limitation | Compare `ask rollback` and `ask reversion`. | The literal query finds evidence; the synonym may miss because this profile is lexical. | |
| Multiple facets | Compare `ask atlas rollback cache ttl` with separate `ask atlas rollback` and `ask cache ttl`. | Restrictive lexical terms may miss combined evidence; no automatic sufficient-coverage claim. | |
| Dated conflict | `ask cache ttl` | Inspect current and legacy notes: 2026-10-20 says 300 seconds, superseding 2026-08-01's 900 seconds. Exact provenance does not establish truth. | |
| Unicode citations | `ask café`, then compare its excerpt to `unicode-release` in the file. | Preserve accents, Japanese, emoji and decomposed `café`; verify byte spans against the cited immutable source. | |
| Code identifier | `ask compute_retry_delay` | Inspect the exact identifier in `retry-code`; evidence is quoted data, not executed code. | |
| Untrusted source | `prompt source injection` | Injection wording remains source data; scope stays unchanged. Inspect the prompt before manual disclosure. Downstream LLM resistance is unmeasured. | |
| Manual answer generation | If you choose an LLM, paste `prompt incident` into it, then try a missing-answer query. Record the model and its settings privately. | Each factual claim cites evidence that supports it; missing facts remain explicit. Check source-instruction handling separately. Leave unrun cases blank; retrieval passes do not prove answer quality. | |
| Same-tenant denial | `user bob`, `docs`, `ask atlas rollback` | Bob has the team tenant but no document grants; no team excerpts are returned. | |
| Cross-tenant query | As `alice`, `ask atlas rollback`, `ask tenantcanary`; repeat both as `outside`. | Alice never receives `other-canary`. Outside may receive that document for Atlas, sees `tenantcanary`, and never receives the team runbook. Return to `alice`. | |
| Update and replay | Save an edit to `atlas-rollback`; `reload atlas-rollback`; query it; reload again unchanged. | Changed text creates a new immutable revision through CAS. Unchanged reload replays its receipt; record IDs and exact quote. | |
| Tombstone | `delete atlas-rollback`, then `ask atlas rollback`. | The deleted runbook is absent. Other authorized matching documents may remain. | |
| Budget and error distinction | `budget 1`, `ask atlas rollback`; then choose a larger budget and repeat. | Tiny context causes a visible budget failure, distinct from no-match insufficiency. Record errors or degraded execution separately from coverage. | |
| Provider and shutdown | Leave provider timeout/rate-limit/generation checks marked N/A until explicitly configured; run `quit`, then start a fresh session. | No embedding/generation calls occur. Owned database resources are cleaned up; the fresh database is seeded from the saved file, not prior database-only state. | |

Before sharing results, remove private prompts, credentials and connection details. Note the wheel path, PostgreSQL version, corpus edits, chosen budgets and observed cleanup outcome. Keep manual LLM observations separate from application mechanics.
