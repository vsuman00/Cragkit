# V6-05 developer trial record

State: the plan's unavailable-participant path is recorded; an installed-package
agent rehearsal passed. Independent human usability, comparative effort and
adoption feedback remain unvalidated. This report does not represent a human
trial as complete.

No unfamiliar human participant or comparable manual SQL baseline was available
in this session. Participant identity, task times, errors, assistance and reasons
to continue/abandon are null in the [verification record](V6-05-verification.json).
Agent preparation time is not a substitute. The frozen target remains library
task time no greater than the same-behavior baseline, with no relaxed invariants;
that target was not measured.

The [future human protocol](../../../docs/usability-trial.md) fixes the corpus,
starting state, comparison tasks and recording rules. It requires both arms to
enforce scope, required filters, immutable source fidelity, explicit uncertainty
and operational errors. It does not compare a full library against an easier SQL
task. Missing participation is recorded as the active plan and BRD require.

## Agent rehearsal and actual corrections

Root used one writer because the small installation/documentation rehearsal was
dependent work. No agent was treated as an independent human participant. Reading
the guide exposed stale `0.0.0` wheel/tarball names, an old planned beta label and
an assumed local PostgreSQL path. The operations guide and pilot README/checklist
now use current Python `1.0.0rc1` / npm `1.0.0-rc.1`, caller-selected artifact
paths and the existing `--postgres-bin` option. The root README's section order,
centered banner, status table, callouts and collapsible guide were preserved;
only stale V6 status content changed.

The first offline installation failed before installing: uv 0.11.8 rejected an
absolute `--constraints` filename containing the workspace's space. A second
attempt using a file-URI wheel failed for the same reason. Root also mistakenly
launched the first smoke command before checking the failed installation; its
child could not import Cragkit. That disposable database closed. All three
failures are retained as agent observations, not attributed to a human user.

Isolated dry runs then varied one argument at a time. Relative paths, a file-URI
wheel, an absolute interpreter and an absolute wheel all resolved successfully.
Only the spaced absolute constraints path failed. Using a relative locked
constraints path fixed installation. The guide records this specific issue; it
does not incorrectly blame the wheel or shell quoting. No version assertion,
security guard or dependency lock was weakened.

Nine locked core/PostgreSQL packages installed from the offline cache into a
fresh owned environment. The installed core wheel is the post-security local
audit archive, identified by digest in the verification record. Its origin was
confined to the environment, not the checkout. It is not a final release artifact.

The corrected smoke run used genuine isolated PostgreSQL 17.11 and ten public
synthetic documents. All 21 mechanics checks passed: expected/absent retrieval,
unknown coverage, exact citations, same-tenant/foreign denial, foreign-owner
access, Unicode bytes, code identifiers, source injection retained as data,
unauthorized writes, invalid input, strict budget failure, idempotent ingestion,
immutable update, updated evidence, tombstone exclusion and a closed-resource
operational failure. No real embedding or generation call ran. The listener,
child application, database and private runtime credentials were cleaned up.

Example reproduced command, from the repository root after installing the wheel:

```sh
uv run --project packages/python --frozen --no-sync python -B examples/pilot_rag/session.py --python artifacts/V6/V6-05/pilot-env/bin/python --postgres-bin artifacts/V6/V6-02A/private-pg/prefix/Cellar/postgresql@17/17.11/bin --smoke
```

The initial environment had no successful prior installation; the verified
correction installed all nine packages before the successful fresh database run.
Logs, corpus/wheel digests, failures and import-origin confinement are retained.
Manual checklist result cells remain blank. No human feedback or measured effort
improvement is inferred from the smoke checks.

## Resource observation and next gate

After smoke, memory free was 32% and swap allocation had increased. Root stopped
further native workload. A later check recovered to 46% free, but swap allocation
grew again; causality was not established. No owned PostgreSQL/Qdrant/child process
remained. Further local load must wait for stable headroom or use an explicitly
approved suitable CI runner. Documentation and metadata work can continue.

V6-05's documentation/rehearsal work and unavailable-participant record are
complete under its explicit limitation path. Human comparative claims remain
unvalidated. Next: V6-06 exact artifacts, licenses/notices and supported CI evidence.
Optional exercise: explain `partial` evidence versus a failed execution without
referring to implementation internals. Learning practice remains unassessed.
