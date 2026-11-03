# V6-04R consumer security reassessment

Partial overall, 4 November 2026. Scoped native engineering acceptance passed;
the CSO assessment, replacement release artifacts and production deployment
assessment remain incomplete. This report does not certify that Cragkit or an
application using it is unhackable.

For example, a query containing a forged JSON-RPC request remains query/source
text. It cannot replace the host's tenant or grants. A malicious installed
callback already has the host process's privileges; retrieval validation does
not sandbox that code.

The [CSR-r1 contract](../../../contracts/CONSUMER_SECURITY_REVIEW.md) defines
the scope. The base commit was `bdb4bd7a33c64b982f338cc6523f69b9c26b45f0`.
The [verification record](V6-04R-verification.json) binds commands, source hashes,
test counts, dependency observations and local archive identities. Existing
user-owned prose edits and audit drafts were preserved and excluded from this
change's staged source. Python AST comparison excluding docstrings and Node
comparison excluding JSDoc distinguish those edits from the implemented fixes.

## CSO result and limits

Status: partial. Ran: sanitized snapshot and bounded history capture, helper
source reads and an independent static boundary challenge. Reason: Docker and
qualified scanner/runtime profiles were unavailable; the run closed without
an assessment submission. Its saved application model is empty and its twelve
assessment domains remain `not_assessed`. Next: use the trusted helper's doctor
and a separately initiated fresh CSO run with prompt assessment submission;
qualified isolated execution additionally requires its supported local Docker
and exact catalog profiles. Do not infer a clean audit from the empty findings.

Run `1793734268477-c0bfcb20040d052e` finished through `gstack-cso` ABI 3.
Its private report is retained at
`~/.gstack/security/cso/e7ac09bf7e97c728f9f0310d/1793734268477-c0bfcb20040d052e/report.md`.
The snapshot contains 1,019 sanitized inputs, three execution exclusions and
nine unread binary inputs (three diagrams and six papers). Redactions changed
some inputs. History retained nine of 100 selected commits within its 1 MiB
limit. This is not complete historical-secret inspection.

Gitleaks, OSV-Scanner, Semgrep, zizmor, Trivy and Schemathesis did not run in
CSO. No authenticated runtime witness or repair bundle was produced. The native
tests and audits below ran outside that CSO run; they are separate engineering
evidence, not substituted CSO coverage or OWASP/ASVS certification.

The requested gstack upgrade also completed: `1.45.0.0` to `1.94.34.0`, clean
fast-forward with a backup branch, separated source/runtime directories and 83
resolving Codex section links. Browser bootstrap/render passed. Installed Bun
1.3.13 differs from upstream's CI pin 1.4.2; setup passed with that warning.
No Cragkit browser service, model download or global Bun upgrade was added.

## Findings, corrections and counterevidence

| ID | Observation and impact | Disposition |
| --- | --- | --- |
| CSR-01 | Planner transports could return a declared exception containing a mutated message, cause or private properties. A Node error named `AbortError` could also escape provider classification without caller cancellation. | Fixed in both native planners: reconstruct fresh canonical operational errors; only a real caller signal controls caller cancellation. Preserve explicit fallback and dispatched-work accounting. |
| CSR-02 | LangChain tools propagated declared engine/serializer exception instances, including custom properties and Python exception context. A consuming application logging those objects could expose private callback diagnostics. | Fixed in both adapters: allowlist built-in classes by inheritance, instantiate only library constructors, discard mutable code/message/cause/properties. Python raises outside the handler with suppressed context. |
| CSR-03 | Python initially classified an unknown `CragkitError` subclass from the engine differently from Node. | Fixed and covered: unknown engine errors become `ProviderUnavailable`; unknown serializer errors become `InvalidRequest`. This is a contract correction, not a demonstrated authorization exploit. |
| CSR-04 | The retained accepted RC1 artifacts predate these source corrections. Existing environment flags alone must not admit them for upload. | Added a checked boolean `security_hold: true` to publication policy. Admission rejects true, missing or malformed states before product access/upload. Hold removal requires reviewed replacement acceptance. |

