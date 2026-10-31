# Installed-package manual RAG pilot

For example, `ask atlas rollback` retrieves synthetic runbook excerpts with source references. `prompt atlas rollback` prepares evidence for you to paste into an LLM of your choice. The app makes no generation or embedding calls.

This is V5-PILOT-01, a local installed-artifact beta trial. V5 is a milestone label: the wheel's actual version is `0.0.0` and it is unpublished. This exercise is not V6-05 usability acceptance, a held-out quality evaluation or a release claim. See the [operations guide](../../docs/v5-operations.md) and [tracker](../../tasks/todo.md).

## Start a disposable session

Run these commands from the repository root. They require `uv`, Python 3.14, the existing local wheel below and the existing PostgreSQL 17.11 binaries at `/opt/homebrew/opt/postgresql@17/bin`. The launcher requires that exact PostgreSQL version; it does not download a server or a model. If the wheel is absent, follow the operations guide and inspect the local build evidence before installing it.

```sh
uv venv --python 3.14 examples/v5_rag/.venv
uv pip install --python examples/v5_rag/.venv/bin/python 'artifacts/V5/V5-08/full-core-frameworks/core/python/cragkit-0.0.0-py3-none-any.whl[postgres]'
uv run --project packages/python --frozen --no-sync python examples/v5_rag/session.py
```

The launcher uses the repository development environment only to provision the explicit disposable TLS database. Its child application runs in `examples/v5_rag/.venv` and imports the installed wheel, without importing the product from the checkout. Inspect the startup import origin. The application seeds [corpus.json](corpus.json) automatically into collection `manual-pilot` and starts as `alice`.

Append `--smoke` to the launcher command for automated mechanics verification:

```sh
uv run --project packages/python --frozen --no-sync python examples/v5_rag/session.py --smoke
```

A smoke run does not complete the [manual checklist](CHECKLIST.md) or measure model quality. The session owns a disposable database and destroys it on exit. Interactive sessions end after at most one hour; smoke runs have a three-minute cap. Edits saved to `corpus.json` persist as files; database-only changes do not survive a new session. Do not point fixture provisioning at an existing database.

The launcher explicitly applies the existing checksummed migrations to its new local database before starting the app. It creates separate restricted reader and writer logins, each with a maximum of one connection; the setup administrator closes before the app starts. The app neither connects as an administrator nor runs migrations. No persistent database service is started.

## Try your own documents

First complete the synthetic baseline. Then copy `corpus.json` to a private location outside the repository, replace entries with your own Markdown or plain-text content in the `text` field, and pass its absolute path:

```sh
uv run --project packages/python --frozen --no-sync python examples/v5_rag/session.py --corpus /absolute/private/pilot-corpus.json
```

The file is a JSON list of objects with exactly `id`, `title`, `tenant` and `text` string fields. Use unique lowercase slug IDs, `team` or `other` as tenant, and nonempty text. The limits are 20 documents, 16 KiB of UTF-8 text per document and 256 KiB for the JSON file. Markdown is ingested as plain text in this pilot; PDF/OCR is unsupported. Start a fresh session after adding IDs or changing tenants. Within a session, save a text/title edit and use `reload DOCUMENT_ID` as its owner. Keep private content and manual results outside Git. `--smoke` uses only the bundled synthetic corpus.

These selectable identities are a local test harness, not an authentication system. Anyone running the pilot can select `outside`; keep the CLI private. The consuming application must resolve identities itself in a deployed system. Retrieval uses no external inference provider. Copying a prompt into another service is a separate disclosure you control.

## Use the application

| Command | Behavior |
| --- | --- |
| `docs` | List documents visible to the selected reader. |
| `ask QUERY` | Retrieve source-linked excerpts and show status, execution, coverage and diagnostics. |
| `prompt QUERY` | Print evidence and instructions to paste manually into your chosen LLM. |
| `user alice` | Select the team owner, who has grants to the nine team documents. |
| `user bob` | Select a reader in the same team tenant with no document grants. |
| `user outside` | Select the other tenant's reader, who can read its canary document. |
| `reload DOCUMENT_ID` | Read the saved corpus entry and ingest it using compare-and-swap revision checks. Changed text creates a new immutable revision; unchanged text replays the existing receipt. |
| `delete DOCUMENT_ID` | Tombstone the selected document. |
| `budget N` | Set the context budget for subsequent retrieval. |
| `help` | Show available commands. |
| `quit` | Exit and clean up the disposable session. |

Scope is selected by application code. Query text cannot change the tenant or grant access. Alice and Bob share a tenant but have different document grants; tenant membership alone does not authorize reading. The other tenant's document repeats `Atlas rollback` to make a cross-tenant check meaningful.

Try these short lexical queries first:

```text
docs
ask atlas rollback
ask cache ttl
ask compute_retry_delay
ask café
prompt incident
user bob
ask atlas rollback
user outside
ask tenantcanary
user alice
```

The backend uses PostgreSQL native full-text search, not embeddings or BM25. Query terms can be combined restrictively: a long natural-language question may miss a passage that a short keyword query finds. For example, `ask reversion` may miss the rollback runbook. Useful hits have unknown coverage and can remain `partial`; the app has no assessor that could establish sufficiency. A no-match `insufficient` result differs from an operational exception or degraded execution.

The budget is an estimate for Cragkit's serialized evidence context. It is not a hard token ceiling for the copied prompt, its extra instructions or an external model's response. Account for those separately when using an LLM.

## Inspect evidence before using a prompt

Compare excerpts with their document ID, immutable revision, digest and UTF-8 byte spans. The Unicode fixture deliberately includes both composed and decomposed accents; do not normalize a quote when checking source fidelity. A correct citation establishes where the bytes came from. It does not prove that a claim is current or true: the cache notes explicitly record conflicting dated values.

`prompt` helps you assemble a manual RAG request. Read its evidence, then paste the printed prompt into your chosen LLM only if you intend to disclose it there. All bundled text is synthetic, including the source injection fixture. Treat that fixture as untrusted source data. This app cannot establish that a separate LLM follows instructions or resists injection, and it never fabricates a successful model evaluation.

To inspect revision behavior, save a small text change to `atlas-rollback` in `corpus.json`, run `reload atlas-rollback`, and query again. Record the new revision and exact updated quote. Repeat `reload atlas-rollback` without changing the file to inspect replay. Then run `delete atlas-rollback` and verify the tombstoned document is absent from retrieval. Other documents may still match `atlas rollback`; compare document IDs rather than assuming the whole query must become empty. Restore your corpus edit when you finish if you want the original fixture next time.

For a failure case, set `budget 1` and query `atlas rollback`. A context-budget failure must be visible rather than reported as missing documentation. Set a larger budget before continuing. As a small exercise, compare `rollback` and `reversion`, then explain which limitation belongs to lexical retrieval and which belongs to coverage assessment.
