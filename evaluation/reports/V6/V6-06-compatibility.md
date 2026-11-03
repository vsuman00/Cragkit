# V6-06 recorded-output compatibility bridge

Status: COMPLETE for the fixed recorded-output compatibility bridge and local
native resource acceptance. Root ran the native command successfully on its
first attempt and reported 32 combined focused cases passed in 0.54 seconds.
This lane inspected the actual result, observation files and digests. Full V6,
publication and broad release readiness remain separate gates.

For example, a security fix can change installed package bytes while preserving
the output produced from an existing sealed provider response. Replaying that
response on the new package tests compatibility. It does not rerun the model.

## Fixed identities and boundaries

The historical quality evaluation remains bound to source
`25275e447c64ecfd243ef6bc26c87031d5e2e472`, package tree
`05fdc769488f496ef71ec6b988383fa8d1f18b1c` and original ECR-r1 identity
`59af39c6cb0a5d118c73511dbb67b5fd22b2289a731ffeaaa5fc488d4105b993`.
The retained recovery run has 39 recorded calls, 30 mode rows and five
publication receipts. Its [quality findings and limitations](V6-02-recovery.md)
remain unchanged.

The target is clean source
`0c7c568d5cb71638eebab2dea97c5973b0f8cc08`, package tree
`60a251c2bf94402cb562d0398403c218875454f3`. Exact core products come from the
hosted ZIP with SHA-256
`37b5fbcadc65be97556d885810a598e791b4321ba2ef9d3868877e2a67e4b17b`.
The [CI bundle audit](V6-06-ci-verification.json) supplies its CIB-r1 product
inventory. The bridge separately checks the ZIP digest and core member bytes;
editing a product and its inventory entry together cannot establish a new match.

The original candidate configuration, ECR-r1 preparation/verification and
`run_release_evaluation.py --mode replay` same-identity guard are unchanged.
EBC-r1 is a separate, fixed compatibility bridge. It grants no new live quality
acceptance and does not describe the newer source as the historical live runtime.

## EBC-r1 procedure

1. Start with the target wheel's Python using `-I -B`. Reject ambient Python/Node
   import overrides. Verify the target Git source and protected-path cleanliness
   before importing its tools. Add only the target tools directory to Python's
   import path.
2. Use the historical environment in a separate process to verify the full old
   ECR-r1 receipt and issue the sealed, label-free recovery packet. Require the
   fixed historical source and runtime identity.
3. Verify pinned hashes for the retained live binding, provider accounting,
   live observation and tape seal. Check their packet/identity binding and
   healthy 39-completion accounting. The existing private journal loader checks
   every pending/completion hash, response digest, provider shape and exact
   directory membership.
4. Bind the target to its clean source and CIB-r1 core products. Require exact
   installed `cragkit` file-set/byte equality with the wheel, installed module
   origins, and exact Node dist equality with the npm archive. Check installed
   Python/Node dependency versions against frozen locks and snapshot their actual
   bytes, executable bytes, runtime versions and pinned tokenizer.
5. Run native Python and Node serially against disposable PostgreSQL. Python
   uses `ReplaySend`; Node uses the existing native replay worker and its
   `assert_complete()` check. Both must consume all 39 ordered request keys with
   no provider sender, fallback or credential discovery. Validate 30 rows and
   five receipts per runtime; reject operational failures. Compare every
   normalized row and receipt with the retained live observation, removing only
   row latency and stage durations. Recheck target snapshots after execution.
6. With explicit `--include-resources`, run the existing RST-r1 Python and Node
   fake-provider workload serially under the same target identity. Retain all
   twelve existing checks per runtime, three ingestion measurements, forty
   retrieval measurements, cancellation/backpressure checks, frozen thresholds
   and pressure guards. Verify disposable listener shutdown. This produces a
   separate resource section, with no new quality claim.
7. Recheck the target and retained tape after execution. Write a fresh private
   result containing EBC-r1 identity, target inventory, retained pins, replay
   counts, parity and cleanup. A failure returns a fixed diagnostic and stage
   name, without exception text, and never writes a passing result.

## Verified execution and results

Root ran the focused bridge tests (11 passed in 0.55 seconds), then the combined
CI-bundle/bridge cases after the final environment-binding guard:

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_check_ci_bundle.py tools/tests/test_check_recorded_compatibility.py -q
```

The combined result was 32 passed in 0.54 seconds. Root observed this terminal
result; a separate combined test log was not retained.

The negative cases cover dirty source, a different old runtime, CI archive
tampering, coordinated product/manifest tampering, retained response tampering,
missing completions, wrong packet binding, changed request keys, incomplete or
extra replay consumption and semantic output changes. Tiny synthetic fixtures
exercise these boundaries without opening the original corpus or live tape.

Root ran the following native command from the project root, using its prepared
PostgreSQL 17.11/pgvector fixture and a fresh output path. It installed nothing
and had no provider-call opt-in:

```sh
env -u PYTHONPATH -u PYTHONHOME -u NODE_PATH -u NODE_OPTIONS \
  artifacts/V6/release-candidate-rc1/packages/python/.venv/bin/python -I -B tools/check_recorded_compatibility.py \
  --baseline-root artifacts/V6/recovery-candidate-rc1 \
  --baseline-runtime artifacts/V6/recovery-candidate-rc1/artifacts/V6/recovery-runtime/runtime.json \
  --baseline-live artifacts/V6/recovery-candidate-rc1/artifacts/V6/recovery-live-2026-11-03 \
  --target-root artifacts/V6/release-candidate-rc1 \
  --bundle-root artifacts/V6/hosted-candidate-0c7c568 \
  --bundle-metadata artifacts/V6/ci-bundle-audit.json \
  --bundle-archive artifacts/V6/hosted-candidate-0c7c568.zip \
  --prepared-postgres-bin artifacts/V6/V6-02A/private-pg/prefix/Cellar/postgresql@17/17.11/bin \
  --output artifacts/V6/release-recorded-compatibility \
  --allow-local-processes --include-resources
