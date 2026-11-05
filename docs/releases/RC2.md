# RC2 package descriptions

Python `1.0.0rc2` and npm `1.0.0-rc.2` are the published description-update release
for `cragkit`, `cragkit-langchain` and `cragkit-mcp`. Exact-download and installed-consumer checks passed;
the [roadmap](../roadmap.md) records current registry acceptance.

## Changes

Each of the six packages includes its own README with purpose, installation,
working API examples, configuration, trusted identity boundaries, limitations and
MIT license information. Python manifests declare the README as their Markdown
project description. The package checker verifies descriptions in wheel metadata,
source distributions and npm tarballs.

Package versions, matching integration dependencies and engine version identifiers
advance together. Runtime behavior and third-party dependency versions remain
unchanged from RC1. Uncommitted application/source edits are excluded from the
release products. Previously published RC1 files remain immutable.

Distribution contents follow the earlier reviewed separation of the private
maintainer workbench: obsolete npm test scripts and personal source-distribution
harness files are omitted. This inherited packaging cleanup does not change
runtime modules or third-party dependencies.

## Verification and limits

Release admission requires exact product hashes, README metadata checks, clean
installed consumers and runtime-payload comparison with RC1. The current task
does not start a new backend deployment, model evaluation or production test.
Recorded [RC1 runtime limits](V6.md) still apply; this release makes no new
quality, performance, compatibility or security-certification claim.

The source repository remains private, so GitHub documentation links require
collaborator access. Essential package setup and service-free examples are
included in each registry README. Publication does not make GitHub public or
deploy a consuming application.


## Python provenance correction

The Python RC2 uploader disabled attestations. PyPI consequently reports loss of
provenance relative to RC1 even though the files match the reviewed artifacts.
Use [Python RC3](RC3.md) for the corrective attested release. RC2 files and their
historical warning are preserved; they were not overwritten or deleted.

npm RC2 remains current. Its packages contain their full READMEs, and the owner
confirmed the core page displays the guide. Both `latest` and `next` select RC2.
