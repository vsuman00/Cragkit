# V6-08D registry publication

4 November 2026. Publication is in progress. All three npm RC1 products are
public and their canonical downloads match the reviewed SHA-256/size. The Python
core wheel and sdist are also published and byte-verified. Five of nine fixed
files are verified; Python adapters and V6-09/C3/version exit remain pending.
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
