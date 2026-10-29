# V5-04 profile-5 runtime admission

The Python and Node PostgreSQL adapters now recognize the exact QP-r1 profile-5
history, catalog, owner metadata, capability fingerprint and restricted role
permissions. A profile-4 instance refuses a live change to profile 5. The
source reader uses retained original byte counts and reports an erased source
as unavailable before attempting to decode a NULL body.

For example, a source excerpt that was 18 UTF-8 bytes before erasure retains
that original count even when its body is NULL. A reader must not treat NULL
as an empty 0-byte excerpt.

| Verification | Result |
| --- | --- |
| Python authority, writer, recovery and source focused tests | 533 passed |
| Node authority, writer, recovery and source focused tests | 331 passed |
| Python strict typecheck | 49 source files, no issues |
| Node build | Passed |
| Disposable PostgreSQL 17 with actual restricted Python and Node writer/reader logins | 18 checks passed; cleanup verified |

The native result is
`artifacts/V5/V5-04-profile5/runtime-admission-02/results.json`. The SQL fixture
uses a synthetic absence digest. The runtime additions prove exact admission
and restricted login compatibility with the installed schema; they do not
establish actual Qdrant deletion, public repeated security convergence or
the complete V5-04 recovery fault matrix. Python and Node source-unavailable
behavior has focused tests; a native erased-source retrieval check remains open.

The Node focused run initially exposed an old-profile regression: explicit
initialization from profiles 2 or 3 to 4 was rejected by a new history pin.
The pin now applies to admitted profiles 4 and 5, preserving that supported
upgrade path. The focused suite then passed. No hosted database, provider call
or package publication ran.
