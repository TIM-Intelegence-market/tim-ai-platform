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

## Preparing large issues for the worker

Check for existing child issues before splitting an epic. Prepare one complete
`TIM_QWEN_TASK_V1` per executable child, validate it with `build_task` and
`issue_triage._bound_task` against the current repository, and verify that the
requested changes fit the patch executor's six-file change limit. Reading
additional test modules does not authorize changing them. Tests must be explicit
and dependencies must use `Depends on #N` lines so the selector waits for them.

The child gets `agent:qwen-ready` (or `agent:qwen-hard` when the validated context
requires the server), `status:ready` and a P0/P1 priority. The parent keeps its
real acceptance status and gains `agent:split` plus links to its executable
children. Remove obsolete `agent:not-suitable` only after that mapping exists.
The generated Priority Board is an `agent:coordination` overview, never a code
task. Server acceptance evaluators can be isolated code tasks; real server,
network, backup and cutover operations remain separate from those evaluators.

## Hard issues on the server model

### Prefer the server and keep it warm

Set `TIM_QWEN_SERVER_PREFERRED=1` and `TIM_QWEN_SERVER_KEEP_WARM=1` in the Mac
worker LaunchAgent environment, alongside the existing `TIM_QWEN_HARD_URL` and
`TIM_QWEN_HARD_MODEL`. The installer preserves these settings from its environment.

Small ready issues then use the installed server model too. The intake no longer
depends on the Mac model being available while the server answers, and checks for
new work every 30 seconds instead of five minutes. Hard issues still wait for the
server on an outage; small issues may use the Mac fallback. File limits and test
sandbox requirements remain those of each original issue contract.

Server implementation and review requests use `keep_alive=-1`. One background
thread in the coordinator also preloads the model with an empty request on startup
and every five minutes, retrying after one minute on transport errors. It does not
generate tokens or download models. Its context and batch size match the server
worker, avoiding configuration changes between warmup, tool loop and review.
It logs `TIM_SERVER_MODEL=WARM` or `UNAVAILABLE` independently of a long-running
issue child. Restarting Ollama still requires reloading the model; the next warmup
or real request performs that load.

Processing remains serial with the current `OLLAMA_NUM_PARALLEL=1`. On the checked
Xeon E3-1270 v6, Ollama has a 300% CPU quota, CPU affinity `2-3,6-7` and a 28 GiB
cgroup memory limit, despite the host having 62 GiB RAM. The warm 64k-context model
occupies about 25 GB and can bring its cgroup close to that limit. More simultaneous
contexts need measured throughput and memory headroom before changing this setting.
The resource isolation for PostgreSQL and TIM runtime remains in place.

Useful pauses include local CI/test contention, an empty eligible queue, dependency
waits and unavailable transport. Warming prevents avoidable model unloads during
these pauses; it does not manufacture tasks or CPU load to make usage appear high.

