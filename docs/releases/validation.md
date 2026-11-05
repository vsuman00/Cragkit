# Cragkit release validation and limitations

For example, an exact, authorized excerpt can be returned with unknown coverage.
That happened in this evaluation: retrieving relevant text did not establish
that the library could correctly declare an answer sufficient.

This report discloses historical release-candidate measurements and their limits.
It does not certify production readiness. Current packages are Python
`1.0.0rc3` and npm `1.0.0-rc.2`; the measurements below retain their original
source identities rather than being relabeled as new release benchmarks.

## Historical retrieval comparison

The recovery run on 3 November 2026 used five synthetic immutable source
revisions, six reviewed questions and eight facets. Authors, agent reviewers and
the approving human saw the packet before sealing. Families were separated from
the earlier packet, but this was a small, pre-exposed recovery evaluation, not a
blind external benchmark. The earlier failed attempt remains recorded as failed.

The evaluated source was
`25275e447c64ecfd243ef6bc26c87031d5e2e472`, package tree
`05fdc769488f496ef71ec6b988383fa8d1f18b1c`. Frozen configuration SHA-256 was
`fd5524e9cc9598011ffd8782f511cde49d802884d15d0e18a34bff900950ab5d`;
execution identity SHA-256 was
`59af39c6cb0a5d118c73511dbb67b5fd22b2289a731ffeaaa5fc488d4105b993`.
These identify retained records, not a public dataset download.

The native matrix was Darwin ARM64, Python 3.14.6, Node 26.5.0, npm 11.17.0,
TypeScript 7.0.2, PostgreSQL 17.11 and pgvector 0.8.0. The comparison used an
isolated database per execution stage and concurrency one. Live quality came
from one Python execution; Python and Node then consumed the same recorded
provider responses. All three stages returned 30 mode/question rows and five
publication receipts, with normalized parity and verified cleanup. The 90 rows
are dependent reproductions of six questions, not 90 independent trials.

### All compared configurations

Every mode used the same reviewed corpus, trusted tenant/collection scope and
required filters. Retrieval never received answerability labels or reviewed
support anchors. Coverage had no configured semantic assessor and remained
unknown. PostgreSQL native full-text search is not BM25.

| Mode | Search and ranking configuration |
| --- | --- |
| Lexical | Native PostgreSQL FTS; up to 15 candidates; no query embedding or reranker. |
| Dense | OpenAI `text-embedding-3-small`, 1,536 dimensions; up to 15 dense candidates; no reranker. |
| Hybrid | The same dense profile plus native FTS, with an identifier branch when the query contains recognized identifiers. Equal family weights, reciprocal-rank fusion constant 60. The total candidate budget is 15: dense/lexical quotas 8/7 without an identifier branch, or 5/5/5 with it. |
| Reranked hybrid | The same hybrid search followed by Cohere `rerank-v5.0-fast`, using the same authorized shortlist before/after ranking. Higher relevance scores rank first; UTF-8 preprocessing revision `utf8-evaluation-r1`; truncation rejected; rerank cap 40, bounded here by the 15-candidate search cap. |
| Corrective | Hybrid backend with that reranker; deterministic query-only whitespace-normalized and identifier variants, deduplicated against the original query. Planner selects bounded variants for missing facets; batch size 15; no provider retries; the shared attempt/subquery/call limits below still apply. |

Common request limits were 25,000 ms, 15 candidates, three attempts, three
subqueries and eight provider calls. Output used `cragkit.context.v2`, strict
`cl100k_base` counting, a 20,000-token ceiling and 256 reserved envelope tokens.
The pinned tokenizer SHA-256 was
`223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7`.
Ingestion used canonical chunk targets of 2,048 bytes and a 4,096-byte maximum.
Evidence defaults used 256 surrounding bytes, no rebalance, no degraded search
fallback and no rerank fallback. The frozen pool-client budget was two; each
worker pool was capped at one client.
Model names were provider aliases, not immutable model snapshots.

The preregistered targets were zero observed invariant violations, operational
failures and false-sufficient results; nonnegative hybrid-minus-lexical recall,
reranked-minus-same-shortlist MRR and corrective-minus-reranked support recall;
and verified cleanup. These were narrow acceptance conditions, not claims of
useful semantic coverage or model superiority. No target was lowered for the
recovery run.

### Retrieval and coverage results

Metrics used `V6-reviewed-span-r1`, k=5 and final released document/revision order.
Recall, reciprocal rank, binary nDCG and continuous UTF-8 support-span recall
averaged five questions with positive reference support. The question with no
positive reference was excluded from those averages, but retained in binary
diagnostic denominators. Operational failures would score zero on eligible
retrieval questions and remain separate from abstention decisions.

| Mode | Document recall@5 | MRR | nDCG@5 | Facet-support recall@5 | Eligible questions |
| --- | --- | --- | --- | --- | --- |
| Lexical | 0.0 | 0.0 | 0.0 | 0.0 | 5 |
| Dense | 0.8 | 0.8 | 0.8 | 0.8 | 5 |
| Hybrid | 0.8 | 0.8 | 0.8 | 0.8 | 5 |
| Reranked hybrid | 0.8 | 0.8 | 0.8 | 0.8 | 5 |
| Corrective | 0.8 | 0.8 | 0.8 | 0.8 | 5 |

