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

## Tools, sandbox and skills

Research and ranking: <https://claude.ai/artifact/FR5gJcqxMhPp7fo9J8av5r>.

**Test sandbox.** `pytest` runs code the model wrote, so every test run goes through
`src/local_first/sandbox_runner.py`. On macOS it wraps the command in `sandbox-exec` with a
generated Seatbelt profile: credential folders (`~/.config/gh-tim-mac-worker`, `~/.config/gh`,
`~/.ssh`, Keychains, Codex and Claude logins, cloud CLIs) are unreadable, Keychain services
are blocked, `launchctl`, `open`, `osascript` and `security` cannot be started, writes are
limited to a scratch folder (the worktree stays read-only, because the worker later runs code
from it outside the sandbox), and only loopback network is allowed, except Ollama's port. The process gets a minimal environment with a throwaway
`HOME`. `TIM_TEST_SANDBOX=required` (set by the issue runner and the LaunchAgent installer)
blocks the task when no sandbox is available; `auto` sandboxes when possible; `off` only drops
the environment. Token-shaped strings are redacted from test output before it reaches logs or
helper prompts.

**Constrained output and edits.** The one-shot request passes a JSON schema to Ollama's
`format`, so only well-formed proposals with allowlisted paths can be decoded. Existing files
can be changed with `edits` (`search`/`replace` pairs); each search text must occur exactly once
in the snapshot the model saw. New files still need full `content`.

**Tool loop.** With `TIM_QWEN_TOOL_LOOP=1` (default for the issue runner and the installer;
switch off with `--disable-qwen-tool-loop` or `TIM_QWEN_TOOL_LOOP=0`) Qwen first works through
`/api/chat` tool calls: `list_dir`, `read_file` and `search_code` (read-only, `src/`, `tests/`,
`docs/`), `run_required_tests` (sandboxed, at most twice), `check_patch` and `submit_patch`.
No tool writes files or takes a shell command, and the submitted patch faces the same gates.
The loop is capped at 12 steps and 10 minutes. Tool calls that Qwen prints as text are parsed
as well, because Ollama's Qwen 3.5 parser is not reliable yet. If the loop ends without a
patch, the worker makes its normal one-shot request. Each result records `tool_loop`
statistics (native, text-parsed and invalid calls, calls per tool, how the loop ended) and
the `test_sandbox` that ran.

**Skills.** `config/qwen-skills/<name>/SKILL.md` holds TIM guidance in the Agent Skills format.
`src/local_first/qwen_skills.py` adds the skills whose `metadata.tim-applies-to` matches
(`always`, `tool-loop` or path globs) to the prompt as text; nothing in a skill is executed.
`config/` is a locked path for worker PRs, so the worker cannot rewrite its own guidance.
Issue contracts may not list `src/local_first/` or `src/llm/` either, so the worker cannot
patch its own gates, sandbox or tool loop.

The local acceptance gate rejects a result whose passing test run was not sandboxed while
`TIM_TEST_SANDBOX=required`. A task that hits the 30-minute limit has its whole process group
stopped. The Seatbelt profile has not yet been tried on the Mac mini; if it blocks Python, the
result names the failed probe.

After pulling these changes on the Mac, rerun the installer so the LaunchAgent gets
`TIM_TEST_SANDBOX` and `TIM_QWEN_TOOL_LOOP`, then restart it.
