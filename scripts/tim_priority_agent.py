#!/usr/bin/env python3
"""Publish a deterministic, read-only TIM work-priority board on GitHub."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ISSUE_REFERENCE = re.compile(r"#(\d+)")
NEXT_ACTION = re.compile(r"(?:NEXT_SAFE_ACTION|NEXT_ACTION)\s*[=:]\s*([^\n`]+)", re.IGNORECASE)
BLOCKED_TEXT = re.compile(r"(?:STATUS|STATE)\s*[=:]\s*(?:BLOCKED|SAFE_STOP)|\bBLOCKER\s*[=:]", re.IGNORECASE)


class PriorityAgentError(RuntimeError):
    """Raised when the agent cannot safely publish a priority board."""


class GitHubClient(Protocol):
    def list_issues(self, state: str = "open") -> list[dict[str, Any]]: ...

    def list_comments(self, number: int) -> list[dict[str, Any]]: ...

    def list_open_pull_requests(self) -> list[dict[str, Any]]: ...

    def create_issue(self, title: str, body: str) -> dict[str, Any]: ...

    def update_issue(self, number: int, body: str) -> dict[str, Any]: ...


class RestGitHubClient:
    def __init__(self, repository: str, token: str) -> None:
        self.repository = repository
        self.token = token

    def _request(self, path: str, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = Request(
            f"https://api.github.com{path}", data=data, method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                **({"Content-Type": "application/json"} if data else {}),
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, json.JSONDecodeError) as error:
            raise PriorityAgentError(f"GitHub API request failed for {method} {path}: {error}") from error

    def _paginate(self, path: str) -> list[dict[str, Any]]:
        # TIM currently has fewer than 100 issues/comments per source issue. A hard
        # page size keeps the agent deterministic and avoids accidental broad scans.
        return list(self._request(f"{path}{'&' if '?' in path else '?'}per_page=100"))

    def list_issues(self, state: str = "open") -> list[dict[str, Any]]:
        return self._paginate(f"/repos/{self.repository}/issues?state={state}")

    def list_comments(self, number: int) -> list[dict[str, Any]]:
        return self._paginate(f"/repos/{self.repository}/issues/{number}/comments")

    def list_open_pull_requests(self) -> list[dict[str, Any]]:
        pull_requests = self._paginate(f"/repos/{self.repository}/pulls?state=open")
        for pull_request in pull_requests:
            sha = pull_request["head"]["sha"]
            checks = self._request(
                f"/repos/{self.repository}/commits/{sha}/check-runs?per_page=100"
            ).get("check_runs", [])
            pull_request["statusCheckRollup"] = checks
        return pull_requests

    def create_issue(self, title: str, body: str) -> dict[str, Any]:
        return self._request(f"/repos/{self.repository}/issues", "POST", {"title": title, "body": body})

    def update_issue(self, number: int, body: str) -> dict[str, Any]:
        return self._request(f"/repos/{self.repository}/issues/{number}", "PATCH", {"body": body})


def label_names(issue: dict[str, Any]) -> set[str]:
    return {label["name"] if isinstance(label, dict) else str(label) for label in issue.get("labels", [])}


def issue_body(issue: dict[str, Any], comments: Iterable[dict[str, Any]]) -> str:
    return "\n".join([issue.get("body") or "", *(comment.get("body") or "" for comment in comments)])


def dependencies(text: str) -> set[int]:
    matches: set[int] = set()
    for line in text.splitlines():
        if re.search(r"\b(?:depends on|blocked by)\b", line, re.IGNORECASE):
            matches.update(int(number) for number in ISSUE_REFERENCE.findall(line))
    return matches


def next_action(text: str, fallback: str) -> str:
    found = NEXT_ACTION.findall(text)
    return found[-1].strip() if found else f"Issue prüfen und den nächsten sicheren Schritt festlegen: {fallback}"


@dataclass(frozen=True)
class PrioritizedIssue:
    number: int
    title: str
    status: str
    reason: str
    action: str
    dependency_numbers: tuple[int, ...]
    updated_at: str
    score: tuple[int, int, float, int]


def classify_issue(issue: dict[str, Any], text: str, open_numbers: set[int]) -> PrioritizedIssue:
    labels = label_names(issue)
    number = int(issue["number"])
    deps = tuple(sorted(dependencies(text)))
    archived = bool({"archive", "duplicate"} & labels)
    blocked = (
        archived
        or "status:waiting" in labels
        or "status:external-action" in labels
        or "ci-blocked" in labels
        or bool(BLOCKED_TEXT.search(text))
    )
    unresolved = tuple(dep for dep in deps if dep in open_numbers)
    p0 = "priority:p0" in labels or "p0" in labels
    active = "status:active" in labels
    ready = "status:ready" in labels

    if archived:
        status, reason, rank = "ARCHIVE", "Archiviert oder Duplikat; nur als Historie referenzieren.", 4
    elif blocked:
        status, reason, rank = "BLOCKED", "Expliziter Blocker, externer Schritt oder fehlgeschlagene Abnahme ist dokumentiert.", 3
    elif unresolved:
        status, reason, rank = "WAITING", f"Wartet auf offene Abhängigkeiten: {', '.join(f'#{dep}' for dep in unresolved)}.", 2
    elif p0 or active:
        status, reason, rank = "NEXT", "Aktiv bzw. P0 und ohne offene explizite Abhängigkeit.", 0
    elif ready:
        status, reason, rank = "READY", "Als bereit markiert und ohne offene explizite Abhängigkeit.", 1
    else:
        status, reason, rank = "READY", "Offen und ohne dokumentierte harte Abhängigkeit; vor Beginn anhand der Acceptance-Gates prüfen.", 1

    # Epics coordinate work but should not outrank executable child tasks at equal state.
    epic_penalty = 1 if "type:epic" in labels else 0
    try:
        freshness = -datetime.fromisoformat(issue.get("updated_at", "").replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        freshness = 0.0
    return PrioritizedIssue(
        number=number,
        title=issue["title"],
        status=status,
        reason=reason,
        action=next_action(text, issue["title"]),
        dependency_numbers=deps,
        updated_at=issue.get("updated_at", ""),
        score=(rank, epic_penalty, freshness, number),
    )


def render_pull_request_blockers(pull_requests: Iterable[dict[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for pr in pull_requests:
        checks = pr.get("statusCheckRollup") or []
        failed = [check.get("name", "unbekannter Check") for check in checks if check.get("conclusion") in {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED"}]
        if failed or pr.get("mergeable_state") in {"dirty", "unstable"}:
            detail = ", ".join(failed) if failed else f"Merge-Zustand: {pr.get('mergeable_state', 'unbekannt')}"
            blockers.append(f"- PR #{pr['number']} — {pr['title']}: {detail}")
    return blockers


def render_board(items: list[PrioritizedIssue], top_n: int, marker: str, timezone_label: str, pull_requests: list[dict[str, Any]]) -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    active = [item for item in items if item.status != "ARCHIVE"]
    top = active[:top_n]
    lines = [
        f"<!-- {marker} -->",
        "# TIM Priority Board",
        "",
        f"Aktualisiert: `{now}` (Workflow-Zeit: UTC; Referenz: {timezone_label})",
        "",
        "> Dieser Bericht priorisiert nur. Er startet keine Arbeit und verändert keine Fach-Issues, Labels oder Status.",
        "",
        "## Top-Prioritäten",
    ]
    if top:
        for index, item in enumerate(top, start=1):
            deps = f" Abhängigkeiten: {', '.join(f'#{dep}' for dep in item.dependency_numbers)}." if item.dependency_numbers else ""
            lines.extend([f"{index}. **#{item.number} — {item.title}** (`{item.status}`)", f"   - {item.reason}{deps}", f"   - Nächster sicherer Schritt: `{item.action}`"])
    else:
        lines.append("Keine nicht-archivierten offenen Issues gefunden.")

    lines.extend(["", "## Warteschlange"])
    for status in ("NEXT", "READY", "WAITING", "BLOCKED"):
        group = [item for item in active if item.status == status]
        lines.extend(["", f"### {status}"])
        if group:
            lines.extend(f"- #{item.number} — {item.title}: {item.reason}" for item in group)
        else:
            lines.append("- Keine Issues.")

    pr_blockers = render_pull_request_blockers(pull_requests)
    lines.extend(["", "## PR-Blocker"])
    lines.extend(pr_blockers or ["- Keine fehlgeschlagenen oder instabilen offenen PR-Checks gemeldet."])
    lines.extend(["", "## Archiv-Referenz", f"- {sum(item.status == 'ARCHIVE' for item in items)} archivierte bzw. Duplikat-Issues wurden nicht priorisiert."])
    return "\n".join(lines) + "\n"


class PriorityAgent:
    def __init__(self, client: GitHubClient, board_title: str, marker: str, timezone_label: str, top_n: int) -> None:
        self.client = client
        self.board_title = board_title
        self.marker = marker
        self.timezone_label = timezone_label
        self.top_n = top_n

    def run(self) -> tuple[int, str]:
        all_issues = [issue for issue in self.client.list_issues("all") if "pull_request" not in issue]
        boards = [issue for issue in all_issues if self.marker in (issue.get("body") or "")]
        if len(boards) > 1:
            raise PriorityAgentError("Mehrdeutige Priority Boards gefunden; keine neue Issue wird erstellt oder überschrieben.")

        work_issues = [issue for issue in all_issues if self.marker not in (issue.get("body") or "")]
        open_numbers = {int(issue["number"]) for issue in work_issues if issue.get("state", "").lower() == "open"}
        items = []
        for issue in work_issues:
            comments = self.client.list_comments(int(issue["number"])) if issue.get("state", "").lower() == "open" else []
            items.append(classify_issue(issue, issue_body(issue, comments), open_numbers))
        items.sort(key=lambda item: item.score)
        board = render_board(items, self.top_n, self.marker, self.timezone_label, self.client.list_open_pull_requests())

        if not boards:
            created = self.client.create_issue(self.board_title, board)
            return int(created["number"]), board
        board_number = int(boards[0]["number"])
        self.client.update_issue(board_number, board)
        return board_number, board


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"), required=not os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"), required=not os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--board-title", default=os.environ.get("PRIORITY_BOARD_TITLE", "TIM Priority Board"))
    parser.add_argument("--marker", default=os.environ.get("PRIORITY_BOARD_MARKER", "TIM_PRIORITY_BOARD_V1"))
    parser.add_argument("--timezone-label", default=os.environ.get("PRIORITY_TIMEZONE_LABEL", "Europe/Berlin"))
    parser.add_argument("--top-n", default=int(os.environ.get("TOP_N", "5")), type=int)
    args = parser.parse_args()
    try:
        board_number, board = PriorityAgent(
            RestGitHubClient(args.repository, args.token), args.board_title, args.marker, args.timezone_label, args.top_n
        ).run()
    except PriorityAgentError as error:
        print(f"Priority agent failed safely: {error}", file=sys.stderr)
        return 1
    print(f"Priority board updated: #{board_number}")
    print(board)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
