# Publishing and deploying Cragkit

For example, publishing a wheel lets another Python application install Cragkit.
That application's server, database and API keys still belong to its operator.
This library does not need its own always-on hosted service.

The [release tracker](../tasks/todo.md) is the authority for completed gates.
Python `1.0.0rc1` and npm `1.0.0-rc.1` are candidate versions. Local builds,
hosted CI, package publication and a deployed consuming application are separate
outcomes. None follows automatically from pushing a commit.

## License and notices

The project's [MIT license](../LICENSE) grants use of this code free of charge.
There is no Cragkit license purchase step. Copies of that license and the
[distribution notice](../NOTICE) must accompany the candidate packages. Each
package declares MIT, and the archive checks compare the shipped text byte for
byte with the reviewed source files.

Dependencies retain their own licenses. Database servers and model/tokenizer
assets are not bundled in the core. Hosted model APIs, hosting and private CI can
have separate usage charges; MIT does not make those services free. Keep the
consumer's credentials outside source control and tool inputs. Cragkit supplies
no shared built-in provider key and does not load `.env` automatically.

## Prepare a candidate

Start from a clean reviewed commit, not a checkout containing unfinished user
edits. Record the source commit, supported runtime/backend matrix, exact locks
and candidate version. Verify package names against the intended registries and
your account permissions. A registry 404 is not a reservation or a promise that
publication will be allowed.

Build the Python wheel and source distribution, rebuild the wheel from that source
distribution, and pack npm tarballs. Use frozen dependencies and immutable action
revisions. The [development guide](development.md) contains the acceptance tools;
the [licensing contract](../contracts/ARTIFACT_LICENSING_V6.md) defines the new
MIT/NOTICE checks. Inspect archives for credentials, private inputs, unsupported
assets and unintended files before sharing them.

Install the exact built products into fresh application environments outside the
checkout. Verify import origins and versions, run examples, and retain hashes and
acceptance results. A passing source test does not prove a package contains the
same code or notices. Local working-tree previews are not frozen release artifacts.

The post-evaluation reranker security correction is tracked separately from the
original live benchmark. Preserve that benchmark's source/tape identity. Final
candidate compatibility, resources and artifact acceptance must identify the
actual code being released rather than relabel the old run.

## Hosted validation

[Candidate validation](../.github/workflows/candidate-validation.yml) is manual
only. It uses a read-only repository token, no provider/database credentials,
immutable action commits, one macOS ARM64 job and a 25-minute job timeout.
Core, framework and MCP checks run serially; exact archive/install profiles follow.
It starts no persistent service, publishes nothing and retains candidate files
for one day. A workflow definition is not a CI pass.

The [replacement candidate run](../evaluation/reports/V6/V6-08C-CI2.md) passed
for source `a3ff7e81332d849724407356d220c991e8a8411d`. Its exact archive and
metadata are retained locally beyond hosted expiry. Earlier run receipts remain
historical. No additional paid validation run is included in the current scope.

GitHub documents standard runners as free for public repositories. Private
repositories draw on included usage and then incur charges. At the recorded
review, standard macOS compute is listed at USD 0.062 per minute: 25 minutes would
be USD 1.55 before included usage, rounding and separately billed storage. Current
account allowance was not accessible through the available API; no free private
run is assumed. See [runner specifications](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)
and [current pricing](https://docs.github.com/en/billing/reference/actions-runner-pricing).

The workflow requires an explicit runner-cost acknowledgment. Before dispatch,
choose a genuinely free covered run or approve a bounded budget. Changing this
repository's visibility requires separate user authorization and makes committed
history public; no workflow should do that itself. A skipped job or failed setup
must not be reported as validated CI. Keep the runner's own OS, architecture,
toolchain, commands, job URL and result artifacts in its acceptance report.

## Publish after the remaining gates

Rehearse migration, interruption and recovery on disposable data before the
publication decision. Application rollback and database rollback are different:
restoring an old package must not restore revoked access or bypass a newer
required schema/profile. Keep migration checksums and recovery instructions with
the candidate.

The [RC1 notes](releases/V6.md) and [disclosure packet](../evaluation/reports/V6/V6-08-disclosure.md)
now accompany nine locally prepared products. Tracked npm packages remain
`private: true`. The offline [preparation tool](../tools/prepare_release_products.py)
copies Python archives unchanged and changes only npm's private token in separate
tarballs. Its verifier derives expected bytes from the pinned CI bundle instead
of trusting a replacement manifest. This local acceptance is recorded in
[corrected V6-08 preparation](../evaluation/reports/V6/V6-08R-verification.json);
[the original preparation report](../evaluation/reports/V6/V6-08-preparation.md)
remains historical evidence.

Follow the [publication procedure](publication.md) for the remaining secure
registry ownership/bootstrap and workflow admission steps. The publishing workflow is prepared and
default-disabled between phases. The three npm products and core PyPI pair have
verified publication evidence; remaining Python adapters need their matching
selected-project setup. Never put a registry token in
Git or chat. The GitHub repository stays private; public packages disclose their
own contents. npm provenance is unavailable from private source repositories,
as documented in [npm trusted publishing](https://docs.npmjs.com/trusted-publishers/).

The user has resumed RC1 deployment; repeat upload-intent approval is not needed.
Corrected packet acceptance and npm owner/write-2FA checks passed, clearing
the artifact hold for the exact owner bootstrap. Hosted admission remains
disabled until the required registry/trust configurations are verified.
Repository visibility and archive choices remain deferred. After publication, fetch the registry products into fresh
environments and verify version/hash policy plus a source-linked smoke query.
Keep prerelease/stable claims distinct. A broken published version generally needs
a new corrective version; do not pretend that replacing local bytes repairs what
users installed.

## Deploy a consuming application

Select only the profiles that application needs. PostgreSQL lexical use needs no
embedding service; dense/reranked use requires explicitly configured providers
and disclosure choices. Apply migrations as a separate operator step, use restricted
runtime roles with verified TLS, bind trusted scope outside agent input and reuse
bounded pools. Store credentials in the application's private environment or
secret store. The [operations guide](v5-operations.md) describes these boundaries.

Start with synthetic data and a small resource budget. Check cancellation,
permission denial, exact citations and operational failures before real user data.
Monitor latency, queue pressure and redacted diagnostics. Define rollback and
support ownership before presenting the application as production-ready. No
dashboard, hosting platform or paid model is required merely to publish this
retrieval library.