See [Ollama's residency and concurrency documentation](https://github.com/ollama/ollama/blob/main/docs/faq.mdx).

tim-server holds `qwen3-coder:30b` (CPU only, 62 GB RAM). The Mac stays the
only machine with GitHub access; the server only sees prompt in, text out.
A LaunchAgent on the Mac (`com.tim.server-ollama-tunnel`) keeps an SSH tunnel
from `127.0.0.1:11435` to the server's Ollama. The worker reads two variables:

- `TIM_QWEN_HARD_URL`: loopback URL of the tunnel, e.g. `http://127.0.0.1:11435`.
  Anything that is not loopback is ignored. Unset means no server model.
- `TIM_QWEN_HARD_MODEL`: defaults to `qwen3-coder:30b`.

An issue labelled `agent:qwen-hard` plus `status:ready` is picked like a
`agent:qwen-ready` issue, but its local Qwen step runs against the server model
with a 900 s request timeout. When the tunnel does not answer or the model is
not installed there, the issue waits for the server without spending a repair
attempt. This also holds when the server disappears between selection and
starting the model process. Earlier genuine failures remain in the ledger.
Codex and Claude fallbacks after a started model attempt are unchanged. The
cold start of the 30B model takes about 2.5 min.

Before any PR is opened, the server model reads the final diff once and writes
up to five lines (`OK` or `PROBLEM` plus findings) into the PR body under
"Reviewer (advisory, …)". That verdict never blocks the PR and is skipped when
the server is unreachable.

## Two workers: Mac easy, server hard

Since 25.10.2026 a second worker can run on tim-core-01 beside the CI runner. `TIM_WORKER_LANE`
splits the issues between them (default `all`: one worker takes both, as before):

| Lane | Machine | Takes | Branches | Triage |
|---|---|---|---|---|
| `easy` | Mac | `agent:qwen-ready` without `agent:qwen-hard` | `codex/issue-N-qwen` | yes |
| `hard` | tim-core-01 | `agent:qwen-hard` | `codex/issue-N-qwen-hard` | never (needs Claude Code) |

Each worker merges, updates or retires only the PRs of its own lane, and neither starts an issue that
has an open worker PR of the other lane. The issue ledger stays per machine, which is safe because the
lanes do not overlap. Never run two workers with lane `all`, or `all` beside another lane.

On the Mac, set `TIM_WORKER_LANE=easy` in the LaunchAgent environment and remove
`TIM_QWEN_SERVER_PREFERRED`, `TIM_QWEN_SERVER_KEEP_WARM` and `TIM_QWEN_HARD_URL`, then rerun the
installer. Triage then still labels large-file issues `agent:qwen-hard` for the server, without a
tunnel. The server worker reaches Ollama directly on `127.0.0.1:11434`, runs model-written tests in
bubblewrap and has no Codex or Claude fallback. Setup and limits: `ops/linux/README.md`.

## Automatic chain (no manual labelling)

Since the automation change the LaunchAgent needs no manual step per issue. Every five minutes,
while the local queues are idle and Ollama answers, the supervisor runs the issue runner with
`--merge --triage --self-update` (set `TIM_GITHUB_TRIAGE=0` or `TIM_WORKER_SELF_UPDATE=0` in the
LaunchAgent environment to switch either off; a `--github-pilot-issue` never triages):

1. **Self-update.** The runner fetches `platform-main`. If the worker checkout is clean and behind,
   it fast-forwards (detached) and exits with code 3; the supervisor exits and launchd restarts it
   on the new code. A dirty or diverged checkout is left alone.
2. **Own PRs.** Open worker PRs (`codex/issue-N-qwen`) are merged when GitHub reports `CLEAN`,
   brought up to date when `BEHIND`, and closed with their branch when `DIRTY` or older than six
   hours. Their issues are not started again while the PR is open.
3. **Work.** The next ready issue is processed as above. Leftovers of an earlier failed attempt
   (worktree, local and remote branch) are removed first; their `.tim` evidence is copied to
   `runs/issue-N-before-attempt-K` in the state folder.
4. **Triage.** Only when nothing is ready: Claude Code (read-only: `Read`, `Grep`, `Glob`, no MCP,
   no credentials, `--restricted`) reads one open issue and the repository and answers `ready` or
   `skip`. A `ready` answer must pass the same `build_task` validation; the worker then posts the
   contract as its own comment (marker `TIM_QWEN_TRIAGE_V1`) and adds `agent:qwen-ready`,
   `status:ready` and `priority:p0|p1`. A `skip` gets a one-line reason and `agent:not-suitable`.
   Only issues from trusted authors are triaged (`uezeyiraydin-cell`, `apoman74-art`, plus
   `TIM_TRIAGE_TRUSTED_AUTHORS`); epics, server, observe-only, waiting and blocked issues are never
   triaged. Contracts are read from the issue body or from a worker comment, never from another
   person's comment.
   A third answer, `split`, is for issues that bundle separable items: the worker opens up to six
   child issues `[Teil von #N] …` with a validated contract in their body and the ready labels,
   comments the list on the parent and labels it `agent:split`. Items that need a person stay on
   the parent. A parent version is split at most once, even if a run stops halfway.

**No endless repetition.** `issue-ledger.json` in the state folder records every triage call and
attempt. Each issue version is triaged at most twice, at most 30 triage calls run per day, and each
contract gets at most two attempts. After the second failure (or at once for an invalid contract)
the issue gets `agent:blocked` and a comment with the last errors, and the queue moves on to the
next issue. Removing `agent:blocked` grants two new attempts; removing `agent:not-suitable` asks for
a new triage. While Ollama is unreachable no attempt starts, so an outage does not use up retries.

The LaunchAgent itself has `RunAtLoad` and `KeepAlive`, so it starts at login and after a crash or
an update exit. LaunchAgents start only after the user logs in; on a Mac mini that should restart
unattended, enable automatic login.

## Tools, sandbox and skills

Research and ranking: <https://claude.ai/artifact/FR5gJcqxMhPp7fo9J8av5r>.

**Test sandbox.** `pytest` runs code the model wrote, so every test run goes through
`src/local_first/sandbox_runner.py`. On macOS it wraps the command in `sandbox-exec` with a
generated Seatbelt profile (Linux: next paragraph): credential folders (`~/.config/gh-tim-mac-worker`, `~/.config/gh`,
`~/.ssh`, Keychains, Codex and Claude logins, cloud CLIs) are unreadable, Keychain services
are blocked, `launchctl`, `open`, `osascript` and `security` cannot be started, writes are
limited to a scratch folder (the worktree stays read-only, because the worker later runs code
from it outside the sandbox), and only loopback network is allowed, except Ollama's port. The process gets a minimal environment with a throwaway
`HOME`. `TIM_TEST_SANDBOX=required` (set by the issue runner and the LaunchAgent installer)
blocks the task when no sandbox is available; `auto` sandboxes when possible; `off` only drops
the environment. Token-shaped strings are redacted from test output before it reaches logs or
helper prompts.

On Linux the same rules come from bubblewrap (`/usr/bin/bwrap`): a read-only view of `/`, empty
folders over the credential paths above and over TIM's server paths (`/etc/tim`, `/opt/tim`,
`/srv/tim`, `/srv/ci`, the production PostgreSQL files and socket, `/root`), the worktree read-only, the
scratch folder writable, and a network namespace with only its own loopback (no Ollama, no database,
no internet). `python -m src.local_first.sandbox_runner` runs a probe in that sandbox and prints `OK`
or what it could still reach; the server unit runs it before every poll.

