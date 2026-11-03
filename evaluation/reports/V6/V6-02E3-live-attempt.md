# V6-02E3 live held-out attempt

Status: **FAILED** on 3 November 2026. V6-02 remains incomplete. Both provider
credentials authenticated successfully, and no credential exposure was found in
the scoped checks. The run did not produce healthy recordings or native replay
acceptance. No paid retry was made.

For example, a completed Python request can return valid source evidence while
a later provider failure leaves the whole comparison unreproducible. Keeping
those outcomes separate prevents a successful subset from hiding a failed run.

## Frozen execution and credential checks

The [credential preflight](V6-02E3-credential-preflight.md) records the private
file checks, repository/history/archive inspection and preventive fixes. Its
verification passed 80 focused tests and 3,635 Python/tool tests, with four
existing intentional Pydantic warnings. The subsequent freeze checks passed
34 tests and verified all 16 sealed inputs. No original label, scorer, target,
package source or lockfile was changed for this run.

The hardened source commit is `de683a241d0da3cd5b7f0edd2946cd949dc8c972`;
the isolated checkout is `34f5222`. Package tree identity remains
`05fdc769488f496ef71ec6b988383fa8d1f18b1c`. The checkout was clean before
preparation. New ECR preparation and independent verification accepted 9,414
inventory files and identity
`2a1dfaf529bb314c280c8403bc65b116021fec80f64a84c50c4a91ea6217ab10`.
The previous receipt was retained and its three changed standard-library caches
were checked against their unchanged source. No identity guard was weakened.

A development-only native Python/Node mechanics run passed parity and targets
with fake providers and genuine isolated PostgreSQL 17.11/pgvector 0.8.0. It made
no HTTP request and did not open held-out labels. This validates the corrected
child environment in actual native execution; it does not establish model quality.

