# Native five-mode evaluation execution

State: native execution mechanics COMPLETE (V6-02D1-D3). Sealed original-packet binding (D4), genuine-vector publication and held-out quality remain open under V6-02.

For example, an explicit `r1` revision filter must retain its meaning when storage uses content-derived revision IDs. Both workers translate that alias using ingestion receipts and preserve unknown literals and negation. The scorer can later use a separate logical-ID view; raw result wires retain their actual native identities.

## Implementation and ownership

Sol Python implemented `tools/retrieval_evaluation.py` and its tests; Sol Node implemented `tools/typescript_retrieval_evaluation.mjs` and its tests. Python assembled their interfaces through direct peer coordination. Root owned [EVX-r1](../../../contracts/EVALUATION_EXECUTION_V6.md), the [synthetic packet](../../../contracts/fixtures/retrieval_evaluation.json), `tools/check_native_evaluation.py`, independent checker tests and final integration. All worker files transferred before integration; no unresolved escalation remained.

Each worker validates and snapshots a closed packet containing document text and query/scope/filter data. Labels, support spans, answerability and facet policies are rejected before resource access. Documents ingest through the actual vector indexer; the writer closes before queries. Lexical, dense, hybrid, reranked hybrid and corrective modes run through their native library APIs with frozen request limits and strict pinned context counting. Model callbacks reject active database leases. Mechanics uses the fake profiles; provider/replay paths require explicit trusted configuration.

The workers retain operational failures as failure rows instead of turning them into missing evidence. Caller cancellation propagates while owned resources close. The Node CLI bounds input and total execution, rejects a JSON signal field and handles interruption even before stdin reaches EOF. An all-success replay must consume its whole tape; failed mode rows remain reportable without a false replay-completion claim.

Root review corrected mixed scalar membership translation in Python, preserved boolean/numeric distinction, and required the packet's filter arrays explicitly. Expanded aliases use bounded membership groups; native filter-complexity rejection stays an operational failure rather than dropping restrictions. Root also requested a complete CLI input-time cancellation bound and preservation of primary errors during cleanup. A later real symlink probe reproduced a silent successful exit without execution; root fixed the entry-point comparison using real paths and added a subprocess regression before the final native rerun.

## Verification

Python worker tests passed 23 cases; Node worker tests passed 24 cases without skips. The independent acceptance checker passed 16 cases, including altered source identity, foreign evidence, false token/context declarations, missing/reordered rows, operational failures and failed cleanup. Worker unit tests mock native boundaries and establish control flow, not database behavior or model quality. The complete Python core/tool suite then passed 3,433 tests with four intentional malformed-model warnings; the combined native Node execution/replay suite passed 65 tests without skips.

The disposable native run used the already prepared PostgreSQL 17.11/pgvector 0.8.0 prefix, separate restricted reader/writer logins and fresh databases for each runtime. Each produced four receipts and 30 mode rows without operational failures. Root reparsed results, checked active source identity, exact UTF-8 excerpts, tenant/collection scope, original filters, unknown coverage, budgets and zero fake cost, then independently recounted each final serialized context using the pinned Python tokenizer. All checks passed. The historical, foreign and missing cases released no evidence. Node and Python receipts/results matched after zeroing only stage durations; measured row latency stayed separate.

The first run retained all 30 Python rows but failed a checker expectation: the query used `expiry` while the source used `expire`. The configured PostgreSQL `pg_catalog.simple` text search does not equate those words. Root corrected only the synthetic checker expectation for that lexical case; the packet, query, source and retrieval implementation remained unchanged. This is an expected lexical miss, not a model-quality result. The revised run passed both languages and verified database/listener cleanup.

Commands and result bindings are recorded in [the verification record](V6-02D-verification.json). Raw observations remain under ignored `artifacts/V6/V6-02D/native-mechanics-03/`. Their normalized cross-runtime SHA-256 is `e58600f67d415740241e99347c8279897a23df6667cbd40233eda2db33aadf54`; the packet SHA-256 is `3e418271afe9a8d942dc25be39e5b3325da639d6ad4083fdb91893bcffc71a92`. The failed first run is retained separately, not counted as acceptance. Final headroom was 30 GiB disk and 47 percent system memory free; tests and native services ran serially.

## Limits and next action

This checkpoint used real native PostgreSQL and fake model responses. It made no provider calls, read no credentials, opened no held-out labels and installed no models or services. Existing core/storage code, locks, migrations, frozen quality targets and reviewed source bytes were preserved. No hosted CI or registry publication is claimed. V6 remains in progress.

Next: bind approved original document/query packets to their seals, freeze the exact candidate identity, finish secure key configuration, then record genuine provider responses and reproduce the five-mode comparison. Later V6 resource, security, usability, artifact, rollback, publication and maintenance gates remain required.

Optional exercise: explain why two runtimes producing the same invented excerpt would pass parity but fail source verification. Learning practice remains unassessed.
