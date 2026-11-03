# V6-08: verified local publication preparation

State: V6-08A/B complete for local preparation. V6-08, publication, maintenance
handoff and version exit remain incomplete. No registry upload, account change,
new CI run, tag, GitHub release or repository visibility change occurred.

For example, changing npm's `private` value changes its tarball hash even when
every runtime byte stays equal. The preparation receipt records both identities;
the earlier CI pass is not relabelled as a pass for unchanged archive bytes.

## Products and verification

The [PPR-r1 contract](../../../contracts/PUBLICATION_PREPARATION_V6.md) binds the
original CI bundle to source `0c7c568`, run `41625938303`, job `125883197705`
and artifact `13226006299`. The original ZIP and all rebuilt wheels remain
retained evidence. The [machine-readable acceptance](V6-08-verification.json)
lists the nine proposed upload files and their original/prepared SHA-256 values.

Root ran the preparation and independent verification commands documented in
[the publication guide](../../../docs/publication.md). Both passed. The manifest
at `artifacts/V6/publication-rc1/publication-manifest.json` has SHA-256
`7ced6f15ee096752d8e974d793d1bd99a8f41d77181fb061d2871d890aeb5dc5`.
It records local preparation and false authorization/publication flags.

All six Python products are byte-identical to CI. Each of the three npm
projections changes only the top-level `private` token from true to false,
preserving every other manifest byte and member byte/name/executable mode.
The tool validates bounded archives without extraction or execution and derives
expected files from the pinned original bundle rather than trusting supplied
replacement hashes. An exclusive destination claim preserves existing output;
the manifest is linked last. Failed cleanup removes only this invocation's
inode-matching files and empty directories. Tracked packages/locks are unchanged.

Root ran these serial checks:

| Check | Actual result |
| --- | --- |
| Preparation, CI-bundle and licensing tests | 161 passed in 0.45 seconds. |
| Full current-checkout Python/tool suite | 4,156 passed, zero skips, four existing intentional serializer warnings in 19.45 seconds. This is local tooling/regression evidence, not another frozen-source hosted run. |
| Exact projected npm products | All three installed in a fresh consumer; all 113 shipped members matched archive bytes; imports resolved inside that installation. |
| Locked dependencies | Fourteen production dependency version/integrity identities matched the reviewed locks; the explicit tokenizer dependency retained its pinned version. |
| Native evidence probes | Python's unchanged exact CI core wheel and newly installed Node product matched across 23 source, eight context, 127 token, 17 packing, 35 assessment and six pipeline cases. Their probes reject external network/process I/O and use synthetic fixtures/fake SQL. |

Consumer commands, isolated import origins and results are retained under
`artifacts/V6/publication-consumer-verified/`; the command script and evidence
hashes are recorded in the JSON acceptance. Python reused its already accepted
exact-wheel environment. This run did not reinstall unchanged Python optional
products or repeat the earlier native database/backend acceptance. Those retain
their separately identified V6-06/07 evidence.

The first offline npm attempt failed with `ENOTCACHED` for package metadata.
A lock built from existing reviewed URL/integrity records avoided that lookup,
then identified a missing tokenizer tarball in the local cache. Both failed
directories/logs are retained. The successful fresh consumer used `npm ci` with
the same locked products, public dependency downloads, empty user/global auth
configuration and scripts/audit/funding disabled. No registry credential,
provider call or publication was needed. The archive preparation/verification
tool itself remains offline.

## Disclosure and resource limits

Root inspected all nine products and 320 members. Selected private provider
values and their base64 representations, plus the declared OpenAI/GitHub/private
key patterns, had zero matches. Both selected private credential files were
regular, current-owner, single-link, mode 0600 with private immediate parents.
This scoped scan does not establish universal absence of secrets. Known private
asset suffixes were absent. See [the disclosure inventory](V6-08-disclosure.md)
for the source/tests/lockfiles/metadata that public packages would expose.

The laptop had 23 GiB disk headroom and 36 percent system memory free before
the checks, then 42 percent free afterward. The final absolute swapout counter
was 7,287,520; no in-run pressure series was collected, so no zero-swap or load
performance claim follows. Checks used one process at a time and small fixtures.
No background database/service was started or left running.

Sol product and guidance peers used nonoverlapping ownership and direct interface
messages; guidance assembled the pair. Root inspected the files and results and
ran final acceptance. The self-contained prose workflow and link/consistency
review apply to the delivered documentation. The [RC1 notes](../../../docs/releases/V6.md)
preserve the benchmark, platform and unavailable-human-trial limitations.

## Next boundary

The next slice is verified registry identities/permissions and a reviewed
publication workflow with a durable transport for these retained products.
The original hosted artifact has one-day retention; a later workflow must not
assume it remains downloadable or rebuild substitute bytes after expiry.
Publication and any additional workflow spending require specific authorization.
Post-registry fetch/hash/install/source-access smoke must pass before V6-08 can
close. The repository remains private; research-PDF/history rights are outside
this package-only review.

Failure case: replacing a runtime byte and updating the supplied manifest still
fails verification because expected products are rebuilt from the pinned CI
bundle. Exercise: identify which receipt proves byte ancestry and which future
receipt would prove registry publication. Learning practice remains unassessed.
