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

The next smallest action is the separately scoped formal V6 evidence/disclosure
review or an authorized maintenance change. The current publishing correction is
finished; stable release and production acceptance are separate decisions.