CSR-01/02 were reproduced using synthetic errors in caller-installed callbacks.
No real key, live provider or attacker-controlled parser-to-private-mutation
chain was used. Confidence is high in the reproduced propagation behavior and
the correction; remote exploitability and severity are not established. Astra's
independent source challenge found no supported confidentiality exploit in the
inspected corrected boundaries. It distinguished trusted in-process callbacks
from narrow tool JSON. This does not establish that every application callback
or integration is safe. No supported remote high/critical finding was identified
in this scoped review; the unassessed domains remain open.

All nine public error classifications retain their codes. Subclass constructors
are not called, genuine cancellation remains covered by existing suites, and
failed dispatched work retains unknown usage rather than being refunded.

## Consumer attack and control evidence

| Boundary | Current evidence and scope |
| --- | --- |
| Hidden authority/configuration | Official Python and Node SDK clients over actual stdio pipes submit foreign principal/grants/revision, provider/transport, prototype and hidden configuration fields. Retained forbidden fields fail before engine calls; successful calls retain exact bound scope and required filters. |
| SQL/shell/prompt/protocol text | Hostile query text and a forged second JSON-RPC-looking message remain escaped data, with exact UTF-8 evidence/digest checks. Python verifies no shell marker was created. These fake-engine tests do not prove native SQL enforcement or downstream LLM obedience. |
| SDK normalization | Pinned Node SDK/Zod drops raw `__proto__` during protocol argument parsing. A raw-wire regression verifies unchanged scope/filters, no foreign own/inherited property and no global prototype mutation. Direct host input rejects it. This wire key is normalized, not rejected; see the [MCP clarification](../../../contracts/MCP_V5.md). |
| Duplicate JSON members | Node's SDK retains the last query value. Duplicate hidden scope keys still fail validation before engine entry. No authority bypass was reproduced; do not claim duplicate-member rejection. |
| Invalid output/private diagnostics | Wrong request ID, extra secret field, changed digest, nonfinite usage, accessors, `toJSON`, foreign prototypes and cyclic data are rejected. Tool responses contain fixed errors and exclude diagnostic canaries. No malicious getter or `toJSON` hook is executed by result validation in the covered Node cases. |
| Logging | Python default and DEBUG SDK notification paths are observed separately. SDK DEBUG protocol logging may include caller-controlled method text; it is application-owned and is not sanitized by fixed tool errors. Keep broad DEBUG off in production and assess the actual sink. |
| Deadline/admission/disconnect | Full existing SDK and core suites retain timeout, cancellation, competing-call, late-work and disconnect cases. This is bounded local behavior, not a distributed rate-limit or sustained hostile-load result. |
| Native authority settlement | Fresh disposable PostgreSQL 17.11 passed 23 genuine SQL checks: restricted roles, forced RLS, denied sensitive reads, guard privileges, current-authority mismatches and lock/commit/loss races. Cleanup was verified. Scope is `same_transaction_security_guard_sql_only`; no current hosted or distributed Qdrant deployment was probed. |

## Actual validation

One test process ran at a time on the M4/16 GiB laptop. Before native work,
system memory free was 38% and disk headroom 18 GiB. No new service remained after
the disposable check. No hosted database mutation, live model call, new paid
CI job, publication, account change or production target was used.

| Check | Result |
| --- | --- |
| Full core Python and tool suites | 4,377 passed; no skips; four existing intentional warnings; 21.52s |
| Full Python LangChain / MCP | 113 / 54 passed |
| Strict Python typing | Core 51 files, LangChain 1 file, MCP 1 file passed |
| Full core Node, strict build included | 1,639 passed; no skips |
| Full Node LangChain / MCP, strict builds included | 108 / 42 passed; no skips |
| Fresh SQL security guard | 23 checks; cleanup verified |
| New consumer/error cases | 108 across six new test files, included above |
| Publication hold regressions | Ten new cases, included in the core/tool total |
| Offline local engineering builds | Three wheels, three sdists and three private npm tarballs built |
| Local archive inspection | Nine inventories checked for forbidden paths, licensing and selected credential patterns; one reserved-domain synthetic invalid-URL fixture reviewed, zero unresolved pattern candidates |

