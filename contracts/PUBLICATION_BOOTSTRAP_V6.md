# First-use publication and isolated transport access

Revision PWB-r1. V6-08D-B0 amends the operator interfaces of PWK/PWP/PUP for
first-use publishing. PPR-r2's fixed nine products, manifests, transformation and
source identities stay unchanged. The user authorized RC1 deployment within
USD2; archive choice and public GitHub conversion remain deferred.

For example, one pending GitHub publisher can create `cragkit`. After conversion
there is no pending entry for that identity, so the owner may register the next
project using the same workflow. A selected phase must not try another project
that has not reached that setup state.

## Evidence and amendment boundary

Run41793016849/job126450534987 failed at the first private draft metadata GET
with HTTP403; every upload step was skipped. Its 36 seconds estimate one Linux
minute/USD0.006, separate from the prior USD0.186 replacement validation estimate.
[GitHub draft visibility](https://docs.github.com/en/rest/releases/releases#list-releases)
requires push access. General endpoint read permission does not establish draft
visibility. Never combine repository-write and registry OIDC in the publisher.

The user's screenshot confirms only `cragkit` pending under
`vsuman00/Cragkit`, `publish-candidate.yml`, no environment. Warehouse's
[GitHub publisher identity](https://github.com/pypi/warehouse/blob/main/warehouse/oidc/models/github.py)
excludes project name. Pending conversion removes that pending entry and can
reuse an existing normal identity. Minting prioritizes pending identity and may
create the project before distribution upload. Thus inspect pending/normal
state after any partial attempt; a failed upload does not prove conversion
never occurred. [Reusable workflows](https://docs.pypi.org/trusted-publishers/troubleshooting/#reusable-workflows-on-github)
are not a substitute for this first-use flow. No PAT, new environment, published
GitHub release, tag, repository visibility change or rebuilt product is added.

## Frozen operator interfaces

Use PWP-r2 policy and PUP-r2 plans/results. Preserve owner/manual/private/main,
reviewed executing SHA, first attempt, hold-clearance and enable-marker guards.
Both fetch and publisher independently run admission.

Required environment values:

- `PYPI_PROJECT`: exactly `all`, `cragkit`, `cragkit-langchain` or `cragkit-mcp`.
- `PYPI_PENDING_PROJECT`: exactly `none` or one of the three project names.
- No missing selector or fallback to `all`. `all` requires pending=`none`; a
  selected phase accepts pending=`none` or the selected project only. Reject a
  conflicting pending project before draft access or token minting.
- `REGISTRY_SETUP_CONFIRMED=true` attests the selected project's pending/normal
  binding and no conflicting pending identity, plus required npm setup. In `all`
  mode it attests all normal project bindings. It must not assert all six
  configurations during the first core bootstrap.
- `GITHUB_RUN_ID` and `GITHUB_REPOSITORY_ID` are required positive numeric
  service context. Publisher additionally receives `TRANSPORT_ARTIFACT_ID` from
  the fetch job's upload output, never from arbitrary dispatch input.

Public Python helper signatures:

```python
admit(environment)
prepare_uploads(*, prepared, report_path, output, pypi_project)
publish_npm(*, prepared, plan_path, environment, runner=subprocess.run)
verify_postflight(*, report_path, pypi_project)
validate_transport_artifact(metadata, environment)
unwrap_transport_artifact(*, archive, output)
```

CLI keeps existing guard/asset/plan/npm modes. Plan requires
`--pypi-project`. Add `artifact --metadata PATH`,
`unwrap-artifact --archive PATH --output PATH`, and
`postflight --report PATH --pypi-project NAME`. Artifact and unwrap modes run
admission; plan scope and npm plan scope must equal the admitted selector.
Postflight returns exit0 for phase complete, exit2 for valid absent required
files awaiting visibility, exit1 for malformed/conflicting/error state. No raw
provider payload, credentials or exception chains in diagnostics.

## Missing-only phase authority

Always check all nine local products, manifest identity and every preflight
record. Verify bytes of every present remote product. Refuse duplicate, missing
or extra records, conflicts or operational errors anywhere, including an
unselected project. Separate `all_missing` from the authorized `missing` list.
Plans record `pypi_project`, both lists, `npm_missing` and `pypi_groups`.

Selected PyPI mode requires all three npm files verified with matching `next`
tags; an adapter additionally requires both core Python files verified. Only
selected missing wheel/sdist may enter the upload directory: at most two files.
Unselected PyPI files may remain absent. `npm_missing` is always empty in a
selected phase. `publish_npm` rejects injected npm files or scope mismatches
before its runner, even if a plan is tampered with. Full mode preserves the
reviewed nine-product missing-only behavior. Preserve exclusive output claims.

Postflight validates the complete report identity and present downloaded bytes
again. A selected phase requires its pair plus the same dependencies; unknown
coverage/absent required files are not success. Report `phase_complete` separately
from `publication_complete`, which is true only when all nine and matching npm
`next` tags actually verify. Other-project absence permits a partial phase;
other-project conflict/error does not. Full mode requires all nine.

## Two jobs and two artifact layers

Fetch timeout five minutes, permissions `contents: write`, `id-token: none`.
Publisher timeout twenty minutes, permissions `contents: read`, `actions: read`,
`id-token: write`, no contents write. Keep serialization and no automatic retry.

Fetch validates current draft/asset IDs, tag, size, digest, membership and exact
`release.target_commitish == GITHUB_SHA`. The new workflow commit changes that
SHA: root must explicitly rebind and reread the private draft before dispatch,
not loosen this comparison. Download only the fixed sealed transport, verify
1,496,502 bytes and SHA256609f3f84924417d4c0e9baefeb2097e10d35cc5e1e43cc283add970a60545d48,
then upload only that file through the existing pinned upload-artifact action,
retention one day, name `reviewed-rc1-transport-GITHUB_RUN_ID`. No unpacking or
registry actions occur with the write token. Pass its artifact ID as job output.

Before publisher download, validate artifact ID, exact name, nonexpired boolean,
positive bounded size, workflow run/repository/head-repository IDs, main branch,
reviewed source SHA and canonical API URL. Outer ZIP bound is4MiB. Download via
`gh api` piped through `head -c 4194305` with pipefail, then reject an oversize
wrapper. No token in command arguments. Unwrap exactly one regular member named
`release-transport.zip`; reject extra/duplicate/directory/link/traversal/encrypted
members, wrong declared/actual size or changed bytes. Verify the inner fixed
size/SHA before exclusively claiming a fresh output directory containing only
`release-transport.zip`. Existing output directories are refused and preserved.
Then the existing transport unpack
revalidates the original candidate, metadata, manifest and products. Outer
artifact identity never substitutes for the fixed inner identity.

After upload, read-only visibility observations may wait on valid absent files.
Bound postflight to at most ten attempts with15-second waits; no upload retry.
Integrity/metadata conflicts or operational failures stop immediately. Selected
phase receipts remain partial until all nine verify.

## Sequencing, cost and acceptance

Keep the current core pending entry. Run selected `cragkit`, confirm actual
registry pair and pending-to-normal conversion, then ask the owner to register
`cragkit-langchain`; repeat for `cragkit-mcp`. Before each attempt confirm pending
identity matches the selected project or is absent for a normal-publisher retry.
Never dispatch a known unconfigured project or intentionally fail another upload
to consume a pending entry. Final strict nine-file download/clean install/source
smoke and V6-09/C3/exit remain required.

Maximum three phases times25runner-minutes atUSD0.006 givesUSD0.45; with observed
prior estimatesUSD0.192, proposed compute ceilingUSD0.642 before small storage/
allowance/rounding. This remains belowUSD2; keep actual measured spend separate.
No new paid validation. Reassess remaining budget before any additional run.

Root owns this contract, policy, test slot, evidence/tracker/Git and real runs.
Sol binding writer owns helper/workflow; Sol guidance writer owns focused tests
and publication guidance and assembles. Freeze this interface before dependent
edits. Tests precede implementation in the shared test slot; writers never edit
the same file. New tests cover selector/pending conflicts, phase file/npm
injection, missing core, unselected conflict, partial/full postflight, artifact
ID/run/source/repo/expiry/bounds/wrapper corruption and actual job permission/
admission separation. Preserve every existing guard, fixed product and user edit.
Root integrates focused serial acceptance before actual publishing.
