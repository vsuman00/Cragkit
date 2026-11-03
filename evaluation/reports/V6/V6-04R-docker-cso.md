# V6-04R Docker-backed CSO follow-up

Historical snapshot. The later [closure report](V6-04R-closure.md) resolves the
retained candidate backlog and records additional scans and local installed
acceptance. The partial results and unresolved-at-the-time statements below
remain the original run's evidence.

Partial, 4 November 2026. Docker-backed security scans now have actual results;
this is not release or production acceptance.

Status: partial. Ran: Gitleaks and zizmor completed; Semgrep completed partially;
the fresh application model and static domain coverage were submitted. Reason:
Semgrep reported parser/rule/execution errors, its candidates still need triage,
two secret-candidate correlations remain unresolved, and application runtime
preparation is incompatible with the current monorepo layout. Next: triage the
retained candidates against exact source and controls, address the scanner
coverage errors, then run the remaining applicable checks in a new bounded run.

For example, a scanner can flag a tokenizer SHA-256 value as an API key because
of its field name and shape. That is a lead to inspect, not proof of a leaked
credential. A query-derived value reaching a SQL command without parameterization
would need a different investigation: trace the value, caller and effective role.

The [verification record](V6-04R-docker-verification.json) binds source identity,
catalog/image provenance, outcome IDs, candidate counts, coverage and limitations.
The earlier [native engineering report](V6-04R-consumer-security.md) remains
historical evidence for its 6,333 passing tests and 23 SQL security checks.
Those tests were not rerun or relabelled as CSO runtime evidence here.

## Docker and controlled setup

The trusted CSO doctor verified local Docker 29.9.2 with seccomp and cgroup
isolation available. Controlled image provisioning acquired ten of eleven exact
qualified Linux/ARM64 images. Trivy 0.75.0's image exceeded the 45-second download
limit. No floating image substitution or direct host scanner was used.

Disk headroom decreased from 16 GiB to about 6.8 GiB during setup. Further image
downloads stopped; existing images were used with one scanner process at a time.
Initial system memory free was 39%. No model or application dependency download,
live provider request, cloud mutation, paid CI run or package publication occurred.

The monorepo owns nested Python manifests/uv locks and Node manifests/locks.
The CSO application preparer instead selected a root Python `requirements.txt`
that does not exist. No fake root file, loosened lock or artificial application
server was introduced to bypass preparation. Schemathesis also has no selected
HTTP/OpenAPI target for the supported local stdio library integration.

## Actual scanner outcomes

| Scanner | Recorded result | Candidate leads and scope |
| --- | --- | --- |
| Gitleaks 8.30.1 | Complete directory pass | Eight generic API-key candidates. This pass does not scan historical revisions; snapshot transformations still apply. |
| zizmor 1.30.1 | Complete workflow pass | Two informational ad-hoc package-install candidates. |
| Semgrep 1.179.0 | Partial, with `TOOL_FAILED` coverage gap | 248 candidates: 214 reported high, 25 medium, 9 informational. These are scanner labels, not validated exploit severities. |
| OSV | Not run | Available image; remaining bounded audit time reserved for triage and finalization. Previous native dependency audits remain separate evidence. |
| Trivy | Not run | Exact image download timed out; further downloads stopped at reduced disk headroom. |
| Schemathesis | Not run | No qualified prepared application or applicable selected HTTP/OpenAPI target. |

The Semgrep backlog includes 161 raw-query leads, 37 asynchronous subprocess
leads, 15 other subprocess leads and 35 other leads, including secrets, regular
expressions, permissions and dynamic operations. A constant SQL statement or
operator-owned executable path may be safe, but no blanket false-positive closure
has been applied. Prioritize production source paths and actual attacker-controlled
data flows, then review fixtures and operator tooling. High scanner labels remain
an open review concern until their controls and impact are established.

Immutable helper outcome identities:

- `gitleaks-5e28f8311f85ad73-039aed87fe121a5c`
- `zizmor-d2c687983071dd4d-f95c73c1e7507c32`
- `semgrep-2942e5c0625daf6e-5a8d84cae01a79ce`

