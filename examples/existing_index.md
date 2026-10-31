# Existing-index example

For example, an application already owns a lexical record for `retry@r1` and its canonical UTF-8 source. These examples resolve the exact revision, verify its digest and byte span, then return Cragkit's native `RetrievalResult`. A query cannot supply a tenant, collection, ACL or required filter: the application binds those when constructing the adapter.

The examples use public request, evidence, result and packing contracts. They demonstrate an application adapter; they do not register a new backend in `PostgresRetriever` or certify an arbitrary vector store. Python and Node run independently, with no database, model, provider, tokenizer asset or Python server for Node. Imports perform no example retrieval.

From the repository root, after the normal development setup and TypeScript build:

```sh
uv run --project packages/python --frozen --no-sync python examples/existing_index.py
node examples/existing_index.mjs
```

The Node example uses the repository's built package files. In an installed application, the corresponding public imports are `cragkit/contracts`, `cragkit/evidence` and `cragkit/errors`. No installation or execution is performed by these files themselves.

| Capability | Declared behavior |
| --- | --- |
| Search | All query terms must occur as lowercase substrings in the index's search text. This is a tiny lexical example, with no ranking, dense search or BM25. |
| Access scope | Tenant, collection, current authorization revision and principal/grant eligibility are checked before matching or source resolution, against the resolved source, and once more after packing before the result returns. |
| Required filters | Only string equality on document ID, revision ID, language, kind or tag. Other valid Cragkit filter forms fail with `UnsupportedCapability`; they are never dropped. |
| Source provenance | Nonempty immutable revision, locator, canonical SHA-256, excerpt SHA-256 and exact UTF-8 byte boundaries are required. Text comes from the caller's resolver, not from an index-provided excerpt. |
| Resource bounds | At most 16 index records, 64 KiB per canonical source, a five-second release deadline and estimated context counting. The example accepts synchronous source resolvers only. |
| Coverage | No reviewed assessment policy is supplied. Evidence produces `partial` with unknown coverage, never a sufficiency claim. Empty authorized results are `insufficient`; a missing source is an operational failure. |

The application must provide immutable revisions and current authorization metadata in both its index records and its source resolver. The example snapshots the caller's index, scope and filters. A production integration needs its own current authority lookup and revocation strategy; this in-memory snapshot is not a long-lived authorization cache policy. Synchronous resolver calls cannot be preempted: the application must bound their work, and the adapter rechecks its deadline before releasing a result. Exact source fidelity does not establish relevance or truth.

One failure case: a matching record without `revision_id` raises `IntegrityViolation` before the resolver runs. A resolver returning a different tenant or a source that no longer meets a required filter raises `UnauthorizedScope` before text is returned. Missing resolution support and unsupported dense/filter capabilities raise `UnsupportedCapability`; unavailable source data raises `ProviderUnavailable`.

Focused checks live in `packages/python/tests/test_existing_index_adapter.py` and `packages/typescript/tests/existing-index-adapter.test.mjs`. They cover exact multibyte evidence, cross-tenant refusal, revocation before return, fresh source authorization, missing revision/digests, unsupported capabilities, changed bytes and a span that splits `é`. These examples are implementation work; V5-05 final acceptance still depends on the upstream V5-04/C2 gates and the integrator's verification.

Small exercise: change the resolved source's tag to `private` while keeping the index tag `public`. The required filter must still prevent source release.
