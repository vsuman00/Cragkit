# V5 exit and checkpoint C3

State: COMPLETE for the planned local/native milestone and its declared profiles. Package manifests remain provisional `0.0.0`; this is not a published beta or production acceptance.

For example, a Qdrant request with a missing facet returns `partial` through direct, LangChain and MCP entry points. A partially written successor never becomes an authorized source just because some points exist.

| Requirement group | Acceptance evidence |
| --- | --- |
| V5-01/02: consistency, scoped dense/sparse candidates and profiles | [QD-r1](../../../contracts/QDRANT_V5.md), [consistency decision](../../../docs/decisions/0003-qdrant-consistency.md), accepted child reports in the [tracker](../../../tasks/todo.md) |
| V5-03: authoritative source release | [Native disclosure acceptance](V5-03D.md) |
| V5-04: publication, repair, current authorization and purge | [All 43 exact native fault IDs](V5-04H.md), [content-free evidence ledger](V5-04H-matrix.json) |
| V5-05/06: existing indexes and optional MCP | [C2 acceptance](V5-C2.md) |
| V5-07: native backend/library/tool/MCP agreement | [Representative matrix](V5-07.md) |
| V5-08: isolated optional artifacts and operations | [Final installation evidence](V5-08.md), [operations guide](../../../docs/v5-operations.md) |

The final 34-stage core/framework command passed serially:

```sh
python3 tools/check_v4.py --artifacts-dir artifacts/V5/V5-08/full-core-frameworks
```

It passed 3,146 Python/tool tests, 1,582 Node tests, Python strict typing over 50 core files, Node strict typing/build, schema exports and every shared parity group. LangChain passed 72 Python and 69 Node tests plus strict types and isolated installed-artifact checks. The four Python warnings are intentional serializer warnings from malformed-model negative cases. No tests were skipped in the final core run. The approved development corpus and all 16 sealed inputs passed. The detailed log is ignored `artifacts/V5/V5-08-full-validation.log`.

The V5 complement separately passed six clean installation profiles per runtime, rebuilt MCP wheel contents, guarded installed imports and 41 Python/36 Node installed MCP tests. Refreshed MCP strict types passed in both runtimes; seven artifact rejection tests passed. Core wheel/sdist/npm and optional LangChain/MCP artifacts were built locally, with sizes and SHA-256 digests retained in their acceptance records. Core runtime dependencies remain Pydantic/Zod; optional drivers remain optional for consumers. Default development setup now includes the same already pinned HTTP/PostgreSQL clients required to typecheck and test optional modules.

The V5-07 native matrix passed 84 retrieval calls and 16 forged-input refusals across PostgreSQL lexical/Qdrant dense and the three entry points, with exact parsed cross-runtime observations and verified cleanup. Final acceptance rechecked the 43-ID ledger against all 42 retained native result digests. These publication/source implementations were unchanged after that acceptance; the matrix was inspected rather than all historical scenarios being rerun on one new server.

The documented deadline recovery example was executed again for V5-08: seven checks per runtime, matching witness, old-owner closure, successor refusal while a write remained unresolved, actual late HTTP completion, continued refusal and genuine managed recovery before publication. Cleanup was verified. Failure lesson: deadline expiry or a dead owner cannot prove an admitted external write stopped; durable uncertainty must outlive it.

All local test/install suites ran serially. Final headroom was 33 GiB disk and 59 percent system memory free. No live inference, model download, hosted write, cluster deployment, registry publication or persistent task-owned service was used. Built artifacts reflect the inspected working tree, including preserved pre-existing reader-facing edits; those unrelated files remain outside the scoped commit. Learning practice is unassessed: explain why PostgreSQL lexical retrieval can operate with zero provider allowance while Qdrant dense retrieval cannot.

V5's scope is closed. V6 owns release evaluation, distribution and maintenance gates. Current evidence does not establish live-model quality, arbitrary external writers, clustered Qdrant, automatic supervisor takeover, PostgreSQL dense/hybrid transport combinations beyond their earlier acceptance, hosted CI or production readiness. The user's Daybreak clarification removes the separate cybersecurity deliverable, without changing required library authorization and integrity behavior.
