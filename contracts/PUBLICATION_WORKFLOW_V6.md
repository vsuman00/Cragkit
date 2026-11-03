# Publication workflow and registry verification

Revision: PWK-r1. V6-08C1/C2 implement the remaining local workflow machinery;
registry permissions, human authorization and hosted execution stay separate.
The [PPR-r1 products](PUBLICATION_PREPARATION_V6.md) and exact reviewed manifest
remain immutable inputs. Do not rebuild package code or change tracked guards.

For example, a successful upload response is insufficient: the registry may
already contain a different file. Fetch metadata and bytes and compare both with
the reviewed product identities before accepting the published version.

## Frozen identities

Use PPR-r1's fixed source/CI identities and manifest SHA-256
`7ced6f15ee096752d8e974d793d1bd99a8f41d77181fb061d2871d890aeb5dc5`.
The public proposed RC1 set remains six PyPI files/three projects and three npm
tarballs/three projects, with npm prerelease tag `next`. No stable release or
repository visibility change is included. Root owns the eventual workflow,
reviewed transport digest/policy, shared docs, tracker, tests and Git integration.

## V6-08C1: durable private transport

Sol transport peer owns `tools/release_transport.py` and
`tools/tests/test_release_transport.py`. Implement standard-library `pack` and
`unpack` CLI operations. The sole input payload is the retained CI ZIP,
`ci-run.json`, `ci-jobs.json`, `ci-artifact.json` and the original prepared
`publication-manifest.json`. Fix those five archive names; no user path or
additional file may be bundled. Validate the source with PPR-r1/CIB-r1 and the
fixed manifest digest before writing. Produce a deterministic transport ZIP,
owner-only and without credentials or private configuration. Output a small
nonsecret receipt containing its SHA-256/size and five member hashes.
The pack completion receipt is `transport-receipt.json`; the unpacked prepared
products retain their original PPR `publication-manifest.json`. Root's shared
PPR helper accepts `completion_marker=...` with its original default preserved.

Unpack requires an independently supplied expected transport SHA-256, bounded
raw/expanded sizes, exactly five safe regular members and byte-exact manifest
identity. Do not extract arbitrary ZIP paths. Revalidate the full candidate and
regenerated manifest before exposing a fresh output directory; reuse the
exclusive destination/manifest-last discipline where applicable. Refuse links,
duplicates, extra/missing/drifted members and existing output, preserve foreign
files on failure, and use fixed safe diagnostics without payload exceptions.
Neither operation uses the network, credentials, subprocesses or upload APIs.

The intended later transport is one private GitHub draft-release asset, fetched
by the publishing job with read-only repository access. This document authorizes
only local preparation. Creating that draft/tag/asset requires the later specific
authorization; do not create any now. The workflow must verify the local reviewed
transport digest and never assume the original one-day Actions artifact survives.

## V6-08C2: read-only registry verification

Sol registry peer owns `tools/check_registry_products.py` and
`tools/tests/test_check_registry_products.py`, and assembles the pair. The tool
reads the committed V6-08 product summary/manifest identity, never a caller's
arbitrary replacement product list. It performs bounded unauthenticated HTTPS
GETs to canonical public PyPI/npm metadata and file hosts, then verifies all
nine expected product bytes/sizes and available registry digest/integrity fields.
Reject wrong package/version, duplicate/unreviewed files, malformed JSON,
metadata/hash drift, unsafe URLs, redirects, credentials, non-HTTPS and
unexpected hosts before following a URL. Do not use environment auth/proxies or
read credential files. Keep one request active, no retries, at most 18 HTTP
requests, 5 seconds per request and a shared 60-second deadline. Bound metadata
and product bytes before reading. Use standard verified TLS and fixed redacted
diagnostics; never retain arbitrary server response/error bodies.

Expose `--allow-missing` for preflight only: a genuine 404/missing expected file
is `absent`, operational errors remain errors, and any present product must match
exactly. Missing files cannot become a complete publication result.
If metadata claims a file exists but its download returns 404, that inconsistency
is an error, not permission to retry a publication of the same filename.
Default complete mode returns nonzero until all nine files are verified. Save bounded
public receipts and verified bytes only into a fresh output directory; do not
install or execute them. Account identity/ownership is never inferred from a 404.
Record npm `next` tag state if available through a bounded canonical read;
do not claim tag acceptance without observing it. Peers agree the exact CLI/report
interface directly and tell root before workflow wiring.

Tests use fake HTTP transports and small synthetic files. They cover complete
success, partial/absent state, drifted bytes/metadata/integrity, unsafe URLs,
redirects, failed TLS/timeouts, bounded calls/bytes/deadline, duplicate/nonfinite
JSON, wrong identities and preservation of existing output. No test may access
real registries or account credentials. Root alone owns live read-only preflight.

## Root workflow and integration

Root implements a manual-only, default-disabled publication workflow after both
interfaces freeze. Use pinned tools/actions, minimal permissions, a reviewed
source-SHA check, exact manifest/transport checks, owner-actor admission
and explicit publication/cost acknowledgments. No push/PR trigger or automatic
upload follows from committing the workflow. Prefer registry-bound OIDC; npm's
initial authenticated project bootstrap remains a separate required owner step.
Preflight all present products before any upload; publish only reviewed missing
files, core before adapters, and verify all registry products afterward. Never
treat a partial upload or "already exists" response as success. Clean downloaded
consumer/database smoke remains a separate V6-08D acceptance requirement.

Platform amendment after root/Astra review: use a single-maintainer manual
authorization model, without an independent deployment reviewer or mandatory
GitHub environment. The account plan was not returned by the available API;
private environments/reviewer features have plan restrictions, and no upgrade or
visibility change is authorized. Admit only owner `vsuman00` on reviewed `main`,
attempt one, with all three explicit acknowledgments and repository variable
`CRAGKIT_RELEASE_ENABLED=reviewed-rc1`; that variable is currently absent.
Trust in the owner account and repository writers remains explicit. A matching
SHA acknowledges an identity, not proof of independent review. Registry-supported
workflow/ref restrictions must be verified during setup; do not infer them from
an emitted OIDC subject. This change does not authorize enabling or running the
workflow. A protected environment can be considered separately if available.

Root runs focused tests serially, prepares/rechecks the actual local transport,
validates workflow structure/negative guards, and performs at most one bounded
public read-only preflight. No new paid job, account change, package upload,
GitHub release/tag/asset or visibility change is authorized. Root records local
versus hosted/registry evidence separately. Peers use direct dependency messages,
nonoverlapping paths and no test/install/service execution; guidance or ownership
changes require agreement/stopped writes. Protected/outcome changes return to
root, then Astra if unresolved. Apply the self-contained prose workflow.
