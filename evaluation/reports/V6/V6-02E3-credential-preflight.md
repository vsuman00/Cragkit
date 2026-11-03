# V6-02E3 credential preflight

Status: PASS for the scoped local audit and preventive fixes. Genuine-provider
authentication and held-out quality remain unverified until the live run.

The user selected the existing OpenAI benchmark credential and requested that
important credentials remain private. Both selected provider files are outside
Git, owned by the current account, regular single-link files with mode `0600`
inside `0700` directories. Only format and safe metadata were reported. This
benchmark setup does not add a built-in library key; consuming applications own
and inject their credentials.

## Corrections and evidence

The two Sol peers reviewed transport and package boundaries independently,
resolved their split directly and returned ownership to root. The artifact peer
assembled both reviews. Root inspected the changes and ran verification.

- The replay-only Node child now receives six explicit runtime environment
  variables. For example, an application token under an unfamiliar name is
  excluded instead of bypassing a provider-specific denylist.
- Invalid release CLI arguments produce a fixed JSON error. Synthetic regression
  cases verify that argument values cannot be echoed by argparse. Static help
  and valid execution flags still work.
- The shared archive validator now also rejects PostgreSQL password/service
  files and P12/PFX bundles. Existing archives contain none of these names.

Commands actually run, serially:

```sh
uv run --project packages/python --frozen --no-sync python -B -m pytest tools/tests/test_check_native_evaluation.py tools/tests/test_run_release_evaluation.py tools/tests/test_check_artifacts.py -q
uv run --project packages/python --frozen --no-sync python -B -m pytest packages/python/tests tools/tests -q
```

Results: **80 focused tests passed**; **3,635 Python/tool tests passed** with four
existing warnings from intentionally bypassed invalid Pydantic test models.
No provider calls, downloads or services were needed for these tests.

A private, value-free exact comparison covered both selected provider keys and
selected URL/base64 representations against 4,574 reachable Git objects
(117,555,475 bytes), 1,896 working files (53,573,478 bytes), and 367 members of
12 declared release archives (6,017,538 unpacked bytes). There were zero exact
matches, zero high-confidence provider/private-key pattern matches and zero
skipped files within that scope. Archive hashes and sizes match their recorded
acceptance reports. The URL-shaped archive fixture was classified by AST as a
negative endpoint test, without printing its literal. The sanitized counts are
in [the audit record](V6-02E3-credential-verification.json).

This is a bounded audit, not proof that every possible credential or encoding is
absent. Installed dependencies, unrelated files outside the project and retained
database binaries were excluded from working-file content inspection. Git
ignore rules and filename checks cannot prevent a forced addition or a secret
embedded in ordinary source. Exact comparisons used private memory only; no
credential, prefix, length or credential digest was written to this report.

## Runtime recheck and next gate

The previous execution identity was correctly refused: three Python standard
library bytecode caches changed. Their source files and runtime versions remain
unchanged; each current cache's code object equals a fresh compilation of that
source. The affected modules are `multiprocessing.resource_tracker`,
`multiprocessing.spawn` and `multiprocessing.synchronize`. No cache was deleted
and the prior receipt was preserved. The evaluation-tool corrections also
require a new source freeze and execution receipt before live dispatch.

TLS verification, fixed HTTPS endpoints, disabled environment proxies/redirects,
fixed errors, private journals and explicit caller-owned keys remain in place.
No paid request was made during this preflight. Root owns the source refreeze,
fresh runtime preparation, live dispatch and post-run credential checks.
Resources: 26 GiB free disk and 35 percent free system memory at the preflight
observation; one test process at a time, no task-owned persistent service.
Learning practice remains unassessed. Optional exercise: explain why ignoring
`.env` cannot prevent a token copied into a tracked Python file.
