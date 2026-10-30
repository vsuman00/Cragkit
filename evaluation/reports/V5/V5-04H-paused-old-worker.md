# V5-04H: Paused old worker resumes after key rotation

State: COMPLETE for exact fault ID `paused_old_worker_resumes` only. V5-04H and V5 remain open.

For example, a child that was admitted before recovery may wake after the supervisor rotates its write key. Its old request must fail at Qdrant, and current authorized work must still be recoverable.

The existing native worker trace already held the same child after durable dispatch and before HTTP send. The surviving supervisor recovered the instance, advanced the epoch and changed the credential generation. On resume, the child sent with its captured old credential and received an actual HTTP 401. Neither its intent nor an unrelated pending intent published, and the backend remained recovery blocked. The first 18-check rerun proved these boundaries but did not satisfy the fixture's reconciliation expectation, so it was not counted as exact acceptance.

Both consumers now retain that recovery proof. Using current authorized scopes and actual durable owner tokens, they reconcile and physically verify the three uncertain documents, settle every dispatch, and reopen the instance once. The paused target is repaired through the current authorized scope and publishes at epoch 2. Exact point ID, payload and vector readback checks the current authorization fields and preserves the previous published generation and the separate EOF document. The fixture does not inject an authorization revision change; a later changed-authorization case remains separate.

Root inspected the peer changes and ran the Python and TypeScript native cases separately, then the combined parent:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_publication_worker.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/paused-old-worker-both-02
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_publication_worker_native.py -q
node --check tools/check_typescript_qdrant_publication_worker.mjs
python3 -m py_compile tools/qdrant_publication_worker_cases.py tools/check_qdrant_publication_worker.py
python3 tools/check_seal.py
```

The combined native run passed 24 checks, 12 per runtime, with matching public-result SHA-256 `7ba570d37e0a78880cf9d914816ae12748590d656142dfbf4e6d8c6e030d267e` and verified cleanup. Three focused tests passed; syntax, compilation and all 16 seals passed. The ignored result is `artifacts/V5/V5-04H/paused-old-worker-both-02/results.json`. The full package regressions last passed at H-S22 and were not rerun for this native harness change. No provider call, hosted mutation or model runtime was used.

The failure case is opening dispatch after rejecting the old key while another document still has an unsettled write. The new trace checks every instance journal is settled before the single reopen. This is local single-node evidence; it does not establish supervisor-death takeover, lease-expiry fencing, hosted CI or production readiness. The peers owned separate native consumers, coordinated check labels directly and assembled the result; root ran final acceptance. Learning practice remains unassessed: explain why rejecting one stale request is insufficient to reopen an instance with other uncertain writes.
