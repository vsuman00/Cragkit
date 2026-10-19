# GIT-01: Baseline upload scope review

State: READY_FOR_COMMIT, subject to the integrator's final staged review. This report does not claim that a commit or push occurred. The root integrator reports creating the private repository [vsuman00/Cragkit](https://github.com/vsuman00/Cragkit) and configuring its HTTPS origin; final remote commit and synchronization checks remain root-owned.

## Audited scope

The read-only candidate snapshot contained 116 files totaling 5,970,613 bytes, before the new repository entrypoint and this report. The root's independent inventory classified 107 text and nine binary files. These counts describe the inspected snapshot, not the final commit; the integrator must record the final staged scope.

Included project material comprises native Python and TypeScript sources, manifests and lockfiles, shared contracts and fixtures, governing architecture and task plans, project agent skills, evaluation tools, approved corpus and seal, development/evaluation evidence, historical proposals and reviews, the interactive proposal HTML and its analysis harness/results, architecture diagrams, and the research paper collection with its manifest. Keep the original historical files intact. Their earlier proposals and illustrative claims do not override the consolidated architecture or establish implemented retrieval behavior.

The largest candidate was `papers/2021-beir.pdf`, at 2,094,824 bytes. No candidate wheel, tarball, ZIP or other build archive appeared in the extension inventory. Six paper files matched both the byte lengths and SHA-256 digests in [the paper manifest](../../../papers/manifest.json). They are public research inputs retained in this private baseline; the manifest records their source URLs. This review does not grant a new license or publish a package.

## Checks and findings

Commands actually used included `git status --short`, `git ls-files --others --exclude-standard`, `git check-ignore -v -- <path>`, and small standard-library scripts over the candidate inventory. The scripts measured file counts/sizes, listed hidden candidate paths, scanned selected credential patterns without printing matched values, inspected URL hosts and executable network primitive counts in historical text, and checked the paper hashes. No tests, installs, services or Git mutations were performed by this reviewer.

The credential scan covered private-key headers, common GitHub/provider/AWS token formats, credential-bearing URLs and quoted credential assignments in text candidates. It produced one candidate finding:

| Location | Type | Inspection result |
| --- | --- | --- |
| `project_context_and_architecture.md:47` | Credential-shaped example database URL | Username and password are generic placeholders and the host is localhost; no actual credential was established. Root independently reached the same classification. |

No matched value is reproduced here. No other matches were found by these patterns. This is a scoped scan, not a guarantee that every secret format or binary payload has been detected. Binary research files were checked against the recorded public-paper digests; they were not subjected to a complete embedded-content audit.

Read inspection of `analysis/explorer-analysis.cjs`, its results JSON and the historical HTML confirmed their project relationship. The CJS harness reads and evaluates the supplied HTML scripts against a small DOM model. Its historical report records unresolved illustrative/accessibility findings; keeping that evidence does not make the HTML a production application. The analysis JSON contains the existing absolute local project path, which is noncredential historical metadata retained under the authorized inclusion scope. The HTML references Google Fonts; its external font loading is distinct from the library's no-network import contract. The scoped scan found no fetch, XMLHttpRequest or WebSocket call primitive in those three historical files.

Hidden candidates at the initial snapshot were `.gitignore` and the two project skill files under `.agents/skills/`. No `.env`, credential configuration or private-key file appeared in the candidate list.

## Exclusions and final gate

Ignore probes confirmed exclusions for `.DS_Store`, `.env`, `.env.local`, virtual environments, Python caches, `node_modules`, compiled `dist` and generated `artifacts`. The explicit `.env.example` negation permits a future reviewed placeholder example; a verbose `git check-ignore` negation line must not be misread as an exclusion. No example file exists in the audited candidates.

A hypothetical `local-secret.pem` was not ignored in the initial rules. No such candidate was present. The reviewer recommended that the root integrator add private-key/container patterns before the baseline upload and verify them with the final ignore checks. Root owns ignore changes and the actual staged candidate set.

Before committing, root must inspect the explicit staged scope, credential findings, whitespace, documentation links, approved evaluation seal and repository visibility. After the authorized commit and push, root must verify the local/remote commit identity and zero ahead/behind state. No public license, package publication or hosted CI activation is part of this upload.

Root final preparation: private-key extensions `*.pem`, `*.key`, `*.p12` and `*.pfx` were added to the ignore rules and verified. The initial staged inventory contains 119 explicit project paths. `git diff --cached --check` first identified three whitespace-only lines in the historical HTML; root trimmed only those blank-line spaces and verified that substantive lines were unchanged. The staged whitespace check then passed, and all 16 approved seal hashes still matched. Native source, manifests, locks and approved labels were unchanged during GIT-01, so their preceding V0 acceptance results were not rerun or presented as a new test run.

One failure case: staging an ignored local environment with force would bypass this candidate audit. Use explicit intended paths and inspect the staged diff. Learning remains pending; the next small action is the authorized baseline commit/push and remote verification.