Total automated regression cases: 6,333. Native SQL checks are separate. Core
and MCP Python used 3.14.6; the existing LangChain environment used 3.14.4.
Node 26.5.0/npm 11.17.0 and uv 0.11.8 were used. These local results do not replace
the supported-platform exact-artifact/CI matrix.

Failed evidence was retained before corrections. Original planner Python
regressions failed 6/7 and LangChain failed 38/38. The first Python parity fixture
incorrectly instantiated the abstract-style error base; it was corrected to an
unknown subclass, then reproduced one real classification mismatch. The first
full LangChain run exposed two existing context-suppression assertions; the
implementation was corrected without changing them. The first post-fix combined Node run
passed 46/47; the remaining prototype-key assumption was replaced only after
SDK/Zod source inspection and the independent challenge above. A TypeScript
comparison utility used an obsolete compiler API path; intended-source review
instead compares exact code with JSDoc removed. Archive inspection initially
included uv's output `.gitignore`; the inventory now selects actual archives.
No test assertion for authority, fidelity, accounting or error privacy was
relaxed to obtain a pass.

## Dependency and server-advisory observations

All seven native audits exited 0 without changing locks: npm audit for the three
Node packages reported zero known advisories; frozen `uv audit` for core,
LangChain, MCP and the backend-conformance workspace reported no known
vulnerabilities across 38/47/48/61 packages. `uv audit` reports its experimental
status. Public package names/versions were queried; no private source, documents,
credentials or model prompts were sent. Known-advisory absence is time-bound
and does not establish absence of undiscovered or host-specific vulnerabilities.

The prepared test PostgreSQL is 17.11, the fixed 17.x version in the inspected
[official security table](https://www.postgresql.org/support/security/).
Prepared Qdrant 1.20.0 is outside the affected ranges in the reviewed
[distributed internal authentication advisory](https://github.com/qdrant/qdrant/security/advisories/GHSA-frc7-44gm-99qq),
[read-only key/JWT advisory](https://github.com/qdrant/qdrant/security/advisories/GHSA-3gph-6c29-p29v)
and [logger file-write advisory](https://github.com/qdrant/qdrant/security/advisories/GHSA-f632-vm87-2m2f).
The [pgvector advisory page](https://github.com/pgvector/pgvector/security/advisories)
had no published advisories. These observations cover the named versions and
advisories, not every server CVE, extension build or a production configuration.

## Release and production gate

The earlier CI source, nine publication products, transport, manifest hashes and
immutable `V6-08-verification.json` remain historical evidence. They do not cover
these corrections. The nine new archives are local engineering samples only;
they have not been refrozen as replacement publication products, clean-installed
across the release matrix or validated by a new authorized candidate CI run.
Tracked npm packages remain private. Publication is on hold independently of
account setup and authorization flags.

The [production security guide](../../../docs/production-security.md) assigns
identity binding, current grants, least-privilege database credentials, verified
TLS, private per-project provider keys, logs/retention, global quotas, patching
and recovery to their actual owners. No built-in provider key is required.
Before deployment, select and assess the consuming application's actual target
and verify those controls there. Arbitrary plugins remain trusted in-process
code; retrieved source text remains untrusted data.

Next smallest release action: freeze corrected source and prepare exact
replacement artifacts under the existing release contract. Required new CI,
public registry setup, publication and post-registry installs remain separate
pending gates. CSO domain assessment and deployed-target testing are also open;
neither this report nor local passing tests completes V6-08 or version exit.

Learning exercise, still unassessed: explain why a tool response with a fixed
error code can be safe while an application's DEBUG log containing the original
exception remains sensitive.
