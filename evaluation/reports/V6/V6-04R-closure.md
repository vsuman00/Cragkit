# V6-04R security finding closure

4 November 2026. All 258 retained scanner candidates and 11 later history-scan
occurrences have an inspected disposition. None establishes an unresolved product
vulnerability in the reviewed paths. Two installed-artifact test-selection gaps
were fixed and verified. Local replacement-product acceptance passed. Publication
remains on hold for replacement candidate CI, release-packet review and registry
gates; this is not a completed production assessment or security certification.

For example, `replay_key` looks like authentication material to a generic secret
rule. Here it is a SHA-256 identity computed from a provider request and compared
with an ordered synthetic recording. An actual provider credential in that field
would require a different disposition and exposure response.

The [verification record](V6-04R-closure-verification.json) binds commands,
scanner provenance, source identity, acceptance receipts and twelve archive
hashes. The [candidate ledger](V6-04R-dispositions.json) retains every original
ID, rule, location, control, evidence reference and residual assumption. The
[remediation contract](../../../contracts/SECURITY_FINDING_REMEDIATION.md) records
ownership and acceptance. Older reports and frozen release receipts remain intact.

## Retained findings and legacy reports

| Inventory | Inspected outcome |
| --- | --- |
| 248 Semgrep leads | Two Sol peers reviewed 124 each, partitioned by file. The tools peer assembled; root reconciled all IDs and independently inspected product SQL, regular expressions, subprocess and digest controls. No confirmed injection or other product defect remained in these occurrences. |
| Eight Gitleaks leads | Five tokenizer digests, one synthetic owner token, one prose occurrence and one synthetic authorization revision. No authentication secret at the cited occurrences. |
| Two zizmor informational leads | Fixed `npm@11.17.0` installs with `--ignore-scripts`; no caller-selected version or shell interpolation. This does not certify registry/toolchain bytes or arbitrary operator configuration. |
| Eleven native Git-history leads | Eight correspond to the reviewed fields, prose or fixtures; three additional `replay_key` occurrences are deterministic request digests in a synthetic replay fixture. All have historical commit/blob identity and unchanged current-line correlation. |

The two previously unresolved secret matches were correlated exactly, rather
than inferred from nearby text. Full retained helper output, minus exactly one
CLI-added terminal newline, matches each scanned execution hash. The tracker
start lies inside `API2` prose; the schema probe start lies inside a six-character
authorization-revision fixture literal. Astra independently challenged and
confirmed those interpretations. This establishes neither a match between the
entire unredacted tracker and sanitized snapshot nor universal secret absence.

SQL leads use parameter tuples for data and fixed or quoted code-owned syntax.
The dynamic writer helper's table/column/key inputs were traced through callers;
they are not arbitrary request dictionary keys. Regular-expression separators
and character classes are disjoint; the dynamic fence pattern accepts only the
two fence characters and a numeric repeat count. Subprocess tools use argument
arrays, ownership/target checks and explicit operator configuration. Operator-
chosen executables and installed callbacks remain trusted code. Compatibility
SHA-1/MD5 checks follow exact size and SHA-256 checks; they are not the security
authenticator. Owner-only directory mode `0700` is intentional.

The protected V1, V2 and V2-V4 audit drafts were reviewed without editing them.
Their concrete claims are superseded by later scoped fixes and current guards:
mandatory host write authorization before parsing/leasing, NUL rejection,
restricted writer privileges, integrity-error mapping, vector capability checks,
privileged-role rejection, locale preflight, independent SQL hardening checks,
and bounded ownership-aware cleanup with safe diagnostics. The V1 draft's
proposed document-grant query is not the implemented write policy: the trusted
host must supply `authorize_write` and return exact `True`. Historical default-
deadline failures remain failures; their original cleanup cause is not invented.
Hosted, pooled and production requests in those drafts retain their own scopes.

## Scanner coverage and honest limits

Fresh helper run `1793738033708-d7614cea083ffbf1` finished successfully as
**partial**, with accepted initial/final manual domain records. Manual submission
excluded helper-owned scanner domains. Source execution snapshot:
`a8499020b9ed757aa556c30f22891d4fd7fcc2228c15b09ac539468e0cd2b539`.
All eleven qualified scanner images were available after controlled provisioning.

| Actual check | Result |
| --- | --- |
| Qualified OSV 2.6.0 | Complete selected-source pass, zero candidates; offline database dated 4 October 2026. |
| Qualified Trivy 0.75.0 | Complete selected-source pass, zero candidates; offline database dated 4 October 2026. |
| Qualified Gitleaks 8.30.1 | Complete selected-source directory pass, zero candidates. This narrower source selection does not negate the earlier full-snapshot leads. |
| Qualified Semgrep 1.179.0 | Partial with parser/rule/execution error; 37 candidates, all matching reviewed retained IDs. The partial outcome is preserved. |
| Separate native Semgrep, shipped source | Same version and byte-identical 1,433-rule asset: exit 0, 37 reviewed candidates, no parser errors. |
| Separate native Semgrep, implementation/operator code | Exit 0, 332 files, 244 candidates, no parser errors. Every candidate matches a retained disposition. Four retained JSON-report digest leads lie outside this code scope. |
| Separate native Gitleaks Git scan | `--all`, redaction 100%, allow comments ignored, empty ignore file. 231 locally reachable commits; scanner reports 205 patch commits and about 15.34 MB scanned. Exit 1 means eleven candidate leads, all reviewed, rather than a zero-finding result. |
| Fresh native dependency audits | Three npm locks and four uv locks: zero known vulnerabilities/adverse statuses reported; all seven lock hashes unchanged. |

