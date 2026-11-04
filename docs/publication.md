# Publish the reviewed RC1 products

The user has resumed completion of V6, including RC1 package deployment. That
instruction supersedes the earlier publication pause; repeat upload-intent
approval is not required. Corrected-packet acceptance and owner npm login/write-2FA checks have passed.
The artifact hold is cleared for the exact reviewed owner bootstrap. The hosted
workflow requires verified setup for its explicitly selected phase. The
[security closure](../evaluation/reports/V6/V6-04R-closure.md) records closed
reviewed leads; qualified CSO coverage remains partial. Corrected
[CI acceptance](../evaluation/reports/V6/V6-08C-CI2.md) and
[prepared products](../evaluation/reports/V6/V6-08R-verification.json) replace
the earlier held packet. Keep operational admission checks in force.

For example, a wheel already tested in CI can be copied unchanged for upload.
An npm tarball with `private: true` needs a separately reviewed local projection
before publication. A version string alone does not establish that relationship.

This guide implements the local preparation boundary in
[PPR-r2](../contracts/REPLACEMENT_PUBLICATION_V6.md), retaining
[PPR-r1](../contracts/PUBLICATION_PREPARATION_V6.md) product rules. The repository remains
private. The [registry progress receipt](../evaluation/reports/V6/V6-08D-publication.md)
records all six registry products and nine files published, byte-verified and
checked through installed consumers. The manual
[publishing workflow](../.github/workflows/publish-candidate.yml) now has local
checks. Its first run failed at private draft metadata access before any upload;
[PWB-r1](../contracts/PUBLICATION_BOOTSTRAP_V6.md) defines the corrected two-job,
selected-project procedure, whose core publication phase passed. The separate
[candidate workflow](../.github/workflows/candidate-validation.yml) validates
candidates and has no registry-upload role. Local preparation, account setup,
publication authorization, an upload and post-publication smoke are separate
states. Stable `1.0.0` requires its own later decision; this packet is RC1 only.

## Review the local preparation

Use the corrected retained ZIP and its run/job/artifact metadata. They bind source
`a3ff7e81332d849724407356d220c991e8a8411d`, run `41777862696`, job
`126402305700`, artifact `13297269766` and ZIP SHA-256
`422cb0367bdd11b61416b287378abffbd78c60442f1ceb1ce7523280d58858be`.
Preserve original and corrected ZIPs, metadata, receipts and rebuilt wheels;
historical inputs cannot substitute for this corrected candidate. No additional
paid validation run is included in this procedure.

The following are the local preparation/verification commands. Consult the
[disclosure record](../evaluation/reports/V6/V6-08-disclosure.md) and tracker for
historical disclosure scope. Corrected nine-product prepare/verify passed; the
[immutable current summary](../evaluation/reports/V6/V6-08R-verification.json)
binds manifest `7ab4ba1aeebfce8b83871f7bda8bf09cfdc39e6e405f28a0ca88fe55ecbdc663`
and has SHA-256 `32b3251e3ef7d9536830f15ed1c196a45f2c1a91c31093dce2d99aed99471312`.
Use a fresh output directory to repeat preparation; the accepted output exists.

```sh
python3 tools/prepare_release_products.py prepare \
  --archive artifacts/V6/replacement-candidate-a3ff7e8/candidate.zip \
  --run artifacts/V6/replacement-candidate-a3ff7e8/run.json \
  --jobs artifacts/V6/replacement-candidate-a3ff7e8/jobs.json \
  --artifact artifacts/V6/replacement-candidate-a3ff7e8/artifact.json \
  --output artifacts/V6/publication-replacement-a3ff7e8
python3 tools/prepare_release_products.py verify \
  --archive artifacts/V6/replacement-candidate-a3ff7e8/candidate.zip \
  --run artifacts/V6/replacement-candidate-a3ff7e8/run.json \
  --jobs artifacts/V6/replacement-candidate-a3ff7e8/jobs.json \
  --artifact artifacts/V6/replacement-candidate-a3ff7e8/artifact.json \
  --prepared artifacts/V6/publication-replacement-a3ff7e8
```

Preparation validates a staging directory, exclusively claims a fresh output
directory and writes the manifest last as its completion marker. A race-created
destination is refused and preserved. An interrupted directory without a valid
manifest is incomplete and verification rejects it. After failure, inspect the fixed
error and use a fresh task-owned path; do not delete unrelated output or treat a
partial directory as accepted. Verification independently derives expected bytes
from the original candidate and rejects extra, missing or changed files. It does
not accept a supplied replacement hash as proof of ancestry.

