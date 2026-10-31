# Releasing Cragkit as an open-source library

For example, a Python application installs a Cragkit wheel and imports it in its own process. A Node application installs the npm package and runs native JavaScript. Publishing those packages makes them downloadable. Hosting an application that uses them is a separate operation.

This guide explains the release path while [V6](../tasks/versions/V6-release.md) is still in progress. The [tracker](../tasks/todo.md) records actual acceptance. Commands marked **planned** are instructions for a future authorized release, not commands executed by writing this guide.

## Understand the names and versions

| Label | Meaning for this project |
| --- | --- |
| V0 through V6 | Internal implementation milestones, not published package versions. |
| `0.0.0` | Current provisional package metadata. Local archives with this version do not establish a registry release. |
| Python `1.0.0rc1`, npm `1.0.0-rc.1` | Proposed release-candidate spellings for the same release stage. Consumers deliberately try the candidate while release acceptance is completed. |
| `1.0.0` | Proposed stable release after all required gates and publication authorization. It does not promise every platform, deployment or future API. |

The three distribution names are currently `cragkit`, `cragkit-langchain` and `cragkit-mcp` in both ecosystems. Import names differ: Python uses `cragkit_langchain` and `cragkit_mcp`; Node uses the distribution names. Before publishing, verify account ownership and accepted names on each registry. A name in a local manifest does not reserve it. PyPI supports a pending trusted publisher for creating a new project, but that configuration itself does not reserve the name. See [PyPI project creation](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

The user selected MIT. Add the correct copyright holder/year, ship the license and synchronize package metadata. MIT permits reuse under its notice conditions; it does not replace dependency or model notices. Preserve those separately. The authoritative text is [OSI's MIT license](https://opensource.org/license/mit).

## 1. Prepare a release checkout without losing ongoing work

Keep the original working directory and its unrelated edits intact. First identify the reviewed commit containing the intended release changes. In the original checkout, these **planned** commands create another checkout of that commit:

```sh
git status --short
git worktree add --detach ../Cragkit-release <reviewed-commit>
git -C ../Cragkit-release status --short
git -C ../Cragkit-release rev-parse HEAD
```

Replace `<reviewed-commit>` before execution. Choose a new destination. Do not copy unreviewed dirty files into the candidate or use reset/clean to make the original directory appear clean. The release checkout should contain the accepted source; environments and generated archives remain local. Follow [the scoped Git procedure](version-control.md) for commits and pushes. Creating a worktree does not publish packages.

## 2. Fix the release contract before measuring it

Confirm runtime constraints from the manifests: Python `>=3.14,<3.15` and Node `>=26.5.0 <27` are the present declarations. Wider support requires evidence. Choose the candidate version, synchronize optional packages' core dependency versions, review public names and remove npm's current `private: true` only when publication is authorized. Retain strict runtime/dependency bounds unless a separately tested change expands them.

Freeze quality/resource thresholds and benchmark configuration before held-out evaluation. Run the ordered V6 gates: retrieval evaluation, resource tests, boundary/artifact audit, independent developer trial, exact package/CI checks, migration rehearsal, publication and maintenance handoff. A missing participant or required measurement stays pending. [Coverage inventory](../evaluation/release/V6-coverage.json) locates evidence owners; it is not a pass report.

## 3. Build and inspect local distribution artifacts

A wheel is Python's installable archive; an sdist is its source archive. npm uses a tarball containing the selected published files. Build outside any publishing job first. [PyPA's packaging tutorial](https://packaging.python.org/en/latest/tutorials/packaging-projects/) explains these formats and the build/upload separation.

The following existing repository command rebuilds and checks the core archives in isolated environments. It is **planned for the new candidate**; prior runs are recorded in [development.md](development.md) and [V5 installation evidence](../evaluation/reports/V5/V5-08.md):

```sh
python3 tools/check_artifacts.py --output-dir artifacts/V6/candidate-core
```

Use a new output directory and inspect the tool's actual options before execution. It can install dependencies and access registries. Optional framework/MCP profiles need their own acceptance; core success does not validate them. The final integrator selects the existing combined checks and records each actual command serially.

For a small manual preview, these existing npm scripts/CLI operations are also **planned for the candidate**:

```sh
npm --prefix packages/typescript run build
npm --prefix packages/typescript pack --dry-run
```

Inspect archive contents, metadata, exported files, license/notices and dependency boundaries. Exclude credentials, connection files, private logs/source text and model assets. Core imports must not create a connection, fetch weights or migrate a database. An accidental secret requires stopping publication and correcting the artifact, not merely hiding its listing. [npm publish documentation](https://docs.npmjs.com/cli/commands/npm-publish/) describes tarball publication and dry runs.

## 4. Test the exact files a consumer receives

Record each archive's SHA-256 and the source commit. On this macOS development machine the **planned** check is:

```sh
shasum -a 256 <candidate-wheel> <candidate-sdist> <candidate-npm-tarball>
```

Replace all placeholders. A digest identifies bytes; it does not prove their quality. Record hashes before upload and compare them with downloaded release artifacts afterward.

Install the actual wheel/tarball into a fresh environment outside the checkout. For illustration, these **planned commands** require the selected interpreter, pip/npm and absolute artifact paths:

```sh
python3.14 -m venv <fresh-python-environment>
<fresh-python-environment>/bin/python -m pip install <absolute-candidate-wheel>
<fresh-python-environment>/bin/python -c 'import cragkit; print(cragkit.__file__)'
npm --prefix <fresh-node-project> install <absolute-candidate-npm-tarball>
```

Use a fresh Node project with a reviewed manifest. Verify imported modules resolve from the installed environment, then run documented ingestion, source-linked retrieval and partial-result handling. Test applicable optional extras separately. A source-checkout test can accidentally import local files and miss a missing export in an archive. The repository's artifact probes check installed provenance; manual examples supplement them.

## 5. Add CI before granting registry access

Local checks and hosted CI are different evidence. No successful hosted run follows from a local command or a proposed workflow. The integrator must create and inspect actual workflows before this guide can name their paths or results.

Separate build/test jobs from the publish job. Give ordinary jobs read-only repository permissions. Restrict publication to the reviewed release identity and an approved environment. Pin third-party actions to reviewed full commit SHAs and pin build tools/dependencies. Do not expose publication authority to untrusted pull-request code. GitHub explains these controls in [workflow security hardening](https://docs.github.com/en/actions/security-for-github-actions/security-guides/security-hardening-for-github-actions).

Trusted publishing uses a short-lived OIDC identity instead of a stored long-lived registry token. Configure the registry's repository, actual workflow filename and environment to match the reviewed publisher. Grant `id-token: write` only to the publishing job; this permission permits obtaining an identity token, not arbitrary repository writes. See [GitHub OIDC reference](https://docs.github.com/en/actions/reference/security/oidc) and [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

For npm, follow the current supported CI-provider/CLI requirements and package settings in [npm trusted publishers](https://docs.npmjs.com/trusted-publishers/). npm automatically adds provenance for supported trusted-publishing runs. Bootstrap name ownership and any first manual upload separately if required; never assume PyPI and npm have the same setup. Record the selected bootstrap method before using credentials.

## 6. Publish only after the concrete candidate is approved

First publication requires explicit manual authorization for the exact registry, names, versions and artifacts. A Git push or approval of MIT does not supply it. Show the evidence bundle and unresolved limitations before requesting that authorization.

For npm, this is a **planned publication shape**, not permission to execute:

```sh
npm publish <approved-npm-tarball> --tag next --access public
```

Use `next` for the release candidate; approve the stable distribution-tag policy separately. Publish optional packages only after the exact core dependency is available. Upload the reviewed Python wheel/sdist through the configured PyPI trusted-publisher job. Do not rebuild different bytes between acceptance and upload. npm name/version pairs cannot be reused after publication; [npm publish](https://docs.npmjs.com/cli/commands/npm-publish/) documents that restriction.

Fetch the published versions into fresh environments, compare identity/hash metadata and repeat the source-linked smoke query. Record registry URLs and results separately from local acceptance. If publication fails partway through the six distributions, report which names/versions exist and stop dependent promotion until reconciled.

## 7. Deploy a consuming application only when needed

A library release needs no always-running Cragkit server. An application may host its own API or MCP host using the optional packages. It owns authentication, trusted scope, database credentials, provider policy, cancellation and final answers. Follow [V5 operations](v5-operations.md) for supported backend profiles and ownership.

Provision databases and run explicit reviewed migrations through an administrative step. Runtime imports must not migrate. Rehearse backup, interrupted upgrades and rollback on disposable data before an application upgrade; restoring data must not restore revoked permissions. Keep infrastructure costs, deployment authorization and live-provider disclosure separate from publishing downloadable libraries.

## 8. Maintain the published contract

Publish quickstarts, supported versions, optional-dependency choices, known limitations and support/reporting instructions alongside the release notes. A useful bug report includes package/runtime/backend versions, a small redacted reproduction and the expected source-linked result. Preserve secrets and private source text.

Failure case: `1.0.0` imports in the checkout but its wheel omits a required module. Reproduce from the downloaded wheel, add a regression, fix and test a new candidate, then publish a corrective version such as `1.0.1`. Record affected versions and migration advice. Do not silently replace the original release or claim an unrun fix works.

Exercise: explain which evidence would change if an archive hash changed after tests passed. Then identify the one step that grants registry publication authority. Learning remains unassessed.
