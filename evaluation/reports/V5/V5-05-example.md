# V5-05 existing-index implementation evidence

The Python and Node examples map a small caller-owned lexical index to native
Cragkit evidence contracts. This implements the example slice; final V5-05
acceptance still depends on V5-04 and C2. No production-readiness claim follows.

Both examples bind trusted scope and required filters outside query input,
resolve immutable source revisions, verify SHA-256 and UTF-8 byte spans, and
reauthorize after packing. Unsupported dense search and filter forms fail
explicitly. This substring example does not implement BM25 or ranking.

Verification performed by the integrator:

| Check | Result |
| --- | --- |
| Focused Python example tests | 10 passed |
| Focused Node example tests | 8 passed |
| Python example CLI | Passed |
| Node example CLI | Passed |
| Parsed CLI result equality | Exact equality; one excerpt, `partial`, unknown coverage |

The focused cases cover cross-tenant refusal before source lookup, immutable
input snapshots, fresh authorization and revocation before return, missing
revision/digests, changed source bytes, unsupported capabilities and byte spans
that split `é`. A matching stale index cannot override the resolver's current
authorization. These deterministic tests do not establish live model quality.

Commands used:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest packages/python/tests/test_existing_index_example.py -q
node --test --test-concurrency=1 packages/typescript/tests/existing-index-example.test.mjs
uv run --project packages/python --frozen --no-sync python examples/existing_index.py
node examples/existing_index.mjs
```

Private execution logs and parsed outputs are in `artifacts/V5/V5-05/`. No model,
provider, database, background service or hosted CI was used by these checks.
The existing built Node package was used. Synchronous source resolvers cannot
be preempted; callers must bound their work. The example checks its five-second
deadline before releasing a result. Context counting is explicitly estimated.

Read the [example guide](../../../examples/existing_index.md) for capability and
source-authority requirements. Learning exercise: change only the resolved
source's tag from `public` to `private` and explain why the required filter still
blocks release. The exercise remains unassessed.
