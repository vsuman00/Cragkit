# V5 local installation and operations

For example, a PostgreSQL lexical application needs the core and PostgreSQL driver,
but no Qdrant server, embedding provider or MCP process. Choose the smallest profile
that supplies the required capabilities.

This guide covers the published RC1 library and explicit operational boundaries. Current versions are Python `1.0.0rc1` and npm `1.0.0-rc.1`. See [RC1 notes](releases/V6.md) for recorded acceptance and limitations. Source builds, native backend mechanics, live-model quality and production operation require separate evidence.

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

LangChain is another separate optional artifact; its installation guidance is in
[development.md](development.md). MCP is a transport over the same native retrieval
contracts, not a database or identity service. Tool input cannot choose trusted scope
or expose database credentials. The supported host transport is stdio; this guide does
not deploy an HTTP service.

## Build and install local artifacts

Use [public package validation](development.md#public-package-validation) to build and check all six packages without private workbench inputs. Choose fresh output directories. Maintainer regression and native checks use the separate private harness; a package/import pass is not a live backend or model-quality result.

Install the exact reviewed local wheel/tarball into a fresh application environment when evaluating a source change. Select only needed extras: Python `postgres`, `qdrant` or `tokenizers`, and Node optional peers `pg@8.23.1` or `tiktoken@1.0.22`. Install matching local core artifacts alongside optional LangChain/MCP artifacts so their exact-version dependency resolves to the intended product. See [development](development.md) and package manifests for current commands.

For registry RC1 use the pinned package versions in [README](../README.md#quick-start). Local source builds and registry files have separate identities; do not label newly built bytes as the previously accepted registry products. Installation does not select or call an embedding provider, start a database or apply migrations.

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

Native maintainer acceptance retains a deadline scenario with an independently held HTTP request, successor refusal and managed recovery, plus a supervisor-pause scenario. Those harnesses and their exact server binaries/receipts remain private. They require explicitly owned disposable PostgreSQL/Qdrant targets and separate local-process admission; the routine private regression runner does not start those services.

For an authorized native run, select one language suite at a time, a fresh private output directory and the exact supported server profiles. Record process/storage ownership and actual cleanup. Success must include verified client closure, worker reaping, stopped owned servers, listener absence and removal of owned fixture storage. A cleanup failure remains a failed run; do not delete unrelated processes or data. A paused-supervisor refusal demonstrates fencing, not automatic failover.

See [development](development.md#private-maintainer-verification) for the private harness boundary. Current source/native operational results and installed-artifact import/MCP round trips remain separate evidence.

As a small exercise, choose between PostgreSQL lexical and Qdrant dense for a local
application with no embedding credential. List the dependencies and explain why an
unknown Qdrant dispatch must remain blocked after its worker exits.
