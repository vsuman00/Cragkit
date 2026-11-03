# V6-07: migration and rollback acceptance

V6-07 is complete for the declared local rehearsal, including a required explicit
operator repair. The [upgrade report](V6-07-upgrade.md),
[backup report](V6-07-backup.md) and [verification record](V6-07-verification.json)
retain commands, versions, hashes, failures and limits. Full V6 remains open.

For example, migration 0002 preserves the short configuration name `simple` in
legacy rows. Both current CI and historical Python/Node packages refuse that
spelling for FTS and identifier candidates. The separately versioned maintenance
step canonicalizes only that field under writer-excluding locks and verifies
that source bytes, binary vectors, security state and histories remain unchanged.
The unmodified upgrade is still recorded as rejected.

Native acceptance passed six upgrade groups and fourteen operator groups,
including genuine precommit backend termination for both repair and profile
upgrade, bounded writer-lock refusal, explicit retry and idempotence. A separate
lexical-only fixture passed CLI check/apply/check with exit statuses 2/0/0.
The current products retained fake dense support after setup 0003; historical
products refused it while preserving exact lexical and identifier reads. Those
old products lack a later security correction and are not approved rollback
versions. The [operations guide](../../../docs/migrations-and-recovery.md) explains
how to select a compatible recovery path.

The backup lane restored three synthetic documents in quarantine, reapplied
current authority, then passed ten recovery checks and five source-access cases
per runtime. Revoked, foreign, tombstoned and old-scope access stayed denied.
Both lanes closed owned services, used no model HTTP calls or hosted database
writes, and preserved the original live evaluation and candidate product bytes.
Ten upgrade pressure observations showed 35-38 percent free memory and no
swapout growth within the small functional run. No load benchmark ran.

Final focused checks passed 109 upgrade/operator cases; the backup suite passed
32 cases. The first full Python/tool run exposed an existing test-loader class
identity collision: a budget test replaced a module already used by the sender.
The same three-file collection reproduced the failure before a loader-only fix;
it then passed all 72 cases. Final full verification passed 4,109 tests, no skips
and four existing intentional Pydantic boundary warnings. No production budget,
error type or assertion was weakened. Earlier failed logs remain retained.

This is scoped local operational evidence, not production PITR, cross-cluster
recovery or new live model quality. The maintenance tool's combined snapshot
limit is 1,000 rows/8 MiB; setup-only optional vector storage is unsupported.
The earlier paid CI covers its original inputs. Next is V6-08 release preparation
and its separate publication decision, followed by maintenance handoff. Learning
practice remains unassessed: explain why a pending repair receipt and a valid old
backup both require further checks before application traffic resumes.
