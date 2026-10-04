#!/usr/bin/env python3
"""Fail-closed merge controller for pull requests opened by the worker identity.

Runs from the base branch (see .github/workflows/auto-merge-controller.yml), so a pull request cannot change
the rules it is judged by. It never reads PR text, labels or comments: eligibility comes from the PR author
login, the head branch and repository, the exact head SHA, the checks reported for that SHA and a fresh run
of the path gate on the PR's diff. Any unknown state, missing check, moved SHA or API error blocks the merge.

Inactive by default: the shipped policy has `enabled: false`, `dry_run: true` and no worker login.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

try:
    from scripts import pr_gate
except ImportError:  # executed as a plain script
    import pr_gate  # type: ignore[no-redef]

SHA = re.compile(r"[0-9a-f]{40}")
DRAFT_OK_STATES = {"draft", "clean"}
MERGE_METHODS = {"squash", "merge", "rebase"}
PAGE = 100
MAX_PAGES = 10


class ControllerError(RuntimeError):
    """The controller cannot reach a safe verdict; the run fails and nothing is merged."""


class ApiError(ControllerError):
    """A GitHub API call failed."""


def load_policy(path: Path) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(policy["enabled"], bool) or not isinstance(policy["dry_run"], bool):
            raise ValueError("enabled and dry_run must be booleans")
        for key in ("base_branch", "head_branch_regex", "merge_method"):
            if not isinstance(policy[key], str) or not policy[key]:
                raise ValueError(f"{key} must be a non-empty string")
        for key in ("worker_logins", "required_checks", "check_app_slugs", "allowed_conclusions"):
            if not isinstance(policy[key], list) or not all(isinstance(item, str) and item for item in policy[key]):
                raise ValueError(f"{key} must be a list of non-empty strings")
        for key in ("required_checks", "check_app_slugs", "allowed_conclusions"):
            if not policy[key]:
                raise ValueError(f"{key} must not be empty")
        if policy["merge_method"] not in MERGE_METHODS:
            raise ValueError("merge_method must be squash, merge or rebase")
        if type(policy["max_merges_per_run"]) is not int or not 1 <= policy["max_merges_per_run"] <= 5:
            raise ValueError("max_merges_per_run must be an integer from 1 to 5")
        re.compile(policy["head_branch_regex"])
    except (OSError, ValueError, KeyError, TypeError, re.error) as error:
        raise ControllerError(f"policy unreadable or invalid: {error!r}") from error
    return policy


def _login(pr: dict[str, Any]) -> str:
    return str((pr.get("user") or {}).get("login") or "").casefold()


def is_worker_pr(pr: dict[str, Any], policy: dict[str, Any]) -> bool:
    """Cheap pre-filter. Identity and base only: never text, labels or comments."""
    workers = {login.casefold() for login in policy["worker_logins"]}
    return bool(workers) and _login(pr) in workers and (pr.get("base") or {}).get("ref") == policy["base_branch"]


def check_blockers(checks: Sequence[dict[str, Any]] | None, status: dict[str, Any] | None,
                   policy: dict[str, Any]) -> list[str]:
    if checks is None:
        return ["check runs unavailable"]
    if status is None:
        return ["commit statuses unavailable"]
    allowed = set(policy["allowed_conclusions"])
    blockers: list[str] = []
    for run in checks:
        name = run.get("name")
        if run.get("status") != "completed":
            blockers.append(f"check {name!r} is {run.get('status')!r}, not completed")
        elif run.get("conclusion") not in allowed:
            blockers.append(f"check {name!r} concluded {run.get('conclusion')!r}")
    for required in policy["required_checks"]:
        good = [run for run in checks if run.get("name") == required and run.get("status") == "completed"
                and run.get("conclusion") in allowed and (run.get("app") or {}).get("slug") in policy["check_app_slugs"]]
        if not good:
            blockers.append(f"required check {required!r} is missing or not reported by an allowed app")
    if status.get("total_count") and status.get("state") != "success":
        blockers.append(f"commit status is {status.get('state')!r}")
    return blockers


def pr_blockers(pr: dict[str, Any], policy: dict[str, Any], repo: str) -> list[str]:
    """Every reason this PR must not be merged right now; an empty list means eligible."""
    blockers: list[str] = []
    head, base = pr.get("head") or {}, pr.get("base") or {}
    if pr.get("state") != "open" or pr.get("merged"):
        blockers.append("pull request is not open")
    if base.get("ref") != policy["base_branch"]:
        blockers.append(f"base branch is {base.get('ref')!r}")
    if (head.get("repo") or {}).get("full_name") != repo:
        blockers.append("head is not in this repository")
    if not re.fullmatch(policy["head_branch_regex"], str(head.get("ref") or "")):
        blockers.append("head branch name does not match the worker pattern")
    if not SHA.fullmatch(str(head.get("sha") or "")):
        blockers.append("head SHA is missing or malformed")
    if _login(pr) not in {login.casefold() for login in policy["worker_logins"]}:
        blockers.append("author is not a configured worker identity")
    if pr.get("mergeable") is not True:
        blockers.append(f"mergeable is {pr.get('mergeable')!r}")
    state = pr.get("mergeable_state")
    if state not in (DRAFT_OK_STATES if pr.get("draft") else {"clean"}):
        blockers.append(f"mergeable_state is {state!r}")
    return blockers


@dataclass
class Decision:
    number: int
    outcome: str  # skipped | blocked | would-mark-ready | marked-ready | would-merge | merged
    sha: str = ""
    reasons: list[str] = field(default_factory=list)

    def line(self) -> str:
        return json.dumps({"pr": self.number, "sha": self.sha, "outcome": self.outcome, "reasons": self.reasons})


def decide(api: Any, gate: Callable[[dict[str, Any]], list[str]], policy: dict[str, Any], repo: str,
           number: int) -> Decision:
    """Evaluate one PR and, when allowed by the policy, take exactly one step towards merging it."""
    try:
        pr = api.pull(number)
        sha = str((pr.get("head") or {}).get("sha") or "")
        reasons = pr_blockers(pr, policy, repo)
        if not reasons:
            behind = (api.compare(policy["base_branch"], sha) or {}).get("behind_by")
            if type(behind) is not int or behind != 0:
                reasons.append(f"head is not up to date with {policy['base_branch']} (behind_by={behind!r}); "
                               "the checked tree would differ from the merged tree")
        if not reasons:
            reasons += check_blockers(api.check_runs(sha), api.commit_status(sha), policy)
        if not reasons:
            reasons += [f"gate: {item}" for item in gate(pr)]
        if reasons:
            return Decision(number, "blocked", sha, reasons)
        if pr.get("draft"):
            if policy["dry_run"]:
                return Decision(number, "would-mark-ready", sha)
            api.mark_ready(pr["node_id"])  # the next run re-evaluates the ready PR and merges it
            return Decision(number, "marked-ready", sha)
        fresh = api.pull(number)
        if (fresh.get("head") or {}).get("sha") != sha or fresh.get("state") != "open" \
                or fresh.get("mergeable_state") != "clean":
            return Decision(number, "blocked", sha, ["pull request changed during evaluation"])
        if policy["dry_run"]:
            return Decision(number, "would-merge", sha)
        api.merge(number, sha, policy["merge_method"])
        return Decision(number, "merged", sha)
    except Exception as error:  # fail closed on every error, including malformed API data
        return Decision(number, "blocked", "", [f"{type(error).__name__}: {error}"[:300]])


def run(api: Any, gate: Callable[[dict[str, Any]], list[str]], policy: dict[str, Any], repo: str,
        emit: Callable[[str], None] = print) -> int:
    if not policy["enabled"]:
        emit("auto-merge controller is disabled by policy; nothing was evaluated.")
        return 0
    try:
        candidates = [pr for pr in api.open_pulls(policy["base_branch"]) if is_worker_pr(pr, policy)]
    except ControllerError as error:
        emit(f"controller failed closed: {error}")
        return 1
    merged = 0
    for pr in sorted(candidates, key=lambda item: int(item["number"])):
        decision = decide(api, gate, policy, repo, int(pr["number"]))
        emit(decision.line())
        if decision.outcome in {"merged", "would-merge"}:
            merged += 1
            if merged >= policy["max_merges_per_run"]:
                break  # later PRs are evaluated against the new base in the next run
    emit(f"evaluated {len(candidates)} worker pull request(s); dry_run={policy['dry_run']}")
    return 0


class GhApi:
    """Thin wrapper over `gh api`; every request is built from validated numbers and SHAs only."""

    def __init__(self, repo: str, runner: Callable[..., Any] = subprocess.run) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise ControllerError("repository must look like owner/name")
        self.repo, self.runner = repo, runner

    def _gh(self, *args: str) -> Any:
        try:
            completed = self.runner(["gh", "api", *args], check=True, text=True, capture_output=True, timeout=90)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
            raise ApiError(str(getattr(error, "stderr", "") or error)[:500]) from error
        try:
            return json.loads(completed.stdout) if completed.stdout.strip() else None
        except ValueError as error:
            raise ApiError("GitHub returned unparseable JSON") from error

    @staticmethod
    def _number(value: Any) -> int:
        if type(value) is not int or value <= 0:
            raise ControllerError("pull request number must be a positive integer")
        return value

    @staticmethod
    def _sha(value: Any) -> str:
        if not isinstance(value, str) or not SHA.fullmatch(value):
            raise ControllerError("not a full commit SHA")
        return value

    def _pages(self, path: str, key: str | None) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        total = None
        for page in range(1, MAX_PAGES + 1):
            data = self._gh(f"{path}{'&' if '?' in path else '?'}per_page={PAGE}&page={page}")
            batch = data.get(key) if key else data
            if not isinstance(batch, list):
                raise ApiError("unexpected response shape")
            items += batch
            total = data.get("total_count") if key else None
            if len(batch) < PAGE or (total is not None and len(items) >= total):
                break
        else:
            raise ApiError("too many pages; refusing to decide on partial data")
        if total is not None and len(items) < total:
            raise ApiError("incomplete check list")
        return items

    def open_pulls(self, base: str) -> list[dict[str, Any]]:
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", base):
            raise ControllerError("unsafe base branch name")
        return self._pages(f"repos/{self.repo}/pulls?state=open&base={base}", None)

    def pull(self, number: int) -> dict[str, Any]:
        return self._gh(f"repos/{self.repo}/pulls/{self._number(number)}")

    def check_runs(self, sha: str) -> list[dict[str, Any]]:
        return self._pages(f"repos/{self.repo}/commits/{self._sha(sha)}/check-runs", "check_runs")

    def commit_status(self, sha: str) -> dict[str, Any]:
        return self._gh(f"repos/{self.repo}/commits/{self._sha(sha)}/status")

    def compare(self, base: str, sha: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", base):
            raise ControllerError("unsafe base branch name")
        return self._gh(f"repos/{self.repo}/compare/{base}...{self._sha(sha)}")

    def mark_ready(self, node_id: str) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_=-]+", str(node_id)):
            raise ControllerError("unsafe node id")
        self._gh("graphql", "-f", "query=mutation($id:ID!){markPullRequestReadyForReview(input:{pullRequestId:$id})"
                 "{pullRequest{id}}}", "-f", f"id={node_id}")

    def merge(self, number: int, sha: str, method: str) -> None:
        if method not in MERGE_METHODS:
            raise ControllerError("unknown merge method")
        # `sha` makes GitHub itself refuse the merge (409) when the head moved after evaluation.
        self._gh("-X", "PUT", f"repos/{self.repo}/pulls/{self._number(number)}/merge",
                 "-f", f"sha={self._sha(sha)}", "-f", f"merge_method={method}")


def make_gate(repository: Path, gate_policy_path: Path,
              runner: Callable[..., Any] = subprocess.run) -> Callable[[dict[str, Any]], list[str]]:
    """Re-run the path gate on the exact head SHA, using the policy from the base checkout."""
    gate_policy = pr_gate.load_policy(gate_policy_path)

    def git(*args: str) -> str:
        return runner(["git", *args], cwd=repository, check=True, text=True, capture_output=True,
                      timeout=300).stdout.strip()

    def gate(pr: dict[str, Any]) -> list[str]:
        number, head, base = int(pr["number"]), str(pr["head"]["sha"]), str(pr["base"]["sha"])
        if not SHA.fullmatch(head) or not SHA.fullmatch(base):
            return ["malformed SHA"]
        git("fetch", "--no-tags", "origin", f"refs/pull/{number}/head")
        if git("rev-parse", "FETCH_HEAD") != head:
            return ["fetched head differs from the evaluated head SHA"]
        return pr_gate.evaluate(pr_gate.diff_entries(repository, base, head), gate_policy)

    return gate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--policy", type=Path, required=True, help="merge policy taken from the base branch")
    parser.add_argument("--gate-policy", type=Path, required=True, help="path-gate policy taken from the base branch")
    parser.add_argument("--repository", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    try:
        policy = load_policy(args.policy)
        if not policy["enabled"]:
            print("auto-merge controller is disabled by policy; nothing was evaluated.")
            return 0
        api = GhApi(args.repo)
        gate = make_gate(args.repository, args.gate_policy)
    except (ControllerError, pr_gate.GateError) as error:
        print(f"controller failed closed: {error}", file=sys.stderr)
        return 1
    return run(api, gate, policy, args.repo)


if __name__ == "__main__":
    raise SystemExit(main())
