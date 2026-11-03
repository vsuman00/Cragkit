# V6-02 held-out recovery evaluation

Status: COMPLETE for the declared small-corpus evaluation, reporting and recorded
native reproduction criteria. Full V6 and production readiness remain OPEN.
The original failed attempt remains preserved as failed; this separate approved
recovery packet passed the frozen targets without lowering them.

For example, valid source excerpts can cover a question while the library still
returns partial with unknown coverage. That occurred here: successful retrieval
must not be described as a useful sufficient-answer decision.

## Evaluated identity and execution

The project user approved all six recovery questions/eight facets on 3 November 2026.
[Approval and seal](../../review/retrieval-recovery/approval.json) preserve that
decision and initial exposure. The five immutable source revisions have disjoint
family IDs from the original manifest, but agent authors/reviewers and the human
saw the small synthetic packet before sealing. This is not a blind external
benchmark or a population-quality guarantee.

The [clean preparation report](V6-02I-runtime.md) binds source
`25275e447c64ecfd243ef6bc26c87031d5e2e472`, checkout `34b5748`, unchanged package
tree `05fdc769488f496ef71ec6b988383fa8d1f18b1c` and runtime identity
`59af39c6cb0a5d118c73511dbb67b5fd22b2289a731ffeaaa5fc488d4105b993`.
Source and complete compiled/dependency inventories were checked before/after
execution. Labels/facets remained outside worker/provider runtime projections;
independent scoring loaded their issued root/path/digest after execution.

Root recorded one new recovery execution under the user's existing explicit
instruction to call necessary project APIs. The new profile uses a separate
durable admission with the same USD 0.02 total, USD 0.01/provider, 60-call ceiling,
concurrency one and zero retries. Original admission/tape ownership was retained.
Only approved public synthetic text was disclosed. The existing private keys
were supplied through explicit paths, verified TLS/fixed provider endpoints and
headers. No key or private database configuration is included in this report.

