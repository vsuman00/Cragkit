# Publication policy

For example, an npm trust entry can be saved without an OIDC publication ever succeeding. Verify actual registry files and authentication outcomes separately.

RC1 is already published as Python `1.0.0rc1` and npm `1.0.0-rc.1` for `cragkit`, `cragkit-langchain` and `cragkit-mcp`. Recorded acceptance covers six packages and nine exact files. The detailed bootstrap records, upload receipts and release packet are retained in the private maintainer archive. [RC1 notes](releases/V6.md) summarize scope and limitations. Formal public-evidence exit remains pending while GitHub is private.

## Package descriptions and registry pages

A short summary and a full project description are separate fields. For example,
`cragkit-langchain` needs a one-line explanation for search results and a README
that shows how to bind application identity before exposing its retrieval tool.

| Package | Python project description | npm README |
| --- | --- | --- |
| `cragkit` | [Python README](../packages/python/README.md) | [Node README](../packages/typescript/README.md) |
| `cragkit-langchain` | [Python README](../packages/langchain-python/README.md) | [Node README](../packages/langchain-typescript/README.md) |
| `cragkit-mcp` | [Python README](../packages/mcp-python/README.md) | [Node README](../packages/mcp-typescript/README.md) |

In each Python package's `pyproject.toml`, `[project].description` supplies the
short summary and `readme = "README.md"` supplies the full description with
Markdown content type. Inspect both the wheel's `METADATA` and the source
distribution's README. See the [Python packaging metadata guide](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/).

In each Node package's `package.json`, `description` supplies the short summary.
Its root `README.md` supplies the package page's README tab. npm includes a root
README in the package even when `files` lists only compiled output and notices;
inspect the actual tarball. See [npm's README guide](https://docs.npmjs.com/about-package-readme-files/)
and [package metadata](https://docs.npmjs.com/cli/configuring-npm/package-json/).

Keep these six guides specific to their package and runtime: purpose, supported
versions, installation, real public APIs, configuration, identity boundaries,
limitations and license. Link to the full API reference with absolute URLs so
registry readers can follow the links. The root GitHub README is a separate page;
editing it does not update registry descriptions. While GitHub is private, those
repository links require collaborator access, so essential setup stays in each
registry README itself.

Registry descriptions are part of release products. npm updates its README when
a new version is published. PyPI stores the first uploaded metadata for a release;
later uploads do not update it. Prepare and validate a separately versioned release
to correct an existing description, then obtain publication authorization under
the gates below. Do not delete or re-upload RC1. See the
[npm update rule](https://docs.npmjs.com/about-package-readme-files/) and
[PyPI metadata rule](https://dev.pypi.org/api-reference/json/).

The public package checker preserves the package READMEs in its isolated source
export and rejects missing or mismatched wheel descriptions, source READMEs and
npm READMEs. After an authorized upload, also inspect the live registry metadata
and rendered package pages; a local build does not update those pages or establish
Google indexing.

## Admit a future release

A new version, stable release, upload, account change or hosted publishing run needs its own authorized scope. Follow [releasing](releasing.md) for source/product acceptance. Bind admission to exact reviewed source, archive hashes and package/version/registry identities. Reject an active, missing or malformed security-hold decision. An old receipt never approves changed products.

The frozen RC1 publisher is retained privately; the public checkout contains no upload workflow. A future publisher requires a new review of its exact source, products, admission controls and transport. Separate repository fetching from credential-bearing publication and give each stage only the rights it needs. Never commit or paste registry tokens, private connection data or a credential-bearing URL.

## Prepare and authenticate

Retain wheel, source-distribution and npm hashes and compare archive members to their reviewed source. Python products and npm publication metadata have distinct byte identities. The recorded RC1 preparation changed only npm's top-level `private` token in separate publication tarballs while preserving runtime bytes and notices; tracked manifests remain private. Do not treat a replacement manifest as proof of ancestry.

Verify ownership for each of the six registry projects, approved account protections and actual trusted-publisher configuration. Distinguish owner bootstrap, saved trust, skipped uploads and successful OIDC use. Private-source npm provenance is unavailable for the recorded RC1; do not claim provenance from a saved trust configuration. Inspect current official registry requirements before a future authorized release.

## Upload and accept exact bytes

Use an explicit missing-only upload plan. If an upload partially succeeds, enumerate current files and compare their exact hashes before retrying; never overwrite a published version or blindly rerun the whole release. A conflict or unknown identity stops publication.

Download every selected registry file into fresh application environments. Verify version/hash policy, imports, optional adapters, source-distribution builds and the appropriate source-linked smoke/failure behavior. Preserve redacted evidence for each exact product. An upload success alone is not installed-consumer acceptance.

Publication does not deploy a consuming application, authorize a public GitHub release, change repository visibility or prove production readiness. Keep those outcomes separate in the [roadmap](roadmap.md).
