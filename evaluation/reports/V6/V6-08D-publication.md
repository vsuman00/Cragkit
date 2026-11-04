# V6-08D registry publication

4 November 2026. Publication is in progress. All three npm RC1 products are
public and their canonical downloads match the reviewed SHA-256/size. PyPI
upload, clean registry-installed smoke and V6-09/C3/version exit remain pending.
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
instructions were incorrect. Keep core pending; the new [first-use contract](../../../contracts/PUBLICATION_BOOTSTRAP_V6.md)
uses selected-project phases and conversion before registering the next name.
No PyPI token or credential was requested. Actual OIDC first use remains pending.

The hosted workflow remains default-disabled until the reviewed private transport
and exact executing SHA are bound. One Linux job, 20-minute timeout and one-day
nonsecret receipts fit the approved USD2 ceiling with the recorded earlier
USD0.186 replacement-CI estimate; proposed job compute is at most USD0.12 before
allowance/storage. No new paid validation is included. Repository visibility and
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
was created. Proposed changes require local checks and an actual revised run;
the failed run is not acceptance evidence for them.
