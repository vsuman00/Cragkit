# V5 local installation and operations

For example, a PostgreSQL lexical application needs the core and PostgreSQL driver,
but no Qdrant server, embedding provider or MCP process. Choose the smallest profile
that supplies the required capabilities.

This guide covers local candidate artifacts and disposable operational examples.
Current manifests use Python `1.0.0rc1` and npm `1.0.0-rc.1`; no registry release is
implied. Older V5 reports retain their original `0.0.0` identities. Check the [tracker](../tasks/todo.md) and
[V5-08 evidence](../evaluation/reports/V5/V5-08.md) for actual acceptance. Installation,
native backend mechanics, live-model quality and hosted operation are separate evidence.

## Select a profile

Use Python `>=3.14,<3.15` or Node `>=26.5.0 <27`, matching the current manifests.
Python executes in Python and the npm package executes in Node; Node needs no Python
server in an application deployment. Python development tools below orchestrate both
native runtimes only for local acceptance.

| Profile | Install beyond core | Required services and private configuration |
| --- | --- | --- |
| Core | None; core depends on Pydantic in Python and Zod in Node | No database, model or transport host for import and deterministic contracts |
| PostgreSQL | Python `postgres` extra; Node optional `pg==8.23.1` peer (npm uses `pg@8.23.1`) | PostgreSQL, restricted runtime role credentials and verified TLS/CA for a remote target; pgvector for the vector profile, not for lexical FTS |
| Qdrant candidate retrieval | Python `qdrant` extra (`httpx==0.28.1`); Node uses native HTTP | Supported Qdrant endpoint/read credential, exact index/profile identity and a compatible authoritative SourceStore; the reference authority additionally needs PostgreSQL and its driver |
| Qdrant reference authority | Python `postgres,qdrant` extras; Node `pg@8.23.1` and native HTTP | Qdrant plus the explicit PostgreSQL authority schema, separate restricted roles and application-owned pools/supervisor |
| Exact token accounting | Python `tokenizers` extra; Node `tiktoken@1.0.22` | Explicit matching tokenizer and renderer/wrapper; no model endpoint required by the tokenizer |
| MCP | Separate `cragkit-mcp` artifact and its SDK dependencies | Application-owned stdio host and trusted scope resolver, plus services required by its selected backend |

The tested Qdrant reference server is single-node Qdrant 1.20.0. Its synthetic vector
profile needs no inference credential. A real dense embedding profile needs an
explicit supported embedding transport, model/profile identity, provider disclosure
policy and credential supplied privately by the application. Installing a profile
does not select or call that provider. Sparse encoding is separately declared;
PostgreSQL native FTS is not BM25. Qdrant dense corrective retrieval does not silently
supply lexical or hybrid search.

LangChain is another separate optional artifact; its V4 installation procedure is in
[development.md](development.md). MCP is a transport over the same native retrieval
contracts, not a database or identity service. Tool input cannot choose trusted scope
or expose database credentials. The supported host transport is stdio; this guide does
not deploy an HTTP service.

## Build and install local artifacts

Run from the repository root. Use fresh output directories and serialize these tools.
They install dependencies in temporary environments and leave acceptance reports in
ignored `artifacts/`; imports do not install them. Dependency installation can use
package registries, while guarded import probes reject covered product network/process APIs. These probes
are focused regression checks, not a network security sandbox.

```sh
python3 tools/check_artifacts.py --output-dir artifacts/V5/V5-08/core
python3 tools/check_qdrant_artifacts.py --core-artifacts artifacts/V5/V5-08/core --output-dir artifacts/V5/V5-08/optional
```

The first command builds and checks the core wheel, source distribution, rebuilt wheel
and npm tarball. The second builds the optional MCP artifacts and checks separate
clean core, PostgreSQL, Qdrant candidate-only, Qdrant authoritative, tokenizer and MCP installation profiles in each runtime.
The MCP test environments additionally install locked test dependencies and a tokenizer;
those are harness inputs rather than required core dependencies. Inspect their reports
before using an archive. These checks do not start an application
backend or prove a real embedding model's quality.

For an application, install an explicit archive path from those reports into a new
environment. For Python, select the wheel's extra using the quoted local path syntax
`'/absolute/path/cragkit-1.0.0rc1-py3-none-any.whl[postgres]'`; select `qdrant` or
`tokenizers` instead for the corresponding dependency. For the reference Qdrant
PostgreSQL authority select both `postgres,qdrant`. Core needs no extra. Install the
local core wheel alongside the local MCP wheel so its exact `cragkit==1.0.0rc1` dependency
resolves to your built product.

If an absolute wheel path contains spaces, use a percent-encoded file URI in a
PEP 508 requirement, for example
`'cragkit[postgres] @ file:///absolute/My%20Project/cragkit-1.0.0rc1-py3-none-any.whl'`.
`Path('/absolute/My Project/cragkit-1.0.0rc1-py3-none-any.whl').as_uri()` produces
that URI. If you also use a locked constraints file in this repository's spaced
workspace, pass its relative path from the repository root. The local uv rehearsal
rejected a spaced absolute `--constraints` path; the interpreter and wheel paths
were independently verified to work.