The native Semgrep asset was reproduced from the qualified image's pinned rule
source and curation recipe. Its asset SHA-256 is
`2b00d88982338e907f66dd8c1d60c791dff64a5a8ea51e9dca8c5958c51b0502`.
It ran with one worker, local rules, metrics/version checks off, and no cloud
analysis. Two earlier broad explicit-file invocations timed out at 420 and 240
seconds and were terminated. Those are retained failures, not clean scans. The
bounded directory-discovery run then completed in 83.441 seconds. This separate
native engineering result does not repair or relabel the CSO container result.

Native Gitleaks used the [official 8.30.1 release](https://github.com/gitleaks/gitleaks/releases/tag/v8.30.1),
with downloaded ARM64 archive size and SHA-256 verified against the release API
digest. Its [documented Git scan](https://github.com/gitleaks/gitleaks/blob/v8.30.1/README.md)
is patch based. It covers local reachable refs, not unreachable objects, external
forks, remote caches or arbitrary nested binary archives. No credential values
are included in committed findings.

Qualified runtime preparation remains unsupported for the selected monorepo:
the root preparer expects a nonexistent root requirements file, nested Python
locks need a qualified platform export, and qualified Node 24.4.0 differs from
supported Node 26.5.0. No fake manifest/server or weakened engine constraint was
added. No authenticated CSO runtime witness was produced. Schemathesis has no
applicable HTTP/OpenAPI endpoint in the native/local-stdio library; an HTTP
consuming application requires its own deployment assessment. These limits
prevent an unqualified completed-CSO-audit claim.

## Fixed installed-product verification gaps

CSR-CLOSE-I01 adds the existing LangChain error-disclosure and core planning
security tests to `check_framework_artifacts.py`'s explicit installed test set.
CSR-CLOSE-I02 adds the existing MCP security-abuse tests to
`check_qdrant_artifacts.py`. Missing selected files now fail staging. Tests execute
outside the checkout against installed products, with module-origin, dependency
identity, tokenizer/fixture inputs and cleanup checks preserved.

| Actual validation | Result |
| --- | --- |
| Focused artifact-tool tests | 10 passed. |
| Publication admission regressions | 43 passed after the hold explanation update; hold remains true. |
| Full Python core/tool checkpoint | 4,377 passed, no skips; four existing Pydantic warnings from deliberately bypassed invalid models. |
| Core clean artifact acceptance | Passed guarded imports, 216 evidence fixture cases and 44 execution/planning/corrective/event fixture cases across native installed consumers. |
| LangChain plus core security, installed | Python 120 passed; Node 112 passed. |
| MCP host/stdio/security, installed | Python 54 passed; Node 42 passed. |
| Optional installed profiles | Core, PostgreSQL, Qdrant, authoritative Qdrant, tokenizers and MCP passed in both runtimes: twelve profiles. |
| Native PostgreSQL security guard | 23 checks passed; proof is same-transaction SQL guard only; cleanup verified. |
| Twelve archives | Three direct wheels, three sdists, three rebuilt wheels and three npm tarballs inspected. License/notices, paths, metadata, exports, rebuild equality and relevant lock identities passed. |
| Selected credential-pattern inspection | One reserved-domain dummy-credential URL in an invalid-endpoint rejection test; inspected and closed. No unresolved pattern candidates. |

Products came from a clean tracked-source export of `a188957`, package tree
`63dafe3b3906778e456b1cd2aefb7f99cd896e43`, with only the two reviewed checker
overlays. The eight user-edited source files and storage guidance were preserved
and excluded from that export. All three npm products remain private. Historical
6,333-test acceptance is separate earlier evidence; the table records this task's
actual checks without adding overlapping cases into a misleading unique total.

Temporary consumer environments and the task-owned PostgreSQL process closed.
Disk was 18 GiB before and 16 GiB at the checkpoint; system memory free was 38%
and 40%. One scanner/test/install process ran at a time. Native scanner tools and
raw reports remain in private local directories. No live model call, hosted
database mutation, new paid CI or registry upload occurred.

## Release decision and next action

Known retained findings are closed for the inspected occurrences, and local
replacement-product security acceptance passed. The
[publication hold](../../release/V6-publication.json) stays true. Its old manifest,
transport pins and immutable V6-08 receipt were not rewritten to fit new products.

Next: freeze the corrected candidate, obtain separately authorized candidate CI
for that identity, then review its replacement packet and hold removal. Registry
owners, namespace/permissions, publication authorization and actual registry
download/install/source smoke remain separate required gates. V6-08D, V6-09/C3,
version exit and consuming-application production acceptance remain incomplete.
No old paid-job approval carries forward to a new run.

An installed plugin executes trusted code with the consuming process's access;
Cragkit does not sandbox it. Host identity, current grants, ingress quotas,
provider disclosure/keys, logging, backups and deployment patching remain in the
[production guide](../../../docs/production-security.md). A failure to rehearse:
a callback that lies about authorization can defeat the host's policy even when
all library schemas validate. Optional exercise: explain which reviewed SQL
value is data and which syntax fragment is constrained by code-owned callers.