Official prices were reviewed on the run date: [OpenAI embeddings](https://developers.openai.com/api/docs/models/text-embedding-3-small)
and [Cohere Rerank Fast](https://cohere.com/blog/rerank-5) each list USD 0.02 per
million input tokens. The fresh private dated review was supplied explicitly;
the earlier price-review record was preserved. These list prices do not verify
account billing. The budget snapshot's older `price_date` is its fixed code-rate
revision; the explicit run review records the current review date.

The live parent used `--mode live`, a fresh output directory, the verified
runtime receipt, explicit private credential paths, the reviewed price file,
a durable once-only admission directory and both process/provider opt-in flags.
Limits remained USD 0.02 total, USD 0.01/provider, 60 calls, concurrency one and
zero retries. Only approved public synthetic evaluation texts were disclosed.
Credentials were supplied in HTTPS authentication headers to their intended
providers, with verified TLS, fixed destinations, no environment proxy and no
redirects. No credential value was placed in argv, reports or Git.

## Actual execution and failure

The Python live worker returned all **30 question/mode rows**, six questions
across five modes, with three document-revision publication receipts. There
were 37 admissions: 26 OpenAI responses and ten Cohere responses completed;
the eleventh Cohere attempt failed at ordinal 37. Confirmed completed HTTP
requests number 36; the recorded dispatch bound is 36–37 because final completion
and usage are unknown. The journal retained 37 pending records, 36 completions
and 36 response files. It remained failed and unsealed.

The fixed failure code is `transport_failed`. The transport deliberately
collapsed HTTP status, media/encoding/size failures and network errors into a
safe diagnostic. It therefore cannot establish the underlying HTTP status now.
Eleven Cohere admissions occurred within 14.82 seconds, while [Cohere's official
rate-limit table](https://docs.cohere.com/docs/rate-limits) lists ten Rerank
requests per minute for trial keys. Rate limiting is a plausible explanation,
**not a confirmed HTTP 429 diagnosis**. Successful earlier responses from both
providers rule out describing this whole run as rejected credentials.

The unhealthy recording prevented both Python and Node replay. Each retained
replay score has 30 explicit nonexecution failure placeholders; these are not
60 additional executed failures. Normalized parity, complete same-shortlist
verification and overall quality acceptance remain false. The raw parent's
`evidence_kind` label mentions replay, but its explicit stage states show that
neither replay ran. The stage states govern this report.

Recorded estimated cost is USD 0.00133424, including the full conservative ceiling
for the unknown final request. Cumulative admission ceilings sum to USD 0.01311472;
this sum is distinct from outstanding exposure after known usage was settled.
The final Cohere request retains unknown usage and unknown billing. Actual total
account charges remain unknown; a failed request must not be treated as free.

## Independent scoring and manual review

The [machine-readable report](V6-02E3-live-verification.json) preserves per-mode,
per-question metrics, denominators, Wilson intervals, all failed targets and
raw-result hashes. The original complete raw files remain private and unchanged.

- Python live has zero observed authorization, identity or fidelity violations,
  zero false-sufficient results and **two operational failures**: q30 in
  `reranked_hybrid` and `corrective`. Each affected mode has failure rate 1/6.
- Document/support recall and rank metrics have four eligible supported questions
  per mode. Lexical recall/MRR/support recall are 0.0; dense, hybrid, reranked
  hybrid and corrective report 1.0 on this small attempted packet.
- Hybrid-minus-lexical recall is +1.0. Corrective-minus-reranked support recall is 0.0.
  The full-run same-shortlist rerank comparison remains null/unverified because
  q30 failed. Four successful eligible comparisons with zero deltas cannot
  replace that failed gate or establish full-run reranker acceptance.
- No valid result is sufficient. False-sufficient 0/28 is conditional on valid
  execution and accompanies universal withholding on the three answerable
  questions: answerable abstention 3/3, Wilson 95% approximately [0.439,1.0]. This
  does not demonstrate useful sufficiency discrimination. Conflict denominator
  is zero, so this packet establishes no conflict-classification performance.

Manual review found no unsupported sufficient acceptance example to inspect;
its absence is reported rather than fabricated. In q25, dense retrieval covers
both reviewed deployment-runbook support spans, but the result stays partial
with unknown coverage. Source retrieval can be correct while the engine still
withholds sufficiency. In q29, one rotation-policy facet has support and another
is missing; the partial result appropriately withholds the missing answer.

## Disposition, cleanup and next action

V6-02E3 and V6-02 remain OPEN. Operational-failure-zero, healthy recording,
complete same-shortlist verification, reproduction and native parity gates did
not pass. V6-03 and subsequent dependency-gated tasks have not been accepted.
The original held-out packet was opened and scored on this date. The frozen
candidate's unopened-access wording is a historical pre-run declaration; this
report records the exposure. No labels or thresholds were tuned after access.

Preserve the original admission, incomplete journal, observations and scores.
Do not remove the admission, fabricate a seal, replay an incomplete tape or
repeat the original paid run under another output path. The next corrective
proposal is an offline development slice for bounded trial-key pacing and safe
fixed HTTP-status categories. A later unbiased quality run must follow the
[contamination and fresh-review policy](../../protocol.md#human-review-and-sealing),
with a fresh reviewed held-out set where a failure informs a change, a source/
runtime/input refreeze and a separately recorded budget and execution decision.
No such second dispatch is authorized by this report.

Both Sol peers independently reviewed the failed run, coordinated directly and
returned their assembled findings to root. No protected decision remained in
dispute. Python worker cleanup and recorder cleanup passed; the aggregate flag
remains false because required stages never ran. The owned PostgreSQL processes
were closed, and a process-name check found no PostgreSQL/pg_ctl/initdb process
remaining. No service, installation or model download was added. One suite and
one native fixture ran at a time on the declared laptop.

Root compared both selected keys against all 121 generated run files and found
zero matches. No raw provider response or private configuration is committed.
The broader audit remains scoped; it cannot prove absence of every possible
credential. Learning practice is unassessed. Optional exercise: explain why
zero false-sufficient results can coexist with an unusable all-abstaining system.
