# Current roadmap and maintenance state

For example, changing a reranker error requires a synthetic regression and checks in both native runtimes. It does not require a new model benchmark or permission to publish a stable release.

Cragkit's current scope is maintenance of the native Python and TypeScript release-candidate libraries and their optional LangChain/MCP packages. The [architecture](architecture/ARCHITECTURE.md) and public [contracts](../contracts/README.md) govern behavior. Personal implementation plans, evaluation packets, reports, tests and demonstration applications are preserved outside this source checkout in a private maintainer archive.

## Release state

Python `1.0.0rc3` and npm `1.0.0-rc.2` are published for `cragkit`,
`cragkit-langchain` and `cragkit-mcp`. All current registry artifacts passed exact
hash and fresh-consumer checks. All six Python RC3 files have cryptographically
verified publication attestations. npm `latest` and `next` both select RC2; the
owner confirmed the core README is visible on npm.

The owner explicitly chose to keep GitHub public, knowing that earlier committed
history still contains archived material. Current personal workbench files and
release receipts remain outside the source checkout. [RC3 notes](releases/RC3.md)
record the provenance correction and limitations. Formal V6 evidence/disclosure
acceptance remains distinct from package publication.

Stable `1.0.0`, another upload, repository visibility changes, production
deployment, live-provider runs and paid hosted CI require their own authorized
scope. OCR, dependent multi-hop, answer verification and a hosted dashboard
remain later research.

## Next work

Maintain a small source checkout that builds without the private workbench. Use [development](development.md) for public checks and the separate private maintainer regression runner. Keep source-build, regression, installed-artifact, native backend, live-provider, hosted CI and publication results distinct.

For each authorized behavior change, name the task, define its failure case, inspect the relevant contract and run the smallest meaningful checks. Changes to shared schemas, migrations, locks or release identities have one writer. Complete the handoff only after final integration accepts the results. Record code whose required checks have not run as `IMPLEMENTED_UNVALIDATED`.

## Session handoff

Tasks `RELEASE-DESCRIPTIONS` and `RELEASE-PROVENANCE` are `COMPLETE` for the
published package descriptions, npm default tags and corrective Python provenance.
RC2 Python files remain unchanged with their historical missing-attestation
warning. RC3 restores publication attestations without changing runtime behavior
or third-party dependencies beyond the declared package/engine version metadata.
Python engine `1.0.0-rc.3`, npm engine `1.0.0-rc.2` and schema `0.1` are explicit;
this version difference is not a behavioral-parity result.

The Python Sol peer owned artifact, consumer and signature verification and
assembled the evidence. The Node Sol peer owned the publisher and admission
checks. Peers coordinated directly and serialized test processes. Astra resolved
the draft-access and provenance-route questions. The coordinator owned tracked
versions, locks, documentation, exact upload admission and final integration.

The clean source passed 33 serial package stages. Six Python RC3 files passed
source/archive and native-payload comparisons, fresh installation and 11 synthetic
consumer groups. The publisher passed 32 failure-case checks. Official verifier
`pypi-attestations` 0.0.31 checked all six published signatures, exact file digests,
repository, workflow, publisher commit and run; altered digests, workflows and
signatures were rejected. Python descriptions match source. npm RC2's three exact
downloads, fresh installation and six synthetic consumer groups passed earlier.

Python RC3 was published in run `42054210894` from publisher commit
`0b9bfbba2dbf716517e1312ac624273f6f4b97cc`; product source was
`0930c191097397521fb269e6947edd0dea5f7afd`. The temporary upload workflow is
disabled, and its exact files and reports are preserved privately. No registry
credentials were committed. Nine pre-existing user edits remain byte-for-byte
unchanged. No model, database service or production deployment was started.

The npm API omits the README text even though the version payload and archives
contain it. The owner confirmed the core npm page displays its full guide;
automated visual checks of all package pages are not claimed. The first private
upload attempts incurred an estimated $0.03 in base compute before any allowance;
RC3 used a standard public-repository runner. User practice and production
acceptance remain unassessed.

