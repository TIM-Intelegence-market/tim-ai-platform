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


UNBYPASSABLE_RULES = {"pull_request", "required_status_checks", "non_fast_forward", "deletion"}


def _validate_required_rulesets(specs: Any) -> None:
    """The rulesets the base branch must be protected by. A bypass applies to every rule of its ruleset, so the
    rules that make checks mandatory may only live in rulesets without any bypass actor."""
    if not isinstance(specs, list) or not specs:
        raise ValueError("required_rulesets must be a non-empty list")
    names: set[str] = set()
    for spec in specs:
        if (not isinstance(spec, dict) or set(spec) != {"name", "rules", "bypass"} or not isinstance(spec["name"], str)
                or not spec["name"] or not isinstance(spec["rules"], list) or not spec["rules"]
                or not all(isinstance(rule, str) and rule for rule in spec["rules"])
                or len(set(spec["rules"])) != len(spec["rules"]) or spec["bypass"] not in {"none", "merger_only"}):
            raise ValueError("every required ruleset needs exactly name, rules and bypass (none or merger_only)")
        if spec["name"] in names:
            raise ValueError("required ruleset names must be unique")
        names.add(spec["name"])
        if spec["bypass"] == "merger_only" and set(spec["rules"]) & UNBYPASSABLE_RULES:
            raise ValueError("a ruleset with a bypass actor must not carry the rules that make checks mandatory")
    protected = {rule for spec in specs if spec["bypass"] == "none" for rule in spec["rules"]}
    if not UNBYPASSABLE_RULES <= protected:
        raise ValueError("pull_request, required_status_checks, non_fast_forward and deletion must all sit in "
                         "rulesets without a bypass actor")


def load_policy(path: Path) -> dict[str, Any]:
    try:
        policy = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(policy["enabled"], bool) or not isinstance(policy["dry_run"], bool):
            raise ValueError("enabled and dry_run must be booleans")
        for key in ("base_branch", "head_branch_regex", "merge_method"):
            if not isinstance(policy[key], str) or not policy[key]:
                raise ValueError(f"{key} must be a non-empty string")
        for key in ("worker_logins", "check_app_slugs", "allowed_conclusions"):
            if not isinstance(policy[key], list) or not all(isinstance(item, str) and item for item in policy[key]):
                raise ValueError(f"{key} must be a list of non-empty strings")
        for key in ("check_app_slugs", "allowed_conclusions", "required_checks"):
            if not policy[key]:
                raise ValueError(f"{key} must not be empty")
        for spec in policy["required_checks"]:
            if (not isinstance(spec, dict) or set(spec) != {"name", "workflow_path", "event"}
                    or not all(isinstance(value, str) and value for value in spec.values())):
                raise ValueError("every required check needs exactly name, workflow_path and event")
        if not policy["required_statuses"]:
            raise ValueError("required_statuses must not be empty")
        for spec in policy["required_statuses"]:
            if (not isinstance(spec, dict) or set(spec) != {"context", "creator", "workflow_path", "event"}
                    or not all(isinstance(value, str) and value for value in spec.values())):
                raise ValueError("every required status needs exactly context, creator, workflow_path and event")
        if len({spec["context"] for spec in policy["required_statuses"]}) != len(policy["required_statuses"]):
            raise ValueError("required status contexts must be unique")
        names = [spec["name"] for spec in policy["required_checks"]]
        if len(set(names)) != len(names):
            raise ValueError("required check names must be unique")
        for key in ("require_rulesets", "require_app_token"):
            if not isinstance(policy[key], bool):
                raise ValueError(f"{key} must be a boolean")
        for key in ("merger_app_id", "check_integration_id"):
            if type(policy[key]) is not int or policy[key] < 0:
                raise ValueError(f"{key} must be a non-negative integer")
        if policy["check_integration_id"] == 0:
            raise ValueError("check_integration_id must be the GitHub Actions app id")
        _validate_required_rulesets(policy["required_rulesets"])
        if not policy["dry_run"] and not (policy["require_rulesets"] and policy["require_app_token"]
                                          and policy["merger_app_id"] > 0):
            raise ValueError("real merges require require_rulesets, require_app_token and a merger_app_id")
        if not policy["dry_run"] and policy["max_merges_per_run"] != 1:
            raise ValueError("real runs merge exactly one pull request per run (max_merges_per_run must be 1)")
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


