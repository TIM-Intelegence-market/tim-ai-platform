#!/usr/bin/env python3
"""Run one safe local Codex-to-Claude GitHub issue handoff."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

DEPENDENCY = re.compile(r"\b(?:depends on|blocked by)\b[^\n]*", re.IGNORECASE)
ISSUE_REFERENCE = re.compile(r"#(\d+)")
RUN_MARKER = "TIM_CODEX_CLAUDE_RUN_V1"
ANALYSIS_MARKER = "TIM_CODEX_ANALYSIS_V1"
WORKFLOW_LABELS = {
    "agent:pilot": "Explicit test issue for the local Codex-to-Claude pipeline",
    "agent:analyzing": "Codex analysis is running",
    "agent:claude-running": "Claude implementation is running",
    "agent:pr-open": "A Claude draft pull request is open",
    "agent:blocked": "Automation stopped safely; human action is needed",
    "agent:retry": "Explicitly allow one retry after a blocked run",
    "agent:auto-merge": "Pipeline PR eligible for automated merge after all gates pass",
}
EXCLUDED_LABELS = {
    "type:epic", "status:blocked", "status:waiting", "ci-blocked",
    "external-action", "status:external-action", "archive", "duplicate",
    "agent:analyzing", "agent:claude-running", "agent:pr-open", "agent:blocked",
}


class PipelineError(RuntimeError):
    """A fail-closed pipeline error suitable for an issue comment."""


@dataclass(frozen=True)
class Candidate:
    number: int
    title: str
    body: str
    labels: frozenset[str]
    updated_at: str
    url: str


def labels(issue: dict[str, Any]) -> frozenset[str]:
    return frozenset(item["name"] if isinstance(item, dict) else str(item) for item in issue.get("labels", []))


def dependency_numbers(body: str) -> frozenset[int]:
    return frozenset(int(number) for line in DEPENDENCY.findall(body or "") for number in ISSUE_REFERENCE.findall(line))


def choose_candidate(issues: Sequence[dict[str, Any]], *, mode: str = "pilot") -> Candidate | None:
    """Choose one ready P0/P1 issue, deterministically and without guessing."""
    open_numbers = {int(issue["number"]) for issue in issues if issue.get("state", "open").lower() == "open"}
    candidates: list[tuple[int, str, int, Candidate]] = []
    for issue in issues:
        issue_labels = labels(issue)
        if mode == "pilot" and "agent:pilot" not in issue_labels:
            continue
        if issue.get("state", "open").lower() != "open" or "status:ready" not in issue_labels:
            continue
        priority = 0 if "priority:p0" in issue_labels else 1 if "priority:p1" in issue_labels else None
        excluded = issue_labels & EXCLUDED_LABELS
        retryable = excluded == {"agent:blocked"} and "agent:retry" in issue_labels
        if priority is None or (excluded and not retryable):
            continue
        if dependency_numbers(issue.get("body") or "") & open_numbers:
            continue
        candidate = Candidate(int(issue["number"]), issue["title"], issue.get("body") or "", issue_labels,
                              issue.get("updatedAt") or issue.get("updated_at") or "", issue.get("url") or "")
        candidates.append((priority, candidate.updated_at, candidate.number, candidate))
    return min(candidates, default=None, key=lambda item: item[:3])[3] if candidates else None


def analysis_prompt(candidate: Candidate, base_sha: str) -> str:
    return f"""Analyze GitHub issue #{candidate.number} for implementation. Work read-only.
Repository base commit: {base_sha}
Issue title: {candidate.title}
Issue body:
{candidate.body}

Return Markdown using exactly these headings: Problem, Accepted solution, Affected files, Risks, Test plan, Stop conditions.
Do not implement, edit files, create branches, or call GitHub in this analysis. The downstream Claude worker is explicitly authorized to push its isolated branch and create the required draft PR; never describe that PR as out of scope. Respect repository instructions and reject unsafe work."""


def claude_prompt(candidate: Candidate, analysis: str, branch: str) -> str:
    return f"""You are the implementation worker for GitHub issue #{candidate.number}: {candidate.title}.
