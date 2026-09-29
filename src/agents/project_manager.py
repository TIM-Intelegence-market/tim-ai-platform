"""Project Manager Agent V1: a deterministic, read-only TIM work-priority board.

Contract (Constitution Band 5, Master Prompt 09), declared in ``SPEC``:
- Mission: rank open GitHub issues and open-PR blockers in exactly one board issue.
- Reads: issues, issue comments, open pull requests, their check runs.
- Writes: only the one board issue (create once, then update). No labels,
  statuses, comments, merges, approvals, orders or other issue edits.
- Replay: the board is a pure function of a recorded snapshot. The board's
  timestamp is the snapshot's ``captured_at``, never the render time.
- Board identity: marker in the body AND exact board title AND an author from
  ``BOARD_AUTHORS``. Any other issue that merely quotes the marker is ordinary
  work and is never overwritten.

- Text directives (``STATUS: BLOCKED``, ``NEXT_ACTION=``, ``depends on #n``)
  count only when an author from ``trusted_authors`` wrote them (default: the
  repository owner). Anyone else's issue or comment text cannot steer the board;
  labels still apply.
- Every issue, PR and check text is escaped before it lands in the board, so
  it can neither break the Markdown nor mention (ping) anyone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Protocol

from src.agents.contract import AgentSpec, RunRecord, run_task

READ_SNAPSHOT = "read_github_snapshot"
BUILD_BOARD = "build_priority_board"
CREATE_BOARD = "create_priority_board_issue"
UPDATE_BOARD = "update_priority_board_issue"

SPEC = AgentSpec(
    name="project-manager",
    version="1.1.0",
    mission="Rank open TIM GitHub issues and open-PR blockers deterministically "
            "in exactly one priority board issue.",
    owner="uezeyiraydin-cell",
    allowed_actions=(READ_SNAPSHOT, BUILD_BOARD, CREATE_BOARD, UPDATE_BOARD),
    tools=("github_rest",),
    max_input_bytes=8 * 1024 * 1024,
    timeout_seconds=600,
)

SNAPSHOT_SCHEMA = "tim.priority_board.snapshot.v2"
BOARD_AUTHORS = ("github-actions[bot]",)
ISSUE_REFERENCE = re.compile(r"#(\d+)")
NEXT_ACTION = re.compile(r"(?:NEXT_SAFE_ACTION|NEXT_ACTION)\s*[=:]\s*([^\n`]+)", re.IGNORECASE)
# REST returns lowercase conclusions, GraphQL uppercase; compare case-insensitively.
FAILED_CONCLUSIONS = {"FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED"}
BLOCKED_TEXT = re.compile(r"(?:STATUS|STATE)\s*[=:]\s*(?:BLOCKED|SAFE_STOP)|\bBLOCKER\s*[=:]", re.IGNORECASE)


class PriorityAgentError(RuntimeError):
    """Raised when the agent cannot safely publish a priority board."""


class GitHubClient(Protocol):
    def list_issues(self, state: str = "open") -> list[dict[str, Any]]: ...

    def list_comments(self, number: int) -> list[dict[str, Any]]: ...

    def list_open_pull_requests(self) -> list[dict[str, Any]]: ...

    def create_issue(self, title: str, body: str) -> dict[str, Any]: ...

    def update_issue(self, number: int, body: str) -> dict[str, Any]: ...


def label_names(issue: Mapping[str, Any]) -> set[str]:
    return {label["name"] if isinstance(label, dict) else str(label) for label in issue.get("labels", [])}


def issue_body(issue: Mapping[str, Any], comments: Iterable[Mapping[str, Any]],
               trusted_authors: Iterable[str]) -> str:
    """Text that may carry directives: only what a trusted author wrote."""
    trusted = set(trusted_authors)
    parts = [issue.get("body") or ""] if issue.get("author") in trusted else []
    parts.extend(comment.get("body") or "" for comment in comments if comment.get("author") in trusted)
    return "\n".join(parts)


_MARKDOWN_SPECIAL = re.compile(r"([\\`*_\[\]<>#|~])")


def md(text: Any) -> str:
    """Render untrusted text inline: one line, Markdown escaped, no @-mentions."""
    flat = " ".join(str(text).split())
    return _MARKDOWN_SPECIAL.sub(r"\\\1", flat).replace("@", "@\u200b")


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


def classify_issue(issue: Mapping[str, Any], text: str, open_numbers: set[int]) -> PrioritizedIssue:
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


def render_pull_request_blockers(pull_requests: Iterable[Mapping[str, Any]]) -> list[str]:
    blockers: list[str] = []
    for pr in pull_requests:
        checks = pr.get("statusCheckRollup") or []
        failed = [check.get("name", "unbekannter Check") for check in checks if str(check.get("conclusion") or "").upper() in FAILED_CONCLUSIONS]
        if failed or pr.get("mergeable_state") in {"dirty", "unstable"}:
            detail = ", ".join(failed) if failed else f"Merge-Zustand: {pr.get('mergeable_state', 'unbekannt')}"
            blockers.append(f"- PR #{pr['number']} — {md(pr['title'])}: {md(detail)}")
    return blockers


def render_board(items: list[PrioritizedIssue], top_n: int, marker: str, timezone_label: str,
                 pull_requests: list[Mapping[str, Any]], *, generated_at: str) -> str:
    active = [item for item in items if item.status != "ARCHIVE"]
    top = active[:top_n]
    lines = [
        f"<!-- {marker} -->",
        "# TIM Priority Board",
        "",
        f"Aktualisiert: `{generated_at}` (Workflow-Zeit: UTC; Referenz: {timezone_label})",
        "",
        "> Dieser Bericht priorisiert nur. Er startet keine Arbeit und verändert keine Fach-Issues, Labels oder Status.",
        "",
        "## Top-Prioritäten",
    ]
    if top:
        for index, item in enumerate(top, start=1):
            deps = f" Abhängigkeiten: {', '.join(f'#{dep}' for dep in item.dependency_numbers)}." if item.dependency_numbers else ""
            lines.extend([f"{index}. **#{item.number} — {md(item.title)}** (`{item.status}`)", f"   - {item.reason}{deps}", f"   - Nächster sicherer Schritt: {md(item.action)}"])
    else:
        lines.append("Keine nicht-archivierten offenen Issues gefunden.")

    lines.extend(["", "## Warteschlange"])
    for status in ("NEXT", "READY", "WAITING", "BLOCKED"):
        group = [item for item in active if item.status == status]
        lines.extend(["", f"### {status}"])
        if group:
            lines.extend(f"- #{item.number} — {md(item.title)}: {item.reason}" for item in group)
        else:
            lines.append("- Keine Issues.")

    pr_blockers = render_pull_request_blockers(pull_requests)
    lines.extend(["", "## PR-Blocker"])
    lines.extend(pr_blockers or ["- Keine fehlgeschlagenen oder instabilen offenen PR-Checks gemeldet."])
    lines.extend(["", "## Archiv-Referenz", f"- {sum(item.status == 'ARCHIVE' for item in items)} archivierte bzw. Duplikat-Issues wurden nicht priorisiert."])
    return "\n".join(lines) + "\n"


def is_board(issue: Mapping[str, Any], config: Mapping[str, Any]) -> bool:
    return (config["marker"] in (issue.get("body") or "")
            and issue.get("title") == config["board_title"]
            and issue.get("author") in config["board_authors"])


def build_board(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Pure function of the snapshot: the replayable core of the agent."""
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise PriorityAgentError("Unbekanntes Snapshot-Schema; kein Board erzeugt.")
    config = snapshot["config"]
    issues = snapshot["issues"]
    # Closed issues only resolve dependencies; they are never ranked, and a
    # closed board is history, not the board to update.
    open_issues = [issue for issue in issues if issue["state"].lower() == "open"]
    boards = [issue for issue in open_issues if is_board(issue, config)]
    if len(boards) > 1:
        raise PriorityAgentError("Mehrdeutige Priority Boards gefunden; keine neue Issue wird erstellt oder überschrieben.")
    board_numbers = {issue["number"] for issue in boards}
    work = [issue for issue in open_issues if issue["number"] not in board_numbers]
    open_numbers = {issue["number"] for issue in work}
    comments = snapshot["comments"]
    items = sorted(
        (classify_issue(issue, issue_body(issue, comments.get(str(issue["number"]), []),
                                          config["trusted_authors"]), open_numbers)
         for issue in work),
        key=lambda item: item.score)
    board = render_board(items, config["top_n"], config["marker"], config["timezone_label"],
                         snapshot["pull_requests"], generated_at=snapshot["captured_at"])
    return {
        "board": board,
        "board_issue_number": boards[0]["number"] if boards else None,
        "top": [item.number for item in items if item.status != "ARCHIVE"][:config["top_n"]],
    }


