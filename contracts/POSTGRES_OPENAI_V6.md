# PGO-r1: Explicit PostgreSQL OpenAI profile

State: FROZEN implementation contract. Native mechanics passed 16 operator and 40 runtime checks; successful real-profile publication and live quality acceptance remain pending V6-02. The initial V6 candidate will be superseded and refrozen before held-out access, preserving quality targets and split digests.

For example, equal 1536 dimensions do not make a synthetic vector compatible with an OpenAI vector. Each profile has its own physical table, immutable model identity and explicitly selected runtime configuration.

## Scope and ownership

This is the missing native PostgreSQL integration for the already selected E-r1 OpenAI profile, required by V6's five-mode live comparison. It adds no model, server architecture, generic dynamic backend or new request field. Keep all applied lexical/setup migration bytes unchanged. Qdrant contracts, fingerprints and runtime files are protected and unchanged.

Root owns this contract, new setup SQL, explicit operator runner, shared fixtures/digests, tracker, candidate refreeze and final integration. Python and TypeScript peers own their separate native runtime paths in a clean detached worktree. They implement two reviewable dependent slices per language, first profile/session/ingestion and then orchestration/accounting/lifecycle. Python assembles the pair. No peer changes shared migration bytes, schema/fixture files, locks, package versions or the tracker. Test/native slots remain serialized. The user's dirty original source files remain untouched until root applies the integrated patch while preserving their edits.

## Immutable storage states

| Exact setup history | Exact registry | Runtime support |
| --- | --- | --- |
| Existing 0001 and 0002 checksums | Original fake row only | Default fake profile only |
| Existing two checksums plus 0003 | Original fake row and exact E-r1 OpenAI row | Either profile, selected explicitly |

The new `0003_openai_te3small_1536.sql` SHA-256 is `9f909b14e690112fbc4c8671f7e758e839e615e68aad33f927b400ea04eb9f16`. It replaces only the registry's fake-only CHECK with an exact two-tuple CHECK, retains the immutable registry trigger, inserts `openai_te3small_1536_r1` and creates `chunk_vectors_openai_te3small_1536`. The new table has the exact profile CHECK, vector(1536), unit-norm CHECK, primary key, registry FK and complete chunk/generation cascade FKs, RLS enabled and PUBLIC privileges revoked. No runtime role receives automatic grants or policies. Explicit operator provisioning owns those choices.

Admission matches the complete history, registry and applicable table invariants, including validated keys/constraints, enabled RLS and effective restricted privileges. Unknown suffixes, missing/mismatched rows, wrong hashes, a missing/altered table, disabled constraints/RLS or unsafe membership fail closed. Arbitrary prefix or selected-row-only checks are insufficient. No import, constructor or read/write initialization applies a migration. An old binary encountering an unknown upgraded setup remains incompatible; rollback compatibility is explicit.

## Trusted profile and execution

Add optional constructor `embedding_profile`, default `FAKE_PROFILE`, to native PostgresVectorIndexer, PostgresRetriever and PostgresCorrectiveBackend. Snapshot the exact existing E-r1 profile; reject unknown profiles and mismatched embedders before I/O. A valid OpenAI adapter without explicit OpenAI selection retains the previous unsupported/default refusal. No table name or profile can be chosen in agent-editable request input. A closed internal two-profile map alone chooses fixed SQL identifiers.

Thread the selected snapshot through native sessions/handles, ingestion receipts/payload/generation identity, SQL table selection, dense candidates, fusion, versions and corrective handoff. Every batch must match the full selected profile and correct synthetic flag. Fake identities, fake generation hashing and known-zero accounting remain unchanged. OpenAI rows never inherit a fake candidate default. Source identities, exact excerpts, filters, immutable revisions and authorization remain the existing contracts.

Before new-profile inference, acquire a bounded capability/preauthorization lease, validate the selected compatible storage, and release it. Revalidate in the actual search/write lease. No model callback runs inside a database transaction. Legacy schema refusal must happen before transport dispatch. Shared deadlines, candidate/attempt limits and cancellation continue to apply.

## Per-call dispatch hook

EmbeddingAdapter embed_query/embed_batch gains optional trusted `on_dispatch`, a synchronous void callback passed per call, never stored as shared request state. Validate it before I/O; invoke it only after input/profile/policy-cost/deadline admission and body construction, immediately before the actual transport call, outside generic provider-error sanitization. Typed budget/admission failures propagate unchanged and prevent transport. Reject async/nonvoid callbacks without transport and observe/close invalid awaitables. Existing callers without the hook retain their behavior. The live PostgreSQL path uses the hook for atomic ledger admission; it does not mutate private transport fields. Verify predispatch refusal, cancellation, dispatched failure and unknown usage separately.

## Usage and lifecycle

On the live path, reserve model budget at actual transport dispatch. Predispatch admission failure is not a billed call; a dispatched failure retains a call and unknown usage. Successful reported token usage stays reported; estimated cost must not become known account billing. ExecutionLedger's current known/unknown contract may retain unknown cost while the adapter keeps its estimate separately. Do not add a new public cost enum in this slice. Fake accounting retains its existing adapter-boundary semantics and tests.

Extend the exact lifecycle cascade graph with the new table's complete chunk and generation edges. Purge must preserve its existing rollback and authorization checks on legacy and upgraded storage. No security rollback restores revoked access.

## Acceptance before refreeze

Verify both runtimes against genuine PostgreSQL17.11/pgvector0.8.0, with deterministic injected provider responses for mechanics and no vectors mislabeled as live inference. Keep live-model quality separate.

1. Legacy fake defaults and golden ingestion identities remain unchanged; upgraded fake and explicit OpenAI operations use separate tables.
2. OpenAI on legacy storage, default/explicit profile mismatch and full-profile/synthetic/batch mismatches fail before disclosure or mutation.
3. Unknown history, registry drift, missing/altered table, disabled RLS or validated-constraint drift fail admission.
4. Same-intent profile changes, interrupted staging, cancellation, replay, CAS, revisions, revocation, tombstones and purge preserve prior behavior.
5. Dense/hybrid/reranked/corrective native execution preserves selected profile/version/usage and exact source/filter parity; lexical behavior stays unchanged.
6. No transaction is held during inference. Predispatch failure, dispatched failure and successful unknown/estimated billing receive distinct honest accounting.

Run focused native-language regressions first, then existing shared contracts and serial combined native acceptance. Record exact commands, configuration, resources and cleanup. Only root accepts the parent and refreezes candidate source identity before held-out execution. Explain one failure case in the learning guide; practice remains optional and unassessed.
