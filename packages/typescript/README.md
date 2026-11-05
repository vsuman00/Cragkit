# Cragkit for Node.js

Native TypeScript retrieval with source-linked evidence, coverage estimates and execution diagnostics. Cragkit runs inside your Node.js application; it does not require a Python server.

Your application owns identity, data, provider clients and final answers. Cragkit supplies retrieval contracts and optional execution components for working with that application-owned configuration.

## Install

Requires Node.js `>=26.5.0 <27`. The package uses ECMAScript modules and includes TypeScript declarations.

```sh
npm install cragkit@1.0.0-rc.1
```

Use an `.mjs` file or set `"type": "module"` in your application's `package.json`.

## Validate a request

This example needs no database, model, provider key or network connection:

```js
import { version } from 'cragkit';
import { parse_request, parse_scope } from 'cragkit/contracts';

const request = parse_request({
  request_id: 'request-1',
  query: 'How are backups retained?',
  collection: 'engineering',
});

// Resolve these values in trusted application code, outside agent input.
const scope = parse_scope({
  tenant_id: 'tenant-a',
  principal_id: 'user-1',
  authorization_revision: 'auth-1',
});

console.log(version); // 1.0.0-rc.1
console.log(request.limits.deadline_ms); // 10000
console.log(request.output_profile.counting_mode); // estimated
console.log(scope.grant_ids); // []
```

Parsing validates structure and applies defaults. It does not retrieve evidence or authorize a user. A blank query, an unknown request field or a scope without `authorization_revision` raises `InvalidRequest` from `cragkit/errors`.

## Retrieval components

- `cragkit/contracts` provides strict request, trusted-scope and result parsing.
- `cragkit/postgres` provides explicit PostgreSQL resources, ingestion and retrieval.
- `cragkit/qdrant` and the Qdrant subpaths provide optional Qdrant integration.
- `cragkit/embeddings` and `cragkit/reranking` provide model-adapter boundaries.
- `cragkit/context`, `cragkit/packing` and `cragkit/assessment` provide context rendering, extractive packing and coverage assessment.
- `cragkit/execution` provides bounded retrieval execution.

The PostgreSQL backend uses pgvector and native full-text search. Native full-text search is not BM25. Backend setup, schema migrations and provider selection are explicit application operations. Install optional `pg` or `tiktoken` dependencies only for the components you use; consult the guides for their required versions and configuration.

Importing the package does not open a database, download a model or contact a provider. Cragkit does not load `.env` files or supply a shared API key. Load your own secrets and inject configured clients into the selected adapters.

## Evidence and limits

Results distinguish evidence coverage (`sufficient`, `partial`, `insufficient`) from execution (`complete`, `degraded`). Source excerpts retain UTF-8 byte spans and digests. An exact excerpt does not prove relevance or source truth.

Estimated token counting does not establish a hard tokenizer-based ceiling. Strict counting requires the declared tokenizer and actual serialized wrapper. Bind trusted access scope outside query/tool input and enforce it in every backend branch and when releasing sources.

This is release candidate `1.0.0-rc.1`. Installation and contract examples do not establish production readiness, live-model quality or backend deployment acceptance. The application remains responsible for its security configuration and final answer.

## Documentation

- [API reference](https://github.com/vsuman00/Cragkit/blob/main/docs/api-reference.md)
- [PostgreSQL setup](https://github.com/vsuman00/Cragkit/blob/main/docs/neon.md)
- [Qdrant integration](https://github.com/vsuman00/Cragkit/blob/main/docs/integrations/qdrant.md)
- [Security guidance](https://github.com/vsuman00/Cragkit/blob/main/docs/production-security.md)
- [Release notes and limitations](https://github.com/vsuman00/Cragkit/blob/main/docs/releases/V6.md)

Repository documentation requires repository access while the source repository is private. The example above is self-contained.

## License

MIT. See `LICENSE` and `NOTICE` in the package.
