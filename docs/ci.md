# Source and package validation

For example, a checkout can typecheck while its source distribution omits a required file. Build and fresh installed-import checks cover that separate boundary.

The current public entry point is:

```sh
python3 tools/check_public_packages.py --output-dir artifacts/public-check
```

Use a fresh ignored directory. The checker validates all six package sources and archives serially without private corpus, tests, examples or evaluation data. See [development](development.md) for prerequisites and the separate private maintainer regression runner. The default uses offline caches; hosted CI selects `--allow-downloads` for dependency registries. The checks do not start a database, model or persistent service and do not publish.

The [manual candidate workflow](../.github/workflows/candidate-validation.yml) uses the public package checker. A workflow definition or a local pass is not a hosted CI result. Do not dispatch paid hosted CI without authorized scope and a bounded budget; a private repository's free allowance is not assumed. Branch protection, repository visibility and publication remain separate controls.

Historical RC1 hosted acceptance remains scoped to its exact source, archives and macOS ARM64 toolchain recorded in [release notes](releases/V6.md). Its detailed receipts and previous workbench pipeline are retained privately. New checkout bytes require fresh checks and cannot inherit an old candidate receipt.
