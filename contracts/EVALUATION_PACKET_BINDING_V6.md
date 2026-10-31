# Evaluation packet binding EPB-r1

For example, changing a local manifest and its hashes must not authorize sending a private replacement document to an embedding API. Bind runtime input to the independently pinned original human-approval seal, then verify the exact bytes consumed by parsing.

`tools/evaluation_packet.py` exports `bind_packet(root=ROOT, *, split="development", allow_held_out=False, require_candidate=False)`. The result is an issued immutable snapshot with `runtime_packet()` and `provenance()` methods. It is not a provider transport or an externally supplied authorization record. Live parents must call the binder themselves.

Development defaults to an offline rehearsal. Held-out selection always requires `allow_held_out=True` and successful candidate-source verification before interpreting held-out question JSON. Tests use synthetic held-out fixtures; opening the original reviewed held-out labels remains a separate evaluation action.

The original approved seal SHA-256 is `210ddce9237847d271db35dbff1d7c74a1ba1f30323a3f4119f939a604a83f81`. Updating a mutable candidate/manifest/seal together cannot replace that approval. A changed reviewed packet requires an explicit new approval and policy revision. The candidate's six preregistration input digests and the approved seal must agree on the same consumed bytes. Reads use directory descriptors with no symlink following, admit regular files only, reject FIFOs without blocking, and enforce per-file byte ceilings. JSON rejects duplicate keys and nonfinite values. Errors contain fixed diagnostics and do not retain parser/decoder exception context.

The binder reuses the release checker's pure frozen-settings validation. Its own bounded readers check preregistration inputs and approved source/dataset bytes. The full release CLI retains its separate coverage and evidence-path checks; packet binding alone does not establish release readiness.

Runtime projection contains only EVX-r1 documents and query/scope/filter fields. Reviewed answerability, support, facets and policy do not enter either native worker. Projection passes the worker's pure packet validator. Callers receive fresh copies from the immutable snapshot; manually constructed or unissued snapshots cannot attest source verification.

Candidate-source verification checks the pinned Git commit/package tree, tracked source differences, staged/unstaged/untracked source changes, committed release metadata, and the binder/Python import origin. A stale or dirty checkout fails. The covered source areas are `packages`, `tools`, `contracts` and `evaluation/runners`. Git commands have finite timeouts and their diagnostics are not returned to callers.

Source identity is a snapshot, separate from compiled Node output or installed-artifact identity. Provenance always reports `compiled_artifacts_verified: false`. Before a live evaluation, the parent must prepare and bind the compiled/runtime artifacts from the frozen checkout and revalidate its execution identity. Serialized provenance is not a substitute for those checks. Neither binding mode reads keys, makes provider requests, downloads assets, starts services or changes release targets.
