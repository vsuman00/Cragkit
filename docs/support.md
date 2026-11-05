# Support scope and safe bug reports

For example, a provider failure must remain an operational error; an empty search
result alone does not prove the provider failed. Include both the evidence status
and execution state when reporting retrieval behavior.

Cragkit supports investigation of its native Python and Node libraries and the
optional profiles documented in [development](development.md) and the
[release notes](releases/V6.md). Acceptance covers the recorded versions,
platforms and workloads. It does not establish production readiness, general
model quality, universal hardware support or an application support commitment.
There is no promised response time or service-level agreement.

The consuming application owns identity, data, access policy, hosting, provider
accounts and final answers. It creates provider clients and injects transports.
Credentials remain in trusted host-application configuration; a host application
may load its own private `.env`. Cragkit does not load `.env` or supply a shared
key. Routine synthetic reproduction needs no live provider or development key.

## Report a reproducible problem

The repository is public for testers and contributors. Use the
[bug report form](https://github.com/vsuman00/Cragkit/issues/new?template=bug_report.yml)
for a reproducible non-sensitive problem. For setup, start with the
[README quick start](../README.md#quick-start); for a patch, follow
[contribution guidance](../CONTRIBUTING.md). Issues and pull requests are public.
GitHub private vulnerability reporting is not enabled; use the private-exchange
guidance below for suspected security issues.

Include:

- Exact package/version, Python or Node version, OS/architecture, optional profile
  and database/driver/model/tokenizer versions where relevant. Distinguish a
  registry install from a checkout, and record the import origin.
- One small synthetic document/request, trusted-scope shape and required-filter
  shape using invented identities. Include the commands and configuration fields
  needed to reproduce it, without real values or credential-bearing URLs.
- Expected behavior and actual behavior separately, stable error code, evidence
  status, execution state and whether fallback was enabled. State whether the
  result came from a fake provider, native backend, live provider or installed
  package. Include a failing test or minimal example when available.
- Redacted diagnostics, frequency and last known working version. Preserve exact
  synthetic UTF-8 bytes/spans for a fidelity bug; private source text is not a
  suitable substitute for a shareable fixture.

Never attach keys, tokens, passwords, `.env`, raw provider errors, private queries,
source documents, database dumps or unreviewed logs. Private repositories and
issue attachments are still disclosures. For a suspected authorization bypass,
credential exposure or other security issue, stop sharing the real payload;
request a trusted private exchange through an established maintainer contact.
No public security inbox or formal coordinated-disclosure service is claimed.

## Triage and follow-through

The maintainer first checks reproduction and affected contract, then separates
an invariant failure from configuration, an unsupported profile or a quality
limitation. Unknown coverage cannot become sufficient; operational errors cannot
be relabeled missing evidence. A source-linked excerpt does not establish truth.
Record the disposition and evidence without promising a fix date.

Use [contribution guidance](../CONTRIBUTING.md) for a patch and the
[maintenance checklist](maintenance.md) for regression, release and communication.
A new corrective release may be needed for broken published bytes; replacing a
local archive does not repair an installed published version. Report workarounds
with their limits and never suggest dropping required filters or broadening
access as recovery.