For Node, run `npm install --ignore-scripts /absolute/path/to/cragkit-1.0.0-rc.1.tgz`
in a new application directory. Add `pg@8.23.1` or `tiktoken@1.0.22` only when that
profile needs it. Install the local core tarball alongside the MCP tarball; do not
resolve provisional package names from a public registry. Neither package is being
published by these commands.

## Connections, credentials and migrations

Create bounded pools once per application, not per request. Keep credentials in private
files/configuration outside the repository and logs. Runtime roles must be nonowners,
without superuser, BYPASSRLS or administrative fallback. Remote database connections
must validate certificate and hostname. Qdrant remote endpoints require verified HTTPS;
explicit loopback development endpoints may use HTTP. Proxy/TLS bypass is unsupported.

Open resources explicitly, then initialize adapters to verify their selected schema,
capabilities and permissions. Imports and constructors neither connect nor migrate.
Bind trusted scope outside agent-editable input. Reauthorize source release after
retrieval and before provider disclosure/final packing. Release database leases before
model work, while retaining the operation's shared deadline and budget.

Applications apply migrations as a separate operator action, with exact-byte checksums
and the expected ledger/catalog. Do not run fixture setup against an existing application
database. The PostgreSQL retrieval schema and optional vector setup have their own
history; see [PostgreSQL storage](../storage/postgres/README.md). The Qdrant authority
uses a separate `cragkit_qdrant` namespace and numbered migration history; see
[source authority](../storage/qdrant/postgres/README.md) and
[publication migrations](../storage/qdrant/postgres/PUBLICATION.md). Apply the exact
profile required by the operation: source-only, publication, attestation, security
projection or managed purge. A newer profile is not permission to skip earlier
migrations or substitute a hand-edited catalog. Initialization rejects mismatches
rather than repairing them.

## Consistency and ownership

PostgreSQL retrieval obtains its search branches from the same active-generation
snapshot, releases the transaction before external reranking and freshly checks source
authorization before release. Qdrant is a candidate replica: publication requires staged
immutable sources, globally claimed point identities, durable dispatch records, exact
readback and an authoritative publication CAS. Two stores share no transaction. A count
or successful HTTP response alone cannot prove published membership. Old replica grants
never authorize source disclosure. Authority outage is an operational failure, not an
empty successful search. See [ADR 0003](decisions/0003-qdrant-consistency.md).

The supported managed writer requires the actual caller-owned native single-node
supervisor, owned process/storage, immutable credential epochs and the selected replay
configuration, including `prevent_unoptimized=false`. Keep one supervisor owner for the
instance. Replica clusters, automatic supervisor takeover, arbitrary external writers
and lease-only ownership are unsupported. Restart or apparent health does not establish
quiescence, settlement or permission to reopen admission.

The [publication API guide](qdrant-publication.md) shows the public manager and worker
construction order. Managers borrow their authority, writer, recovery, transport,
supervisor and pools. Closing a manager or worker host does not close those borrowed
resources. An application's shutdown must stop admission, drain/cancel its operations,
close/reap worker hosts, close managers and their verifiers/transport/recovery/writer,
then close owned pools and finally its supervisor/controller. Close recovery coordinators
before their borrowed resources and controller. Follow the concrete runtime's cleanup
interfaces; do not replace this order with private proof or receipt calls.

## Execute bounded recovery and shutdown

For example, a worker can expire after dispatch without proving that the write stopped.
Its durable unknown dispatch blocks a successor. Killing the child, inspecting existing
points or retrying the same request does not remove that fence. Public managed repair
must refence old credentials, reconcile exact durable state, verify current readback
and settle uncertainty before reopening. A lost completed SQL reply instead needs
same-identity durable confirmation, not a replacement point write.

The following existing native acceptance example deliberately expires an actual
publication operation with an independently retained HTTP request and exercises successor
refusal and managed recovery. Despite the parent tool name, its `deadline` scenario
uses public in-process managers rather than a child publisher. It owns only disposable local
PostgreSQL/Qdrant servers and synthetic records. It requires the installed PostgreSQL
17 binaries, the previously verified Qdrant binary with the exact hash below, current
Node dependencies/build and the locked Python optional environment. It downloads no
model and uses no provider or hosted database credentials.

```sh
npm --prefix packages/typescript run build
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_worker.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --scenario deadline --runtime all --artifacts-dir artifacts/V5/V5-08/operations-deadline
```

Choose another fresh artifact directory when repeating it. The parent runs languages
serially. Read its `results.json`: success must include `cleanup_verified=true`, not
merely a completed business step. Cleanup closes owned clients, reaps owned workers,
stops owned servers, verifies listener absence and removes only private fixture storage.
A cleanup failure remains a failed run with diagnostics; do not mark it successful or
delete unrelated processes/data. This is source-checkout native operational evidence;
it is separate from installed-artifact import and MCP round-trip checks.

For a second experiment, use `--scenario supervisor_pause` with a different fresh
directory. It stops an admitted worker's actual supervisor, checks independent controller
and SQL-owner refusal, then resumes the same owner for cleanup. It demonstrates refusal
under a paused supervisor, not automatic failover. See the full
[development commands](development.md) for setup and other accepted fault scenarios.

As a small exercise, choose between PostgreSQL lexical and Qdrant dense for a local
application with no embedding credential. List the dependencies and explain why an
unknown Qdrant dispatch must remain blocked after its worker exits.
