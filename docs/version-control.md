# Cragkit version control

The user has authorized a private GitHub baseline and ongoing version control for completed, plan-aligned changes. After each accepted atomic change, commit and immediately push to the configured GitHub remote unless the user explicitly requests local-only work. Keep implementation, local verification, commit, push and hosted CI evidence distinct.

The initial branch is `main`. The private repository [vsuman00/Cragkit](https://github.com/vsuman00/Cragkit) exists with an HTTPS `origin` remote; its initial commit and push remain pending GIT-01 verification. Read [the tracker](../tasks/todo.md) for current state. Repository availability does not configure hosted CI. This task activates no workflows and publishes no packages.

## Make a scoped commit

For example, an accepted request-validation fix should include its owned source, regression tests and required documentation. Leave an unrelated draft untouched.

1. Read the applicable instructions, task acceptance and actual workspace. Inspect `git status --short`, `git diff` and `git diff --cached`. Preserve existing user-owned edits and inspect recent commit messages when history exists.
2. Identify the exact files belonging to the completed change. Run the actual focused checks recorded in [development.md](development.md), and record results and limitations. Documentation-only changes need link and consistency checks. Use [the local CI profile](ci.md) when the checkpoint requires broader acceptance.
3. Review credentials, private data and generated content before staging. Preserve approved corpus bytes and verify the seal when the change could affect sealed inputs. Keep environments, caches, build output and generated package artifacts out of Git through the reviewed ignore rules.
4. Stage explicit owned files. Inspect the complete staged diff and run `git diff --cached --check`. Confirm that every staged path belongs to the intended change.
5. Commit with a Conventional Commit subject such as `fix(contracts): reject invalid evidence spans` or `docs(development): record verified setup commands`. Explain a consequential contract or migration change in the body. The first baseline may record the existing reviewed V0 work together because it has no earlier project history.
6. Push the current branch immediately, then verify synchronization as described below. Report the commit hash, branch, remote and actual checks.

During coordinated work, one designated Git integrator owns the index, configuration, remotes, commits and pushes. Other peers report their owned files and evidence. Use short-lived feature branches when needed for independent changes or review; keep `main` as the initial integration branch. Honor remote branch protection. If a protected branch requires a pull request, push the branch and report the remaining merge gate; do not bypass protection or infer permission to send GitHub comments or messages.

## Verify the push

These commands are the workflow to run after a commit, not evidence that a push has occurred. `git push -u origin HEAD` establishes the current branch's upstream when needed:

```sh
git push -u origin HEAD
git fetch origin
git status --short --branch
git rev-list --left-right --count HEAD...@{upstream}
git rev-parse HEAD
```

Also compare the local commit with `git ls-remote --heads origin <current-branch>`, replacing the placeholder with the actual branch name. A synchronized branch has matching commit IDs and ahead/behind counts `0 0`. Report unrelated remaining workspace changes separately. A successful commit with a failed push is still unpublished to the remote; preserve it, diagnose the specific failure and retry only within the authorized workflow.

A failure case is staging the entire workspace while another peer has an unfinished edit: the commit would mix accepted and unaccepted work. Stop and correct the index scope without overwriting that edit. Do not reset or clean user work, force-push shared history, delete unrelated files or change repository visibility to make a check pass. Resolve a scope, credential or remote-protection blocker before the dependent Git action.

## Baseline contents

The initial upload may include reviewed native source, tests, contracts, locks, plans, project skills, evaluation sources and labels, review/seal records, reports, historical proposals and saved research papers. Historical documents remain labelled by their role and do not override the architecture. Local environments, dependency directories, caches, `.DS_Store`, compiled output and generated package archives remain excluded. The [GIT-01 upload review](../evaluation/reports/V0/GIT-01.md) records the actual inventory and audit; it is separate from root's final staged review and remote verification.

Optional exercise: identify the files belonging to one small accepted change, then explain how the staged diff and remote commit checks protect different parts of the workflow.
