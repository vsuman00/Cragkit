# V6 resource testing contract

Revision: RST-r1. Frozen before measurement on 3 November 2026.

V6-03A measures the default installed core. V6-03B measures native PostgreSQL
workloads with fake providers. Neither changes the frozen candidate, thresholds,
reviewed questions, core library or provider policy. The release tracker owns
acceptance; successful measurements do not authorize publication.

## Default installed core

Build fresh core wheel and npm archives from the clean recovery candidate. Install
only required dependencies in separate minimal environments. Record archive and
probe digests, exact versions, hardware, environment preparation and logical sizes.
Use the existing `check_artifacts.py` 19-entry-point probes and I/O guards without
weakening them. Run five fresh processes per language, serially, with a 15-second
child timeout. In each process, repeat the same imports 50 times after the initial
import. Record every observation, median and nearest-rank p95. For five samples,
p95 is the maximum. Every fresh observation and logical install size must satisfy
the unchanged `V6-candidate.json` resource targets. Warm timings are descriptive;
there is no invented warm threshold. RSS covers the whole child lifetime. Logical
size is the entire minimal Python environment or Node `node_modules`, matching
the baseline. Filesystem caches are uncontrolled; this is not an OS-cold test.

## Native workload

Both peers implement `run_resource_workload` (Python) or `runResourceWorkload`
(Node) accepting a JSON-compatible configuration with `reader_config`,
`writer_config`, `tokenizer_path`, and `sdk_root`. Python imports the frozen installed
candidate; Node dynamically loads modules from `sdk_root/dist`. Root supplies
configuration over stdin through a bounded parent, never command-line credentials.
Peers own function implementations and focused tests; root owns launch adapters,
fixtures, shared contracts, reports, tracker, Git and the single test slot.

Use one isolated genuine PostgreSQL 17.11/pgvector 0.8.0 fixture per runtime,
restricted reader/writer roles, TLS verification and existing migrations. Reuse
one writer and one reader pool sequentially, with `max_size=1`, `max_waiting=1`,
bounded acquisition and close timeouts. No configuration or secret values in output.
Use fake 1,536-dimensional embeddings under `FAKE_PROFILE`, strict cl100k counting
with the supplied pinned tokenizer, and the frozen request ceilings: 25 seconds,
15 candidates, 3 attempts, 3 subqueries, 8 provider calls, 20,000 context tokens,
256 envelope reserve. No real provider transport, model installation or network
other than the explicit local TLS database.

Create exactly three short synthetic documents, sequential ingestion batch size
one, in tenant `resource-tenant`, collection `resource-tests`. IDs `resource-0`
through `resource-2`; text `Resource handbook N. The support route is queue N.`
where N is 0, 1 or 2. Bind an explicit writer authorization callback to that scope
and those identities. Record all three ingestion latencies and receipt fidelity.
After closing the writer, reuse one reader. Measure 20 hybrid retrievals at
concurrency one, then 20 at concurrency two using a fixed worker count, never an
unbounded gather. Query `support route queue` with required document-id filter
`resource-0`; all returned evidence must belong to that exact tenant, collection,
document and canonical source span. Require nonempty evidence and complete
execution; no sufficient-status claim. Record latency for every request, strict
context counts, attempts, provider calls and worker RSS. Report throughput as
observed requests per elapsed stage second, not a hardware guarantee.

For deterministic contention, hold one lease with an event, start one waiting
lease and await observable waiter admission (bounded polling of the resource's
own active-user set is allowed for this white-box harness). A third lease must
fail with `provider_unavailable` before a 1-second watchdog. Cancel the waiting
lease, release the holder and verify a fresh `SELECT 1` succeeds. Separately cancel
an active `SELECT pg_sleep(2)` after native dispatch is observable, bound unwind
to 5 seconds, and verify healthy reuse. Native cancellation may destroy and replace
the connection; do not require connection identity. Record expected cancellation
separately from failures. All tasks and resources close in `finally`, including
failed scenarios; parent also enforces finite child lifetime.

Output one object with revision `RST-r1`, runtime (`python` or `node`), version,
`ingestion_ms` (3), `retrieval` (two stages with concurrency, elapsed_ms and 20
latency samples each), `checks` (named booleans), `peak_rss_bytes`, and
`provider_http_calls` (zero). Additional bounded numeric/count diagnostics are
allowed. Do not emit request/source text, database configuration or exception
representations. A false invariant throws a fixed diagnostic, never a success
record. Parent validates shape, counts, finite positive durations, complete checks
and unchanged retrieval p95 deadline. Queue/cancellation assertions are required.
Synthetic unit doubles are harness checks; only the actual native run establishes
database behavior. Roots and peers coordinate directly about contract details;
contract or outcome changes require root before dependent edits.

## Pressure and scope

Record actual machine/OS/runtime versions rather than assuming the historical
16 GB development laptop. Check free memory and cumulative swap before setup and
between stages; refuse below 10 percent free or observed sustained swap growth.
Use one test or native process at a time. Stop on responsiveness degradation.
No simultaneous-system-memory estimate by adding independent RSS peaks. Report
database logical footprint separately from worker memory. Close fixture processes.
These native measurements cover PostgreSQL only. Qdrant and cross-platform resource
evidence remain explicit limits; existing conformance does not become throughput
evidence. Broader supported-platform testing belongs to V6-06 CI when available.

## RST-r1 recovery clarification before final native measurement

The first native run failed; a diagnostic run isolated Node `active_reuse` with
`provider_unavailable`. Python completed its native workload. The pinned Node
driver destroys a client socket on active cancellation; PostgreSQL may retain its
backend slot until the running command observes disconnect. The fixture's existing
role connection limit remains one. Immediate reuse is not established.

For Node only, observe eventual healthy reuse through a harness probe with one
original five-second deadline, at most 25 sequential attempts, and 100 ms pauses
clipped to remaining time. Each attempt uses the lesser of two seconds and the
remaining original budget, with a shared abort signal. Catch only the library's
exact `provider_unavailable` code; unrelated failures remain fatal. Record attempt,
refusal and elapsed counts. Require an actual successful `SELECT 1`. This changes
the measurement procedure after an observed failure; it adds no library retry,
privileged observer, extra client or relaxed role limit. Original failed runs remain
retained. No claim of server-side cancellation acknowledgment follows from success.
