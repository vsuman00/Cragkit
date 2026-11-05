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

Task `DOCS-ONBOARDING` is `COMPLETE` for the README, API/Qdrant guides and
contributor workflows. The README preserves its centered banner, top-level section
order, status table, callouts and five collapsible guides, with application setup
and usage replacing internal milestone history.

Two Sol peers owned API/Qdrant reference and contribution/templates; the API peer
assembled their shared outcome. The coordinator integrated README and this handoff,
verified source-derived coverage across 28 Python modules and 21 TypeScript entry
points, checked templates and validated the executable examples. The catalog
separates methods, constructors, properties, schemas and protocol/type declarations.

Python and Node service-free request examples passed. The README retrieval examples
returned the same exact excerpt through a disposable TLS PostgreSQL fixture, and an
ungranted identity received no evidence. The fixture listener closed. TypeScript
examples passed strict checks against the released declarations, including exact
optional-property handling. Python guide imports/definitions passed with external
I/O blocked. Both issue forms parsed with unique fields; documentation links and
README structure passed. Qdrant/MCP construction examples were checked without
calling a live model or running a new end-to-end Qdrant/MCP deployment.

No native source, dependencies, locks, private workbench, package publication,
repository visibility or paid CI changed. Existing user edits were preserved.
Verification used one process at a time and small synthetic inputs; no task-owned
service remains. User practice is unassessed. The next action remains the separate
public-history/disclosure decision and subsequent maintenance under the current scope.
