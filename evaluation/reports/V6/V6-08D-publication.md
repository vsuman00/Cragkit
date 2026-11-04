# V6-08D registry publication

4 November 2026. V6-08 is complete for the authorized RC1 publication. All three
packages are public on both npm and PyPI; all nine canonical downloads match
the reviewed bytes. Fresh installed consumers, source builds and native source
checks passed. Maintenance/C3 and formal public-evidence exit remain separate.
The [machine receipt](V6-08D-publication.json) records actual product identities
and registry observations; [local acceptance](V6-08R-acceptance.md) remains a
separate earlier checkpoint.

## npm owner bootstrap

The verified owner `vaibhavsuman00`, with write-2FA, published the three exact
reviewed tarballs through normal `npm publish`, explicitly selecting `next`,
public access, no lifecycle scripts and no provenance. No source rebuild or
stage command was used. Core passed exact canonical registry verification before
the adapters. Both adapter downloads also passed; registry `next` points to
`1.0.0-rc.1` for all three. No upload was retried.

The core CLI returned zero and registry PUT returned HTTP202, while the first
public reads returned404. Root stopped before adapters, reconciled authenticated
write permission and public metadata, then verified the actual download before
continuing. npm documents [publish-time scanning](https://github.blog/changelog/2026-07-28-npm-publish-time-malware-scanning-and-dual-use-metadata/)
with delayed availability. Adapter controllers waited with bounded read-only
metadata observations before strict final byte verification; waiting did not
repeat uploads. HTTP acceptance alone was not treated as installability.

Public metadata also contains a `0.0.0-stage` placeholder and `latest` aliases
RC1 for each package, despite the commands specifying `next`. The cause of the
placeholder was not independently established. No tag or version was deleted or
changed. Sol peers escalated the scope question; Astra reviewed the contracts:
RC1 plus matching `next` is required, while absence of `latest` is not. Exact
core bytes satisfy the adapter dependency. Preserve/disclose this metadata and
continue approved missing products; optional tag/unpublish changes retain their
separate scope boundary. No stable `1.0.0` release is claimed.

Consumers should pin `1.0.0-rc.1` or explicitly choose `next`. Distribution is not
exclusive to `next`: default installation can select RC1 through `latest`. The
existing registry verifier checks the reviewed files and `next`; its success
does not prove absence of extra versions or aliases. These observations are
kept separately rather than inventing a new acceptance rule after upload.

## Account and hosted-job preparation

All three npm trusted publisher configurations were read back through the
authenticated CLI: GitHub repository `vsuman00/Cragkit`, workflow
`publish-candidate.yml`, no environment, direct-publish permission. The provider
also returns its documented [default staging permission](https://github.blog/changelog/2026-09-03-multiple-trusted-publishing-configurations-for-npm/).
The initial private core helper expected only direct permission; its extra-field
assertion was corrected after inspecting the actual response and provider docs.
The configuration was preserved and not recreated. The later configurations
verified the exact repository/workflow and closed permission set.

Saved fields are not successful npm OIDC evidence. Current npm trust requires a
first successful publish within two days; this owner bootstrap preceded trust
and cannot validate it. Expired configuration must be recreated near a future
legitimate release. Do not claim permanent automation readiness or publish a
new version just to validate a trust configuration.

The earlier owner confirmation was corrected by screenshots: only `cragkit`
is pending under the intended GitHub identity. PyPI rejected simultaneous
identical pending identities for the other project names. The original setup
instructions were incorrect. The new [first-use contract](../../../contracts/PUBLICATION_BOOTSTRAP_V6.md)
uses selected-project phases and conversion before registering the next name.
No PyPI token or credential was requested. Core OIDC first use subsequently
passed; the owner confirmed the next LangChain pending configuration.

The hosted workflow remains default-disabled between phases. Each phase binds
the reviewed transport to the exact executing SHA. Observed job compute totals
USD0.402 before allowance/storage; the two remaining phases cap additional
compute at USD0.30. These estimates fit the approved USD2 ceiling; the invoice
and included allowance are unverified. No new paid validation is included. Repository visibility and
archive decisions remain deferred. Historical preparation receipts remain fixed.


## First hosted attempt and supported correction

Run41793016849/job126450534987, source103ecb0, failed with HTTP403 at the first
private draft metadata GET. All registry upload steps were skipped. The run
was already terminal when inspected; no cancellation or rerun was sent. The
release-enable variable was removed. The36-second Linux job estimates one
rounded minute/USD0.006 before allowance/storage; actual billing is unverified.
This failure is separate from the PyPI pending-identity registration constraint.

The [first-use amendment](../../../contracts/PUBLICATION_BOOTSTRAP_V6.md) isolates
five-minute write-token/no-OIDC transport fetching from twenty-minute read-token/
OIDC uploading. It also adds explicit selected-project and pending-identity
admission, exact at-most-two-file phase plans and partial/full postflight.
Warehouse can create a project during minting before file upload: inspect actual
pending/normal state after every partial attempt rather than assuming no project
was created. The failed run is not acceptance evidence for the revised path.

## Core PyPI publication and installed source checks

Run 41798494028 reached the private draft successfully but refused its changed
tag after a target-only PATCH. Its 17-second fetch job performed no uploads.
The repair supplies the exact tag and target together, rereads all metadata
and passes the existing validator without weakening its checks.

[Run 41799900669](https://github.com/vsuman00/Cragkit/actions/runs/41799900669),
workflow source `14ee35e8`, then passed both jobs: 19 seconds fetch and 105 seconds
publish. Only the two core Python files were uploaded; adapter actions were
skipped and npm uploaded zero files. Selected-phase postflight passed. Canonical
downloads independently match the fixed core wheel and sdist. Product source
remains `a3ff7e8`; executing workflow source and packaged source are distinct.

Fresh consumers outside the checkout installed the actual registry core wheel
and all three npm tarballs. All 113 installed npm member files match their
archives. Installed-origin and default-import isolation checks passed; shared
evidence fixtures agree across runtimes. The installed Node LangChain suite
passed 108 tests and MCP passed 42. Python adapter installs await their publication.

The first database-smoke admission failed before PostgreSQL startup because
the fixture helper imports optional `httpx`. An isolated import confirmed the
missing module. Adding reviewed helper dependencies offline from hashed frozen
locks fixed the harness; no product or guard changed. The unchanged recovery
helper then passed ten backup/authority checks and five source-access cases per
runtime in 2.535 seconds. Allowed UTF-8 bytes/digests/spans matched; revoked,
foreign-tenant, tombstoned and held-old-scope access was denied. Cleanup was
verified and provider HTTP calls were zero. This is synthetic disposable
PostgreSQL evidence, not production recovery or model-quality acceptance.

The core run's receipt step succeeded without uploading its hidden-directory
files. Actual logs confirm `include-hidden-files: false` and no files found.
The next workflow enables hidden traversal only for the three explicit JSON
receipt paths, fails on an empty selection and retains them for one day.
The regression suite passed 98 tests with one expected duplicate-ZIP warning;
actionlint 1.7.12 passed both workflows. The next legitimate adapter phase will
verify hosted retention. The separate local canonical-download receipt is
retained; hosted receipt payloads and independent attestation verification are
not claimed for the core run.


## LangChain authorization refusal and receipt verification

[Run 41803938051](https://github.com/vsuman00/Cragkit/actions/runs/41803938051),
source `cf98dc0`, passed the 19-second fetch job and publisher admission,
transport, product, registry and missing-only checks. PyPI rejected the
LangChain upload with HTTP 400: "Non-user identities cannot create new projects."
The publisher job ended after 45 seconds. MCP and npm uploads and postflight
were skipped. The release-enable marker was removed; no retry was dispatched.

Both reviewed LangChain archives carry the correct `Name: cragkit-langchain`
and `Version: 1.0.0rc1`; MCP metadata was checked separately as well. The error
requires inspecting the actual pending publisher and project state, rather than
changing reviewed package bytes. PyPI's [troubleshooting guide](https://docs.pypi.org/trusted-publishers/troubleshooting/#upload-errors)
describes this project-name mismatch. A previously configured normal publisher
can also authenticate without authorizing a different absent project. Current
[Warehouse minting](https://github.com/pypi/warehouse/blob/main/warehouse/oidc/views.py) checks pending identity before normal identity, so the error
alone does not prove which owner setting is wrong. Root requested the current
nonsecret project, repository, workflow and environment fields. No project,
publisher or tag was deleted, and no token was requested.

A fresh independent registry check still verifies five fixed files and records
four absent adapter files. Absent distribution files do not prove an empty
project was not created during minting. Resolve actual account state before
registering another pending identity or dispatching another phase.

Receipt retention is now verified on the real hosted path: artifact
`13308612984` is a 1,496-byte ZIP, SHA-256
`d541c123db0f965b7111a662abede24e9b389581390e6024971a2d58a19b8fb0`.
Its only members are the preflight registry JSON and missing-only plan JSON.
Downloaded contents confirm five verified/four absent files and exactly the
LangChain pair selected, with zero npm uploads authorized. No postflight receipt
exists because that step was skipped. The receipt fix is accepted independently
of the failed registry authorization.

Observed compute estimates now total USD0.414 before included allowance,
rounding and small one-day storage. Two further capped phases would bring
compute to at most USD0.714, below the user's USD2 limit. This is an estimate,
not an invoice or authorization for speculative retries. Full V6 remains open.


## Core source-distribution installation

The canonical published core source archive was built offline with its pinned
build backend. The resulting wheel is byte-identical to the published wheel
(SHA-256 `8ed2d5be9c965f9b8c70088f5e3625ac589c4efae00ec6f45441786f99799ccc`);
all 57 member files also match. The rebuilt wheel was installed into a separate
fresh environment outside the checkout with frozen, hash-checked dependencies.
Default imports passed the network/process and optional-dependency guards.

Installed evidence checks agree with the canonical registry-wheel consumer:
23 source cases, 8 context cases, 127 token counts, 17 packing cases,
35 assessment cases and 6 pipeline cases. Build, install and checks took
1.68 seconds on the recorded local macOS ARM64/Python 3.14.6 environment.
This verifies both published core distribution formats; it does not expand
the supported platform evidence. No provider call, database startup, registry
upload or hosted job ran. The rebuilt file was not published.


## Corrected LangChain publication and installed acceptance

The owner reported a spelling correction and explicitly requested one retry.
The same fixed LangChain products passed in
[run 41807132666](https://github.com/vsuman00/Cragkit/actions/runs/41807132666),
workflow source `4ccede9`: fetch 21 seconds, publish 107 seconds. Only LangChain's
missing pair was uploaded. Independent canonical downloads match wheel SHA-256
`84f0df209a07874f4150fbcd12e103e0ca1c4174a047143ed9ec1c38cac02002`
and source SHA-256
`d43c80e37485bcf414b6c60f0ceb4fd85aa4e6c477436fb8b076b8d4f2d98eb6`.
Selected-phase verification passed; complete publication remains false because
the two MCP files are absent. The release-enable marker was removed afterward.

The 5,576-byte hosted receipt archive, artifact `13310765885`, has SHA-256
`7d2c892c81a49f9d5e59a775dbb5a4ae835a7639ca9f05d8fa817b19f4ea1e8f`.
It contains preflight, the two-file missing-only plan and four bounded read-only
postflight observations. The fourth observation verifies seven files; earlier
observations retain the valid five-file state while registry visibility catches
up. No upload was retried within the run. An initial local inspector assumed a
single observation; reading the actual members corrected that assumption to
the workflow's declared one-to-ten bound.

The published LangChain source archive rebuilds offline to the exact published
wheel. Installing the canonical wheel into the clean registry consumer preserved
all prior dependency versions. Installed origins and all six immutable member
files match; installer-managed `RECORD` is excluded from byte comparison.
Copied LangChain and core planner-security suites passed 120 tests in an
isolated interpreter. The full build/install/check sequence took 3.98 seconds,
with frozen hash-checked cached dependencies and zero provider calls.
The first helper attempt used a relative archive path after changing cwd and
stopped before building; resolving paths fixed only the private harness.

MCP is the only unpublished product. The owner has been asked to configure its
exact publisher before the final selected phase. Estimated observed compute
now totals USD0.432; one further capped phase projects at most USD0.582 before
allowance, rounding and small one-day storage. No additional paid validation
was started. Earlier failed runs and qualified security/quality/platform
limitations remain part of the evidence.


## Final MCP publication and V6-08 acceptance

[Run 41809111947](https://github.com/vsuman00/Cragkit/actions/runs/41809111947),
workflow source `c4959fa`, passed fetch in 38 seconds and publish in 135 seconds.
Only MCP's missing wheel and source archive were uploaded. Strict independent
verification without `--allow-missing` confirms all nine files and all three
npm `next` tags. MCP wheel SHA-256 is
`8e90f98762d3a030e20a6f23b5a3f6e2e5759a672161d77ef3d2a34197a625f7`;
source SHA-256 is
`339f041a57a5fa941a6b02b3e96dd0ecdc3e4e1156c2f1cb99c7e01dc26b2a6e`.
The release-enable marker was removed after terminal success.

MCP's hosted receipt artifact `13310504691` is 6,548 bytes with SHA-256
`57a575014111d8543745eea2a14ed882c6e176d8a21a94749655b46aecc36971`.
Its five bounded read-only postflight observations end at nine verified files;
preflight and the selected two-file plan are retained too. No upload was retried.
Observed Actions compute estimates total USD0.456 before allowance, rounding and
small one-day artifact storage; no more publication compute is planned.

The canonical MCP source archive rebuilds to its exact published wheel. Clean
installation preserved all prior dependency versions, matched all six immutable
member files (installer `RECORD` excluded), and verified installed origins.
All 54 MCP tests passed, including official SDK stdio subprocess checks. The
first copied test selection omitted its `test_stdio_process` support module;
copying that existing fixture and running all three test files corrected only
the private harness. Both installed Python adapters then passed 174 tests
together in 4.43 seconds, in the same clean environment. Prior Node adapter
and core tests retain their exact-artifact evidence.

The independent audit identified a required missing-evidence versus operational-
failure case beyond the existing source/recovery checks. One new disposable
PostgreSQL fixture exercised three checks per installed runtime: filtered
positive source retrieval, nonexistent required document returning
`insufficient`/`complete`, and the same retrieval after pool close raising typed
`ProviderUnavailable`. All six passed; listener cleanup was verified and
provider calls were zero. An operational failure was never relabeled as absence.

This closes publication and registry-consumer acceptance, including the six
registry permissions/bootstrap paths. npm trusted-publisher fields were saved
and verified, but skipped npm OIDC uploads still do not prove future automation;
the two-day first-use expiry limitation remains. All three PyPI projects have
actual OIDC publication evidence. There is no stable `1.0.0` release, public
GitHub conversion, archive move or broader production-target claim. Formal V6
exit still requires public disclosure of limitations and benchmark evidence;
those materials remain private under the user's deferred file/public decision.


## Supplementary npm placeholder inspection

After final C3 acceptance, a read-only audit checked the public `0.0.0-stage`
version of each npm package. Each archive contains exactly a README and a
`stub: true` package manifest. There are no executable members, scripts or
dependencies. All three archives matched registry SHA-512 integrity and SHA-1
metadata; their expanded text and downloaded metadata produced zero Gitleaks
findings. The [audit record](V6-08D-placeholder-audit.json) preserves sizes,
member digests and scope.

This establishes the inspected placeholder contents, not their creation cause.
Registry README wording does not establish which actor or client created them.
No install, script, provider call, registry write, deletion or tag mutation ran.
These placeholders are not operational Cragkit releases and do not replace the
nine approved RC1 files. Consumers should still pin the declared RC1 or choose
`next`. Formal V6 exit remains pending the owner's public-evidence decision.
