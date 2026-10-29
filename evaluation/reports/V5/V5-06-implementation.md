# V5-06 optional MCP implementation checks

The Python and Node optional packages expose one retrieval tool through their
official MCP SDKs. The application binds the native engine, trusted scope,
required filters, limits and final model-facing serializer before a client can
send a query. The host returns native status, evidence, limitations and usage.
It does not generate an answer or expose write, repair or purge operations.

The packages pin Python `mcp==2.3.0` and Node
`@modelcontextprotocol/server==2.4.0`, with local stdio as their transport.
The core package manifests did not gain MCP dependencies. The installed SDKs
were inspected before implementation, including their cancellation and stdio
interfaces. Python's default SDK telemetry middleware is disabled in this host.

| Local check | Result |
| --- | --- |
| Python official SDK stream round trip and boundary tests | 36 passed |
| Node official SDK stdio transport round trip and boundary tests | 36 passed |
| Python strict mypy | Passed, one source file |
| Node package build/typecheck | Passed |

Tests exercise forged scope/filter/limit input, status and result identity,
scope snapshots, sanitized errors, output and wrapper ceilings, authentic strict
token counting, competing calls, cancellation, noncooperative engine drainage,
disconnect, malformed and oversized frames, and network denial. The local SDK
round trips use synthetic native results; they do not establish live provider
quality. Python uses SDK in-memory streams plus separate bounded-frame tests.
Node uses its SDK through an injected byte-stream transport. A separate installed
Python child-process stdio check remains to be run before final V5-06 acceptance.

The first Python close regression kept the caller waiting when an engine
suppressed cancellation. A dedicated close signal now wakes the caller while
the engine's work slot stays occupied until it actually drains. Another focused
failure showed that `asyncio.wait` had defaulted to waiting for both the engine
and close signal; the first-completed mode now returns when either completes.
Both corrections were checked with the affected case before the complete
optional package suite.

The official SDK interfaces are documented in the
[Python SDK](https://py.sdk.modelcontextprotocol.io/) and
[Node SDK](https://ts.sdk.modelcontextprotocol.io/v2/get-started/first-server).
This report covers local implementation checks. V5-06 final acceptance remains
dependent on V5-04, V5-05 and C2; no hosted CI, package publication or live
model/provider run is claimed.
