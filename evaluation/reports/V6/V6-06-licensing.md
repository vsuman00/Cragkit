# V6-06 licensing preparation

State: A1/A2 metadata, B validator and C1/C2 integration passed local focused/layout
checks. Parent V6-06 remains incomplete: clean exact artifacts, installed profiles,
final compatibility/resource evidence and hosted CI are still required.

Root froze [ALC-r1](../../../contracts/ARTIFACT_LICENSING_V6.md). One Sol peer owned
the three Python and three npm manifests plus twelve license/notice copies; the
other implemented the pure archive validator and tests and assembled the result.
Peers coordinated directly, inspected actual files and returned ownership. Root
inspected the result, aligned npm lock root-license metadata and wired the helper
into core, framework and MCP wheel/sdist/npm acceptance. Dependency graphs,
integrity hashes, public versions, runtime bounds and npm privacy stayed unchanged.

All six packages now declare MIT and author Vaibhav Suman without an email, with
role-specific descriptions and existing repository URLs. Each ships exact root
LICENSE/NOTICE text. Python uses PEP 639 metadata supported by the pinned build
backend; npm explicitly lists the two notice files. The validator performs no I/O
or execution, rejects missing/mutated texts and ambiguous identities/headers, and
returns a fresh fixed error without parser content or chains.

Root passed 135 focused helper/artifact regressions. Nine actual offline preview
archives passed the licensing layout checks: three wheels, three sdists and three
npm tarballs. An initial preview script mistakenly enumerated uv's generated
`.gitignore` as an archive; selecting the explicit expected archive names corrected
the harness. Actual wheel metadata was 2.5; a root-added exact 2.4 assumption was corrected
against the current PyPA specification to accept known PEP 639 formats 2.4–2.6
and reject old/invalid formats. Exact licensing checks remain unchanged. These previews include preserved
user prose and are not final release products. The
[verification record](V6-06-licensing-verification.json) retains hashes and limits.

The small serial builds recorded 47–48% memory free with no new swapouts. Earlier
V6-05 native/load work remains separate; no database/model/provider service ran
for these licensing checks. No registry publication, repository visibility change
or hosted CI dispatch occurred.

All six registry-name queries returned HTTP 404 at the recorded time, which is
neither reservation nor verified account ownership. GitHub reported a private
repository, Actions enabled and zero existing runs. The billing allowance could
not be read. The prepared manual-only workflow uses immutable action commits,
read-only contents permission and a 30-minute single-job timeout; no CI pass or
free private run is claimed.

The [publishing/deployment guide](../../../docs/releasing.md) teaches license,
artifact, CI, permission and consumer-hosting steps separately. Next: commit this
verified child scope, prepare a clean candidate and validate exact installed
artifacts and post-evaluation compatibility; obtain a concrete CI cost/visibility
decision before dispatch if free usage cannot be independently established.
