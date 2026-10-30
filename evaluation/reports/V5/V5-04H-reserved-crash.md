# V5-04H reserved child crash checkpoint

This checkpoint exercises frozen fault ID `journal_commit_before_api` with
the actual native Python and Node publication workers. A separate disposable
scenario first publishes a base generation through a real child, then stages
its successor. The parent terminates and reaps that exact child when the new
`reserved` event arrives after the real reservation COMMIT and before the
dispatched marker or HTTP send.

For example, a `reserved` journal row survives the child's death even though
the successor points are absent from Qdrant. A fresh SQL read finds one
reserved or unknown dispatch with the original ID and sequence. The base
generation stays active, the successor stays unpublished, and the same
supervisor remains alive. A fresh host retry after a bounded 1.05-second wait
produces no second dispatch or point write. The physical absence check is
repeated after that retry. These observations establish refusal at the
reserved-before-HTTP boundary; the observer event alone would not.

The first local native probe exposed a fixture cleanup call to a Python
verifier without a `close()` method. Root used the existing optional-close
pattern. The accepted serial PostgreSQL 17/Qdrant 1.20 run then passed 12
checks, six per runtime, with matching public-result hash
`fad298337cc6ef1386d01a2f62c1fef23377d38bdf05e5da49ca871d0db2a646`
and verified task-owned cleanup. Private result:
`artifacts/V5/V5-04H/reserved-both-02/results.json`.

The affected ordinary-worker native regression also passed 18 checks, nine
per runtime, with matching public-result hash
`7ba570d37e0a78880cf9d914816ae12748590d656142dfbf4e6d8c6e030d267e`
and cleanup. Its first local probe exposed a fixed EOF fixture that needed to
acknowledge `reserved` before withholding `before_write`; root corrected the
fixture and reran it. Private result:
`artifacts/V5/V5-04H/ordinary-reserved-regression-both-02/results.json`.
The ordinary trace still kills and pauses only at the later dispatched
barrier and observes an actual old-key HTTP 401 after recovery.

Full local Python/package-tool regression passed 3,097 tests with four
existing serializer warnings. Full Node regression passed 1,557 tests and
strict TypeScript build. Python mypy found no issues in 49 source files;
all 16 sealed inputs matched. No schema, grants, migration, dependency,
lockfile, model provider or hosted service changed.

The `reserved_owner_crash` row has real child-death and blocked-retry evidence,
but the 1.05-second wait is not a configured lease-expiry boundary. That row
remains open for its exact lease assertion. Thirteen H IDs have complete native
evidence; other matrix rows, recovery coordinator process death, V5-04 parent
acceptance and full V5 remain open. Learning practice is unassessed: explain
why absent points after a crash cannot by itself clear a durable reservation.
