# V6-08: local workflow and registry verification

State: C1/C2 and the local C3 workflow machinery passed scoped acceptance.
Registry account permissions, trusted-publisher/bootstrap configuration,
publication authorization, hosted execution and post-registry consumer/source
smoke remain incomplete. V6-08 and full V6 are not complete.

For example, a registry 404 permits a preflight result of `absent`; it cannot
prove that the current account may publish the name. A TLS failure is an
operational error and must not become that same absence result.

## Local acceptance

The [PWK-r1 contract](../../../contracts/PUBLICATION_WORKFLOW_V6.md) and
[workflow policy](../../release/V6-publication.json) preserve the earlier nine
RC1 products and their immutable PPR manifest. The transport contains five fixed
inputs: original CI ZIP, three original metadata records and the reviewed
manifest. Actual pack/unpack passed. Its size is 1,486,204 bytes and SHA-256 is
`6b817c8c627e1cdd0fe882b25617b2be17fe6ff7dc75e45b3d8a26d69c0db0d0`.
Root compared every regenerated product and the manifest with the earlier
prepared files; all bytes matched. The transport remains local, mode 0600.

The [manual workflow](../../../.github/workflows/publish-candidate.yml) has no
push/PR trigger. Publication, cost and setup flags default false; the repository
enable variable is absent. Admission requires owner `vsuman00`, private
repository, reviewed `main` SHA and attempt one. Its token has repository read
and upload-job OIDC permissions. It cannot create the proposed private draft
release/asset; those later authorized actions are separate. Draft identity,
asset membership/size/digest and transport bytes are checked before unpacking.

Preflight validates existing registry files and plans only reviewed missing
files. Python core precedes adapters, each through its own trusted publisher;
`skip-existing` is false. npm uses exact tarballs, `next`, ignored package hooks
and explicit unavailable-provenance handling. A conflicting existing npm tag
needs review. Postflight fetches all nine files and checks tags. No hosted
publication behavior, account authority or post-install behavior is inferred
from this local implementation.

| Actual check | Result |
| --- | --- |
| Transport tests after final parser correction | 68 passed in 1.14 seconds. |
| Registry checker, fake HTTP and real non-network child tests | 103 passed in 0.91 seconds. |
| Final admission/upload-planning tests | 33 passed in 0.10 seconds. |
| Final full current-checkout Python/tool suite | 4,360 passed, zero skips, four existing intentional warnings in 20.75 seconds. |
| Actionlint 1.7.12 | Both current workflows passed; local binary matched the official release checksum. No global install or hosted run. |
| Actual local missing-file plan | Nine missing products, three Python upload groups and ordered npm paths; local admission refused without authorization context. No upload function ran against a real registry. |

An initial corrupt-ZIP test passed with a stdlib overlap warning containing an
untrusted member name. Root inspected the parser and moved complete duplicate/
header checks before any member read. The same 68 tests then passed without that
warning. No archive guard or error assertion was weakened. The initial parser-warning observation and subsequent clean result remain
distinct; the initial test run itself did not fail.

## Bounded registry requests

The checker pins the earlier committed product-summary bytes as well as manifest
and source identities. It uses unauthenticated direct verified TLS, canonical
hosts/URLs, strict JSON, byte limits, actual file hashes and registry digests.
Redirects, proxy/auth environment discovery and arbitrary server error text are
excluded. Metadata claiming a file exists followed by file 404 is an error.

Root and Astra resolved the DNS/header deadline gap with one supervised helper
per request: at most 18 sequential launches, one active child, five-second
request and shared 60-second budgets. Timeout/interruption kills and reaps the
child before its private temporary directory is removed. SIGTERM enters that
cleanup path. Real non-network sleeper/slow-writer tests verify termination,
reaping and temporary cleanup; fake cases cover bounds, malformed outputs and
late completion. OS scheduling/launch/reaping overhead means this is not a
promise that total CLI runtime is exactly 60 seconds.

Root ran one public read-only preflight. It made nine requests, returned all nine
products and three npm `next` tags absent, and had zero operational errors.
`publication_complete` remained false. No provider/document input was sent and
no account credential was used. This result neither reserves names nor proves
permission. Receipts are under `artifacts/V6/registry-preflight-rc1/` and bound by
[the machine-readable verification](V6-08-workflow-verification.json).

## Authorization model and remaining work

Read-only GitHub inspection found no environment and no repository variable;
the API did not return the account plan. Current platform documentation limits
private environment/reviewer features by plan. Root accepted Astra's bounded
single-maintainer model instead of inventing a paid upgrade or repository
visibility decision. There is no independent deployment reviewer. The owner
account and repository writers remain trusted; SHA matching is acknowledgment,
not proof of review. Registry-supported workflow/ref restrictions still require
verification during authorized setup. See [the runbook](../../../docs/publication.md).

Sol transport and registry peers owned separate tool/test pairs; registry
assembled their interfaces. Root owned the shared helper extension, policy,
workflow, planner/tests, documentation, test slot and final integration. Both
peers stopped writing before transfer. Astra reviews were read-only. No package,
applied migration, dependency lock, README structure or user-owned source changed.
Resource checks observed 23 GiB disk headroom and 39 percent system memory free;
no load benchmark, model download, persistent service or database was started.

Next: obtain public registry identities, verify six project permissions and
secure bootstrap/trusted-publisher setup, then request the concrete publication,
private draft-asset transport and one bounded workflow authorization. No account
configuration, draft/tag/asset upload, enablement, dispatch or publication ran.
V6-08D download/install/source-access smoke and V6-09/C3/exit remain required.

Failure case: after a partial upload, an existing file with a different digest
stops the next attempt before further upload planning. Exercise: explain why a
missing name, authenticated ownership and successful publication require three
different observations. Learning practice remains unassessed.
