# Python RC3 publication provenance

Python `1.0.0rc3` is the published corrective release for `cragkit`,
`cragkit-langchain` and `cragkit-mcp`. All six distribution files
passed exact-download and cryptographic provenance verification; see the [current roadmap](../roadmap.md). npm remains at
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

The [recorded runtime limitations](V6.md) and [validation report](validation.md)
still apply. The report separates the historical quality comparison from RC3
package verification. This correction does not establish production readiness,
general model quality or universal hardware support. The repository is public by the owner's explicit
decision; this does not certify a consuming application's deployment.

## Verified publication

All three project descriptions match their package READMEs. The six downloaded
files match the admitted hashes and sizes. Fresh installation and 11 synthetic
consumer groups passed. The official `pypi-attestations` verifier checked every
signature, file digest, repository, workflow, publisher commit and run. Wrong
digests, workflows and altered signatures were rejected.

The publisher was commit `0b9bfbba2dbf716517e1312ac624273f6f4b97cc`, in
[run 42054210894](https://github.com/vsuman00/Cragkit/actions/runs/42054210894).
Product source was `0930c191097397521fb269e6947edd0dea5f7afd`. The temporary
uploader is disabled and preserved in the private maintainer archive.

| Package | Attested Python release | Current npm release |
| --- | --- | --- |
| `cragkit` | [1.0.0rc3](https://pypi.org/project/cragkit/1.0.0rc3/) | [1.0.0-rc.2](https://www.npmjs.com/package/cragkit/v/1.0.0-rc.2) |
| `cragkit-langchain` | [1.0.0rc3](https://pypi.org/project/cragkit-langchain/1.0.0rc3/) | [1.0.0-rc.2](https://www.npmjs.com/package/cragkit-langchain/v/1.0.0-rc.2) |
| `cragkit-mcp` | [1.0.0rc3](https://pypi.org/project/cragkit-mcp/1.0.0rc3/) | [1.0.0-rc.2](https://www.npmjs.com/package/cragkit-mcp/v/1.0.0-rc.2) |

npm's `latest` and `next` tags both select RC2 for all three packages. The owner
confirmed the core npm page displays its full README. Registry JSON omits that
README text, so JSON-field presence was not used as proof of page rendering.
No new npm package bytes or publisher permissions were needed.
