# V0 local CI profile

The V0 check entrypoint is `python3 tools/check_core_pipeline.py`, run from a checkout with Python 3.14, Node 26.5 or later in the declared 26.x range, npm and uv available. Local compatibility evidence is limited to the exact versions recorded in [development.md](development.md). The private [GitHub repository](https://github.com/vsuman00/Cragkit) and local `main` branch were created after V0 acceptance. The later manual candidate workflow has [one verified V6 run](../evaluation/reports/V6/V6-06-ci.md). That result does not establish branch protection or authorize another run or publication.

The runner installs from the frozen Python and npm locks, verifies the explicit pinned tokenizer asset, then runs typing, Python/tool tests, TypeScript tests/build, schema drift, native execution/planning/corrective/event and request/result/embedding and vector-generation/dense/identifier-fusion/hybrid/reranker/context/packing/assessment/evidence-pipeline parity, approved development-corpus checks, sealed-input integrity and clean package verification. The 27 stages execute one subprocess at a time and stop at the first failed or timed-out stage. Failed checks return nonzero; a success summary appears only after every stage passes.

```sh
python3 tools/check_core_pipeline.py
```

Generated archives and verification reports go under ignored `artifacts/V0/`. To choose a different task-owned output directory:

```sh
python3 tools/check_core_pipeline.py --artifacts-dir /tmp/cragkit-v0-artifacts
```

The artifact verifier builds a Python wheel and source distribution plus an npm tarball, inspects their contents, and checks fresh installations outside the source checkout. Dependency installation may access package registries. Import checks block networking and exclude optional database/model/framework packages. These are local package checks, not registry publication or live-provider evidence. Import timings and memory observations are scoped process samples, not retrieval performance or universal hardware budgets.

Routine corpus validation reads development labels only. The seal checker hashes the approved held-out input bytes without interpreting labels or scoring a model. The initial human review and seal are recorded in [the review record](../evaluation/review/seal.json). A changed sealed input fails integrity verification; corrections require a new reviewed revision rather than silent relabeling.

For example, corrupting a sealed source file makes the integrity stage fail before package acceptance. A source file that hashes correctly may still contain false information; the checksum does not establish source truth. An optional exercise is to inspect the runner's stage order and identify which command would reject a request-schema change without updated fixtures.

## Historical hosted-job proposal

The original V0 proposal was one job on pull requests and pushes. The accepted V6 implementation is manual-only to control private-runner cost. It uses the recorded Python/Node/uv toolchain, serial checks and no provider/database credentials or persistent service, then retains candidate archives without publishing packages. See [the current workflow](../.github/workflows/candidate-validation.yml) and [release guide](releasing.md). Branch protection remains a separate configuration outcome.

Hosted evidence covers the recorded macOS ARM64 tuple. Other operating systems and architectures lack release acceptance evidence; branch protection is not established by the passing job.

## V4 optional SDK checkpoint

`python3 tools/check_sdk_packages.py --artifacts-dir artifacts/V4/acceptance` runs the 27 core stages and seven optional SDK stages serially. Optional SDK installs have their own frozen locks; they do not change the default core import/dependency gate. The final stage builds and installs optional adapter archives outside the checkout, checks SDK versions/integrities and reruns the real SDK tests against installed products. Database acceptance remains an explicit separate run with private configuration and test-write authorization. A passing local V4 command does not establish hosted CI or registry publication.