def run_id_of(check: dict[str, Any], repo: str) -> int | None:
    """Workflow run id from a check's details URL; None when the check cannot be attributed to a run of this repo."""
    match = re.fullmatch(rf"https://github\.com/{re.escape(repo)}/actions/runs/(\d+)/job/\d+",
                         str(check.get("details_url") or ""))
    return int(match.group(1)) if match else None


def status_run_id(url: Any, repo: str) -> int | None:
    match = re.fullmatch(rf"https://github\.com/{re.escape(repo)}/actions/runs/(\d+)", str(url or ""))
    return int(match.group(1)) if match else None


def required_run_ids(checks: Sequence[dict[str, Any]] | None, status: dict[str, Any] | None,
                     policy: dict[str, Any], repo: str) -> list[int]:
    names = {spec["name"] for spec in policy["required_checks"]}
    ids = {run_id_of(check, repo) for check in (checks or []) if check.get("name") in names}
    contexts = {spec["context"] for spec in policy["required_statuses"]}
    ids |= {status_run_id(entry.get("target_url"), repo) for entry in ((status or {}).get("statuses") or [])
            if isinstance(entry, dict) and entry.get("context") in contexts}
    return sorted(run_id for run_id in ids if run_id is not None)


def status_blockers(status: dict[str, Any], runs: dict[int, dict[str, Any]], policy: dict[str, Any],
                    repo: str) -> list[str]:
    """Required commit statuses must be exactly one per context, successful, from the expected creator and workflow."""
    entries = status.get("statuses")
    if not isinstance(entries, list) or (status.get("total_count") or 0) > len(entries):
        return ["commit statuses are incomplete"]
    blockers: list[str] = []
    if entries and status.get("state") != "success":
        blockers.append(f"commit status is {status.get('state')!r}")
    for spec in policy["required_statuses"]:
        matching = [entry for entry in entries if isinstance(entry, dict) and entry.get("context") == spec["context"]]
        if len(matching) != 1:
            blockers.append(f"required status {spec['context']!r} is missing or ambiguous ({len(matching)} entries)")
            continue
        entry = matching[0]
        if entry.get("state") != "success":
            blockers.append(f"required status {spec['context']!r} is {entry.get('state')!r}")
        if (entry.get("creator") or {}).get("login") != spec["creator"]:
            blockers.append(f"required status {spec['context']!r} was not created by {spec['creator']!r}")
        run_id = status_run_id(entry.get("target_url"), repo)
        run = runs.get(run_id) if run_id is not None else None
        if run is None:
            blockers.append(f"required status {spec['context']!r} cannot be attributed to a workflow run of this repository")
        elif run.get("path") != spec["workflow_path"] or run.get("event") != spec["event"]:
            blockers.append(f"required status {spec['context']!r} comes from {run.get('path')!r} on {run.get('event')!r}")
    return blockers


def check_blockers(checks: Sequence[dict[str, Any]] | None, runs: dict[int, dict[str, Any]] | None,
                   status: dict[str, Any] | None, policy: dict[str, Any], sha: str, repo: str) -> list[str]:
    """Checks must be complete and successful, and each required check must come from exactly the expected workflow."""
    if checks is None or runs is None:
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
    for spec in policy["required_checks"]:
        candidates = [run for run in checks if run.get("name") == spec["name"]]
        if not candidates:
            blockers.append(f"required check {spec['name']!r} is missing")
        for candidate in candidates:
            blockers += _identity_blockers(candidate, runs, spec, policy, sha, repo)
    blockers += status_blockers(status, runs, policy, repo)
    return blockers


