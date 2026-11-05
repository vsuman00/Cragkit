# Qdrant integration

For example, an application can search a Qdrant vector collection for a runbook,
then ask PostgreSQL to verify the nominated revision, current access and exact
source bytes. A stale Qdrant grant never authorizes returning the runbook text.

Cragkit supports optional Qdrant candidate retrieval and a managed publication
path. Qdrant is a candidate replica; the reference source and authorization
authority remains PostgreSQL. The current corrective adapter is dense-only.
It does not provide PostgreSQL lexical search, hybrid retrieval or BM25.

Use [the API reference](../api-reference.md) for every constructor and method,
[operations](../v5-operations.md) for ownership, and
[managed publication](../qdrant-publication.md) for staging, repair, security
convergence and purge. The supported profiles are deliberately narrow; the
[RC1 notes](../releases/V6.md) describe the recorded scope and limitations.

## Install the application dependencies

Choose your application's native runtime. Python requires `>=3.14,<3.15`:

```sh
python -m pip install 'cragkit[postgres,qdrant,tokenizers]==1.0.0rc1'
```

Node requires `>=26.5.0 <27`:

```sh
npm install 'cragkit@1.0.0-rc.1' 'pg@8.23.1' 'tiktoken@1.0.22'
```

The Python `qdrant` extra supplies HTTPX; Node includes
`FetchQdrantTransport` using native fetch. No Qdrant SDK, Python server for Node,
local model or provider credential is needed merely to import these modules.
The reference source store needs the PostgreSQL driver. A real embedding path
also needs the supported tokenizer asset and an application-owned model
transport. Installing these packages starts no server and applies no migration.

## Prepare the backend and authority

The candidate adapter admits this declared profile:

| Setting | Accepted configuration |
| --- | --- |
| Server | Single-node Qdrant `1.20.0`; clustering disabled |
| Dense vector | Exactly one named `dense` vector, 1536 dimensions, `Cosine`, no multivector configuration |
| Replication | `replication_factor=1`, `write_consistency_factor=1` |
| Dense model | Exact `FAKE_PROFILE` or `OPENAI_PROFILE` identity; not an arbitrary 1536-dimensional model |
| Real dense profile | `openai_te3small_1536_r1`, `text-embedding-3-small`, `cl100k_base`, L2 normalization |
| Optional sparse vector | Exact synthetic `SPARSE_PROFILE`, named `sparse`, without an IDF modifier; supported only with the fake dense profile |
| Required filters | String `eq`/`in`, combined with `and`/`or`; other operators are rejected |

The sparse profile is caller-supplied synthetic fixture data. It is not a
production sparse encoder, a general sparse-model plugin or BM25. The dense
corrective backend rejects modes other than `dense` even if a candidate store
declares sparse capability.

The application/operator must provision the Qdrant collection and compatible
canonical source records. Calling `initialize` verifies admission; it does not
create a collection or infer an embedding model from its dimension count.

Apply the exact [Qdrant PostgreSQL authority profile](../../storage/qdrant/postgres/README.md)
with separate operator privileges. This uses the `cragkit_qdrant` namespace and
its own migration history, rather than assuming the ordinary PostgreSQL
retriever schema is interchangeable. Publication, attestation, security and
erasure profiles add their declared migrations in order; see
[publication setup](../../storage/qdrant/postgres/PUBLICATION.md).