Review `artifacts/V6/publication-replacement-a3ff7e8/publication-manifest.json`, all nine products,
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
and reported 2FA enabled. npm now authenticated as that owner with write-2FA
confirmed. The screenshot initially verified only the `cragkit` pending PyPI publisher;
the earlier instruction to create three identical pending configurations was
wrong. All three PyPI first-use phases have since passed. Register each remaining name only after the prior entry
converts. See the
[account setup record](../evaluation/reports/V6/V6-08C-accounts.md) and current
[bootstrap contract](../contracts/PUBLICATION_BOOTSTRAP_V6.md).
A scope/name change would require a new reviewed
candidate, metadata and dependency pins; do not silently rename these products.

Use the registries' signed-in account pages and enable account protection. Prefer
workflow-bound trusted publishing over long-lived credentials. Configure exact
repository/workflow identities through the owner's secure authenticated setup. This
first-maintainer workflow uses owner-only manual admission and minimal job
permissions. No independent deployment reviewer or protected environment is
configured; keep that trust boundary explicit. Never paste a registry token or one-time password into chat, Git,
reports or a command recorded in shell history.

PyPI supports a pending trusted publisher for a new project; it creates the
project during first-use token minting and does not reserve the name. Existing
projects need an authorized owner to add the publisher. See
[PyPI first-use setup](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
and [existing-project setup](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).
Local product preparation itself creates no publisher or registry project.

npm trusted publishing supports private source repositories but cannot generate
provenance from them. It requires npm >=11.5.1 and Node >=22.14.0 on supported
hosted runners. Its setup uses package settings, so first-publication ownership
needs a verified bootstrap path; the three npm packages now have observed owner
bootstrap and exact-byte download evidence. Do not assume
that a configured workflow claims a name. See
[npm trusted publishing](https://docs.npmjs.com/trusted-publishers/).
If the authorized bootstrap requires interactive publication, use the owner's
secure CLI login/2FA flow. If a token is necessary, use the narrowest supported
short-lived credential in an approved secret store, then revoke it when no longer
needed. No token has been requested or configured here.

For first publication, [npm requires an existing package before trust setup](https://docs.npmjs.com/cli/v11/commands/npm-trust/).
The guarded publishing job cannot bootstrap an absent npm package through a trust
that has not yet been configured. After corrected candidate CI, packet review,
artifact hold clearance and verified owner npm login/write-2FA, the owner can bootstrap the exact
three approved npm RC1 tarballs through interactive login/2FA. This initial owner
step does not require nonexistent npm trust configuration. Only afterward can
those packages receive trusted publishers; keep workflow setup confirmation false
until required npm setup and the selected PyPI binding are checked. The missing-only planner can then
verify existing npm bytes and the `next` tags and upload only missing PyPI files.
A skipped npm upload does not validate npm OIDC. New npm trust configurations
expire without a first successful publish within two days; time their setup for
an approved publishable version. These remain deployment steps, not completed
account setup. Do not set `registry_setup_confirmed` from usernames alone.

The [owner setup checklist](../evaluation/reports/V6/V6-08C-accounts.md#owner-setup)
gives exact publisher fields. GitHub owner `vsuman00` differs from registry user
`vaibhavsuman00`. PyPI pending publishers need no bootstrap upload. npm staged
publishing of a new name creates a public placeholder, so it is not a harmless
way to prepare these absent names or bypass the held nine-product RC1 packet.

## Workflow controls and private transport

The [workflow policy](../evaluation/release/V6-publication.json) fixes the
1,496,502-byte transport SHA-256
`609f3f84924417d4c0e9baefeb2097e10d35cc5e1e43cc283add970a60545d48`.
The locally prepared ZIP at
`artifacts/V6/replacement-transport-a3ff7e8/release-transport.zip` contains exactly
the corrected CI `candidate.zip`, its three metadata records and the reviewed publication manifest. Unpack regenerates the same nine
products and rechecks their identities. The original one-day hosted artifact is
not required once this retained transport is available.

The private draft uses tag `rc1-transport-20261104-a3ff7e8`. The first hosted
attempt failed with HTTP 403 at draft metadata retrieval before uploads. Draft
visibility requires push access; a general read permission is insufficient.
The amended workflow separates repository-write access from registry identity:

1. The five-minute fetch job has `contents: write` and `id-token: none`. It runs
   admission, verifies draft/asset identity and fixed transport bytes, and uploads
   only the sealed transport as `reviewed-rc1-transport-GITHUB_RUN_ID`, retained
   one day. It neither unpacks products nor invokes registries.
2. The twenty-minute publisher has `contents: read`, `actions: read` and
   `id-token: write`. It independently runs admission, validates the fetch output's
   artifact ID against this run, repository, source, main branch, expiry, name,
   bounded size and canonical URL, then downloads at most 4 MiB plus one byte.
   The wrapper must contain exactly one regular `release-transport.zip`; fixed
   inner size/hash and existing candidate/manifest/product checks run again.

The reviewed draft must target the exact executing `GITHUB_SHA`. Rebind and
reread that private draft after workflow changes; supply both exact tag and target
in the update, because a target-only PATCH can reset a draft tag. Run the full
existing metadata validator on the fresh response; never relax the equality check.
Artifact ID comes from the fetch job output, not dispatch input. No PAT,
reusable workflow, new environment or public GitHub release is introduced.

The core phase passed, but its receipt step omitted hidden-directory files.
The corrected step includes hidden files only at the three explicit nonsecret
JSON paths and fails if none are found. Keep that allowlist; never archive the
workspace, private source, credentials or whole hidden directories.

Both jobs require owner `vsuman00`, private `vsuman00/Cragkit`, manual dispatch
from `main`, first attempt, exact executing-SHA acknowledgment, publication/cost/
setup flags, hold clearance and enable marker `reviewed-rc1`. Both selectors are
mandatory: `pypi_project` is `all` or one exact project name, and
`pypi_pending_project` is `none` or one exact project name. Conflicting pending
identity is rejected before draft access or token minting. `all` requires no
pending identity. Setup acknowledgment refers to the selected pending/normal
binding and required npm setup; it must not falsely assert all six configurations.

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

Budget at the reviewed Linux rate USD 0.006 per minute: at most three phases,
each five fetch minutes plus twenty publishing minutes, estimate USD 0.45.
Prior replacement validation and the failed 36-second publish attempt estimate
USD 0.192 combined; proposed compute total is USD 0.642 before storage,
allowances and rounding, below the USD 2 ceiling. Record actual durations and
remaining budget before each dispatch; no new paid validation is included.

## Publish one PyPI project at a time

Keep the screenshot-confirmed core pending entry: owner `vsuman00`, repository
`Cragkit`, workflow `publish-candidate.yml`, no environment. Pending GitHub
identity uniqueness excludes the project name, so simultaneous identical pending
entries for the adapters cannot be registered. Follow this sequence:

1. Admit `pypi_project=cragkit` with `pypi_pending_project=cragkit`, or `none`
   only after its normal binding is verified for a retry. Verify all nine local
   products and every present remote product. All three npm files and matching
   `next` tags must already verify. Upload only the selected missing wheel/sdist.
2. Confirm both exact core files by registry download and inspect pending-to-normal
   conversion and ownership. Minting may create the project before uploading;
   after any failure inspect actual state before choosing retry selectors.
3. Only then register `cragkit-langchain` under the same GitHub binding. Select it
   explicitly; both core Python files must verify in addition to npm. Confirm its
   pair and conversion, then repeat for `cragkit-mcp`.

Each selected phase permits at most two missing Python files and no npm upload.
Other Python projects may be absent, but any unselected conflict or operational
error blocks the phase. Missing, unknown or conflicting selectors are errors;
there is no default-to-all behavior. `all` mode is reserved for verified normal
bindings and retains nine-product missing-only checks.

Postflight validates the full report and downloaded present bytes again. It
reports `phase_complete` independently of `publication_complete`; only all nine
verified files and npm tags establish the latter. Valid absent required files
return exit 2 and permit at most ten read-only observations with fifteen-second
waits. Errors/conflicts stop immediately; no upload retry occurs in that loop.
Final clean installs and source-linked smoke still gate V6-08 completion.

After the remaining acceptance and authenticated setup gates pass, publish only the reviewed files, core
before its optional adapters. PyPI receives the six wheel/sdist files at
`1.0.0rc1`; npm receives the three projected tarballs at `1.0.0-rc.1`, explicitly
under the prerelease tag `next`. Never use a working-tree rebuild, a wildcard
that includes retained rebuilt wheels, or a publish-from-directory command in
place of the reviewed products. The prepared workflow verifies the original
candidate and prepared hashes before upload, pins actions/tools and retains
nonsecret receipts. Reusing old prepared bytes avoids an unreviewed rebuild.

For illustration only, the npm upload of one reviewed tarball would use the
following form after hold removal and secure authentication:

```sh
npm publish ./artifacts/V6/publication-replacement-a3ff7e8/products/npm/cragkit-1.0.0-rc.1.tgz --registry=https://registry.npmjs.org/ --access=public --tag=next --ignore-scripts --provenance=false
```

This command form ran for the three reviewed npm products. The explicit
tarball selects the reviewed bytes and `next` is required. The registry also
returned `latest` pointing to RC1 and a placeholder during initial bootstrap;
distribution is not next-only. Preserve that observation and pin the desired
prerelease explicitly. npm will not reuse a published name/version.
These behaviors are documented in
[npm publish](https://docs.npmjs.com/cli/v11/commands/npm-publish/).
Setting `--provenance=false` records the private-source limitation; it does not
create an attestation or justify a provenance badge. Upload clients and the PyPI
upload invocation are fixed in the prepared workflow. The first hosted attempt failed before these uploads; the amended transport and
PyPI first-use sequence still need their own execution evidence.

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
