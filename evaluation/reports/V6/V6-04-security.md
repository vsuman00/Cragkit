# V6-04 security and failure audit

State: scoped local acceptance passed on 3 November 2026. This closes the
implemented-boundary audit, not production readiness. The
[verification record](V6-04-verification.json) binds changed files, commands,
artifact hashes, current native results and historical evidence.

Two Sol peers inspected both native runtimes across complementary edge ranges:
[E01–E54](V6-04-core-audit.json) and [E55–E108](V6-04-extension-audit.json).
They communicated directly; the extension peer assembled the findings. Root
owned changes, execution, artifact inspection and final acceptance. Astra reviewed
the unresolved exception-contract decision. Worker inspection alone was not
treated as a test pass. All 108 cases have source/test/evidence owners; this is
not a measured coverage percentage.

## Finding and correction

E51 found that an unknown injected reranker transport exception escaped unchanged
in Python and Node. A synthetic marker appeared in both default traces. A declared
project error with a private cause or mutated message could also expose details.
No actual credential or live provider was used to reproduce this issue.

The [RK-r2 clarification](../../../contracts/RERANKER_V3.md) and both adapters now
reconstruct ordinary operational exceptions as fresh allowlisted library errors.
Known authorization, integrity, validation and deadline classifications stay
intact; caller subclass constructors never run. Python raises after leaving the
handler so the provider exception does not remain as cause or context. Node copies
no provider message, payload, cause or attached property. Transport abort errors
keep a fixed cancellation name/message.

An unknown failure becomes `ProviderUnavailable` and still fails that rank call
even when fallback is enabled. A transport-declared unavailable/unsupported error
can still produce the existing explicit degraded result. One dispatch, original
deadline, occupied-admission rules and request-owned cancellation remain intact.
No error code or automatic retry was added. The inspected corrective capture path
does not add a reranker retry; an external caller can still choose to retry the
existing retryable availability code.

For example, a provider error containing a private diagnostic now yields only
`Provider is unavailable.` through the adapter and PostgreSQL retrieval entry
point. A malformed score mapping remains an integrity error. Safe error messages
do not establish that evidence is relevant or sufficient.

## Actual validation

| Check | Current result |
| --- | --- |
| Focused adapter and retrieval security regressions | 58 Python / 39 Node passed |
| Full Python/core-tool suite | 3,843 passed; four existing intentional warnings |
| Full core Node suite and strict build | 1,635 passed |
| Python strict typing | 51 source files passed |
| Optional LangChain suites | 73 Python / 70 Node passed |
| Optional MCP suites | 41 Python / 36 Node passed |
| Shared reranker / hybrid / evidence fixtures | 11 / 8 public plus 4 encoder / 6 cases passed |
| Genuine SQL security guard and lock races | 23 checks; cleanup verified |
| Actual supervisor suspension, both runtimes | 14 checks; cleanup verified |
| Genuine managed purge, both runtimes | 52 checks; cleanup verified |

The new regressions cover unknown and declared error chains, changed messages,
authorization/integrity/deadline classification, both fallback settings, subclass
constructors, timeout conversion, one invocation, public retrieval propagation
and released leases. Existing cancellation, late-work admission, malformed output
and source/filter tests still pass. These are public-boundary adversarial tests
and source inspection; they are not an external penetration-test certification.

The first optional Python MCP check exposed stale installed `0.0.0` metadata:
40 tests passed and one installed-version assertion failed. Root verified the
mismatch, resynced its frozen offline environment with Python 3.14.6 and reran all
optional SDK suites after the security patch. Locks, source and version assertions
were not weakened. The original failed log is retained.

The 43-case V5 native fault ledger was also rechecked against all 42 retained result
digests. Twenty-nine relevant Qdrant library/migration files are byte-identical to
the V5 exit commit `c8d5721`; the renamed native verification consumer is also
byte-identical. Those runs remain historical. The fresh guard, process and purge
runs above establish current representative native behavior; they do not claim
all historical scenarios were rerun on one server.

## Packages and credentials

Root built six local audit archives: core, LangChain and MCP for Python and npm.
Bounded archive inspection rejected forbidden paths, symlinks and model/private
asset types. No selected saved credential or its base64 encoding appeared in those
archives or the 950 current tracked files scanned. Private values, prefixes,
lengths and credential digests were not recorded. Ignore rules keep environment
files, credentials, certificates, local environments and generated output out of
Git. The earlier Git-history check remains separate; a selected-key scan cannot
identify every unknown or previously rotated secret.

These archives include preserved user prose edits and are local security samples,
not the final frozen V6-06 release bytes. Publication has not occurred. Final
licenses, notices, exact installs and supported-platform CI remain later gates.

An explicit [OSV version query](https://google.github.io/osv.dev/post-v1-querybatch/)
returned no matching advisory IDs for 133 public locked Python/npm package versions
at the recorded time. Only package names and versions were sent. That result does
not prove absence of unknown or unreported vulnerabilities and does not cover
PostgreSQL/Qdrant binaries, system libraries or the operating system.

## Limits and remaining gates

The audit records 102 implemented cases with inspected local evidence. Six are
explicitly future or conditional: E58 migration/rollback, E61 published-byte
verification, E62 caching, E63 approximate indexing, E64 answer generation and
E67 automatic hosted credential/ban intervention. They were not marked passed.
V6-07/V6-08 remain responsible for their release gates. The E32 local CPU-model
subcase is also unimplemented; arbitrary synchronous callbacks are not sandboxed
or preempted. Historical active-only search and default unknown-coverage/conflict
limitations remain visible in the V6-02 report.

This patch follows the frozen V6-02 live evaluation. Its original candidate,
recording, labels, metrics and admission are preserved; the changed source is not
represented as a new live evaluation. Later offline compatibility, final resource,
artifact and CI acceptance must bind the final candidate separately. No paid API
call, hosted database change or local model download ran in this audit.

Actual local pressure stayed above the stop threshold, with 45–47% free during
the later checks and decreasing existing swap allocation. Owned PostgreSQL,
Qdrant, child processes and listeners closed. No cluster, cross-platform, arbitrary
application-log or universal cancellation-redaction guarantee is made.

Optional exercise: explain why an unknown transport error remains fatal to the
current rank call while a declared availability error can use explicit fallback.
Learning practice remains unassessed. Next task: V6-05 developer usability trial.
