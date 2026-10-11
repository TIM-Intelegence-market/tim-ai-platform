# Local Qwen blocker handoff

The Mac worker calls Ollama directly. When the active task is blocked and
`TIM_CODEX_BLOCKER_ADVISOR=1`, it asks the ChatGPT-authenticated Codex CLI for
a bounded diagnosis using `gpt-5.6-luna`. The request contains only sanitized
task metadata and failure details. Codex runs in an empty temporary directory
with a read-only sandbox; GitHub credential environment variables are removed.
It still runs under the same macOS user, so this is not OS-level isolation.
Its answer is advisory and Qwen must
retry under the existing local verification gates. If Codex CLI fails, the
daemon can ask OmniRoute for the same bounded advice. It does not scan and
route historical blocker requests.

## GitHub issue escalation

For a GitHub-fed task `github-issue-N`, a blocked local attempt can be posted
on issue N as a `TIM_BLOCKER_REQUEST` comment and marked `agent:escalate`.
This path is disabled unless `TIM_QWEN_GITHUB_ESCALATION=1`. Before either
GitHub write, the bridge checks a dedicated `GH_CONFIG_DIR`, the configured
`TIM_QWEN_WORKER_LOGIN`, the actual login, and the absence of admin or maintain
permissions. A non-GitHub task keeps the older central blocker comment without
the escalation label. The separate Codex-to-Claude issue pipeline only selects
an escalated issue when it also has `status:ready` and P0/P1 priority, then
verifies that the blocker comment's task ID matches the issue number. Claude
works in a restricted worktree and produces a draft PR; local tests and review
remain required. The Codex CLI advisory is the automated ChatGPT-backed
support step; an interactive ChatGPT conversation still needs a person to
operate it.

The Mac LaunchAgent is loaded in single-task pilot mode with a dedicated
`apoman74-art` GitHub login. The GitHub blocker bridge passed a controlled live
write test on issue #165, which was then closed. A complete Qwen-to-Claude
issue repair and draft-PR pilot is still pending.

## Current Mac configuration

- Preferred and installed local model: `qwen3.5:9b`; no installed fallback.
- Codex CLI advisor model: `gpt-5.6-luna` (explicit override; live probe passed).
- OmniRoute endpoint: `http://127.0.0.1:20128/v1`.
- Live local test model: `ollama-local/qwen2.5:7b`.
- Automatic cloud fallback model: `anthropic/claude-sonnet-5`.
- A dedicated OmniRoute chat key is read from macOS Keychain, service
  `TIM-OmniRoute-Worker`, account `tim-qwen-worker`. It is never placed in Git,
  the LaunchAgent plist, or a process environment variable.

## Manual inspection and testing

The standalone `scripts/run_local_blocker_broker.py --state-root STATE_ROOT`
command retains its explicit approval gate for manual testing. The daemon's
automatic path does not use these commands.
Operational blockers use `~/Library/Application Support/TIM/local-first`;
developer blockers use this worktree's `.tim/local-first`.

1. `review TASK_ID` prints the exact bounded outbound preview and request SHA-256.
   Inspect it for private material before proceeding.
2. `chatgpt-unavailable TASK_ID --reason '...'` records an explicit outcome. A
   timeout by itself does not record unavailability.
3. `approve TASK_ID --request-sha256 SHA256` authorizes only that request. A
   changed request invalidates the record.
4. `route TASK_ID
   --local-smoke` instead sends the approved request to the local model for a
   connectivity test. The returned state is `RESOLVED` when an advisory proposal
   was stored, or `ROUTER_FAILED` when routing failed. A failed request is not
   retried automatically.

The worker stores Codex or router advice as `BLOCKER_PROPOSAL`, never as a verified
resolution. When the task is retried, the local worker receives that advice and
reruns its normal safety and verification path.

## Local documentation assistant

Qwen's operational and developer prompts include up to three relevant Markdown
excerpts from this repository's `docs/` directory. Retrieval is local-only,
bounded, and skips links, oversized files, sensitive filenames and credential
lines. Excerpts cite file paths and line numbers and are explicitly marked as
untrusted reference material. They do not expand writable paths or bypass the
existing patch, test, and safety gates. No documentation is sent to OmniRoute.

## Acceptance and limits

Run the broker and local-worker tests, then the opt-in live test with
`TIM_OMNIROUTE_LIVE_TEST=1`. The live test uses only the local model. OmniRoute
cloud routing requires a key and available provider credits; a failed cloud
request leaves the task blocked.
