# Cragkit for Python

Cragkit is a native Python retrieval library for applications that need passages
with source references, coverage estimates, limitations and execution diagnostics.
Use it behind document assistants, RAG pipelines and agent tools. Your application
owns authentication, documents, model clients and the final answer.

This is the core package. LangChain and MCP integrations are separate optional
packages; Python execution does not require a Cragkit server.

This release updates package descriptions and version metadata. Runtime behavior
is unchanged from RC1. See the [RC2 release notes](https://github.com/vsuman00/Cragkit/blob/main/docs/releases/RC2.md).

## Install

Requires Python `>=3.14,<3.15`. The current version is a release candidate.

```sh
python -m pip install "cragkit==1.0.0rc2"
```

Install only the integrations your application needs:

```sh
python -m pip install "cragkit[postgres]==1.0.0rc2"
python -m pip install "cragkit[qdrant]==1.0.0rc2"
python -m pip install "cragkit[tokenizers]==1.0.0rc2"
```

These extras install clients or tokenizer support. They do not provision a
database, apply migrations, download model assets or configure credentials.

## Try it without a service

This complete example validates a request and trusted scope, then checks exact
UTF-8 source spans. It makes no database or model calls.

```python
from cragkit.canonical import canonicalize
from cragkit.contracts import parse_request, parse_scope
from cragkit.errors import InvalidRequest

request = parse_request({
    "query": "What is the retry policy?",
    "collection": "engineering",
    "limits": {"max_provider_calls": 0},
})
scope = parse_scope({
    "tenant_id": "example-tenant",
    "principal_id": "example-user",
    "authorization_revision": "r1",
    "grant_ids": ["engineering-read"],
})

document = canonicalize("Café policy\r\nRetry three times.\r\n")
source = document.canonical_text.encode("utf-8")
for chunk in document.chunks:
    assert source[chunk.start_byte:chunk.end_byte].decode("utf-8") == chunk.text

print(request.collection, scope.tenant_id, len(document.chunks))

try:
    parse_request({"query": "", "collection": "engineering"})
except InvalidRequest as error:
    print(error.code)  # invalid_request
```

The scope above is synthetic. In an application, resolve it from authenticated
identity and current authorization. Bind it outside model-editable input; a
caller who can invent trusted scope can defeat the access boundary.

## Connect retrieval to your application

- PostgreSQL with pgvector and native full-text search is the reference backend.
  Native PostgreSQL FTS is not BM25.
- Qdrant provides an optional candidate search path with an authoritative source
  and access boundary. It requires explicit setup.
- Embedding, reranking and planning adapters accept application-supplied
  transports. Bring your own provider credentials or configured local runtime.
- Exact excerpts retain canonical UTF-8 byte offsets, revision identities and
  digests. Source fidelity does not establish source truth or relevance.
- Retrieval budgets cover deadlines, attempts, candidates and provider calls.
  Estimated token counting is not a hard model-token ceiling; strict counting
  needs the supported tokenizer and actual serialized representation.

Import application classes from their modules, such as
`from cragkit.postgres import PostgresRetriever`. The package root exposes the
version; it is not an umbrella import for every class. Open resources explicitly
and close application-owned pools and clients when finished.

Core imports do not connect to databases, contact model providers, load project
`.env` files or apply migrations. Cragkit supplies no built-in provider key and
requires no Cragkit API key. Configure secrets in your consuming application and
inject its clients; never put secrets in retrieval or tool arguments.

## Read the result honestly

`status` estimates coverage as `sufficient`, `partial` or `insufficient`.
`execution` separately reports `complete` or `degraded`. A search can complete
and still lack evidence. Unknown coverage cannot become sufficient; operational
errors remain errors. Inspect evidence, facets and limitations before answering.

Release-candidate checks cover declared configurations and bounded workloads. They do not
establish universal model quality, all-platform compatibility or production
acceptance for your application. Cragkit does not supply OCR, crawling, final
answer generation or answer verification.

## Documentation and license

- [Application setup and retrieval example](https://github.com/vsuman00/Cragkit/blob/main/README.md)
- [API reference](https://github.com/vsuman00/Cragkit/blob/main/docs/api-reference.md)
- [PostgreSQL setup](https://github.com/vsuman00/Cragkit/blob/main/storage/postgres/README.md)
- [Qdrant setup](https://github.com/vsuman00/Cragkit/blob/main/docs/integrations/qdrant.md)
- [RC1 scope and limitations](https://github.com/vsuman00/Cragkit/blob/main/docs/releases/V6.md)

GitHub guides require access while the source repository remains private. The
example above is self-contained for registry consumers. Project code is licensed
under [MIT](https://github.com/vsuman00/Cragkit/blob/main/LICENSE); dependencies,
models and provider services have their own licenses, terms and costs.
