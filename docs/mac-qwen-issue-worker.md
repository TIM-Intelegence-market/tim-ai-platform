# Mac Qwen GitHub issue worker

`scripts/run_mac_qwen_issue.py` handles one GitHub issue at a time. The Mac is
TIM's fallback system while the server Qwen 30B model is being built. The
worker uses the isolated `apoman74-art` GitHub login and stops if that login
has Admin or Maintain permissions.

An issue must be open and labelled `agent:qwen-ready`, `status:ready`, and
`priority:p0` or `priority:p1`. Epics, blocked issues, issues with an open PR,
and issues blocked by another open issue are excluded. The body must contain a
fenced contract:

````text
```json TIM_QWEN_TASK_V1
{
  "task_id": "github-issue-123",
  "issue_number": 123,
  "risk": "A3",
  "sandboxed": true,
  "objective": "Describe one bounded code change",
  "allowed_paths": ["src/example.py"],
  "tests": ["tests/test_example.py"]
}
```
````

Only canonical Python files under `src/` and test modules under `tests/` are
accepted; database, incident, market-data, orderflow and paper-trading paths
are outside this A3 pilot contract. The
worker creates a fresh worktree from `platform-main`, runs local Qwen through
the existing patch and test gates, and uses Codex CLI as an opt-in patch
fallback when Qwen is blocked, then Claude Code CLI when Codex fails or its
patch is rejected. Both receive a sanitized snapshot without GitHub credential
environment variables, and Claude runs without tools. All providers face the
same file allowlist, hashes, syntax check, and tests. An accepted local result is then
committed by the worker account and opened as a normal PR linked to the issue.

Run the read-only selection check first:

```sh
.venv/bin/python scripts/run_mac_qwen_issue.py --pilot-issue 123 --dry-run
```

Run the one-issue pilot and wait for GitHub's merge gate:

```sh
.venv/bin/python scripts/run_mac_qwen_issue.py --pilot-issue 123 --merge
```

Without `--merge`, the worker stops after opening the PR. With `--merge`, it
waits for GitHub to report the exact worker PR head as mergeable, then requests
a squash merge. GitHub's branch ruleset remains authoritative. A conflict,
changed PR head, failed local acceptance, or expired wait leaves the PR or
worktree for inspection. Local runtime evidence in `.tim/` never enters a
commit. `--no-codex-fallback` and `--no-claude-fallback` switch either helper
off for a run.

The existing Mac LaunchAgent can poll this runner while its local queues are
idle. Enable it only with the dedicated GitHub login, and initially restrict
it to one issue using `--enable-github-intake --github-pilot-issue NUMBER` in
`scripts/install_local_qwen_launchd.py`. Add `--github-merge` only when the
worker should request a merge after GitHub's required checks. The poll interval
is five minutes and the service keeps one task in progress at a time.

The current worker PAT can write issues, branches and PRs, but cannot read the
Checks or commit-status APIs. The worker therefore uses the PR merge state and
GitHub's enforced ruleset for the final gate. Read-only CI diagnosis can use a
separate account with Checks read access.
