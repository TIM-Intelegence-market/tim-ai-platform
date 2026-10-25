#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, TextIO

SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|password|secret|authorization)\s*[:=]\s*[^\s,;]+")
DEFAULT_BLOCKER_ISSUE = 12
DEFAULT_MAX_LOCAL_REPAIR_CYCLES = 2

HARD_BLOCKER_MARKERS = (
    "sandbox env gate is closed",
    "sandbox marker missing",
    "snapshot drift:",
    "unsafe contract path",
    "path not allowed:",
    "patch path not allowlisted:",
    "forbidden code intent:",
    "hash mismatch:",
    "production database",
    "live trading",
    "execution enabled",
)

LOCAL_REPAIR_MARKERS = (
    "QWEN_REPAIR_EXHAUSTED:",
    "verification failed; rolled back",
    "QWEN_ERROR:TimeoutError",
    "QWEN_ERROR:OSError",
    "LOCAL_QWEN_UNAVAILABLE",
    "developer exited",
    "LOCAL_ACCEPTANCE_FAILED:",
)


def _child_env(repo: Path) -> dict[str, str]:
    current = os.environ.get("PYTHONPATH", "")
    pythonpath = str(repo) if not current else str(repo) + os.pathsep + current
    return {
        **os.environ,
        "PYTHONPATH": pythonpath,
        "TIM_LIVE_TRADING": "0",
        "TIM_EXECUTION_ENABLED": "0",
    }


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temp = Path(handle.name)
    temp.replace(path)


def _safe_text(value: Any, limit: int = 3000) -> str:
    return SECRET_RE.sub(r"\1=<REDACTED>", str(value))[:limit]



def _valid_external_resolution(state: Path, task_id: str) -> bool:
    """Fail closed unless a resolution is valid for this exact task."""
    path = state / "blockers/resolutions" / f"{task_id}.json"
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if (
        isinstance(payload, dict)
        and payload.get("kind") == "BLOCKER_RESOLVED"
        and str(payload.get("task_id")) == task_id
        and payload.get("authority") == "LOCAL_SAFETY_GATES"
    ):
        return True
    if isinstance(payload, dict) and payload.get("kind") == "BLOCKER_PROPOSAL":
        from src.local_first.provider_broker import ProviderBroker, valid_router_proposal
        try:
            request, _, _ = ProviderBroker(state)._request(task_id)
        except (OSError, ValueError):
            return False
        return valid_router_proposal(path, task_id, request)
    return False

def _closure_policy(task_id: str) -> dict[str, Any]:
    return {
        "primary_objective": "Reduce the existing TIM backlog by completing this task end-to-end.",
        "current_task": task_id,
        "wip_limit": 1,
        "task_creation": "FORBIDDEN_FOR_INTERNAL_STEPS",
        "decomposition": "INTERNAL_CHECKPOINTS_ONLY",
        "completion_rule": "Do not switch tasks. Repair, test and verify this same task until its local acceptance gate passes or a genuine external blocker requires escalation.",
        "quality_rule": "Prefer the smallest correct implementation with targeted regression tests; activity without closure has zero value.",
        "escalation_rule": "Known/local errors stay inside the same task. Only genuinely unknown or unsafe blockers are escalated; after resolution resume the same task.",
        "success_metric": "TASK_CLOSURE_RATE",
    }


def _with_closure_policy(payload: dict[str, Any], task_id: str) -> dict[str, Any]:
    enriched = dict(payload)
    enriched["execution_policy"] = _closure_policy(task_id)
    enriched["next_action"] = str(enriched.get("next_action") or "Complete current task end-to-end")
    return enriched


def _closure_metrics(completed: int, initial: int, remaining: int) -> dict[str, Any]:
    rate = 1.0 if initial == 0 else completed / initial
    return {
        "completed_this_run": completed,
        "initial_tasks": initial,
        "remaining": remaining,
        "task_closure_rate": round(rate, 4),
        "task_closure_percent": round(rate * 100.0, 1),
        "wip": 1 if remaining > 0 else 0,
    }


def _acquire_supervisor_lock(state: Path) -> TextIO | None:
    """Enforce exactly one local build-queue supervisor process."""
    state.mkdir(parents=True, exist_ok=True)
    path = state / "supervisor.lock"
    handle = path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid={os.getpid()}\n")
    handle.flush()
    return handle