**Constrained output and edits.** The one-shot request passes a JSON schema to Ollama's
`format`, so only well-formed proposals with allowlisted paths can be decoded. Existing files
can be changed with `edits` (`search`/`replace` pairs); each search text must occur exactly once
in the snapshot the model saw. New files still need full `content`.

**Tool loop.** With `TIM_QWEN_TOOL_LOOP=1` (default for the issue runner and the installer;
switch off with `--disable-qwen-tool-loop` or `TIM_QWEN_TOOL_LOOP=0`) Qwen first works through
`/api/chat` tool calls: `list_dir`, `read_file` and `search_code` (read-only, `src/`, `tests/`,
`docs/`), `run_required_tests` (sandboxed, at most twice), `check_patch` and `submit_patch`.
No tool writes files or takes a shell command, and the submitted patch faces the same gates.
The loop is capped at 12 steps and 10 minutes on the Mac. Heavy server runs use
a shared 15-minute loop budget, including model loading, with each call bounded
by the remaining budget. CPU prefill batches are limited to 256 tokens for
these server calls. Tool calls that Qwen prints as text are parsed as well,
because Ollama's Qwen 3.5 parser is not reliable yet. If the loop ends without a
patch, the worker makes a structured one-shot request. Heavy server retries
retain the same context and CPU batch settings. Each result records `tool_loop`
statistics (native, text-parsed and invalid calls, calls per tool, how the loop ended) and
the `test_sandbox` that ran.

**Skills.** `config/qwen-skills/<name>/SKILL.md` holds TIM guidance in the Agent Skills format.
`src/local_first/qwen_skills.py` adds the skills whose `metadata.tim-applies-to` matches
(`always`, `tool-loop` or path globs) to the prompt as text; nothing in a skill is executed.
`config/` is a locked path for worker PRs, so the worker cannot rewrite its own guidance.
Issue contracts may not list `src/local_first/` or `src/llm/` either, so the worker cannot
patch its own gates, sandbox or tool loop.

GitHub issue runs share a 900-second generation budget between Qwen's tool loop
and structured retry. A retry receives only the remaining time; after exhaustion,
the configured CLI helpers still run. The build-queue supervisor does not repeat
the entire provider chain inside an issue attempt: the issue ledger owns its two
attempts. The outer process-group limit is 40 minutes, allowing for Qwen, both
helpers, sandboxed verification and durable result writes. These limits do not
change standalone local build-queue runs.
The daemon allows 90 minutes for the whole intake, including the task, up to
10 minutes of advisory review and up to 30 minutes waiting for GitHub's merge
gate. Its timeout must not interrupt those nested stages.

The local acceptance gate rejects a result whose passing test run was not sandboxed while
`TIM_TEST_SANDBOX=required`. A task that hits the 40-minute limit has its whole process group
stopped. The Seatbelt profile has not yet been tried on the Mac mini; if it blocks Python, the
result names the failed probe.

After pulling these changes on the Mac, rerun the installer so the LaunchAgent gets
`TIM_TEST_SANDBOX` and `TIM_QWEN_TOOL_LOOP`, then restart it.

### Kompakter Prompt für kleine Server-Aufgaben

Kleine Aufgaben auf dem Server (`TIM_QWEN_SERVER_RUN=1`, ohne
`TIM_QWEN_HARD_RUN=1`) senden die Vertragslisten nur einmal und lassen die
lokal geprüften Snapshot-Hashes aus dem Modellprompt weg. Die Hashprüfung
selbst bleibt unverändert. Pflichtdateien, Datei-Inhalte, harte Regeln,
Ausführungsrichtlinie und Skill-Anweisungen bleiben vollständig erhalten.
Nur optionale Dokumentationsauszüge werden auf einen Auszug mit höchstens
600 Zeichen begrenzt; Kürzungen werden markiert. Skill-Beschreibungen werden
weggelassen, ihre Anweisungen und Vertrauenskennzeichnung bleiben erhalten.

Beim Auftrag #242 sank die Promptgröße gegenüber der vorherigen Version von
22.219 auf 19.181 Zeichen (13,7 Prozent). Das ist eine Größenmessung, kein
Nachweis einer entsprechenden Laufzeitverkürzung oder eines erfolgreichen
Patches. Mac-Aufgaben und große Hard-Aufgaben behalten das volle Format.
Die Kontextfenster-Einstellung bleibt gleich, damit das warm gehaltene
Server-Modell nicht wegen wechselnder Kontextgrößen neu geladen werden muss.