You are in a dedicated git worktree on branch `{branch}`. The following Codex analysis is binding for technical scope only; its read-only restriction applies to Codex, not to you:

{analysis}

Implement only this issue. Respect repository instructions. Run relevant tests. Commit the changes, push exactly branch `{branch}`, then create exactly one GitHub DRAFT PR targeting the repository default branch. Include `Closes #{candidate.number}` and this run marker in its body: `<!-- {RUN_MARKER} -->`.
Never merge a PR, close an issue, delete history, alter credentials, or work outside this worktree. If the work cannot safely be completed, stop without pushing and clearly explain why."""


class CommandRunner:
    def run(self, args: Sequence[str], *, cwd: Path | None = None, timeout: int = 900) -> str:
        try:
            completed = subprocess.run(list(args), cwd=cwd, check=True, text=True, capture_output=True, timeout=timeout)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            detail = getattr(error, "stderr", "") or getattr(error, "stdout", "") or str(error)
            raise PipelineError(detail.strip()[:2000]) from error
        return completed.stdout.strip()


class DirectoryLock:
    def __init__(self, path: Path) -> None:
        self.path = path

    def __enter__(self) -> "DirectoryLock":
        try:
            self.path.mkdir(parents=True)
        except FileExistsError as error:
            raise PipelineError("Another pipeline run already holds the local lock.") from error
        (self.path / "pid").write_text(str(os.getpid()), encoding="utf-8")
        return self

    def __exit__(self, *_: object) -> None:
        for child in self.path.iterdir():
            child.unlink(missing_ok=True)
        self.path.rmdir()


class Pipeline:
    def __init__(self, repository: Path, state_dir: Path, runner: CommandRunner | None = None) -> None:
        self.repository, self.state_dir, self.runner = repository.resolve(), state_dir.expanduser(), runner or CommandRunner()

    def command(self, *args: str, cwd: Path | None = None, timeout: int = 900) -> str:
        return self.runner.run(args, cwd=cwd or self.repository, timeout=timeout)

    def github(self, *args: str) -> str:
        return self.command("gh", *args)

    def ensure_prerequisites(self, *, require_agents: bool = True) -> None:
        executables = ["gh", "git"]
        if require_agents:
            executables.extend(["codex", "claude"])
        for executable in executables:
            if shutil.which(executable) is None:
                raise PipelineError(f"Required executable is unavailable: {executable}")
        self.github("auth", "status")
        if require_agents:
            try:
                claude_auth = json.loads(self.command("claude", "auth", "status"))
            except json.JSONDecodeError as error:
                raise PipelineError("Claude authentication status was not machine-readable.") from error
            if not claude_auth.get("loggedIn"):
                raise PipelineError("Claude Code is not logged in. Run `claude auth login` before retrying.")

    def ensure_labels(self) -> None:
        for name, description in WORKFLOW_LABELS.items():
            self.github("label", "create", name, "--color", "5319e7", "--description", description, "--force")

    def list_issues(self) -> list[dict[str, Any]]:
        raw = self.github("issue", "list", "--state", "open", "--limit", "100", "--json", "number,title,body,labels,updatedAt,url,state")
        return json.loads(raw)

    def edit_labels(self, number: int, *, add: str = "", remove: str = "") -> None:
        args = ["issue", "edit", str(number)]
        if add:
            args.extend(["--add-label", add])
        if remove:
            args.extend(["--remove-label", remove])
        self.github(*args)

    def comment(self, number: int, body: str) -> None:
        self.github("issue", "comment", str(number), "--body", body)

    def default_base_ref(self) -> str:
        repository = json.loads(self.github("repo", "view", "--json", "defaultBranchRef"))
        name = repository.get("defaultBranchRef", {}).get("name")
        if not name:
            raise PipelineError("GitHub default branch could not be determined.")
        self.command("git", "fetch", "--quiet", "origin", name)
        return f"origin/{name}"

    def run_analysis(self, candidate: Candidate, run_id: str, base_ref: str) -> str:
        base_sha = self.command("git", "rev-parse", base_ref)
        output = self.state_dir / "runs" / f"{run_id}-analysis.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        self.command("codex", "exec", "-C", str(self.repository), "--sandbox", "read-only",
                     "--output-last-message", str(output), analysis_prompt(candidate, base_sha), timeout=1800)
        if not output.exists() or not output.read_text(encoding="utf-8").strip():
            raise PipelineError("Codex completed without a usable analysis artifact.")
        analysis = output.read_text(encoding="utf-8").strip()
        self.comment(candidate.number, f"<!-- {ANALYSIS_MARKER} run={run_id} -->\n## Codex analysis\n\n{analysis}")
        return analysis


    def make_worktree(self, candidate: Candidate, run_id: str, base_ref: str) -> tuple[Path, str]:
        slug = re.sub(r"[^a-z0-9]+", "-", candidate.title.lower()).strip("-")[:40] or "work"
        branch = f"claude/issue-{candidate.number}-{slug}"
        worktree = self.state_dir / "worktrees" / f"issue-{candidate.number}-{run_id[:8]}"
        worktree.parent.mkdir(parents=True, exist_ok=True)
        if self.command("git", "branch", "--list", branch).strip():
            listing = self.command("git", "worktree", "list", "--porcelain")
            for block in listing.split("\n\n"):
                if f"branch refs/heads/{branch}" in block:
                    path_line = next((line for line in block.splitlines() if line.startswith("worktree ")), None)
                    if path_line:
                        return Path(path_line.removeprefix("worktree ")), branch
            raise PipelineError(f"Branch {branch} already exists without a managed worktree; refusing a duplicate implementation.")
        self.command("git", "worktree", "add", "-b", branch, str(worktree), base_ref)
        return worktree, branch

    def find_draft_pr(self, branch: str) -> dict[str, Any] | None:
        raw = self.github("pr", "list", "--head", branch, "--state", "open", "--json", "number,url,headRefOid")
        pull_requests = json.loads(raw)
        return pull_requests[0] if pull_requests else None

    def merge_ready_prs(self) -> int:
        """Merge only this pipeline's PRs after current, positive GitHub checks."""
        raw = self.github("pr", "list", "--state", "open", "--label", "agent:auto-merge",
                          "--limit", "100", "--json", "number")
        merged = 0
        for item in json.loads(raw):
            number = int(item["number"])
            pr = json.loads(self.github("pr", "view", str(number), "--json",
                "number,body,baseRefName,headRefName,headRefOid,isDraft,mergeable,mergeStateStatus,statusCheckRollup,labels"))
            body = pr.get("body") or ""
            branch = pr.get("headRefName") or ""
            match = re.fullmatch(r"claude/issue-(\d+)-[a-z0-9-]+", branch)
            pr_labels = labels(pr)
            if ("agent:auto-merge" not in pr_labels or not match
                    or pr.get("baseRefName") != self.default_branch_name()
                    or f"<!-- {RUN_MARKER} -->" not in body
                    or not re.search(rf"\bCloses\s+#{match.group(1)}\b", body, re.IGNORECASE)
                    or pr.get("mergeable") != "MERGEABLE"
                    or pr.get("mergeStateStatus") != "CLEAN"):
                continue
            checks = pr.get("statusCheckRollup") or []
            if (not any(check.get("name") == "TIM full suite" and check.get("conclusion") == "SUCCESS"
                        for check in checks)
                    or any(check.get("conclusion") != "SUCCESS" for check in checks)):
                continue
            if pr.get("isDraft"):
                self.github("pr", "ready", str(number))
            self.github("pr", "merge", str(number), "--squash", "--match-head-commit", pr["headRefOid"])
            merged += 1
        return merged

    def default_branch_name(self) -> str:
        repository = json.loads(self.github("repo", "view", "--json", "defaultBranchRef"))
        name = repository.get("defaultBranchRef", {}).get("name")
        if not name:
            raise PipelineError("GitHub default branch could not be determined.")
        return name

    def ensure_draft_pr(self, candidate: Candidate, branch: str) -> dict[str, Any] | None:
        """Recover only a branch Claude already pushed; never manufacture a branch."""
        pull_request = self.find_draft_pr(branch)
        if pull_request is not None:
            return pull_request
        remote_branch = self.command("git", "ls-remote", "--heads", "origin", branch)
        if not remote_branch.strip():
            return None
        self.github("pr", "create", "--draft", "--head", branch,
                    "--title", f"{candidate.title} (Claude draft)",
                    "--body", f"Closes #{candidate.number}\n\n<!-- {RUN_MARKER} -->")
        return self.find_draft_pr(branch)

    def execute(self, *, dry_run: bool = False, mode: str = "pilot") -> int:
        if not dry_run:
            self.ensure_prerequisites(require_agents=False)
            self.merge_ready_prs()
        self.ensure_prerequisites()
        candidate = choose_candidate(self.list_issues(), mode=mode)
        if candidate is None:
            print("No eligible P0/P1 issue found.")
            return 0
        print(f"Selected #{candidate.number}: {candidate.title}")
        if dry_run:
            return 0
        self.ensure_labels()
        run_id = uuid.uuid4().hex
        self.edit_labels(candidate.number, add="agent:analyzing", remove="agent:retry")
        try:
            base_ref = self.default_base_ref()
            analysis = self.run_analysis(candidate, run_id, base_ref)
            self.edit_labels(candidate.number, add="agent:claude-running", remove="agent:analyzing")
            worktree, branch = self.make_worktree(candidate, run_id, base_ref)
            self.command("claude", "-p", "--output-format", "json", "--max-turns", "30", "--dangerously-skip-permissions",
                         claude_prompt(candidate, analysis, branch), cwd=worktree, timeout=3600)
            pull_request = self.ensure_draft_pr(candidate, branch)
            if pull_request is None:
                raise PipelineError("Claude finished without opening the required draft pull request.")
            self.github("pr", "edit", str(pull_request["number"]), "--add-label", "agent:auto-merge")
            self.comment(candidate.number, f"<!-- {RUN_MARKER} run={run_id} -->\nClaude draft PR: {pull_request['url']}\nBranch: `{branch}`")
            self.edit_labels(candidate.number, add="agent:pr-open", remove="agent:claude-running")
            return 0
        except PipelineError as error:
            self.comment(candidate.number, f"<!-- {RUN_MARKER} run={run_id} status=blocked -->\n## Automation blocked\n\n{error}")
            self.edit_labels(candidate.number, add="agent:blocked", remove="agent:analyzing")
            self.edit_labels(candidate.number, add="agent:blocked", remove="agent:claude-running")
            return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--state-dir", type=Path, default=Path("~/Library/Application Support/TIM GitHub Worker"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--mode", choices=("pilot", "production"), default=os.environ.get("TIM_PIPELINE_MODE", "pilot"))
    parser.add_argument("--setup-labels", action="store_true", help="Create only the additive workflow labels.")
    parser.add_argument("--merge-ready", action="store_true", help="Merge eligible pipeline PRs with passing checks.")
    args = parser.parse_args()
    try:
        with DirectoryLock(args.state_dir.expanduser() / "run.lock"):
            pipeline = Pipeline(args.repository, args.state_dir)
            if args.setup_labels:
                pipeline.ensure_prerequisites(require_agents=False)
                pipeline.ensure_labels()
                return 0
            if args.merge_ready:
                pipeline.ensure_prerequisites(require_agents=False)
                print(f"Merged {pipeline.merge_ready_prs()} eligible PR(s).")
                return 0
            return pipeline.execute(dry_run=args.dry_run, mode=args.mode)
    except PipelineError as error:
        print(f"Pipeline stopped safely: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
