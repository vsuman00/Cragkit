# Build, release and deploy Cragkit

For example, building a wheel checks a local package, publishing makes exact bytes available from a registry, and deploying runs a consuming application. Treat these as separate outcomes.

Cragkit is an MIT-licensed Python and TypeScript library with separate optional LangChain and MCP packages. The [current roadmap](roadmap.md) records scope; [RC1 notes](releases/V6.md) record release state and limits. The repository is public by its owner's decision. Current releases are Python
`1.0.0rc3` and npm `1.0.0-rc.2`; a new or stable release needs separately authorized scope.

## Prepare exact products

Start from reviewed source and preserve unrelated work. Record commit, package versions, manifests, frozen locks and the supported runtime/backend matrix. Run [public package checks](development.md#public-package-validation) and the affected private maintainer regressions. Native backend, live-provider, hosted CI and production checks remain distinct.

Build Python wheels/source distributions and npm tarballs, rebuild wheels from source distributions, and inspect exact members, versions and hashes. Include the reviewed [MIT license](../LICENSE) and [notice](../NOTICE); dependencies and models retain their own licenses. Keep secrets, private corpus, workbench history and model assets out of distributions. Install the exact products in fresh application environments and verify import origin and supported behavior. A source pass cannot establish archive contents.

Preserve Python publication attestations. Local builds are compatible with
publisher attestations; these identify the uploader and file digest, rather than
certifying a build process. Require attestations explicitly in the publishing
action and verify every published distribution's signature, digest and publisher
identity. Do not mark a release complete if this provenance is missing. See the
[RC3 correction](releases/RC3.md) and [PyPI attestation model](https://docs.pypi.org/attestations/security-model/).

## Review gates and hosted validation

Release identity includes exact source and product hashes. Changed bytes require new acceptance; an earlier candidate receipt cannot validate a replacement. Keep any explicit security hold fail-closed until a reviewed correction and its required checks pass. Detailed historical RC1 receipts remain in the private maintainer archive.

The [candidate workflow](../.github/workflows/candidate-validation.yml) is manual. Inspect its current implementation and required inputs before use. A workflow definition is not a run, and local validation does not authorize paid hosted CI. Bound cost and resources before any authorized dispatch. Repository visibility, branch protection and a public evidence release are separate user decisions.

## Publish and verify

Follow [publication](publication.md) only for an authorized version and exact reviewed products. Verify registry ownership and current authentication/trust configuration without exposing tokens. The frozen release publishers are retained privately. The public checkout has no upload workflow; any future publisher requires a new review and separately authorized scope. Do not change tracked npm `private` settings as an incidental source-build step.

After upload, download exact registry files into fresh environments, verify hashes/version policy and check installed consumers. Record partial uploads and retry only missing accepted products. Published bytes are immutable: a broken release needs a corrective version, rather than different local bytes under the same version.

## Deploy a consuming application

The application supplies hosting, identity, credentials and final answers. Select required optional profiles, reuse bounded clients/pools, bind trusted scope outside tool input and apply migrations explicitly with operator credentials. Remote databases need verified certificate and hostname checks and restricted runtime roles. See [operations](v5-operations.md), [production security](production-security.md) and [migration/recovery](migrations-and-recovery.md).

Start with synthetic data and verify permission denial, cancellation, exact citations, overload and operational failure before real data. Define current-authority recovery and support ownership. Installing this library requires no dashboard, built-in key, hosted Cragkit service or paid model.
