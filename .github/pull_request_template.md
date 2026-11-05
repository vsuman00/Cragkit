<!-- Use a Conventional Commit style title, for example:
fix(retrieval): preserve required filters during recovery
Complete applicable sections; use "not applicable" with a reason rather than silently omitting a material check.
Never include credentials, connection strings, private queries or source documents, raw provider errors, or sensitive security payloads.
-->

## Problem

Describe the trigger, affected packages/versions and current behavior. Link the related issue when one exists. Use a closing keyword only if this PR resolves it.

## Resulting behavior and approach

Explain what changes and why. Include a short before/after example and the relevant public contract. Identify intentional limitations or remaining work.

## Reproduction and evidence

Provide a small synthetic reproduction, exact commands and expected output. For behavior changes, record the failure before the patch and success after it, plus a failure or denied-access case. Explain Python/TypeScript parity or why one runtime needs no change.

## Checks

| Command and working directory | Runtime/profile | Result |
| --- | --- | --- |
| <!-- Exact command actually run --> | <!-- Version and configuration --> | <!-- Pass/fail and relevant output --> |

List unrun checks and the reason. Distinguish local/fake-provider, installed-artifact, native-backend, live-provider and hosted CI evidence. Maintainer-only regression checks can remain pending; contributors do not need the private workbench. Do not infer a hosted pass from opening this PR.

## Compatibility, security and operations

Describe public API/schema, dependency/lock, backend/SQL, provider/tokenizer and data-disclosure impact where applicable. Include migration, reindexing or rollback limits for breaking changes. Explain effects on trusted scope, required filters, source fidelity, cancellation, budgets and redaction. State when none apply.

## Documentation and release impact

Link updated usage or contract documentation. State whether published users need a corrective version or migration; a merged PR does not publish a package. Do not change published RC1 identities as part of an unrelated fix.

## Review checklist

- [ ] The change has one focused purpose and fits the roadmap or an agreed proposal.
- [ ] I reviewed the diff and excluded unrelated work, generated output, credentials and private data.
- [ ] I reported checks actually run, their results and the limits of that evidence.
- [ ] I provided synthetic behavior and failure cases, or explained why this is documentation-only.
- [ ] I addressed both native runtimes or explained why only one needs changes.
- [ ] I described compatibility, dependency, migration and security effects, or explained why none apply.
- [ ] I updated affected documentation and contracts, or explained why no update is needed.