Open a bounded least-privilege `PoolResource` for source reads. Use explicit
host/database/user fields, an absolute trusted CA path and an owner-only
password file as shown in the [README](../../README.md#retrieve-from-postgresql)
and [connection guide](../neon.md). Keep the pool open for the application
lifetime. Neither a migration-owner connection nor a Qdrant API key substitutes
for the trusted source-reader role.

## Keep configuration and secrets in the application

Cragkit supplies no shared key and does not load `.env` files. Each application
may load its private development `.env` or production secret configuration
before constructing the clients. In the examples below, application code reads
these names from the process environment:

| Variable | Meaning |
| --- | --- |
| `APP_QDRANT_URL` | Verified HTTPS origin with no embedded credentials, query or path prefix |
| `APP_QDRANT_API_KEY` | Optional private Qdrant read credential; never put it in the request or scope |
| `APP_QDRANT_NAMESPACE` | Registered backend namespace |
| `APP_QDRANT_COLLECTION` | Physical Qdrant collection name |
| `APP_QDRANT_INCARNATION` | Registered collection-incarnation identity |

These are example application variable names, not Cragkit environment variables.
The namespace, physical collection, incarnation and complete embedding profile
must match the authority and published point payloads. A logical request
collection, such as `handbook`, is separate from the physical Qdrant collection.

HTTPS certificate verification is required for remote endpoints. Explicit
loopback development HTTP can be enabled with `allow_loopback_http=True` in
Python or `allow_loopback_http: true` in Node; it is disabled by default. The
built-in candidate transports do not provide arbitrary write access. Managed
publication uses supervisor-issued transports and its own credential fencing.

## Construct dense retrieval in Python

The function below is an integration boundary for an application that already
owns an opened source-reader pool, an embedding transport, a matching token
counter and an approved embedding policy. It creates and closes its own search
transport/stores. For a server, retain compatible stores between requests and
close them at shutdown; the stores admit one operation/request handle at a time.

The supplied embedding transport must implement
`async __call__(body: bytes, *, deadline: float, max_response_bytes: int) -> bytes`.
Application code attaches its private provider credential, sends the original
request bytes to the selected embedding endpoint, bounds streamed response bytes
and obeys cancellation/deadline. The expected response is the E-r1 model/data/
usage JSON shape, not an arbitrary SDK object. The adapter validates profile,
item order, dimensions, finite vectors and normalization. See
[embedding contract](../../contracts/EMBEDDINGS_V2.md).

For `OPENAI_PROFILE`, load a context counter with
`Cl100kCounter.from_file(your_pinned_asset_path)`. Its asset must already exist
and match the declared hash. The embedding protocol requires `name`, so adapt
the loaded counter as follows:

```python
class EmbeddingTokenCounter:
    name = "cl100k_base"

    def __init__(self, context_counter):
        self._counter = context_counter

    def count(self, text: str) -> int:
        return self._counter.count(text)
```

Pass `EmbeddingTokenCounter(context_counter)` as `token_counter` below. A live policy must explicitly set `allow_live=True`, a permitted
`max_cost_usd` and the application's current `usd_per_million_tokens`; no price
is embedded in this guide. The transport and its provider client remain
application-owned. Read the [disclosure and budget contract](../../contracts/EXECUTION_V4.md)
before passing private query text to a provider.

```python
import asyncio
import os

from cragkit.contracts import RetrievalRequest, TrustedScope, parse_result
from cragkit.corrective import CorrectiveRetriever
from cragkit.embeddings import (
    OPENAI_PROFILE, EmbeddingPolicy, EmbeddingTransport, TokenCounter,
)
from cragkit.postgres import PoolResource
from cragkit.qdrant import HttpxQdrantTransport, QdrantSearchStore
from cragkit.qdrant_corrective import QdrantCorrectiveBackend
from cragkit.qdrant_source import PostgresQdrantSourceStore


async def retrieve_qdrant(
    scope: TrustedScope,
    source_resource: PoolResource,
    *,
    embedding_transport: EmbeddingTransport,
    token_counter: TokenCounter,
    embedding_policy: EmbeddingPolicy,
):
    config = {
        "backend_namespace": os.environ["APP_QDRANT_NAMESPACE"],
        "physical_collection": os.environ["APP_QDRANT_COLLECTION"],
        "collection_incarnation": os.environ["APP_QDRANT_INCARNATION"],
        "dense_profile": OPENAI_PROFILE.model_dump(mode="json"),
        "sparse_profile": None,
    }
    transport = HttpxQdrantTransport(
        os.environ["APP_QDRANT_URL"],
        api_key=os.environ.get("APP_QDRANT_API_KEY"),
    )
    candidates = QdrantSearchStore(config, transport)
    sources = PostgresQdrantSourceStore(source_resource, config)
    deadline = asyncio.get_running_loop().time() + 10
    try:
        await candidates.initialize(deadline=deadline)
        await sources.initialize(deadline=deadline)
        backend = QdrantCorrectiveBackend(
            candidates, sources,
            embedding_transport=embedding_transport,
            token_counter=token_counter,
            policy=embedding_policy,
            mode="dense",
        )
        retriever = CorrectiveRetriever(backend, batch_size=8)
        response = await retriever.retrieve(
            RetrievalRequest(
                query="What is the retry limit?",
                collection="handbook",
                limits={
                    "max_attempts": 1,
                    "max_subqueries": 1,
                    "max_candidates": 8,
                    "max_provider_calls": 1,
                },
                output_profile={"renderer": "cragkit.context.v2"},
            ),
            scope=scope,
            deadline=deadline,
        )
        return parse_result(response["result"]), response["diagnostics"]
    finally:
        try:
            await sources.close()
        finally:
            try:
                await candidates.close()
            finally:
                await transport.close()
```

The trusted `scope` comes from authenticated application code. The pool, token
counter and model transport are borrowed; this function leaves them open.
`cragkit.context.v2` is required by `CorrectiveRetriever`; the default v1 output
profile used by the simpler lexical retriever is not accepted here. With no
reviewed assessment policy supplied, coverage remains conservative rather than
becoming sufficient from vector similarity alone.

## Construct dense retrieval in TypeScript

The same graph runs natively in Node. The embedding transport signature is
`(body: Uint8Array, options: {deadline, signal, max_response_bytes}) =>
Promise<Uint8Array>`. Load the matching local context counter with
`await Cl100kCounter.create(your_pinned_asset_path)`, then pass
`{name: "cl100k_base", count: (text: string) => contextCounter.count(text)}`
as the embedding `TokenCounter`. Close the owned context counter at application
shutdown. Supply an explicit live policy with the same fields as
Python, using application-reviewed pricing and spending limits.

```typescript
import { parse_request, type TrustedScope } from 'cragkit/contracts';
import { CorrectiveRetriever } from 'cragkit/corrective';
import {
  OPENAI_PROFILE,
  type EmbeddingPolicy, type EmbeddingTransport, type TokenCounter,
} from 'cragkit/embeddings';
import { now, type PoolResource } from 'cragkit/postgres';
import { FetchQdrantTransport, QdrantSearchStore } from 'cragkit/qdrant';
import { QdrantCorrectiveBackend } from 'cragkit/qdrant-corrective';
import { PostgresQdrantSourceStore } from 'cragkit/qdrant-source';

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing application setting: ${name}`);
  return value;
}

