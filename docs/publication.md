# Publish the reviewed RC1 products

Publication remains on security hold. The later
[security closure](../evaluation/reports/V6/V6-04R-closure.md) resolves the retained
findings and passes local replacement-artifact checks. The retained release
packet still predates the corrected code: replacement candidate CI and packet
review must precede explicit hold removal. Do not use the manual upload examples
below to bypass the hold. Account setup and publication authorization remain separate.

For example, a wheel already tested in CI can be copied unchanged for upload.
An npm tarball with `private: true` needs a separately reviewed local projection
before publication. A version string alone does not establish that relationship.

This guide implements the local preparation boundary in
[PPR-r1](../contracts/PUBLICATION_PREPARATION_V6.md). The repository remains
private and no package has been published. The manual
[publishing workflow](../.github/workflows/publish-candidate.yml) now has local
checks but has not been enabled or run. The separate
[candidate workflow](../.github/workflows/candidate-validation.yml) validates
candidates and has no registry-upload role. Local preparation, account setup,
publication authorization, an upload and post-publication smoke are separate
states. Stable `1.0.0` requires its own later decision; this packet is RC1 only.

## Review the local preparation

Use the retained ZIP and original run/job/artifact metadata. They bind source
`0c7c568d5cb71638eebab2dea97c5973b0f8cc08`, run `41625938303`, job
`125883197705`, artifact `13226006299` and ZIP SHA-256
`37b5fbcadc65be97556d885810a598e791b4321ba2ef9d3868877e2a67e4b17b`.
The one approved paid CI run is consumed; neither these commands nor its result
authorize a rerun. Preserve the original ZIP, metadata and rebuilt wheels after
the hosted artifact expires.

The following are the local preparation/verification commands. Consult the
[disclosure record](../evaluation/reports/V6/V6-08-disclosure.md) and tracker for
actual execution status; a command shown here is not a passing result.

```sh
python3 tools/prepare_release_products.py prepare \
  --archive artifacts/V6/hosted-candidate-0c7c568.zip \
  --run artifacts/V6/ci-run.json \
  --jobs artifacts/V6/ci-jobs.json \
  --artifact artifacts/V6/ci-artifact.json \
  --output artifacts/V6/publication-rc1
python3 tools/prepare_release_products.py verify \
  --archive artifacts/V6/hosted-candidate-0c7c568.zip \
  --run artifacts/V6/ci-run.json \
  --jobs artifacts/V6/ci-jobs.json \
  --artifact artifacts/V6/ci-artifact.json \
  --prepared artifacts/V6/publication-rc1
```

Preparation validates a staging directory, exclusively claims a fresh output
directory and writes the manifest last as its completion marker. A race-created
destination is refused and preserved. An interrupted directory without a valid
manifest is incomplete and verification rejects it. After failure, inspect the fixed
error and use a fresh task-owned path; do not delete unrelated output or treat a
partial directory as accepted. Verification independently derives expected bytes
from the original candidate and rejects extra, missing or changed files. It does
not accept a supplied replacement hash as proof of ancestry.

Review `artifacts/V6/publication-rc1/publication-manifest.json`, all nine products,
their inventories, original/prepared hashes, licenses and disclosure before any
upload. The Python wheels/sdists are byte-identical to CI. The npm projection
changes only top-level `private` from true to false; all other JSON values,
member bytes and executable modes remain unchanged. Tracked manifests/locks keep
their original guard. The manifest records `prepared_local`,
`publication_authorized: false`, `published: false`, and pending registry
ownership/authentication/smoke. It is a local receipt, not registry provenance.

## Establish the six registry permissions securely

For each registry, verify who owns or may create `cragkit`, `cragkit-langchain`
and `cragkit-mcp`. Earlier public metadata responses do not reserve a name or
prove account permission. The user supplied `vaibhavsuman00` for both registries
and reported 2FA enabled; authenticated sessions and all six publishing permissions
remain unverified. See the [account setup record](../evaluation/reports/V6/V6-08C-accounts.md).
A scope/name change would require a new reviewed
candidate, metadata and dependency pins; do not silently rename these products.

Use the registries' signed-in account pages and enable account protection. Prefer
workflow-bound trusted publishing over long-lived credentials. Configure exact
repository/workflow identities only after secure setup is authorized. This
first-maintainer workflow uses owner-only manual admission and minimal job
permissions. No independent deployment reviewer or protected environment is
configured; keep that trust boundary explicit. Never paste a registry token or one-time password into chat, Git,
reports or a command recorded in shell history.

