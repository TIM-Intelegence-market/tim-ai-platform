#!/usr/bin/env python3
"""Process one explicitly ready GitHub issue with the Mac Qwen worker."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.github_issue_pipeline import DirectoryLock, Pipeline, PipelineError, WorkerIdentity
from src.local_first.github_issue_queue import build_task, select_ready_issue

REPO = "TIM-Intelegence-market/tim-ai-platform"
WORKER_LOGIN = "apoman74-art"


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
                "TIM_CLAUDE_PATCH_FALLBACK": "1" if claude_fallback else "0"})
    completed = subprocess.run(
        [sys.executable, "scripts/run_local_qwen_build_queue.py", "--task-id", task["task_id"]],
        cwd=worktree, env=env, capture_output=True, text=True, timeout=1800, check=False,
    )
    acceptance = state / "acceptance-results" / f"{task['task_id']}.json"
    result = state / "developer-results" / f"{task['task_id']}.json"
    if completed.returncode or not acceptance.is_file() or not result.is_file():
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


def process_one(pipeline: Pipeline, state_dir: Path, *, pilot_issue: int | None,
                codex_fallback: bool, merge: bool, dry_run: bool = False,
                claude_fallback: bool = False) -> str:
    pipeline.verify_worker_identity()
    if pipeline.repository_slug() != REPO:
        raise PipelineError("unexpected TIM repository")
    issues = json.loads(pipeline.github("issue", "list", "--state", "open", "--limit", "1000",
                                       "--json", "number,title,body,labels,updatedAt,url,state"))
    if not isinstance(issues, list):
        raise PipelineError("GitHub issue list is invalid")
    issue = select_ready_issue(issues, only_number=pilot_issue)
    if issue is None:
        return "No eligible Mac Qwen issue."
    task = build_task(issue)
    number = task["issue_number"]
    if dry_run:
        return f"Eligible Mac Qwen issue #{number}: {issue.get('title', '')}"
    base = pipeline.default_base_ref()
    if base != "origin/platform-main":
        raise PipelineError("unexpected TIM base branch")
    branch = f"codex/issue-{number}-qwen"
    worktree = state_dir / "worktrees" / f"issue-{number}-qwen"
    if worktree.exists() or pipeline.command("git", "branch", "--list", branch).strip():
        raise PipelineError("issue worktree or branch already exists; inspect the previous run")
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
    if merge:
        _merge_when_ready(pipeline, int(match.group(1)), branch, head)
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
    args = parser.parse_args()
    try:
        with DirectoryLock(args.state_dir.expanduser() / "run.lock"):
            worker = worker_identity(Path.home() / ".config/gh-tim-mac-worker")
            pipeline = Pipeline(args.repository, args.state_dir, worker=worker)
            print(process_one(pipeline, args.state_dir.expanduser(), pilot_issue=args.pilot_issue,
                              codex_fallback=not args.no_codex_fallback,
                              claude_fallback=not args.no_claude_fallback, merge=args.merge,
                              dry_run=args.dry_run))
        return 0
    except (PipelineError, OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"Mac Qwen issue worker stopped safely: {str(exc)[:300]}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
