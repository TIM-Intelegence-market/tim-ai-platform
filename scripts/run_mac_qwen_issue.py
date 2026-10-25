#!/usr/bin/env python3
"""Process one explicitly ready GitHub issue with the Mac Qwen worker."""

from __future__ import annotations

import argparse
import calendar
import copy
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.github_issue_pipeline import DirectoryLock, Pipeline, PipelineError, WorkerIdentity
from src.local_first.github_issue_queue import LANES, build_task, is_hard_issue, select_ready_issue
from src.local_first import issue_triage
from src.local_first.issue_triage import IssueLedger, attach_worker_contract, contract_hash
from src.local_first.patch_executor import redact_diagnostic_secrets
from src.local_first.server_residency import configured_server, SERVER_OPTIONS

REPO = "TIM-Intelegence-market/tim-ai-platform"
# Big model on tim-server, reached through the local SSH tunnel (LaunchAgent com.tim.server-ollama-tunnel).
# The server never sees GitHub: only prompt in, text out. Server-preferred mode also routes
# small issues there. Hard issues always wait instead of falling back to the Mac model.
HARD_MODEL_DEFAULT = "qwen3-coder:30b"
HARD_REQUEST_TIMEOUT = "900"
REVIEW_MAX_DIFF_CHARS = 60_000
WORKER_LOGIN = "apoman74-art"
WORKER_BRANCH = re.compile(r"codex/issue-([1-9][0-9]*)-qwen(-hard)?")
SELF_UPDATED_EXIT = 3
STALE_PR_SECONDS = 6 * 3600
# Jobs that normally run for minutes; failing within seconds means no runner started them.
LONG_CHECKS = frozenset({"test", "TIM full suite"})
NO_RUNNER_SECONDS = 15
# The CI runner mac-mini-tim shares this Mac; a worker job beside a test job doubles its runtime.
CI_JOB_PROCESS = "Runner.Worker"


def worker_lane() -> str:
    """TIM_WORKER_LANE: "hard" on tim-core-01, "easy" on the Mac beside it, "all" (default) for one worker."""
    lane = os.environ.get("TIM_WORKER_LANE", "all").strip().lower() or "all"
    if lane not in LANES:
        raise PipelineError(f"unknown TIM_WORKER_LANE {lane!r}; expected one of {', '.join(LANES)}")
    return lane


def worker_branch(number: int, lane: str) -> str:
    """The hard lane has its own branches, so two workers never maintain each other's PRs."""
    return f"codex/issue-{number}-qwen" + ("-hard" if lane == "hard" else "")


def worker_name(lane: str) -> str:
    return "Server-Qwen-Worker" if lane == "hard" else "Mac-Qwen-Worker"


def ci_job_running() -> bool:
    """True while a GitHub Actions job runs on this Mac (TIM_WORKER_CI_PAUSE=0 switches the pause off)."""
    if os.environ.get("TIM_WORKER_CI_PAUSE") == "0":
        return False
    try:
        return subprocess.run(["pgrep", "-f", CI_JOB_PROCESS], capture_output=True,
                              timeout=10, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def worker_identity(config_dir: Path) -> WorkerIdentity:
    """Load the isolated gh login from Keychain without printing its token."""
    config = config_dir.expanduser().resolve()
    if config != (Path.home() / ".config/gh-tim-mac-worker").resolve():
        raise PipelineError("unexpected worker GitHub configuration directory")
    env = {key: value for key, value in os.environ.items()
           if key not in {"GH_TOKEN", "GITHUB_TOKEN", "GIT_ASKPASS", "SSH_ASKPASS"}}
    env["GH_CONFIG_DIR"] = str(config)
    result = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True,
                            env=env, timeout=20, check=False)
    token = result.stdout.strip()
    if result.returncode or not token or "\n" in token:
        raise PipelineError("dedicated GitHub worker login is unavailable")
    return WorkerIdentity(WORKER_LOGIN, token, config)


def _git_paths(pipeline: Pipeline, worktree: Path, gitdir: Path) -> set[str]:
    tracked = pipeline.worktree_git(worktree, gitdir, "diff", "--name-only", "-z", "HEAD")
    untracked = pipeline.worktree_git(worktree, gitdir, "ls-files", "--others", "--exclude-standard", "-z")
    return {path for output in (tracked, untracked) for path in output.split("\0") if path}


