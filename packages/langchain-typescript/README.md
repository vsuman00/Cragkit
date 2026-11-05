# Cragkit LangChain adapter for Node.js

Expose Cragkit retrieval as a native LangChain tool while keeping trusted access scope and retrieval policy in application code. The adapter returns a serialized Cragkit evidence result; your application owns the final answer.

## Install

Requires Node.js `>=26.5.0 <27` and ECMAScript modules. The package includes TypeScript declarations and installs its LangChain dependencies.

```sh
npm install cragkit@1.0.0-rc.1 cragkit-langchain@1.0.0-rc.1
```

Use an `.mjs` file or set `"type": "module"` in your application's `package.json`.

## Create and invoke a tool

This self-contained example injects a fake engine to demonstrate the adapter without a database or provider. Replace `engine` with your configured retriever for actual retrieval.

```js
import { create_tool } from 'cragkit-langchain';

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

const tool = create_tool({
  engine,
  template: {
    collection: 'engineering',
    required_filters: [{ op: 'eq', field: 'kind', value: 'runbook' }],
  },
  // Resolve identity in trusted application code, outside agent input.
  scope: {
    tenant_id: 'tenant-a',
    principal_id: 'user-1',
    authorization_revision: 'auth-1',
  },
  final_serializer: (actual) =>
    typeof actual === 'string' ? actual : JSON.stringify(actual),
});

const serialized = await tool.invoke({
  request_id: 'request-1',
  query: 'How are backups retained?',
  collection: 'engineering',
});

console.log(JSON.parse(serialized).status); // insufficient
```

The RC1 engine contract returns an envelope containing `result`. The result must validate and its `request_id` must match the request. The fake example reports unknown coverage and supplies no evidence; it does not establish retrieval quality.

## Boundaries and behavior

`create_tool` returns a LangChain `DynamicStructuredTool`. The supported invocation path is asynchronous `invoke`/`call`. The adapter rejects unsupported batch and streaming paths.

The agent-facing arguments contain the query, collection, optional request/schema identity and search hints. Trusted scope, required filters and execution limits come from the application-bound configuration. Adding `tenant_id` to tool input or changing the bound collection raises `InvalidRequest` before engine execution.

The adapter passes an abort signal and deadline to the engine, validates the returned result and checks the serialized output budget. `final_serializer` must be synchronous and represent the actual string or LangChain `ToolMessage` that your application will send. The example uses the default estimated counting mode; strict counting needs a supported `Cl100kCounter` and tokenizer configuration.

Your application owns outer tracing and final wire serialization. Importing the adapter does not start retrieval or contact a provider. Cragkit does not automatically load `.env` files or supply provider credentials. Construct backend/model clients explicitly and inject them into the engine.

## Evidence and limits

Cragkit separates coverage (`sufficient`, `partial`, `insufficient`) from execution (`complete`, `degraded`). Exact source-linked excerpts do not establish relevance or source truth. Your application configures backend permissions; the retrieval engine must reauthorize source release. Your application owns the final answer.

This is release candidate `1.0.0-rc.1`. A fake-engine invocation verifies adapter use only; it does not prove live-model quality, production readiness or backend deployment behavior.

## Documentation

- [LangChain integration guide](https://github.com/vsuman00/Cragkit/blob/main/docs/integrations/langchain.md)
- [API reference](https://github.com/vsuman00/Cragkit/blob/main/docs/api-reference.md)
- [Security guidance](https://github.com/vsuman00/Cragkit/blob/main/docs/production-security.md)
- [Release notes and limitations](https://github.com/vsuman00/Cragkit/blob/main/docs/releases/V6.md)

Repository documentation requires repository access while the source repository is private. The example above is self-contained.

## License

MIT. See `LICENSE` and `NOTICE` in the package.
