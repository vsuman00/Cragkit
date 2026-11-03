# Optional retrieval-only MCP host

Revision: MT-r1, V5-06 implementation contract. Acceptance remains gated by
V5-04, V5-05 and C2.

For example, a client may supply a query and request ID. It cannot replace the
tenant, required filters, authorization revision or execution budget bound by
the application.

Use the official SDKs in separate optional packages: Python `mcp==2.3.0` and
Node `@modelcontextprotocol/server==2.4.0`. Core imports and installs remain free
of MCP dependencies. The supported transport is local stdio only. Use SDK
framing and protocol types; do not create an alternate MCP implementation.
The [Python SDK](https://py.sdk.modelcontextprotocol.io/) and
[Node SDK](https://ts.sdk.modelcontextprotocol.io/v2/get-started/first-server)
document the selected v2 API family; inspect installed pinned APIs before use.

Expose `create_server(engine, template, scope, final_serializer, counter=None)`
in Python and `create_server({engine,template,scope,final_serializer,counter?})`
in Node. The result owns one native SDK server and retrieval task lifecycle;
provide an explicit async stdio runner and close operation. No server starts on
import or factory construction. Engine clients and pools remain caller-owned.

Register only `cragkit_retrieve`. Snapshot and validate the trusted scope and
request template at construction with existing native contract parsers. The
input schema is exactly the public `ToolRequest`, with unknown fields forbidden.
Collection must equal the bound collection. Parse again inside the handler;
malformed input must fail before engine execution. Native required filters,
limits and output profile survive binding. Do not accept scope, credentials,
database connection, callback, provider, repair, purge or arbitrary SQL input.

The SDK parses protocol arguments before this handler. The pinned Node SDK/Zod
normalizes away a raw JSON `__proto__` key; this is not rejection of that wire
key. Consumer regression tests verify that normalization cannot introduce
foreign authority or prototype properties. Direct host input still rejects it.
Do not claim byte-level rejection of every raw field from handler validation.

Invoke the engine's actual native async `retrieve` with the rebound request,
trusted scope and monotonic deadline; Node also passes its owned abort signal.
Accept either the native `RetrievalResult` or the existing corrective engine's
wrapper containing `result`; validate and release only the result, never private
diagnostics. Its request ID must match. Preserve status, execution, limitations,
source-linked evidence and usage. No answer generation or sufficiency promotion.

Return one SDK text content item containing compact native result JSON, with
`isError=false`. Bound content and the actual final serialized tool response to
262144 UTF-8 bytes. The application-supplied trusted `final_serializer` receives
that exact SDK tool-result object and returns its complete model-facing
representation. Count that representation using the existing authentic
`Cl100kCounter` for strict mode, or explicit UTF-8 estimated counting. Include
the template's envelope reserve and reject overflow before release. A serializer
is required; the transport cannot infer an application's model wrapper.

Map expected Cragkit errors to their stable code only. Unexpected exceptions
become `provider_unavailable`; never return exception text, source/query input,
credentials, SQL or diagnostic stacks. Do not enable tracing/exporters or log
tool arguments/results. Native protocol errors must not echo rejected arguments.
Apply the same final-serializer byte/token checks to error tool results. If that
safe result cannot fit, or its serializer fails, raise a fixed SDK protocol error
instead of recursively returning an uncounted tool result. The transport strips
protocol error data and rejected input. A protocol failure is not a retrieval
result or a claim that a model-facing wrapper was successfully packed.
No sampling, prompts, resources, HTTP listeners or ambient credential discovery.

Bound concurrent retrieval to one active call per host. A competing call fails
before touching the engine. On deadline, client cancellation, disconnect or
close, cancel/abort owned work and suppress late responses. Retain ownership
until actual work drains; a noncooperative task keeps the host unavailable for
new work. Do not claim cancellation stopped an uncooperative external operation.
Close borrowed clients only when the application explicitly owns that action.

The stdio entry bounds each incoming frame to 65536 bytes before JSON decoding,
including incomplete lines, and rejects overlong or malformed UTF-8 frames
without copying their contents to logs/errors. Where the SDK lacks such a bound,
use its injectable byte/text stream or Transport interface with a minimal bounded
stream adapter, retaining the SDK's parser and serializer. No persistent watcher
or background service is installed.

Required focused and real SDK client cases: discovery and round trip; unchanged
status/result identity; malformed and unknown input; forged scope/filters/limits;
wrong collection; snapshot mutation; cancellation/deadline/disconnect; late
uncooperative completion; competing calls; close idempotence; malformed/oversized
frames; unexpected secret-bearing errors; output/wrapper overflow; actual strict
counter; no unsolicited network/tracing. Root runs one test process at a time.
