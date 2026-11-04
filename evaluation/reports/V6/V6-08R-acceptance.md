# V6-08R corrected packet acceptance

4 November 2026. Local corrected-packet acceptance passed. The user's active
goal includes RC1 deployment; archive choices and GitHub public conversion remain
deferred. V6-08 stays incomplete until actual registry publication and clean
download/install/source-access checks pass. The artifact hold is cleared for the exact reviewed owner npm bootstrap after
authentication/write-2FA verification. Hosted publication stays disabled pending
its separate registry/trust configuration checks.

For example, npm needs a public projection of the reviewed tarball: changing its
top-level `private` boolean creates a new archive identity even though every
runtime file is unchanged. Both identities are recorded and independently
compared before upload.

## Fixed products

[PPR-r2](../../../contracts/REPLACEMENT_PUBLICATION_V6.md) selects corrected
source `a3ff7e81332d849724407356d220c991e8a8411d`, package tree
`63dafe3b3906778e456b1cd2aefb7f99cd896e43`, CI run/job/artifact
`41777862696` / `126402305700` / `13297269766`. The retained candidate ZIP is
1,286,413 bytes, SHA-256
`422cb0367bdd11b61416b287378abffbd78c60442f1ceb1ce7523280d58858be`.
[Actual hosted evidence](V6-08C-CI2.md) remains separate from this local run.

Six Python files are exact CI copies; three npm tarballs change only the allowed
top-level guard. Current independent `prepare_release_products.py verify`
returned `verified_local`. Manifest SHA-256 is
`7ab4ba1aeebfce8b83871f7bda8bf09cfdc39e6e405f28a0ca88fe55ecbdc663`.
The [immutable preparation summary](V6-08R-verification.json) retains digest
`32b3251e3ef7d9536830f15ed1c196a45f2c1a91c31093dce2d99aed99471312`.
The original PPR-r1 summary was unchanged; this acceptance is a separate record.

The deterministic transport is 1,496,502 bytes, SHA-256
`609f3f84924417d4c0e9baefeb2097e10d35cc5e1e43cc283add970a60545d48`.
Its successful unpack regenerates the identical manifest and all nine exact
product bytes. Workflow, policy and guide now agree on this digest. The first
operator unpack command had an unset checksum argument and was rejected before
output; it was corrected using the fixed reviewed digest. That command error
is not represented as an intentional regression test.

## Checks actually run

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_prepare_release_products.py tools/tests/test_check_ci_bundle.py tools/tests/test_artifact_licensing.py tools/tests/test_release_transport.py tools/tests/test_check_registry_products.py tools/tests/test_publication_workflow.py -q
```

Result: **378 passed in 2.34 seconds**. Preparation, CI admission, licensing,
transport, registry verifier and workflow cases ran together. New regressions
refuse historical/wrong source metadata even when its replacement summary digest
matches, and compare the actual executable workflow unpack command with the
reviewed policy while preserving admission and upload order. An older test
process handle was missing and its terminal result could not be recovered;
this captured combined run supplies the acceptance result.

Clean consumers outside the checkout installed the exact public projections
with cached dependencies, empty npm authentication configuration and lifecycle
hooks disabled. Versions/integrities of all 26 installed third-party npm
dependencies matched the reviewed locks. All three products imported from
installed locations, and all 113 npm member files matched their tarballs.
A fresh Python environment installed the exact corrected core wheel and frozen
dependencies offline. Its default-import probe passed with focused external-I/O
and optional-dependency guards.

Installed Python/Node evidence results matched: 23 source cases, eight context
cases, 127 token counts, 17 packing cases, 35 assessments and six pipeline cases.
Installed npm LangChain tests passed **108/108**; MCP passed **42/42**, with no
skips. MCP initially failed to load two test files because this temporary harness
omitted the test-only `@modelcontextprotocol/client`. The log established
`ERR_MODULE_NOT_FOUND`; the exact locked client was added offline, versions and
integrities were checked, and only the affected MCP test loading was rerun. No
product or production dependency was changed to fix the harness. Failed output
is retained privately alongside the passing results.

All nine products' 323 member files were decoded through existing bounded
parsers into numbered private files for static scanning. Gitleaks 8.30.1,
full redaction, empty ignore file and ignored allow-comments found **zero matches**.
Selected private/credential asset path checks also found zero matches. These
scoped checks do not establish universal security or examine public Git history.
Research PDFs, environments, provider credentials, private evaluation recordings
and database backups are outside these products. The existing qualified CSO
coverage remains partial; reviewed security leads retain their closed dispositions.

Raw consumer scripts, logs and scan results are owner-only outside Git. The
[sanitized machine record](V6-08R-acceptance.json) includes commands, identities,
counts, retained failure scope and remaining gates. No raw credential or private
query/source text is included. User-owned source/storage/tracker draft and three
audit drafts remain excluded from this change. No runtime source, package
manifest, lockfile, migration or historical receipt was rewritten.

## Remaining deployment work

The retained read-only registry preflight made nine bounded requests and found
all nine target files and three npm `next` tags absent. This proves neither
name ownership nor authenticated permission. Current npm `whoami` and profile checks authenticate `vaibhavsuman00` with
`auth-and-writes` 2FA and no pending setup. The owner confirmed PyPI pending
publishers are not configured yet. The browser-access
host is unavailable. The owner must complete secure sign-in/2FA and the pending
publisher setup; passwords, tokens and one-time codes must stay out of chat/Git.

After secure setup, bootstrap only the three reviewed npm RC1 tarballs under
`next`, establish the required ownership/trust configuration and verify present
bytes before the missing-only hosted job. Saved or skipped npm trust is not
successful OIDC evidence. PyPI pending publishers support first use without a
bootstrap upload. Use [the current procedure](../../../docs/publication.md) and
its separate bootstrap/workflow admission requirements.

No registry upload, private release-asset upload, publishing dispatch, new paid
validation or repository visibility change ran. Prior replacement CI compute
estimate is USD 0.186 before included usage; the planned 20-minute Linux publish
job estimates at most USD 0.12 before storage/allowance, within the user's USD 2
ceiling. Actual billing remains unverified. Current work used bounded serial
local checks, no model call or running database. Observed headroom was 16 GiB
disk and 42 percent free system memory before consumers.

V6-08 publication/post-registry smoke, V6-09 maintenance, C3 and version exit
remain incomplete. Historical quality, migration and replay results retain
their original candidate scope. Learning is unassessed. Optional exercise:
trace why changing one runtime byte cannot be approved by replacing only a
manifest hash, then identify which registry facts must be checked after a partial
upload.
