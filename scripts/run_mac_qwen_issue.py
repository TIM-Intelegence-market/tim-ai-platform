#!/usr/bin/env python3
"""Process one explicitly ready GitHub issue with the Mac Qwen worker."""

from __future__ import annotations

import argparse
import calendar
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
from src.local_first.github_issue_queue import build_task, select_ready_issue
from src.local_first import issue_triage
from src.local_first.issue_triage import IssueLedger, attach_worker_contract, contract_hash

REPO = "TIM-Intelegence-market/tim-ai-platform"
WORKER_LOGIN = "apoman74-art"
WORKER_BRANCH = re.compile(r"codex/issue-([1-9][0-9]*)-qwen")
SELF_UPDATED_EXIT = 3
STALE_PR_SECONDS = 6 * 3600


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


def _run_local_task(worktree: Path, task: dict, *, codex_fallback: bool,
                    claude_fallback: bool = False) -> dict:
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
    env.update({"PYTHONPATH": str(worktree), "TIM_LOCAL_PATCH_SANDBOX": "1",
                "TIM_BLOCKER_AUTO_WAIT": "0", "TIM_LIVE_TRADING": "0",
                "TIM_EXECUTION_ENABLED": "0", "OLLAMA_MODEL": "qwen3.5:9b",
                "TIM_CODEX_PATCH_FALLBACK": "1" if codex_fallback else "0",
                "TIM_CLAUDE_PATCH_FALLBACK": "1" if claude_fallback else "0",
                # Model-written tests never run outside the OS sandbox on the worker Mac.
                "TIM_TEST_SANDBOX": "required",
                "TIM_QWEN_TOOL_LOOP": "0" if os.environ.get("TIM_QWEN_TOOL_LOOP") == "0" else "1"})
    returncode = _run_task_group(
        [sys.executable, "scripts/run_local_qwen_build_queue.py", "--task-id", task["task_id"]],
        worktree, env, timeout=1800)
    acceptance = state / "acceptance-results" / f"{task['task_id']}.json"
    result = state / "developer-results" / f"{task['task_id']}.json"
    if returncode or not acceptance.is_file() or not result.is_file():
        rejection = _contract_rejection(result) if result.is_file() else None
        if rejection:
            raise ContractRejected(f"Vertrag nicht ausführbar: {rejection}")
        raise PipelineError("local Qwen/Codex/Claude task did not pass its acceptance gate")
    evidence = json.loads(acceptance.read_text(encoding="utf-8"))
    outcome = json.loads(result.read_text(encoding="utf-8"))
    if evidence.get("status") != "FIXED" or evidence.get("passed") is not True:
        raise PipelineError("local task acceptance is not FIXED")
    return {"acceptance": evidence, "result": outcome}


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
    if pipeline.command("git", "status", "--porcelain", "--untracked-files=no"):
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


def _maintain_worker_prs(pipeline: Pipeline, ledger: IssueLedger, *, merge: bool,
                         now: float | None = None) -> set[int]:
    """Finish or retire the worker's own open PRs; return the issue numbers they cover."""
    prs = json.loads(pipeline.github(
        "pr", "list", "--state", "open", "--author", WORKER_LOGIN, "--limit", "100", "--json",
        "number,headRefName,headRefOid,baseRefName,mergeStateStatus,createdAt,author"))
    covered: set[int] = set()
    now = time.time() if now is None else now
    for pr in prs if isinstance(prs, list) else []:
        match = WORKER_BRANCH.fullmatch(str(pr.get("headRefName", "")))
        if match is None or pr.get("baseRefName") != "platform-main":
            continue
        issue = int(match.group(1))
        covered.add(issue)
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
            elif merge and (status == "DIRTY" or now - created > STALE_PR_SECONDS):
                reason = f"worker PR #{number} closed: {status or 'unknown'} after {int((now - created) // 60)} min"
                pipeline.github("pr", "close", number, "--delete-branch", "--comment",
                                "Der Mac-Qwen-Worker schließt diesen PR und versucht es neu "
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


def _triage_one(pipeline: Pipeline, ledger: IssueLedger, issues: list, repo_root: Path) -> str:
    candidates = issue_triage.triage_candidates(issues, ledger)
    if not candidates:
        return "No eligible Mac Qwen issue; nothing left to triage."
    if not ledger.triage_budget_left():
        return "No eligible Mac Qwen issue; daily triage budget used."
    issue = candidates[0]
    number = issue["number"]
    try:
        raw = issue_triage.ask_claude(issue_triage.triage_prompt(issue), repo_root)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        ledger.record_triage(issue, f"error:{type(exc).__name__}")
        return f"Triage of #{number} failed: {type(exc).__name__}"
    result = issue_triage.parse_triage(raw, issue, repo_root)
    ledger.record_triage(issue, result["decision"])
    _ensure_labels(pipeline)
    if result["decision"] == "ready":
        pipeline.github("issue", "comment", str(number), "--body", issue_triage.ready_comment(result))
        pipeline.github("issue", "edit", str(number), "--add-label",
                        f"{issue_triage.LABEL_READY},status:ready,priority:{result['priority']}")
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
                        f"{issue_triage.LABEL_READY},status:ready,priority:{subtask['priority']}")
        children.append(child)
        ledger.entry(parent["number"]).setdefault("children", []).append(child)
        ledger.save()
    return children


