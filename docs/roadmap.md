# Current roadmap and maintenance state

For example, changing a reranker error requires a synthetic regression and checks in both native runtimes. It does not require a new model benchmark or permission to publish a stable release.

Cragkit's current scope is maintenance of the native Python and TypeScript RC1 libraries and their optional LangChain/MCP packages. The [architecture](architecture/ARCHITECTURE.md) and public [contracts](../contracts/README.md) govern behavior. Personal implementation plans, evaluation packets, reports, tests and demonstration applications are preserved outside this source checkout in a private maintainer archive.

## Release state

Python `1.0.0rc1` and npm `1.0.0-rc.1` are published for `cragkit`, `cragkit-langchain` and `cragkit-mcp`. Recorded acceptance covers six registry packages and nine exact files. Maintenance and checkpoint C3 passed their scoped checks. Formal V6 exit still awaits the deferred public disclosure of limitations and benchmark evidence; the GitHub repository remains private. [RC1 notes](releases/V6.md) retain the scope and material limitations.

Stable `1.0.0`, a new registry upload, repository visibility changes, production deployment, live-provider runs and paid hosted CI require their own authorized scope. OCR, dependent multi-hop, answer verification and a hosted dashboard remain later research.

## Next work

Maintain a small source checkout that builds without the private workbench. Use [development](development.md) for public checks and the separate private maintainer regression runner. Keep source-build, regression, installed-artifact, native backend, live-provider, hosted CI and publication results distinct.

For each authorized behavior change, name the task, define its failure case, inspect the relevant contract and run the smallest meaningful checks. Changes to shared schemas, migrations, locks or release identities have one writer. Complete the handoff only after final integration accepts the results. Record code whose required checks have not run as `IMPLEMENTED_UNVALIDATED`.

## Session handoff

Task `PUBLIC-SEPARATION`: separate approved private workbench materials from the library source while preserving the originals and validating the current library. Documentation and package/check tooling are independent assigned lanes; the final integrator owns filesystem moves, protected user edits, combined validation and completion state.

State: `COMPLETE` for the authorized source/private-workbench separation. The
original589 approved files and198 dependent validation/workflow files were moved
outside this checkout with byte hashes verified. A full1063-file pre-change source
snapshot and private Git history bundle were also preserved. Generated remainders
from the former private directories were moved intact; no original file was deleted.

The final public package profile passed33 serial stages without private inputs:
all six package typechecks, builds, nine artifacts, source-distribution rebuilds,
fresh installed imports and locked Node integrity checks. The private overlay
passed4434 core/tool Python,113 LangChain Python,54 MCP Python,1639 core Node,
108 LangChain Node and42 MCP Node tests. Current operator guards passed19 cases;
new package-checker boundaries passed5. Six copied legacy CLI fakes were updated
to the extracted helper seam after their failure was diagnosed; assertions and
archived originals were preserved. Disposable verified-TLS PostgreSQL/pgvector
operator acceptance passed8 checks with listener cleanup. No live-provider call,
model download, new package publication, visibility change or paid CI ran.

The original frozen publisher and its validation closure remain private. Current
public CI is manual build verification with read-only permissions and no upload
step. Current operational security SQL is available under deployment/checks;
applied migrations and native library source were unchanged by this task.
Protected pre-existing native edits remain uncommitted and separately preserved.

Use one test process and small fixtures; final checks ran serially. The known-
advisory check covers133 exact versions across six frozen locks and found no
matches at its recorded time; this does not establish universal security. Original
receipts, detailed logs, source hashes and private runner instructions are retained
in the owner-only workbench. Learning explanation was provided; user practice is
unassessed. The next action is the separately authorized public-history/disclosure
decision. Formal V6 exit and production acceptance remain separate from this task.
