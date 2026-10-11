#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_REPO = "TIM-Intelegence-market/tim-ai-platform"
RESOLUTION_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _gh(argv: list[str], *, input_text: str | None = None) -> str:
    completed = subprocess.run(
        ["gh", *argv],
        input=input_text,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        # Never echo stderr here: auth tooling can include environment-specific detail.
        raise RuntimeError(f"gh command failed with exit code {completed.returncode}")
    return completed.stdout


def publish(request: Path, issue: int, repo: str, *, escalate: bool = False) -> None:
    payload = json.loads(request.read_text(encoding="utf-8"))
    if payload.get("kind") != "BLOCKER_REQUEST" or not payload.get("task_id"):
        raise ValueError("not a TIM BLOCKER_REQUEST")
    if not payload.get("blocker_reason") and payload.get("reason"):
        payload["blocker_reason"] = payload["reason"]
    if escalate:
        expected = os.getenv("TIM_QWEN_WORKER_LOGIN", "")
        if not expected or not os.getenv("GH_CONFIG_DIR"):
            raise RuntimeError("dedicated Qwen GitHub worker identity is not configured")
        actual = _gh(["api", "user", "--jq", ".login"]).strip()
        if actual.casefold() != expected.casefold():
            raise RuntimeError("GitHub login does not match the Qwen worker identity")
        permissions = json.loads(_gh(["api", f"repos/{repo}", "--jq", ".permissions"]))
        if permissions.get("admin") is not False or permissions.get("maintain") is not False:
            raise RuntimeError("Qwen worker GitHub permissions are too broad or unknown")
    body = (
        f"<!-- TIM_BLOCKER_REQUEST task_id={payload['task_id']} -->\n"
        "## TIM local blocker request\n"
        "Qwen/Ollama remains the primary worker. Claude may resolve this blocker through the bounded draft-PR pipeline.\n\n"
        "```json\n"
        f"{json.dumps(payload, indent=2, sort_keys=True)}\n"
        "```\n"
    )
    _gh(["issue", "comment", str(issue), "--repo", repo, "--body-file", "-"], input_text=body)
    if escalate:
        _gh(["issue", "edit", str(issue), "--repo", repo, "--add-label", "agent:escalate"])


def pull_resolution(task_id: str, issue: int, output: Path, repo: str) -> bool:
    owner, name = repo.split("/", 1)
    raw = _gh(["api", f"repos/{owner}/{name}/issues/{issue}/comments?per_page=100"])
    comments = json.loads(raw)
    marker = f"TIM_BLOCKER_RESOLVED task_id={task_id}"
    for comment in reversed(comments):
        body = str(comment.get("body", ""))
        if marker not in body:
            continue
        match = RESOLUTION_RE.search(body)
        if not match:
            continue
        payload: dict[str, Any] = json.loads(match.group(1))
        if payload.get("kind") != "BLOCKER_RESOLVED" or payload.get("task_id") != task_id:
            continue
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            temp = Path(handle.name)
        temp.replace(output)
        return True
    return False


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Optional GitHub bridge for TIM local blocker mailbox")
    root.add_argument("--repo", default=DEFAULT_REPO)
    commands = root.add_subparsers(dest="command", required=True)

    send = commands.add_parser("publish")
    send.add_argument("--request", required=True, type=Path)
    send.add_argument("--issue", required=True, type=int)
    send.add_argument("--escalate", action="store_true", help="Mark this task's own issue for Claude handoff.")

    pull = commands.add_parser("pull")
    pull.add_argument("--task-id", required=True)
    pull.add_argument("--issue", required=True, type=int)
    pull.add_argument("--output", required=True, type=Path)
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "publish":
        publish(args.request, args.issue, args.repo, escalate=args.escalate)
        return 0
    found = pull_resolution(args.task_id, args.issue, args.output, args.repo)
    return 0 if found else 3


if __name__ == "__main__":
    raise SystemExit(main())
