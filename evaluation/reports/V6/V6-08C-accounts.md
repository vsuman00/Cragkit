# Registry account readiness

4 November 2026. V6-08C-account-r2: public-account declarations and read-only
preflight are recorded; authenticated permissions and publisher setup remain
pending. The user supplied `vaibhavsuman00` for PyPI and npm and confirmed 2FA
enabled on both. No login, account change, workflow dispatch or upload occurred.
The security hold remains true.

For example, a pending PyPI publisher authorizes a specific workflow to create a
project on first use. Saving it does not reserve the package name. The registry
account username and GitHub repository owner are different fields.

The [verification record](V6-08C-accounts-verification.json) records exact public
requests, workflow hashes, the CI proposal and unverified states. The Sol PyPI
peer owned first-use/account requirements; the Sol npm peer owned bootstrap
requirements and assembled both private reports. Root inspected both reports,
the actual missing-only planner and publishing workflow, and performed preflight.
No runtime, lock, schema or workflow code changed.

## Observed account and name state

| Check | Actual result |
| --- | --- |
| User account declaration | PyPI and npm username `vaibhavsuman00`; both accounts have 2FA according to the user. |
| Public PyPI profile | Profile exists and displays the supplied username with no projects. This does not authenticate this session or prove account ownership. |
| Public npm profile | Web fetch returned HTTP 403; account existence was not independently established through that page. |
| Three PyPI project metadata requests | `cragkit`, `cragkit-langchain`, `cragkit-mcp`: HTTP 404 each. |
| Three npm package metadata requests | Same names: HTTP 404 each. |
| Signed-in account inspection | Browser host unavailable; native Chrome fallback timed out. No account/session/permission state was obtained. |

The six requests used direct verified HTTPS with bounded time/size limits and no
credentials. They requested project/package metadata, rather than only an absent
version. Public absence establishes neither reservation nor permission to create
a name; registries can reject names for other policy reasons. Existing names,
denied creation or unexpected account identity require review before proceeding.
The [public PyPI profile](https://pypi.org/user/vaibhavsuman00/) is only public
identity evidence.

## Owner setup

Use your own signed-in registry sessions. Confirm the username, verified email
and account protection there. Keep passwords, tokens, recovery material and
one-time codes private. This task did not inspect credential files or request a
key. Account confirmation and actual publishing permission are distinct checks.

For PyPI, open [account Publishing](https://pypi.org/manage/account/publishing/)
and prepare one GitHub pending publisher per project. The fields matching the
current workflow are:

| Field | Value |
| --- | --- |
| PyPI project name | One entry each for `cragkit`, `cragkit-langchain`, `cragkit-mcp` |
| GitHub owner | `vsuman00` |
| Repository | `Cragkit` |
| Workflow filename | `publish-candidate.yml` |
| Environment | Leave blank; the inspected job declares none |

Use the filename only. Before saving, review that this grants the named workflow
publishing access; inspect each saved pending row afterward. No package is
uploaded by this setup. PyPI's [first-use instructions](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)
describe creation on actual first publication and explain that a competing
registration can invalidate pending setup. No pending row was saved by the agent.

For npm, [trust setup requires an existing package](https://docs.npmjs.com/cli/v11/commands/npm-trust/).
The three requested names were absent in this preflight. After replacement CI,
packet review, explicit hold removal and approval of the exact public products,
the owner can first publish the three approved npm RC1 tarballs through secure
interactive login/2FA, core before adapters, under `next`. This is an actual
public release action, not account setup. No executable bootstrap command is
provided for the stale retained products.

Once a package exists, its GitHub trusted publisher uses the same owner,
repository, filename and blank environment above. Direct `npm publish` permission
must be selected for the current workflow. A saved publisher is not a successful
OIDC test. Newly configured trust expires unless its first successful publish
occurs within two days; do not create an unused trust and call it permanently
verified. npm's [configuration and expiry rules](https://docs.npmjs.com/trusted-publishers/)
also distinguish private-source publishing from provenance availability.

The current missing-only planner can reconcile already published npm products
by exact bytes and matching `next` tags, then upload only missing PyPI products.
That sequence was inspected at `tools/publication_workflow.py:76` and
`tools/check_registry_products.py`; it was not executed. A job skipping npm proves
no npm OIDC authentication. No admission condition was weakened. If successful npm
OIDC is required before release acceptance, a reviewed later version or different
bootstrap design is still needed.

Do not stage placeholders to claim these names: npm's
[new-name staged flow](https://docs.npmjs.com/staged-publishing/) creates a public
`0.0.0-stage` package. That would expand the held RC1 product set. No placeholder,
name change or registry mutation occurred.

## Replacement CI proposal

The prepared next execution is one manual `candidate-validation.yml` job on
reviewed `main`, using `macos-15` ARM64 with a 30-minute timeout. It runs serial
native checks and builds/validates the corrected core, LangChain and MCP products.
Artifacts have one-day retention. Workflow permissions are `contents: read`;
it has no registry upload step. No rerun or separate publishing job is included.
The proposal binds the current workflow digest; the exact pushed source SHA must
be checked immediately before dispatch and against the resulting run.

Estimated compute at the current macOS rate is up to USD 1.86 before included
usage: 30 minutes times USD 0.062. Artifact storage is additional; remaining
included usage/storage is unverified. [GitHub runner rates](https://docs.github.com/en/billing/reference/actions-runner-pricing)
and [billing/storage rules](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
were checked for this proposal. This is an estimate, not a claim of a free run.

The earlier single-job approval has been consumed. This proposal has no new
approval and was not dispatched. Current
[workflow input](../../../.github/workflows/candidate-validation.yml) defaults
`runner_cost_acknowledged` to false. Obtain approval for this one job before
dispatch; the separate publishing job and account access remain outside it.

## Handoff and verification

Six public metadata requests completed without operational errors. Primary
registry documentation and the actual workflow/planner were reviewed. Only small
text/network reads ran; available disk was about 15 GiB. No install, model,
provider request, database process or product test was needed for documentation
and account evidence. No background task or persistent service was started.
Prose, links, JSON consistency, protected-worktree and staged-secret checks are
recorded by the final integrator. Older frozen packet hashes remain unchanged.

Next: separately approve corrected candidate CI, complete signed-in PyPI pending
setup and later approved npm bootstrap, and verify actual account permissions.
Candidate CI does not depend on those registry settings. Release-packet review,
explicit upload authorization and post-registry download/install/source smoke
remain required. V6-08C/08D and version exit are not complete.

Failure example: entering `vaibhavsuman00` as the GitHub owner would mismatch
`vsuman00/Cragkit`. Optional exercise: explain which observation proves public
name absence and which later operation can establish actual publishing rights.
