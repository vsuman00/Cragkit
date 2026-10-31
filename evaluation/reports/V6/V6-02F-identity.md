# RC identity and local artifact preparation

V6-02F local preparation checkpoint: PASS. Clean source/runtime preparation is
still pending the source commit, preregistration refreeze and isolated checkout.
This does not complete V6-02 or the later V6-06 release gate.

For example, a result parsed from an older recording may still declare engine
`0.0.0`. A newly built RC must declare `1.0.0-rc.1`. Accepting historical wire
identities does not permit relabelling a prototype archive as the current RC.

## Decision and implementation

[ADR0005](../../../docs/decisions/0005-release-candidate-identity.md) explicitly
moves RC identity preparation before original held-out access. The six library
manifests and internal pins use Python `1.0.0rc1` or npm `1.0.0-rc.1`. Both
native engine defaults/emitters and MCP server identities use `1.0.0-rc.1`;
the result schema remains `0.1`. Shared fixtures include historical explicit
engine acceptance and the updated native retrieval expectations.

Sol peers implemented separate Python and TypeScript core paths, coordinated
wire identity directly and returned their work to root; Node assembled the pair.
Root integrated shared contracts/schema/fixtures, metadata/locks, adapter server
identity, artifact guards, import probes, admission checks and final tests.
Third-party dependency records are unchanged across all seven lock workspaces.
Private npm status and publication authorization were preserved.

Independent final review found two defects. The development guide still deferred
metadata to V6-06; root corrected it. The runtime gate also executed existing
Node output before its fresh-build comparison. Root moved export verification
after complete emitted-set equality and executes only scratch-compiled output.
Regression tests verify that stale output never reaches export execution and
that the scratch export must equal the declared candidate. A real scratch
compilation matched all 100 emitted files and exported `1.0.0-rc.1`.

## Actual verification

| Check | Actual result |
| --- | --- |
| Initial core identity integration | 3,614 Python/tool and 1,617 Node tests, both typechecks/build, schema export/drift, 33 shared result and 17 corrective cases passed |
| Complete local core/SDK pipeline | All 34 stages passed; 3,616 Python/tool, 1,617 Node, 73 Python / 70 Node LangChain tests and clean installed artifacts passed |
| Artifact/version guard focus | 94 tests passed |
| Final runtime/parent correction | 84 tests passed; final complete Python/tool suite passed 3,620 with four deliberate malformed-model serializer warnings |
| Optional artifact/install profiles | Twelve isolated profiles passed, including 41 Python / 36 Node installed MCP tests; temporary environments cleaned |
| Actual native backend routes | 84 direct/LangChain/MCP calls and 16 boundary refusals passed with cross-runtime parity; cleanup verified |
| Actual five-mode RC development run | 120 rows per runtime, nine receipts each, complete parity and same-shortlist comparisons passed; cleanup verified |
| Node evaluation/replay tools | 65 tests passed without skips |
| Frozen inputs | Six release input digests and all 16 sealed files verified; benchmark bytes unchanged |

Root inspected all 240 mode result wires and 28 retained backend case wires:
every engine identity is the common RC value. The independent artifact peer
verified twelve archive hashes/sizes, 53 archived Python modules against current
sources and 104 npm emitted files against local output. It inspected 85 successful
artifact command records; those inspections are separate from root's fresh
execution. The initial load-only `check_retrieval.py` invocation produced no
native evidence and is not counted as a native retrieval check.

[Structured verification](V6-02F-identity-verification.json) binds actual commands,
logs, local artifacts, source snapshots, dependency integrity and limitations.
Raw evidence lives under ignored `artifacts/V6/V6-02F/`. Native retrieval uses
fake profiles and the original approved development split: no original held-out
interpretation or provider request occurred. Fake metric deltas are harness
checks, not model-quality results.

## Remaining work and preservation

The next step is to commit the coherent source, update only preregistration
source identities, and prepare an isolated checkout with its own frozen
installation, fresh build and pinned tokenizer. ECR must then pass actual
prepare/verify before secure provider setup and genuine held-out execution.
The current historical source identity is not silently treated as current.

Local archive checks used the inspected working tree, including pre-existing
user prose. That prose stays outside the scoped commit. These archives are local
preparation evidence and must not be published or represented as exact clean
candidate bytes. V6-06 still rebuilds/audits exact artifacts, notices, supported
installations and actual CI evidence after the earlier version gates.

Root reversed only the intended RC identity edits in memory and verified that
all nine original user-owned files otherwise retain their original hashes.
Unrelated source/prose, audit reports and the old tracker draft remain protected.
README banner, section order, status table, callouts and collapsible guide remain
intact. Existing caches were not deleted. Runs were serialized on the declared
small-machine configuration, with no persistent service or model installation.

Optional exercise: explain why checking a generated export before verifying its
source can execute unwanted code even when the eventual comparison rejects it.
Learning practice remains unassessed.

## First clean-environment attempt

The isolated checkout passed committed-source verification, then refused runtime
preparation before producing a receipt. Diagnosis identified npm's exact error:
it rejects loading `/dev/null` as both its user and global configuration file.
The gate now creates two distinct empty owner-only files in a private temporary
working directory and cleans them afterward. The real npm probe reports 11.17.0;
85 runtime/parent tests and the full 3,621-test Python/tool suite passed after the
fix. Four deliberate serializer warnings remain unchanged.

A separate clean inventory preflight passed 9,411 files / 340,528,782 bytes with
no checkout bytecode, within the existing bounds. That inventory is prerequisite
evidence, not a combined runtime receipt. Source refreeze and actual ECR
prepare/verify are still required. No package-tree, target, label, model or
provider change was made to fix this environment probe.
