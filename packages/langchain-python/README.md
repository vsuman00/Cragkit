# Cragkit LangChain adapter for Python

Expose a Cragkit retrieval engine as an asynchronous LangChain tool while keeping
access scope, required filters and budgets under application control. The tool
returns validated retrieval results with source references, coverage estimates,
limitations and usage. It does not generate the final answer.

This release updates package descriptions and version metadata. Runtime behavior
is unchanged from RC1. See the [RC2 release notes](https://github.com/vsuman00/Cragkit/blob/main/docs/releases/RC2.md).

## Install

Requires Python `>=3.14,<3.15`. This release candidate installs matching Cragkit
core and the pinned LangChain Core dependency.

```sh
python -m pip install "cragkit-langchain==1.0.0rc2"
```

The package provides `cragkit_langchain.create_tool`. Installing it does not
provision a store, configure a model or supply provider credentials.

## Run a tool without a model

This complete example uses a synthetic engine that always reports no evidence.
It demonstrates the wrapper contract, not retrieval quality or a real backend.

```python
import asyncio
import json

from cragkit.contracts import parse_scope
from cragkit_langchain import create_tool


class ExampleEngine:
    async def retrieve(self, request, *, scope, deadline):
        return {"result": {
            "request_id": request.request_id,
            "status": "insufficient",
            "execution": "complete",
            "evidence": [],
            "facets": [],
            "context": "",
            "limitations": [{"code": "coverage_unknown"}],
        }}


async def main():
    scope = parse_scope({
        "tenant_id": "example-tenant",
        "principal_id": "example-user",
        "authorization_revision": "r1",
        "grant_ids": ["engineering-read"],
    })
    tool = create_tool(
        ExampleEngine(),
        template={
            "collection": "engineering",
            "limits": {"max_provider_calls": 0},
        },
        scope=scope,
        # This example exposes plain strings directly, without a model wrapper.
        final_serializer=lambda actual: actual,
    )
    content = await tool.ainvoke({
        "query": "What is the retry policy?",
        "collection": "engineering",
    })
    print(json.loads(content)["status"])  # insufficient


asyncio.run(main())
```

Replace `ExampleEngine()` with your configured native corrective retrieval
engine, which returns its standard result under `result`. Resolve scope from
trusted application identity. The example's tenant and grants are synthetic.

## Bind policy before the model calls

`create_tool(engine, *, template, scope, final_serializer, counter=None,
name="cragkit_retrieve")` binds the engine, collection, required filters, limits
and output profile. Model-facing input contains only the narrow tool request:
query, collection, request ID, schema version and search hints.

The input collection must match the bound collection. For example, supplying
`scope` or `limits` inside `tool.ainvoke(...)` raises `InvalidRequest` before
retrieval. A model cannot change identity or increase its budget through those
arguments. An application that accepts forged trusted scope defeats this boundary.

Supported Python calls are asynchronous `ainvoke` and `arun`. Plain arguments
return a JSON string; a supported native tool-call envelope returns an SDK
`ToolMessage`. Synchronous, batch and streaming routes are unsupported. The
adapter validates results and preserves typed operational errors.

## Count the actual output

`final_serializer` is required. It must return the representation your application
will expose to its model, including the wrapper, tool name, call ID and escaping
when applicable. The identity serializer above applies only to its plain-string
example. Use an appropriate serializer for SDK tool-call envelopes.

Estimated mode uses a UTF-8 byte estimate and provides no hard token ceiling.
Strict counting needs the supported issued `Cl100kCounter`, its explicitly loaded
local tokenizer asset and the actual serialized representation. A result that
fits before wrapping may still raise `ContextBudgetTooSmall` afterward.

## Configuration and limits

Bring your own store, model clients and provider credentials. Configure secrets
in the consuming application and inject transports; Cragkit does not load project
`.env` files or supply an API key. Install core extras separately for PostgreSQL,
Qdrant or tokenizer support when needed. Tool construction does not start a model
or database service.

Owned tool calls disable scoped tracing and bypass framework callback dispatch.
An outer agent may still record content before calling this tool; the application
owns that disclosure choice. Deadlines and Python task cancellation propagate to
retrieval. The adapter does not own your injected engine or backend resources.

Coverage and execution remain separate: `insufficient` can accompany `complete`,
as the example shows. Source fidelity is not proof of truth. This release does not establish
general model quality, production readiness or all-platform compatibility.

## Documentation and license

- [LangChain behavior and serialization](https://github.com/vsuman00/Cragkit/blob/main/docs/integrations/langchain.md)
- [Core API reference](https://github.com/vsuman00/Cragkit/blob/main/docs/api-reference.md)
- [Application setup](https://github.com/vsuman00/Cragkit/blob/main/README.md)
- [RC1 limitations](https://github.com/vsuman00/Cragkit/blob/main/docs/releases/V6.md)

GitHub guides require access while the repository remains private. This package
is [MIT licensed](https://github.com/vsuman00/Cragkit/blob/main/LICENSE).
Dependencies and provider services retain their own licenses, terms and costs.
