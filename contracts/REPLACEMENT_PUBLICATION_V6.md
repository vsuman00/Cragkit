# Corrected release candidate publication

Revision: PPR-r2. This amendment selects the corrected candidate for V6-08R.
It supersedes PPR-r1's input identities for current tooling, while retaining the
original PPR-r1 summary, receipts, archives and transport as historical evidence.
PPR-r1 product format and its exact transformation rules remain unchanged.

For example, the old CI ZIP remains a valid historical artifact, but it must
not be selected for the current publication after product security fixes.

## Fixed current candidate

- Source: `a3ff7e81332d849724407356d220c991e8a8411d`.
- Package tree: `63dafe3b3906778e456b1cd2aefb7f99cd896e43`.
- Run/job/artifact: `41777862696` / `126402305700` / `13297269766`.
- ZIP SHA-256: `422cb0367bdd11b61416b287378abffbd78c60442f1ceb1ce7523280d58858be`.
- ZIP size: 1,286,413 bytes.
- Local retained inputs: `artifacts/V6/replacement-candidate-a3ff7e8/`.
- Python version: `1.0.0rc1`; npm version: `1.0.0-rc.1`, tag `next`.
- Names in both registries: `cragkit`, `cragkit-langchain`, `cragkit-mcp`.

Revalidate CIB-r1 before preparing the nine products. Copy six Python archives
byte for byte. Only npm's top-level `private` boolean may change; all other
JSON values, file bytes, paths and executable modes remain fixed. Preserve the
three rebuilt wheels and original CI ZIP as evidence. Do not rebuild runtime
code or mutate tracked package manifests/locks to make publication possible.

The corrected summary is `evaluation/reports/V6/V6-08R-verification.json`.
Root derives it from the prepared manifest after independent verification,
then freezes its SHA-256 and the manifest SHA-256 before dependent tool edits.
Prepare and verify a fresh deterministic private transport, bind its digest to
the policy, and reject old, wrong-source, missing, extra or changed inputs.
The frozen manifest digest is `7ab4ba1aeebfce8b83871f7bda8bf09cfdc39e6e405f28a0ca88fe55ecbdc663`;
the frozen summary digest is `32b3251e3ef7d9536830f15ed1c196a45f2c1a91c31093dce2d99aed99471312`.
Current transport uses fixed member `candidate.zip`, the three CI metadata JSON
files and the manifest; it is 1,496,502 bytes with digest
`609f3f84924417d4c0e9baefeb2097e10d35cc5e1e43cc283add970a60545d48`.

## Ownership and verification

Root owns candidate selection/preparation, this contract, frozen summary,
policy/workflow, public publication procedure, tracker, test slot and Git.
Sol binding peer owns `tools/release_transport.py`,
`tools/check_registry_products.py` and its focused test file. Wait for root's
frozen manifest/summary digests before dependent edits. Sol guidance peer owns
`README.md`, `docs/releases/V6.md`, and private assembly of both lane reports.
Both do substantive work, communicate concrete dependencies directly and keep
nonoverlapping writes. Outcome/protected ownership changes escalate to root;
unresolved material decisions go to Astra. No peer tests, services, installs,
account changes, credentials, paid calls or uploads.

Root serializes preparation/CIB/licensing/transport/registry/workflow regressions,
actual prepare/verify/pack/unpack, content/disclosure review and appropriate
installed consumers. Passing old receipts do not prove the corrected packet.
Preserve all user-edited source, storage guidance, tracker draft and audit drafts.
README keeps the user's established section/banner/table/callout/guide structure.

## Resume and publication boundary

The user's latest active goal explicitly resumes remaining product work including
package deployment. It supersedes the earlier stop before publication. File
archive selection and making GitHub public are deferred to the user; the current
repository remains private. No file move, deletion, history rewrite or public
repository conversion is part of this release task.

Keep the publication hold until corrected packet review, README refresh and
required authenticated registry setup pass. Local preparation still writes
`publication_authorized: false` and `published: false`; those describe preparation,
not an upload. Existing owner/manual exact-SHA admission, bounded missing-only
planning, secure bootstrap and post-registry verification remain required.
Never report saved or skipped npm trust configuration as a successful OIDC test.
No password, token, recovery code or credential-bearing URL belongs in chat/Git.

No new paid validation run is included. Publishing execution must be bounded
within the user's USD 2 computation ceiling, accounting for the already recorded
replacement validation estimate; the planned 20-minute Linux publish job is
estimated at USD 0.12 before included usage. Record actual duration and billing
uncertainty; do not infer registry/account authorization from a green CI job.

V6-08 completes only after actual registry downloads, exact-byte reconciliation,
clean installs and source-linked smoke. V6-09/C3/exit follow their stated
dependencies. No smaller local-only milestone substitutes for those outcomes.
