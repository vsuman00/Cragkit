# Publication preparation

Revision: PPR-r1. V6-08A/B prepare reviewable RC1 products and release notes.
They do not authorize an upload, a workflow run, account changes, a tag, a GitHub
release, a repository visibility change or another paid service call.

For example, a public npm tarball needs `private: false`. Its new archive hash
must be recorded even when every runtime file still matches the reviewed CI
candidate. The source checkout keeps its publication guard.

## Inputs and identity

Use the retained, locally verified candidate bundle from V6-06:

- Source: `0c7c568d5cb71638eebab2dea97c5973b0f8cc08`.
- CI run/job/artifact: `41625938303` / `125883197705` / `13226006299`.
- ZIP SHA-256: `37b5fbcadc65be97556d885810a598e791b4321ba2ef9d3868877e2a67e4b17b`.
- Python version: `1.0.0rc1`; npm version: `1.0.0-rc.1`.
- Products in each registry: `cragkit`, `cragkit-langchain`, `cragkit-mcp`.

Revalidate the original ZIP and retained run/job/artifact metadata with CIB-r1;
a copied JSON success field alone is not proof. Preserve the original bundle and
all three rebuilt wheels as evidence. The publication set contains nine files:
three direct wheels, three source distributions and three npm tarballs.

## V6-08A: local preparation tool

One Sol writer owns `tools/prepare_release_products.py` and
`tools/tests/test_prepare_release_products.py`. Implement a bounded, offline,
standard-library tool with no publication or credential-discovery capability.
Root owns execution. The tool must refuse an existing output destination,
including one created concurrently before its exclusive directory claim. Finish
all staging checks before that claim, create files without overwriting existing
paths, and write the manifest last as the completion marker. After a failure,
clean up only this invocation's temporary staging and files; remove its claimed
output directory only if empty. Never delete another writer's file.

Copy the six Python products byte for byte. Repack the three npm archives in
memory without extracting or running their contents. Only the JSON value of
`package/package.json`'s top-level `private` field may change, from true to false.
Every other JSON value and every other member name, byte and executable mode
must remain equal. Reject unsafe paths, links, duplicate members/JSON keys,
nonfinite JSON, incorrect source identities and changed manifests. Use bounded
counts/sizes and deterministic archive output. Apply the original licensing
checks through a guarded comparison view rather than weakening ALC-r1's
private-candidate requirement. Leave all tracked manifests and locks untouched.

Write `publication-manifest.json` (PPR-r1) with source and CI identity, original
and prepared archive SHA-256/size, package/registry/version, relative product
paths, member inventories/hashes and the exact allowed transformation. State
`prepared_local`, `publication_authorized: false`, `published: false` and record
that registry ownership, authentication and post-publication smoke are pending.
Provide an offline verification mode that rechecks prepared files against the
original candidate and rejects missing, extra or mutated products. It must not
trust hashes or success fields supplied only by the prepared manifest.

Tests cover deterministic success, all nine products, exact Python bytes,
manifest-only npm change, mismatched CI identity, drifted runtime/license/JSON,
unsafe/duplicate/link members, existing-output refusal and failed preparation
cleanup. Existing CIB/ALC tests remain unchanged and must continue to pass.

## V6-08B: reader guidance and assembly

A second Sol writer owns `docs/releases/V6.md`, `docs/publication.md` and
`evaluation/reports/V6/V6-08-disclosure.md`; this peer assembles the pair.
Document the exact RC scope, migration repair, supported matrix, test evidence,
quality/resource limitations and incomplete publication state. Link detailed
reports instead of duplicating their full inventories. Explain preparation,
registry account setup, first publication, partial publication recovery and the
required clean download/install/source-linked smoke. Distinguish proposed
commands from executed ones and prerelease from stable release.

Use current primary registry documentation for account/OIDC/provenance facts.
Public package publication can disclose package source, metadata and notices
while the GitHub repository stays private. npm provenance is unavailable from
private source repositories; do not claim a badge or change visibility to obtain
one. PyPI pending publishers do not reserve names. npm bootstrap ownership and
the six account permissions remain unverified. Never request a token in chat.
List the exact proposed disclosure and reviewable files before authorization.
Research PDFs and private evaluation/provider/config/backup files are excluded
from these products. Their presence in repository history means a later public
repository decision needs a separate review; package inspection is not that
review. Do not assert unverified redistribution rights.

## Coordination and acceptance

Peers message each other directly about tool/guide interfaces and findings.
Nonoverlapping ownership transfers require agreement, a stopped writer and root
notification. Root owns this contract, tracker, shared instructions, workflow,
test slot, final evidence, Git and final integration. No peer runs tests,
installs, services, provider calls or registry mutations. Escalate protected,
outcome or other-lane ownership changes before dependent edits; unresolved
material choices go through root to Astra. Apply the self-contained prose skill.

Root runs focused preparation/CIB/ALC tests, prepares and independently verifies
the actual nine products, inspects their disclosure/credential inventory and
performs affordable serial local consumer checks. Only then request the next
specific missing publication/account/cost decision. V6-08 remains incomplete
until authorized registry publication and clean post-publication smoke pass.

Failure case: a tarball with one changed runtime byte must be refused even when
its supplied manifest contains a matching replacement digest. An operator must
prepare and verify a new candidate rather than relabel the earlier CI result.
