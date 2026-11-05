# API reference

For example, import `PostgresRetriever` from `cragkit.postgres` in Python or
`cragkit/postgres` in Node, construct it with an opened `PoolResource`, and pass
trusted scope separately from the request. The package root exports only the
version: `cragkit.__version__` in Python and `version` in TypeScript.

This reference covers the native interfaces and optional LangChain/MCP packages.
Current Python packages use `1.0.0rc3`; npm packages use `1.0.0-rc.2`. Use the
[README](../README.md) for installation and a first retrieval call,
[development guide](development.md) for source builds, and
[contracts](../contracts/README.md) for validation rules and failure behavior.
These are signatures and behavior contracts, not a claim that a backend,
provider, deployment or result quality has been verified in your application.

Jump to [request/result fields](#requests-source-references-and-results),
[ownership](#resource-ownership-and-cancellation), [errors](#errors),
[Python signatures](#python-modules), [TypeScript signatures](#typescript-modules),
or [MCP setup](#mcp-packages).

## Choose an entry point

| Task | Python | TypeScript |
| --- | --- | --- |
| Validate requests, trusted scope and results | `cragkit.contracts` | `cragkit/contracts` |
| Open a bounded PostgreSQL resource | `cragkit.postgres` | `cragkit/postgres` |
| Ingest text/Markdown and publish lexical generations | `PostgresIndexer` | `PostgresIndexer` |
| Embed, stage and publish vector generations | `PostgresVectorIndexer` | `PostgresVectorIndexer` |
| Retrieve lexical, dense or hybrid PostgreSQL evidence | `PostgresRetriever` | `PostgresRetriever` |
| Run bounded corrective retrieval | `cragkit.corrective.CorrectiveRetriever` | `cragkit/corrective` |
| Supply a PostgreSQL corrective backend | `cragkit.postgres_corrective` | `cragkit/postgres-corrective` |
| Search the optional Qdrant candidate replica | `cragkit.qdrant` | `cragkit/qdrant` |
| Read authoritative source data for Qdrant nominations | `cragkit.qdrant_source` | `cragkit/qdrant-source` |
| Compose dense Qdrant corrective retrieval | `cragkit.qdrant_corrective` | `cragkit/qdrant-corrective` |
| Manage Qdrant publication, repair and erasure | `cragkit.qdrant_publication` | `cragkit/qdrant-publication` |
| Inject embedding/reranking/planning transports | `cragkit.embeddings`, `.reranking`, `.planning` | `cragkit/embeddings`, `/reranking`, `/planning` |
| Render, count, pack and assess exact excerpts | `cragkit.context`, `.packing`, `.assessment`, `.evidence` | Corresponding `/context`, `/packing`, `/assessment`, `/evidence` subpaths |
| Account for calls, candidates, attempts and cost | `cragkit.execution` | `cragkit/execution` |
| Export bounded redacted events | `cragkit.events` | `cragkit/events` |
| Expose a scope-bound LangChain tool | `cragkit_langchain.create_tool` | `cragkit-langchain` |
| Serve the retrieval-only MCP tool | `cragkit_mcp.create_server` | `cragkit-mcp` |

TypeScript supports only the subpaths declared in its package `exports` map.
Internal files such as `canonical.ts` and `fusion.ts` are not independent npm
entry points. Python's `canonical`, `ingestion`, `lifecycle`, `retrieval` and
`vector_ingestion` modules can also be imported directly. The PostgreSQL entry
point reexports their application classes.

## Requests, source references and results

`parse_request`, `parse_tool_request`, `parse_scope` and `parse_result` validate
native data and convert boundary failures to `InvalidRequest`. Python models
are strict, frozen Pydantic models. TypeScript exposes Zod schemas, inferred
types and parsed frozen values. Model construction can also report its runtime's
native validation error; use the parser functions when you need Cragkit's error
boundary.

| Object | Fields and purpose |
| --- | --- |
| `ToolRequest` | `schema_version`, `request_id`, `query`, `collection`, `search_hints`. This is the narrow model-facing input. |
| `RetrievalRequest` | Tool fields plus `required_filters`, `limits`, `output_profile`. Filters and limits are application-controlled when using a tool wrapper. |
| `TrustedScope` | `tenant_id`, `principal_id`, `authorization_revision`, `grant_ids`. Resolve these from trusted application identity before calling Cragkit. |
| `Limits` | `deadline_ms`, `max_attempts`, `max_subqueries`, `max_candidates`, `max_context_tokens`, `max_provider_calls`, `max_spend_usd`. Individual adapters can impose smaller bounds. |
| `OutputProfile` | `renderer`, `tokenizer`, `envelope_reserve_tokens`, `counting_mode`. Strict counting requires the supported tokenizer and actual serialized output. |
| `Evidence` | `evidence_id`, collection/document/revision/chunk identity, `source_locator`, `start_byte`, `end_byte`, exact `text`, source/text SHA-256 digests. Spans use canonical UTF-8 byte offsets. |
| `Facet` | `facet_id`, `question`, `required`, `state`, `evidence_ids`, `assessment_method`, `assessment_version`. States are `supported`, `missing`, `unknown` or `conflicting`. |
| `RetrievalResult` | `schema_version`, `request_id`, `status`, `execution`, `evidence`, `facets`, `context`, `limitations`, `usage`, `versions`, `trace_id`. |
| `Usage` | Attempt/provider-call counts, input/output tokens, cost amount/kind, context tokens/counting mode and `stage_durations`. Unknown provider usage remains unknown. |
| `Versions` | Engine, policy, model, tokenizer and index identifiers. These identify the configuration used; they are not quality scores. |
| `Limitation` | A closed limitation `code` and optional `facet_ids`/`evidence_ids`; inspect it alongside coverage and execution. |
| `StageDuration` | Stage name and measured `duration_ms`. |

An empty `grant_ids` list does not by itself mean no access: current authority
can permit the bound principal directly. Applications must resolve the complete
identity and current authorization; they cannot use a grant-list shortcut to
infer denial or permission.

Defaults are 10,000 ms, three attempts, four subqueries, 200 candidates, 2,000
context tokens and 16 provider calls, with no declared spend ceiling. An adapter
does not have to support every schema maximum or every filter operator. Qdrant's
current filter subset is string `eq`/`in` with `and`/`or`.

`status` estimates evidence coverage: `sufficient`, `partial` or `insufficient`.
`execution` separately records `complete` or `degraded`. A complete search can
still be insufficient. The default PostgreSQL lexical path does not assess
semantic support: it returns `coverage_unknown` and cannot return sufficient
coverage merely because a term matched. Reviewed span policies can assess their
declared facets; an excerpt's fidelity does not prove its relevance or truth.

Request, scope and result JSON schemas are under
[contracts/schemas/0.1](../contracts/schemas/0.1/).
See [result semantics](../contracts/RESULTS.md),
[retrieval](../contracts/RETRIEVAL_V1.md) and
[execution](../contracts/EXECUTION_V4.md) for the complete limits.

## Resource ownership and cancellation

Constructors do not open pools, migrate schemas, download models, load project
`.env` files or start MCP/Qdrant processes. Open `PoolResource` explicitly, then
close it in `finally`. The application owns CA/password files, provider keys,
transports and database roles. A retriever borrows its backend and clients.

Deadlines are absolute monotonic seconds: use
`asyncio.get_running_loop().time()` in Python and `now()` from
`cragkit/postgres` or `performance.now() / 1000` in Node. Do not pass a wall-clock
timestamp or a duration where a deadline is required. Python uses task
cancellation. TypeScript operations accept `AbortSignal` where their signature
declares one.

`PoolResource.open()` validates private connection configuration and establishes
pool connectivity. Backend/session operations separately validate the selected
schema, catalog and role before source operations. `lease()` in Python and `withLease()` in Node bound connection ownership.
Retrievers and indexers do not close the resource they borrow. Qdrant stores
require `initialize()` before operations, admit one operation/request handle at
a time, and leave injected transports and PostgreSQL resources open on close.
Close store/request handles first, then application-owned clients/resources.
Managed Qdrant controllers own the process they explicitly start; their close
operation is different from closing a borrowed search transport.

`Cl100kCounter.from_file()` in Python and `Cl100kCounter.create()` in Node load a
caller-supplied pinned tokenizer asset. They do not download it. Node's counter
has `close()`; Python's counter does not. The embedding `TokenCounter` protocol requires a `name` field. A context counter
does not supply that protocol directly: adapt it with `name="cl100k_base"` and
forward `count(text)` to the loaded `Cl100kCounter`. Estimated counting is a
byte-based estimate, not a hard model-token ceiling. Wrapper serializers must count the
actual outer tool/MCP output too.

## Errors

Catch exported classes from `cragkit.errors` or `cragkit/errors`. Their public
messages are fixed and redacted. `CragkitError.to_dict()` produces an error
envelope; Node additionally supplies `toJSON()`.

| Class | Code | Meaning |
| --- | --- | --- |
| `InvalidRequest` | `invalid_request` | Invalid shape, scalar, option or state transition. |
| `UnauthorizedScope` | `unauthorized_scope` | Trusted scope or current authorization denies the operation. |
| `UnsupportedCapability` | `unsupported_capability` | The selected profile, dependency, tokenizer or operation is not supported. |
| `IndexNotReady` | `index_not_ready` | Required initialization or index state is absent. |
| `EmbeddingProfileMismatch` | `embedding_profile_mismatch` | Supplied model/vector identity does not match the configured profile. |
| `ProviderUnavailable` | `provider_unavailable` | Provider/resource unavailable, including rejected concurrent admission. |
| `DeadlineExceeded` | `deadline_exceeded` | The shared operation deadline expired. |
| `ContextBudgetTooSmall` | `context_budget_too_small` | The selected serialized output cannot fit the configured budget. |
| `IntegrityViolation` | `integrity_violation` | Source, digest, identity, profile or durable-state validation failed. |

`BudgetExhausted` belongs to the execution module. It signals that the next
reservation cannot fit the ledger. It is distinct from a search that finds no
evidence. Python cancellation and Node abort behavior also remain distinct from
missing evidence. See [error envelopes](../contracts/RESULTS.md).

## Ingestion and lifecycle

For example, `PostgresIndexer.ingest("Restart the worker.", collection="ops",
document_id="runbook", intent_id="import-1", source_locator="runbook.md", ... )`
canonicalizes one source and publishes its generation through the explicit
writer resource. An application authorizer must approve that trusted scope and
document. A retrieval role cannot be used as the writer.

`canonicalize` accepts text/Markdown and returns canonical text, parser/chunker
identity, source/canonical digests and chunks with exact byte spans.
`PostgresIndexer.ingest` adds immutable revision/generation publication and an
idempotency receipt. `PostgresVectorIndexer.stage` computes and stages the vector
generation; `publish`/`ingest` complete publication. Retrying an intent with
different payload bytes is an integrity failure, rather than a replacement of
the original revision.

The write authorizer is asynchronous and receives `(scope, collection,
document_id)`. Lifecycle authorization additionally receives the action.
`PostgresLifecycle.tombstone` hides the document. `purge_tombstoned` removes
eligible retained data under the lifecycle contract. Both require an explicit
expected generation and trusted scope. Qdrant uses its own managed security,
convergence and purge interfaces; see the
[Qdrant integration guide](integrations/qdrant.md).

## Optional tool wrappers

Bind `template` and `scope` in trusted host code. The template contains
`collection`, and optionally `required_filters`, `limits`, `output_profile`.
The model can supply only the `ToolRequest` fields. A collection mismatch is
rejected. The synchronous `final_serializer` must serialize the actual wrapper
object that your application will send; it is part of budget verification.

Python's LangChain factory is
`create_tool(engine, *, template, scope, final_serializer, counter=None,
name="cragkit_retrieve")`. Node uses one `CreateToolOptions` object. The engine
is the corrective retrieval interface returning `{result, diagnostics}`;
LangChain expects its `result` field. Use `ainvoke` in Python and `invoke` in
Node. The supported narrow tool disables unsupported streaming and batch entry
points; it is not a general LangChain chain implementation.

Python's MCP factory has the same keyword setup without a tool-name option.
Node uses `create_server({engine, template, scope, final_serializer, counter})`.
The MCP engine can return a direct result or a corrective result envelope.
`create_server` returns a `RetrievalHost`; call `run_stdio()` explicitly and
close the host in `finally`. Python also offers `run_streams`; Node exports
`BoundedStdioTransport`. The host exposes one retrieval-only tool, not ingestion
or administrative writes. Resolve authenticated identity outside model input;
the stdio wrapper is not an authentication service.

See the [MCP contract](../contracts/MCP_V5.md),
[token/context contract](../contracts/TOKEN_CONTEXT_V3.md) and native signatures
below before wiring another serializer or transport.

## Native signature catalog

The catalog below names public callables, class/protocol methods, properties, data models,
schemas, types and profile constants. Python signatures use source annotations;
`self`/`cls` are omitted for readability. Python `@property` routes and TypeScript getters are read-only attributes,
written as `name: Type` and accessed without parentheses. Ordinary methods such
as `capabilities()` remain callable. Pydantic models use their named fields
as constructor keywords and provide Pydantic's `model_validate` and
`model_dump` interfaces. Listed model fields are declared fields; subclasses
also retain their base fields. Validation/serialization hooks and underscore
helpers are implementation details, not additional application operations.

The TypeScript catalog follows the package export maps, including reexports.
Type-only exports have no runtime constructor. Signatures describe the source
API and are not a single copy-and-paste program: types imported by a declaration
or opaque proof/receipt names can appear without being exported for application
construction. Use the linked contracts for their wire shapes.

For managed Qdrant dependencies, low-level authority/controller methods are
listed so the exported classes are explainable. Methods involving projections,
attestations, proofs, barriers or owner capabilities support the native managed
graph. Their signatures do not permit applications to mint, copy, serialize or
substitute those values. Use `QdrantPublicationManager` for ordinary application
writes and [managed publication](qdrant-publication.md) for operator flows.

## Python modules

### `cragkit`

Version only. Native execution lives in explicit modules.

Import from `cragkit`. [Module source](../packages/python/src/cragkit/__init__.py).

- `__version__`: Package version string. [Declaration](../packages/python/src/cragkit/__init__.py).

### `cragkit.contracts`

- `Filter`: discriminated union of the concrete filter models below. [Declaration](../packages/python/src/cragkit/contracts/models.py#L67).

Import from `cragkit.contracts`. [Module source](../packages/python/src/cragkit/contracts/__init__.py).

#### `parse_request`

Validate a full retrieval request and apply defaults; reject invalid native input with InvalidRequest.

[Source](../packages/python/src/cragkit/contracts/__init__.py#L33).

```text
parse_request(value: object) -> RetrievalRequest
```

#### `parse_tool_request`

Validate the narrow model-facing request; reject scope, filters or limits supplied as extra tool fields.

[Source](../packages/python/src/cragkit/contracts/__init__.py#L37).

```text
parse_tool_request(value: object) -> ToolRequest
```

#### `parse_scope`

Validate trusted host identity/scope; validation itself does not authenticate the caller.

[Source](../packages/python/src/cragkit/contracts/__init__.py#L41).

```text
parse_scope(value: object) -> TrustedScope
```

#### `parse_result`

Validate cross-field evidence, facets, usage and result invariants.

[Source](../packages/python/src/cragkit/contracts/__init__.py#L45).

```text
parse_result(value: object) -> RetrievalResult
```

#### `EqualityFilter`

Equality/inequality leaf; adapter capabilities can restrict operators.

[Source](../packages/python/src/cragkit/contracts/models.py#L39).

Declared fields: `op`, `field`, `value`.


#### `GroupFilter`

Bounded and/or filter group.

[Source](../packages/python/src/cragkit/contracts/models.py#L57).

Declared fields: `op`, `filters`.


#### `Limits`

Request-wide ceilings; see the request table above and adapter-specific limits.

[Source](../packages/python/src/cragkit/contracts/models.py#L76).

Declared fields: `deadline_ms`, `max_attempts`, `max_subqueries`, `max_candidates`, `max_context_tokens`, `max_provider_calls`, `max_spend_usd`.


#### `MembershipFilter`

Bounded membership leaf.

[Source](../packages/python/src/cragkit/contracts/models.py#L51).

Declared fields: `op`, `field`, `values`.


#### `NotFilter`

Negated filter; only adapters declaring it may accept it.

[Source](../packages/python/src/cragkit/contracts/models.py#L62).

Declared fields: `op`, `filter`.


#### `OrderFilter`

Numeric order leaf; unsupported backends reject it.

[Source](../packages/python/src/cragkit/contracts/models.py#L45).

Declared fields: `op`, `field`, `value`.


#### `OutputProfile`

Renderer, tokenizer, wrapper reserve and counting mode.

[Source](../packages/python/src/cragkit/contracts/models.py#L86).

Declared fields: `renderer`, `tokenizer`, `envelope_reserve_tokens`, `counting_mode`.


#### `RetrievalRequest`

Full application retrieval request, including required filters, limits and output profile.

[Source](../packages/python/src/cragkit/contracts/models.py#L107).

Declared fields: `required_filters`, `limits`, `output_profile`.


#### `ToolRequest`

Narrow model-facing request; scope and required filters are absent.

[Source](../packages/python/src/cragkit/contracts/models.py#L99).

Declared fields: `schema_version`, `request_id`, `query`, `collection`, `search_hints`.


#### `TrustedScope`

Trusted application-bound tenant/principal/authorization/grant identity.

[Source](../packages/python/src/cragkit/contracts/models.py#L113).

Declared fields: `tenant_id`, `principal_id`, `authorization_revision`, `grant_ids`.


#### `Evidence`

Exact source-linked evidence with canonical byte spans and digests.

[Source](../packages/python/src/cragkit/contracts/results.py#L33).

Declared fields: `evidence_id`, `collection`, `document_id`, `revision_id`, `chunk_id`, `source_locator`, `start_byte`, `end_byte`, `text`, `source_sha256`, `text_sha256`.


#### `Facet`

Reviewed facet state and supporting evidence references.

[Source](../packages/python/src/cragkit/contracts/results.py#L56).

Declared fields: `facet_id`, `question`, `state`, `required`, `evidence_ids`, `assessment_method`, `assessment_version`.


#### `Limitation`

Closed limitation code.

[Source](../packages/python/src/cragkit/contracts/results.py#L78).

Declared fields: `code`, `facet_ids`, `evidence_ids`.


#### `RetrievalResult`

Validated result envelope with separate coverage and execution state.

[Source](../packages/python/src/cragkit/contracts/results.py#L125).

Declared fields: `request_id`, `status`, `schema_version`, `execution`, `evidence`, `facets`, `context`, `usage`, `limitations`, `trace_id`, `versions`.


#### `StageDuration`

Bounded named stage duration.

[Source](../packages/python/src/cragkit/contracts/results.py#L87).

Declared fields: `stage`, `duration_ms`.


#### `Usage`

Known/estimated/unknown usage and stage timings.

[Source](../packages/python/src/cragkit/contracts/results.py#L92).

Declared fields: `attempt_count`, `provider_calls`, `provider_input_tokens`, `provider_output_tokens`, `cost_usd`, `cost_kind`, `context_tokens`, `context_counting`, `stage_durations`.


#### `Versions`

Engine/policy/model/tokenizer/index identifiers.

[Source](../packages/python/src/cragkit/contracts/results.py#L117).

Declared fields: `engine`, `policy`, `model`, `tokenizer`, `index`.



### `cragkit.postgres`

This facade reexports the application-facing PostgreSQL resource, ingestion, retrieval and lifecycle APIs.

Import from `cragkit.postgres`. [Module source](../packages/python/src/cragkit/postgres.py).

#### `PoolConfig`

Bounded native PostgreSQL configuration. CA and password-file paths are absolute; credentials stay in private files.

[Source](../packages/python/src/cragkit/_postgres_pool.py#L19).

Declared fields: `host`, `port`, `dbname`, `user`, `sslrootcert`, `passfile`, `max_size`, `max_waiting`, `startup_timeout`, `acquire_timeout`, `close_timeout`, `release_timeout`.


#### `PoolResource`

Explicit bounded pool lifecycle. The default owns its driver pool; an injected pool remains caller-owned.

[Source](../packages/python/src/cragkit/_postgres_pool.py#L102).

- `PoolResource(config: PoolConfig, *, pool: PoolProtocol | None=None, factory: Callable[[PoolConfig], PoolProtocol] | None=None) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async open() -> None`: Open and validate the bounded resource before use.
- `async lease(*, deadline: float) -> AsyncIterator[ConnectionProtocol]`: Acquire/release a connection as an async context manager under the shared deadline.
- `async close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `parse_pool_config`

Validate scalar database settings and absolute private credential/CA paths.

[Source](../packages/python/src/cragkit/_postgres_pool.py#L63).

```text
parse_pool_config(value: object) -> PoolConfig
```

#### `IngestionReceipt`

Immutable publication identity and payload/source digests, with replay state.

[Source](../packages/python/src/cragkit/ingestion.py#L28).

Declared fields: `tenant_id`, `collection`, `document_id`, `intent_id`, `revision_id`, `generation_id`, `payload_sha256`, `canonical_sha256`, `chunk_count`, `replayed`.


#### `PostgresIndexer`

Canonicalize and publish lexical source generations through a restricted writer resource.

[Source](../packages/python/src/cragkit/ingestion.py#L271).

- `PostgresIndexer(resource: PoolResource, *, authorize_write: Callable[[TrustedScope, str, str], Awaitable[bool]]) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async ingest(source: str | bytes, *, collection: str, document_id: str, intent_id: str, source_locator: str, scope: TrustedScope, deadline: float, expected_generation_id: str | None=None, metadata: dict[str, object] | None=None, format: str='text/plain', canonical_options: dict[str, Any] | None=None, before_publish: Callable[[], Awaitable[None]] | None=None) -> IngestionReceipt`: Canonicalize and durably publish a generation; matching intent retries report replay instead of mutating immutable payload.

#### `LifecycleReceipt`

Document lifecycle outcome, active generation and whether state changed.

[Source](../packages/python/src/cragkit/lifecycle.py#L27).

Declared fields: `tenant_id`, `collection`, `document_id`, `state`, `active_generation_id`, `changed`.


#### `PostgresLifecycle`

Apply explicitly authorized tombstones and purge eligible tombstoned source records.

[Source](../packages/python/src/cragkit/lifecycle.py#L132).

- `PostgresLifecycle(resource: PoolResource, *, authorize_lifecycle: LifecycleAuthorizer) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async tombstone(*, collection: str, document_id: str, expected_generation_id: str | None, scope: TrustedScope, deadline: float) -> LifecycleReceipt`: Admit the authorized tombstone; replica completion is a separate state.
- `async purge_tombstoned(*, collection: str, document_id: str, expected_generation_id: str | None, scope: TrustedScope, deadline: float) -> LifecycleReceipt`: Purge eligible tombstoned PostgreSQL data after lifecycle authorization and generation checks.

#### `PostgresRetriever`

Borrow an opened PostgreSQL resource for lexical, dense or hybrid retrieval. Optional evidence configuration enables packing/assessment/reranking.

[Source](../packages/python/src/cragkit/retrieval.py#L29).

- `PostgresRetriever(resource: PoolResource, *, mode: str='lexical', embedder: EmbeddingAdapter | None=None, embedding_profile: EmbeddingProfile=FAKE_PROFILE, allow_degraded: bool=False, identifiers: bool=True, evidence_options: dict[str, Any] | None=None) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async retrieve(request: RetrievalRequest, *, scope: TrustedScope, deadline: float) -> RetrievalResult`: Retrieve scoped evidence under the request deadline and limits; inspect coverage and execution separately.

#### `PostgresVectorIndexer`

Stage and publish exact embedding-profile generations with bounded embedding batches.

[Source](../packages/python/src/cragkit/vector_ingestion.py#L115).

- `PostgresVectorIndexer(resource: PoolResource, *, authorize_write: Callable[[TrustedScope, str, str], Awaitable[bool]], embedder: EmbeddingAdapter, embedding_profile: EmbeddingProfile=FAKE_PROFILE, max_batches: int=128, max_attempts: int=8) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async stage(source: str | bytes, *, collection: str, document_id: str, intent_id: str, source_locator: str, scope: TrustedScope, deadline: float, expected_generation_id: str | None=None, metadata: dict[str, object] | None=None, format: str='text/plain', canonical_options: dict[str, Any] | None=None) -> VectorIngestionReceipt`: Stage immutable generation data without claiming the later publication is complete.
- `async publish(source: str | bytes, *, collection: str, document_id: str, intent_id: str, source_locator: str, scope: TrustedScope, deadline: float, expected_generation_id: str | None=None, metadata: dict[str, object] | None=None, format: str='text/plain', canonical_options: dict[str, Any] | None=None, before_publish: Callable[[], Awaitable[None]] | None=None) -> VectorIngestionReceipt`: Publish the admitted staged generation after required checks and original-fence comparison.
- `async ingest(source: str | bytes, *, collection: str, document_id: str, intent_id: str, source_locator: str, scope: TrustedScope, deadline: float, expected_generation_id: str | None=None, metadata: dict[str, object] | None=None, format: str='text/plain', canonical_options: dict[str, Any] | None=None, before_publish: Callable[[], Awaitable[None]] | None=None) -> VectorIngestionReceipt`: Canonicalize and durably publish a generation; matching intent retries report replay instead of mutating immutable payload.

#### `VectorIngestionReceipt`

Ingestion receipt extended with embedding profile, calls and usage.

[Source](../packages/python/src/cragkit/vector_ingestion.py#L24).

Declared fields: `embedding_profile`, `provider_calls`, `usage`.



### `cragkit.retrieval`

Import from `cragkit.retrieval`. [Module source](../packages/python/src/cragkit/retrieval.py).

- `PostgresRetriever`: reexport/definition of the interface documented under `cragkit.postgres`.

### `cragkit.ingestion`

Import from `cragkit.ingestion`. [Module source](../packages/python/src/cragkit/ingestion.py).

- `IngestionReceipt`: reexport/definition of the interface documented under `cragkit.postgres`.
- `PostgresIndexer`: reexport/definition of the interface documented under `cragkit.postgres`.

### `cragkit.vector_ingestion`

Import from `cragkit.vector_ingestion`. [Module source](../packages/python/src/cragkit/vector_ingestion.py).

- `VectorIngestionReceipt`: reexport/definition of the interface documented under `cragkit.postgres`.
- `PostgresVectorIndexer`: reexport/definition of the interface documented under `cragkit.postgres`.

### `cragkit.lifecycle`

- `Operation`: `Literal["tombstone", "purge"]`.
- `LifecycleAuthorizer`: `Callable[[TrustedScope, str, str, Operation], Awaitable[bool]]`; arguments are trusted scope, collection, document ID and lifecycle action.

Import from `cragkit.lifecycle`. [Module source](../packages/python/src/cragkit/lifecycle.py).

- `LifecycleReceipt`: reexport/definition of the interface documented under `cragkit.postgres`.
- `PostgresLifecycle`: reexport/definition of the interface documented under `cragkit.postgres`.

### `cragkit.canonical`

Import from `cragkit.canonical`. [Module source](../packages/python/src/cragkit/canonical.py).

#### `CanonicalChunk`

One immutable exact source slice, its ordinal, byte span, digest and optional count.

[Source](../packages/python/src/cragkit/canonical.py#L14).

Declared fields: `chunk_id`, `ordinal`, `start_byte`, `end_byte`, `text`, `text_sha256`, `oversized_split`, `token_count`.


#### `CanonicalDocument`

Canonical source and chunk metadata returned by canonicalize.

[Source](../packages/python/src/cragkit/canonical.py#L26).

Declared fields: `canonical_text`, `source_sha256`, `canonical_sha256`, `parser_id`, `chunker_profile`, `format`, `tokenizer_id`, `token_count`, `chunks`.


#### `canonicalize`

Decode and canonicalize bounded plain text/Markdown into immutable UTF-8 chunks and digests.

[Source](../packages/python/src/cragkit/canonical.py#L75).

```text
canonicalize(source: str | bytes, *, format: str='text/plain', max_source_bytes: int=1048576, target_bytes: int=2048, max_chunk_bytes: int=32768, token_counter: Callable[[str], int] | None=None, tokenizer_id: str | None=None, token_target: int | None=None, max_tokens: int | None=None) -> CanonicalDocument
```


### `cragkit.embeddings`

Import from `cragkit.embeddings`. [Module source](../packages/python/src/cragkit/embeddings.py).

#### `EmbeddingProfile`

Full embedding identity; matching dimension count alone is insufficient.

[Source](../packages/python/src/cragkit/embeddings.py#L23).

Declared fields: `profile_id`, `provider`, `model`, `dimensions`, `tokenizer`, `normalization`.


#### `EmbeddingLimits`

Per-call item, byte, token and response limits; these are bounded independently of request totals.

[Source](../packages/python/src/cragkit/embeddings.py#L46).

Declared fields: `max_items`, `max_input_bytes`, `max_batch_bytes`, `max_input_tokens`, `max_batch_tokens`, `max_response_bytes`.


#### `EmbeddingPolicy`

Explicit live-call admission, cost bound and optional token price for estimates.

[Source](../packages/python/src/cragkit/embeddings.py#L55).

Declared fields: `allow_live`, `max_cost_usd`, `usd_per_million_tokens`.


#### `TokenCounter`

Application-injected counting protocol with a declared tokenizer name.

[Source](../packages/python/src/cragkit/embeddings.py#L61).

Declared fields: `name`.

- `count(text: str) -> int`: Count the supplied string using the declared tokenizer.

#### `EmbeddingTransport`

Application-owned asynchronous request-byte transport; enforce deadline and response-byte limits.

[Source](../packages/python/src/cragkit/embeddings.py#L67).

- `async __call__(body: bytes, *, deadline: float, max_response_bytes: int) -> bytes`: Implement this asynchronous transport/export protocol under its declared bounds.

#### `EmbeddingUsage`

Reported/unknown token and cost accounting for an embedding call.

[Source](../packages/python/src/cragkit/embeddings.py#L71).

Declared fields: `prompt_tokens`, `total_tokens`, `cost_usd`, `cost_kind`.


#### `EmbeddingBatch`

Bound profile, vectors, usage, call count and synthetic marker.

[Source](../packages/python/src/cragkit/embeddings.py#L78).

Declared fields: `profile`, `vectors`, `usage`, `provider_calls`, `synthetic`.


#### `EmbeddingAdapter`

Validate and bound one query or batch embedding call through the injected transport and tokenizer.

[Source](../packages/python/src/cragkit/embeddings.py#L121).

- `EmbeddingAdapter(transport: EmbeddingTransport, token_counter: TokenCounter, *, profile: EmbeddingProfile=FAKE_PROFILE, limits: EmbeddingLimits | None=None, policy: EmbeddingPolicy | None=None) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async embed_query(text: str, *, deadline: float, on_dispatch: Callable[[], None] | None=None) -> EmbeddingBatch`: Validate and embed one query, recording profile and usage.
- `async embed_batch(texts: list[str] | tuple[str, ...], *, deadline: float, on_dispatch: Callable[[], None] | None=None) -> EmbeddingBatch`: Validate and embed a bounded batch, preserving item order and profile.

- `FAKE_PROFILE`: Synthetic-only deterministic profile; it does not establish live-model quality. [Declaration](../packages/python/src/cragkit/embeddings.py).
- `OPENAI_PROFILE`: Pinned text-embedding-3-small, 1536 dimensions, cl100k_base, L2 normalization profile. [Declaration](../packages/python/src/cragkit/embeddings.py).

### `cragkit.reranking`

Import from `cragkit.reranking`. [Module source](../packages/python/src/cragkit/reranking.py).

#### `RerankProfile`

Model revision, preprocessing, score kind/direction and truncation policy for reranking.

[Source](../packages/python/src/cragkit/reranking.py#L20).

Declared fields: `profile_id`, `provider`, `model`, `model_revision`, `score_kind`, `score_direction`, `preprocessing_revision`, `truncation_policy`.


#### `RerankTransport`

Application-owned asynchronous reranking byte transport with bounded response size.

[Source](../packages/python/src/cragkit/reranking.py#L46).

- `async __call__(body: bytes, *, deadline: float, max_response_bytes: int) -> bytes`: Implement this asynchronous transport/export protocol under its declared bounds.

#### `RerankingAdapter`

Validate bounded candidate views, rank identity/order and declared fallback behavior.

[Source](../packages/python/src/cragkit/reranking.py#L84).

- `RerankingAdapter(transport: RerankTransport, *, profile: RerankProfile=FAKE_RERANK_PROFILE, allow_live: bool=False) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `profile: RerankProfile` (read-only property): the bound provider/model profile.
- `async rank(query: str, candidates: list[dict[str, str]] | tuple[dict[str, str], ...], *, deadline: float, max_provider_calls: int=1, allow_fallback: bool=False) -> dict[str, Any]`: Rank the bounded candidate IDs with score direction, truncation and fallback validation.

- `FAKE_RERANK_PROFILE`: Synthetic-only deterministic profile; it does not establish live-model quality. [Declaration](../packages/python/src/cragkit/reranking.py).

### `cragkit.context`

Import from `cragkit.context`. [Module source](../packages/python/src/cragkit/context.py).

#### `Cl100kCounter`

Pinned, local cl100k tokenizer counter. Use its factory rather than direct construction.

[Source](../packages/python/src/cragkit/context.py#L25).

- `Cl100kCounter(encoding: Any, *, _factory: object=None) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `from_file(path: str | Path) -> Cl100kCounter`: Load and hash-check the supplied tokenizer asset locally.
- `count(text: str) -> int`: Count the supplied string using the declared tokenizer.

#### `render_context`

Serialize exact evidence fields as the selected compact JSON representation.

[Source](../packages/python/src/cragkit/context.py#L77).

```text
render_context(evidence: object) -> str
```

#### `count_context`

Render and count the selected evidence representation plus reserve; enforce the configured counting mode.

[Source](../packages/python/src/cragkit/context.py#L107).

```text
count_context(evidence: object, *, max_tokens: int, reserve: int=256, counter: Cl100kCounter | None=None, counting_mode: str='estimated') -> dict[str, Any]
```


### `cragkit.packing`

Import from `cragkit.packing`. [Module source](../packages/python/src/cragkit/packing.py).

#### `pack_evidence`

Pack verified exact source slices, deduplicate/merge eligible spans, and enforce serialization/token bounds.

[Source](../packages/python/src/cragkit/packing.py#L48).

```text
async pack_evidence(evidence: object, sources: object, *, deadline: float, max_tokens: int, reserve: int=256, counter: Cl100kCounter | None=None, counting_mode: str='estimated', surrounding_bytes: int=256, facet_evidence: object=_DEFAULT_FACETS) -> dict[str, Any]
```


### `cragkit.assessment`

Import from `cragkit.assessment`. [Module source](../packages/python/src/cragkit/assessment.py).

#### `validate_assessment`

Validate facet/evidence references and conservative assessment invariants.

[Source](../packages/python/src/cragkit/assessment.py#L82).

```text
validate_assessment(evidence: object, facets: object) -> list[dict[str, Any]]
```

#### `assess_evidence`

Assess evidence against the supplied reviewed policy; unknown coverage cannot become sufficient.

[Source](../packages/python/src/cragkit/assessment.py#L104).

```text
assess_evidence(query: object, evidence: object, policy: object=None) -> dict[str, Any]
```


### `cragkit.evidence`

Import from `cragkit.evidence`. [Module source](../packages/python/src/cragkit/evidence.py).

#### `pack_and_assess`

Pack, reassess surviving evidence, and optionally perform one bounded rebalance.

[Source](../packages/python/src/cragkit/evidence.py#L16).

```text
async pack_and_assess(query: object, evidence: object, sources: object, *, deadline: float, max_tokens: int, reserve: int=256, counter: Cl100kCounter | None=None, counting_mode: str='estimated', surrounding_bytes: int=256, policy: object=None, rebalance: bool=False) -> dict[str, Any]
```


### `cragkit.execution`

Import from `cragkit.execution`. [Module source](../packages/python/src/cragkit/execution.py).

#### `BudgetExhausted`

The next ledger reservation cannot fit a declared request limit.

[Source](../packages/python/src/cragkit/execution.py#L14).

Construct this concrete error with no arguments; it inherits to_dict from CragkitError.

#### `ExecutionLedger`

Request-local atomic reservations. Reserve before dispatch, reconcile reported usage after completion, and abandon unresolved work honestly.

[Source](../packages/python/src/cragkit/execution.py#L46).

- `ExecutionLedger(limits: object, *, deadline: float) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `deadline: float` (read-only property): the shared effective monotonic deadline.
- `close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.
- `reserve(*, provider_calls: int=0, candidates: int=0, attempts: int=0, cost_upper_usd: float | None=None) -> object`: Reserve bounded calls, candidates, attempts and optional cost before dispatch.
- `dispatch(reservation: object) -> None`: Mark the exact reservation as dispatched before external work starts.
- `reconcile(reservation: object, *, input_tokens: int | None=None, output_tokens: int | None=None, cost_usd: float | None=None) -> None`: Reconcile one dispatched reservation with actual/unknown token and cost usage.
- `abandon(reservation: object) -> None`: Preserve honest accounting for a reservation that cannot be reconciled.
- `snapshot() -> dict[str, Any]`: Read immutable bounded accounting/queue diagnostics.


### `cragkit.planning`

Import from `cragkit.planning`. [Module source](../packages/python/src/cragkit/planning.py).

#### `validate_plan`

Validate allowed original/variant queries and prevent changes to trusted request constraints.

[Source](../packages/python/src/cragkit/planning.py#L48).

```text
validate_plan(value: object, *, query: object, variants: object, missing_facets: object, max_subqueries: object) -> list[dict[str, str]]
```

#### `PlannerTransport`

Application-owned planner transport; no identity or permissions belong in a model-editable plan.

[Source](../packages/python/src/cragkit/planning.py#L76).

- `async __call__(payload: dict[str, Any], *, deadline: float) -> object`: Implement this asynchronous transport/export protocol under its declared bounds.

#### `PlannerAdapter`

Validate bounded rewrites while preserving the original query, scope, required filters and limits.

[Source](../packages/python/src/cragkit/planning.py#L107).

- `PlannerAdapter(transport: PlannerTransport, *, sdk_retries: int=0, cost_upper_usd: float | None=None, allow_fallback: bool=False) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async plan(query: object, *, variants: object, missing_facets: object, max_subqueries: object, ledger: ExecutionLedger, deadline: float) -> dict[str, Any]`: Call the planner and validate allowed query variants/fallback under the request bounds.


### `cragkit.corrective`

Import from `cragkit.corrective`. [Module source](../packages/python/src/cragkit/corrective.py).

#### `QdrantCandidate`

Typed Qdrant nomination handoff. Its payload is not authorized source text.

[Source](../packages/python/src/cragkit/corrective.py#L31).

Declared fields: `backend`, `score`, `nomination`.


#### `CorrectiveRetriever`

Bounded attempts over a trusted backend; returns a result plus diagnostics and stop reason. It borrows its backend.

[Source](../packages/python/src/cragkit/corrective.py#L98).

- `CorrectiveRetriever(backend: Any, *, policy: object=None, variants: object=None, planner: PlannerAdapter | None=None, counter: Cl100kCounter | None=None, batch_size: int=16, max_retries: int=0, backoff_ms: int=0, no_progress_limit: int=1, event_sink: EventSink | None=None) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async retrieve(request: object, *, scope: object, deadline: float) -> dict[str, Any]`: Retrieve scoped evidence under the request deadline and limits; inspect coverage and execution separately.


### `cragkit.postgres_corrective`

Import from `cragkit.postgres_corrective`. [Module source](../packages/python/src/cragkit/postgres_corrective.py).

#### `PostgresCorrectiveBackend`

PostgreSQL search and source-capture boundary for CorrectiveRetriever.

[Source](../packages/python/src/cragkit/postgres_corrective.py#L42).

- `PostgresCorrectiveBackend(resource: PoolResource, *, mode: str='lexical', embedder: EmbeddingAdapter | None=None, embedding_profile: EmbeddingProfile=FAKE_PROFILE, reranker: RerankingAdapter | None=None) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `result_versions: Mapping[str, str] | None` (read-only property): backend model/index identifiers for result diagnostics.
- `async search(request: RetrievalRequest, *, scope: TrustedScope, deadline: float, limit: int, ledger: ExecutionLedger) -> dict[str, Any]`: Return scoped candidate identities through the backend search contract.
- `async capture(candidates: Any, *, request: RetrievalRequest, scope: TrustedScope, deadline: float, max_source_bytes: int, ledger: ExecutionLedger) -> dict[str, Any]`: Reauthorize and capture exact source evidence for selected candidates.


### `cragkit.events`

Import from `cragkit.events`. [Module source](../packages/python/src/cragkit/events.py).

#### `new_trace`

Create a new opaque local trace identifier.

[Source](../packages/python/src/cragkit/events.py#L24).

```text
new_trace() -> str
```

#### `EventExporter`

Asynchronous redacted-event export callback under a deadline.

[Source](../packages/python/src/cragkit/events.py#L28).

- `async __call__(event: dict[str, Any], *, deadline: float) -> None`: Implement this asynchronous transport/export protocol under its declared bounds.

#### `EventSink`

Bounded event queue and export lifecycle. Exporter failures do not become successful retrieval evidence.

[Source](../packages/python/src/cragkit/events.py#L39).

- `EventSink(exporter: EventExporter | None=None, *, capacity: int=32, timeout_ms: int=25) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `emit(stage: str, *, trace_id: str, attempt: int, elapsed_ms: float, candidate_count: int=0, provider_calls: int=0, stop_reason: str | None=None) -> bool`: Enqueue a validated redacted event without unbounded growth.
- `snapshot() -> dict[str, int]`: Read immutable bounded accounting/queue diagnostics.
- `drain() -> list[dict[str, Any]]`: Return and remove queued events locally, accounting for them as drained/dropped; this does not invoke the exporter.
- `close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.
- `async flush(deadline: float) -> dict[str, int]`: Asynchronously export queued events under the deadline and report delivered/dropped/queued counts.


### `cragkit.qdrant`

See the Qdrant guide for exact admission and source-authority requirements.

Import from `cragkit.qdrant`. [Module source](../packages/python/src/cragkit/qdrant.py).

#### `QdrantTransport`

Bounded, cancellation-safe candidate HTTP transport protocol. A store borrows it.

[Source](../packages/python/src/cragkit/qdrant.py#L25).

Declared fields: `bounded_responses`, `cancellation_safe`.

- `async request(method: str, path: str, *, body: bytes | None=None, deadline: float, max_response_bytes: int=1048576) -> bytes`: Perform one bounded transport request using the supplied absolute deadline.

#### `QdrantSearchStore`

Initialized candidate replica only. Search results are UNVERIFIED nominations; this store releases no source text.

[Source](../packages/python/src/cragkit/qdrant.py#L33).

- `QdrantSearchStore(config: object, transport: QdrantTransport) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `config: QdrantConfig` (read-only property): the immutable selected configuration.
- `capabilities() -> Mapping[str, object]`: Return the supported capability flags rather than inferring them from an adapter name.
- `async initialize(*, deadline: float) -> None`: Validate/admit the selected native profile before operations; it does not apply SQL migrations.
- `async search_candidates(request: object, *, scope: object, dense: object=None, sparse: object=None, branch_limits: object, ledger: ExecutionLedger, deadline: float) -> tuple[QdrantNomination, ...]`: Return scoped UNVERIFIED Qdrant nominations; source authorization remains a separate step.
- `async close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `CandidatePayload`

Candidate-side identity, spans, hashes, profiles and authorization metadata. Verify against source authority before release.

[Source](../packages/python/src/cragkit/_qdrant_contract.py#L70).

Declared fields: `backend_namespace`, `physical_collection`, `collection_incarnation`, `tenant_id`, `collection`, `document_id`, `revision_id`, `generation_id`, `chunk_id`, `start_byte`, `end_byte`, `source_sha256`, `text_sha256`, `dense_profile_id`, `sparse_profile_id`, `dense_profile`, `sparse_profile`, `principal_ids`, `grant_ids`, `authorization_revision`, `language`, `kind`, `tag`.


#### `QdrantConfig`

Namespace, physical collection/incarnation, complete dense profile and optional supported sparse profile.

[Source](../packages/python/src/cragkit/_qdrant_contract.py#L51).

Declared fields: `backend_namespace`, `physical_collection`, `collection_incarnation`, `dense_profile`, `sparse_profile`.


#### `QdrantNomination`

Point identity, branch, score semantics, UNVERIFIED marker and candidate payload.

[Source](../packages/python/src/cragkit/_qdrant_contract.py#L124).

Declared fields: `point_id`, `branch`, `score`, `score_kind`, `score_direction`, `verification`, `payload`.


#### `SparseProfile`

Full sparse encoder/vocabulary/preprocessing/statistics identity. The declared profile is synthetic, not general BM25.

[Source](../packages/python/src/cragkit/_qdrant_contract.py#L25).

Declared fields: `profile_id`, `encoder`, `model`, `revision`, `vocabulary`, `preprocessing`, `weighting`, `corpus_statistics_revision`.


#### `bind_embedding_batch`

Validate a complete E-r1 batch against the selected exact dense profile and expected item count.

[Source](../packages/python/src/cragkit/_qdrant_contract.py#L398).

```text
bind_embedding_batch(batch: object, profile: object, *, expected_items: int | None=None) -> EmbeddingBatch
```

#### `compile_filter`

Compile required filters together with trusted tenant/principal/grant scope; unsupported operators fail closed.

[Source](../packages/python/src/cragkit/_qdrant_contract.py#L229).

```text
compile_filter(request: object, scope: object) -> dict[str, Any]
```

#### `point_id`

Derive the deterministic point UUID from the complete immutable identity.

[Source](../packages/python/src/cragkit/_qdrant_contract.py#L191).

```text
point_id(identity: object) -> str
```

#### `HttpxQdrantTransport`

Optional Python HTTPX transport. Owns a lazy client by default; an injected client remains borrowed.

[Source](../packages/python/src/cragkit/_qdrant_transport.py#L70).

- `HttpxQdrantTransport(endpoint: str, *, api_key: str | None=None, allow_loopback_http: bool=False, client: Any=None) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async request(method: str, path: str, *, body: bytes | None=None, deadline: float, max_response_bytes: int=1048576) -> bytes`: Perform one bounded transport request using the supplied absolute deadline.
- `async close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

- `SPARSE_PROFILE`: Synthetic caller-supplied sparse fixture profile, not BM25. [Declaration](../packages/python/src/cragkit/qdrant.py).

### `cragkit.qdrant_source`

Import from `cragkit.qdrant_source`. [Module source](../packages/python/src/cragkit/qdrant_source.py).

#### `PostgresQdrantSourceStore`

Initialized authoritative SQL source/ACL reader bound to the same complete Qdrant configuration.

[Source](../packages/python/src/cragkit/qdrant_source.py#L27).

- `PostgresQdrantSourceStore(resource: PoolResource, config: object) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `config: QdrantConfig` (read-only property): the immutable selected configuration.
- `capabilities() -> Mapping[str, bool]`: Return the supported capability flags rather than inferring them from an adapter name.
- `async initialize(*, deadline: float) -> None`: Validate/admit the selected native profile before operations; it does not apply SQL migrations.
- `open_request(request: object, *, scope: object, deadline: float) -> SourceRequest`: Create one request-bound source handle using independently supplied trusted scope.
- `async close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `SourceFetch`

Verified/unavailable/budget-exhausted read outcome. Opaque binding and private source are excluded from ordinary serialization.

[Source](../packages/python/src/cragkit/_qdrant_source.py#L36).

Declared fields: `state`, `evidence`, `source_bytes`, `stale`, `binding`, `private_source`.


#### `PrivateSource`

Private canonical source buffer for authorized internal packing; do not expose or log it as a result.

[Source](../packages/python/src/cragkit/_qdrant_source.py#L31).

Declared fields: `canonical_text`, `source_sha256`.


#### `SourceRequest`

Request-bound source release handle returned by open_request. Close it before admitting another request.

[Source](../packages/python/src/cragkit/qdrant_source.py#L113).

- `async fetch_candidate(nomination: object, *, max_source_bytes: int, include_source: bool=False) -> SourceFetch`: Verify a nomination against current SQL source/authorization and issue an opaque handle binding when verified.
- `async release(binding: object, *, purpose: str, max_source_bytes: int, include_source: bool=False) -> SourceFetch`: Reauthorize the same request-bound source binding for provider or final release.
- `async close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.


### `cragkit.qdrant_corrective`

Import from `cragkit.qdrant_corrective`. [Module source](../packages/python/src/cragkit/qdrant_corrective.py).

#### `QdrantCorrectiveBackend`

Compose initialized Qdrant candidates and PostgreSQL sources with an explicit embedding transport; dense mode only.

[Source](../packages/python/src/cragkit/qdrant_corrective.py#L17).

- `QdrantCorrectiveBackend(candidates: QdrantSearchStore, sources: PostgresQdrantSourceStore, *, embedding_transport: EmbeddingTransport, token_counter: TokenCounter, policy: EmbeddingPolicy | None=None, mode: str='dense') -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `capabilities() -> Mapping[str, bool]`: Return the supported capability flags rather than inferring them from an adapter name.
- `async search(request: Any, *, scope: Any, deadline: float, limit: int, ledger: ExecutionLedger) -> dict[str, Any]`: Return scoped candidate identities through the backend search contract.
- `async capture(candidates: Any, *, request: Any, scope: Any, deadline: float, max_source_bytes: int, ledger: ExecutionLedger) -> dict[str, Any]`: Reauthorize and capture exact source evidence for selected candidates.


### `cragkit.qdrant_publication`

See managed publication for the supported dependency graph and operator limits. Opaque receipt/proof helpers are not free-standing exports.

Import from `cragkit.qdrant_publication`. [Module source](../packages/python/src/cragkit/qdrant_publication.py).

#### `PostgresQdrantPublicationAuthority`

Bind the exact writer and recovery objects. This holder does not grant readiness or authorization.

[Source](../packages/python/src/cragkit/qdrant_publication.py#L56).

- `PostgresQdrantPublicationAuthority(writer: PostgresQdrantWriter, recovery: PostgresQdrantRecovery | None) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.

#### `ManagedQdrantPublicationTransport`

Borrow the actual native controller and manage attempt transport handles; close does not close the controller.

[Source](../packages/python/src/cragkit/qdrant_publication.py#L79).

- `ManagedQdrantPublicationTransport(supervisor: ManagedQdrantSupervisor | OrdinaryWorkerController) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `QdrantPublicationManager`

Managed stage, publish, repair, current-security convergence and scoped purge. Authorize every operation with application code.

[Source](../packages/python/src/cragkit/qdrant_publication.py#L198).

- `QdrantPublicationManager(authority: PostgresQdrantPublicationAuthority, transport: ManagedQdrantPublicationTransport, config: object, supervisor: ManagedQdrantSupervisor | OrdinaryWorkerController, authorize_write: Callable[[TrustedScope, str, str], Awaitable[bool]]) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async initialize(*, deadline: float) -> None`: Validate/admit the selected native profile before operations; it does not apply SQL migrations.
- `async stage(change: object, scope: object, ledger: ExecutionLedger, *, deadline: float) -> Mapping[str, Any]`: Stage immutable generation data without claiming the later publication is complete.
- `async publish(reference: object, scope: object, ledger: ExecutionLedger, *, deadline: float) -> Mapping[str, Any]`: Publish the admitted staged generation after required checks and original-fence comparison.
- `async repair(reference: object, scope: object, ledger: ExecutionLedger, *, deadline: float) -> Mapping[str, Any]`: Run managed recovery/readback of the original intent before final publication; no caller replacement proof is accepted.
- `async converge_security(reference: object, scope: object, ledger: ExecutionLedger, *, deadline: float) -> Mapping[str, Any]`: Refence, repair and verify the claimed current authorization replica set.
- `async purge(record: object, scope: object, ledger: ExecutionLedger, *, retention_policy: str, deadline: float) -> Mapping[str, Any]`: Erase the admitted managed scope under the explicit retention policy; application backups remain outside this operation.
- `async close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `QdrantReconciliationVerifier`

Verify the complete scoped replica against a genuine original projection and supervisor; a fabricated receipt is rejected.

[Source](../packages/python/src/cragkit/_qdrant_reconciliation.py#L372).

- `QdrantReconciliationVerifier(writer: PostgresQdrantWriter, supervisor: ManagedQdrantSupervisor) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async verify(proof: object, context: object, *, deadline: float, budget: VerificationBudget | None=None) -> ReconciliationReceipt`: Verify all required original scoped content and issue the native receipt; fabricated/copied proofs are rejected.

#### `PostgresQdrantRecovery`

Restricted supervisor SQL authority for genuine credential refencing, retired dispatch settlement and managed reopening.

[Source](../packages/python/src/cragkit/_qdrant_recovery.py#L479).

- `PostgresQdrantRecovery(resource: PoolResource, config: object, supervisor: ManagedQdrantSupervisor, verifier: QdrantReconciliationVerifier) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async initialize(*, deadline: float) -> None`: Validate/admit the selected native profile before operations; it does not apply SQL migrations.
- `async recover(recovery_id: object, *, deadline: float) -> object`: Perform the selected native managed recovery step; ordinary readback alone cannot refence an uncertain writer.
- `async advance_owner(proof: object, value: object, *, deadline: float) -> Mapping[str, Any]`: Advance the admitted durable owner using the genuine current recovery proof.
- `async settle_retired(proof: object, receipt: object, *, deadline: float) -> Mapping[str, Any]`: Settle retired uncertainty using issuer-bound recovery and verification evidence.
- `async dispatch_stage_recovery(proof: object, value: object, authorize: object, *, deadline: float, budget: VerificationBudget | None=None) -> Mapping[str, Any]`: Dispatch only original missing-point recovery batches under genuine recovery authorization.
- `async reopen(proof: object, *, deadline: float) -> Mapping[str, Any]`: Reopen ordinary work only after genuine recovery, complete verification and retired settlement.
- `async close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `QdrantSecurityManager`

Independent SQL authorization/tombstone admission. Replica convergence and physical purge are separate operations.

[Source](../packages/python/src/cragkit/_qdrant_security.py#L31).

- `QdrantSecurityManager(writer: PostgresQdrantWriter, authorize_write: Callable[[TrustedScope, str, str], Awaitable[bool]]) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async initialize(*, deadline: float) -> None`: Validate/admit the selected native profile before operations; it does not apply SQL migrations.
- `async update_authorization(change: object, scope: object, ledger: ExecutionLedger, *, deadline: float) -> Mapping[str, Any]`: Commit the explicit current authorization intent without claiming replica convergence.
- `async tombstone(change: object, scope: object, ledger: ExecutionLedger, *, deadline: float) -> Mapping[str, Any]`: Admit the authorized tombstone; replica completion is a separate state.
- `async close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `ManagedQdrantSupervisor`

Explicitly own one supported native Qdrant process, registered profile and credential-fencing lifecycle; imports start no process.

[Source](../packages/python/src/cragkit/_qdrant_supervisor.py#L231).

- `ManagedQdrantSupervisor(binary: Path, work_dir: Path, instance_id: object, config: object) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `register_profile(value: object) -> None`: Register the exact physical collection/profile before managed supervisor initialization.
- `identity() -> dict[str, Any]`: Read the controller's native instance identity.
- `control_binding() -> Mapping[str, Any]`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `profile_binding(config: object) -> Mapping[str, Any]`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `async control_session() -> AsyncIterator[_ControlSession]`: Hold the genuine supervisor control exclusion for a bounded native recovery/finalization flow.
- `block_ordinary(*, _control: object | None=None) -> None`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async initialize(*, deadline: float, provision: Callable[[_Transport, dict[str, Any]], Awaitable[object]] | None=None) -> None`: Validate/admit the selected native profile before operations; it does not apply SQL migrations.
- `issue_attempt(binding: object, *, deadline: float) -> _Attempt`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `transport_for(capability: object, *, _control: object | None=None) -> _Transport`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async deliver_worker_credential(capability: object, sink: Callable[[dict[str, Any]], Awaitable[object]], *, deadline: float) -> None`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async recover(request: object, *, deadline: float, _control: object | None=None) -> _Proof`: Perform the selected native managed recovery step; ordinary readback alone cannot refence an uncertain writer.
- `issue_recovery_attempt(proof: object, binding: object, *, deadline: float, _control: object | None=None) -> _Attempt`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `recovery_binding(proof: object) -> Mapping[str, Any]`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `barrier_binding(barrier: object) -> Mapping[str, Any]`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `async seal_recovery(proof: object, *, deadline: float, _control: object | None=None) -> _Barrier`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `finish_recovery(barrier: object, settlement: object, *, deadline: float, _control: object | None=None) -> None`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `attempt_binding(capability: object) -> Mapping[str, Any]`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `async close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `ManagedQdrantPublicationWorkerHost`

Publish an already staged intent in one owned native child while the parent retains the actual supervisor.

[Source](../packages/python/src/cragkit/_qdrant_publication_worker.py#L672).

- `ManagedQdrantPublicationWorkerHost(supervisor: ManagedQdrantSupervisor, authorize_write: Any) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async publish(job: Any, ledger: ExecutionLedger, *, deadline: float, observer: Any=None) -> Any`: Publish the admitted staged generation after required checks and original-fence comparison.
- `async close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `OwnedPublicationWorker`

Observer-issued handle for that exact child. Do not construct it or pass arbitrary PIDs/signals.

[Source](../packages/python/src/cragkit/_qdrant_publication_worker.py#L590).

- `OwnedPublicationWorker(token: object, process: Any) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async pause(*, deadline: float) -> None`: Pause only the actual observer-issued owned worker under the deadline.
- `async resume(*, deadline: float) -> None`: Resume only the actual observer-issued owned worker under the deadline.
- `async terminate(*, deadline: float) -> None`: Terminate and reap only the actual observer-issued owned worker.

#### `PostgresQdrantWriter`

Restricted durable SQL authority used by the managed graph. Low-level methods require original native capabilities and validated state.

[Source](../packages/python/src/cragkit/_qdrant_writer.py#L469).

- `PostgresQdrantWriter(resource: PoolResource, config: object, instance_id: object) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async initialize(*, deadline: float) -> None`: Validate/admit the selected native profile before operations; it does not apply SQL migrations.
- `async inspect(value: object, *, deadline: float) -> Mapping[str, Any] | None`: Read the admitted durable intent state without releasing source data.
- `async manager_snapshot(value: object, *, deadline: float) -> Mapping[str, Any]`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `async preflight_repair(value: object, *, deadline: float) -> Mapping[str, Any]`: Read and validate the original intent/owner/backend/pending state before managed repair admission.
- `async admit_publication(value: object, *, deadline: float) -> Mapping[str, Any]`: Admit the bounded native authority transition under original identity and current SQL fences.
- `async dispatch_status(value: object, dispatch_id: object, *, deadline: float) -> Mapping[str, Any] | None`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `async publication_preparation(value: object, *, deadline: float) -> Mapping[str, Any] | None`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `async stage(plan: StagePlan, scope: object, *, owner_token: object, deadline: float) -> Mapping[str, Any]`: Stage immutable generation data without claiming the later publication is complete.
- `async acquire_owner(value: object, *, deadline: float) -> Mapping[str, Any]`: Admit the bounded native authority transition under original identity and current SQL fences.
- `async close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.
- `async reserve_dispatch(value: object, reservation: object, *, deadline: float) -> Mapping[str, Any]`: Admit the bounded native authority transition under original identity and current SQL fences.
- `async mark_dispatched(value: object, dispatch_id: object, *, deadline: float) -> None`: Journal the exact dispatch lifecycle; a lost acknowledgment remains unresolved until managed recovery.
- `async mark_unknown(value: object, dispatch_id: object, *, deadline: float) -> None`: Journal the exact dispatch lifecycle; a lost acknowledgment remains unresolved until managed recovery.
- `async settle_dispatch(value: object, dispatch_id: object, completion_sha256: object, *, deadline: float) -> None`: Journal the exact dispatch lifecycle; a lost acknowledgment remains unresolved until managed recovery.
- `async load_stage(value: object, *, deadline: float) -> StagePlan`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async project_security(value: object, *, deadline: float) -> SecurityProjection`: Produce a native issuer-bound projection from admitted durable state; callers cannot substitute a serialized copy.
- `async validate_security_projection(projection: object, *, deadline: float) -> None`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async fixed_validate_security_guarded(guard: object, projection: object, *, deadline: float) -> None`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async project_publication(value: object, binding: object, *, deadline: float) -> PublicationProjection`: Produce a native issuer-bound projection from admitted durable state; callers cannot substitute a serialized copy.
- `async validate_publication_projection(projection: object, *, deadline: float) -> None`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async project_recovery_dispatch(authorization: object, value: object, point_ids: object, *, deadline: float) -> _RecoveryDispatchPlan`: Produce a native issuer-bound projection from admitted durable state; callers cannot substitute a serialized copy.
- `async validate_recovery_dispatch(plan: object, authorization: object, *, deadline: float) -> None`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async project_security_dispatch(authorization: object, point_ids: object, *, deadline: float) -> _SecurityDispatchPlan`: Produce a native issuer-bound projection from admitted durable state; callers cannot substitute a serialized copy.
- `async validate_security_dispatch(plan: object, authorization: object, *, deadline: float) -> None`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async project_stage(value: object, binding: object, *, deadline: float) -> ExpectedProjection`: Produce a native issuer-bound projection from admitted durable state; callers cannot substitute a serialized copy.
- `async validate_projection(projection: object, *, deadline: float) -> None`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async prepare(value: object, readback_sha256: object, *, deadline: float) -> Mapping[str, Any]`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async attestation_snapshot(value: object, *, deadline: float) -> Mapping[str, Any]`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `async attest_prepared(receipt: object, verifier: object, *, deadline: float) -> Mapping[str, Any]`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async publish(value: object, *, deadline: float) -> Mapping[str, Any]`: Publish the admitted staged generation after required checks and original-fence comparison.
- `async apply_security(record: object, scope: object, *, owner_token: object, deadline: float) -> Mapping[str, Any]`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async bind_purge(record: object, scope: object, *, owner_token: object, deadline: float) -> Mapping[str, Any]`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async project_purge(value: object, retention_policy: str=PURGE_POLICY, *, deadline: float) -> PurgeProjection`: Produce a native issuer-bound projection from admitted durable state; callers cannot substitute a serialized copy.
- `async validate_purge_projection(projection: object, *, deadline: float) -> None`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async admit_purge_tombstone_owner(projection: object, *, deadline: float) -> Mapping[str, Any]`: Admit the bounded native authority transition under original identity and current SQL fences.
- `async admit_purge_successor(projection: object, predecessor: object, identity: object, *, deadline: float) -> Mapping[str, Any]`: Admit the bounded native authority transition under original identity and current SQL fences.
- `async project_purge_dispatch(authorization: object, point_ids: object, *, deadline: float) -> _PurgeDispatchPlan`: Produce a native issuer-bound projection from admitted durable state; callers cannot substitute a serialized copy.
- `async validate_purge_dispatch(plan: object, authorization: object, *, deadline: float) -> None`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async historical_purge(value: object, *, deadline: float) -> Mapping[str, Any]`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async complete_purge(verifier: object, receipt: object, *, deadline: float) -> Mapping[str, Any]`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.


### `cragkit.errors`

Import from `cragkit.errors`. [Module source](../packages/python/src/cragkit/errors.py).

#### `CragkitError`

Base type for catching public errors. Construct concrete subclasses, whose code/message are fixed and safely serialized.

[Source](../packages/python/src/cragkit/errors.py#L4).

Declared fields: `code`, `message`, `retryable`.

- `CragkitError() -> None`: Base implementation constructor; use a concrete fixed-message error such as InvalidRequest().
- `to_dict() -> dict[str, str | bool]`: Return the fixed redacted public error envelope.

#### `InvalidRequest`

Public fixed-message error with code invalid_request; see the error table above.

[Source](../packages/python/src/cragkit/errors.py#L16).

Construct this concrete error with no arguments; it inherits to_dict from CragkitError.

#### `UnauthorizedScope`

Public fixed-message error with code unauthorized_scope; see the error table above.

[Source](../packages/python/src/cragkit/errors.py#L21).

Construct this concrete error with no arguments; it inherits to_dict from CragkitError.

#### `UnsupportedCapability`

Public fixed-message error with code unsupported_capability; see the error table above.

[Source](../packages/python/src/cragkit/errors.py#L26).

Construct this concrete error with no arguments; it inherits to_dict from CragkitError.

#### `IndexNotReady`

Public fixed-message error with code index_not_ready; see the error table above.

[Source](../packages/python/src/cragkit/errors.py#L31).

Construct this concrete error with no arguments; it inherits to_dict from CragkitError.

#### `EmbeddingProfileMismatch`

Public fixed-message error with code embedding_profile_mismatch; see the error table above.

[Source](../packages/python/src/cragkit/errors.py#L37).

Construct this concrete error with no arguments; it inherits to_dict from CragkitError.

#### `ProviderUnavailable`

Public fixed-message error with code provider_unavailable; see the error table above.

[Source](../packages/python/src/cragkit/errors.py#L42).

Construct this concrete error with no arguments; it inherits to_dict from CragkitError.

#### `DeadlineExceeded`

Public fixed-message error with code deadline_exceeded; see the error table above.

[Source](../packages/python/src/cragkit/errors.py#L48).

Construct this concrete error with no arguments; it inherits to_dict from CragkitError.

#### `ContextBudgetTooSmall`

Public fixed-message error with code context_budget_too_small; see the error table above.

[Source](../packages/python/src/cragkit/errors.py#L54).

Construct this concrete error with no arguments; it inherits to_dict from CragkitError.

#### `IntegrityViolation`

Public fixed-message error with code integrity_violation; see the error table above.

[Source](../packages/python/src/cragkit/errors.py#L59).

Construct this concrete error with no arguments; it inherits to_dict from CragkitError.


### `cragkit.contracts.models`

- `InputString`, `Identity`, `Query`, `Collection`, `Scalar`, `Number`, `Integer`, `FilterField`, `Filter`: validated field aliases for the strict request/scope models; they are not runtime constructors. [Definitions](../packages/python/src/cragkit/contracts/models.py).

Import from `cragkit.contracts.models`. [Module source](../packages/python/src/cragkit/contracts/models.py).

#### `ContractModel`

Strict frozen base for native request/scope models; validation hooks are implementation details.

[Source](../packages/python/src/cragkit/contracts/models.py#L20).

Construct this concrete error with no arguments; it inherits to_dict from CragkitError.

#### `FilterModel`

Bounded filter model base; choose a concrete operator model.

[Source](../packages/python/src/cragkit/contracts/models.py#L31).

Construct this concrete error with no arguments; it inherits to_dict from CragkitError.

- `EqualityFilter`: reexport/definition of the interface documented under `cragkit.contracts`.
- `OrderFilter`: reexport/definition of the interface documented under `cragkit.contracts`.
- `MembershipFilter`: reexport/definition of the interface documented under `cragkit.contracts`.
- `GroupFilter`: reexport/definition of the interface documented under `cragkit.contracts`.
- `NotFilter`: reexport/definition of the interface documented under `cragkit.contracts`.
- `Limits`: reexport/definition of the interface documented under `cragkit.contracts`.
- `OutputProfile`: reexport/definition of the interface documented under `cragkit.contracts`.
- `ToolRequest`: reexport/definition of the interface documented under `cragkit.contracts`.
- `RetrievalRequest`: reexport/definition of the interface documented under `cragkit.contracts`.
- `TrustedScope`: reexport/definition of the interface documented under `cragkit.contracts`.

### `cragkit.contracts.results`

- `Digest`, `SafeCount`, `EvidenceIds`, `FacetIds`: validated digest/count/reference aliases used by result fields; they are not independent retrieval operations. [Definitions](../packages/python/src/cragkit/contracts/results.py).

Import from `cragkit.contracts.results`. [Module source](../packages/python/src/cragkit/contracts/results.py).

#### `digest`

Validate a lower-case SHA-256 digest used in the result models.

[Source](../packages/python/src/cragkit/contracts/results.py#L11).

```text
digest(value: str) -> str
```

#### `unique_ids`

Validate unique identity sequences for result contract consistency.

[Source](../packages/python/src/cragkit/contracts/results.py#L17).

```text
unique_ids(values: tuple[str, ...]) -> tuple[str, ...]
```

- `Evidence`: reexport/definition of the interface documented under `cragkit.contracts`.
- `Facet`: reexport/definition of the interface documented under `cragkit.contracts`.
- `Limitation`: reexport/definition of the interface documented under `cragkit.contracts`.
- `StageDuration`: reexport/definition of the interface documented under `cragkit.contracts`.
- `Usage`: reexport/definition of the interface documented under `cragkit.contracts`.
- `Versions`: reexport/definition of the interface documented under `cragkit.contracts`.
- `RetrievalResult`: reexport/definition of the interface documented under `cragkit.contracts`.

### `cragkit_langchain`

Import from `cragkit_langchain`. [Module source](../packages/langchain-python/src/cragkit_langchain/__init__.py).

#### `create_tool`

Create the narrow scope/template-bound LangChain retrieval tool with actual-wrapper serialization checks.

[Source](../packages/langchain-python/src/cragkit_langchain/__init__.py#L198).

```text
create_tool(engine: Any, *, template: object, scope: object, final_serializer: Callable[[str | ToolMessage], str], counter: Cl100kCounter | None=None, name: str='cragkit_retrieve') -> StructuredTool
```


### `cragkit_mcp`

Import from `cragkit_mcp`. [Module source](../packages/mcp-python/src/cragkit_mcp/__init__.py).

#### `RetrievalHost`

Scope-bound retrieval-only MCP host. Use create_server to validate configuration before serving.

[Source](../packages/mcp-python/src/cragkit_mcp/__init__.py#L112).

- `RetrievalHost(engine: Any, template: Any, scope: Any, serializer: Callable[[types.CallToolResult], str], counter: Cl100kCounter | None) -> None`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async retrieve(value: object) -> types.CallToolResult`: Retrieve scoped evidence under the request deadline and limits; inspect coverage and execution separately.
- `async run_streams(read_stream: Any, write_stream: Any) -> None`: Serve the MCP host over explicitly supplied native streams.
- `async run_stdio(*, stdin: Any=None, stdout: Any=None) -> None`: Explicitly serve the retrieval-only MCP host over stdio.
- `async close() -> None`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `create_server`

Create and validate the retrieval-only MCP host; serving is a separate explicit call.

[Source](../packages/mcp-python/src/cragkit_mcp/__init__.py#L280).

```text
create_server(engine: Any, *, template: object, scope: object, final_serializer: Callable[[types.CallToolResult], str], counter: Cl100kCounter | None=None) -> RetrievalHost
```


## TypeScript modules

### `cragkit`

Version only. Native execution lives in explicit modules.

Import from `cragkit`. [Entry source](../packages/typescript/src/index.ts).

- `version`: Package version string. [Declaration](../packages/typescript/src/index.ts#L1).

### `cragkit/contracts`

Schema objects expose Zod validation; type names are compile-time only. The parser functions provide the Cragkit error boundary.

Import from `cragkit/contracts`. [Entry source](../packages/typescript/src/contracts.ts).

- `EqualityFilterSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/requests.ts#L8).
- `OrderFilterSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/requests.ts#L9).
- `MembershipFilterSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/requests.ts#L10).
- `Filter`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/requests.ts#L12).
- `LimitsSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/requests.ts#L39).
- `OutputProfileSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/requests.ts#L48).
- `RequestSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/requests.ts#L61).
- `ToolRequestSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/requests.ts#L67).
- `TrustedScopeSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/requests.ts#L68).
- `RetrievalRequest`: Full application retrieval request, including required filters, limits and output profile. [Declaration](../packages/typescript/src/requests.ts#L74).
- `ToolRequest`: Narrow model-facing request; scope and required filters are absent. [Declaration](../packages/typescript/src/requests.ts#L75).
- `TrustedScope`: Trusted application-bound tenant/principal/authorization/grant identity. [Declaration](../packages/typescript/src/requests.ts#L76).
- `Limits`: Request-wide ceilings; see the request table above and adapter-specific limits. [Declaration](../packages/typescript/src/requests.ts#L77).
- `OutputProfile`: Renderer, tokenizer, wrapper reserve and counting mode. [Declaration](../packages/typescript/src/requests.ts#L78).
#### `parse_request`

Validate a full retrieval request and apply defaults; reject invalid native input with InvalidRequest.

[Source](../packages/typescript/src/requests.ts#L83).

```text
parse_request = (input: unknown): RetrievalRequest =>
```

#### `parse_tool_request`

Validate the narrow model-facing request; reject scope, filters or limits supplied as extra tool fields.

[Source](../packages/typescript/src/requests.ts#L84).

```text
parse_tool_request = (input: unknown): ToolRequest =>
```

#### `parse_scope`

Validate trusted host identity/scope; validation itself does not authenticate the caller.

[Source](../packages/typescript/src/requests.ts#L85).

```text
parse_scope = (input: unknown): TrustedScope =>
```

- `EvidenceSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/results.ts#L21).
- `FacetSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/results.ts#L32).
- `LimitationSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/results.ts#L38).
- `StageDurationSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/results.ts#L40).
- `UsageSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/results.ts#L53).
- `VersionsSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/results.ts#L58).
- `ResultSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/results.ts#L92).
- `RetrievalResult`: Validated result envelope with separate coverage and execution state. [Declaration](../packages/typescript/src/results.ts#L93).
- `Evidence`: Exact source-linked evidence with canonical byte spans and digests. [Declaration](../packages/typescript/src/results.ts#L94).
- `Facet`: Reviewed facet state and supporting evidence references. [Declaration](../packages/typescript/src/results.ts#L95).
- `Usage`: Known/estimated/unknown usage and stage timings. [Declaration](../packages/typescript/src/results.ts#L96).
- `Versions`: Engine/policy/model/tokenizer/index identifiers. [Declaration](../packages/typescript/src/results.ts#L97).
- `Limitation`: Closed limitation code. [Declaration](../packages/typescript/src/results.ts#L98).
- `StageDuration`: Bounded named stage duration. [Declaration](../packages/typescript/src/results.ts#L99).
#### `parse_result`

Validate cross-field evidence, facets, usage and result invariants.

[Source](../packages/typescript/src/results.ts#L100).

```text
function parse_result(input: unknown): RetrievalResult
```


### `cragkit/errors`

Import from `cragkit/errors`. [Entry source](../packages/typescript/src/errors.ts).

- `ErrorCode`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/errors.ts#L1).
- `ErrorEnvelope`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/errors.ts#L4).
#### `CragkitError`

Base type for catching public errors. Construct concrete subclasses, whose code/message are fixed and safely serialized.

[Source](../packages/typescript/src/errors.ts#L6).

Declared properties: `code`, `retryable`.

- `constructor(code: ErrorCode, message: string, retryable: boolean)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `to_dict(): ErrorEnvelope`: Return the fixed redacted public error envelope.
- `toJSON(): ErrorEnvelope`: Serialize the documented safe view, or reject serialization for opaque capability holders.

#### `InvalidRequest`

Public fixed-message error with code invalid_request; see the error table above.

[Source](../packages/typescript/src/errors.ts#L18).

- `constructor()`: Construct configuration and bind dependencies; perform explicit initialization separately where required.

#### `UnauthorizedScope`

Public fixed-message error with code unauthorized_scope; see the error table above.

[Source](../packages/typescript/src/errors.ts#L21).

- `constructor()`: Construct configuration and bind dependencies; perform explicit initialization separately where required.

#### `UnsupportedCapability`

Public fixed-message error with code unsupported_capability; see the error table above.

[Source](../packages/typescript/src/errors.ts#L24).

- `constructor()`: Construct configuration and bind dependencies; perform explicit initialization separately where required.

#### `IndexNotReady`

Public fixed-message error with code index_not_ready; see the error table above.

[Source](../packages/typescript/src/errors.ts#L27).

- `constructor()`: Construct configuration and bind dependencies; perform explicit initialization separately where required.

#### `EmbeddingProfileMismatch`

Public fixed-message error with code embedding_profile_mismatch; see the error table above.

[Source](../packages/typescript/src/errors.ts#L30).

- `constructor()`: Construct configuration and bind dependencies; perform explicit initialization separately where required.

#### `ProviderUnavailable`

Public fixed-message error with code provider_unavailable; see the error table above.

[Source](../packages/typescript/src/errors.ts#L33).

- `constructor()`: Construct configuration and bind dependencies; perform explicit initialization separately where required.

#### `DeadlineExceeded`

Public fixed-message error with code deadline_exceeded; see the error table above.

[Source](../packages/typescript/src/errors.ts#L36).

- `constructor()`: Construct configuration and bind dependencies; perform explicit initialization separately where required.

#### `ContextBudgetTooSmall`

Public fixed-message error with code context_budget_too_small; see the error table above.

[Source](../packages/typescript/src/errors.ts#L39).

- `constructor()`: Construct configuration and bind dependencies; perform explicit initialization separately where required.

#### `IntegrityViolation`

Public fixed-message error with code integrity_violation; see the error table above.

[Source](../packages/typescript/src/errors.ts#L42).

- `constructor()`: Construct configuration and bind dependencies; perform explicit initialization separately where required.


### `cragkit/postgres`

Import from `cragkit/postgres`. [Entry source](../packages/typescript/src/postgres.ts).

#### `PoolResource`

Explicit bounded pool lifecycle. The default owns its driver pool; an injected pool remains caller-owned.

[Source](../packages/typescript/src/postgres-pool.ts#L131).

Declared properties: `config`.

- `constructor(config: PoolConfig, options: { pool?: PgPool; factory?: PoolFactory } = {})`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async open(): Promise<void>`: Open and validate the bounded resource before use.
- `async withLease<T>(options: LeaseOptions, body: (client: PgClient, signal: AbortSignal) => Promise<T>): Promise<T>`: Run the callback under a bounded connection lease and release it afterward.
- `async close(): Promise<void>`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `parse_pool_config`

Validate scalar database settings and absolute private credential/CA paths.

[Source](../packages/typescript/src/postgres-pool.ts#L24).

```text
function parse_pool_config(input: unknown): PoolConfig
```

#### `now`

Read monotonic seconds for absolute operation deadlines.

[Source](../packages/typescript/src/postgres-pool.ts#L43).

```text
now = (): number =>
```

- `PoolConfig`: Bounded native PostgreSQL configuration. CA and password-file paths are absolute; credentials stay in private files. [Declaration](../packages/typescript/src/postgres-pool.ts#L23).
- `LeaseOptions`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/postgres-pool.ts#L42).
#### `PostgresIndexer`

Canonicalize and publish lexical source generations through a restricted writer resource.

[Source](../packages/typescript/src/ingestion.ts#L168).

- `constructor(private readonly resource: PoolResource, private readonly authorize_write: WriteAuthorizer)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async ingest(source: string | Uint8Array, input: IngestOptions): Promise<IngestionReceipt>`: Canonicalize and durably publish a generation; matching intent retries report replay instead of mutating immutable payload.

- `IngestionReceipt`: Immutable publication identity and payload/source digests, with replay state. [Declaration](../packages/typescript/src/ingestion.ts#L13).
- `IngestOptions`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/ingestion.ts#L19).
- `type WriteAuthorizer = (scope: TrustedScope, collection: string, document_id: string) => Promise<boolean>`: Asynchronous per-document write decision; return an actual boolean.
#### `PostgresLifecycle`

Apply explicitly authorized tombstones and purge eligible tombstoned source records.

[Source](../packages/typescript/src/lifecycle.ts#L115).

- `constructor(private readonly resource: PoolResource, private readonly authorize_lifecycle: LifecycleAuthorizer)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `tombstone(input: LifecycleOptions): Promise<LifecycleReceipt>`: Admit the authorized tombstone; replica completion is a separate state.
- `purge_tombstoned(input: LifecycleOptions): Promise<LifecycleReceipt>`: Purge eligible tombstoned PostgreSQL data after lifecycle authorization and generation checks.

- `LifecycleReceipt`: Document lifecycle outcome, active generation and whether state changed. [Declaration](../packages/typescript/src/lifecycle.ts#L9).
- `LifecycleOptions`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/lifecycle.ts#L15).
- `type LifecycleAuthorizer = (scope: TrustedScope, collection: string, document_id: string, operation: 'tombstone' | 'purge') => Promise<boolean>`: Asynchronous document/action lifecycle decision; return an actual boolean.
#### `PostgresRetriever`

Borrow an opened PostgreSQL resource for lexical, dense or hybrid retrieval. Optional evidence configuration enables packing/assessment/reranking.

[Source](../packages/typescript/src/retrieval.ts#L18).

- `constructor(private readonly resource: PoolResource, options: RetrieverOptions = {})`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async retrieve(input: RetrievalRequest, options: LeaseOptions & {scope: TrustedScope}): Promise<RetrievalResult>`: Retrieve scoped evidence under the request deadline and limits; inspect coverage and execution separately.

#### `RetrieverOptions`

Options/protocol shape for this module; its declared fields and methods below define the boundary.

[Source](../packages/typescript/src/hybrid.ts#L17).

Declared properties: `mode`, `embedding_profile`, `embedder`, `allow_degraded`, `identifiers`, `evidence_options`.


- `EvidenceConfiguration`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/hybrid.ts#L16).
#### `PostgresVectorIndexer`

Stage and publish exact embedding-profile generations with bounded embedding batches.

[Source](../packages/typescript/src/vector-ingestion.ts#L59).

- `constructor(private readonly resource: PoolResource, private readonly authorize_write: lexical.WriteAuthorizer, private readonly embedder: EmbeddingAdapter, limits: { max_batches?: number; max_attempts?: number; embedding_profile?: EmbeddingProfile } = {})`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async stage(source: string | Uint8Array, input: lexical.IngestOptions): Promise<VectorIngestionReceipt>`: Stage immutable generation data without claiming the later publication is complete.
- `async publish(source: string | Uint8Array, input: lexical.IngestOptions): Promise<VectorIngestionReceipt>`: Publish the admitted staged generation after required checks and original-fence comparison.
- `async ingest(source: string | Uint8Array, input: lexical.IngestOptions): Promise<VectorIngestionReceipt>`: Canonicalize and durably publish a generation; matching intent retries report replay instead of mutating immutable payload.

- `VectorIngestionReceipt`: Ingestion receipt extended with embedding profile, calls and usage. [Declaration](../packages/typescript/src/vector-ingestion.ts#L15).

### `cragkit/qdrant`

Import from `cragkit/qdrant`. [Entry source](../packages/typescript/src/qdrant.ts).

- `QdrantSearchOptions`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/qdrant.ts#L14).
#### `QdrantSearchStore`

Initialized candidate replica only. Search results are UNVERIFIED nominations; this store releases no source text.

[Source](../packages/typescript/src/qdrant.ts#L24).

Declared properties: `config`.

- `constructor(config:unknown,transport:QdrantTransport)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `capabilities()`: Return the supported capability flags rather than inferring them from an adapter name.
- `async initialize(options:OperationOptions):Promise<void>`: Validate/admit the selected native profile before operations; it does not apply SQL migrations.
- `async search_candidates(input:unknown,options:QdrantSearchOptions):Promise<readonly QdrantNomination[]>`: Return scoped UNVERIFIED Qdrant nominations; source authorization remains a separate step.
- `async close():Promise<void>`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `FetchQdrantTransport`

Optional Node fetch transport. Enforces endpoint, response-size, deadline and cancellation rules.

[Source](../packages/typescript/src/qdrant-transport.ts#L24).

Declared properties: `bounded_responses`, `cancellation_safe`.

- `constructor(endpoint:unknown,options:{api_key?:string;allow_loopback_http?:boolean;fetch?:typeof fetch}={})`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async request(method:string,path:string,options:QdrantTransportOptions):Promise<Uint8Array>`: Perform one bounded transport request using the supplied absolute deadline.
- `async close():Promise<void>`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `QdrantTransport`

Bounded, cancellation-safe candidate HTTP transport protocol. A store borrows it.

[Source](../packages/typescript/src/qdrant-transport.ts#L4).

Declared properties: `bounded_responses`, `cancellation_safe`.

- `request(method:string,path:string,options:QdrantTransportOptions):Promise<Uint8Array>`: Perform one bounded transport request using the supplied absolute deadline.

- `QdrantTransportOptions`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/qdrant-transport.ts#L3).
#### `bind_embedding_batch`

Validate a complete E-r1 batch against the selected exact dense profile and expected item count.

[Source](../packages/typescript/src/qdrant-contract.ts#L56).

```text
function bind_embedding_batch(batch:unknown,profile:unknown,options:{expected_items?:number}={}):EmbeddingBatch
```

#### `point_id`

Derive the deterministic point UUID from the complete immutable identity.

[Source](../packages/typescript/src/qdrant-contract.ts#L80).

```text
function point_id(tuple: unknown):string
```

#### `compile_filter`

Compile required filters together with trusted tenant/principal/grant scope; unsupported operators fail closed.

[Source](../packages/typescript/src/qdrant-contract.ts#L97).

```text
function compile_filter(request:unknown,scope:unknown):Readonly<Record<string,unknown>>
```

- `SPARSE_PROFILE`: Synthetic caller-supplied sparse fixture profile, not BM25. [Declaration](../packages/typescript/src/qdrant-contract.ts#L8).
- `QdrantConfigSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/qdrant-contract.ts#L11).
- `QdrantPayloadSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/qdrant-contract.ts#L76).
- `QdrantConfig`: Namespace, physical collection/incarnation, complete dense profile and optional supported sparse profile. [Declaration](../packages/typescript/src/qdrant-contract.ts#L12).
- `QdrantPayload`: Candidate-side metadata shape; it is not a source-authority decision. [Declaration](../packages/typescript/src/qdrant-contract.ts#L77).
- `QdrantNomination`: Point identity, branch, score semantics, UNVERIFIED marker and candidate payload. [Declaration](../packages/typescript/src/qdrant-contract.ts#L79).

### `cragkit/embeddings`

Import from `cragkit/embeddings`. [Entry source](../packages/typescript/src/embeddings.ts).

- `EmbeddingProfileSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/embeddings.ts#L7).
- `EmbeddingProfile`: Full embedding identity; matching dimension count alone is insufficient. [Declaration](../packages/typescript/src/embeddings.ts#L8).
- `FAKE_PROFILE`: Synthetic-only deterministic profile; it does not establish live-model quality. [Declaration](../packages/typescript/src/embeddings.ts#L9).
- `OPENAI_PROFILE`: Pinned text-embedding-3-small, 1536 dimensions, cl100k_base, L2 normalization profile. [Declaration](../packages/typescript/src/embeddings.ts#L10).
- `EmbeddingLimitsSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/embeddings.ts#L12).
- `EmbeddingLimits`: Per-call item, byte, token and response limits; these are bounded independently of request totals. [Declaration](../packages/typescript/src/embeddings.ts#L13).
- `EmbeddingPolicySchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/embeddings.ts#L15).
- `EmbeddingPolicy`: Explicit live-call admission, cost bound and optional token price for estimates. [Declaration](../packages/typescript/src/embeddings.ts#L16).
- `EmbeddingUsageSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/embeddings.ts#L17).
- `EmbeddingUsage`: Reported/unknown token and cost accounting for an embedding call. [Declaration](../packages/typescript/src/embeddings.ts#L18).
- `EmbeddingBatchSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/embeddings.ts#L19).
- `EmbeddingBatch`: Bound profile, vectors, usage, call count and synthetic marker. [Declaration](../packages/typescript/src/embeddings.ts#L20).
#### `TokenCounter`

Application-injected counting protocol with a declared tokenizer name.

[Source](../packages/typescript/src/embeddings.ts#L21).

Declared properties: `name`.

- `count(text: string): number`: Count the supplied string using the declared tokenizer.

- `type EmbeddingTransport = (body: Uint8Array, options: { deadline: number; signal: AbortSignal; max_response_bytes: number }) => Promise<Uint8Array>`: Application-injected callable protocol; follow its declared deadline, cancellation and byte bounds.
#### `EmbeddingOptions`

Options/protocol shape for this module; its declared fields and methods below define the boundary.

[Source](../packages/typescript/src/embeddings.ts#L23).

Declared properties: `deadline`, `signal`, `on_dispatch`.


#### `EmbeddingAdapter`

Validate and bound one query or batch embedding call through the injected transport and tokenizer.

[Source](../packages/typescript/src/embeddings.ts#L90).

Declared properties: `profile`, `limits`, `policy`.

- `constructor(transport: EmbeddingTransport, token_counter: TokenCounter, options: { profile?: EmbeddingProfile; limits?: z.input<typeof EmbeddingLimitsSchema>; policy?: z.input<typeof EmbeddingPolicySchema> } = {})`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async embed_query(text: string, options: EmbeddingOptions): Promise<EmbeddingBatch>`: Validate and embed one query, recording profile and usage.
- `async embed_batch(texts: readonly string[], options: EmbeddingOptions): Promise<EmbeddingBatch>`: Validate and embed a bounded batch, preserving item order and profile.


### `cragkit/reranking`

Import from `cragkit/reranking`. [Entry source](../packages/typescript/src/reranking.ts).

- `RerankProfileSchema`: Runtime Zod validator for the corresponding contract. [Declaration](../packages/typescript/src/reranking.ts#L11).
- `RerankProfile`: Model revision, preprocessing, score kind/direction and truncation policy for reranking. [Declaration](../packages/typescript/src/reranking.ts#L16).
- `FAKE_RERANK_PROFILE`: Synthetic-only deterministic profile; it does not establish live-model quality. [Declaration](../packages/typescript/src/reranking.ts#L17).
- `RerankCandidate`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/reranking.ts#L20).
- `RerankScore`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/reranking.ts#L21).
- `RerankResult`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/reranking.ts#L22).
- `type RerankTransport = (body: Uint8Array, options: { deadline: number; signal: AbortSignal; max_response_bytes: number }) => Promise<Uint8Array>`: Application-injected callable protocol; follow its declared deadline, cancellation and byte bounds.
#### `RerankOptions`

Options/protocol shape for this module; its declared fields and methods below define the boundary.

[Source](../packages/typescript/src/reranking.ts#L24).

Declared properties: `deadline`, `signal`, `max_provider_calls`, `allow_fallback`.


#### `RerankingAdapter`

Validate bounded candidate views, rank identity/order and declared fallback behavior.

[Source](../packages/typescript/src/reranking.ts#L85).

Declared properties: `profile`.

- `constructor(transport: RerankTransport, options: { profile?: RerankProfile; allow_live?: boolean } = {})`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async rank(query: string, candidates: readonly RerankCandidate[], options: RerankOptions): Promise<RerankResult>`: Rank the bounded candidate IDs with score direction, truncation and fallback validation.


### `cragkit/context`

Import from `cragkit/context`. [Entry source](../packages/typescript/src/context.ts).

- `CONTEXT_RENDERER`: Identifier cragkit.context.v2 for the exact evidence renderer. [Declaration](../packages/typescript/src/context.ts#L7).
#### `Cl100kCounter`

Pinned, local cl100k tokenizer counter. Use its factory rather than direct construction.

[Source](../packages/typescript/src/context.ts#L13).

Declared properties: `tokenizer`.

- `static async create(path: string | URL): Promise<Cl100kCounter>`: Create the counter from the caller-supplied pinned local tokenizer file.
- `close(): void`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.
- `count(value: unknown): number`: Count the supplied string using the declared tokenizer.

#### `render_context`

Serialize exact evidence fields as the selected compact JSON representation.

[Source](../packages/typescript/src/context.ts#L52).

```text
function render_context(input: unknown): string
```

- `ContextOptions`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/context.ts#L76).
- `CountedContext`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/context.ts#L80).
#### `count_context`

Render and count the selected evidence representation plus reserve; enforce the configured counting mode.

[Source](../packages/typescript/src/context.ts#L84).

```text
function count_context(input: unknown, options: ContextOptions): CountedContext
```


### `cragkit/packing`

Import from `cragkit/packing`. [Entry source](../packages/typescript/src/packing.ts).

- `PackingOptions`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/packing.ts#L8).
- `PackedEvidence`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/packing.ts#L9).
#### `pack_evidence`

Pack verified exact source slices, deduplicate/merge eligible spans, and enforce serialization/token bounds.

[Source](../packages/typescript/src/packing.ts#L40).

```text
async function pack_evidence(input: unknown, sourceInput: unknown, options: PackingOptions): Promise<PackedEvidence>
```


### `cragkit/assessment`

Import from `cragkit/assessment`. [Entry source](../packages/typescript/src/assessment.ts).

#### `validate_assessment`

Validate facet/evidence references and conservative assessment invariants.

[Source](../packages/typescript/src/assessment.ts#L32).

```text
function validate_assessment(evidence: unknown, facets: unknown): readonly Facet[]
```

- `Assessment`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/assessment.ts#L44).
#### `assess_evidence`

Assess evidence against the supplied reviewed policy; unknown coverage cannot become sufficient.

[Source](../packages/typescript/src/assessment.ts#L47).

```text
function assess_evidence(query: unknown, evidence: unknown, policy: unknown = null): Assessment
```


### `cragkit/evidence`

Import from `cragkit/evidence`. [Entry source](../packages/typescript/src/evidence.ts).

- `EvidenceOptions`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/evidence.ts#L7).
- `AssessedEvidence`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/evidence.ts#L8).
#### `pack_and_assess`

Pack, reassess surviving evidence, and optionally perform one bounded rebalance.

[Source](../packages/typescript/src/evidence.ts#L10).

```text
async function pack_and_assess(query: unknown, evidence: unknown, sources: unknown, options: EvidenceOptions): Promise<AssessedEvidence>
```


### `cragkit/execution`

Import from `cragkit/execution`. [Entry source](../packages/typescript/src/execution.ts).

#### `BudgetExhausted`

The next ledger reservation cannot fit a declared request limit.

[Source](../packages/typescript/src/execution.ts#L17).

- `constructor()`: Construct configuration and bind dependencies; perform explicit initialization separately where required.

- `Reservation`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/execution.ts#L21).
- `ExecutionSnapshot`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/execution.ts#L23).
#### `ExecutionLedger`

Request-local atomic reservations. Reserve before dispatch, reconcile reported usage after completion, and abandon unresolved work honestly.

[Source](../packages/typescript/src/execution.ts#L28).

- `constructor(options: {limits: unknown; deadline: number})`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `deadline: number` (read-only getter): the shared effective monotonic deadline.
- `close(): void`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.
- `reserve(options: {provider_calls?: number; candidates?: number; attempts?: number; cost_upper_usd?: number | null} = {}): Reservation`: Reserve bounded calls, candidates, attempts and optional cost before dispatch.
- `dispatch(reservation: Reservation): void`: Mark the exact reservation as dispatched before external work starts.
- `reconcile(reservation: Reservation, options: {input_tokens?: number | null; output_tokens?: number | null; cost_usd?: number | null} = {}): void`: Reconcile one dispatched reservation with actual/unknown token and cost usage.
- `abandon(reservation: Reservation): void`: Preserve honest accounting for a reservation that cannot be reconciled.
- `snapshot(): ExecutionSnapshot`: Read immutable bounded accounting/queue diagnostics.


### `cragkit/planning`

Import from `cragkit/planning`. [Entry source](../packages/typescript/src/planning.ts).

- `ApprovedVariant`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/planning.ts#L15).
- `PlanningResult`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/planning.ts#L17).
- `type PlannerTransport = (payload: DeepReadonly<Config>, options: {deadline: number; signal: AbortSignal}) => Promise<unknown>`: Application-injected callable protocol; follow its declared deadline, cancellation and byte bounds.
#### `validate_plan`

Validate allowed original/variant queries and prevent changes to trusted request constraints.

[Source](../packages/typescript/src/planning.ts#L35).

```text
function validate_plan(value: unknown, options: unknown): readonly ApprovedVariant[]
```

#### `PlannerAdapter`

Validate bounded rewrites while preserving the original query, scope, required filters and limits.

[Source](../packages/typescript/src/planning.ts#L60).

- `constructor(options: {transport: PlannerTransport; sdk_retries?: number; cost_upper_usd?: number | null; allow_fallback?: boolean})`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async plan(options: {query: unknown; variants: unknown; missing_facets: unknown; max_subqueries: unknown; ledger: ExecutionLedger; deadline: number; signal?: AbortSignal}): Promise<PlanningResult>`: Call the planner and validate allowed query variants/fallback under the request bounds.


### `cragkit/corrective`

Import from `cragkit/corrective`. [Entry source](../packages/typescript/src/corrective.ts).

- `CorrectiveCandidate`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/corrective.ts#L36).
- `CorrectiveBackendOptions`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/corrective.ts#L37).
#### `CorrectiveBackend`

Options/protocol shape for this module; its declared fields and methods below define the boundary.

[Source](../packages/typescript/src/corrective.ts#L38).

Declared properties: `candidate_accounting`, `result_versions`.

- `search(request: RetrievalRequest, options: CorrectiveBackendOptions & {limit: number}): Promise<unknown>`: Return scoped candidate identities through the backend search contract.
- `capture(candidates: readonly CorrectiveCandidate[], options: CorrectiveBackendOptions & {request: RetrievalRequest; max_source_bytes: number}): Promise<unknown>`: Reauthorize and capture exact source evidence for selected candidates.

- `CorrectiveResponse`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/corrective.ts#L44).
#### `CorrectiveRetriever`

Bounded attempts over a trusted backend; returns a result plus diagnostics and stop reason. It borrows its backend.

[Source](../packages/typescript/src/corrective.ts#L60).

- `constructor(options: {backend: CorrectiveBackend; policy?: unknown; variants?: unknown; planner?: PlannerAdapter | null; counter?: Cl100kCounter | null; event_sink?:EventSink|null; batch_size?: number; max_retries?: number; backoff_ms?: number; no_progress_limit?: number})`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async retrieve(input: unknown, options: {scope: unknown; deadline: number; signal?: AbortSignal}): Promise<CorrectiveResponse>`: Retrieve scoped evidence under the request deadline and limits; inspect coverage and execution separately.


### `cragkit/postgres-corrective`

Import from `cragkit/postgres-corrective`. [Entry source](../packages/typescript/src/postgres-corrective.ts).

#### `PostgresCorrectiveBackend`

PostgreSQL search and source-capture boundary for CorrectiveRetriever.

[Source](../packages/typescript/src/postgres-corrective.ts#L31).

Declared properties: `result_versions`.

- `constructor(options:{resource:PoolResource;mode?:'lexical'|'dense'|'hybrid';embedder?:EmbeddingAdapter;embedding_profile?:EmbeddingProfile;reranker?:RerankingAdapter})`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async search(input:RetrievalRequest, options:Bound & {limit:number})`: Return scoped candidate identities through the backend search contract.
- `async capture(input:readonly LexicalCandidate[], options:Bound & {request:RetrievalRequest;max_source_bytes:number})`: Reauthorize and capture exact source evidence for selected candidates.


### `cragkit/events`

Import from `cragkit/events`. [Entry source](../packages/typescript/src/events.ts).

- `EventStage`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/events.ts#L15).
- `EventFields`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/events.ts#L16).
- `ExecutionEvent`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/events.ts#L17).
- `EventSnapshot`: Compile-time contract shape for this entry point. [Declaration](../packages/typescript/src/events.ts#L18).
- `type EventExporter=(event:ExecutionEvent,options:{deadline:number;signal:AbortSignal})=>Promise<unknown>`: Application-injected callable protocol; follow its declared deadline, cancellation and byte bounds.
#### `new_trace`

Create a new opaque local trace identifier.

[Source](../packages/typescript/src/events.ts#L20).

```text
function new_trace():string
```

#### `EventSink`

Bounded event queue and export lifecycle. Exporter failures do not become successful retrieval evidence.

[Source](../packages/typescript/src/events.ts#L33).

- `constructor(options:{exporter?:EventExporter|null;capacity?:number;timeout_ms?:number}={})`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `emit(stage:EventStage,options:EventFields):boolean`: Enqueue a validated redacted event without unbounded growth.
- `snapshot():EventSnapshot`: Read immutable bounded accounting/queue diagnostics.
- `drain():readonly ExecutionEvent[]`: Return and remove queued events locally, accounting for them as drained/dropped; this does not invoke the exporter.
- `close():void`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.
- `async flush(options:{deadline:number;signal?:AbortSignal}):Promise<EventSnapshot>`: Asynchronously export queued events under the deadline and report delivered/dropped/queued counts.


### `cragkit/qdrant-source`

Import from `cragkit/qdrant-source`. [Entry source](../packages/typescript/src/qdrant-source.ts).

#### `PostgresQdrantSourceStore`

Initialized authoritative SQL source/ACL reader bound to the same complete Qdrant configuration.

[Source](../packages/typescript/src/qdrant-source.ts#L114).

Declared properties: `config`.

- `constructor(resource:PoolResource,config:unknown)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `capabilities()`: Return the supported capability flags rather than inferring them from an adapter name.
- `async initialize(options:DeadlineOptions):Promise<void>`: Validate/admit the selected native profile before operations; it does not apply SQL migrations.
- `open_request(input:unknown,options:DeadlineOptions&{scope:unknown}):SourceRequest`: Create one request-bound source handle using independently supplied trusted scope.
- `async close():Promise<void>`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.
- `toJSON()`: Serialize the documented safe view, or reject serialization for opaque capability holders.

#### `SourceFetch`

Verified/unavailable/budget-exhausted read outcome. Opaque binding and private source are excluded from ordinary serialization.

[Source](../packages/typescript/src/qdrant-source-contract.ts#L14).

- `constructor(readonly state:SourceState,readonly evidence:Evidence|null,readonly binding:object|null,readonly source_bytes:number,readonly stale:boolean,readonly private_source:PrivateSource|null)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `toJSON()`: Serialize the documented safe view, or reject serialization for opaque capability holders.


#### Returned `SourceRequest` handle

Obtain this handle from `PostgresQdrantSourceStore.open_request`; it is not a
named export from `cragkit/qdrant-source`. Its operations are:

- `fetch_candidate(input: unknown, options: {max_source_bytes: number; include_source?: boolean}): Promise<SourceFetch>`: verify the nomination against current authority and issue its request-bound opaque binding.
- `release(binding: unknown, options: {purpose: 'provider' | 'final'; max_source_bytes: number; include_source?: boolean}): Promise<SourceFetch>`: reauthorize the same binding before the selected release.
- `close(): Promise<void>`: cancel/drain the owned request and free the store's single handle slot.
- `toJSON()`: reject serialization of the request-bound capability holder.

The source and private binding remain outside safe public serialization.

### `cragkit/qdrant-corrective`

Import from `cragkit/qdrant-corrective`. [Entry source](../packages/typescript/src/qdrant-corrective.ts).

#### `QdrantCorrectiveBackend`

Compose initialized Qdrant candidates and PostgreSQL sources with an explicit embedding transport; dense mode only.

[Source](../packages/typescript/src/qdrant-corrective.ts#L24).

Declared properties: `candidate_accounting`.

- `constructor(candidates:QdrantSearchStore,sources:PostgresQdrantSourceStore,options:{ embedding_transport:EmbeddingTransport;token_counter:TokenCounter;policy?:Partial<EmbeddingPolicy>;mode?:string})`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `capabilities()`: Return the supported capability flags rather than inferring them from an adapter name.
- `async search(input:RetrievalRequest,options:CorrectiveBackendOptions&{limit:number}):Promise<{candidates:readonly Candidate[];degraded:boolean}>`: Return scoped candidate identities through the backend search contract.
- `async capture(input:readonly CorrectiveCandidate[],options:CorrectiveBackendOptions&{request:RetrievalRequest;max_source_bytes:number})`: Reauthorize and capture exact source evidence for selected candidates.


### `cragkit/qdrant-publication`

The ten exported managed classes form one original-identity graph. Low-level controller/authority operations do not replace manager admission.

Import from `cragkit/qdrant-publication`. [Entry source](../packages/typescript/src/qdrant-publication.ts).

#### `PostgresQdrantPublicationAuthority`

Bind the exact writer and recovery objects. This holder does not grant readiness or authorization.

[Source](../packages/typescript/src/qdrant-publication.ts#L61).

- `constructor(writer:PostgresQdrantWriter,recovery:PostgresQdrantRecovery|null)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.

#### `ManagedQdrantPublicationTransport`

Borrow the actual native controller and manage attempt transport handles; close does not close the controller.

[Source](../packages/typescript/src/qdrant-publication.ts#L71).

- `constructor(supervisor:OrdinaryPublicationController)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async close():Promise<void>`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `QdrantPublicationManager`

Managed stage, publish, repair, current-security convergence and scoped purge. Authorize every operation with application code.

[Source](../packages/typescript/src/qdrant-publication.ts#L94).

- `constructor(authority:PostgresQdrantPublicationAuthority,transport:ManagedQdrantPublicationTransport, config:unknown,supervisor:OrdinaryPublicationController,authorize_write:Authorizer)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async initialize(rawOptions:unknown):Promise<void>`: Validate/admit the selected native profile before operations; it does not apply SQL migrations.
- `async stage(change:unknown,inputScope:unknown,ledger:ExecutionLedger,rawOptions:unknown):Promise<Result>`: Stage immutable generation data without claiming the later publication is complete.
- `async publish(input:unknown,inputScope:unknown,ledger:ExecutionLedger,rawOptions:unknown):Promise<Result>`: Publish the admitted staged generation after required checks and original-fence comparison.
- `async repair(input:unknown,inputScope:unknown,ledger:ExecutionLedger,rawOptions:unknown):Promise<Result>`: Run managed recovery/readback of the original intent before final publication; no caller replacement proof is accepted.
- `async converge_security(input:unknown,inputScope:unknown,ledger:ExecutionLedger,rawOptions:unknown):Promise<Result>`: Refence, repair and verify the claimed current authorization replica set.
- `async purge(input:unknown,inputScope:unknown,ledger:ExecutionLedger,retention_policy:unknown,rawOptions:unknown):Promise<Result>`: Erase the admitted managed scope under the explicit retention policy; application backups remain outside this operation.
- `async close():Promise<void>`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `QdrantSecurityManager`

Independent SQL authorization/tombstone admission. Replica convergence and physical purge are separate operations.

[Source](../packages/typescript/src/qdrant-security.ts#L37).

- `constructor(writer:PostgresQdrantWriter,authorize_write:Authorizer)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async initialize(rawOptions:unknown):Promise<void>`: Validate/admit the selected native profile before operations; it does not apply SQL migrations.
- `async update_authorization(record:unknown,scope:unknown,ledger:ExecutionLedger,options:unknown):Promise<SecurityResult>`: Commit the explicit current authorization intent without claiming replica convergence.
- `async tombstone(record:unknown,scope:unknown,ledger:ExecutionLedger,options:unknown):Promise<SecurityResult>`: Admit the authorized tombstone; replica completion is a separate state.
- `async close():Promise<void>`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `PostgresQdrantWriter`

Restricted durable SQL authority used by the managed graph. Low-level methods require original native capabilities and validated state.

[Source](../packages/typescript/src/qdrant-writer.ts#L367).

- `constructor(resource: PoolResource, config: unknown, instance_id: unknown)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async initialize(input:unknown):Promise<void>`: Validate/admit the selected native profile before operations; it does not apply SQL migrations.
- `async inspect(input:unknown,rawOptions:unknown):Promise<IntentView|null>`: Read the admitted durable intent state without releasing source data.
- `async preflight_repair(input:unknown,rawOptions:unknown):Promise<Readonly<{intent:IntentView;owner:ManagerOwner|null;backend:ManagerBackend;pending:boolean}>>`: Read and validate the original intent/owner/backend/pending state before managed repair admission.
- `async manager_snapshot(input:unknown,rawOptions:unknown):Promise<ManagerSnapshot>`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `async admit_publication(input:unknown,rawOptions:unknown):Promise<PublicationAdmission>`: Admit the bounded native authority transition under original identity and current SQL fences.
- `async stage(plan:unknown,inputScope:unknown,rawOptions:unknown):Promise<IntentView>`: Stage immutable generation data without claiming the later publication is complete.
- `async load_stage(input:unknown,rawOptions:unknown):Promise<StagePlan>`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async project_recovery_dispatch(authorization:unknown,input:unknown,rawIds:unknown,rawOptions:unknown):Promise<RecoveryDispatchPlan>`: Produce a native issuer-bound projection from admitted durable state; callers cannot substitute a serialized copy.
- `async validate_recovery_dispatch(plan:unknown,authorization:unknown,rawOptions:unknown):Promise<void>`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async project_purge(input:unknown,policy:unknown,rawOptions:unknown):Promise<PurgeProjection>`: Produce a native issuer-bound projection from admitted durable state; callers cannot substitute a serialized copy.
- `async reserve_purge_capacity(input:unknown,batches:unknown,rawOptions:unknown):Promise<void>`: Admit the bounded native authority transition under original identity and current SQL fences.
- `async validate_purge_projection(input:unknown,rawOptions:unknown):Promise<void>`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async project_security(input:unknown,rawOptions:unknown):Promise<SecurityProjection>`: Produce a native issuer-bound projection from admitted durable state; callers cannot substitute a serialized copy.
- `async validate_security_projection(input:unknown,rawOptions:unknown):Promise<void>`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async admit_purge_successor(input:unknown,rawPredecessor:unknown,rawIdentity:unknown,rawOptions:unknown):Promise<Readonly<{owner_token:string;backend_epoch:number}>>`: Admit the bounded native authority transition under original identity and current SQL fences.
- `async admit_purge_tombstone(input:unknown,rawOptions:unknown):Promise<SecurityOwner>`: Admit the bounded native authority transition under original identity and current SQL fences.
- `async confirm_purge(input:unknown,policy:unknown,rawOptions:unknown):Promise<IntentView>`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async complete_purge(verifier:QdrantSecurityVerifier,receipt:unknown,rawOptions:unknown):Promise<IntentView>`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async project_security_dispatch(authorization:unknown,rawIds:unknown,rawOptions:unknown):Promise<SecurityDispatchPlan>`: Produce a native issuer-bound projection from admitted durable state; callers cannot substitute a serialized copy.
- `async validate_security_dispatch(plan:unknown,authorization:unknown,rawOptions:unknown):Promise<void>`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async project_purge_dispatch(authorization:unknown,rawIds:unknown,rawOptions:unknown):Promise<PurgeDispatchPlan>`: Produce a native issuer-bound projection from admitted durable state; callers cannot substitute a serialized copy.
- `async validate_purge_dispatch(plan:unknown,authorization:unknown,rawOptions:unknown):Promise<void>`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async project_stage(input:unknown,rawPhysical:unknown,rawOptions:unknown):Promise<ExpectedProjection>`: Produce a native issuer-bound projection from admitted durable state; callers cannot substitute a serialized copy.
- `async validate_projection(input:unknown,rawOptions:unknown):Promise<void>`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async project_publication(input:unknown,rawAttempt:unknown,rawOptions:unknown):Promise<PublicationProjection>`: Produce a native issuer-bound projection from admitted durable state; callers cannot substitute a serialized copy.
- `async validate_publication_projection(input:unknown,rawOptions:unknown):Promise<void>`: Validate the original issuer-bound managed projection/capability under current SQL fences.
- `async acquire_owner(input:unknown,rawOptions:unknown):Promise<Readonly<{owner_token:string;backend_epoch:number}>>`: Admit the bounded native authority transition under original identity and current SQL fences.
- `async dispatch_status(input:unknown,rawId:unknown,rawOptions:unknown):Promise<DispatchStatus|null>`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `async attestation_snapshot(input:unknown,rawOptions:unknown):Promise<Readonly<{preparation:PreparationMetadata;attestation:PreparationAttestation|null}>>`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `async attest_prepared(receipt:unknown,verifier:QdrantPublicationVerifier,rawOptions:unknown):Promise<Readonly<{intent:IntentView;attestation:PreparationAttestation|null}>>`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async publication_preparation(input:unknown,rawOptions:unknown):Promise<Readonly<{ preparation:Readonly<{owner_token:string;backend_epoch:number;authorization_revision:string;mutation_epoch:number; manifest_sha256:string;readback_sha256:string}>;dispatch:DispatchStatus; }>|null>`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `async reserve_dispatch(input:unknown,rawDispatch:unknown,rawOptions:unknown):Promise<DispatchView>`: Admit the bounded native authority transition under original identity and current SQL fences.
- `async mark_dispatched(context:unknown,dispatch_id:unknown,options:unknown):Promise<void>`: Journal the exact dispatch lifecycle; a lost acknowledgment remains unresolved until managed recovery.
- `async mark_unknown(context:unknown,dispatch_id:unknown,options:unknown):Promise<void>`: Journal the exact dispatch lifecycle; a lost acknowledgment remains unresolved until managed recovery.
- `async settle_dispatch(context:unknown,dispatch_id:unknown,completion_sha256:unknown,options:unknown):Promise<void>`: Journal the exact dispatch lifecycle; a lost acknowledgment remains unresolved until managed recovery.
- `async prepare(input:unknown,rawReadback:unknown,rawOptions:unknown):Promise<IntentView>`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async publish(input:unknown,rawOptions:unknown):Promise<IntentView>`: Publish the admitted staged generation after required checks and original-fence comparison.
- `async apply_security(input:unknown,inputScope:unknown,rawOptions:unknown):Promise<IntentView>`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async bind_purge(input:unknown,inputScope:unknown,rawOptions:unknown):Promise<IntentView>`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async close():Promise<void>`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `PostgresQdrantRecovery`

Restricted supervisor SQL authority for genuine credential refencing, retired dispatch settlement and managed reopening.

[Source](../packages/typescript/src/qdrant-recovery.ts#L265).

- `constructor(resource:PoolResource,config:unknown,supervisor:ManagedQdrantSupervisor,verifier:QdrantReconciliationVerifier)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async initialize(rawOptions:unknown):Promise<void>`: Validate/admit the selected native profile before operations; it does not apply SQL migrations.
- `async recover(rawRecovery:unknown,rawOptions:unknown):Promise<unknown>`: Perform the selected native managed recovery step; ordinary readback alone cannot refence an uncertain writer.
- `async advance_owner(proof:unknown,rawContext:unknown,rawOptions:unknown):Promise<Readonly<{owner_token:string;backend_epoch:number}>>`: Advance the admitted durable owner using the genuine current recovery proof.
- `async dispatch_stage_recovery(proof:unknown,rawContext:unknown,authorize:unknown,rawOptions:unknown,inputBudget?:VerificationBudget):Promise<Readonly<{batches:number;points:number}>>`: Dispatch only original missing-point recovery batches under genuine recovery authorization.
- `async settle_retired(proof:unknown,receipt:unknown,rawOptions:unknown):Promise<Readonly<{settled_count:number}>>`: Settle retired uncertainty using issuer-bound recovery and verification evidence.
- `async reopen(proof:unknown,rawOptions:unknown):Promise<Readonly<{state:'open';epoch:number}>>`: Reopen ordinary work only after genuine recovery, complete verification and retired settlement.
- `close():Promise<void>`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `ManagedQdrantSupervisor`

Explicitly own one supported native Qdrant process, registered profile and credential-fencing lifecycle; imports start no process.

[Source](../packages/typescript/src/qdrant-supervisor.ts#L96).

- `constructor(binary:unknown,work_dir:unknown,instance_id:unknown,config:unknown)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `register_profile(input:unknown):void`: Register the exact physical collection/profile before managed supervisor initialization.
- `identity():Identity`: Read the controller's native instance identity.
- `control_binding():Readonly<Record<string,unknown>>`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `profile_binding(input:unknown):Readonly<Record<string,unknown>>`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `async control_session<T>(body:(control:SupervisorControlSession)=>Promise<T>):Promise<T>`: Hold the genuine supervisor control exclusion for a bounded native recovery/finalization flow.
- `block_ordinary(_control?:object):void`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async initialize(rawOptions:unknown):Promise<void>`: Validate/admit the selected native profile before operations; it does not apply SQL migrations.
- `issue_attempt(input:unknown,rawOptions:unknown):Attempt`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `attempt_binding(input:unknown):Readonly<Record<string,unknown>>`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `transport_for(input:unknown):SupervisorTransport`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async deliver_worker_credential(input:unknown,sink:unknown,rawOptions:unknown):Promise<void>`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `recovery_binding(input:unknown):Readonly<Record<string,unknown>>`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `barrier_binding(input:unknown):Readonly<Record<string,unknown>>`: Read/validate native managed binding or durable state; this value grants no independent write permission.
- `async seal_recovery(proof:unknown,rawOptions:unknown,_control?:object):Promise<RecoveryBarrier>`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `finish_recovery(barrier:unknown,settlement:unknown,rawOptions:unknown,_control?:object):void`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `issue_recovery_attempt(proof:unknown,input:unknown,rawOptions:unknown,_control?:object):Attempt`: Native managed-graph operation requiring original controller/authority capabilities; use the manager for ordinary application work.
- `async recover(input:unknown,rawOptions:unknown,_control?:object):Promise<PhysicalRecovery>`: Perform the selected native managed recovery step; ordinary readback alone cannot refence an uncertain writer.
- `async close():Promise<void>`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `QdrantReconciliationVerifier`

Verify the complete scoped replica against a genuine original projection and supervisor; a fabricated receipt is rejected.

[Source](../packages/typescript/src/qdrant-reconciliation.ts#L325).

- `constructor(writer: PostgresQdrantWriter, supervisor: ManagedQdrantSupervisor)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async verify(proof: unknown, input: unknown, rawOptions: unknown, budget?:VerificationBudget): Promise<ReconciliationReceipt>`: Verify all required original scoped content and issue the native receipt; fabricated/copied proofs are rejected.
- `async close(): Promise<void>`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `ManagedQdrantPublicationWorkerHost`

Publish an already staged intent in one owned native child while the parent retains the actual supervisor.

[Source](../packages/typescript/src/qdrant-publication-worker.ts#L189).

- `constructor(supervisor:ManagedQdrantSupervisor,authorize_write:(scope:TrustedScope,collection:string,document_id:string)=>Promise<boolean>)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async publish(rawJob:unknown,ledger:ExecutionLedger,rawOptions:LeaseOptions&{observer?:Observer}):Promise<Readonly<Data>>`: Publish the admitted staged generation after required checks and original-fence comparison.
- `async close():Promise<void>`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `OwnedPublicationWorker`

Observer-issued handle for that exact child. Do not construct it or pass arbitrary PIDs/signals.

[Source](../packages/typescript/src/qdrant-publication-worker.ts#L173).

- `constructor(token:unknown,state:WorkerState)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async pause(options:LeaseOptions):Promise<void>`: Pause only the actual observer-issued owned worker under the deadline.
- `async resume(options:LeaseOptions):Promise<void>`: Resume only the actual observer-issued owned worker under the deadline.
- `async terminate(options:LeaseOptions):Promise<void>`: Terminate and reap only the actual observer-issued owned worker.
- `toJSON():never`: Serialize the documented safe view, or reject serialization for opaque capability holders.


### `cragkit-langchain`

Import from `cragkit-langchain`. [Entry source](../packages/langchain-typescript/src/index.ts).

- `ToolEngine`: Compile-time contract shape for this entry point. [Declaration](../packages/langchain-typescript/src/index.ts#L15).
- `type FinalSerializer=(actual:string|ToolMessage)=>string`: Synchronous serialization of the actual outer string/ToolMessage for token and byte checks.
- `CreateToolOptions`: Compile-time contract shape for this entry point. [Declaration](../packages/langchain-typescript/src/index.ts#L17).
#### `create_tool`

Create the narrow scope/template-bound LangChain retrieval tool with actual-wrapper serialization checks.

[Source](../packages/langchain-typescript/src/index.ts#L174).

```text
function create_tool(options:CreateToolOptions):DynamicStructuredTool<typeof NarrowToolSchema,ToolRequest,unknown,string>
```


### `cragkit-mcp`

Import from `cragkit-mcp`. [Entry source](../packages/mcp-typescript/src/index.ts).

- `RetrievalEngine`: Compile-time contract shape for this entry point. [Declaration](../packages/mcp-typescript/src/index.ts#L13).
- `CreateServerOptions`: Compile-time contract shape for this entry point. [Declaration](../packages/mcp-typescript/src/index.ts#L15).
#### `BoundedStdioTransport`

Bound MCP input frames before official SDK parsing; attach/detach streams explicitly.

[Source](../packages/mcp-typescript/src/index.ts#L42).

Declared properties: `onclose`, `onerror`, `onmessage`.

- `constructor(readonly input:Readable=process.stdin,readonly output:Writable=process.stdout)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async start():Promise<void>`: Attach bounded MCP framing to the supplied streams.
- `async send(message:JSONRPCMessage):Promise<void>`: Serialize and send one official MCP SDK message.
- `async close():Promise<void>`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `RetrievalHost`

Scope-bound retrieval-only MCP host. Use create_server to validate configuration before serving.

[Source](../packages/mcp-typescript/src/index.ts#L94).

Declared properties: `server`.

- `constructor(engine:RetrievalEngine,template:RetrievalRequest,scope:TrustedScope, serializer:(actual:CallToolResult)=>string,counter:Cl100kCounter|null)`: Construct configuration and bind dependencies; perform explicit initialization separately where required.
- `async retrieve(input:unknown,external?:AbortSignal):Promise<CallToolResult>`: Retrieve scoped evidence under the request deadline and limits; inspect coverage and execution separately.
- `async run_stdio({input=process.stdin,output=process.stdout}:{input?:Readable;output?:Writable}={}):Promise<void>`: Explicitly serve the retrieval-only MCP host over stdio.
- `async close():Promise<void>`: Reject new work and complete this object's owned cleanup; borrowed resources retain their application owner.

#### `create_server`

Create and validate the retrieval-only MCP host; serving is a separate explicit call.

[Source](../packages/mcp-typescript/src/index.ts#L199).

```text
function create_server(value:CreateServerOptions):RetrievalHost
```


## MCP packages

For example, a desktop MCP client can start your application's stdio entry
script, discover `cragkit_retrieve`, and send a question about `handbook`.
The application binds that host to an authenticated scope and a fixed collection
before the client supplies tool arguments.

Install the matching optional package in your application environment:

```sh
python -m pip install 'cragkit-mcp==1.0.0rc3'
```

```sh
npm install 'cragkit-mcp@1.0.0-rc.2' 'cragkit@1.0.0-rc.2'
```

Use the runtime and backend setup in the [README](../README.md#quick-start).
The optional package installs its pinned official MCP SDK. Installing it does
not configure an engine or create a ready-to-run standalone CLI.

Supply these dependencies from trusted application code:

| Dependency | Application responsibility |
| --- | --- |
| `engine` | An initialized native asynchronous retrieval engine and its borrowed pools/providers. The host accepts a direct validated result or a corrective envelope containing `result`. |
| `scope` | A validated scope derived from authenticated identity/current authorization, never from model/tool arguments. The host snapshots this scope. |
| `template` | The fixed collection plus required filters, request limits and output profile. The snippets select v2 for a corrective engine and estimated counting. |
| `final_serializer` | A synchronous function receiving the actual SDK tool-result object and returning the complete representation exposed to the model, including your wrapper and escaping. |
| `counter` | An authentic local `Cl100kCounter` when strict counting is selected. The estimated examples below omit it. |

These integration functions make those application dependencies explicit.
They do not provision a database, choose a provider or resolve identity.
Use a host per trusted scope/session; a model cannot switch its tenant by adding
fields to `ToolRequest`.

Python:

```python
from typing import Any, Callable

from mcp import types
from cragkit.contracts import TrustedScope
from cragkit_mcp import create_server


async def serve_mcp(
    engine: Any,
    scope: TrustedScope,
    final_serializer: Callable[[types.CallToolResult], str],
):
    host = create_server(
        engine,
        template={
            "collection": "handbook",
            "required_filters": [],
            "limits": {"max_context_tokens": 2000},
            "output_profile": {"renderer": "cragkit.context.v2"},
        },
        scope=scope,
        final_serializer=final_serializer,
    )
    try:
        await host.run_stdio()
    finally:
        await host.close()
```

TypeScript:

```typescript
import { type TrustedScope } from 'cragkit/contracts';
import { create_server, type CreateServerOptions } from 'cragkit-mcp';

async function serveMcp(
  engine: CreateServerOptions['engine'],
  scope: TrustedScope,
  finalSerializer: CreateServerOptions['final_serializer'],
) {
  const host = create_server({
    engine,
    template: {
      collection: 'handbook',
      required_filters: [],
      limits: { max_context_tokens: 2000 },
      output_profile: { renderer: 'cragkit.context.v2' },
    },
    scope,
    final_serializer: finalSerializer,
  });
  try {
    await host.run_stdio();
  } finally {
    await host.close();
  }
}
```

Your entry script constructs the selected engine, resolves its trusted scope,
defines the serializer for the actual downstream model wrapper, and invokes
this function. Configure the MCP client to launch that script in the intended
application environment. Do not write application logs to protocol stdout.
A generic SDK JSON dump only suffices when it is the complete representation
your application actually exposes; the host cannot infer additional model
wrappers. A strict ceiling also needs the declared tokenizer and enough
`envelope_reserve_tokens`; estimated counting provides no hard token guarantee.

`run_stdio()` serves until disconnect/close. Python additionally supports
`run_streams`; Node exports `BoundedStdioTransport` for the official SDK's
transport boundary. Host close cancels/drains its owned work and closes the
owned MCP server. The engine, its pools/provider clients and tokenizer remain
application-owned and must be closed separately after the host finishes.
A host admits one retrieval at a time. It exposes retrieval only, with no
sampling, prompt/resource server, HTTP listener or ingestion/repair/purge tool.

The client can call the advertised tool with this narrow argument object:

```json
{"query":"What is the retry delay?","collection":"handbook"}
```

The result is one SDK text content item containing compact validated result
JSON, preserving coverage, execution, limitations and source references.
Corrective diagnostics are not model content. Stable public errors become safe
error codes; malformed protocol input is not echoed in an error message.

For a failure case, `tenant_id` or `required_filters` in direct host/tool input
fails narrow request validation before the engine runs. A different collection
is also rejected. Do not accept a model's permissions to repair this error.
The host owns those fields. Protocol parsing has its own SDK normalization
boundary; see the [MCP contract](../contracts/MCP_V5.md) before making a
byte-level rejection claim about a raw frame.

As a small exercise, parse a `ToolRequest` with an extra `tenant_id` field and
confirm that it fails before any backend call. This checks the boundary without
a provider, database or model download.

For contributing or extending one of these interfaces, use
[CONTRIBUTING](../CONTRIBUTING.md) and update the relevant shared contract.
