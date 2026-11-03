# V6-08: proposed RC1 disclosure

State: nine locally prepared products passed root acceptance in
[the preparation report](V6-08-preparation.md). Registry publication,
account changes, tags, GitHub releases, repository visibility changes and further
paid CI are not authorized. No registry publication or post-registry smoke has
occurred. PPR-r1 governs this packet; V6-08 remains incomplete.

For example, a source distribution includes readable Python implementation and
tests even if the GitHub repository stays private. A private repository does not
make a public package's contents private.

## Proposed public files

The exact target registries are public PyPI and public npm. The proposed set is:

| Registry | Package/version | Files under `artifacts/V6/publication-rc1/products/` |
| --- | --- | --- |
| PyPI | `cragkit` / `1.0.0rc1` | `pypi/cragkit-1.0.0rc1-py3-none-any.whl`, `pypi/cragkit-1.0.0rc1.tar.gz` |
| PyPI | `cragkit-langchain` / `1.0.0rc1` | `pypi/cragkit_langchain-1.0.0rc1-py3-none-any.whl`, `pypi/cragkit_langchain-1.0.0rc1.tar.gz` |
| PyPI | `cragkit-mcp` / `1.0.0rc1` | `pypi/cragkit_mcp-1.0.0rc1-py3-none-any.whl`, `pypi/cragkit_mcp-1.0.0rc1.tar.gz` |
| npm | `cragkit` / `1.0.0-rc.1` | `npm/cragkit-1.0.0-rc.1.tgz` |
| npm | `cragkit-langchain` / `1.0.0-rc.1` | `npm/cragkit-langchain-1.0.0-rc.1.tgz` |
| npm | `cragkit-mcp` / `1.0.0-rc.1` | `npm/cragkit-mcp-1.0.0-rc.1.tgz` |

Review all nine files together with `publication-manifest.json` in that local
directory. The original ZIP, its metadata and three rebuilt wheels are retained
evidence, not additional upload products. The release notes and guide are
`docs/releases/V6.md` and `docs/publication.md`; they are reviewable documentation,
not files automatically included in the registry products.

## Source and allowed change

The source is `0c7c568d5cb71638eebab2dea97c5973b0f8cc08`, package tree
`60a251c2bf94402cb562d0398403c218875454f3`. The single approved private CI run,
job and artifact are `41625938303` / `125883197705` / `13226006299`. Retained
ZIP SHA-256:
`37b5fbcadc65be97556d885810a598e791b4321ba2ef9d3868877e2a67e4b17b`.
[CI evidence](V6-06-ci.md) records its original twelve products and limitations.

All six Python upload files must remain byte-identical to CI. Each npm archive
may change only `package/package.json`'s top-level `private` JSON value from true
to false. All other values and member bytes/modes remain equal; original and
prepared hashes must both be recorded. Tracked manifests and locks remain
unchanged. Prepared npm archives are projections with reviewed ancestry, not the
unchanged CI archive bytes or a new hosted CI result.

## Content visible to package recipients

Read-only inspection of the retained original ZIP, its twelve nested archives
and the nine prepared products found the following distribution classes. The
selected-credential scan and final execution are recorded separately in
[the root acceptance](V6-08-verification.json).

| Product | Disclosed content |
| --- | --- |
| Python wheels | Native Python source, typing markers, build/package metadata, dependency declarations, MIT license and distribution notice. Core: 57 members; each optional wheel: 7. |
| Python sdists | Source and tests, `uv.lock`, `pyproject.toml`, `.gitignore`, `PKG-INFO`, LICENSE and NOTICE. Core: 117 members; LangChain: 9; MCP: 10. |
| npm tarballs | Compiled JavaScript, TypeScript declarations, full `package.json`, LICENSE and NOTICE. Core: 103 members; each optional package: 5. |

Metadata exposes package names/versions, descriptions, author `Vaibhav Suman`,
copyright year 2026, the repository/homepage/issue URLs under
`https://github.com/vsuman00/Cragkit`, package subdirectories and exact dependency
versions. npm also exposes scripts and development dependency metadata, including
optional packages' relative `file:../typescript` development link. That link is
retained metadata, not a bundled checkout or a consumer installation dependency.
No author email is declared. The archives do not bundle the root README or this
release guide. Private repository links may be inaccessible to package users;
they do not authorize a visibility change.

