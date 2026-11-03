# Production security for consuming applications

For example, a signed-in user's session resolves to tenant A and its current
grants. The application binds that scope before retrieval. A tool request asking
for tenant B is rejected; query text never chooses the tenant or grants.

No active production target has been assessed or configured. This guide assigns
deployment work to the consuming application's operator. Local tests, database
development acceptance, hosted candidate CI and a production deployment are
separate evidence. See the [finding closure](../evaluation/reports/V6/V6-04R-closure.md)
for the current findings, commands, corrections and remaining gaps.

## Keep the corrected release on hold

The [publication policy](../evaluation/release/V6-publication.json) uses an
explicit boolean `security_hold`. While it is `true`, publication admission must
fail before environment, asset or upload checks. Missing or malformed hold state
also fails closed. Environment flags and the old candidate's passing receipt do
not clear this hold.

Corrected source bytes require new acceptance. Preserve old source identities,
artifact hashes and receipts as historical evidence; do not change their pins
to make corrected bytes appear covered by an earlier run. Before reviewing hold
removal, freeze the corrected source, run the affected security and compatibility
checks, build exact replacement products, and verify their hashes, contents,
clean installs and applicable candidate CI gates. Record any required check that
has not run as pending. The earlier candidate's CI result does not validate a
replacement artifact.

Removing a hold is a reviewed release decision. It does not authorize a new
paid CI run, registry/account setup, publication, public release or production
deployment. Registry publishing remains unauthorized. Follow the
[publication procedure](publication.md), [release guide](releasing.md) and
[tracker](../tasks/todo.md) for those separate gates.

## Bind authority in the host

The application authenticates the caller, resolves its current principal,
tenant, grants and authorization revision, then binds a trusted scope outside
agent-editable input. Bind required filters, collection policy, limits and
provider configuration through the supported host/template APIs. Do not merge
HTTP request bodies, model output or tool arguments into that trusted state.
Re-resolve authority as sessions and grants change; a scope snapshot is not an
identity service or permission to reuse stale grants indefinitely.

Use native runtime-role checks and allowed/foreign/revoked/tombstoned source
tests before admitting real data. Searches must apply the trusted scope and
required filters before candidate limits, and source release must recheck
current authority. The [architecture](architecture/ARCHITECTURE.md#11-failures-privacy-and-operational-controls)
and [operations guide](v5-operations.md) define the library's part of that
boundary. The supported MCP transport is local stdio; it supplies no public
HTTP endpoint, authentication gateway or shared user identity resolver.

## Assign operational controls

| Control | Owner and required evidence |
| --- | --- |
| Database authority | The application/database operator provisions separate migration/admin, ingestion and retrieval credentials. Test actual runtime logins, memberships, row policies and default denial. Never run retrieval as an owner or RLS-bypass administrator. |
| Verified transport | The operator validates the actual database endpoint's certificate and hostname. PostgreSQL uses `verify-full`; native Node connections require equivalent certificate/hostname checks. Reject verification errors without downgrading. Pooling and each new target require their own acceptance. Follow the [Neon runbook](neon.md) for its development profile; that profile does not approve production. |
| Provider disclosure and secrets | Each consuming project selects allowed providers, endpoints, data disclosure and spend policy. Configure its own keys through private environment/configuration or a secret store. Cragkit supplies no built-in provider key and does not load `.env` automatically. Never accept provider credentials or endpoint changes from a query, and never commit keys or credential-bearing DSNs. |
| Logs and diagnostics | The application controls log sinks, access, retention and redaction. Keep raw query/source replay off unless explicitly reviewed. Inspect exceptions, causes and exported records with synthetic canaries. Keep broad SDK DEBUG logging off by default: SDK protocol-method diagnostics can include caller-controlled text. Do not assume fixed public tool errors sanitize arbitrary application logs. |
| Admission and tenant fairness | The application/ingress operator bounds request bytes, pending work, concurrent sessions, per-tenant load and provider expenditure across processes and instances. Apply global rate/spend quotas and tenant fairness outside Cragkit's per-request limits. Test overload, caller cancellation, disconnect and drain without late source release. Reuse bounded pools and clients. |
| Recovery | The operator protects backups and rehearses recovery in isolation. Before reopening traffic, apply independently current grants, revisions and tombstones. If current authority is unavailable or uncertain, keep the restored target quarantined. An old backup or package rollback must not restore revoked access. Follow [migration and recovery](migrations-and-recovery.md). |
| Patching and release identity | Maintainers monitor native dependency advisories and investigate severity and reachability; application operators monitor their own host, runtime and added plugins. Retain exact package/source identity, lock/audit results and a reviewed rollback target. A historical passing audit cannot establish that later dependencies or products are safe. |

## Treat source text as data

A retrieved document can contain "ignore prior instructions" or a genuine quote
with an incorrect claim. Preserve its exact source link and bytes while keeping
authority in the host. Source fidelity proves neither truth nor relevance, and
does not prevent a consuming LLM from following injected instructions. The
application owns final-answer policy, tool permissions and any additional
content handling.

Installed plugins, serializers, provider callbacks and framework extensions run
as trusted code in the host process. Cragkit does not sandbox them. Review their
access to files, credentials, network and execution facilities before installing
or enabling them; retrieval validation is not an isolation boundary for that
code.

## Record what remains unvalidated

The first CSO run was partial with unavailable Docker/scanners and an unsubmitted
assessment. After Docker started, the
[fresh follow-up](../evaluation/reports/V6/V6-04R-docker-cso.md) recorded its
application model, completed Gitleaks and zizmor scans, and partial Semgrep
coverage. The later [closure](../evaluation/reports/V6/V6-04R-closure.md) accounts
for all retained candidates, adds complete native source parsing, fresh dependency
and Git-history checks, and verifies local installed replacement products. A
fresh qualified helper run completed OSV, Trivy and selected-source Gitleaks;
its Semgrep and overall result remain partial. Runtime preparation is unsupported
for the selected nested locks/toolchain. Native tests are separate evidence.
Do not describe these partial helper runs as completed security audits.
Deployment-specific identity, ingress, secrets, logging, recovery and operational
controls still require assessment on the selected application target. No
universal safety claim or security certification follows from this guide.

One failure to rehearse: restore a backup containing a revoked grant while the
current authority service is unavailable. The application must remain closed to
that source. As a small exercise, identify which operator can establish current
authority before restoring traffic.
