# Tooling entry points

For example, a renamed file may still be copied by an archive builder. Check its actual entry point and installed package contents, not only source imports.

Use role-based names for implementation tools. Preserve versioned contract identifiers, migration identities and historical receipts.

## Current public checks

`tools/check_public_packages.py` performs serial frozen type/build/archive/import checks for all six packages without private workbench inputs. [Development](development.md) describes its command and scope. It does not run a live provider or native database integration.

Public `tools/` also retains explicit storage/migration, schema export, tokenizer acquisition and private-configuration operator utilities. `tools/operator_support.py` supplies bounded operator prerequisites without importing the private evaluation harness. Operational SQL checks live under `storage/postgres/deployment/checks/`. Frozen RC1 release/evaluation automation remains private. Inspect each tool's `--help`, implementation and admission conditions before using it; the presence of a tool does not authorize a target mutation, account change or publication. Follow [storage](../storage/postgres/README.md), [migration and recovery](migrations-and-recovery.md), [operations](v5-operations.md) and [publication](publication.md) as applicable.

Personal benchmark drivers, corpus checks, resource experiments, test runners and historical helper names are retained in the separate private workbench. Maintainers use the private regression overlay described in [development](development.md#private-maintainer-verification) to check current public sources against that harness. Those inputs are neither shipped runtime dependencies nor public source-build requirements.

One failure case: running a historical corpus pipeline directly from the source-only checkout may reference a private file that is intentionally absent. Use the public checker for public build acceptance and the explicit private runner for maintainer regressions; do not copy private evidence back into a package to make that old command pass.
