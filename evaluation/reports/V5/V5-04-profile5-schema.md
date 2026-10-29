# V5 profile-5 schema prerequisite

QP-r1 adds one explicit PostgreSQL migration after the four accepted Qdrant
migrations. It permits the existing security guard to check a committed security
owner, and it adds an irreversible representation for managed source, replay and
request bodies. The dedicated purger can erase those bodies while retaining
source identities, spans, digests, claims and operation history.

For example, an old owner may be the committed authorization update itself.
The guard now accepts that actual owner and still checks the current security
tuple under backend, owner and document locks. It refuses a purge owner for that
operation. Vector deletion alone does not set purge completion.

The integrator ran these checks on an isolated PostgreSQL 17 fixture:

| Check | Observed result |
| --- | --- |
| Native seed through accepted profile-4 writer | Passed, cleanup verified |
| Migration installation, complete rollback and exact checksum history | Passed |
| Stage, prior security and same-current-security owner guard calls | Passed |
| Restricted role, malformed/foreign input and pending-journal refusals | Passed |
| Erasure rollback, body restore refusal and exact SQL retry | Passed |
| Committed erasure, fresh login, read-only historical confirmation | Passed |
| Native SQL checks in the final run | 14 passed, cleanup verified |
| Focused schema and probe helper tests | 44 passed |
| Protected inputs | 16 seals, four earlier migration hashes and three user audits unchanged |

The first native run identified new trigger functions that inherited PostgreSQL's
default PUBLIC execution permission. The migration now explicitly revokes that
permission. A subsequent native run passed the guard and erasure checks. The
initial fixture attempt also identified that ordinary security-owner admission
requires profile 4; its writer now starts after that prerequisite is installed.
Those failures were diagnosed at their exact stage before the focused fixes.

The final native result is in
`artifacts/V5/V5-04-profile5/native-05/results.json`. Its profile fingerprint is
`ca83de1388d892be58ccf6a49acf1a8afcdccd66c3f30b87d57bd457fe76f5d8`;
the separate effective capability fingerprint is
`80210922ed1130d45762383222affbf0147c679f5a23e9b2ed20ac079f33c817`.
These come from the actual installed catalog, not a fixture assertion alone.

The absence digest supplied in these SQL checks is synthetic. The result proves
relational authorization, atomicity and restricted permissions; it does not
prove that Qdrant points were deleted or that a real absent replica was observed.
Runtime profile admission, repeated public security convergence, physical purge
and source-unavailable behavior are separate open gates. G2, G3 and V5 remain
incomplete. No hosted database, provider/model call or package release ran.

The migration retains locators and ACL metadata and performs logical managed-row
erasure. It does not sanitize PostgreSQL heap, WAL, replicas or backups, nor
external logs and caller-owned stores. A learned failure case: allowing a new
trigger function to inherit PUBLIC execution made a strict guard reject the
profile. Restricting that function's grant fixed the actual permission mismatch.
