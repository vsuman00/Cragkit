# Publish the reviewed RC1 products

For example, a wheel already tested in CI can be copied unchanged for upload.
An npm tarball with `private: true` needs a separately reviewed local projection
before publication. A version string alone does not establish that relationship.

This guide implements the local preparation boundary in
[PPR-r1](../contracts/PUBLICATION_PREPARATION_V6.md). The repository remains
private and no package has been published. No publishing workflow exists yet.
The [existing workflow](../.github/workflows/candidate-validation.yml) validates
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
prove account permission. Current account identities, credentials and all six
permissions remain unverified. A scope/name change would require a new reviewed
candidate, metadata and dependency pins; do not silently rename these products.

Use the registries' signed-in account pages and enable account protection. Prefer
workflow-bound trusted publishing over long-lived credentials. Configure exact
repository/workflow/environment identities only after a reviewed publishing
workflow and authorization exist. Use a protected deployment environment and
minimal job permissions; keep dependency installation separate from the upload
credential. Never paste a registry token or one-time password into chat, Git,
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
place of the reviewed products. A future workflow must verify the original
candidate and prepared hashes before upload, pin its actions/tools and retain
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
upload invocation remain to be frozen in the reviewed workflow; no untested
workflow is presented as ready.

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
