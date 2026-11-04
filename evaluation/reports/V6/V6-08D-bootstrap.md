# V6-08D first-use publishing correction

4 November 2026. Local acceptance passed; revised hosted behavior is unvalidated.
The first run's HTTP403 and the user's single pending-publisher screenshot
identified two distinct setup assumptions to correct. No PyPI file was uploaded
by that failed run. [PWB-r1](../../../contracts/PUBLICATION_BOOTSTRAP_V6.md) freezes
the replacement operator interface; the nine products and PPR-r2 hashes stay fixed.

For example, a selected `cragkit` phase sees six missing Python files but may
authorize only its two reviewed core files. It cannot upload another project's
files or an npm file. Other absent projects remain explicitly incomplete.

## Verified locally

The six preparation/CI/licensing/transport/registry/workflow suites passed
**431 tests** in 2.57 seconds, including 97 focused workflow cases. The one warning
is expected from intentionally constructing a duplicate-name ZIP fixture. New
phase/artifact interfaces had 11 expected red cases before implementation. No
peer ran tests or account actions; root serialized execution and integration.

Coverage includes missing/unknown selectors, conflicting pending identities,
selected two-file plans, injected other-project/npm files, missing core,
unselected drift/error, phase/full postflight, same-run source/repository/ID,
expiry/size/URL, corrupted/extra/duplicate/traversal/link/directory/encrypted ZIP
members, declared-size failure before member read and preserved existing output.
Static checks inspect the actual two jobs' permission and admission separation.
Actionlint 1.7.12 passed both workflow files. GitHub run/repository IDs remain
immutable service defaults, without redundant workflow overrides.

A real current registry snapshot with three exact npm downloads produced an
actual local core plan: six absent files, two authorized files, zero npm files,
only the core upload flag true. Prepublication postflight correctly remained
phase_complete=false/publication_complete=false. Current product verifier and
frozen manifest/summary identities were preserved.

The retained real Actions candidate ZIP uses regular Unix mode `0o100644` members and
a classic end record. A local single-member wrapper using that observed format
unwrapped the exact 1,496,502-byte sealed transport, SHA-256 `609f3f84924417d4c0e9baefeb2097e10d35cc5e1e43cc283add970a60545d48`.
This validates bounded local parsing, not the unrun new hosted handoff.

## Required hosted proof

The fetch job has contents-write and no OIDC, a five-minute cap, and verifies
only draft/asset metadata plus the fixed sealed bytes before one-day artifact
handoff. It never unpacks products or runs registry actions. The publisher has
contents-read/actions-read plus OIDC, a twenty-minute cap, no repository write.
Both independently enforce owner/manual/private/main/exact-SHA/first-attempt,
hold-clearance, enable marker and selected setup. Wrapper download is bounded
at 4 MiB, metadata is tied to the same run/source/repository, and inner size/hash
are checked before product reconstruction.

Selected PyPI phases require all npm products verified; adapters additionally
require the core Python pair. Plans distinguish all missing from authorized
missing. Postflight distinguishes complete phase from complete publication;
valid absent required files may receive ten bounded read-only observations,
while conflicts and operational errors stop. No upload is retried automatically.

Only core pending is confirmed. The owner retains that entry. After actual core
registry verification and pending conversion, register the next project under
the same workflow, one at a time. Warehouse can create a project during minting
before upload, and pending identity takes precedence over normal identity. After
any partial failure inspect the actual pending/normal state before retrying.
The existing private draft must be explicitly rebound to the new reviewed
executing SHA before dispatch; its identity check was not loosened.

## Cost and remaining work

Including both observed candidate jobs and the failed 36-second publish attempt,
compute estimate is USD 0.378 before included allowance. Three additional capped
phases total at most 75 runner minutes / USD 0.45, projecting USD 0.828 before small
one-day storage and billing adjustments, below the user's USD 2 ceiling. No new
paid validation ran. Actual invoice/allowance remain unverified.

[Sanitized detail](V6-08D-bootstrap.json) retains counts, scope and limitations.
Raw logs/scripts/scan data remain owner-only outside Git. Root inspected Sol
implementation, test/docs assembly and Astra's bounded permission/phase review.
No runtime, lock, migration, archive choice, public visibility, package version
or registry tag changed in this fix. V6-08 still needs actual selected uploads,
strict nine-product downloads and clean installed source-access smoke; V6-09,
C3 and exit follow. Learning is unassessed. Optional exercise: explain why a
valid core publisher cannot safely authorize a different project's first upload.
