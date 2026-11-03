# Security finding remediation

Revision: CSR-CLOSE-r1. Task V6-04R-CLOSE addresses the retained Docker scanner
backlog and missing security checks before release acceptance. A scanner label
is a lead; closure requires the actual input, caller, sensitive sink and control.
For example, an operator-created SQL fixture does not establish an injection
path from a retrieval query. An unescaped query reaching SQL would require a fix.

## Shared outcome and ownership

Close every retained candidate with specific evidence, fix confirmed defects and
verify the changes. Preserve the original run and its immutable outcome artifacts;
record later dispositions as later evidence. Do not rewrite an old partial audit
as complete, blanket-suppress rules or lower severity without tracing impact.

Two Sol peers each own 124 Semgrep candidates, partitioned by file in private
assignment records. The Python peer owns the Python-runtime files and its
assigned tooling; the tools peer owns the TypeScript-runtime files and its other
assigned tooling, and ASSEMBLES. Initial writes are separate private candidate
disposition files and reports. Both do substantive source/caller analysis.
Repository implementation paths require an explicit ownership transfer from root
after a concrete fix is identified. Peers communicate dependencies directly and
may rebalance within this subsystem after agreement and a stopped prior writer.
Changes to the outcome, protected boundaries or another lane require escalation.
Unresolved material decisions go through root to Astra.

Root owns the two initially unresolved secret correlations, scanner coverage/configuration
work, dependency checks, test slot, common contracts/fixtures, documentation,
tracker and Git. Root integrates both reports and independently checks proposed
closures. Existing user source comments, tracker draft, storage guidance and
three audit drafts are protected. No peer tests, installs, services or scanners.

## Evidence and verification

Each disposition retains the original candidate ID, rule, path and line, observed
input control, sensitive operation, concrete controls, supporting source/caller
references, residual assumptions and one of: not vulnerable in the inspected
path, fixed and verified, requires fix, or unresolved. Do not publish credential
values. Use retained helper reads for original snapshot identity; keep source
redaction and scanner position differences explicit until correlated.

Fixes use small, separately owned implementation/test slices. Reproduce the
relevant failure first, preserve the failed evidence, then run focused tests and
broader affected checks. One local test/scanner process at a time; synthetic
data and fake providers unless an explicitly authorized native fixture is needed.
Check resource headroom before image/dependency acquisition. New scanner runs use
the trusted helper, immutable profiles, an early coverage submission and final
submission that excludes helper-owned scanner records before finishing.

Classify scanner parser/configuration failures separately from product defects.
Run applicable missing checks; mark a scanner inapplicable only with the actual
surface and reason, not because setup failed. Do not introduce a fake application
or root dependency file to satisfy a tool's unsupported monorepo preparation.
No live model, hosted write, new paid CI, credential/account change or package
upload is authorized by this remediation task.

## Release gate

The publication hold remains until required security work and exact replacement
artifact acceptance pass. Build and inspect corrected products locally, including
clean installed behavior where possible. External CI/account/registry permissions
and publication authorization remain separate gates. PyPI distributes the Python
packages; `pip` is the installer. npm distributes the Node packages. This contract
does not authorize uploads to either registry or claim universal safety.

## Installed security acceptance slices

CSR-CLOSE-I01 owns `tools/check_framework_artifacts.py`: explicitly stage and run
the LangChain error-disclosure and core planner security regressions against
installed wheel/npm products outside the checkout. Acceptance: existing adapter
cases plus these regressions pass, with installed-module provenance and locked
dependency checks preserved.

CSR-CLOSE-I02 owns `tools/check_qdrant_artifacts.py`: explicitly stage and run the
MCP security-abuse regressions with the existing host and Python stdio cases.
Acceptance: installed consumers pass all selected cases and all six optional
profiles in each runtime; rebuilt wheels match and temporary environments close.

The tools Sol peer owns the private I01 proposal and assembles both proposals;
the Python Sol peer owns the private I02 proposal. After both stopped, root
reviewed and applied their patches to the two repository paths. Root is the sole
integration writer and execution owner. No runtime API, dependency lock or
applied migration change is part of these slices.

The [closure report](../evaluation/reports/V6/V6-04R-closure.md) records actual
outcomes and remaining release gates. The
[earlier Docker report](../evaluation/reports/V6/V6-04R-docker-cso.md) and its
immutable scanner receipts remain historical evidence, including partial results.