## Triage and independent challenge

Two Sol peers performed complementary read-only reviews through the helper.
The release peer assembled their application-boundary and publishing evidence.
Root inspected that assembly, the native embedding adapters and two scoped SQL
candidate queries. Peer success was not treated as whole-system acceptance.

Five Gitleaks candidates identify tokenizer integrity digest fields/constants.
One is a synthetic owner-token argument in a fake-state test fixture. Those six
classifications disclose no candidate values. Two exact correlations remain open:

| Retained candidate location | Disposition |
| --- | --- |
| `tasks/todo.md:1175` | Redacted/large tracker output did not establish the exact scanner match. Nearby prose is insufficient to close it. |
| `tools/qdrant_publication_schema.py:414` | Synthetic transaction-probe context is counterevidence, but the exact matched occurrence was not correlated. |

Astra independently challenged this unresolved decision and agreed that neither
candidate should be closed from neighboring synthetic/prose context alone.
There is no confirmed live credential exposure, and no supported high-severity
finding follows from these two candidates. Their security significance remains
unestablished. No credential was printed, tested against a provider or rotated
as a side effect of scanner triage.

Both zizmor locations install fixed `npm@11.17.0` with `--ignore-scripts`.
Source review found no attacker-selected version or shell interpolation in those
steps. The publishing security hold precedes that install. This does not establish
the safety of downloaded npm implementation bytes or every effective registry/
configuration input; those supply-chain limits remain explicit.

## Persisted audit and recording limits

Fresh run: `1793736056579-06b263c519e5f9fd`, source commit
`671cc2c5fbb82e9779759f8b4bcf0e78b03be501` plus the preserved dirty checkout and
the new assignment handoff. Sanitized snapshot SHA-256:
`521d7e051eddfb1b2248ec1505646b4d3ccae121f69d43a0d66bef52d4d5c887`.

The helper accepted the initial application model and all twelve assessment
domain records. Three scanner outcome artifacts were persisted separately by
the helper. The run then finished as partial. Its private report is:
`~/.gstack/security/cso/e7ac09bf7e97c728f9f0310d/1793736056579-06b263c519e5f9fd/report.md`.

The final enrichment submission mistakenly included helper-owned scanner rows
and was rejected with `INVALID_SCHEMA: Coverage domain is helper-owned:
scanner:gitleaks`. One correction after finalization was rejected with
`INVALID_SCHEMA: Only a running audit accepts evidence`. The initial submission
and immutable scanner outcomes remain saved. Post-scan classifications and
unresolved candidates are recorded in this companion report and its verification
record; they are not retroactively accepted helper domain updates.

Nine binary inputs remain withheld, and history is bounded to the newest ten
of 100 selected commits. Static reads, redactions, directory scanning and partial
parser coverage do not establish complete historical-secret or source coverage.
No application runtime reproduction or authenticated runtime bundle was produced.
No new supported exploit was established in the reviewed paths; the untriaged
backlog prevents treating the empty supported-findings list as a clean audit.

## Release gate and next work

The [publication policy](../../release/V6-publication.json) retains
`security_hold: true`. Registry setup, corrected-source refreeze, exact replacement
artifact acceptance, authorized candidate CI and production-target checks remain
separate gates. No hold removal or universal safety claim follows from running
Docker. Use the [production security guide](../../../docs/production-security.md)
for application-owned identity, logging, quotas, secrets and recovery controls.

Next smallest task: group the 248 retained Semgrep candidates by rule and call
site, trace production SQL/subprocess/regular-expression inputs first, and
independently challenge each proposed disposition. Correlate the two unresolved
Gitleaks occurrences without exposing credential values. Then address the
Semgrep coverage error and remaining applicable scanner/runtime prerequisites.
Do not install more images until disk headroom is reviewed. Do not delete
unrelated files or use global Docker pruning to make space.

Learning exercise, unassessed: explain why an owner-only directory mode and a
fixed SQL command might attract scanner warnings without proving a vulnerability,
then identify the additional attacker-control evidence each case would need.
