# Recovery candidate execution preparation

Status: PASS for actual clean runtime preparation, independent verification and
native development rehearsal. Genuine recovery evaluation is recorded separately
in [V6-02 recovery acceptance](V6-02-recovery.md).

For example, a virtual environment satisfying `>=3.14` can still violate an
exactly frozen Python 3.14.6 matrix. The runtime guard refused that mismatch; the
matrix was preserved and the retained matching interpreter was selected explicitly.

The fresh detached checkout at `34b5748` evaluates source
`25275e447c64ecfd243ef6bc26c87031d5e2e472`, package tree
`05fdc769488f496ef71ec6b988383fa8d1f18b1c`. It selects only the separately approved
recovery-r1 held-out profile; original development inputs remain unchanged.
Original candidate bytes are retained in the tracked history file and the failed
original checkout/admission remains intact. Quality, resource, request, provider,
call and spend targets match the original configuration exactly.

Python dependencies were installed offline from the frozen lock. The first
unqualified environment selected Python 3.14.4; preparation refused it. An explicit
offline sync with the retained Homebrew 3.14.6 interpreter corrected that prerequisite.
Node's fresh offline `npm ci` failed with `ENOTCACHED`; its private log is retained.
No partial dependency directory existed. Root verified every one of 1,706 old Node
dependency inventory entries against the previously accepted ECR receipt and
confirmed identical package locks, copied those exact bytes, then reverified the
complete copied inventory. This is verified frozen-dependency reuse, not a claim
that the failed npm command succeeded. Node built from the checked source.
The pinned tokenizer was copied and hash-verified; no model download occurred.

A second preparation failed because the task-owned receipt parent did not exist.
After a full diagnostic snapshot passed and filesystem inspection confirmed the
missing prerequisite, root created only that owner-only parent. No validator,
source, version matrix or recorded failed log was weakened or deleted.

Final ECR preparation and independent verification both accepted 9,414 inventory
files, 100 emitted Node files, Python 3.14.6, Node 26.5.0, npm 11.17.0 and
TypeScript 7.0.2. The owner-only receipt is mode 0600 within a 0700 directory.
The accepted execution identity is:

```text
59af39c6cb0a5d118c73511dbb67b5fd22b2289a731ffeaaa5fc488d4105b993
```

Actual preparation commands used the retained pinned Python executable explicitly:

```sh
uv sync --project packages/python --python /opt/homebrew/Cellar/python@3.14/3.14.6/Frameworks/Python.framework/Versions/3.14/bin/python3.14 --frozen --offline
npm --prefix packages/typescript run build
uv run --project packages/python --frozen --no-sync python -B tools/evaluation_runtime.py prepare --output artifacts/V6/recovery-runtime
uv run --project packages/python --frozen --no-sync python -B tools/evaluation_runtime.py verify --receipt artifacts/V6/recovery-runtime/runtime.json
```

The output's parent was created with mode 0700 before final preparation. No user
cache was removed. The native parent rehearsal used that receipt, `--mode mechanics`,
the existing genuine PostgreSQL 17.11/pgvector 0.8.0 prefix, a fresh output directory
and explicit local-process opt-in. It reverified identity around both native
stages. Python and Node each returned 120 development rows and nine receipts;
normalized parity, harness metric targets and owned cleanup passed. There were
zero model HTTP calls or held-out execution during this rehearsal. Fake results
do not establish model quality.

[Structured preparation evidence](V6-02I-runtime-verification.json) binds the
configuration, receipt, dependency-copy provenance, failed prerequisites,
permissions, runtime versions and retained safe log hashes. Source status in the
isolated checkout remains clean. No hosted database or registry publication is
inferred from this local preparation. Learning practice remains unassessed.
