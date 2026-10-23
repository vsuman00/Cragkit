# V0 local CI profile

The V0 check entrypoint is `python3 tools/check_v0.py`, run from a checkout with Python 3.14, Node 26.5 or later in the declared 26.x range, npm and uv available. Local compatibility evidence is limited to the exact versions recorded in [development.md](development.md). The private [GitHub repository](https://github.com/vsuman00/Cragkit) and local `main` branch were created after V0 acceptance. Hosted CI and branch protection remain unconfigured and unrun; repository creation alone does not establish either.

The runner installs from the frozen Python and npm locks, then runs typing, Python/tool tests, TypeScript tests/build, schema drift, native request/result/embedding and vector-generation/dense parity, approved development-corpus checks, sealed-input integrity and clean package verification. The 15 stages execute one subprocess at a time and stops at the first failed or timed-out stage. Failed checks return nonzero; a success summary appears only after every stage passes.

```sh
python3 tools/check_v0.py
```

Generated archives and verification reports go under ignored `artifacts/V0/`. To choose a different task-owned output directory:

```sh
python3 tools/check_v0.py --artifacts-dir /tmp/cragkit-v0-artifacts
```

The artifact verifier builds a Python wheel and source distribution plus an npm tarball, inspects their contents, and checks fresh installations outside the source checkout. Dependency installation may access package registries. Import checks block networking and exclude optional database/model/framework packages. These are local package checks, not registry publication or live-provider evidence. Import timings and memory observations are scoped process samples, not retrieval performance or universal hardware budgets.

Routine corpus validation reads development labels only. The seal checker hashes the approved held-out input bytes without interpreting labels or scoring a model. The initial human review and seal are recorded in [the review record](../evaluation/review/seal.json). A changed sealed input fails integrity verification; corrections require a new reviewed revision rather than silent relabeling.

For example, corrupting a sealed source file makes the integrity stage fail before package acceptance. A source file that hashes correctly may still contain false information; the checksum does not establish source truth. An optional exercise is to inspect the runner's stage order and identify which command would reject a request-schema change without updated fixtures.

## Future hosted job

When implementing hosted CI, create one job on pull requests and pushes using a clean supported runner. Check out the code, install the recorded Python/Node/uv toolchain, and run the same entrypoint. Keep test processes serial and exclude models, provider credentials and database services from V0. Retain the archives and acceptance report as job artifacts, without publishing packages. Configure branch protection separately when the hosted job has actually been observed to pass.

Cross-platform execution, hosted runner behavior and branch protection remain unvalidated until that real job runs. The local job definition is documented here rather than claiming an unavailable hosted CI result.
