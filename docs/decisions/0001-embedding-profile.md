# ADR 0001: First embedding profile

This dated decision records the design at acceptance. It does not report current implementation or release completion; use the [current roadmap](../roadmap.md) and [RC1 notes](../releases/V6.md) for that state.

Date: 22 October 2026. Task: V2-01. Status: ACCEPTED as a design decision. The owner selected hosted, opt-in OpenAI `text-embedding-3-small`, 1536 dimensions, fake providers for routine work and live access disabled until separately configured. No paid call, model-weight acquisition or document disclosure is approved by this record. The [current roadmap](../roadmap.md) owns completion state.

## Why this decision comes first

For example, “restart the service” and “reboot the daemon” can be close in a model's vector space even without matching words. A vector is a coordinate list, not a source citation or proof that a passage answers the question.

The original product requirements (retained privately) require measured quality and cost (BR-05), bounded work (BR-06), compatible generations (BR-08), explicit disclosure choices (BR-09) and optional integrations (BR-10). The [architecture](../architecture/ARCHITECTURE.md) requires native Python and Node execution, optional model dependencies and immutable source references. The original V2 plan, retained privately, assigned adapters to V2-02/V2-03, vector storage to V2-04 and quality comparison to V2-08. This decision does not implement those tasks.

## Compared candidates

| Property | Small local candidate | Hosted candidate |
| --- | --- | --- |
| Identity | `sentence-transformers/all-MiniLM-L6-v2`, repository revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` | OpenAI `text-embedding-3-small`; no immutable dated snapshot verified |
| Application profile / unselected alternative | `minilm_l6_v2_384_fp32_256_mean_l2_r1` | `openai_te3small_1536_r1` |
| Dimension | 384 | Explicitly request 1536 |
| Preprocessing | Pinned tokenizer, 256 total positions including special tokens, attention-mask mean pooling and L2 normalization | Unmodified approved UTF-8 text; no query prefix; explicit float output and dimension |
| Inference location | Native optional ONNX Runtime in each application process | HTTPS request from each native application; no Python server for Node |
| Laptop trade-off | Model/session, tokenizer, CPU work and optional native packages | Client and response processing; remote inference and network dependency |
| Disclosure | No hosted inference disclosure when assets are acquired and inference stays offline | Approved source/query text leaves the machine |
| Terms | Apache-2.0 model card; retain license/notices and review runtime/tokenizer dependencies separately | Hosted service under applicable account terms; no open-weight license inferred |
| Metered inference price | No hosted embedding charge; local compute/setup still has cost | Dated reference: USD 0.02 per million ordinary input tokens; not a spending authorization |
| Main unresolved risk | Actual Python 3.14 / Node 26.5 execution, preprocessing parity and resource use | Provider policy/credentials, availability and unpinned alias drift |

Local facts come from the [model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2), [pinned sentence configuration](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/sentence_bert_config.json), [tokenizer configuration](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/tokenizer_config.json) and [pooling configuration](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/resolve/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/1_Pooling/config.json). Hosted identity and price come from the [official model page](https://developers.openai.com/api/docs/models/text-embedding-3-small); dimension and unit normalization are documented in the [embedding guide](https://developers.openai.com/api/docs/guides/embeddings).

The local ONNX directory lists a 90.4 MB FP32 model and a 23 MB arm64 int8 variant. Start a future parity probe with FP32; a quantized asset is a separate profile. Those figures describe individual weight files, not installed size or model RAM. [Official assets](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41/onnx).

Official package metadata lists an ONNX Runtime 1.31.0 Python 3.14 macOS arm64 wheel and onnxruntime-node 1.30.0. The npm package reports about 301 MB unpacked and no Node engines restriction. These establish candidate availability, not successful installation or cross-runtime parity. The ONNX Runtime Node binding documents macOS arm64 CPU binaries. Dependencies remain unselected until a native probe; do not install a full training stack. [Python metadata](https://pypi.org/pypi/onnxruntime/1.31.0/json), [Node metadata](https://registry.npmjs.org/onnxruntime-node/1.30.0), [Node platform documentation](https://onnxruntime.ai/docs/get-started/with-javascript/node.html).

## Accepted decision and alternatives

Select `openai_te3small_1536_r1`, backed by OpenAI `text-embedding-3-small`, with explicit 1536-dimensional float output and provider-declared L2 normalization. The owner accepted this hosted, opt-in execution policy in the session. It avoids local model-runtime installation while preserving native Python and Node execution. Routine development uses fake providers. No retrieval-quality advantage has been established on this corpus.

The local MiniLM candidate remains unselected. It is a useful future alternative when privacy and pinned weights take priority, but adds native runtime and preprocessing compatibility work. Changing to it requires a distinct profile and re-embedding; it is not an automatic fallback.

The only selected real provider is direct OpenAI, enabled explicitly by application configuration for this profile. The current configured allowlist remains empty, external source/query disclosure is denied and the live spend allowance is USD 0. No credentials are discovered and no model assets are downloaded. A future opt-in must bind the approved endpoint `https://api.openai.com/v1/embeddings`, allowed input and spend policy outside query input. Do not redirect credentials or use a proxy/provider substitute implicitly.

