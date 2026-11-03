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
immutable action commits, one macOS ARM64 job and a 30-minute job timeout.
Core, framework and MCP checks run serially; exact archive/install profiles follow.
It starts no persistent service, publishes nothing and retains candidate files
for one day. A workflow definition is not a CI pass.

The [single approved candidate run](../evaluation/reports/V6/V6-06-ci.md) passed
for source `0c7c568`. Its downloaded products and hashes are retained locally
beyond hosted expiry. This approval covers that completed run only; future paid
CI, registry publication and repository visibility need their own authorization.

GitHub documents standard runners as free for public repositories. Private
repositories draw on included usage and then incur charges. At the recorded
review, standard macOS compute is listed at USD 0.062 per minute: 30 minutes would
be USD 1.86 before included usage, rounding and separately billed storage. Current
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

Prepare the changelog and exact reviewed archive hashes. Current npm packages
remain `private: true` to prevent accidental publication. A prospective public
build needs its own explicit metadata review and final artifact checks before
permission to publish; do not simply remove the guard and upload an unchecked
replacement. Configure registry ownership and scoped/trusted publishing through
the account's secure workflow. Never put a registry token in Git or chat.

Publication, repository visibility and package releases need their specific user
approval. After authorized publication, fetch the registry products into fresh
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
