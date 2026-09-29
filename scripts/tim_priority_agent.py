#!/usr/bin/env python3
"""Publish a deterministic, read-only TIM work-priority board on GitHub.

Thin CLI around src/agents/project_manager.py (Project Manager Agent V1).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.agents.contract import ReplayMismatch, RunRecord, replay  # noqa: E402
from src.agents.project_manager import (  # noqa: E402,F401
    SPEC,
    GitHubClient,
    PriorityAgent,
    PriorityAgentError,
    build_board,
    classify_issue,
    render_board,
    render_pull_request_blockers,
)

PAGE_SIZE = 100
MAX_PAGES = 50


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
        # Follow pages until a short page arrives. Fail closed instead of truncating:
        # a partial scan would hide old issues or lose the existing board.
        separator = "&" if "?" in path else "?"
        items: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            batch = list(self._request(f"{path}{separator}per_page={PAGE_SIZE}&page={page}"))
            items.extend(batch)
            if len(batch) < PAGE_SIZE:
                return items
        raise PriorityAgentError(f"Mehr als {MAX_PAGES * PAGE_SIZE} Einträge für {path}; Abbruch statt Teilergebnis.")

    def list_issues(self, state: str = "open") -> list[dict[str, Any]]:
        return self._paginate(f"/repos/{self.repository}/issues?state={state}")

    def list_comments(self, number: int) -> list[dict[str, Any]]:
        return self._paginate(f"/repos/{self.repository}/issues/{number}/comments")

    def list_open_pull_requests(self) -> list[dict[str, Any]]:
        pull_requests = self._paginate(f"/repos/{self.repository}/pulls?state=open")
        for pull_request in pull_requests:
            # The list endpoint omits mergeable_state; only the single-PR endpoint returns it.
            details = self._request(f"/repos/{self.repository}/pulls/{pull_request['number']}")
            pull_request["mergeable_state"] = details.get("mergeable_state")
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


def replay_record(path: Path) -> int:
    try:
        record = RunRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))
        replay(SPEC, build_board, record)
    except (OSError, ValueError, KeyError, ReplayMismatch, PriorityAgentError) as error:
        print(f"Replay failed: {error}", file=sys.stderr)
        return 1
    print(f"Replay OK: output {record.output_hash}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument("--board-title", default=os.environ.get("PRIORITY_BOARD_TITLE", "TIM Priority Board"))
    parser.add_argument("--marker", default=os.environ.get("PRIORITY_BOARD_MARKER", "TIM_PRIORITY_BOARD_V1"))
    parser.add_argument("--timezone-label", default=os.environ.get("PRIORITY_TIMEZONE_LABEL", "Europe/Berlin"))
    parser.add_argument("--top-n", default=int(os.environ.get("TOP_N", "5")), type=int)
    parser.add_argument("--dry-run", action="store_true", help="build the board but write nothing to GitHub")
    parser.add_argument("--record-path", type=Path, help="write the replayable run record (snapshot + board) here")
    parser.add_argument("--replay", type=Path, metavar="RECORD", help="re-run a recorded snapshot offline and verify the board")
    args = parser.parse_args()
    if args.replay:
        return replay_record(args.replay)
    if not args.repository or not args.token:
        parser.error("--repository and --token (or GITHUB_REPOSITORY / GITHUB_TOKEN) are required")
    agent = PriorityAgent(
        RestGitHubClient(args.repository, args.token), args.board_title, args.marker,
        args.timezone_label, args.top_n, repository=args.repository,
    )
    try:
        board_number, board = agent.run(dry_run=args.dry_run)
    except PriorityAgentError as error:
        print(f"Priority agent failed safely: {error}", file=sys.stderr)
        return 1
    finally:
        if args.record_path and agent.last_record is not None:
            args.record_path.write_text(json.dumps(agent.last_record.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.dry_run:
        print(f"Dry run: no GitHub write (existing board: {board_number or 'none'})")
    else:
        print(f"Priority board updated: #{board_number}")
    print(board)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