Choosing a design does not authorize a paid smoke run, account changes or private corpus disclosure. The consuming application always owns its allowed inputs and provider policy. For hosted embeddings, OpenAI documents no training use by default, but abuse-monitoring logs may retain customer content for up to 30 days. Zero Data Retention requires eligibility and approval; do not assume it applies to this account. Review the applicable [OpenAI Services Agreement](https://openai.com/policies/services-agreement/) before enabling an account; this record does not grant model-weight redistribution rights or assess legal compliance. No local-only or zero-retention claim follows from a hosted choice. [Official data controls](https://developers.openai.com/api/docs/guides/your-data).

## Profile invariants for the adapters

These are accepted design constraints for V2-02/V2-03, not implemented configuration fields. Local-specific rules apply only if the unselected alternative is later adopted:

- Bind the profile in trusted application configuration, outside agent-editable query input. Store the full profile identity with every vector generation. Dimension alone is not compatibility.
- Local identity includes exact asset SHA-256 values, tokenizer files, sequence limit, special-token handling, padding, pooling, normalization, precision and application revision. A repository revision alone does not verify acquired bytes. Capture hashes before inference.
- The local sentence limit is 256 although the tokenizer advertises 512. Reject over-limit input rather than silently truncate. Any later splitting/rechunking policy must retain canonical source spans and use an explicit generation/profile change.
- Hosted requests explicitly set `model`, `dimensions: 1536` and `encoding_format: "float"`. Record requested and returned model identity and application profile revision. An unchanged alias cannot prove unchanged weights; require a new generation when changing models, dimensions or preprocessing, and record this alias limitation in evaluations.
- Reject wrong dimension, non-numeric/non-finite components, zero norm, missing vectors, duplicate or out-of-range indexes and incompatible profiles. Check unit norm with a declared initial tolerance of `1e-3`; verify and revise that policy from actual probe evidence before freezing fixtures. Never silently repair a malformed provider vector.
- Routine fixtures use an explicit fake identity distinct from either real profile. Fake vectors can establish validation, cancellation, ordering and accounting behavior; they establish no semantic quality, latency or model-memory result.
- Unknown provider usage stays unknown. Estimate cost only with a dated price and known billable tokens; do not report missing usage as zero. Provider failure remains an operational failure; lexical fallback belongs to the explicit V2-07 policy.

The embeddings API documents nonempty inputs, 8192 tokens per input, up to 2048 array entries and a 300,000 aggregate token ceiling. These are service limits, not development batch settings. Validate indexed responses before use. [Official request/response reference](https://developers.openai.com/api/reference/resources/embeddings/methods/create).

The proposed dimensions fit the documented pgvector `vector` index dimensional bound of 2000. V2-05 still starts with exact search. No migration, extension capability or index has been tested or changed in this task. [pgvector documentation](https://github.com/pgvector/pgvector).

## Laptop and future probe policy

Observed hardware: arm64, 16 GiB physical RAM, 27 GiB disk available and 46 percent system memory free at task start. These are snapshots, not performance guarantees. Recheck headroom immediately before any install or inference. Keep one language/probe process at a time, no Docker/database service for this decision, one model session and one in-flight inference request. Do not sum separate process peaks as a system peak.

For a later local probe: acquire only explicitly approved, pinned assets and optional runtime dependencies; record hashes, installed bytes and licenses. Start CPU-only, batch size one and one worker. Measure import, initialization, query duration, peak process RSS and responsiveness separately. Stop if memory pressure, swap growth or responsiveness worsens. Run Python and Node sequentially on identical synthetic strings and compare token IDs, masks and vectors under a declared numerical tolerance. A model fitting on disk proves nothing about runtime memory.

For a later hosted smoke: require explicit credentials/configuration and allowed sample plus a nonzero spend ceiling. Proposed sample is exactly `Cragkit embedding compatibility probe.`; one request, one input, one attempt, no retries, one in-flight request and a 15-second deadline. Count at most 32 tokens with the declared tokenizer before sending, recheck current pricing and set a local per-run allowance no greater than USD 0.001. At the dated reference price, 32 input tokens would cost USD 0.00000064 before other charges. That estimate is not observed billing or an account-wide hard quota. Never discover a credential automatically or substitute private text for the sample.

For subsequent development, begin with one active ingestion job and small batches capped by both items and serialized UTF-8 bytes; add tokenizer limits before claiming a token ceiling. Exact numeric batch/error contracts will be implemented and verified in V2-02/V2-03. No provider SDK or model runtime becomes a core dependency.

## Evidence and limits

Completed: owner profile-policy decision, primary-source and repository inspection, hardware snapshot and a bounded metadata probe fetching only five pinned public model configuration files. It checked 384 hidden dimensions, the explicit 256 sentence limit, the advertised 512 tokenizer limit, mean pooling and the normalization module. The ignored machine record is `artifacts/V2/V2-01-metadata.json` and includes fetched-file hashes and metadata-process observations: 1.714 seconds elapsed and 30,900,224 bytes peak RSS for the metadata-fetch process. These are not inference measurements. These hashes describe configuration files, not model weights.

A sequential synthetic interface probe on Python 3.14.6 and Node v26.5.0 constructed HTTPS request envelopes without sending them, round-tripped JSON and checked one explicitly fake 1536-component unit vector. Both passed. Metadata is in `artifacts/V2/V2-01-interface.json`. Whole-process peak RSS was 23,871,488 bytes for Python and 55,754,752 bytes for Node; separate elapsed samples were 0.044161 and 0.043231 seconds. These measure a tiny synthetic client process, not network latency, provider inference or production resource needs.

Not run: model inference, model/SDK installation, native model parity, actual provider response validation, retrieval quality/cost evaluation, database changes, package builds or hosted CI. V2-01 is complete as a design decision: its live-sample verification applies only when configured, and the owner explicitly left live access disabled. The metadata/interface checks do not establish live compatibility. V2-02/V2-03 still own adapters, validation, deadlines/cancellation and honest usage; any live smoke remains separately configured and labelled. Code and approved/sealed evaluation data were preserved.

## Learning checkpoint

Imagine model A places a concept on the horizontal axis while model B places it on the vertical axis. Comparing an A document vector to a B query vector can produce a plausible numerical distance with no useful semantic meaning. Even two 384-dimensional models are incompatible without the same declared embedding space.

Failure example: allowing the MiniLM tokenizer's 512 default in Node while Python uses the sentence model's 256 limit changes the represented input. Explicit preprocessing and shared fixtures prevent that mismatch; merely checking vector length does not.

Optional exercise: explain why changing the model requires re-embedding stored chunks, then name two profile fields other than dimension that must match. Explanation provided; user practice remains pending.
