# V3-02D: Hosted probe preparation and authentication failure

Historical attempt record; superseded for current acceptance by [successful comparison](V3-02D.md).

Date: 2026-10-24. State: required live comparison NOT PASSED after two explicitly configured Python authentication attempts. [V3-02](V3-02.md) and V3 remain incomplete. No dependent V3-03 implementation was started.

## Configuration and bounded attempt

The user saved a nonempty owned regular key file with mode 0600 in an owned directory with mode 0700. Key contents were not printed, committed or passed in process arguments. Root selected the shortlisted Cohere `rerank-v5.0-fast` API2 mutable alias for the requested comparison. The two native probes use only the existing three-passage synthetic room example, not approved evaluation documents or held-out labels.

Fixed destination: `https://api.cohere.com/v2/rerank`; verified TLS, no proxy/redirect/retry, max three short ASCII passages, explicit top_n equal to candidate count and max_tokens_per_doc1024. Each probe normalizes returned indices/scores through the native RK-r2 adapter and emits sanitized metadata only. Provider token processing/truncation remains unknown; these probes do not establish a production hosted transport or model-token ceiling.

Cohere's [dated launch pricing](https://cohere.com/blog/rerank-5) lists Fast at USD0.02/million tokens. Admission arithmetic for two requests with three 32,768-token context bounds is USD 0.00393216, below the task's USD 0.01 budget. This is a planning estimate, not an invoice or a strict guarantee for unknown account terms. [Provider data commitments](https://cohere.com/enterprise-data-commitments) distinguish commercial and trial usage; this run makes no account-specific retention/training/zero-retention claim and transmits only original synthetic public fixture text.

Actual observation retained in ignored artifacts/V3/V3-02D/python.json:

```json
{"state":"failed","runtime":"python","error_code":"provider_http_status","http_status":401,"provider_calls":1,"observed_ms":481.125}
```

The Node live request did not run. No automatic retry, model substitution or account upgrade occurred. The owner then confirmed the saved credential was from OpenAI or another provider. Root advised revoking/rotating it at its original provider because it had been sent once to Cohere as an authentication header. Provider-side revocation remains a user action; it was not performed or claimed here. The key and raw response headers/body are absent from this report and Git.

An initial local invocation resolved the virtualenv interpreter symlink, losing its environment and failing before probe setup/credential reading/network dispatch. Root corrected the invocation to preserve the virtualenv path, then made the one request above. That local failure is not counted as a model request. The actual request process had a parent 30-second wall limit; the Python transport separately used a bounded socket timeout. Native Node has a 20-second abort deadline. After the owner confirmed a replacement was saved, root made the separately configured second attempt described below; Node remained undispatched.

## Implemented tools and verification

Two Sol peers owned separate Python/Node probe tools and coordinated profile/mapping/report fields directly. Python assembled; root inspected, tested and owns the final result. Workers never read the key or executed live calls. No unresolved peer issue required Astra.

Root added the hidden-entry `tools/save_cohere_key.py` helper: input validation, owner/private path checks, atomic file replacement, no key in errors or shell history, no network request. Offline tests use fake keys under temporary homes and cover successful save/read/replacement, invalid-input preservation, unsafe permissions/symlinks/oversize, sanitized401 failure without retry, hidden-prompt error redaction and Node's no-opt-in zero-call guard.

Actual validation: initial focused 13 tests passed, then the final checkpoint included 14 new tests. `node --check tools/check_typescript_cohere_reranking.mjs` passed. Running that tool without --allow-live intentionally failed with live_opt_in_required, provider_calls0 and no credential/network access. Full `python3 tools/check_v0.py --artifacts-dir artifacts/V3/V3-02D/checkpoint` passed all 18 stages: 884 Python/tool tests, 701 Node tests, strict typing/build, 11 synthetic adapter parity cases, existing conformance/schema/corpus/seal checks, four clean artifacts and three guarded imports.

Resources: M4/16 GiB constraint, observed 40 GiB free disk; one check process and one live request at a time, no new dependency/model download/database/service/watcher. Only hosted authentication failures occurred. Actual billable tokens and cost are unknown; no zero-cost claim. Task test processes and artifact environments were closed/removed. Both user audit reports remain untouched and excluded.

## Next action

After revoking/rotating the wrong-provider key, get a Cohere key from its [API-key dashboard](https://dashboard.cohere.com/api-keys), run `python3 tools/save_cohere_key.py` locally and confirm saved. Then root may run a newly configured small comparison; no further live call is authorized by this report alone. Preserve cumulative call counts and the budget when a replacement-key run is authorized.

Learning example: an API key authenticates to its issuing provider, not to every model service. Authentication failure establishes no ranking behavior. Practice remains pending.


## Replacement attempt and final preparation checks

The owner replied saved to the replacement-key instruction. Root made one new Python request under the same sample/timeout controls: HTTP 401, provider_calls 1, observed_ms 418.881. Node again did not run. Cumulative actual requests: two Python requests, both 401; zero Node requests. Under the dated price/context admission assumptions, two requests remain below USD 0.01; observed billable usage remains unknown. No actual ranking response was received.

An offline format check then found a recognizable OpenAI project/service key prefix, without printing the prefix contents or token. This is a format observation, not verification with OpenAI. Root advised rotating any key used for these wrong-destination attempts and offered either a valid Cohere key or an explicitly revised OpenAI-based reranker contract/evaluation. The owner chose to retain Cohere and create a key in its dashboard; save confirmation is pending. No further live call will run before resolution.

The saver and both probes now reject recognizable OpenAI project/service key formats locally, before dispatch. The saver also converts GetPassWarning into failure to prevent echoed-input fallback, writes no extra newline so a 4,096-character key stays within the 4,096-byte reader bound, and preserves an existing key on invalid input. Review found those two helper issues; both were fixed and covered before final validation. The helper changes do not revoke keys or alter provider accounts.

Final actual checks supersede the earlier preparation checkpoint: 18 focused offline tests passed; full 18-stage final checkpoint passed 888 Python/tool tests, 701 Node tests, mypy 21 source files, TypeScript checks/build, 11 shared adapter cases, schemas/corpus/16 seals, four clean artifacts and three guarded installed imports. Log: artifacts/V3/V3-02D/final.log. No implementation/test changes followed that final checkpoint. The successful credential path remains demonstrated with fake test keys only; both real authentication attempts failed.