def _issue_record(issue: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "number": int(issue["number"]),
        "title": issue["title"],
        "state": str(issue.get("state", "")),
        "labels": sorted(label_names(issue)),
        "body": issue.get("body") or "",
        "updated_at": issue.get("updated_at") or "",
        "author": (issue.get("user") or {}).get("login"),
    }


def _pull_request_record(pr: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "number": int(pr["number"]),
        "title": pr["title"],
        "mergeable_state": pr.get("mergeable_state"),
        "statusCheckRollup": [{"name": check.get("name"), "conclusion": check.get("conclusion")}
                              for check in pr.get("statusCheckRollup") or []],
    }


class PriorityAgent:
    def __init__(self, client: GitHubClient, board_title: str, marker: str, timezone_label: str,
                 top_n: int, *, board_authors: tuple[str, ...] = BOARD_AUTHORS,
                 repository: str = "", trusted_authors: Iterable[str] | None = None,
                 clock=None) -> None:
        self.client = client
        if trusted_authors is None:
            owner = repository.split("/", 1)[0] if "/" in repository else ""
            trusted_authors = (owner,) if owner else ()
        self.config = {"board_title": board_title, "marker": marker, "timezone_label": timezone_label,
                       "top_n": top_n, "board_authors": list(board_authors),
                       "trusted_authors": sorted({a for a in trusted_authors if a})}
        self.repository = repository
        self.clock = clock or (lambda: datetime.now(timezone.utc).replace(microsecond=0).isoformat())
        self.last_record: RunRecord | None = None

    def collect_snapshot(self) -> dict[str, Any]:
        SPEC.authorize(READ_SNAPSHOT)
        captured_at = self.clock()
        issues = sorted((_issue_record(issue) for issue in self.client.list_issues("all")
                         if "pull_request" not in issue), key=lambda issue: issue["number"])
        comments = {}
        for issue in issues:
            if issue["state"].lower() == "open" and not is_board(issue, self.config):
                comments[str(issue["number"])] = [{"body": comment.get("body") or "",
                                                   "author": (comment.get("user") or {}).get("login")}
                                                  for comment in self.client.list_comments(issue["number"])]
        pull_requests = sorted((_pull_request_record(pr) for pr in self.client.list_open_pull_requests()),
                               key=lambda pr: pr["number"])
        return {"schema": SNAPSHOT_SCHEMA, "repository": self.repository, "captured_at": captured_at,
                "config": self.config, "issues": issues, "comments": comments,
                "pull_requests": pull_requests}

    def run(self, *, dry_run: bool = False) -> tuple[int | None, str]:
        snapshot = self.collect_snapshot()
        record = run_task(SPEC, build_board, snapshot, action=BUILD_BOARD)
        self.last_record = record
        output = record.to_dict()["output"]
        board, board_number = output["board"], output["board_issue_number"]
        if dry_run:
            return board_number, board
        if board_number is None:
            SPEC.authorize(CREATE_BOARD)
            created = self.client.create_issue(self.config["board_title"], board)
            return int(created["number"]), board
        SPEC.authorize(UPDATE_BOARD)
        self.client.update_issue(board_number, board)
        return board_number, board
