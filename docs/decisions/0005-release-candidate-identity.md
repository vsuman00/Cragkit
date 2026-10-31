# 0005: Coherent candidate identity before evaluation

Accepted on 31 October 2026 as a sequencing amendment, before original held-out
access. It changes neither frozen quality/resource targets nor publication
authorization. Implementation and actual verification remain tracker-owned.

For example, Python `1.0.0rc1` and npm `1.0.0-rc.1` name the same release stage.
Both native result wires will declare engine `1.0.0-rc.1`, so exact parity does
not need to erase version differences. The result schema remains `0.1`; package,
engine and schema identities serve different purposes.

## Decision and scope

Prepare the preregistered RC metadata and native engine identity as V6-02F,
before clean source/runtime preparation and the first held-out execution.
The six library manifests, their internal core pins and locks, core exports,
native engine emitters/defaults, MCP server identities and current artifact
guards must agree. Python package metadata and its public `__version__` use
`1.0.0rc1`; npm metadata/exports and the shared wire engine use `1.0.0-rc.1`.
MCP servers use the common SemVer spelling. Do not rewrite unrelated test-client
versions or dated reports. Keep third-party dependency versions and hashes fixed.

Update active normative result documentation, schema defaults and affected
shared fixtures deliberately. Parsed historical results declaring `0.0.0`
remain valid identities; fresh native results and default-generated fixtures
must use the new declared engine. No filter, authorization, ranking, coverage,
packing or lifecycle behavior is changed by this prerequisite.

Keep each slice bounded: root owns the shared decision/contracts/fixtures,
manifests/locks, artifact policy, tracker and integration; language peers may
own separate native source/test paths after the contract is frozen. Serialize
installs, typechecks and integration tests. Preserve existing user prose edits.
Record the clean candidate source commit/package tree only after the coherent
metadata and required checks pass. ECR must reject package/engine identities
that differ from the declared candidate rather than merely fingerprinting them.

## Why preparation moves earlier

The [release freeze](0004-v6-release-freeze.md) named RC1 while all actual
packages and engine declarations remained `0.0.0`. The original plan deferred
metadata to V6-06, after evaluation, performance, security and usability work.
EPB/ECR bind source and runtime bytes strictly; a later version change cannot
inherit or relabel the earlier execution receipt. Two Sol reviewers inspected
the declarations and resolved this dependency directly; root accepted their
explicit preparation prerequisite.

Keeping engine `0.0.0` by redefining it as an unrelated protocol revision would
contradict its current declared implementation meaning. Evaluating a clearly
named `0.0.0` candidate and later proving a metadata promotion could be honest,
but it needs a separate transition contract. Aligning the intended first RC
before exposure avoids that known mismatch and preserves strict raw parity.

## Remaining gates

This decision does not complete V6-02 or V6-06. Genuine provider execution,
independent held-out scoring, healthy native replay and later performance,
security, usability, artifact/install/license/CI and migration checks remain
required. V6-08 still requires approval of the exact publication artifacts.
No registry release or package-name ownership is implied.

Any later source/dependency change or final GA version needs its own execution
identity and acceptance. A held-out failure cannot be repaired by lowering a
target, tuning against its labels or relabelling its tape. Preserve the outcome
and obtain a fresh reviewed evaluation revision where required by the protocol.

Optional exercise: explain why matching version strings alone cannot prove that
an installed artifact contains the tested source.