def _select(pipeline: Pipeline, ledger: IssueLedger, issues: list, *, pilot_issue: int | None,
            skip: set[int], dry_run: bool) -> tuple[dict, dict] | None:
    """Pick the next workable issue; a broken contract or used-up attempts never block the queue."""
    while True:
        issue = select_ready_issue(issues, only_number=pilot_issue, skip=skip)
        if issue is None:
            return None
        number = issue["number"]
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
    skip = set() if dry_run else _maintain_worker_prs(pipeline, ledger, merge=merge)
    selected = _select(pipeline, ledger, issues, pilot_issue=pilot_issue, skip=skip, dry_run=dry_run)
    if selected is None:
        if triage and pilot_issue is None and not dry_run:
            return _triage_one(pipeline, ledger, issues, pipeline.repository)
        return "No eligible Mac Qwen issue."
    issue, task = selected
    number = task["issue_number"]
    if dry_run:
        return f"Eligible Mac Qwen issue #{number}: {issue.get('title', '')}"
    base = pipeline.default_base_ref()
    if base != "origin/platform-main":
        raise PipelineError("unexpected TIM base branch")
    branch = f"codex/issue-{number}-qwen"
    worktree = state_dir / "worktrees" / f"issue-{number}-qwen"
    digest = contract_hash(task)
    attempt = ledger.start_attempt(number, digest)
    try:
        _clear_leftovers(pipeline, state_dir, number, branch, worktree, attempt)
        worktree.parent.mkdir(parents=True, exist_ok=True)
        pipeline.command("git", "worktree", "add", "-b", branch, str(worktree), base)
        gitdir = Path(pipeline.command("git", "rev-parse", "--absolute-git-dir", cwd=worktree))
        outcome = _run_local_task(worktree, task, codex_fallback=codex_fallback,
                                  claude_fallback=claude_fallback)
        paths = _assert_task_diff(pipeline, worktree, gitdir, task)
        pipeline.worktree_git(worktree, gitdir, "diff", "HEAD", "--check")
        pipeline.worktree_git(worktree, gitdir, "add", "--", *paths)
        pipeline.worktree_git(worktree, gitdir, "-c", f"user.name={WORKER_LOGIN}",
                              "-c", f"user.email={WORKER_LOGIN}@users.noreply.github.com",
                              "commit", "--no-verify", "-m", f"fix(issue-{number}): Mac Qwen repair")
        head = pipeline.worktree_git(worktree, gitdir, "rev-parse", "HEAD")
        pipeline.worktree_git(worktree, gitdir, "push", "--no-verify", "origin", branch)
        body = (f"Closes #{number}\n\nMac Qwen issue repair.\n\n"
                f"Local acceptance: {outcome['acceptance']['status']}\n"
                f"Implementation provider: {outcome['result'].get('fallback_provider') or outcome['result'].get('provider')}\n"
                f"Changed paths: {', '.join(paths)}\n\n"
                "GitHub required checks and the repository ruleset control merging.\n")
        body_path = state_dir / "runs" / f"issue-{number}-pr.md"
        body_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_text(body, encoding="utf-8")
        url = pipeline.github("pr", "create", "--base", "platform-main", "--head", branch,
                              "--title", f"fix(issue-{number}): {str(issue.get('title', 'Mac Qwen repair'))[:90]}",
                              "--body-file", str(body_path))
        match = re.search(r"/pull/([1-9][0-9]*)", url)
        if match is None:
            raise PipelineError("GitHub did not return a pull request URL")
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