The own-code MIT license and NOTICE remain byte-identical to the reviewed assets.
Dependency names and versions do not transfer dependency licenses. Database
servers, model weights/runtimes and tokenizer rank assets are not bundled; the
consumer owns optional setup and applicable terms. Provider credentials and
disclosure decisions remain caller-owned.

## Exclusions and repository boundary

The proposed products exclude `papers/`, PDFs, root evaluation corpora/review
labels, provider recordings, admissions, raw benchmark outputs, private `.env`
and database/operator configuration, keys/certificates, credentials, source dumps,
backups, local environments/caches and Git history. Package tests inside sdists
are intentionally disclosed; that is distinct from shipping private evaluation
tapes or configuration. Exact inventories and bounded content guards must be
rechecked on the final prepared bytes.

Six research PDFs are tracked under `papers/` in the repository. Their
redistribution rights have not been established by this review, and the
project's MIT license does not establish those rights. They are absent from the
reviewed package classes. Making the repository/history public would require a
separate rights, secret and history review. Public package publication needs no
such visibility change and does not itself publish the entire repository.

An archive-path audit cannot detect every possible secret embedded in ordinary
source text. Earlier selected-key scans are scoped historical evidence. Root
inspected all nine products/320 members and found zero selected-provider-value,
base64 or declared provider/GitHub/private-key-pattern matches without printing
private values. This result applies only to that scan scope. No general
absence-of-secrets or removal-of-watermark claim follows from this review.

## Pending account and publication decisions

No PyPI/npm account identity or permission to create/update any of the six
registry projects has been verified. Registry name availability is not ownership.
Prefer exact workflow/environment-bound trusted publishers after authorization;
never request tokens in chat. A PyPI pending publisher does not reserve a name.
npm first-publication bootstrap still needs an authenticated, verified path.
The [publication guide](../../../docs/publication.md) links current primary
registry instructions, separates planned uploads from executed work and explains
partial publication recovery and clean registry smoke.

A later PyPI publish attestation can disclose the uploader workflow/run/repository
and commit identity. It describes that upload, not proof that this job built the
original CI products. npm provenance remains unavailable from private source.
No attestation was generated during local preparation.

The source repository remains private. npm trusted publishing can use private
source, but npm provenance is unavailable there; no provenance badge is claimed.
The manual publishing workflow has local validation but is disabled and unrun. The next authorization must identify
these nine exact reviewed products, their public code/metadata disclosure, the
six registry permissions, authentication/bootstrap path and any bounded workflow
cost. It must not imply stable `1.0.0`, another paid CI run or repository exposure.

## Assembly and checks

V6-08B owns only the release notes, publication guide and this report. The peer
tool interface is `prepare`/`verify` with original ZIP/run/jobs/artifact inputs,
one fresh output directory and no identity override. The product writer owns
the preparation tool/tests; root owns execution, shared contracts, tracker and
Git. Peer assembly read all 407 tool and 287 test lines without mutating the other
lane's files. The CLI, expected product paths, manifest schema, independently
reconstructed verification, private-token projection and manifest-last output
behavior match PPR-r1 by inspection. No actionable interface mismatch remained.
Reports alone are not passes.

The actual local manifest inspected during assembly has SHA-256
`7ced6f15ee096752d8e974d793d1bd99a8f41d77181fb061d2871d890aeb5dc5`.
It records all nine products, the exact source/CI identities, three retained
rebuilt-wheel inventories and false authorization/publication flags. Read-only
member comparison found the six Python files byte-identical to the original;
the only changed npm member in each archive is `package/package.json`, with
`private: false`. Tool/test inspection confirms replacement of only that JSON
token while preserving the other manifest bytes. Root's independent tool verify,
installed-consumer checks and selected-secret scan are separate final evidence.

Executed in this lane: governing document/report reads; retained-ZIP and prepared
product member/metadata inspection with Python standard-library archive readers;
read-only primary registry-document lookup; 22 relative link-target checks with
no missing target; and the self-contained prose inspection/cleaning pass with no
suspicious Unicode or deterministic edits. Low density tiers required no prose
rewrite. One initial multi-file prose-inspector invocation was rejected because
the tool accepts one path; individual invocations then succeeded. No test,
install, service, provider call, registry mutation or workflow dispatch ran in
this lane. Resource use was limited to bounded
file reads and documentation editing; no task-owned background process exists.

Failure example: a tarball with a changed runtime byte must fail even if its
supplied manifest contains an updated matching hash. The original CI candidate
is the comparison authority. Optional exercise: explain why publishing only the
sdist still discloses source while leaving tracked research PDFs private.
