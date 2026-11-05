# ADR 0002: Bounded reranking contract and model shortlist

This dated decision records the design at acceptance. It does not report current implementation or release completion; use the [current roadmap](../roadmap.md) and [RC1 notes](../releases/V6.md) for that state.

Date: 2026-10-24. Task: V3-01. Contract revision: RK-r1.

Status: contract and shortlist decision; real model selection, runtime adapters and quality acceptance remain pending.

## Decision

Use an injectable fake or recorded-response reranker first. The [shared contract](../../contracts/RERANKER_V3.md) and [synthetic recordings](../../contracts/fixtures/reranking.json) establish deterministic mapping, ordering, score semantics and failure behavior. These recordings were authored for contract verification; they are not outputs captured from either shortlisted model. Their compatibility evidence concerns JSON mechanics only.

For example, a synthetic logit of `-2.0` can be a valid relevance score. It ranks below `1.0` when larger scores rank first. Applying sigmoid preserves this ordering, but a transformed value is not a calibrated probability that a source is true or that all question facets are answered.

Keep at most 40 candidates, explicit byte/input bounds, a shared request deadline and cancellation. Reject missing, duplicate or unknown candidate mappings and nonfinite scores. Preserve raw scores, their direction and model/configuration identity. Break ties according to RK-r1. Do not use a universal score cutoff or derive sufficient coverage from a maximum score. Release the search transaction before model work and reauthorize source release afterward, as required by the [architecture](../architecture/ARCHITECTURE.md).

No paid call, dependency installation, model download or selected real-model default follows from this ADR. V3-02 must implement the bounded adapters and perform its explicit live comparison after the application configures the model and approves the associated resource and disclosure choices. V3-07 owns development-label policy calibration.

## Shortlist checked against primary documentation

Sources below were checked on 2026-10-24. Identifiers describe the documented options on that date; availability and APIs require another check before execution.

| Candidate | Score and input semantics | Compatibility evidence and limits |
| --- | --- | --- |
| Local `cross-encoder/ms-marco-MiniLM-L6-v2` | English MS MARCO passage-ranking model. Its published config uses an Identity activation, six layers and 512 position embeddings. Sentence Transformers documents MS MARCO outputs as logits; sigmoid is an optional monotonic transform. | A modest local comparison candidate, not a measured laptop fit. Native Python library examples exist. Native Node execution and numerical/tokenizer equivalence have not been measured. |
| Hosted Cohere `rerank-v5.0-fast` via `/v2/rerank` | The model catalog lists this exact identifier with a 32k context. Preserve the provider's `relevance_score` as a provider-defined relevance score, larger first, without relabeling it source truth or coverage. | HTTP permits separate native Python/Node clients without a Python service. Endpoint access, account availability, latency, billing and cross-runtime response compatibility have not been exercised. This is a shortlist entry, not a claim that it is the best or newest choice. |

Local references: [model card and Apache-2.0 license declaration](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2), [published model configuration](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2/raw/main/config.json), and [Sentence Transformers score semantics](https://www.sbert.net/docs/cross_encoder/usage/usage.html). A live configuration must pin an immutable model revision, tokenizer assets, runtime versions, device, precision and activation; a mutable `main` reference is research evidence, not a reproducible execution pin.

Hosted references: [Cohere model catalog](https://docs.cohere.com/docs/models) and [Rerank API reference](https://docs.cohere.com/reference/rerank). The provider advertises calibrated relevance for this family; that claim does not establish calibration on Cragkit's corpus, facet coverage or source truth. Record the exact provider identifier and API version, plus returned version/request metadata where available. Do not invent an immutable hosted weights revision when the API does not expose one.

## Input and truncation policy

RK-r1 byte limits bound transport and memory; they do not establish a tokenizer limit. A future local adapter must count the complete query-passage pair, including special tokens, against the pinned tokenizer/model limit. The 512-position local configuration cannot be treated as 512 passage tokens plus an unlimited query. Pin preprocessing and truncation side in both runtimes. Reject over-limit inputs by default. Any explicitly enabled truncation must retain the original candidate identity and record the exact submitted slice and truncation metadata; it must never change the immutable source revision or canonical citation span.

The hosted API documents automatic document truncation at `max_tokens_per_doc`, whose documented default is 4096. Its catalog also describes query-document context accounting and internal chunking. These are distinct from Cragkit's candidate cap and byte bounds. A hosted adapter must set its limit explicitly and establish how the actual submitted/processed representation is known. If exact provider-side truncation cannot be established, record that uncertainty and fail: RK-r1 does not support unknown truncation. Never mark such input as fully observed. Request all candidate scores; `top_n` filtering cannot silently create an incomplete mapping. Provider passages or offsets are not authorized canonical source excerpts.

## Optional dependencies and resource gates

Keep every model/client dependency outside core imports. Python could use optional `sentence-transformers` with PyTorch, or an optional ONNX path. [Sentence Transformers backend documentation](https://www.sbert.net/docs/cross_encoder/usage/efficiency.html) describes PyTorch, ONNX and OpenVINO; it does not prove Node compatibility. A native Node ONNX runtime and equivalent tokenizer/preprocessing would need a separate pinned compatibility probe. Do not add these packages or a Python server for npm as part of V3-01. Hosted clients may use optional language SDKs or bounded HTTP adapters; exact dependency versions remain a V3-02 decision after manifest/API inspection.

The development constraint is the plan's M4/16 GB machine, not a measured support promise. Before a local run, inspect available memory/disk, model asset size and all dependency/model licenses. Record cache paths and approved downloads. Start with one model, one bounded worker and small batches; move CPU work away from the event loop. Cancellation must stop waiting/dispatch and report any inference that cannot actually be interrupted. Stop and reduce the workload if pressure or responsiveness deteriorates. No memory, throughput or latency result was measured for either shortlist option here.

Before a hosted run, explicitly configure the destination, credentials, approved query/passage disclosure, timeout, request/attempt caps and spend ceiling. Check current pricing and provider data/retention terms for the selected account and deployment. The local Apache-2.0 declaration does not license a hosted service, and an API response is not evidence of zero cost. Do not commit credentials or private evaluation text. No provider call or billable usage occurred in this slice.

## Acceptance boundary and next action

The recorded development sample can show that negative logits survive validation, tied scores sort deterministically, malformed mappings fail and explicit truncation remains visible. It cannot show relevance quality, factuality, live model equivalence, cancellation of real inference, native runtime support or resource fit. The final integrator records actual fixture checks and resource observations in the V3-01 report; this ADR alone is not proof those checks passed.

Next: implement V3-02 with fake failure cases first, then compare explicitly configured real candidates under the same small development sample and bounded resource policy. Keep held-out labels sealed. A failure example is a provider returning only its top three scores for forty supplied candidates: reject the incomplete response rather than assigning invented scores to the other candidates. Learning exercise: explain why a logit, its rank and a calibrated decision answer different questions.
