# Artifact licensing checks

Revision: ALC-r1, frozen before V6-06 packaging edits.

Outcome: all six RC1 packages declare MIT and carry byte-exact copies of the
root LICENSE and NOTICE. No package publication, account change, name reservation,
repository visibility change or provider call is authorized by these edits.
Names, versions, dependency graphs, runtime bounds and native execution remain
unchanged. npm private=true remains until separate publication authorization.

## Metadata lane

One Sol writer owns the three Python pyproject.toml files (child V6-06A1), the
three Node package.json files (A2), and LICENSE/NOTICE copies under each of those
six package directories. Root retains lockfiles, shared root files, tracker,
workflow and Git. No dependency/lock installation or test runs by peers.

Python project fields: license="MIT", license-files=["LICENSE", "NOTICE"],
description appropriate to the existing library/adapter role, authors with name
Vaibhav Suman only, and project URLs to the existing GitHub repository. The pinned
Hatchling 1.32.4 supports this PEP 639 declaration. Do not add license classifiers
or a build dependency. Wheel license files belong under the single .dist-info/
licenses directory; sdist retains root LICENSE and NOTICE. Package imports and
public versions stay unchanged.

Node metadata: license="MIT", author="Vaibhav Suman", descriptive text,
repository URL/directory and issue/homepage URLs. Explicit files entries include
dist, LICENSE and NOTICE. Keep private=true. Root will align package-lock root
metadata without changing resolved dependencies or integrity hashes.

## Validator lane

The complementary Sol owns only tools/artifact_licensing.py and
tools/tests/test_artifact_licensing.py (V6-06B), and assembles the peer pair. It
implements a standard-library pure helper:

```python
validate_artifact_licensing(
    files, *, kind, package_name, version, license_bytes, notice_bytes
) -> None
```

files is the bounded archive_files dictionary of member names to bytes. kind is
wheel, sdist or npm. Raise a fixed ArtifactLicensingError on any invalid record;
never include archive payloads, names supplied by data or exception chains in an
error. The helper performs no I/O, build, install, network or credential discovery.
Root wires it into existing package acceptance tools after ownership returns.

Wheel: exactly one .dist-info/METADATA with supported PEP 639 metadata format
2.4, 2.5 or 2.6 (the current pinned builder emits 2.5);
correct normalized distribution name and
exact version; one License-Expression MIT; exact License-File declarations LICENSE
and NOTICE; byte-exact payloads at that metadata directory's licenses/LICENSE
and licenses/NOTICE. Reject duplicate metadata headers that could disguise a
different declaration. Do not invoke archive-provided code.

Sdist: one top directory containing pyproject.toml, LICENSE and NOTICE. Check
project name/version/SPDX/license-files from standard-library tomllib and exact
license/notice bytes. Permit normal package source and build configuration; the
separate generic archive path/size/asset guard still applies.

npm: package/package.json has exact name/version, license MIT, private=true and
the explicit dist/LICENSE/NOTICE files entries; package/LICENSE and package/NOTICE
match expected bytes. This validates local guarded candidates, not publication
eligibility. Unknown/incorrect formats, missing notices, mutated text, ambiguous
headers and wrong identities must fail. Tests use synthetic archives and meaningful
rejection cases. No test execution by the peers; root owns the single test slot.

## Integration and resource scope

Peers coordinate concrete dependencies directly and may transfer owned files only
after agreement, stopped writes and root notification. Outcome/contract/protected
changes require root; unresolved material decisions go through root to Astra.
The assembler inspects both lanes, reports actual changes and limitations and
returns ownership before root integration. The root NOTICE and LICENSE are shared
immutable inputs for these lanes. Apply self-contained prose hygiene to new prose.

Local native/load tests are stopped after sustained swap growth in V6-05. Writers
may perform light file edits/reads, without installs, services, tests or downloads.
Root rechecks headroom before validation. Hosted CI must have its own declared
runner/matrix and cost decision before dispatch; preparing a manual workflow
does not establish a CI pass or authorize a billable run. Final exact artifacts,
source identity, offline replay compatibility and publication remain separate gates.
