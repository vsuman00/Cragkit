# Small-corpus evaluation protocol

V0-06 prepares local labels and mechanical checks. The initial packet contains original synthetic documents and synthetic question labels. The project user approved all 30 labels on 19 October 2026. The [review record and integrity seal](review/seal.json) preserve that decision and the frozen inputs; agent drafting and automated checks do not supply human approval. See the [review packet](review/V0-labels.md), [manifest](corpus/manifest.json) and [architecture validation gate](../docs/architecture/ARCHITECTURE.md#13-validation-and-release-evidence).

For example, a label quoting `café 🙂` must use the exact UTF-8 byte span and canonical source digest. Matching that span establishes the label's reference; a human must still judge whether it answers the facet.

## Files and labels

The manifest uses schema version `0.1`. Each immutable document revision declares tenant, collection, document and revision identities, a family, development or held-out split, active state, corpus-relative path and SHA-256 digest of the exact source bytes. Preserve source bytes when labeling. A changed revision needs a new identity and reviewed labels.

Question files are [dev.json](questions/dev.json) and [held_out.json](questions/held_out.json). Each declares synthetic origin and a human-review state. Questions declare tenant, collection, query, required equality filters, answerability and facets. Support references carry document/revision IDs, byte offsets, exact text and canonical digest. Missing facets have no support; conflicts have at least two distinct spans for human inspection. A validator cannot establish that two excerpts actually conflict or that an absent answer exists nowhere in the authorized corpus.

The initial label format permits only equality filters on `document_id` and `revision_id`. This bounds fixture validation; the library request contract supports its separately defined filter tree. Supports must match the question's tenant, collection, filters and split. Active revisions are the default; a historical support requires an explicit revision filter. No family may appear in both splits. Treat long numeric-looking IDs as strings.

Answerable labels have supported facets throughout. Partially answerable labels include available evidence and an unresolved missing or conflicting facet. Unanswerable labels have only missing facets and empty support. These are reviewer judgments recorded in fixtures, not measured engine outcomes.

## Mechanical checks

From the project root, proposed commands are:

```sh
python3 tools/check_corpus.py
python3 tools/check_corpus.py --include-held-out
python3 tools/check_corpus.py --include-held-out --require-human-review
```

The default validates all corpus source digests and split metadata, then reads development labels only. It does not open the held-out question file. The explicit held-out option allows initial mechanical review of all labels; output contains counts, never answers or query/source text. Source files remain readable in this repository, so this is an operating convention rather than a security boundary.

Checks cover document/revision identity uniqueness, one active revision per document, safe corpus-relative paths, valid UTF-8 sources, exact source digests, family isolation, question/facet IDs, authorized references, declared filters, exact byte spans, support digests and label consistency. The checker performs no retrieval, source-network fetch, provider call or model evaluation. Its focused tests use temporary tiny corpora and mutated labels. Actual command results belong in the task evidence and tracker, not this protocol's proposed command list.

`--require-human-review` fails while any loaded dataset is pending. It accepts an `approved` declaration only with a reviewer identity; it does not authenticate that identity or create approval. The coordinator records such a declaration only after the user's actual review. Run the flag with `--include-held-out` when checking the complete initial review gate.

## Human review and sealing

Before requesting approval, prepare the complete review packet and run the mechanical checks. The user reviews every source/support span and facet, resolves ambiguous wording, checks answerable and absent-answer judgments within authorized scope, verifies conflicting claims and inspects tenant/revision negatives. Record corrections, reviewer identity, review decision and fixture revision. Preserve pending status until that review occurs. V0-07 depends on accepted V0-06 labels.

After approval, freeze the family split and record digests of the manifest, source revisions and both question files. Mark the held-out set sealed in the review record. Initial authoring and review have exposed it to the current agents; disclose that exposure. Use a separate reviewer and additional unseen families for later stronger evaluation where practical.

After sealing, tune prompts, policies, thresholds and implementation choices on development data only. Keep held-out labels out of routine agent context and development runs. Freeze compared configurations and quality targets before a deliberate held-out run. Record access, configuration, fixture digests, complete results and limitations. If a held-out failure informs a change, record the contamination and obtain a fresh held-out set for an unbiased later comparison.

No retrieval score, false-sufficient rate, latency, memory benchmark or model-quality result exists from label checking. Later quality work needs larger diverse human-reviewed suites, scoped measurements and confidence intervals where the sample permits them.

Learning remains pending. One failure case: a correct quote from the other tenant must fail label validation even if its text answers the question. Exercise: inspect one multibyte excerpt and explain why its byte offset differs from its character index.

## V2 development ablation

V2-08 freezes six development questions in [the shared HY-r1 fixture](../contracts/fixtures/hybrid.json) before measuring lexical, dense and hybrid retrieval: current identifier, historical revision, absent answer, second tenant, conflicting sources and an explicit document filter. [HY-r1](../contracts/HYBRID_V2.md) and the [native runner](../tools/check_hybrid.py) declare the configuration. The encoder hashes ASCII word counts to 1536 dimensions and normalizes them; it reads no labels. This synthetic baseline tests mechanics and cannot establish hosted-model quality.

The runner verifies the approved manifest/development-label state, indexes all nine development revisions on the dedicated empty development target and preserves the active pointer rules. It maps label revision IDs to generated immutable physical IDs; a historical filter is retained rather than broadened to the current revision. Both runtimes use the same stored corpus and queries. Compare complete normalized results, including verified source/context and redacted execution/accounting fields. Hold provider calls, database clients and test suites serial and bounded.

Metrics at k=5 count distinct document/revision identities: document recall, reciprocal rank and binary nDCG. Macro averages exclude questions with no positive references; report their denominator. Support-span recall separately checks continuous byte coverage, allowing any approved support for a supported facet and requiring all references for a conflicting facet. Evidence on unanswerable labels is a separate rate and does not assert that every returned statement is false. The fixture has six questions, five with positive support and one unanswerable question.

Report per-question ranks, aggregates, manifest/label digests and observed per-runtime end-to-end latency. Declare known zero synthetic model spend separately from unmeasured hosting cost. Investigate lower-ranked expected sources and missed historical targets with reviewed source references; rerun parity after fixes without quietly tuning the frozen comparison. Preserve held-out labels and seals. [V2 results and limitations](reports/V2/V2-07-08-exit.md) distinguish this small development baseline from live or held-out quality evaluation.
