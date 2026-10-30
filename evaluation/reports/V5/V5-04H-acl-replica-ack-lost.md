# V5-04H: Lost ACL replica acknowledgment

State: COMPLETE for fault ID `acl_replica_ack_lost` only. V5-04H and V5 remain open.

For example, a Qdrant point write may finish while its acknowledgment is lost. A reader whose grant was revoked must still receive no source text while the writer determines what happened.

The G2c native public-security trace now drops the client reply after a completed auth-3 full-point PUT. Both runtimes verify a durable `unknown` dispatch, a blocked backend, an incomplete replica flag, and the committed revocation. A retained handle and a fresh request for the original reader return unavailable; retained release carries zero source bytes. An explicit retry fences the credential used for the uncertain write, settles its journal, and leaves the backend open. A direct Qdrant readback confirms the exact four current auth-3 points and their ACL payloads. The old credential returns HTTP 401, and no PUT is resent through it. The existing auth-4 lost-acknowledgment case still runs.

Root inspected the two nonoverlapping consumer edits and ran these checks serially:

```sh
uv run --project packages/python --frozen --no-sync pytest tools/tests/test_qdrant_security_verification_native.py -q
uv run --project packages/python --frozen --no-sync --extra qdrant --extra postgres python tools/check_qdrant_security_verification.py --postgres-bin /opt/homebrew/opt/postgresql@17/bin --server-binary artifacts/V5/V5-02A/server-binary/qdrant --binary-sha256 830bd61d0efdba90e0737e174cefe32d4f9e0161b0e2b8684d655fb774544fd3 --allow-local-processes --with-security-guard --with-purge-profile --public-security --runtime all --artifacts-dir artifacts/V5/V5-04H/acl-replica-ack-both-07
node --check tools/check_typescript_qdrant_public_security.mjs
uv run --project packages/python --frozen --no-sync python -m py_compile tools/qdrant_public_security_cases.py
python3 tools/check_seal.py
```

Ten focused protocol tests passed. The combined native parent passed 18 checks, nine per runtime, with identical semantic witness SHA-256 `bcf117af7abc3b1bfc33a924ee0fe0ac4843445601c862cb2e413d2ee7a08df5` and verified cleanup. The ignored result is `artifacts/V5/V5-04H/acl-replica-ack-both-07/results.json`. Syntax, compilation, and all 16 sealed inputs passed. The full 3,104-test Python and 1,557-test Node regressions passed in H-S22; they were not rerun for this fixture-only slice. No product module, schema, migration, lockfile, shared sealed fixture, or user-owned file changed.

Two earlier fixture runs exposed test assumptions: the first queried the preceding owner's journal, and a later Node observer expected the body in `end()` even though the transport sends it through `write()`. The corrected fixture queries the new owner intent and captures both write paths. A replay can settle from fresh-key readback without another PUT; the check therefore requires current physical state and zero retired-key resends, not a second PUT. This is local native single-node evidence, not hosted CI, live-model quality, or production readiness. Sol peers coordinated the Python and Node observations directly; Python assembled, and root performed final acceptance. Learning practice remains unassessed: explain why a completed but unacknowledged replica write must block source release for the revoked reader.
