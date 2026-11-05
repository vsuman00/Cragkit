# Qdrant corrective integration: QCC-r1

Task: V5-07. This contract extends the trusted backend handoff used by the native corrective engines. It does not change the request or result wire schemas.

State: accounting/candidate handoffs, both optional adapters and the declared native backend/transport matrix are accepted under V5-07. Clean installed artifacts remain V5-08. See native evidence (record retained in the private maintainer archive) for tested profiles and limits.

For example, PostgreSQL cosine distance 0 and Qdrant cosine similarity 1 can describe the same direction. Keep each backend's score semantics rather than converting a nomination into a PostgreSQL distance candidate.

## Candidate and accounting boundary

The Qdrant backend returns a closed internal candidate with `backend: "qdrant"`, the existing tenant/collection/document/revision/generation/chunk/span/text-digest fields, its unchanged native score, and its complete immutable `nomination`. Common identity, span, digest and score must equal the nomination. The nomination retains its branch, score kind/direction, complete profiles and payload. It remains unverified until QS-r1 source resolution. These internal candidates and private sources never enter the public result schema.

Existing trusted backends use outer candidate accounting by default. A backend may explicitly declare `candidate_accounting: "backend"`; the corrective engine snapshots that declaration during construction. It then reserves only the logical attempt while that backend's native search reserves candidate work on the same ledger. A successful search must increase candidate usage by exactly the admitted limit; undercharging or inconsistent usage fails integrity validation. Failed work retains whatever native charges occurred. Deadline, attempt and candidate ceilings are unchanged. PostgreSQL continues using outer accounting.

## Optional native adapter

Separate optional Python and TypeScript Qdrant corrective entry points compose initialized candidate/source stores and an explicitly supplied embedding transport, counter and policy. They construct the existing E-r1 adapter locally so provider accounting occurs at actual transport invocation. Imports perform no I/O. Resources remain caller-owned. Dense search is initially supported; lexical/hybrid capability is explicitly unsupported. Candidate/source profiles must match before calls, and E-r1 validates model responses. No model download, implicit key discovery or paid default is introduced.

Search uses the real QC-r1 store and shared execution ledger. Capture opens a fresh QS-r1 request handle, verifies each nomination, obtains exact authoritative source bytes, reauthorizes final release, preserves stale/budget diagnostics and closes the handle. Repeated captures accumulate actual bytes through the outer request ceiling. Source/operational failures cannot become an empty successful search. No SQL lease spans model work or HTTP. Native similarity values remain private diagnostics and do not imply coverage.

## Acceptance slices

1. V5-07A: Native candidate and accounting handoff in both cores. Test signed similarity, mismatched mirrored identity/score, wrong branch/kind, exact single reservation, undercharging, retries and prior PostgreSQL behavior.
2. V5-07B: Optional native Qdrant corrective adapters with fake embedding providers for routine tests; bounded source release, profile mismatch, current authorization, cancellation and byte limits.
3. V5-07C: Actual disposable PostgreSQL/Qdrant direct, tool and official MCP conformance in both runtimes. Use common deterministic data/providers, explicit backend capability differences, source identities/status/budget checks and partial-publication faults. Normalize only declared timing and raw backend ranking differences. Record every tested combination and cleanup.

All three slices must pass before V5-07 completes. Native backend/transport execution is distinct from fake-provider contract tests and from V5-08 clean installed artifacts.