V6-EXIT-AUDIT is COMPLETE for the requirement review and private disclosure
preparation. Sol release_python inspected the twelve engineering tasks/checkpoints
and their recorded acceptance; Sol release_node prepared the aggregate report and
assembled the pair's work. They coordinated directly, with separate private output
ownership. The coordinator inspected the assembled evidence and owns final
integration and this handoff. Astra resolved the written gate: public configurations,
metrics, applicable confidence intervals and limitations can accompany genuine
private reproduction without publishing raw evaluation files. Public independent
rerun availability must remain explicitly unclaimed.

The audit checked frozen input and selected evidence hashes, all 42 recorded C3
return codes, 85 aggregate facts and five independently recalculated Wilson
intervals. The disclosure draft passed the scoped secret scan and prose hygiene
checks. These were evidence/documentation checks; no product, backend, live-model,
CI or registry tests were rerun. The twelve engineering gates retain their stated
limits, including unavailable human usability evidence and partial qualified CSO
coverage. The original archive and nine existing edits remain unchanged.

V6-EXIT is COMPLETE for the supported release-candidate scope. The owner approved
the aggregate disclosure and selected the current release candidates for testers.
Six unauthenticated public HTTPS reads matched the reviewed documentation at
commit `0a371f285162967c8c77ec0632129dfad5ab6a56`. The
[validation report](releases/validation.md) records
all five compared configurations, aggregate results, applicable confidence
intervals and limitations. Raw test cases, labels, recordings and personal archived
files remain in the private workbench. The report does not provide an independently
runnable public dataset or turn historical quality measurements into RC3 results.

This audit used bounded file reads, one small validation process at a time and no
installs, backend services, model calls or paid CI. Observed headroom was 30 GiB
disk and 52 percent system memory free; no task-owned background process remains.
Learning practice is unassessed. An optional exercise is to explain why zero
false-sufficient observations under universal abstention do not prove useful
coverage assessment. Stable release and production acceptance remain separate
decisions. The initial V0-V6 release-candidate work is complete within its recorded
acceptance scope. The next action is tester feedback and issue-driven maintenance
under [the maintenance workflow](maintenance.md).

`DOC-PUBLIC-ONBOARDING` is COMPLETE. The owner confirmed that public access is
intentional for testers and contributors. Read-only GitHub checks confirmed public
visibility, enabled issues and forking, and disabled private vulnerability reporting.
Contribution, support and version-control guidance now reflect that state, with
direct routes to the quick start, bug form and fork/PR workflow. The correction
passed 26 relative-link/anchor checks and the required prose checks. One writer
owned the dependent documentation slice; no runtime, registry, account setting,
backend service or paid job changed. Nine pre-existing edits were preserved.
The onboarding correction did not authorize benchmark disclosure. Its later
approval and public integration are recorded above.

`V6-EXIT-PUBLISH` is COMPLETE. The registry Sol peer verified all six current
projects and nine selected file identities with six bounded official JSON reads;
all three npm `latest` and `next` tags select RC2. Retained exact-file, consumer
and Python signature evidence remains bound to the unchanged artifacts. The
review Sol peer checked report privacy, identity and claim limits, inspected the
registry receipt after its final freeze, and assembled both lanes. Peers
coordinated directly with separate private outputs; the coordinator owned public
documents, Git, anonymous readback and final acceptance.

The approved report remains SHA-256
`02c3cf47ba204ef5f86cca0906077daf1194c31d84a3e1a1f6058940a89a4c06`.
All six published documents matched their reviewed bytes through anonymous HTTPS
reads. Local checks passed 35 relative links/anchors, six prose checks and the
scoped staged secret scan. The committed package tree still matches verified
RC3 source `0930c191097397521fb269e6947edd0dea5f7afd`. Original preservation
checks passed for 787 moved files, 1,063 source-snapshot files, 3,789 generated
files, six links and 557 directories; the retained Git history bundle verified.
Nine pre-existing local edits remain unchanged and outside the published products.

The build phase is closed for the public tester release: Python `1.0.0rc3` and
npm `1.0.0-rc.2`, including the optional LangChain/MCP packages. No new package
version, paid CI, provider request, installation or backend service was needed.
Small serial checks used no persistent listener or background service. The known
quality, platform, human-trial and qualified-CSO limits remain in the public
report. Stable `1.0.0` and production deployment are not claimed. Learning
practice remains unassessed; normal maintenance starts from reproducible tester
reports and preserves the same scope, source-fidelity and disclosure boundaries.
