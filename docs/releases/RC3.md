# Python RC3 publication provenance

Python `1.0.0rc3` is the prepared corrective release for `cragkit`,
`cragkit-langchain` and `cragkit-mcp`. Publication and provenance verification
are pending; see the [current roadmap](../roadmap.md). npm remains at
`1.0.0-rc.2` and does not require new files for this Python correction.

## Correction

RC2's Python upload explicitly disabled publish attestations. The files matched
the reviewed products, but PyPI reported a loss of provenance compared with RC1.
RC3 restores publication attestations for every wheel and source distribution.
RC2 and its warning history remain available and unchanged.

A publish attestation identifies the authorized publisher and the exact file
digest. It does not certify source security or assert that GitHub built the file.
Locally built, reviewed products can be attested during publication. See
[PyPI's security model](https://docs.pypi.org/attestations/security-model/).

Package versions, matching Python integration pins and the Python engine version
advance together. Runtime behavior and third-party dependencies remain unchanged
from RC2. npm's engine version remains `1.0.0-rc.2`; the result schema stays `0.1`.
Historical evaluation identities and receipts are not relabeled.

## Acceptance

Admission requires local package checks, runtime-payload comparison, clean
installed consumers, exact registry downloads and verification of all six
publication attestations against their file hashes and the configured publisher.
A successful upload or a provenance API response alone is insufficient.

The [recorded runtime limitations](V6.md) still apply. This correction does not
establish production readiness, general model quality or public GitHub access.