def _assert_task_diff(pipeline: Pipeline, worktree: Path, gitdir: Path, task: dict) -> list[str]:
    changed = _git_paths(pipeline, worktree, gitdir)
    # Runtime evidence is local data, never part of a pull request.
    code = {path for path in changed if not path.startswith(".tim/")}
    allowed = set(task["allowed_paths"])
    if not code or not code <= allowed:
        raise PipelineError(f"worker changed paths outside issue contract: {sorted(code - allowed)}")
    for path in code:
        file = worktree / path
        if not file.is_file() or file.is_symlink():
            raise PipelineError(f"worker output is not a regular file: {path}")
    return sorted(code)


def _run_task_group(command: list[str], cwd: Path, env: dict, *, timeout: int) -> int:
    """Run the local task in its own process group and kill the whole group on timeout,
    so no developer or pytest process keeps running in the worktree afterwards."""
    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, text=True, start_new_session=True)
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()
        raise PipelineError("local task timed out; its process group was stopped") from None


# Contract checks that fail the same way on every retry; no model ever saw the task.
CONTRACT_FAILURES = (
    "unsafe contract path", "contract path is not a file", "allowed file context is truncated",
    "invalid required test path", "required output is not allowlisted", "required files exceed",
    "context_paths must", "missing required test is not writable", "required outputs exceed",
    "required new tests exceed",
)


class ContractRejected(PipelineError):
    """The local developer refused the contract itself; retrying cannot help."""