```

The retained stdout at
`artifacts/V6/release-recorded-compatibility-run.log` reports EBC-r1 passed.
The independently recomputed canonical result identity matches
`3efdb1bc1abeca2a5cac50a3b6bb3c6a7df55dbfcf8b14bac6563722b98600f8`.
The target snapshot contains 2,608 files and remained unchanged through both
native replays and both resource workloads. Its resource-binding digest is
`fe442d30048e03940027ce9899a542cf96ade01d46b0bbdb9dc85621080e44f7`.

Python and Node each consumed all 39 strict recorded request keys, produced
30 rows and five publication receipts, and matched the retained live output
after timing-only normalization. The result records zero HTTP calls and
verified cleanup. The existing historical ECR-r1 receipt was verified through
its own environment; no target ECR-r1 identity was invented.

The RST-r1 section separately passed all twelve existing checks in each native
runtime, with three ingestion measurements and forty retrieval requests per
runtime. Recorded p95 values are descriptive local fixture observations:

| Runtime | Concurrency-one p95, ms | Concurrency-two p95, ms | Worker peak RSS, bytes | Database logical size, bytes |
| --- | --- | --- | --- | --- |
| Python | 11.8423 | 22.3731 | 109805568 | 9090739 |
| Node | 13.5516 | 21.1104 | 172736512 | 9090739 |

Database logical size is separate from process RSS. The six pressure samples
each reported 36% free memory and the same cumulative 6,988,180 swapout pages,
so no new swapouts were observed during those samples. The Node harness made
19 recovery attempts with 18 refusals over 2082.865292 ms. These are the bounded
workload's recovery probes, not nineteen library retries for a retrieval.

Retained local file digests bind this observation to the executed helper and
exact outputs. The EBC-r1 identity above hashes canonical content; the result
file digest below hashes the serialized file bytes.

| File | SHA-256 |
| --- | --- |
| `tools/check_recorded_compatibility.py` | `680d020f2fa4be729b19a3bacdba1c13fa3ea466a563d74c0421f7e7de41269f` |
| `artifacts/V6/release-recorded-compatibility/results.json` | `4144836f3d7c67635acba15aee9d541c5d2ab6ab30a05409066a04f9a87e2486` |
| `artifacts/V6/release-recorded-compatibility/python.json` | `44ba37dcddbf1fae4d3aeb2ffe36bca9716f38383aa9e20fb01fcaa92eccb26c` |
| `artifacts/V6/release-recorded-compatibility/node.json` | `efdd5b06c071342a62c0d09aa7720d862e763c3ab09375e65b3bbe17dc4a591c` |
| `artifacts/V6/release-recorded-compatibility/resource-python.json` | `230bafee9e3a2146ddafe2f347494374d81bf11971cd09434d9ff6ab9b64da2e` |
| `artifacts/V6/release-recorded-compatibility/resource-node.json` | `e688c7cf77c06b37d7521c2ce9a0f8bfa6c8e7b6947d3b4abd75af4c19703aa8` |

These results establish compatibility with this fixed retained packet and local
fake-provider resource behavior on the declared runtime. They do not establish
new model inference, new live quality, population quality or another platform's
performance. The bridge inventories installed dependencies and executable
files; it does not replace ECR-r1's complete runtime preparation receipt or
hosted CI.

Root also passed three actual installed-integrity checks through isolated
`-I -B` calls to `bridge.target` with the exact target/product inputs. An added
`cragkit/__release_integrity_probe__.py` file was rejected, a changed target
`dist/index.js` was rejected, and restoration recovered the original 2,608-file
target snapshot
`fe442d30048e03940027ce9899a542cf96ade01d46b0bbdb9dc85621080e44f7`.
Root removed its probe file and restored the original Node bytes in `finally`
cleanup. These checks made zero provider calls. The inspected record at
`artifacts/V6/release-installed/integrity-probes.json` has SHA-256
`5d7cafe7ae97e4eb1a28c10fed75adb9c643fb92f888097823667e95fccb1157`.

This lane changed only the helper, its focused test file and this report. Root
owned the test/native processes; the lane started none. Learning practice
remains unassessed: predict
whether changing a response byte, a request key or only a measured duration
should pass, then explain the difference after the integrator runs the checks.
