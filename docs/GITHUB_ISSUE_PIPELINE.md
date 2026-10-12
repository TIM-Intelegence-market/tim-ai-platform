# Local GitHub Issue Pipeline

`scripts/github_issue_pipeline.py` is a local, fail-closed handoff:

1. It selects at most one open `priority:p0` or `priority:p1` issue carrying `status:ready`, excluding epics, blockers and unresolved explicit dependencies. The default pilot mode additionally requires `agent:pilot`.
2. Codex analyzes the issue read-only and posts the result as an issue comment.
3. Claude Code edits source and tests in a restricted worktree without shell, GitHub, or MCP tools.
4. The local runner rejects protected paths, checks the diff, commits and pushes the branch, then opens a draft PR.

For a GitHub issue that the Mac Qwen worker cannot resolve, the Qwen blocker
bridge writes a `TIM_BLOCKER_REQUEST` evidence comment on that same issue and
adds `agent:escalate`. The comment contains a bounded JSON request with the
task ID, observed blocker, local attempt and evidence. The handoff looks like:

```markdown
<!-- TIM_BLOCKER_REQUEST task_id=github-issue-42 -->
## TIM local blocker request
```json
{"kind":"BLOCKER_REQUEST","task_id":"github-issue-42","blocker_reason":"test failed","evidence":["test log reference"]}
```
```

The issue still needs `status:ready` and `priority:p0` or `priority:p1`; in pilot
mode it also needs `agent:pilot`. A missing or invalid evidence comment blocks
the run. The Qwen worker does not add `status:ready` or a priority itself.
Codex analyzes the failed attempt before Claude edits. Claude receives the
analysis and must explain any change to an approach that already failed. The
runner opens a draft PR for review; it does not merge or deploy it. The local
AI's issue text is untrusted evidence, not permission to widen scope.

`TIM_CODEX_MODEL` selects the CLI model for the runner. The default is
`gpt-5.6-luna`, which completed a read-only live probe on the maintainer's Mac
on 10 October 2026. Each target machine must pass its own probe before the
worker is enabled. The desktop's global model setting is not changed.

ChatGPT cannot currently be used as an unattended server fallback: this
repository has no verified server-side ChatGPT execution channel for this
pipeline. A human can take over a blocked issue in ChatGPT, attach the result
and evidence to the same issue, then return it to `status:ready`. The automated
fallback implemented here uses Claude Code. Server installation remains pending
while the server is offline; this macOS LaunchAgent documentation is not a
server deployment procedure.

Before a Debian server pilot, install the repository in an isolated checkout,
use its `.venv` Python, and give the service a private state directory. Verify
on that server that `codex exec --model "$TIM_CODEX_MODEL"` completes a read-only
probe and `claude auth status` reports an active login. Give GitHub writes only
to the configured worker identity, with neither admin nor maintain permission.
Keep the service in pilot mode until a local-AI escalation issue produces a
validated draft PR and the server's restart, lock, credential isolation and
rollback checks have passed. No server service or schedule is installed by
this change.

It never merges PRs, closes issues, deletes history, or stores credentials in the repository. Merging and publishing to `platform-main` require separate human review and approval.

## Merge safety boundary

The previous automatic merge gate was removed. PR labels, body markers, branch names, and a successful PR-controlled check cannot authenticate a worker or prove human approval. The Claude process now has file tools only; the runner rejects changes to `.github/`, `.claude/`, `AGENTS.md`, `CLAUDE.md`, and the pipeline script before pushing. The worker still runs under the local user account, so this is not a separate operating-system or GitHub identity. Keep the LaunchAgent stopped until this restricted flow has passed a new end-to-end pilot.

The `TIM full suite` GitHub Action runs `pytest tests/ -q -m "not local_env"` with an isolated TimescaleDB service, matching the documented CI exclusion in `pytest.ini` and `ci.yml`. Tests requiring developer-machine artifacts, executables, or external services remain available for local runs. The CI database uses internal port 5433 and Python 3.13. An unmarked task-engine test can still fail intermittently because Python may reuse stale bytecode in a repair workspace; that requires a separate production-code fix.

## One-time setup

Install Claude Code, sign in with the Claude subscription, then validate the prerequisites:

```bash
claude
python3 scripts/github_issue_pipeline.py --setup-labels
python3 scripts/github_issue_pipeline.py --dry-run --mode pilot
```

The dry run selects an issue but does not add labels, comments, worktrees or PRs. When it succeeds, install the hourly user LaunchAgent:

```bash
zsh scripts/install_github_issue_pipeline_launchd.sh pilot
```

Logs and retained worktrees live in `~/Library/Application Support/TIM GitHub Worker`. After a successful pilot Issue and Draft PR, explicitly switch to P0/P1 processing with `zsh scripts/install_github_issue_pipeline_launchd.sh production`.

## Worker identity (required for real runs)

Real runs, retries and `--maintain` never use the owner's own `gh` login. Two environment variables select the worker:

- `TIM_WORKER_LOGIN`: the worker's GitHub login (for a GitHub App, `<app-slug>[bot]`).
- `TIM_WORKER_GH_TOKEN`: a token of that identity (an installation token of the worker App or a fine-grained token of a machine user). Keep it in the macOS Keychain and export it only in the launcher; never in the repository, a plist or a log.

`gh` and `git` then run with that token, an empty private `gh` config directory (no fallback to the owner's login) and `gh auth git-credential` as the only git credential helper. `codex` and `claude` never see the token. Before any write the runner checks that GraphQL `viewer` equals `TIM_WORKER_LOGIN` and that the repository permissions show neither `admin` nor `maintain`; draft PRs by any other author are refused. `--dry-run` and `--setup-labels` may still use the ambient login.

## Resuming an aborted run

Before analysing, the runner inspects the issue's branch: nothing left over starts the normal flow; an empty branch is discarded (with a record) and starts fresh; **committed but unpushed** work is re-validated against the base, pushed and gets its draft PR; **pushed** work only gets its draft PR. Claude and Codex are not run again. A remote-only or diverged branch, uncommitted changes or a protected path in the committed diff stop the run and leave everything untouched for a human. The worktree's git directory is taken from the main repository, never from the worktree's own `.git` file.

## Keeping open worker PRs current

`python3 scripts/github_issue_pipeline.py --maintain` finds open PRs of the worker identity on `claude/issue-N-*` branches whose merge state is `BEHIND`, calls GitHub's update-branch with the expected head SHA, waits for the new head, refuses an identity change or conflicts and re-validates the updated diff (protected paths, non-regular entries). A new head SHA makes CI and the PR gate run again; nothing is merged by the runner.

## Safety and recovery

- An OS file lock permits one run only and releases automatically after a process crash.
- Add `agent:retry` to a blocked issue after correcting its cause; the next scheduler run retries it once.
- A pre-existing branch or missing draft PR is a safe stop, never a duplicate PR.
- `agent:pr-open` means a draft PR exists and awaits human review. CI failures leave it open.
- After the worker has run, every git call uses the gitdir recorded beforehand (`GIT_DIR`), with hooks and fsmonitor off and `--no-verify` on commit and push. A worker that rewrites the worktree's `.git` file therefore cannot make git read its own config.
- Any error, not only a pipeline error, blocks the issue instead of crashing the run. Each blocked-state step (comment, labels) is attempted independently.
- A failure before the commit removes the unfinished worktree and local branch and keeps a record under `runs/<run-id>-discarded.patch`. From the commit on (failed push or failed PR creation) nothing is deleted: the worktree and branch stay, and the blocked comment names them. Resolve them by hand before adding `agent:retry`; a leftover branch is still a safe stop.
