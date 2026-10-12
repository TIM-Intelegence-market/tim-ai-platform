"""Pure, bounded selection and validation for GitHub-fed developer tasks."""

from __future__ import annotations

import json
import re
from pathlib import PurePosixPath
from typing import Any

from src.local_first.patch_executor import FORBIDDEN_PATH_PARTS

TASK_BLOCK = re.compile(r"```json\s+TIM_QWEN_TASK_V1\s*\n(.*?)\n```", re.DOTALL)
REJECT_LABELS = {
    "blocked", "epic", "pr:open", "dependency:blocked", "type:epic",
    "status:blocked", "status:waiting", "agent:pr-open", "agent:blocked",
    "agent:analyzing", "agent:claude-running", "agent:escalate",
}
DEPENDENCY_LINE = re.compile(
    r"(?im)^.*\b(?:depends on|blocked by|blockiert durch|abhängig von)\b[^\n]*$"
)
ISSUE_REFERENCE = re.compile(r"#([1-9][0-9]*)")
PROTECTED_PREFIXES = (
    "src/database/", "src/tim_incident/", "src/orderflow/", "src/paper/",
    "src/market_data/", "src/data_ingestion/",
    # The worker's own gates, sandbox and model plumbing: it must never patch itself.
    "src/local_first/", "src/llm/",
)


def _labels(issue: dict[str, Any]) -> set[str] | None:
    raw = issue.get("labels")
    if not isinstance(raw, list):
        return None
    names = [item.get("name") if isinstance(item, dict) else item for item in raw]
    if any(not isinstance(name, str) for name in names):
        return None
    return set(names)


def select_ready_issue(issues: Any, *, only_number: int | None = None,
                       skip: set[int] | frozenset[int] = frozenset()) -> dict[str, Any] | None:
    """Choose one explicitly labelled, open, small issue with stable ordering."""
    if not isinstance(issues, list):
        return None
    open_numbers = {item.get("number") for item in issues if isinstance(item, dict)
                    and str(item.get("state", "")).lower() == "open"
                    and isinstance(item.get("number"), int) and not isinstance(item.get("number"), bool)}
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for issue in issues:
        if (not isinstance(issue, dict) or str(issue.get("state", "")).lower() != "open"
                or "pull_request" in issue):
            continue
        number = issue.get("number")
        if not isinstance(number, int) or isinstance(number, bool) or number <= 0:
            continue
        if (only_number is not None and number != only_number) or number in skip:
            continue
        labels = _labels(issue)
        if labels is None or labels & REJECT_LABELS or not {"agent:qwen-ready", "status:ready"} <= labels:
            continue
        body = issue.get("body")
        dependencies = {int(ref) for line in DEPENDENCY_LINE.findall(body or "")
                        for ref in ISSUE_REFERENCE.findall(line)} if isinstance(body, str) else set()
        if dependencies & open_numbers:
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
            and value != "src/__init__.py"
            and (path.parts[0] != "tests" or path.name.startswith("test_"))
            and not value.startswith(PROTECTED_PREFIXES)
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
    task_number = task.get("issue_number")
    if (task.get("task_id") != f"github-issue-{number}"
            or not isinstance(task_number, int) or isinstance(task_number, bool) or task_number != number
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