def _release_supervisor_lock(handle: TextIO | None) -> None:
    if handle is None:
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _safe_repo_file(repo: Path, relative: str) -> Path | None:
    rel = Path(relative)
    if not relative or rel.is_absolute() or ".." in rel.parts or "\\" in relative:
        return None
    candidate = (repo / rel).resolve()
    if candidate == repo or repo not in candidate.parents:
        return None
    return candidate


def _git_head(repo: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    return completed.stdout.strip() if completed.returncode == 0 else "UNKNOWN"


def _acceptance_gate(repo: Path, state: Path, task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Deterministically decide whether a VERIFYING developer result is actually FIXED.

    This gate does not ask Qwen for an opinion and does not touch a database. It only validates
    evidence already produced by the deterministic local patch executor plus filesystem state.
    """
    task_id = str(task.get("task_id", "unknown"))
    allowed_paths_raw = task.get("allowed_paths", [])
    allowed_paths = allowed_paths_raw if isinstance(allowed_paths_raw, list) else []
    allowed_set = {str(item) for item in allowed_paths if isinstance(item, str)}

    tests = result.get("tests") if isinstance(result.get("tests"), dict) else {}
    required_tests_raw = result.get("required_tests", [])
    required_tests = required_tests_raw if isinstance(required_tests_raw, list) else []
    executed_tests_raw = tests.get("tests", [])
    executed_tests = executed_tests_raw if isinstance(executed_tests_raw, list) else []

    changed_raw = result.get("changed", [])
    changed = changed_raw if isinstance(changed_raw, list) else []
    changed_paths = [str(item.get("path")) for item in changed if isinstance(item, dict) and item.get("path")]
    meaningful_change = any(
        isinstance(item, dict)
        and item.get("before_sha256")
        and item.get("after_sha256")
        and item.get("before_sha256") != item.get("after_sha256")
        for item in changed
    )

    required_outputs_raw = result.get("required_outputs", [])
    required_outputs = required_outputs_raw if isinstance(required_outputs_raw, list) else []
    output_paths = [_safe_repo_file(repo, str(relative)) for relative in required_outputs]

    from src.local_first.sandbox_runner import ENFORCING_KINDS, configured_mode

    checks = {
        "developer_status_verifying": result.get("status") == "VERIFYING",
        # When the sandbox is required, the passing test run must have happened inside it.
        "test_sandbox_enforced": configured_mode() != "required" or tests.get("sandbox") in ENFORCING_KINDS,
        "rollback_false": result.get("rollback") is False,
        "authority_local_safety_gates": result.get("authority") == "LOCAL_SAFETY_GATES",
        "targeted_tests_passed": tests.get("returncode") == 0,
        "required_tests_match": bool(required_tests) and executed_tests == required_tests,
        "changed_paths_allowlisted": bool(changed_paths) and all(path in allowed_set for path in changed_paths),
        "meaningful_change": meaningful_change,
        "required_outputs_safe": all(path is not None for path in output_paths),
        "required_outputs_exist": all(path is not None and path.is_file() for path in output_paths),
        "required_outputs_touched": all(str(relative) in changed_paths for relative in required_outputs),
        "live_trading_disabled": _child_env(repo).get("TIM_LIVE_TRADING") == "0",
        "execution_disabled": _child_env(repo).get("TIM_EXECUTION_ENABLED") == "0",
    }
    failed = [name for name, passed in checks.items() if not passed]
    hard_failures = {
        "test_sandbox_enforced",
        "rollback_false",
        "authority_local_safety_gates",
        "changed_paths_allowlisted",
        "required_outputs_safe",
        "live_trading_disabled",
        "execution_disabled",
    }
    passed = not failed
    repairable = not any(name in hard_failures for name in failed)

    evidence = {
        "schema_version": 1,
        "kind": "LOCAL_TASK_ACCEPTANCE",
        "task_id": task_id,
        "status": "FIXED" if passed else "BLOCKED",
        "passed": passed,
        "repairable": repairable,
        "failed_checks": failed,
        "checks": checks,
        "changed": changed,
        "tests": {
            "returncode": tests.get("returncode"),
            "sandbox": tests.get("sandbox"),
            "tests": executed_tests,
            "python": _safe_text(tests.get("python", ""), 1200),
            "stdout": _safe_text(tests.get("stdout", ""), 4000),
            "stderr": _safe_text(tests.get("stderr", ""), 4000),
        },
        "required_outputs": [str(item) for item in required_outputs],
        "required_tests": [str(item) for item in required_tests],
        "git_head": _git_head(repo),
        "authority": "TIM_LOCAL_SUPERVISOR",
        "live_trading": "DISABLED",
        "execution": "DISABLED",
        "at_unix_ms": int(time.time() * 1000),
    }
    serialized = json.dumps(evidence, sort_keys=True, default=str).encode("utf-8")
    evidence["evidence_sha256"] = hashlib.sha256(serialized).hexdigest()
    _atomic_json(state / "acceptance-results" / f"{task_id}.json", evidence)
    return evidence


def _blocker_class(result: dict[str, Any]) -> str:
    reason = str(result.get("reason", ""))
    if any(marker.lower() in reason.lower() for marker in HARD_BLOCKER_MARKERS):
        return "HARD_BLOCKER"
    if any(marker.lower() in reason.lower() for marker in LOCAL_REPAIR_MARKERS):
        return "LOCAL_REPAIRABLE"
    acceptance = result.get("acceptance")
    if isinstance(acceptance, dict) and acceptance.get("repairable") is True:
        return "LOCAL_REPAIRABLE"
    return "HARD_BLOCKER"


def _repair_feedback(result: dict[str, Any]) -> str:
    tests = result.get("tests") if isinstance(result.get("tests"), dict) else {}
    parts = [f"Previous supervisor cycle failed: {_safe_text(result.get('reason', 'unknown'), 1400)}"]

    # pytest may emit the useful traceback to stdout rather than stderr.
    # Preserve the tail because the final exception/summary is usually there.
    stderr = _safe_text(str(tests.get("stderr", ""))[-4000:], 4000)
    stdout = _safe_text(str(tests.get("stdout", ""))[-6000:], 6000)

    if stderr:
        parts.append(f"Targeted test stderr: {stderr}")
    if stdout:
        parts.append(f"Targeted test stdout: {stdout}")

    acceptance = result.get("acceptance")
    if isinstance(acceptance, dict) and acceptance.get("failed_checks"):
        parts.append("Acceptance failed checks: " + ", ".join(map(str, acceptance["failed_checks"])))

    parts.append(
        "Repair the same task only. Do not create a subtask and do not weaken safety gates."
    )
    return "\n".join(parts)


def _blocker_request(task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    task_id = str(task.get("task_id", "unknown"))
    tests = result.get("tests") if isinstance(result.get("tests"), dict) else {}
    evidence = [f"reason={_safe_text(result.get('reason', 'unknown'), 1200)}"]
    if tests:
        evidence.append(f"test_returncode={tests.get('returncode')}")
        stderr = _safe_text(tests.get("stderr", ""), 2000)
        if stderr:
            evidence.append(f"test_stderr={stderr}")
    fingerprint_source = json.dumps(
        {
            "task_id": task_id,
            "reason": result.get("reason"),
            "stderr": tests.get("stderr") if isinstance(tests, dict) else None,
        },
        sort_keys=True,
        default=str,
    )
    request_id = hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()[:20]
    return {
        "schema_version": 1,
        "kind": "BLOCKER_REQUEST",
        "request_id": request_id,
        "task_id": task_id,
        "objective": _safe_text(task.get("objective", "local TIM task"), 2500),
        "blocker_reason": _safe_text(result.get("reason", "unknown blocker"), 1600),
        "next_action": _safe_text(result.get("next_action", task.get("next_action", "resolve blocker and retry")), 1600),
        "risk": str(task.get("risk", "A3"))[:20],
        "evidence": evidence[:6],
        "authority": "LOCAL_SAFETY_GATES",
    }


def _escalation_issue(task: dict[str, Any], fallback_issue: int) -> tuple[int, bool]:
    linked_issue = task.get("issue_number")
    if (isinstance(linked_issue, int) and not isinstance(linked_issue, bool) and linked_issue > 0
            and task.get("task_id") == f"github-issue-{linked_issue}"):
        return linked_issue, True
    return fallback_issue, False


def _publish_blocker(repo: Path, state: Path, task: dict[str, Any], result: dict[str, Any], issue: int) -> bool:
    request = _blocker_request(task, result)
    task_id = str(request["task_id"])
    request_id = str(request["request_id"])
    issue, escalate = _escalation_issue(task, issue)
    requests = state / "blockers/requests"
    published = state / "blockers/published"
    request_path = requests / f"{task_id}.{request_id}.json"
    marker = published / f"{task_id}.{request_id}.json"
    _atomic_json(request_path, request)
    if marker.exists():
        return True
    bridge = repo / "scripts/github_blocker_bridge.py"
    if shutil.which("gh") is None or not bridge.is_file():
        print(json.dumps({"TIM_BLOCKER_BRIDGE": "LOCAL_ONLY", "task_id": task_id, "reason": "gh or bridge unavailable"}), flush=True)
        return False
    command = [sys.executable, str(bridge), "publish", "--request", str(request_path), "--issue", str(issue)]
    if escalate:
        command.append("--escalate")
    completed = subprocess.run(
        command,
        cwd=repo,
        env=_child_env(repo),
        text=True,
        capture_output=True,
        check=False,
        timeout=45,
    )
    if completed.returncode != 0:
        print(json.dumps({"TIM_BLOCKER_BRIDGE": "PUBLISH_FAILED", "task_id": task_id, "returncode": completed.returncode}), flush=True)
        return False
    _atomic_json(marker, {"task_id": task_id, "request_id": request_id, "issue": issue, "published": True})
    print(json.dumps({"TIM_BLOCKER_BRIDGE": "PUBLISHED", "task_id": task_id, "issue": issue}), flush=True)
    return True


def _pull_resolution(repo: Path, state: Path, task_id: str, issue: int) -> bool:
    bridge = repo / "scripts/github_blocker_bridge.py"
    output = state / "blockers/resolutions" / f"{task_id}.json"
    completed = subprocess.run(
        [sys.executable, str(bridge), "pull", "--task-id", task_id, "--issue", str(issue), "--output", str(output)],
        cwd=repo,
        env=_child_env(repo),
        text=True,
        capture_output=True,
        check=False,
        timeout=45,
    )
    return completed.returncode == 0 and output.is_file()


def _wait_for_resolution(repo: Path, state: Path, task_id: str, issue: int) -> bool:
    interval = max(10.0, float(os.getenv("TIM_BLOCKER_POLL_SECONDS", "30")))
    print(json.dumps({
        "TIM_BLOCKER_BRIDGE": "WAITING_FOR_CHATGPT_RESOLUTION",
        "task_id": task_id,
        "issue": issue,
        "instruction": "In ChatGPT say only: Blocker prüfen",
    }), flush=True)
    try:
        while True:
            if _pull_resolution(repo, state, task_id, issue):
                print(json.dumps({"TIM_BLOCKER_BRIDGE": "RESOLUTION_RECEIVED", "task_id": task_id}), flush=True)
                return True
            time.sleep(interval)
    except KeyboardInterrupt:
        print(json.dumps({"TIM_BLOCKER_BRIDGE": "WAIT_CANCELLED", "task_id": task_id}), flush=True)
        return False


def _consume_resolution(state: Path, task_id: str) -> None:
    source = state / "blockers/resolutions" / f"{task_id}.json"
    if not source.exists():
        return
    target = state / "blockers/resolutions-consumed"
    target.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), target / f"{task_id}.{time.time_ns()}.json")


def _selected_tasks(inbox: Path, task_id: str | None) -> list[Path]:
    if task_id is not None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", task_id):
            raise ValueError("invalid task ID")
        candidate = inbox / f"{task_id}.json"
        return [candidate] if candidate.is_file() else []
    return sorted(path for path in inbox.glob("*.json") if path.is_file())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the bounded local Qwen developer queue")
    parser.add_argument("--task-id", default=None, help="Run exactly this queued task and leave the rest untouched")
    args = parser.parse_args([] if argv is None else argv)
    if args.task_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", args.task_id):
        parser.error("invalid task ID")
    repo = Path.cwd().resolve()
    state = repo / ".tim/local-first"
    lock_handle = _acquire_supervisor_lock(state)
    if lock_handle is None:
        print(json.dumps({
            "LOCAL_QWEN_BUILD_QUEUE": "BLOCKED",
            "reason": "another supervisor already holds WIP=1 lock",
            "wip": 1,
        }), file=sys.stderr, flush=True)
        return 2

    try:
        inbox = state / "developer-inbox"
        processed = state / "developer-processed"
        results = state / "developer-results"
        marker = state / "PATCH_SANDBOX_ALLOWED"
        if os.getenv("TIM_LOCAL_PATCH_SANDBOX") != "1" or not marker.exists():
            print("BLOCKED: local patch sandbox gate is closed", file=sys.stderr)
            return 2
        if not inbox.exists():
            print("BLOCKED: developer inbox missing", file=sys.stderr)
            return 2
        processed.mkdir(parents=True, exist_ok=True)
        results.mkdir(parents=True, exist_ok=True)
        issue = int(os.getenv("TIM_BLOCKER_ISSUE", str(DEFAULT_BLOCKER_ISSUE)))
        auto_wait = os.getenv("TIM_BLOCKER_AUTO_WAIT", "1") == "1"
        max_local_cycles = max(0, int(os.getenv("TIM_SUPERVISOR_MAX_LOCAL_REPAIR_CYCLES", str(DEFAULT_MAX_LOCAL_REPAIR_CYCLES))))

        tasks = _selected_tasks(inbox, args.task_id)
        initial_total = len(tasks)
        completed_count = 0
        if not tasks:
            print(json.dumps({"LOCAL_QWEN_BUILD_QUEUE": "IDLE", **_closure_metrics(0, 0, 0)}))
            return 0

        print(json.dumps({
            "LOCAL_QWEN_BUILD_QUEUE": "CLOSURE_MODE",
            "policy": "WIP_1_FINISH_CURRENT_TASK_BEFORE_NEXT",
            "acceptance_gate": "DETERMINISTIC_LOCAL_SUPERVISOR",
            "max_local_repair_cycles": max_local_cycles,
            **_closure_metrics(0, initial_total, initial_total),
        }), flush=True)

        for path in tasks:
            payload = json.loads(path.read_text(encoding="utf-8"))
            task_id = str(payload.get("task_id", path.stem))
            payload = _with_closure_policy(payload, task_id)
            _atomic_json(path, payload)
            try:
                persisted_cycle = int(
                    payload.get(
                        "supervisor_repair_cycle",
                        0,
                    )
                )
            except (TypeError, ValueError):
                persisted_cycle = 0

            local_repair_cycles = max(
                0,
                min(
                    persisted_cycle,
                    max_local_cycles,
                ),
            )

            prior_result_path = (
                results / f"{task_id}.json"
            )

            if (
                local_repair_cycles
                >= max_local_cycles
                and prior_result_path.exists()
            ):
                try:
                    prior_result = json.loads(
                        prior_result_path.read_text(
                            encoding="utf-8"
                        )
                    )
                except (
                    OSError,
                    json.JSONDecodeError,
                ):
                    prior_result = {}

                if (
                    _blocker_class(prior_result)
                    == "LOCAL_REPAIRABLE"
                ):
                    if _valid_external_resolution(
                        state,
                        task_id,
                    ):
                        print(
                            json.dumps(
                                {
                                    "LOCAL_QWEN_BUILD_QUEUE":
                                        "EXTERNAL_RESOLUTION_RESUME",
                                    "task_id": task_id,
                                    "cycle": local_repair_cycles,
                                    "max_cycles": max_local_cycles,
                                    "policy":
                                        "SAME_TASK_ONE_EXTERNAL_RETRY",
                                }
                            ),
                            flush=True,
                        )
                    else:
                        print(
                            json.dumps(
                                {
                                    "LOCAL_QWEN_BUILD_QUEUE":
                                        "LOCAL_REPAIR_BUDGET_EXHAUSTED",
                                    "task_id": task_id,
                                    "cycle": local_repair_cycles,
                                    "max_cycles": max_local_cycles,
                                    "policy":
                                        "WAIT_FOR_EXTERNAL_FALLBACK_SAME_TASK",
                                }
                            ),
                            flush=True,
                        )

                        _publish_blocker(
                            repo,
                            state,
                            payload,
                            prior_result,
                            issue,
                        )

                        return 2

            while True:
                print(json.dumps({
                    "LOCAL_QWEN_BUILD_QUEUE": "RUNNING",
                    "task_id": task_id,
                    "primary_goal": "CLOSE_CURRENT_TASK",
                    "wip": 1,
                    "local_repair_cycle": local_repair_cycles,
                }), flush=True)
                completed = subprocess.run(
                    [sys.executable, "scripts/run_local_qwen_developer.py", str(path), "--repo-root", str(repo)],
                    cwd=repo,
                    env=_child_env(repo),
                    text=True,
                    capture_output=True,
                    check=False,
                )
                if completed.stdout:
                    sys.stdout.write(completed.stdout)
                if completed.stderr:
                    sys.stderr.write(completed.stderr)
                result_path = results / f"{task_id}.json"
                result: dict[str, Any]
                if result_path.exists():
                    result = json.loads(result_path.read_text(encoding="utf-8"))
                else:
                    result = {
                        "status": "BLOCKED",
                        "reason": f"developer exited {completed.returncode} without durable result",
                        "next_action": "inspect local developer entrypoint",
                        "tests": {},
                    }

                if completed.returncode == 0 and result.get("status") == "VERIFYING":
                    acceptance = _acceptance_gate(repo, state, payload, result)
                    if acceptance["passed"]:
                        _consume_resolution(state, task_id)
                        shutil.move(str(path), processed / path.name)
                        completed_count += 1
                        remaining = initial_total - completed_count
                        print(json.dumps({
                            "LOCAL_QWEN_BUILD_QUEUE": "TASK_CLOSED",
                            "task_id": task_id,
                            "status": "FIXED",
                            "acceptance_gate": "PASS",
                            "evidence_sha256": acceptance["evidence_sha256"],
                            **_closure_metrics(completed_count, initial_total, remaining),
                        }), flush=True)
                        break
                    result = {
                        **result,
                        "status": "BLOCKED",
                        "reason": "LOCAL_ACCEPTANCE_FAILED:" + ",".join(acceptance["failed_checks"]),
                        "next_action": "REPAIR_AND_RESUME_SAME_TASK_DO_NOT_CREATE_SUBTASK",
                        "acceptance": acceptance,
                    }

                blocker_class = _blocker_class(result)
                if blocker_class == "LOCAL_REPAIRABLE" and local_repair_cycles < max_local_cycles:
                    local_repair_cycles += 1
                    payload["supervisor_repair_cycle"] = local_repair_cycles
                    payload["supervisor_repair_reason"] = _repair_feedback(result)
                    _atomic_json(path, payload)
                    print(json.dumps({
                        "LOCAL_QWEN_BUILD_QUEUE": "LOCAL_REPAIR_RETRY",
                        "task_id": task_id,
                        "cycle": local_repair_cycles,
                        "max_cycles": max_local_cycles,
                        "reason": _safe_text(result.get("reason", "unknown"), 1000),
                        "policy": "SAME_TASK_ONLY",
                    }), flush=True)
                    time.sleep(min(2 ** local_repair_cycles, 4))
                    continue

                print(json.dumps({
                    "LOCAL_QWEN_BUILD_QUEUE": "BLOCKED",
                    "task_id": task_id,
                    "status": result.get("status"),
                    "reason": result.get("reason"),
                    "blocker_class": blocker_class,
                    "next_action": result.get("next_action"),
                    "policy": "REPAIR_AND_RESUME_SAME_TASK_DO_NOT_CREATE_SUBTASK",
                }), flush=True)
                if result.get("external_resolution_used") is True:
                    _consume_resolution(state, task_id)
                published = _publish_blocker(repo, state, payload, result, issue)
                if not published or not auto_wait:
                    return 2
                if not _wait_for_resolution(repo, state, task_id, issue):
                    return 2
                local_repair_cycles = 0
                # Resume the exact same task. Internal implementation/checkpoint work must never
                # become new backlog items; local deterministic gates remain authoritative.

        print(json.dumps({
            "LOCAL_QWEN_BUILD_QUEUE": "PASS",
            "goal": "BACKLOG_REDUCED_BY_CLOSING_EXISTING_TASKS",
            "acceptance_gate": "PASS_FOR_ALL_CLOSED_TASKS",
            **_closure_metrics(completed_count, initial_total, 0),
        }), flush=True)
        return 0
    finally:
        _release_supervisor_lock(lock_handle)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
