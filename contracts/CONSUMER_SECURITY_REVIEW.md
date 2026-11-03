# Consumer security reassessment

Revision: CSR-r1. Task V6-04R reopens the implemented-boundary security review
at the user's request on 4 November 2026, before publication/deployment setup.
It supplements the historical V6-04 report; it does not replace release gates
or authorize publication, paid CI/model calls, cloud changes or third-party
penetration testing. The current checkout and frozen RC products retain separate
identities. Confirmed product fixes invalidate old artifact readiness until
their exact replacement products pass the applicable release checks.

## Assets and trust boundaries

| Boundary | Attacker action | Required protection |
| --- | --- | --- |
| Tool arguments to framework/MCP host | Forge tenant, grants, filters, limits or provider configuration | Narrow schema; trusted scope/template bound by application; reject before engine entry. |
| Query/source/provider data to engine | Inject SQL, commands, tool directives, invented IDs or malformed values | Parameterized/scoped searches; data stays data; validate output and source digests/spans. |
| Engine to storage/source release | Read foreign/revoked/tombstoned sources or stale grants | Required filters and current authority checked at search and release; least-privilege roles. |
| Error/diagnostics to tool/logs | Force secret-bearing messages, causes, properties or protocol frames into output | Fixed public errors, bounded/redacted diagnostics, safe serialization and frame limits. |
| Requests to runtime resources | Flood, hold, cancel, disconnect, oversize or malformed input | Bounded admission/bytes/deadlines; cleanup without late release; no fabricated successful result. |
| Locked dependencies/artifacts to consumer | Exploit known advisory, substituted bytes, hooks or leaked credentials | Native lock audits, reachability triage, guarded exact products, scoped secret scan. |
| Consuming application to production | Bind attacker-supplied scope, expose local stdio as a public service, run admin credentials | Explicit host/deployment ownership and configuration checks; do not claim the library authenticates or sandboxes the application. |

The library executes in its host process. Arbitrary malicious installed plugins
and caller-owned callbacks are trusted code with that process's privileges;
Cragkit is not their sandbox. Retrieved text may still influence a consuming LLM;
source fidelity does not establish truth or eliminate prompt injection in that
application. There is no universal "unhackable" or future-vulnerability claim.

## Managed peer pair

Shared outcome: reproduce consumer-visible plugin abuse cases in both native
runtimes, identify actionable gaps with exact source locations/reproductions,
and provide evidence for fixes and deployment prerequisites. Sol Python owns
`packages/mcp-python/tests/test_security_abuse.py` and ignored
`artifacts/security-review-2026-11-04/python-findings.md`. Sol Node owns
`packages/mcp-typescript/tests/security-abuse.test.mjs` and ignored
`artifacts/security-review-2026-11-04/node-findings.md`; Node ASSEMBLES.
Both review their native core, provider, framework and MCP paths read-only.
Root owns this contract, test slot, dependency/release/SQL review, final report,
deployment guide, tracker and Git. Existing dirty source/doc/audit files are
protected. Peers must not edit product code, existing tests, locks or shared files.

Use official SDK consumers and actual stdio/framing/process boundaries where
practical, with only synthetic documents, fake engines/providers and task-owned
processes. Tests must demonstrate an observable invariant, not mirror private
implementation. Add cases that materially extend existing host/stdio tests;
avoid copying the entire old suite. Read those tests first. No services, installs,
tests, providers or live registry calls by peers. Root runs one suite/process at
a time, grants bounded local native fixtures only after checking headroom, and
preserves failed evidence before the smallest correction.

Review targets: rejected hidden scope/filter/limit/provider fields with zero
engine calls; query/source SQL/shell/prompt payloads remaining inert data;
unknown/declared error canaries and malformed engine output; duplicate/native
JSON/prototype/frame abuse; output framing and diagnostics exclusion; bounded
concurrent admission and cancellation/disconnect with no late source release.
Distinguish client/SDK rejections from library authorization and real storage
enforcement. Existing source/row-security tests remain required evidence.

Peers communicate concrete dependencies directly. Agree transfers before edits,
stop the old writer and notify root. Report outcome/protected-boundary changes
before dependent work. Unresolved material decisions go through root to Astra.
The assembler inspects both lanes; only root can accept integration. Apply the
self-contained prose workflow to findings and reader-facing text.

Implementation ownership after the reproductions: CSR-A2 covers the two planners
and their two new tests; CSR-B2 covers the two LangChain adapters and their two
new tests. The original writers explicitly stopped and transferred those paths
to root for final integration. CSR-R2 gives Sol Node the policy, admission tool
and guard tests; CSR-D1 gives Sol Python the new production security guide, with
Node assembling. Both follow-up writers stop before root acceptance. Root owns
CSR-D2 report/verification, linked guidance, tracker, execution and scoped Git.
The independent Astra challenge is read-only and cannot authorize publication.

## Acceptance and reporting

Root derives a scoped attack/evidence matrix, runs meaningful new and existing
regressions serially, triages current native dependency audit results by severity
and reachability, and fixes confirmed issues without relaxing the invariants.
Recheck affected artifacts and source identity if product bytes change. No high/
critical reachable finding is silently deferred or relabelled as harmless.
Unverified behavior and deployment-specific controls remain explicit gaps.

Report commands, source/artifact identity, new findings and corrections, actual
passes/failures, residual risks and unsupported modes. Include practical consuming
application production checks: identity binding, separate runtime/admin roles,
TLS, provider disclosure/secrets, ingress/global quotas, backups/current-authority
recovery, redacted logs, patch/advisory monitoring and release rollback. Map
controls to their actual owner; do not invent a hosted web service or configure
an unspecified production target. Public registry accounts/publication and
post-publication smoke remain separate existing gates.