Official list prices were rechecked on the run date: [OpenAI embeddings](https://developers.openai.com/api/docs/models/text-embedding-3-small)
and [Cohere Rerank Fast](https://cohere.com/blog/rerank-5) each list USD 0.02 per
million input tokens. A current dated review file was supplied. This verifies
configured rates, not account billing or alias immutability.

The actual parent ran `--mode live` with its prepared receipt, fresh output,
shared once-admission directory, explicit key/price paths and process/provider
opt-in flags. It used isolated genuine PostgreSQL 17.11/pgvector 0.8.0 for each
stage. **39 live requests completed: 29 OpenAI embeddings and 10 Cohere reranks.**
The journal has 39 pending/completion records and 39 captured responses, matching
its healthy seal. There was no unknown or failed request. Fresh Python replay
and native Node replay consumed the complete recordings with **zero HTTP calls**.

Each stage returned 30 rows and five publication receipts. All three normalized
observations match, with complete execution, verified cleanup and all frozen
metric targets passed. Ninety stage rows reuse the same six questions; they are
not 90 independent quality trials. Replay proves reproducibility/parity through
both native libraries, not a second independent model inference.

## Metrics and uncertainty

All modes use k=5. Rank/support averages include five support-bearing questions;
the absent-owner question has no positive reference and is excluded from those
averages. Per-mode binary metrics retain six-question denominators.

| Mode | Document recall/MRR/nDCG/support recall | Support-bearing denominator |
| --- | --- | --- |
| Lexical | 0.0 | 5 |
| Dense | 0.8 | 5 |
| Hybrid | 0.8 | 5 |
| Reranked hybrid | 0.8 | 5 |
| Corrective | 0.8 | 5 |

Hybrid-minus-lexical recall is +0.8 over 5 paired questions. All six same-shortlist
comparisons are verified, including the empty historical case; reranked MRR
minus its original shortlist ordering is 0.0 over 5 eligible pairs. Corrective
support-recall delta is 0.0 over 5 pairs. These satisfy preregistered nonnegative
conditions; they demonstrate no reranker or corrective gain on this packet.
Continuous rank averages have no population confidence intervals here.

Observed invariant, authorization, identity, fidelity, operational-failure and
false-sufficient counts are zero across the 30 live mode rows. Each per-mode
zero rate is 0/6 with Wilson 95% interval approximately [0,0.3903]. Modes/replays are
dependent; no 30/90-independent-trial interval is claimed. Independent byte/scope
inspection matched 44 live evidence occurrences and ten rerank input candidate
sets/hashes to their approved sources and actual shortlist membership.

Every live result withholds sufficiency: abstention 6/6 (Wilson 95% approximately
[0.6097,1]), answerable abstention 3/3 and required abstention 3/3 (each approximately
[0.4385,1]). Abstention correctness is 3/6 (approximately [0.1876,0.8124]). There
are zero sufficient outputs, so precision/usefulness of sufficient acceptance
cannot be estimated. Conflict detection misses 1/1 (approximately [0.2065,1]).
Zero false-sufficient outcomes under universal withholding do not establish
useful coverage assessment or reliable answer generation.

## Manual review and known limitations

No unsupported sufficient acceptance example exists to inspect; none was
invented. Manual review covered all six question types:

- Current q01 retrieves both routing/acknowledgment supports in nonlexical modes,
  but remains partial with unknown coverage despite available evidence.
- Historical q02 returns empty evidence in every mode with insufficient/complete.
  The historical receipt exists, and explicit filters were retained. Frozen SQL
  searches active generations only, so this is a deterministic, preexisting
  historical-search limitation, not a model failure or authorization leak.
- Other-tenant q03 preserves Cobalt's exact Café 🙂 excerpt and tenant scope;
  it still withholds sufficiency despite support.
- Missing-owner q04 retrieves related authorized documents without inventing an
  owner and withholds an answer. Related evidence is not itself an owner answer.
- Partial q05 restricts evidence to the delivery guide, which states its window
  but no manager. The engine remains unknown/partial rather than resolving the
  reviewed missing facet.
- Conflicting q06 retrieves both equal-authority delivery claims yet reports
  unknown coverage rather than identifying conflict. Withholding is conservative;
  conflict detection did not succeed.

Active-generation-only historical search was already documented in
[the V2 exit report](../V2/V2-07-08-exit.md) and [development guidance](../../../docs/development.md#v2-07-hybrid-orchestration-and-v2-08-evaluation).
The evaluation retains its zero contribution and denominator. Acceptance here
covers reporting/reproduction and the declared gates; it does not add a historical
search capability or claim useful sufficiency/conflict detection. Corrective rows
also report budget exhaustion while execution completes. Lexical results are
empty under this simple native FTS setup, which is not BM25. No downstream
answer quality, real-world source truth or broad model superiority was evaluated.

## Accounting, privacy and disposition

The recorder estimate is **USD 0.00004206** from validated reported input usage;
actual account billing remains unknown. Sequential peak admitted exposure was
USD 0.00200432 total and USD 0.00199138 for Cohere, below the configured limits.
Cumulative admission ceilings sum to USD 0.01443086; that sum differs from concurrent
reserved exposure after prior known usage settles. Baseline counterfactual spend
was not measured. Per-mode latency observations use six samples and include
provider pacing/network time; the maximum live retrieval latency was 7619.74 ms,
below the 25,000 ms request deadline. This is not a general latency guarantee.

The [complete metric/provenance record](V6-02-recovery-verification.json) retains
all per-question/mode counts, denominators, Wilson intervals, paired comparisons,
latency definitions and raw-file hashes. Raw model responses remain private.
Root's exact/base64 scan found neither selected key in all 131 generated files.
All 121 original failed-run files and its existing admission hash match their
preserved inventory; one separate recovery admission was added. No original
failure was removed, completed synthetically or relabelled successful.

Both Sol peers independently audited execution/accounting and metrics/manual
examples, coordinated directly and assembled findings. Root inspected their
reports and reconciled the historical capability against existing source/docs;
no material disagreement remained. Local worker/recorder/fixture cleanup passed
and no PostgreSQL process remained. Resource observation: 25.2 GiB free disk and
48 percent free system memory. No hosted database, persistent service, local
model download, CI or package publication is claimed. V6-03 is the next task.
Learning practice is unassessed; exercise: explain why matching replays and zero
false-sufficient results do not prove useful answer quality.