Hybrid-minus-lexical recall was +0.8 over five paired questions. Reranking MRR
gain on its original shortlist and corrective support-recall gain were both
0.0 over five eligible pairs. Six shortlist comparisons were verified, including
the empty historical case. There was no measured reranker or correction gain.
Rank/support means have eligible denominators but no population confidence
interval: this fixed, tiny synthetic suite does not support that interpretation.

The following counts and two-sided 95% Wilson intervals apply separately to
each of the five modes. Intervals are rounded to four decimals; mode results and
replays must not be pooled as independent samples.

| Diagnostic | Count / denominator | Observed rate | Wilson 95% interval |
| --- | --- | --- | --- |
| False-sufficient results | 0 / 6 | 0 | [0, 0.3903] |
| Authorization, identity and fidelity violations, each | 0 / 6 | 0 | [0, 0.3903] |
| Operational failure and degraded execution, each | 0 / 6 | 0 | [0, 0.3903] |
| Abstention | 6 / 6 | 1 | [0.6097, 1] |
| Answerable-question abstention | 3 / 3 | 1 | [0.4385, 1] |
| Required abstention recall | 3 / 3 | 1 | [0.4385, 1] |
| Abstention correctness | 3 / 6 | 0.5 | [0.1876, 0.8124] |
| Conflict detection miss | 1 / 1 | 1 | [0.2065, 1] |

Every result withheld sufficiency, including all three fully answerable
questions. There were no sufficient outputs, so useful sufficient-acceptance
precision could not be estimated. The one conflict was not identified.
Active-generation-only historical search returned no evidence for its historical
question. These failures remain in the denominators. Zero false-sufficient
observations under universal withholding do not establish useful coverage
assessment, reliable final answers, source truth or broad retrieval quality.

### Calls, cost and observed live latency

The run made 39 live requests: 29 OpenAI embedding calls and ten Cohere reranks.
Each replay made zero new HTTP calls. The recorder's usage-based estimate was
USD 0.00004206; actual account billing and per-baseline counterfactual cost were
not measured. Admission allowed at most USD 0.02 total, USD 0.01 per provider,
60 calls, one concurrent call and zero retries. Configured rates on the run date
were USD 0.02 per million input tokens for each selected provider profile.

| Mode | Live median latency, ms | Live nearest-rank p95/max, ms | Samples |
| --- | --- | --- | --- |
| Lexical | 9.7992 | 11.0192 | 6 |
| Dense | 424.4728 | 482.7207 | 6 |
| Hybrid | 411.4404 | 468.3815 | 6 |
| Reranked hybrid | 4,746.5832 | 5,814.0050 | 6 |
| Corrective | 6,589.6164 | 7,619.7380 | 6 |

These end-to-end observations include network time and provider pacing. With
six samples, nearest-rank p95 is the maximum. They are descriptive measurements,
not independent latency confidence intervals or general performance guarantees.

## Resource and platform evidence

Separate resource checks used an M4 ARM64 laptop with 16 GiB RAM and macOS 27.2:
five fresh import processes per runtime, plus three-document fake-provider
workloads with one client/one waiter and 20 requests per runtime at concurrency
one and two. These bounded checks do not establish cold storage, large-corpus,
long-soak or population performance. Immediate Node backend reuse after active
cancellation and independent server-side cancellation acknowledgment remain
unsupported; reuse needed bounded recovery probes.
Corrected hosted package checks used macOS 15.8.2 ARM64; they did not establish
Linux, Windows, other architectures or every allowed runtime patch version.

## Reproduction, release identity and remaining limits

Maintainers retained the frozen configuration, reviewed packet, exact response
recordings, metric definitions and raw-file hashes. Recorded Python and native
Node reproductions passed privately with no new model requests. This summary
does not distribute that packet or provide an independently runnable public
reproduction of these historical numbers. An independently recreated synthetic
example would be new evidence, not a reproduction of this benchmark.

The historical compatibility replay targeted source
`0c7c568d5cb71638eebab2dea97c5973b0f8cc08`. The later corrected RC1 publication
candidate was `a3ff7e81332d849724407356d220c991e8a8411d`; it was not newly
evaluated with live models. RC2 packaging/README work and Python RC3 publication
attestations have their own exact-product and installed-consumer evidence.
Native runtime payloads match published RC1 apart from declared version constants;
this is not a new live evaluation or an independent behavioral guarantee. Publish attestations
identify the publisher and file digest, not source security or a hosted build.

Human usability evidence remains unavailable. An agent rehearsal does not supply
human task time, comparative integration effort or adoption evidence. Qualified
CSO coverage remains partial despite closed reviewed finding dispositions.
Qdrant evidence is limited to the selected single-node 1.20.0 profile. Migration
and recovery require explicit operators, current authorization and quarantined
backups. No universal security, zero-hallucination, downstream answer-quality,
production-readiness or generalized hardware claim follows.