def _identity_blockers(check: dict[str, Any], runs: dict[int, dict[str, Any]], spec: dict[str, str],
                       policy: dict[str, Any], sha: str, repo: str) -> list[str]:
    name = spec["name"]
    if (check.get("app") or {}).get("slug") not in policy["check_app_slugs"]:
        return [f"check {name!r} is reported by a foreign app (ambiguous)"]
    run_id = run_id_of(check, repo)
    run = runs.get(run_id) if run_id is not None else None
    if run is None:
        return [f"check {name!r} cannot be attributed to a workflow run of this repository (ambiguous)"]
    problems = []
    if run.get("path") != spec["workflow_path"] or run.get("event") != spec["event"]:
        problems.append(f"check {name!r} comes from {run.get('path')!r} on {run.get('event')!r}, expected "
                        f"{spec['workflow_path']!r} on {spec['event']!r} (ambiguous)")
    if run.get("head_sha") != sha:
        problems.append(f"check {name!r} ran for another commit than the evaluated head")
    if (run.get("head_repository") or {}).get("full_name") != repo:
        problems.append(f"check {name!r} ran for a different repository")
    return problems


def _ruleset_blockers(spec: dict[str, Any], listing: list[dict[str, Any]], details: dict[int, dict[str, Any]],
                      effective: list[dict[str, Any]], policy: dict[str, Any]) -> list[str]:
    name = spec["name"]
    found = [entry for entry in listing if isinstance(entry, dict) and entry.get("name") == name]
    if len(found) != 1:
        return [f"ruleset {name!r} is missing or ambiguous ({len(found)} found)"]
    ruleset_id = found[0].get("id")
    ruleset = details.get(ruleset_id) if type(ruleset_id) is int else None
    if not isinstance(ruleset, dict):
        return [f"ruleset {name!r} could not be read"]
    out: list[str] = []
    if ruleset.get("enforcement") != "active":
        out.append(f"ruleset {name!r} is not active (enforcement {ruleset.get('enforcement')!r})")
    if ruleset.get("target") != "branch" or ruleset.get("source_type") != "Repository":
        out.append(f"ruleset {name!r} is not a repository branch ruleset")
    ref_name = (ruleset.get("conditions") or {}).get("ref_name") or {}
    if ref_name.get("include") != [f"refs/heads/{policy['base_branch']}"] or ref_name.get("exclude") != []:
        out.append(f"ruleset {name!r} must target exactly refs/heads/{policy['base_branch']} without exclusions")
    rules = [rule for rule in ruleset.get("rules") or [] if isinstance(rule, dict)]
    types = [rule.get("type") for rule in rules]
    if sorted(map(str, types)) != sorted(spec["rules"]):
        out.append(f"ruleset {name!r} has rules {sorted(map(str, types))}, expected exactly {sorted(spec['rules'])}")
    actors = ruleset.get("bypass_actors")
    if spec["bypass"] == "none":
        if actors != []:
            out.append(f"ruleset {name!r} must have no bypass actors (found {actors!r})")
    else:
        expected = {"actor_id": policy["merger_app_id"], "actor_type": "Integration", "bypass_mode": "always"}
        if (not isinstance(actors, list) or len(actors) != 1 or not isinstance(actors[0], dict)
                or {key: actors[0].get(key) for key in expected} != expected):
            out.append(f"ruleset {name!r} must have exactly one bypass actor: the merger app {policy['merger_app_id']}")
    by_type = {rule.get("type"): rule for rule in rules}
    if "required_status_checks" in by_type:
        out += _status_check_rule_blockers(name, by_type["required_status_checks"].get("parameters") or {}, policy)
    if "pull_request" in by_type:
        if (by_type["pull_request"].get("parameters") or {}).get("required_approving_review_count") != 0:
            out.append(f"ruleset {name!r} must require zero human approvals (the pipeline merges without review)")
    for kind in spec["rules"]:
        if not any(isinstance(rule, dict) and rule.get("type") == kind and rule.get("ruleset_id") == ruleset_id
                   for rule in effective):
            out.append(f"rule {kind!r} of ruleset {name!r} is not effective on {policy['base_branch']}")
    return out


