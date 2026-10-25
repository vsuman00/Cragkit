# Optional LangChain Core adapters

For example, a tool can accept a question about a collection while the application binds the tenant, principal, filters and limits. A model cannot add another tenant or increase its budget through the tool's arguments.

These integrations use native Python and Node execution. They live in separate packages; installing core Cragkit does not install LangChain Core, LangSmith, a model or an HTTP server. Python selects LangChain Core 1.7.0; TypeScript selects 1.3.0. See [the adapter contract](../../contracts/EXECUTION_V4.md) and [the V4 plan](../../tasks/versions/V4-corrective-alpha.md).

## Bind the application policy

`create_tool` receives a trusted engine, a template containing collection/required filters/limits/output profile, a trusted scope and a required final serializer. The engine implements the native corrective `retrieve` interface. A successful response contains its standard result under `result`. The tool validates and serializes that result, including statuses, execution, citations, limitations and usage. Internal corrective diagnostics are not model content.

Tool arguments use the existing narrow ToolRequest fields: query, collection, request ID, schema version and search hints. The collection must match the bound template. Scope, filters, limits, counter, engine and serializer never appear in the tool schema. Unknown fields fail before retrieval.

Supported calls are asynchronous: Python `ainvoke` / `arun`, Node `invoke` / `call`. Plain argument objects return a JSON content string. Exact native ToolCall envelopes produce an actual SDK ToolMessage with the validated call ID and fixed name. Synchronous Python calls, raw SDK callbacks, batch and streaming routes are unsupported. The adapter owns this narrow invocation path so framework callbacks cannot receive input before validation or output before the final budget check.

## Count the final message

The application supplies `final_serializer(actual)`: it receives the exact string or SDK ToolMessage and returns the representation the application will expose to its model. It must include the actual wrapper, name, tool-call ID and escaping. Generic SDK dumps do not define every model provider's wire format.

Strict mode requires Cragkit's issued Cl100kCounter loaded explicitly from the pinned local tokenizer asset and `cl100k_base`. After constructing the SDK message, the tool counts the serializer's output, adds the bound envelope reserve and rejects overflow before returning. Estimated mode uses the explicit UTF-8 byte estimate and provides no hard token ceiling. Output is also bounded to 262144 UTF-8 bytes. External prompt/history tokens are outside this tool budget.

A failure example: a context fits, but the final ToolCall wrapper pushes it over the ceiling. The adapter raises ContextBudgetTooSmall and releases no oversized message. Increasing the reserve or reducing the engine's packing budget can leave room for that wrapper; weakening scope checks cannot.

## Tracing and cancellation

Owned calls disable scoped tracing and bypass framework callback dispatch. Nonempty invocation configuration is rejected, except Node's native signal. The adapters do not mutate global tracing/debug settings. An application's outer agent or runnable can record input before calling any tool; the application owns that separate disclosure boundary.

Each call has a fresh deadline and request-local state. Python task cancellation and Node AbortSignal propagate to retrieval. Uncooperative callbacks are bounded by the outer deadline and late failures are observed. Typed operational errors stay errors; unknown engine exceptions use a fixed redacted provider error. No tracing/exporter service is started.

The [corrective demonstration](../../examples/corrective.md) exercises the underlying engines without a model. Optional SDK tests and clean artifact results are recorded in the V4 exit report when acceptance completes. These checks validate integration behavior; they do not establish live model quality or production readiness.

## Small application example

The application supplies `engine`, `scope` and `serialize_model_tool`. The serializer must match its eventual model wrapper.

```python
from cragkit_langchain import create_tool

tool = create_tool(
    engine,
    template={
        "collection": "handbook",
        "limits": {"max_context_tokens": 2000},
        "output_profile": {"renderer": "cragkit.context.v2"},
    },
    scope=scope,
    final_serializer=serialize_model_tool,
)
content = await tool.ainvoke({"query": "What is the retry delay?", "collection": "handbook"})
```

```typescript
import { create_tool } from 'cragkit-langchain';

const tool = create_tool({
  engine,
  template: {
    collection: 'handbook',
    limits: { max_context_tokens: 2000 },
    output_profile: { renderer: 'cragkit.context.v2' },
  },
  scope,
  final_serializer: serialize_model_tool,
});
const content = await tool.invoke({ query: 'What is the retry delay?', collection: 'handbook' });
```

These snippets use the default estimated counting mode. For strict counting, bind that profile, its pinned tokenizer/counter and enough wrapper reserve. No hosted model call occurs merely from constructing the tool.