async function retrieveQdrant(
  scope: TrustedScope,
  sourceResource: PoolResource,
  embeddingTransport: EmbeddingTransport,
  tokenCounter: TokenCounter,
  embeddingPolicy: EmbeddingPolicy,
) {
  const config = {
    backend_namespace: required('APP_QDRANT_NAMESPACE'),
    physical_collection: required('APP_QDRANT_COLLECTION'),
    collection_incarnation: required('APP_QDRANT_INCARNATION'),
    dense_profile: OPENAI_PROFILE,
    sparse_profile: null,
  };
  const apiKey = process.env.APP_QDRANT_API_KEY;
  const transport = new FetchQdrantTransport(
    required('APP_QDRANT_URL'),
    apiKey === undefined ? {} : { api_key: apiKey },
  );
  const candidates = new QdrantSearchStore(config, transport);
  const sources = new PostgresQdrantSourceStore(sourceResource, config);
  const deadline = now() + 10;
  try {
    await candidates.initialize({ deadline });
    await sources.initialize({ deadline });
    const backend = new QdrantCorrectiveBackend(candidates, sources, {
      embedding_transport: embeddingTransport,
      token_counter: tokenCounter,
      policy: embeddingPolicy,
      mode: 'dense',
    });
    const retriever = new CorrectiveRetriever({ backend, batch_size: 8 });
    return await retriever.retrieve(parse_request({
      query: 'What is the retry limit?',
      collection: 'handbook',
      limits: {
        max_attempts: 1, max_subqueries: 1,
        max_candidates: 8, max_provider_calls: 1,
      },
      output_profile: { renderer: 'cragkit.context.v2' },
    }), { scope, deadline });
  } finally {
    try {
      await sources.close();
    } finally {
      try {
        await candidates.close();
      } finally {
        await transport.close();
      }
    }
  }
}
```

These functions are construction examples, not a backend fixture or a provider
benchmark. They require admitted services, published source/vector generations
and application-owned dependencies. They perform an embedding call when invoked;
installation and construction alone do not. Return values contain `result` and
`diagnostics`; inspect `status`, `execution`, `limitations`, usage and stop reason
before deciding whether your application should answer.

## Use the candidate/source interfaces directly

The lower-level boundary is useful when an application owns orchestration:

1. Create `ExecutionLedger` from the validated request limits and effective
   deadline.
2. Supply a fully bound E-r1 dense batch to `search_candidates`, with separate
   trusted scope and explicit `branch_limits`. Raw dense arrays are admitted only
   for the fake profile. The combined candidate branch allowance is at most 64
   and cannot exceed the request/ledger budget.
3. Open a source handle with `sources.open_request(request, scope=...,
   deadline=...)` in Python or `sources.open_request(request, {scope, deadline})`
   in Node.
4. Use `fetch_candidate` to validate the nomination against current SQL authority.
   If verified, retain its opaque `binding` within that request handle only.
5. Use `release(binding, purpose="provider"/"final", ...)` in Python or the
   equivalent Node options to reauthorize the relevant release. `include_source`
   enables a private canonical buffer for packing; do not log or return that
   buffer as public evidence.
6. Close the request handle and ledger in `finally`. Close stores before the
   application-owned HTTP client/pool.

`SourceFetch.state` is `verified`, `unavailable` or `budget_exhausted`. Its safe
serialization omits the binding and private source. A copied binding, another
request's binding, repeat release or changed authority is rejected or produces
the appropriate unavailable outcome. Source reads charge actual loaded bytes,
including later-invalid data, against a fixed bounded request budget.

The candidate transport must advertise `bounded_responses=True` and
`cancellation_safe=True` in Python, or literal `true` in Node. Its
`request(method, path, body/deadline/options)` returns bounded raw JSON bytes;
`QdrantTransport` has no source-release method. Store close does not close an
injected transport. A custom transport must provide equivalent deadline,
cancellation, byte-limit and TLS behavior. An uncancellable transport cannot
silently permit another branch to start.

See [candidate contract](../../contracts/QDRANT_CANDIDATES_V5.md),
[source contract](../../contracts/QDRANT_SOURCES_V5.md) and
[corrective composition](../../contracts/QDRANT_CORRECTIVE_V5.md) for exact shapes
and release limits. The API reference lists the native method signatures.

## Publish, repair and remove data

Use `QdrantPublicationManager`, not the candidate HTTP transport, for the
supported managed write path. The native dependency graph is:

```text
opened writer PoolResource -> PostgresQdrantWriter
owned initialized ManagedQdrantSupervisor -> QdrantReconciliationVerifier
opened supervisor PoolResource + verifier -> PostgresQdrantRecovery
writer + recovery -> PostgresQdrantPublicationAuthority
same actual supervisor -> ManagedQdrantPublicationTransport
authority + transport + config + same supervisor + authorize_write
    -> QdrantPublicationManager