def _status_check_rule_blockers(name: str, parameters: dict[str, Any], policy: dict[str, Any]) -> list[str]:
    out: list[str] = []
    if parameters.get("strict_required_status_checks_policy") is not True:
        out.append(f"ruleset {name!r} does not require an up-to-date branch (strict policy)")
    entries = [entry for entry in parameters.get("required_status_checks") or [] if isinstance(entry, dict)]
    needed = {spec["name"] for spec in policy["required_checks"]} | {spec["context"] for spec in policy["required_statuses"]}
    for context in sorted(needed):
        matching = [entry for entry in entries if entry.get("context") == context]
        if not matching:
            out.append(f"{context!r} is not a required status check of ruleset {name!r}")
        elif any(entry.get("integration_id") != policy["check_integration_id"] for entry in matching):
            out.append(f"required check {context!r} is not bound to the GitHub Actions app")
    return out


def rulesets_blockers(listing: Any, details: dict[int, dict[str, Any]] | None, effective: Any,
                      policy: dict[str, Any]) -> list[str]:
    """GitHub must report, with their bypass configuration, the rulesets that make the guarantees real."""
    if not isinstance(listing, list) or not isinstance(details, dict) or not isinstance(effective, list):
        return ["rulesets unavailable"]
    blockers: list[str] = []
    for spec in policy["required_rulesets"]:
        blockers += _ruleset_blockers(spec, listing, details, effective, policy)
    return blockers


def fetch_rulesets(api: Any, policy: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[int, dict[str, Any]], Any]:
    listing = api.rulesets()
    wanted = {spec["name"] for spec in policy["required_rulesets"]}
    ids = sorted({entry["id"] for entry in listing if isinstance(entry, dict) and entry.get("name") in wanted
                  and type(entry.get("id")) is int})
    return listing, {ruleset_id: api.ruleset(ruleset_id) for ruleset_id in ids}, api.branch_rules(policy["base_branch"])


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
           number: int, merge_guard: Callable[[], list[str]] | None = None) -> Decision:
    """Evaluate one PR and, when allowed by the policy, take exactly one step towards merging it."""
    try:
        pr = api.pull(number)
        sha = str((pr.get("head") or {}).get("sha") or "")
        reasons = pr_blockers(pr, policy, repo)
        if not reasons:
            comparison = api.compare(policy["base_branch"], sha) or {}
            behind = comparison.get("behind_by")
            merge_base = (comparison.get("merge_base_commit") or {}).get("sha")
            if type(behind) is not int or behind != 0:
                reasons.append(f"head is not up to date with {policy['base_branch']} (behind_by={behind!r}); "
                               "the checked tree would differ from the merged tree")
        if not reasons:
            checks, status = api.check_runs(sha), api.commit_status(sha)
            ids = required_run_ids(checks, status, policy, repo)
            runs = {run_id: api.workflow_run(run_id) for run_id in ids} if len(ids) <= 20 else None
            reasons += check_blockers(checks, runs, status, policy, sha, repo)
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
        again = api.compare(policy["base_branch"], sha) or {}
        if again.get("behind_by") != 0 or type(again.get("behind_by")) is not int \
                or (again.get("merge_base_commit") or {}).get("sha") != merge_base:
            return Decision(number, "blocked", sha, ["base branch moved during evaluation"])
        if merge_guard is not None:  # the protection rules are re-read right before every merge, not once per run
            problems = merge_guard()
            if problems:
                return Decision(number, "blocked", sha, [f"rulesets: {item}" for item in problems])
        if policy["dry_run"]:
            return Decision(number, "would-merge", sha)
        api.merge(number, sha, policy["merge_method"])
        return Decision(number, "merged", sha)
    except Exception as error:  # fail closed on every error, including malformed API data
        return Decision(number, "blocked", "", [f"{type(error).__name__}: {error}"[:300]])


