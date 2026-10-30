# V5-04H: Partial Qdrant write and same-identity repair

State: COMPLETE for frozen fault ID `partial_qdrant_write` only. V5-04H and full V5 remain open.

For example, a nine-point generation uses an eight-point first batch and a one-point second batch. If Qdrant completes the first batch but the reply is lost, the publication stays unknown with the previous generation active. Recovery must fill only the missing ninth point and publish the original intent, revision and generation.

## Native assertion change

The existing G1b native scenario already performs this physical fault and repair. The Python and TypeScript consumers now bind the trace more tightly: nine unique expected IDs; the exact first eight-point request and its completed Qdrant response before the reply is withheld; unchanged previous pointer, original owner intent, revision, generation, manifest and payload seals during uncertainty and an authorization denial; a single missing-point recovery request; then ordinary replay batches of eight and one. The final public result and durable snapshot must report the original intent/revision/generation, published state and replica completion. Each successful repair retains the existing one-attempt ledger check. No output shape or ordered check label changed.

The frozen fixture illustrates two chunks. Nine members are required here to cross the implementation's eight-point dispatch limit. The first batch completes and loses its reply; the second batch is not sent before recovery. This is not an interrupted second HTTP request.

## Verification

Root inspected both assembled consumer diffs and corrected Python's reply-loss injector to require an actual `completed` response, matching TypeScript. Root then ran:

```sh
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres pytest tools/tests/test_qdrant_partial_repair_native.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_partial_repair.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --runtime all --artifacts-dir artifacts/V5/V5-04H/partial-both-final-02
python3 tools/check_seal.py
```

Five parent protocol guards passed. The final native run passed eight ordered checks per runtime and `cleanup_verified: true` against disposable PostgreSQL 17 and pinned Qdrant 1.20.0. All 16 sealed evaluation inputs matched. The ignored final record is `artifacts/V5/V5-04H/partial-both-final-02/results.json`. An earlier passing native run preceded the Python completed-reply assertion and is not the final acceptance record. The injected SQL acknowledgment losses intentionally discard test connections; their stderr notices do not indicate fixture cleanup failure.

Two Sol peers wrote separate Python and TypeScript consumers, coordinated the exact batch and identity assertions directly and transferred both paths to root. Python assembled; root ran all checks serially. No product module, schema, migration, shared fixture, dependency, lockfile, provider or hosted service changed. Synthetic vectors establish this fault boundary, not model quality or default-budget performance.

Eighteen exact H IDs now have accepted native evidence. Other fault rows, killed-coordinator recovery and the final V5 gates remain open. Learning practice remains unassessed: explain why the completed first batch cannot be sent again merely because its reply was lost.