def _contract_rejection(result: Path) -> str | None:
    try:
        outcome = json.loads(result.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(outcome, dict) or outcome.get("model_calls") or outcome.get("codex_fallback_calls") \
            or outcome.get("claude_fallback_calls"):
        return None
    reason = str(outcome.get("reason") or "")
    if reason.startswith(CONTRACT_FAILURES) or re.match(r"\w+ must contain 1-\d+ unique file paths", reason):
        return reason[:300]
    return None


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _failure_detail(returncode: int, result: Path, acceptance: Path) -> str:
    """Short cause of a failed attempt for the ledger and the agent:blocked comment.

    Without it every failure reads the same, whether Qwen ran out of time, both helpers
    were rejected, or a CLI was logged out. The ledger redacts tokens and truncates.
    """
    parts = [f"exit={returncode}"]
    outcome = _read_json(result)
    evidence = _read_json(acceptance)
    if outcome is None:
        parts.append("no developer result")
    else:
        # Most telling first: the ledger keeps only the first 300 characters.
        for name in ("codex", "claude"):
            error = outcome.get(f"{name}_fallback_detail") or outcome.get(f"{name}_fallback_error")
            if error:
                parts.append(f"{name}={redact_diagnostic_secrets(str(error))[:80]}")
        if outcome.get("reason"):
            parts.append(f"reason={redact_diagnostic_secrets(str(outcome['reason']))[:100]}")
    if evidence and evidence.get("failed_checks"):
        parts.append("failed_checks=" + ",".join(map(str, evidence["failed_checks"])))
    loop = outcome.get("tool_loop") if outcome else None
    if isinstance(loop, dict) and loop.get("ended"):
        parts.append(f"tool_loop={loop['ended']}")
    text = "; ".join(parts).replace("`", "'").replace("\n", " ")
    return redact_diagnostic_secrets(text)


def _hard_backend() -> tuple[str, str] | None:
    """Return (url, model) of the server model when configured and the tunnel answers, else None."""
    configured = configured_server()
    if configured is None:
        return None
    url, model = configured
    try:
        from src.llm.ollama_client import OllamaClient
        client = OllamaClient(url, model, timeout=5, observation_only=False)
        if model not in client._installed_models():
            return None
    except Exception:  # noqa: BLE001 - any failure means "use the Mac model"
        return None
    return url, model


class ServerBackendUnavailable(PipelineError):
    """The server disappeared before any model work started; defer without spending retries."""


def _run_local_task(worktree: Path, task: dict, *, codex_fallback: bool,
                    claude_fallback: bool = False, hard: bool = False) -> dict:
    backend = _hard_backend() if hard or os.getenv("TIM_QWEN_SERVER_PREFERRED") == "1" else None
    if hard and backend is None:
        raise ServerBackendUnavailable("server model unavailable; wait for the SSH tunnel")
    state = worktree / ".tim/local-first"
    inbox = state / "developer-inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    marker = state / "PATCH_SANDBOX_ALLOWED"
    marker.write_text("mac-qwen-issue-pilot\n", encoding="utf-8")
    marker.chmod(0o600)
    path = inbox / f"{task['task_id']}.json"
    path.write_text(json.dumps(task, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)
    env = Pipeline.agent_env()
    # A parent process cannot accidentally widen a small task's file contract.
    env.pop("TIM_QWEN_HARD_RUN", None)
    env.pop("TIM_QWEN_SERVER_RUN", None)
    env.update({"PYTHONPATH": str(worktree), "TIM_LOCAL_PATCH_SANDBOX": "1",
                "TIM_BLOCKER_AUTO_WAIT": "0", "TIM_LIVE_TRADING": "0",
                "TIM_EXECUTION_ENABLED": "0", "OLLAMA_MODEL": "qwen3.5:9b",
                "TIM_CODEX_PATCH_FALLBACK": "1" if codex_fallback else "0",
                "TIM_CLAUDE_PATCH_FALLBACK": "1" if claude_fallback else "0",
                # The issue ledger already owns retries. Repeating the entire provider
                # chain inside one attempt starves helpers and loses durable results.
                "TIM_SUPERVISOR_MAX_LOCAL_REPAIR_CYCLES": "0",
                "TIM_QWEN_GITHUB_RUN": "1",
                # Model-written tests never run outside the OS sandbox on the worker Mac.
                "TIM_TEST_SANDBOX": "required",
                "TIM_QWEN_TOOL_LOOP": "0" if os.environ.get("TIM_QWEN_TOOL_LOOP") == "0" else "1"})
    if backend is not None:
        env.update({"OLLAMA_BASE_URL": backend[0], "OLLAMA_MODEL": backend[1],
                    "TIM_QWEN_REQUEST_TIMEOUT": HARD_REQUEST_TIMEOUT, "TIM_QWEN_SERVER_RUN": "1"})
        if hard:
            env["TIM_QWEN_HARD_RUN"] = "1"
    returncode = _run_task_group(
        [sys.executable, "scripts/run_local_qwen_build_queue.py", "--task-id", task["task_id"]],
        # 900s shared Qwen budget + two 300s helpers + their 300s test
        # runs, with time left for acceptance and durable result writes.
        worktree, env, timeout=2400)
    acceptance = state / "acceptance-results" / f"{task['task_id']}.json"
    result = state / "developer-results" / f"{task['task_id']}.json"
    if returncode or not acceptance.is_file() or not result.is_file():
        rejection = _contract_rejection(result) if result.is_file() else None
        if rejection:
            raise ContractRejected(f"Vertrag nicht ausführbar: {rejection}")
        raise PipelineError("acceptance gate not passed: " + _failure_detail(returncode, result, acceptance))
    evidence = json.loads(acceptance.read_text(encoding="utf-8"))
    outcome = json.loads(result.read_text(encoding="utf-8"))
    if evidence.get("status") != "FIXED" or evidence.get("passed") is not True:
        raise PipelineError("local task acceptance is not FIXED: " + _failure_detail(returncode, result, acceptance))
    return {"acceptance": evidence, "result": outcome,
            "model": f"{backend[1]}@tim-server" if backend else None}


def _review_patch(task: dict, diff: str) -> dict[str, str] | None:
    """Second pair of eyes from the server model. Advisory only: the verdict goes into the PR body
    and never blocks the PR; a missing backend or any error returns None."""
    backend = _hard_backend()
    if backend is None or not diff.strip():
        return None
    diff = diff[:REVIEW_MAX_DIFF_CHARS]
    prompt = (
        "You review one patch for a trading-research code base. Answer in at most 5 lines.\n"
        "First line exactly OK or PROBLEM. Then name only concrete findings: logic error, "
        "security boundary crossed, file outside the allowed paths, missing or weakened test. "
        "No praise, no style remarks.\n\n"
        f"Objective: {str(task.get('objective', ''))[:1000]}\n"
        f"Allowed paths: {', '.join(str(item) for item in task.get('allowed_paths', []))}\n\n"
        f"Patch:\n{diff}\n")
    try:
        from src.llm.ollama_client import OllamaClient
        client = OllamaClient(backend[0], backend[1], timeout=600, observation_only=False, keep_alive=-1)
        import asyncio
        message = asyncio.run(client.chat([{"role": "user", "content": prompt}],
                                          options={**SERVER_OPTIONS, "num_predict": 400, "temperature": 0}))
        text = str(message.get("content") or "").strip()
    except Exception:  # noqa: BLE001 - advisory only
        return None
    if not text:
        return None
    from src.local_first.patch_executor import redact_tokens
    lines = [line.strip() for line in redact_tokens(text).splitlines() if line.strip()][:5]
    verdict = "\n".join(lines)[:1500].replace("```", "'''")
    return {"model": backend[1], "verdict": verdict} if verdict else None


def _merge_when_ready(pipeline: Pipeline, number: int, branch: str, head: str,
                      *, wait_seconds: int = 1800) -> None:
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        pr = json.loads(pipeline.github("pr", "view", str(number), "--json",
                                        "state,mergeStateStatus,headRefOid,headRefName,baseRefName,author"))
        if (pr.get("state") != "OPEN" or pr.get("headRefOid") != head
                or pr.get("headRefName") != branch or pr.get("baseRefName") != "platform-main"
                or str((pr.get("author") or {}).get("login", "")).casefold() != WORKER_LOGIN.casefold()):
            raise PipelineError("pull request identity or head changed before merge")
        if pr.get("mergeStateStatus") == "CLEAN":
            pipeline.github("pr", "merge", str(number), "--squash")
            return
        if pr.get("mergeStateStatus") in {"DIRTY", "BEHIND"}:
            raise PipelineError(f"pull request cannot merge: {pr.get('mergeStateStatus')}")
        time.sleep(30)
    raise PipelineError("required GitHub checks did not make the PR mergeable in time")


def self_update(pipeline: Pipeline) -> str | None:
    """Fast-forward the worker checkout to origin/platform-main when it is clean.

    Returns a log line when the checkout moved; the supervisor then restarts on the new code.
    """
    pipeline.command("git", "fetch", "--quiet", "origin", "platform-main")
    head = pipeline.command("git", "rev-parse", "HEAD")
    target = pipeline.command("git", "rev-parse", "origin/platform-main")
    if head == target:
        return None
    dirty = pipeline.command("git", "status", "--porcelain", "--untracked-files=no")
    if dirty:
        # Say so on every poll: a silently skipped update kept a fixed worker broken for hours.
        print(f"self-update skipped, worker checkout has local changes: {' '.join(dirty.split())[:200]}",
              file=sys.stderr)
        return None
    try:
        pipeline.command("git", "merge-base", "--is-ancestor", "HEAD", "origin/platform-main")
    except PipelineError:
        return None
    pipeline.command("git", "checkout", "--quiet", "--detach", "origin/platform-main")
    return f"TIM_SELF_UPDATED {head[:12]} -> {target[:12]}"


def _ensure_labels(pipeline: Pipeline) -> None:
    existing = {item.get("name") for item in json.loads(
        pipeline.github("label", "list", "--limit", "500", "--json", "name") or "[]")}
    for name, (color, description) in issue_triage.WORKER_LABELS.items():
        if name not in existing:
            pipeline.github("label", "create", name, "--color", color, "--description", description)


def _block_issue(pipeline: Pipeline, ledger: IssueLedger, number: int, errors: list[str]) -> None:
    """Stop automation on one issue visibly; the local ledger also skips it if GitHub refuses."""
    try:
        _ensure_labels(pipeline)
        pipeline.github("issue", "edit", str(number), "--add-label", issue_triage.LABEL_BLOCKED)
    except PipelineError:
        return
    ledger.mark_blocked(number)
    try:
        pipeline.github("issue", "comment", str(number), "--body", issue_triage.blocked_comment(errors))
    except PipelineError:
        pass


def _seconds(stamp: object) -> float | None:
    try:
        return float(calendar.timegm(time.strptime(str(stamp), "%Y-%m-%dT%H:%M:%SZ")))
    except ValueError:
        return None


def _ci_unavailable(pr: dict) -> bool:
    """True when every failed check died within seconds and a long job was among them.

    That is GitHub Actions not starting runners (spending limit, outage), not the PR failing,
    so the PR must neither be retired as stale nor cost the issue an attempt.
    """
    failed = []
    for check in pr.get("statusCheckRollup") or []:
        if not isinstance(check, dict) or str(check.get("conclusion", "")).upper() not in {
                "FAILURE", "STARTUP_FAILURE", "TIMED_OUT", "CANCELLED"}:
            continue
        start, end = _seconds(check.get("startedAt")), _seconds(check.get("completedAt"))
        if start is None or end is None or end - start > NO_RUNNER_SECONDS:
            return False
        failed.append(str(check.get("name", "")))
    return bool(failed) and any(name in LONG_CHECKS for name in failed)


PR_FIELDS = "number,headRefName,headRefOid,baseRefName,mergeStateStatus,createdAt,author"


def _list_worker_prs(pipeline: Pipeline) -> str:
    """The worker's open PRs, with their checks when its token may read them.

    The worker's fine-grained token cannot read commit statuses, and GitHub then refuses the whole
    query. Without the checks `_ci_unavailable` sees no failures, so such a PR is treated as before.
    """
    base = ("pr", "list", "--state", "open", "--author", WORKER_LOGIN, "--limit", "100", "--json")
    try:
        return pipeline.github(*base, PR_FIELDS + ",statusCheckRollup")
    except PipelineError as exc:
        if "Resource not accessible" not in str(exc):
            raise
        return pipeline.github(*base, PR_FIELDS)


def _maintain_worker_prs(pipeline: Pipeline, ledger: IssueLedger, *, merge: bool,
                         now: float | None = None, lane: str = "all") -> set[int]:
    """Finish or retire this lane's open PRs; return the issue numbers all worker PRs cover.

    PRs of the other lane are counted as covered, so neither worker starts an issue the other one
    has a PR for, but they are left to the worker that opened them.
    """
    prs = json.loads(_list_worker_prs(pipeline))
    covered: set[int] = set()
    now = time.time() if now is None else now
    for pr in prs if isinstance(prs, list) else []:
        match = WORKER_BRANCH.fullmatch(str(pr.get("headRefName", "")))
        if match is None or pr.get("baseRefName") != "platform-main":
            continue
        issue = int(match.group(1))
        covered.add(issue)
        if bool(match.group(2)) != (lane == "hard"):
            continue
        number, status = str(pr.get("number")), pr.get("mergeStateStatus")
        try:
            created = calendar.timegm(time.strptime(str(pr.get("createdAt")), "%Y-%m-%dT%H:%M:%SZ"))
        except ValueError:
            created = now
        try:
            if merge and status == "CLEAN":
                pipeline.github("pr", "merge", number, "--squash")
            elif merge and status == "BEHIND":
                pipeline.github("pr", "update-branch", number)
            elif merge and status != "DIRTY" and _ci_unavailable(pr):
                # Keep the PR; once Actions runs again a base update re-runs its checks.
                print(f"worker PR #{number} waits: GitHub Actions started no runner", file=sys.stderr)
            elif merge and (status == "DIRTY" or now - created > STALE_PR_SECONDS):
                reason = f"worker PR #{number} closed: {status or 'unknown'} after {int((now - created) // 60)} min"
                # No --delete-branch: on the detached worker checkout gh fails after closing, which
                # skipped the attempt count below. The next attempt deletes the old branch anyway.
                pipeline.github("pr", "close", number, "--comment",
                                f"Der {worker_name(lane)} schließt diesen PR und versucht es neu "
                                f"(Zustand {status}).")
                covered.discard(issue)
                contract = (ledger.entry(issue).get("attempts") or {}).get("contract")
                if contract and ledger.record_failure(issue, contract, reason):
                    _block_issue(pipeline, ledger, issue, ledger.errors(issue))
        except PipelineError as exc:
            # One stuck PR must not stop the queue; the next poll looks at it again.
            print(f"worker PR #{number} maintenance failed: {str(exc)[:200]}", file=sys.stderr)
    return covered


def _clear_leftovers(pipeline: Pipeline, state_dir: Path, number: int, branch: str,
                     worktree: Path, attempt: int) -> None:
    """Keep the evidence of a failed attempt, then remove its worktree and branches."""
    if worktree.exists():
        evidence = worktree / ".tim/local-first"
        if evidence.is_dir():
            shutil.copytree(evidence, state_dir / "runs" / f"issue-{number}-before-attempt-{attempt}",
                            dirs_exist_ok=True, symlinks=True)
        pipeline.command("git", "worktree", "remove", "--force", str(worktree))
    pipeline.command("git", "worktree", "prune")
    if pipeline.command("git", "branch", "--list", branch).strip():
        pipeline.command("git", "branch", "-D", branch)
    if pipeline.command("git", "ls-remote", "--heads", "origin", branch).strip():
        pipeline.command("git", "push", "--no-verify", "origin", "--delete", branch)


def _triage_one(pipeline: Pipeline, ledger: IssueLedger, issues: list, repo_root: Path,
                lane: str = "all") -> str:
    candidates = issue_triage.triage_candidates(issues, ledger)
    if not candidates:
        return "No eligible Mac Qwen issue; nothing left to triage."
    if not ledger.triage_budget_left():
        return "No eligible Mac Qwen issue; daily triage budget used."
    issue = candidates[0]
    number = issue["number"]
    # Files the Mac model cannot see in full are only accepted while the server model answers.
    # With lane "easy" the server worker takes agent:qwen-hard, even when this Mac has no tunnel.
    allow_hard = lane == "easy" or _hard_backend() is not None
    try:
        raw = issue_triage.ask_claude(issue_triage.triage_prompt(issue, allow_hard=allow_hard), repo_root)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        ledger.record_triage(issue, f"error:{type(exc).__name__}")
        return f"Triage of #{number} failed: {type(exc).__name__}"
    result = issue_triage.parse_triage(raw, issue, repo_root, allow_hard=allow_hard)
    ledger.record_triage(issue, result["decision"])
    _ensure_labels(pipeline)
    if result["decision"] == "ready":
        pipeline.github("issue", "comment", str(number), "--body", issue_triage.ready_comment(result))
        pipeline.github("issue", "edit", str(number), "--add-label",
                        f"{issue_triage.ready_label(result)},status:ready,priority:{result['priority']}")
        return f"Triage: #{number} prepared for the Mac Qwen worker."
    if result["decision"] == "split":
        children = _create_subtasks(pipeline, ledger, issue, result)
        pipeline.github("issue", "comment", str(number), "--body",
                        issue_triage.split_comment(result, children))
        pipeline.github("issue", "edit", str(number), "--add-label", issue_triage.LABEL_SPLIT)
        return f"Triage: #{number} split into {len(children)} worker issues: {children}"
    pipeline.github("issue", "comment", str(number), "--body", issue_triage.skip_comment(result))
    pipeline.github("issue", "edit", str(number), "--add-label", issue_triage.LABEL_NOT_SUITABLE)
    return f"Triage: #{number} is not a Mac Qwen task: {result['reason']}"


def _create_subtasks(pipeline: Pipeline, ledger: IssueLedger, parent: dict, result: dict) -> list[int]:
    """Open one worker-authored issue per subtask; the ledger already marks the parent as split,
    so a crash halfway never creates the same children twice."""
    children: list[int] = []
    for subtask in result["subtasks"]:
        url = pipeline.github("issue", "create", "--title", f"[Teil von #{parent['number']}] {subtask['title']}",
                              "--body", f"Teil von #{parent['number']}; Vertrag folgt.")
        match = re.search(r"/issues/([1-9][0-9]*)", url)
        if match is None:
            raise PipelineError("GitHub did not return an issue URL")
        child = int(match.group(1))
        bound = {**subtask, "task": issue_triage.rebind_task(subtask["task"], child)}
        pipeline.github("issue", "edit", str(child), "--body", issue_triage.subtask_body(parent, bound))
        pipeline.github("issue", "edit", str(child), "--add-label",
                        f"{issue_triage.ready_label(subtask)},status:ready,priority:{subtask['priority']}")
        children.append(child)
        ledger.entry(parent["number"]).setdefault("children", []).append(child)
        ledger.save()
    return children


def _select(pipeline: Pipeline, ledger: IssueLedger, issues: list, *, pilot_issue: int | None,
            skip: set[int], dry_run: bool, lane: str = "all") -> tuple[dict, dict] | None:
    """Pick the next workable issue; a broken contract or used-up attempts never block the queue."""
    hard_ready: bool | None = None
    while True:
        issue = select_ready_issue(issues, only_number=pilot_issue, skip=skip, lane=lane)
        if issue is None:
            return None
        number = issue["number"]
        if is_hard_issue(issue) and not dry_run:
            if hard_ready is None:
                hard_ready = _hard_backend() is not None
            if not hard_ready:
                # Waits for the server tunnel instead of spending attempts on the Mac model.
                skip.add(number)
                continue
        try:
            task = build_task(issue)
        except ValueError as exc:
            skip.add(number)
            if not dry_run and not ledger.entry(number).get("blocked"):
                ledger.exhaust(number, issue_triage.body_hash(issue), f"invalid contract: {exc}")
                _block_issue(pipeline, ledger, number, ledger.errors(number))
            continue
        if ledger.exhausted(number, contract_hash(task)):
            skip.add(number)
            if not dry_run and not ledger.entry(number).get("blocked"):
                _block_issue(pipeline, ledger, number, ledger.errors(number))
            continue
        return issue, task


def process_one(pipeline: Pipeline, state_dir: Path, *, pilot_issue: int | None,
                codex_fallback: bool, merge: bool, dry_run: bool = False,
                claude_fallback: bool = False, triage: bool = False,
                update: bool = False) -> str:
    lane = worker_lane()
    pipeline.verify_worker_identity()
    if pipeline.repository_slug() != REPO:
        raise PipelineError("unexpected TIM repository")
    if update and not dry_run:
        moved = self_update(pipeline)
        if moved:
            return moved
    issues = json.loads(pipeline.github("issue", "list", "--state", "open", "--limit", "1000", "--json",
                                       "number,title,body,labels,updatedAt,url,state,author,comments"))
    if not isinstance(issues, list):
        raise PipelineError("GitHub issue list is invalid")
    issues = [attach_worker_contract(issue, WORKER_LOGIN) if isinstance(issue, dict) else issue
              for issue in issues]
    ledger = IssueLedger(state_dir / "issue-ledger.json")
    ledger.reconcile(issues)
    skip = set() if dry_run else _maintain_worker_prs(pipeline, ledger, merge=merge, lane=lane)
    if not dry_run and ci_job_running():
        return "CI job running on this machine; issue work paused until it ends."
    selected = _select(pipeline, ledger, issues, pilot_issue=pilot_issue, skip=skip, dry_run=dry_run,
                       lane=lane)
    if selected is None:
        # Triage needs Claude Code, which only the Mac has; the hard lane never triages.
        if triage and lane != "hard" and pilot_issue is None and not dry_run:
            return _triage_one(pipeline, ledger, issues, pipeline.repository, lane=lane)
        if lane == "hard":
            if not dry_run and _hard_backend() is None:
                # The server worker has nothing else to do; an idle exit would hide a broken model setup.
                raise PipelineError("server model unavailable (TIM_QWEN_HARD_URL, TIM_QWEN_HARD_MODEL)")
            return "No eligible Qwen issue (lane hard)."
        # The Mac dashboard counts idle polls by this prefix.
        return "No eligible Mac Qwen issue" + (" (lane easy)." if lane == "easy" else ".")
    issue, task = selected
    number = task["issue_number"]
    if dry_run:
        return f"Eligible Qwen issue #{number} (lane {lane}): {issue.get('title', '')}"
    base = pipeline.default_base_ref()
    if base != "origin/platform-main":
        raise PipelineError("unexpected TIM base branch")
    branch = worker_branch(number, lane)
    worktree = state_dir / "worktrees" / branch.removeprefix("codex/")
    digest = contract_hash(task)
    previous_attempts = copy.deepcopy(ledger.entry(number).get("attempts"))
    attempt = ledger.start_attempt(number, digest)
    try:
        _clear_leftovers(pipeline, state_dir, number, branch, worktree, attempt)
        worktree.parent.mkdir(parents=True, exist_ok=True)
        pipeline.command("git", "worktree", "add", "-b", branch, str(worktree), base)
        gitdir = Path(pipeline.command("git", "rev-parse", "--absolute-git-dir", cwd=worktree))
        outcome = _run_local_task(worktree, task, codex_fallback=codex_fallback,
                                  claude_fallback=claude_fallback, hard=is_hard_issue(issue))
        paths = _assert_task_diff(pipeline, worktree, gitdir, task)
        pipeline.worktree_git(worktree, gitdir, "diff", "HEAD", "--check")
        review = _review_patch(task, pipeline.worktree_git(worktree, gitdir, "diff", "HEAD", "--", *paths))
        pipeline.worktree_git(worktree, gitdir, "add", "--", *paths)
        pipeline.worktree_git(worktree, gitdir, "-c", f"user.name={WORKER_LOGIN}",
                              "-c", f"user.email={WORKER_LOGIN}@users.noreply.github.com",
                              "commit", "--no-verify", "-m",
                              f"fix(issue-{number}): {'Server' if lane == 'hard' else 'Mac'} Qwen repair")
        head = pipeline.worktree_git(worktree, gitdir, "rev-parse", "HEAD")
        pipeline.worktree_git(worktree, gitdir, "push", "--no-verify", "origin", branch)
        provider = outcome["result"].get("fallback_provider") or outcome["result"].get("provider")
        body_lines = [f"Closes #{number}", "",
                      "Server Qwen issue repair (tim-core-01)." if lane == "hard" else "Mac Qwen issue repair.", "",
                      f"Local acceptance: {outcome['acceptance']['status']}",
                      f"Implementation provider: {provider}"]
        if outcome.get("model"):
            body_lines.append(f"Qwen model: {outcome['model']}")
        body_lines += [f"Changed paths: {', '.join(paths)}", ""]
        if review:
            body_lines += [f"Reviewer (advisory, {review['model']} on tim-server):", "```",
                           review["verdict"], "```", ""]
        body_lines.append("GitHub required checks and the repository ruleset control merging.")
        body = "\n".join(body_lines) + "\n"
        body_path = state_dir / "runs" / f"issue-{number}-pr.md"
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_text(body, encoding="utf-8")
        url = pipeline.github("pr", "create", "--base", "platform-main", "--head", branch,
                              "--title", f"fix(issue-{number}): {str(issue.get('title', 'Mac Qwen repair'))[:90]}",
                              "--body-file", str(body_path))
        match = re.search(r"/pull/([1-9][0-9]*)", url)
        if match is None:
            raise PipelineError("GitHub did not return a pull request URL")
    except ServerBackendUnavailable:
        # No model process was launched. Preserve any earlier genuine failures exactly.
        entry = ledger.entry(number)
        if previous_attempts is None:
            entry.pop("attempts", None)
        else:
            entry["attempts"] = previous_attempts
        ledger.save()
        return f"Issue #{number} waiting for server model; retry budget unchanged."
    except (PipelineError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        if isinstance(exc, ContractRejected):
            ledger.exhaust(number, digest, str(exc))
            _block_issue(pipeline, ledger, number, ledger.errors(number))
        elif ledger.record_failure(number, digest, str(exc)):
            _block_issue(pipeline, ledger, number, ledger.errors(number))
        raise
    if merge:
        try:
            _merge_when_ready(pipeline, int(match.group(1)), branch, head)
        except PipelineError as exc:
            # The PR stays open; the next poll merges, updates or retires it.
            return f"{url} (merge pending: {str(exc)[:120]})"
    return url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=ROOT)
    parser.add_argument("--state-dir", type=Path, default=Path.home() / "Library/Application Support/TIM Mac Issue Worker")
    parser.add_argument("--pilot-issue", type=int)
    parser.add_argument("--no-codex-fallback", action="store_true")
    parser.add_argument("--no-claude-fallback", action="store_true")
    parser.add_argument("--merge", action="store_true", help="Wait for GitHub gates, then squash merge as the worker")
    parser.add_argument("--dry-run", action="store_true", help="Check identity and issue contract without writing")
    parser.add_argument("--triage", action="store_true",
                        help="When nothing is ready, let Claude triage one open issue into a contract")
    parser.add_argument("--self-update", action="store_true",
                        help="Fast-forward a clean worker checkout to origin/platform-main first")
    args = parser.parse_args()
    try:
        with DirectoryLock(args.state_dir.expanduser() / "run.lock"):
            worker = worker_identity(Path.home() / ".config/gh-tim-mac-worker")
            pipeline = Pipeline(args.repository, args.state_dir, worker=worker)
            message = process_one(pipeline, args.state_dir.expanduser(), pilot_issue=args.pilot_issue,
                                  codex_fallback=not args.no_codex_fallback,
                                  claude_fallback=not args.no_claude_fallback, merge=args.merge,
                                  dry_run=args.dry_run, triage=args.triage, update=args.self_update)
            print(message)
        return SELF_UPDATED_EXIT if message.startswith("TIM_SELF_UPDATED") else 0
    except (PipelineError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"Mac Qwen issue worker stopped safely: {str(exc)[:300]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
