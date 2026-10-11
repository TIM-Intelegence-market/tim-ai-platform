"""Pure, bounded selection and validation for GitHub-fed developer tasks."""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any

from src.local_first.patch_executor import FORBIDDEN_PATH_PARTS

TASK_BLOCK = re.compile(r"```json\s+TIM_QWEN_TASK_V1\s*\n(.*?)\n```", re.DOTALL)
REJECT_LABELS = {"blocked", "epic", "pr:open", "dependency:blocked"}


def _labels(issue: dict[str, Any]) -> set[str] | None:
    raw = issue.get("labels")
    if not isinstance(raw, list):
        return None
    names = [item.get("name") if isinstance(item, dict) else item for item in raw]
    if any(not isinstance(name, str) for name in names):
        return None
    return set(names)


def select_ready_issue(issues: Any) -> dict[str, Any] | None:
    """Choose one explicitly labelled, open, small issue with stable ordering."""
    if not isinstance(issues, list):
        return None
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for issue in issues:
        if not isinstance(issue, dict) or issue.get("state") != "open" or "pull_request" in issue:
            continue
        number = issue.get("number")
        if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
            continue
        labels = _labels(issue)
        if labels is None or labels & REJECT_LABELS or not {"agent:qwen-ready", "status:ready"} <= labels:
            continue
        priority = 0 if "priority:p0" in labels else 1 if "priority:p1" in labels else None
        if priority is not None:
            candidates.append((priority, number, issue))
    return min(candidates, key=lambda item: (item[0], item[1]))[2] if candidates else None


def _safe_python_path(value: Any) -> bool:
    if not isinstance(value, str) or not value.endswith(".py") or "\\" in value:
        return False
    path = PurePosixPath(value)
    return (not path.is_absolute() and path.as_posix() == value and len(path.parts) >= 2
            and path.parts[0] in {"src", "tests"}
            and all(part.lower() not in FORBIDDEN_PATH_PARTS and part not in {".", ".."}
                    for part in path.parts))


def build_task(issue: dict[str, Any]) -> dict[str, Any]:
    """Accept only a fenced, allowlisted A3 contract from the selected issue."""
    number = issue.get("number") if isinstance(issue, dict) else None
    if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        raise ValueError("invalid issue number")
    body = issue.get("body")
    match = TASK_BLOCK.search(body) if isinstance(body, str) else None
    if match is None or len(match.group(1)) > 12_000:
        raise ValueError("missing or oversized TIM_QWEN_TASK_V1 contract")
    try:
        task = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError("invalid TIM_QWEN_TASK_V1 JSON") from exc
    if not isinstance(task, dict):
        raise ValueError("task must be a JSON object")
    if (task.get("task_id") != f"github-issue-{number}" or task.get("issue_number") != number
            or task.get("risk") != "A3" or task.get("sandboxed") is not True):
        raise ValueError("invalid task identity or safety contract")
    allowed = task.get("allowed_paths")
    tests = task.get("tests")
    if (not isinstance(allowed, list) or not 1 <= len(allowed) <= 12
            or not isinstance(tests, list) or not 1 <= len(tests) <= 8
            or any(not _safe_python_path(path) for path in allowed + tests)
            or any(not path.startswith("tests/") for path in tests)
            or len(set(allowed)) != len(allowed) or len(set(tests)) != len(tests)):
        raise ValueError("invalid task file allowlist")
    objective = task.get("objective")
    if not isinstance(objective, str) or not objective.strip() or len(objective) > 4_000:
        raise ValueError("invalid task objective")
    return {"task_id": f"github-issue-{number}", "issue_number": number,
            "risk": "A3", "sandboxed": True, "objective": objective.strip(),
            "allowed_paths": allowed, "tests": tests}