PyPI supports a pending trusted publisher for a new project; it creates the
project only on actual first publication and does not reserve the name. Existing
projects need an authorized owner to add the publisher. See
[PyPI first-use setup](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
and [existing-project setup](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).
No pending publisher or project was created during preparation.

npm trusted publishing supports private source repositories but cannot generate
provenance from them. It requires npm >=11.5.1 and Node >=22.14.0 on supported
hosted runners. Its setup uses package settings, so first-publication ownership
for these uncreated packages still needs a verified bootstrap path. Do not assume
that a configured workflow claims a name. See
[npm trusted publishing](https://docs.npmjs.com/trusted-publishers/).
If the authorized bootstrap requires interactive publication, use the owner's
secure CLI login/2FA flow. If a token is necessary, use the narrowest supported
short-lived credential in an approved secret store, then revoke it when no longer
needed. No token has been requested or configured here.

For first publication, [npm requires an existing package before trust setup](https://docs.npmjs.com/cli/v11/commands/npm-trust/).
The guarded publishing job cannot bootstrap an absent npm package through a trust
that has not yet been configured. After corrected candidate CI, packet review,
hold removal and specific upload approval, the owner can bootstrap the exact
three approved npm RC1 tarballs through interactive login/2FA. Only afterward can
those packages receive trusted publishers. The missing-only planner can then
verify existing npm bytes and the `next` tags and upload only missing PyPI files.
A skipped npm upload does not validate npm OIDC. New npm trust configurations
expire without a first successful publish within two days; time their setup for
an approved publishable version. These are later authorized steps, not completed
account setup. Do not set `registry_setup_confirmed` from usernames alone.

The [owner setup checklist](../evaluation/reports/V6/V6-08C-accounts.md#owner-setup)
gives exact publisher fields. GitHub owner `vsuman00` differs from registry user
`vaibhavsuman00`. PyPI pending publishers need no bootstrap upload. npm staged
publishing of a new name creates a public placeholder, so it is not a harmless
way to prepare these absent names or bypass the held nine-product RC1 packet.

## Workflow controls and private transport

The [workflow policy](../evaluation/release/V6-publication.json) fixes the
1,486,204-byte transport SHA-256
`6b817c8c627e1cdd0fe882b25617b2be17fe6ff7dc75e45b3d8a26d69c0db0d0`.
The locally prepared ZIP contains exactly the original CI ZIP, its three metadata
records and the reviewed publication manifest. Unpack regenerates the same nine
products and rechecks their identities. The original one-day hosted artifact is
not required once this retained transport is available.

The proposed later storage is one private draft release named by tag
`rc1-transport-20261103`, targeting the reviewed workflow commit. Creating it and
uploading its asset are still unauthorized. The publishing job receives numeric
release/asset IDs, verifies draft/commit/name/size/digest/membership, and downloads
the asset through a read-only repository token. No tag or public GitHub release
is created by the publishing job. Draft creation, asset access and hosted behavior
remain to be verified after authorization.

Only owner `vsuman00` can admit the job, from `main`, on its first attempt, with
the executing SHA explicitly acknowledged and all three publication/cost/setup
flags true. Repository variable `CRAGKIT_RELEASE_ENABLED` must equal
`reviewed-rc1`; it is currently absent. There are no push/PR triggers. The job
has read-only repository access and upload-job OIDC permission, without a stored
PyPI/npm token. Core precedes adapters. Preflight validates present files and
plans only missing files; postflight fetches all nine and checks npm `next`.
It never blindly skips conflicting files or retries a partial publication.

This is a single-maintainer flow that trusts the owner account and repository
writers; matching a SHA does not prove independent review. GitHub's environment
and reviewer features have plan restrictions for private repositories. The API
did not return this account's plan, and no environment exists. We have not
assumed a Free plan, upgraded the account or made the repository public. See
[GitHub environment availability](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments).

Before setup, use your own [PyPI account](https://pypi.org/account/register/) and
[npm account](https://www.npmjs.com/signup), verify email and enable MFA. The
PyPI pending-publisher fields are owner `vsuman00`, repository `Cragkit`, workflow
`publish-candidate.yml`, and no environment for this flow. npm uses the same
repository/workflow and must allow direct publication, after its initial owner
bootstrap is resolved. Confirm each registry's supported constraints instead of
assuming that it enforces a branch merely because GitHub emits a branch subject.
Account creation/configuration and interactive bootstrap need the owner's secure
participation; public usernames are sufficient for coordination. Never share a
password, key or token in chat.

The proposed job is one `ubuntu-24.04` run, with a 20-minute timeout and one-day
nonsecret receipt storage. At the reviewed Linux two-core rate of USD 0.006 per
minute, compute would be up to USD 0.12 before included usage, rounding and
separate storage. Allowance and actual charges are unknown. The earlier approved
macOS validation run does not authorize this job. See
[GitHub runner pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing).
No dispatch, registry/account change or private asset upload has run.

## Review the proposed first upload

This is a plan, not an executed upload or permission request. The next concrete
authorization must name the public package/version set, exact manifest/products,
public disclosure, owner/authentication path and any bounded workflow cost. It
must separately cover any account configuration or workflow execution needed.
No tag, GitHub release, repository visibility change or new paid CI is implied.

After secure setup and explicit approval, publish only the reviewed files, core
before its optional adapters. PyPI receives the six wheel/sdist files at
`1.0.0rc1`; npm receives the three projected tarballs at `1.0.0-rc.1`, explicitly
under the prerelease tag `next`. Never use a working-tree rebuild, a wildcard
that includes retained rebuilt wheels, or a publish-from-directory command in
place of the reviewed products. The prepared workflow verifies the original
candidate and prepared hashes before upload, pins actions/tools and retains
nonsecret receipts. Reusing old prepared bytes avoids an unreviewed rebuild.

For illustration only, the npm upload of one reviewed tarball would use the
following form after authorization and secure authentication:

```sh
npm publish ./artifacts/V6/publication-rc1/products/npm/cragkit-1.0.0-rc.1.tgz --registry=https://registry.npmjs.org/ --access=public --tag=next --ignore-scripts --provenance=false
```

This command has not run. `next` avoids npm's default `latest` tag; the explicit
tarball selects the reviewed bytes. npm will not reuse a published name/version.
These behaviors are documented in
[npm publish](https://docs.npmjs.com/cli/v11/commands/npm-publish/).
Setting `--provenance=false` records the private-source limitation; it does not
create an attestation or justify a provenance badge. Upload clients and the PyPI
upload invocation are fixed in the prepared workflow. Its hosted upload,
OIDC/account configuration and draft-asset read still lack execution evidence.

## Handle a partial upload

Record each successful registry/package/version/file, registry URL, returned
digest/integrity metadata and receipt before continuing. If a later upload fails,
stop and compare registry state with the reviewed manifest. Preserve successful
versions. Upload only genuinely missing reviewed files after confirming their
identity and authority; do not blindly rerun the whole sequence or accept
"already exists" as a passing byte check.

If published bytes, version, dependencies or installed behavior differ, mark
E61 failed and stop promotion. Investigate the smallest failing package. Prepare
and verify a new corrective version rather than substituting local bytes for
what users already received. Any yank, deprecation, unpublish, tag change or
corrective publication needs its specific authorized scope. An RC pass does not
authorize stable publication.

## Fetch and smoke the registry products

After authorized publication, download all nine products from their canonical
registries into fresh directories outside the checkout. Compare the downloaded
bytes with the reviewed manifest's SHA-256 and size; also verify available
registry digest/integrity metadata. Check package/version, contents and notices.
If the registry does not return the exact reviewed bytes, stop for an explicit
investigation; do not silently relax the identity policy.

Install exact versions into fresh Python and Node environments without checkout
imports or workspace links. Install core first and test both optional adapters;
record interpreter/runtime versions, import origins, resolved dependencies and
download URLs. Use a small public synthetic corpus and a disposable authorized
PostgreSQL target with the selected optional profile. Run a source-linked query,
verify exact UTF-8 spans/digests and required filters, demonstrate missing evidence
versus operational failure, then verify foreign/revoked denial and cleanup.
No live model/provider call is needed for this smoke. Use the existing
[installed evidence checks](development.md) and
[pilot procedure](../examples/pilot_rag/README.md) with the explicit downloaded
products; record the actual commands/results instead of assuming a local smoke
proves registry behavior.

Only successful clean download, identity, install and source-access checks close
V6-08. See [the release notes](releases/V6.md) for the tested matrix and limitations.
Learning exercise: after one adapter upload fails, list the registry facts you
would inspect before retrying it.
