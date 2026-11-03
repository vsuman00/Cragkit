# V6-03 resource and concurrency evidence

State: local acceptance passed on 3 November 2026. V6-03A1 covers minimal default
installs. V6-03B1/B2 cover native Python/Node workloads; B3 is the bounded parent.
The [RST-r1 contract](../../../contracts/RESOURCE_TESTING_V6.md) was agreed before
measurement. Its later Node recovery clarification is disclosed below. The
[full observations](V6-03-verification.json) retain samples, targets, pressure,
digests and failed runs. Full V6 and publication remain incomplete.

The clean recovery candidate is source `25275e447c64ecfd243ef6bc26c87031d5e2e472`,
checkout `34b5748`, runtime identity
`59af39c6cb0a5d118c73511dbb67b5fd22b2289a731ffeaaa5fc488d4105b993`.
Independent ECR verification passed before and after native execution. Root-owned
workload tooling is separately hashed. No core, lockfile, reviewed input, model,
profile, scorer or frozen target changed.

## Default installed core

Actual machine: Mac16,12 M4, arm64, 16 GiB RAM, macOS 27.2. Versions: Python
3.14.6, Node 26.5.0, Pydantic 2.14.1, Zod 4.6.7. Fresh wheel and npm archives came
from the clean candidate. Python installed only locked core dependencies from
the offline cache. Node used bounded archive extraction plus 840 Zod files checked
against the runtime receipt. This is verified dependency reuse, not an npm-install
success claim. The first npm pack failed because its output directory was absent;
creating that task-owned directory resolved it. No model or dependency download ran.

The existing 19-entry-point import probes enforce absent optional packages and
deny network/process I/O. Five fresh processes per language run serially, each
followed by 50 warm reimports. Every fresh timing, RSS and install-size observation
passed its unchanged ceiling. Warm timing has no invented acceptance threshold.

| Measure | Python | Node | Frozen ceiling, Python / Node |
| --- | --- | --- | --- |
| Fresh import median | 0.2540 s | 0.04385 s | descriptive |
| Fresh import p95/max, n=5 | 0.5928 s | 0.06449 s | 1.4471 s / 0.13168 s |
| Warm reimport median, n=250 | 0.00481 ms | 0.04894 ms | descriptive |
| Whole-child peak RSS, maximum | 67,092,480 bytes | 92,241,920 bytes | 130,023,424 / 171,900,928 bytes |
| Logical minimal install | 8,032,831 bytes | 7,409,253 bytes | 16,033,052 / 14,788,674 bytes |

Python logical size includes its whole minimal environment; Node includes
`node_modules`, matching the baseline. RSS is not an import-only increment and
logical bytes are not allocated disk usage. Filesystem caches are uncontrolled;
fresh process does not mean OS-cold storage. Python synchronous reimports and
Node asynchronous dynamic imports are separate observations, not a language race.

## Native PostgreSQL workload

Each runtime used a separate disposable TLS-verified PostgreSQL 17.11 database
with genuine pgvector 0.8.0 and distinct restricted reader/writer roles. One writer
ingested three short documents sequentially, then closed. One reader pool reused
one client with one allowed waiter. Twenty hybrid requests ran at concurrency one,
then twenty at concurrency two through fixed worker counts. Fake embeddings were
used under the fake profile; provider HTTP calls were zero. This is resource and
contract evidence, not live model quality evidence.

| Runtime / concurrency | Requests | Latency median | Latency p95 | Observed requests/s |
| --- | --- | --- | --- | --- |
| Python / 1 | 20 | 11.18 ms | 11.44 ms | 87.30 |
| Python / 2 | 20 | 21.73 ms | 21.83 ms | 92.17 |
| Node / 1 | 20 | 10.21 ms | 12.74 ms | 88.66 |
| Node / 2 | 20 | 19.40 ms | 20.10 ms | 101.74 |

All samples completed under the original 25,000 ms deadline and preserved the
exact required document filter, authorized revision, source digest and UTF-8 span.
Strict context counting, envelope reserve, attempts and fake-provider call ceilings
passed. Python ingestion median/max was 26.33/40.94 ms; Node was 32.36/46.65 ms
(three samples each). Native worker peak RSS was 109,772,800 bytes Python and
172,294,144 bytes Node, including optional drivers/tokenizer. Those are descriptive
workload measurements, not the minimal-core RSS gate above. Each database's logical
size was 9,090,739 bytes, including fixture schema. Separate RSS peaks are not summed
into a simultaneous machine-memory claim.

With one lease held and one waiter observably admitted, a third lease was rejected
within the one-second watchdog. Queued cancellation unwound and a fresh `SELECT 1`
succeeded. Active cancellation followed observable native `pg_sleep(2)` dispatch:
libpq ACTIVE/busy state in Python, or active driver query plus flushed TLS bytes in
Node. These observations do not independently acknowledge server execution.

The first run failed and was retained. A diagnostic run confirmed Node
`active_reuse` / `provider_unavailable`; Python completed all native checks. Source
inspection showed that Node destroys a frontend socket before PostgreSQL must
release its backend slot. A role connection limit of one can therefore refuse
immediate reuse. No SQLSTATE 53300 observation is claimed. Before the final run,
RST-r1 explicitly allowed a bounded harness recovery observation: one five-second
deadline, at most 25 sequential probes, 100 ms pauses, only `provider_unavailable`
treated as temporary. No library retry or role-limit relaxation was added.

In the final run, Node observed 17 refusals and a successful eighteenth `SELECT 1`
after 2,017.54 ms. Both runtimes then passed all 12 invariant/cleanup checks.
Immediate reuse and server-side cancellation acknowledgment remain unsupported.
This behavior is a concrete overload/recovery example, not a hidden success retry.

Pressure monitoring recorded 46–49% system memory free, with no new swapouts.
The initial default-import run recorded 48–49% free. Existing swap allocation
predated these runs; no zero-swap claim is made. Each owned database closed and
its listener refused a fresh connection. No persistent service or watcher remains.

## Verification and checkpoint

Root inspected both Sol implementations and their assembled interface report,
then ran one test process at a time. Workers owned separate Python/Node files and
communicated directly; root retained shared contract, launcher, tracker and Git.
The new harness tests passed 45 Python cases and 19 Node cases, including missing
native dispatch, bad source/usage, failed cleanup, delayed backend release,
unrelated recovery errors, child-output overflow and watchdog termination.

The broader checkpoint results and exact reproduction commands are recorded in
[development.md](../../../docs/development.md#v6-03-resource-and-concurrency-checks).
V6-C1 passed 3,825 Python/tool tests (four existing intentional Pydantic warnings),
1,617 core Node tests and all 19 shared fixture/schema/development/seal stages.
Local supported-platform evidence is separate from future V6-06 hosted CI.
Qdrant resources, long-duration soak, large datasets, other machines and operating
systems were not measured. No confidence interval or population performance
guarantee is inferred from twenty requests on three synthetic documents.

Learning example: with a one-client pool, concurrency two adds waiting. It need
not double throughput, and p95 describes the slower end of the observed requests.
Here nearest-rank p95 is the nineteenth sorted latency among twenty observations.
Optional exercise: compare each concurrency-one median with concurrency two and
explain why the queue increases latency. Learning practice remains unassessed.
