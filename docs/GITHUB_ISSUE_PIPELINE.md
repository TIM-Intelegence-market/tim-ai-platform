# Local GitHub Issue Pipeline

`scripts/github_issue_pipeline.py` is a local, fail-closed handoff:

1. It selects at most one open `priority:p0` or `priority:p1` issue carrying `status:ready`, excluding epics, blockers and unresolved explicit dependencies. The default pilot mode additionally requires `agent:pilot`.
2. Codex analyzes the issue read-only and posts the result as an issue comment.
3. Claude Code implements only that analysis in a fresh worktree and opens a draft PR.
4. On a later scheduler run, the merge gate examines pipeline PRs and squash-merges only when every rule below passes.

It never deletes history or stores credentials in the repository. A successful merge may close the linked issue through `Closes #N`.

## Automatic merge rules

The PR must carry `agent:auto-merge`, the `TIM_CODEX_CLAUDE_RUN_V1` marker and a matching `Closes #N` reference. Its branch must be `claude/issue-N-*`, its base must be the current default branch, and GitHub must report `MERGEABLE` and `CLEAN`. Every reported status check must succeed, including the named `TIM full suite` check. The merge command pins the reviewed head SHA with `--match-head-commit`; a new push requires a fresh check. No administrator bypass or GitHub auto-merge is used. Existing draft PRs are not enrolled automatically.

The `TIM full suite` GitHub Action runs `pytest -q` with the local TimescaleDB service. Known baseline failures or missing CI availability keep the PR open. To run the merge gate alone: `python3 scripts/github_issue_pipeline.py --merge-ready`.

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

- The local directory lock permits one run only.
- Add `agent:retry` to a blocked issue after correcting its cause; the next scheduler run retries it once.
- A pre-existing branch or missing draft PR is a safe stop, never a duplicate PR.
- `agent:pr-open` means a draft PR exists. Its `agent:auto-merge` label enrolls it in the merge gate; failed or missing checks leave it open.
