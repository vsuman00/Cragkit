# V5-04H: Deadline expiry does not settle a write

State: COMPLETE for exact `lease_expiry_not_fencing` under the clarified native-profile wording. Parent H/V5 acceptance remains separate.

For example, a local timeout can end a publisher while an already admitted request is still being delivered. Its successor must wait for durable settlement or managed recovery.

The fixture uses standard HTTP clients to stream one admitted full-point request, holding its last byte across the captured original operation deadline. This test-owned delivery is independent of manager cancellation; product transports retain their original timeout behavior. The owner pool closes, its actual PostgreSQL backend disappears, and the original writer cannot reconnect through that closed resource. A fresh independent writer refuses successor ownership while the exact dispatched journal, owner and old active pointer remain unchanged.

The same request then completes with actual HTTP 200 and exact payload/vector readback. No acknowledgment is passed back to the expired manager and no journal settlement is fabricated. Successor refusal and unchanged journal are checked again. Genuine managed repair rotates credentials, rejects the old credential, reconciles and settles the write before publication. The previous generation's physical points remain unchanged. This profile has no timed SQL owner lease; fixture and acceptance wording now identify the real operation deadline.

Python-only and TypeScript-only runs each passed seven checks. Final combined run passed 14, with matching witness SHA-256 `fa5ef2a56c07cdd183123887ff6cba153637e6f596b7cbc0c2bee3b6dc97583c` and verified cleanup. Ignored evidence: `artifacts/V5/V5-04H/deadline-both-final-01/results.json`. Existing ordinary and reserved worker scenarios then passed 24 and 14 native checks respectively in both runtimes. Five focused protocol tests and all 16 seals passed.

The initial Node run exposed millisecond timer rounding: a deadline exception can arrive just before the captured monotonic boundary. The fixture now observes that boundary before testing successor refusal. Python's observer query now commits its read-only transaction before returning its connection. No product module, schema, lockfile or user-owned source was changed. This is bounded local single-node evidence. Learning practice remains unassessed: explain why an HTTP completion without durable settlement does not permit the next publisher.

Final affected regressions passed: 3,111 Python/tool tests with four existing serializer warnings, 1,557 Node tests with strict build, and Python strict typechecking across 49 source files. The final native rerun followed cleanup hardening and preserved the same witness.