def run(api: Any, gate: Callable[[dict[str, Any]], list[str]], policy: dict[str, Any], repo: str,
        emit: Callable[[str], None] = print, token_kind: str = "unknown") -> int:
    if not policy["enabled"]:
        emit("auto-merge controller is disabled by policy; nothing was evaluated.")
        return 0
    if not policy["dry_run"] and policy["require_app_token"] and token_kind != "app":
        emit(f"controller failed closed: real merges need a GitHub App token for the merger identity (token kind: {token_kind!r}).")
        return 1
    try:
        if policy["require_rulesets"]:
            problems = rulesets_blockers(*fetch_rulesets(api, policy), policy)
            if problems:
                emit(json.dumps({"scope": "rulesets", "outcome": "blocked", "reasons": problems}))
                return 1
    except Exception as error:  # fail closed on every error while reading the protection rules
        emit(f"controller failed closed: {type(error).__name__}: {error}"[:400])
        return 1
    try:
        candidates = [pr for pr in api.open_pulls(policy["base_branch"]) if is_worker_pr(pr, policy)]
    except ControllerError as error:
        emit(f"controller failed closed: {error}")
        return 1
    def guard() -> list[str]:
        return rulesets_blockers(*fetch_rulesets(api, policy), policy) if policy["require_rulesets"] else []

    merged = 0
    for pr in sorted(candidates, key=lambda item: int(item["number"])):
        decision = decide(api, gate, policy, repo, int(pr["number"]), guard)
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
        return self._pages(f"repos/{self.repo}/commits/{self._sha(sha)}/check-runs?filter=latest", "check_runs")

    def workflow_run(self, run_id: int) -> dict[str, Any]:
        return self._gh(f"repos/{self.repo}/actions/runs/{self._number(run_id)}")

    def commit_status(self, sha: str) -> dict[str, Any]:
        return self._gh(f"repos/{self.repo}/commits/{self._sha(sha)}/status?per_page=100")

    def compare(self, base: str, sha: str) -> dict[str, Any]:
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", base):
            raise ControllerError("unsafe base branch name")
        return self._gh(f"repos/{self.repo}/compare/{base}...{self._sha(sha)}")

    def rulesets(self) -> list[dict[str, Any]]:
        return self._pages(f"repos/{self.repo}/rulesets?includes_parents=true", None)

    def ruleset(self, ruleset_id: int) -> dict[str, Any]:
        return self._gh(f"repos/{self.repo}/rulesets/{self._number(ruleset_id)}")

    def branch_rules(self, branch: str) -> list[dict[str, Any]]:
        if not re.fullmatch(r"[A-Za-z0-9._-]+", branch):
            raise ControllerError("unsafe branch name")
        return self._gh(f"repos/{self.repo}/rules/branches/{branch}")

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
    parser.add_argument("--verify-rulesets", action="store_true",
                        help="Read-only: check the rulesets and their bypass actors against the policy and exit.")
    args = parser.parse_args(argv)
    if args.verify_rulesets:
        try:
            policy = load_policy(args.policy)
            problems = rulesets_blockers(*fetch_rulesets(GhApi(args.repo), policy), policy)
        except ControllerError as error:
            print(f"verification failed closed: {error}", file=sys.stderr)
            return 1
        print(json.dumps({"scope": "rulesets", "ok": not problems, "problems": problems}))
        return 1 if problems else 0
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
    return run(api, gate, policy, args.repo, token_kind=os.environ.get("TIM_MERGER_TOKEN_KIND", "unknown"))


if __name__ == "__main__":
    raise SystemExit(main())
