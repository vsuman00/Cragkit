# Cragkit MCP host for Python

Expose application-owned Cragkit retrieval through a local stdio MCP host.
The host provides the `cragkit_retrieve` tool and returns validated evidence,
coverage estimates, limitations and diagnostics. Your application controls
identity, store access, model clients and the final answer.

This is an optional transport package. It is not a hosted retrieval service or a
general-purpose database administration server.

This release updates package descriptions and version metadata. Runtime behavior
is unchanged from RC1. See the [RC2 release notes](https://github.com/vsuman00/Cragkit/blob/main/docs/releases/RC2.md).

## Install

Requires Python `>=3.14,<3.15`. This release candidate installs matching Cragkit
core and the pinned MCP SDK dependency.

```sh
python -m pip install "cragkit-mcp==1.0.0rc2"
```

The package exports `create_server` and `RetrievalHost`. It does not supply a
configured engine or automatically start a background server.

## Try the host without starting stdio

This complete example constructs a host and calls its local retrieval method.
The synthetic engine always returns no evidence; no database, model or MCP
client is required. It is a wrapper demonstration, not backend verification.

```python
import asyncio
import json

from cragkit.contracts import parse_scope
from cragkit_mcp import create_server


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
    host = create_server(
        ExampleEngine(),
        template={
            "collection": "engineering",
            "limits": {"max_provider_calls": 0},
        },
        scope=scope,
        final_serializer=lambda actual: actual.model_dump_json(by_alias=True),
    )
    try:
        message = await host.retrieve({
            "query": "What is the retry policy?",
            "collection": "engineering",
        })
        result = json.loads(message.content[0].text)
        print(result["status"])  # insufficient
    finally:
        await host.close()


asyncio.run(main())
```

For an actual MCP process, replace the synthetic engine with your configured
native corrective retrieval engine and explicitly run `await host.run_stdio()`.
The host must have exclusive ownership of that process's protocol stdin/stdout.
Send application logs elsewhere and close the host during shutdown. Constructing
the host does not enter the stdio loop.

## Keep identity outside tool input

`create_server(engine, *, template, scope, final_serializer, counter=None)` binds
the collection, required filters, limits, output profile and trusted scope.
Resolve scope from authenticated application identity; the values in this
example are synthetic. A deployment needing different identities must bind
the correct scope at its trusted application boundary.

Tool arguments contain only query, collection, request ID, schema version and
search hints. A different collection or additional fields such as `scope` or
`limits` are rejected before retrieval. The host exposes retrieval, not ingestion
or administrative writes. Do not accept a client's invented trusted scope.

## Serialization and resource ownership

The required `final_serializer` receives the actual SDK `CallToolResult` and
returns the representation whose size the host must check. The example counts
the aliased JSON representation of that result. Account for any additional
client/model wrapper in your own serializer and budget.

Estimated counting is a UTF-8 byte estimate, not a hard model-token ceiling.
Strict mode requires the supported issued `Cl100kCounter`, an explicitly loaded
local tokenizer asset and the actual serialized output. Oversized output raises
`ContextBudgetTooSmall` before release. Deadline, cancellation and bounded output
checks do not prove source truth or answer quality.

`close()` shuts down host-owned activity; the application still owns its injected
engine, pools and clients. Reuse those resources and close them explicitly.
Do not print protocol-unrelated output to stdout while running stdio.

## Configuration and limitations

Bring your own backend and model clients. PostgreSQL, Qdrant and tokenizer extras
are installed separately through core Cragkit as needed. Configure provider keys
in the consuming application and inject clients; Cragkit supplies no API key and
does not load project `.env` files. Installation does not provision databases,
apply migrations or download model assets.

`sufficient`, `partial` and `insufficient` are coverage estimates. `complete` and
`degraded` describe execution separately. Missing evidence is not an operational
failure, and an operational failure must not be presented as missing evidence.
The example demonstrates complete execution with insufficient evidence.

Release-candidate checks cover declared configurations and bounded workloads. It does not establish
production readiness, universal compatibility or live model quality. A local
method call does not validate an end-to-end MCP client deployment.

## Documentation and license

- [MCP API and host methods](https://github.com/vsuman00/Cragkit/blob/main/docs/api-reference.md#mcp-packages)
- [Application setup](https://github.com/vsuman00/Cragkit/blob/main/README.md)
- [RC1 scope and limitations](https://github.com/vsuman00/Cragkit/blob/main/docs/releases/V6.md)

GitHub guides require access while the repository remains private. Project code
is [MIT licensed](https://github.com/vsuman00/Cragkit/blob/main/LICENSE);
dependencies and provider services have their own licenses, terms and costs.