```

The supervisor constructor takes an absolute owned binary path, absolute owned
work directory, instance identity and configuration. Python uses `Path` objects;
Node uses its declared scalar/options signatures. Its explicit `initialize`
starts and controls the supported owned process lifecycle and validates registered
profiles. Construction does not install Qdrant, provision a cloud collection or
support arbitrary externally managed writers. Replica clusters, automatic
supervisor takeover and general QD-r1 support are outside the declared profile.

| Operation | Meaning |
| --- | --- |
| `stage` | Persist the complete immutable source, manifest, original vectors and explicit initial authorization. It makes no embedding call. |
| `publish` | Write admitted batches, validate actual completed acknowledgments, read back the complete expected scoped set and commit the authoritative generation switch. |
| `repair` | Recover uncertainty or missing original points with genuine refencing and complete verification before publication. |
| `QdrantSecurityManager.update_authorization` / `tombstone` | Commit current SQL authorization/tombstone independently of vector publication admission. |
| `converge_security` | Repair and verify the claimed replica authorization state after a committed current-security intent. |
| `purge` | Erase the managed source/replay scope under the explicit retention policy and native security-owner profile. |
| `ManagedQdrantPublicationWorkerHost.publish` | Publish a previously staged intent in one owned native worker while the parent retains its supervisor. |

Use the exact constructor and input examples in
[managed publication](../qdrant-publication.md). Managers borrow their writer,
recovery, transports, supervisor and pools. Shutdown must close/reap worker hosts,
close managers and their owned verification/attempt handles, close borrowed
dependencies through their application owners, and close the supervisor last.
The Python reconciliation verifier has no separate `close`; its Node counterpart
does. Follow each runtime's actual lifecycle rather than inventing a common
method.

## Failures worth handling

A collection with the wrong dimension or version fails initialization. The
adapter does not resize it. A real batch with a fake profile or the wrong model
identity fails profile validation. Neither error is evidence that the document
is absent.

If Qdrant nominates a document after its access was revoked, the PostgreSQL
source authority prevents release. If that authority is unavailable, the request
fails operationally; it does not turn into an empty successful search. A source
digest/span mismatch is an integrity error.

If a managed worker disappears after dispatch, its write may still have reached
Qdrant. Killing the worker, counting points or receiving an HTTP acknowledgment
does not prove the source generation was published. Durable uncertainty blocks
conflicting work until genuine managed repair/refencing and settlement pass.

For a small exercise, inspect `QdrantSearchStore.capabilities()` without opening
any provider client. Identify why `source_authority=false` requires a separate
source release gate, and why a synthetic sparse capability does not enable dense
corrective hybrid search. Native integration, live-provider quality and
production acceptance require separate checks described in
[development](../development.md).
