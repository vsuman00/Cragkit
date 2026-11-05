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

Task `REGISTRY-CONSUMER-CHECK` is `COMPLETE` for installed-consumer verification
and preparation of the missing registry descriptions. Updating the live
descriptions remains `PENDING_PUBLICATION` for a separately authorized version.

Two Sol peers owned Python and Node evidence and their three package READMEs;
the Python peer assembled the shared outcome. Peers resolved the serial process
slot and published wrapper contract directly. The coordinator owns the Python
`readme` metadata, package checker, development/publication guides, final
integration and this handoff. README ownership transferred before integration.

Fresh public installs of all six exact RC1 packages passed on Python 3.14.6 and
Node 26.5.0. `pip check`, `npm ls --all`, installed-origin and artifact-integrity
checks passed. Consumer checks covered valid and invalid input, trusted-scope
boundaries, UTF-8 spans/digests, and synthetic adapter calls. Six package README
examples passed against the published packages. A shared request/scope/defaults
and blank-query failure check matched across runtimes. An optional Python
dependency's loopback IPv6 capability probe was blocked and recorded separately;
no outbound provider call occurred. This is not full backend or model acceptance.

The live audit found six nonempty short summaries, three empty PyPI long
descriptions and three missing npm READMEs. Six package READMEs now supply setup,
real API examples, configuration, identity boundaries, limitations and license.
Python manifests declare `readme`; the checker preserves and verifies the README
in wheels, source distributions and npm tarballs. All six original missing
descriptions failed the new guard as expected. A clean export of reviewed source
plus this change passed all 33 serial package checks, nine built artifacts and
six description checks; 44 documentation links passed. Prose hygiene passed.

Existing user edits were preserved byte-for-byte. Registry pages, versions,
visibility and publication remain unchanged. Google indexing was not established
by public search results; registry availability is separate. Evidence and fresh
consumer environments remain private outside the source checkout. No services,
models, provider calls or paid CI were started; no task-owned process remains.
User practice is unassessed. The next smallest action is review and authorization
of a new release if the prepared descriptions should appear on the live pages;
the separate public-history/disclosure decision remains pending.

Task `RELEASE-DESCRIPTIONS` is `RUNNING`, authorized by the user's instruction
to publish the prepared descriptions. The target versions are Python `1.0.0rc2`
and npm `1.0.0-rc.2` for the three existing package names. Runtime changes are
limited to version identifiers; uncommitted native edits remain excluded.

The Python Sol peer owns private wheel/source-distribution audits and consumer
acceptance and assembles the pair's evidence. The Node Sol peer owns private npm
audits, consumer acceptance and a proposed bounded upload-only publisher. Peers
coordinate contracts and the serial process slot directly. The coordinator owns
all tracked versions, manifests, locks, documentation, workflow integration,
publication and the final handoff. Shared contract: RC1 behavior with RC2 version
metadata and package READMEs. Security hold remains active until exact products
and the publishing path pass review. No visibility change, stable release,
production deployment, model call or hosted build is included.
