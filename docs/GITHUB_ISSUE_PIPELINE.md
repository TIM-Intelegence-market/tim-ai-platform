# Local GitHub Issue Pipeline

`scripts/github_issue_pipeline.py` is a local, fail-closed handoff:

1. It selects at most one open `priority:p0` or `priority:p1` issue carrying `status:ready`, excluding epics, blockers and unresolved explicit dependencies. The default pilot mode additionally requires `agent:pilot`.
2. Codex analyzes the issue read-only and posts the result as an issue comment.
3. Claude Code edits source and tests in a restricted worktree without shell, GitHub, or MCP tools.
4. The local runner rejects protected paths, checks the diff, commits and pushes the branch, then opens a draft PR.

It never merges PRs, closes issues, deletes history, or stores credentials in the repository. Merging and publishing to `platform-main` require separate human review and approval.

## Merge safety boundary

The previous automatic merge gate was removed. PR labels, body markers, branch names, and a successful PR-controlled check cannot authenticate a worker or prove human approval. The Claude process now has file tools only; the runner rejects changes to `.github/`, `.claude/`, `AGENTS.md`, `CLAUDE.md`, and the pipeline script before pushing. The worker still runs under the local user account, so this is not a separate operating-system or GitHub identity. Keep the LaunchAgent stopped until this restricted flow has passed a new end-to-end pilot.

The `TIM full suite` GitHub Action runs `pytest -q` with an isolated TimescaleDB service. It remains red until external-service and missing-artifact test dependencies are addressed explicitly; tests are not silently skipped. The CI database now uses internal port 5433 and Python 3.13.

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

## Safety and recovery

- An OS file lock permits one run only and releases automatically after a process crash.
- Add `agent:retry` to a blocked issue after correcting its cause; the next scheduler run retries it once.
- A pre-existing branch or missing draft PR is a safe stop, never a duplicate PR.
- `agent:pr-open` means a draft PR exists and awaits human review. CI failures leave it open.
