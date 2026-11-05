# Cragkit MCP host for Node.js

A retrieval-only MCP host for Cragkit. Expose source-linked evidence through an MCP tool while your application supplies the engine, trusted identity and retrieval policy.

## Install

Requires Node.js `>=26.5.0 <27` and ECMAScript modules. The package includes TypeScript declarations and its MCP SDK dependency.

```sh
npm install cragkit@1.0.0-rc.1 cragkit-mcp@1.0.0-rc.1
```

Use an `.mjs` file or set `"type": "module"` in your application's `package.json`.

## Construct a host

This self-contained example injects a fake engine and calls the host directly. It needs no database, model, credentials or running MCP client. Replace `engine` with your configured retriever for actual retrieval.

```js
import { create_server } from 'cragkit-mcp';

const engine = {
  async retrieve(request, { scope, deadline, signal }) {
    signal.throwIfAborted();
    // A real engine uses the trusted scope, deadline and required filters.
    return {
      result: {
        request_id: request.request_id,
        status: 'insufficient',
        limitations: [{ code: 'coverage_unknown' }],
      },
    };
  },
};

const host = create_server({
  engine,
  template: {
    collection: 'engineering',
    required_filters: [{ op: 'eq', field: 'kind', value: 'runbook' }],
  },
  // Resolve identity in trusted application code, outside tool arguments.
  scope: {
    tenant_id: 'tenant-a',
    principal_id: 'user-1',
    authorization_revision: 'auth-1',
  },
  final_serializer: JSON.stringify,
});

try {
  const response = await host.retrieve({
    request_id: 'request-1',
    query: 'How are backups retained?',
    collection: 'engineering',
  });
  console.log(JSON.parse(response.content[0].text).status); // insufficient
} finally {
  await host.close();
}
```

The RC1 engine contract returns an envelope containing `result`. The result must validate and its `request_id` must match the request. The fake example has no evidence and reports coverage as insufficient.

## Serve over stdio

For an MCP client, create the host as above, then use `await host.run_stdio()` instead of the direct `retrieve` call. The host exposes `cragkit_retrieve` over the official SDK's stdio transport. Keep standard output reserved for protocol messages; send application logs elsewhere.

`run_stdio` owns the serving loop and closes the host when it ends. Engines and their database/provider clients remain caller-owned. Configure identity for the application context before creating the host; agent-supplied tool arguments must never select the trusted scope.

## Boundaries and behavior

The host supplies a narrow retrieval tool, not arbitrary SQL, ingestion, deletion or final-answer generation. Query/tool input cannot replace bound scope, required filters or execution limits. Changing the collection or adding an identity field is rejected before engine execution.

The adapter bounds stdio frames, passes cancellation/deadline information to the engine and validates result/output budgets. `final_serializer` must synchronously serialize the actual MCP `CallToolResult` your application sends. The example uses estimated counting; a strict ceiling requires the declared tokenizer and actual wrapper representation.

Importing or constructing the host does not open a database, start stdio serving or call a provider. Cragkit does not automatically load `.env` files or supply a provider key. Load application secrets and inject configured clients explicitly.

## Evidence and limits

Coverage (`sufficient`, `partial`, `insufficient`) is separate from execution (`complete`, `degraded`). Source fidelity does not prove relevance or source truth. Your application configures backend permissions; the retrieval engine must reauthorize source release. Your application owns the final answer.

This is release candidate `1.0.0-rc.1`. The direct fake-engine example does not establish a deployed MCP client's behavior, live-model quality or production readiness.

## Documentation

- [MCP contract](https://github.com/vsuman00/Cragkit/blob/main/contracts/MCP_V5.md)
- [API reference](https://github.com/vsuman00/Cragkit/blob/main/docs/api-reference.md)
- [Security guidance](https://github.com/vsuman00/Cragkit/blob/main/docs/production-security.md)
- [Release notes and limitations](https://github.com/vsuman00/Cragkit/blob/main/docs/releases/V6.md)

Repository documentation requires repository access while the source repository is private. The example above is self-contained.

## License

MIT. See `LICENSE` and `NOTICE` in the package.
